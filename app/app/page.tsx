"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  type ChatResult,
  type DictionaryEntry,
  type Finding,
  type UploadResult,
  generateReport,
  listDatasets,
  streamChat,
  uploadDataset,
} from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Message {
  role: "user" | "assistant" | "status" | "error";
  content: string;
  result?: ChatResult;
}

interface Dataset {
  dataset_id: string;
  filename: string;
  rows: number;
  cols: number;
  dictionary: DictionaryEntry[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function EvidenceBadge({ status }: { status: string }) {
  const colours: Record<string, string> = {
    supported: "bg-emerald-100 text-emerald-700",
    partially_supported: "bg-yellow-100 text-yellow-700",
    insufficient_evidence: "bg-red-100 text-red-700",
    not_applicable: "bg-zinc-100 text-zinc-500",
  };
  const labels: Record<string, string> = {
    supported: "✓ Supported",
    partially_supported: "~ Partial",
    insufficient_evidence: "✗ Insufficient",
    not_applicable: "— N/A",
  };
  const cls = colours[status] ?? "bg-zinc-100 text-zinc-500";
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {labels[status] ?? status}
    </span>
  );
}

function FindingCard({ finding }: { finding: Finding }) {
  return (
    <div className="rounded-lg border border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 p-3 flex flex-col gap-1.5">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm leading-snug text-zinc-800 dark:text-zinc-200 flex-1">{finding.claim}</p>
        <EvidenceBadge status={finding.evidence_status} />
      </div>
      {finding.metric && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Metric: <span className="font-mono">{finding.metric}</span>
          {finding.evidence_id && (
            <> · Evidence: <span className="font-mono">{finding.evidence_id.slice(0, 8)}</span></>
          )}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function AppPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [activeDatasets, setActiveDatasets] = useState<string[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [reportLoading, setReportLoading] = useState(false);
  const [report, setReport] = useState<Record<string, string> | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load persisted datasets on mount
  useEffect(() => {
    listDatasets()
      .then((r) => {
        const loaded = r.datasets.map((d) => ({
          dataset_id: d.dataset_id,
          filename: d.version.source_filename,
          rows: d.version.row_count,
          cols: d.version.column_count,
          dictionary: [],
        }));
        setDatasets(loaded);
      })
      .catch(() => {});
  }, []);

  // Auto-scroll chat to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ---------------------------------------------------------------------------
  // Upload
  // ---------------------------------------------------------------------------

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      setUploading(true);
      try {
        const result: UploadResult = await uploadDataset(file);
        const ds: Dataset = {
          dataset_id: result.dataset_id,
          filename: result.version.source_filename,
          rows: result.version.row_count,
          cols: result.version.column_count,
          dictionary: result.dictionary_proposals,
        };
        setDatasets((prev) => [ds, ...prev.filter((d) => d.dataset_id !== ds.dataset_id)]);
        setActiveDatasets((prev) =>
          prev.includes(ds.dataset_id) ? prev : [...prev, ds.dataset_id]
        );
        setMessages((prev) => [
          ...prev,
          {
            role: "status",
            content: `✓ Uploaded "${file.name}" — ${result.version.row_count.toLocaleString()} rows, ${result.version.column_count} columns.`,
          },
        ]);
      } catch (err: unknown) {
        setMessages((prev) => [
          ...prev,
          { role: "error", content: `Upload error: ${String(err)}` },
        ]);
      } finally {
        setUploading(false);
        e.target.value = "";
      }
    },
    []
  );

  // ---------------------------------------------------------------------------
  // Chat
  // ---------------------------------------------------------------------------

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;
    if (activeDatasets.length === 0) {
      setMessages((prev) => [
        ...prev,
        { role: "error", content: "Select at least one dataset before asking a question." },
      ]);
      return;
    }

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);

    try {
      const stream = streamChat(text, activeDatasets, sessionId);
      let statusLine = "";

      for await (const event of stream) {
        if (event.type === "status_update") {
          statusLine = event.data;
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === "status") {
              return [...prev.slice(0, -1), { role: "status", content: statusLine }];
            }
            return [...prev, { role: "status", content: statusLine }];
          });
        } else if (event.type === "result") {
          // Remove trailing status message, add assistant answer
          setMessages((prev) => {
            const filtered = prev[prev.length - 1]?.role === "status" ? prev.slice(0, -1) : prev;
            return [
              ...filtered,
              { role: "assistant", content: event.data.answer, result: event.data },
            ];
          });
          setSessionId(event.data.session_id);
        } else if (event.type === "clarification_needed") {
          setMessages((prev) => {
            const filtered = prev[prev.length - 1]?.role === "status" ? prev.slice(0, -1) : prev;
            return [
              ...filtered,
              {
                role: "assistant",
                content: `I need some clarification:\n${event.data.questions.join("\n")}`,
              },
            ];
          });
        } else if (event.type === "error") {
          setMessages((prev) => {
            const filtered = prev[prev.length - 1]?.role === "status" ? prev.slice(0, -1) : prev;
            return [...filtered, { role: "error", content: `Error: ${event.data}` }];
          });
        }
      }
    } catch (err: unknown) {
      setMessages((prev) => [
        ...prev,
        { role: "error", content: `Request failed: ${String(err)}` },
      ]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, activeDatasets, sessionId]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // ---------------------------------------------------------------------------
  // Report
  // ---------------------------------------------------------------------------

  const handleGenerateReport = useCallback(async () => {
    if (!sessionId) return;
    setReportLoading(true);
    try {
      const res = await generateReport(sessionId);
      setReport(res.report);
    } catch (err: unknown) {
      setMessages((prev) => [
        ...prev,
        { role: "error", content: `Report error: ${String(err)}` },
      ]);
    } finally {
      setReportLoading(false);
    }
  }, [sessionId]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex h-screen overflow-hidden bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-50">
      {/* ------------------------------------------------------------------ */}
      {/* Sidebar                                                             */}
      {/* ------------------------------------------------------------------ */}
      <aside className="w-64 shrink-0 border-r border-zinc-100 dark:border-zinc-800 flex flex-col">
        {/* Header */}
        <div className="px-4 py-3 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
          <span className="font-semibold text-sm">Analyx</span>
          <Link href="/" className="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300">
            ← Home
          </Link>
        </div>

        {/* Upload */}
        <div className="px-4 py-3 border-b border-zinc-100 dark:border-zinc-800">
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="w-full rounded-lg border-2 border-dashed border-zinc-200 dark:border-zinc-700 py-3 text-xs text-zinc-500 dark:text-zinc-400 hover:border-zinc-400 dark:hover:border-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 transition-colors disabled:opacity-50"
          >
            {uploading ? "Uploading…" : "+ Upload CSV / Excel"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            className="hidden"
            onChange={handleFileChange}
          />
        </div>

        {/* Dataset list */}
        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
          <p className="text-[10px] uppercase tracking-wider text-zinc-400 px-1 mb-1">Datasets</p>
          {datasets.length === 0 && (
            <p className="text-xs text-zinc-400 px-1">No datasets yet.</p>
          )}
          {datasets.map((ds) => {
            const active = activeDatasets.includes(ds.dataset_id);
            return (
              <button
                key={ds.dataset_id}
                onClick={() =>
                  setActiveDatasets((prev) =>
                    active ? prev.filter((id) => id !== ds.dataset_id) : [...prev, ds.dataset_id]
                  )
                }
                className={`w-full text-left rounded-lg px-2.5 py-2 text-xs transition-colors ${
                  active
                    ? "bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900"
                    : "hover:bg-zinc-50 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300"
                }`}
              >
                <p className="font-medium truncate">{ds.filename}</p>
                <p className={`text-[10px] mt-0.5 ${active ? "text-zinc-300 dark:text-zinc-600" : "text-zinc-400"}`}>
                  {ds.rows.toLocaleString()} rows · {ds.cols} cols
                </p>
              </button>
            );
          })}
        </div>

        {/* Report button */}
        {sessionId && (
          <div className="px-4 py-3 border-t border-zinc-100 dark:border-zinc-800">
            <button
              onClick={handleGenerateReport}
              disabled={reportLoading}
              className="w-full rounded-lg bg-zinc-100 dark:bg-zinc-800 px-3 py-2 text-xs font-medium hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors disabled:opacity-50"
            >
              {reportLoading ? "Generating…" : "Generate Report"}
            </button>
          </div>
        )}
      </aside>

      {/* ------------------------------------------------------------------ */}
      {/* Main chat area                                                      */}
      {/* ------------------------------------------------------------------ */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex h-full items-center justify-center text-center">
              <div className="space-y-2">
                <p className="text-base font-medium text-zinc-700 dark:text-zinc-300">
                  Upload a dataset, then ask a question
                </p>
                <p className="text-sm text-zinc-400">
                  e.g. &ldquo;What was total revenue last quarter?&rdquo; or &ldquo;Why did sales decline in Q3?&rdquo;
                </p>
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i}>
              {/* Status pulse */}
              {msg.role === "status" && (
                <p className="text-xs text-zinc-400 dark:text-zinc-500 flex items-center gap-1.5">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-zinc-400 animate-pulse" />
                  {msg.content}
                </p>
              )}

              {/* Error */}
              {msg.role === "error" && (
                <div className="rounded-lg bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 px-3 py-2 text-sm text-red-700 dark:text-red-300">
                  {msg.content}
                </div>
              )}

              {/* User bubble */}
              {msg.role === "user" && (
                <div className="flex justify-end">
                  <div className="rounded-2xl rounded-tr-sm bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-4 py-2 max-w-[75%] text-sm">
                    {msg.content}
                  </div>
                </div>
              )}

              {/* Assistant answer */}
              {msg.role === "assistant" && (
                <div className="space-y-3 max-w-3xl">
                  {/* Answer text */}
                  <div className="rounded-2xl rounded-tl-sm bg-zinc-50 dark:bg-zinc-900 border border-zinc-100 dark:border-zinc-800 px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap">
                    {msg.content}
                  </div>

                  {/* Findings */}
                  {msg.result && msg.result.findings.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-xs font-medium text-zinc-500 uppercase tracking-wider">
                        Findings ({msg.result.findings.length})
                      </p>
                      {msg.result.findings.slice(0, 8).map((f) => (
                        <FindingCard key={f.id} finding={f} />
                      ))}
                    </div>
                  )}

                  {/* Tier / session meta */}
                  {msg.result && (
                    <p className="text-[10px] text-zinc-400 flex gap-3">
                      <span>Tier: <span className="font-mono">{msg.result.tier}</span></span>
                      <span>Session: <span className="font-mono">{msg.result.session_id.slice(0, 8)}</span></span>
                      <span>{msg.result.evidence.length} evidence records</span>
                    </p>
                  )}
                </div>
              )}
            </div>
          ))}

          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div className="border-t border-zinc-100 dark:border-zinc-800 px-4 py-3">
          <div className="flex gap-2 max-w-4xl mx-auto">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                activeDatasets.length === 0
                  ? "Upload and select a dataset first…"
                  : "Ask a question about your data…"
              }
              disabled={loading || activeDatasets.length === 0}
              rows={1}
              className="flex-1 resize-none rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-4 py-2.5 text-sm outline-none focus:border-zinc-400 dark:focus:border-zinc-500 disabled:opacity-50 placeholder:text-zinc-400 leading-relaxed"
            />
            <button
              onClick={sendMessage}
              disabled={loading || !input.trim() || activeDatasets.length === 0}
              className="rounded-xl bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-4 py-2 text-sm font-medium hover:bg-zinc-700 dark:hover:bg-zinc-300 transition-colors disabled:opacity-40"
            >
              {loading ? "…" : "Send"}
            </button>
          </div>
          <p className="text-[10px] text-center text-zinc-400 mt-1.5">
            Enter to send · Shift+Enter for new line
          </p>
        </div>
      </main>

      {/* ------------------------------------------------------------------ */}
      {/* Report panel (slides in on right when available)                   */}
      {/* ------------------------------------------------------------------ */}
      {report && (
        <aside className="w-96 shrink-0 border-l border-zinc-100 dark:border-zinc-800 flex flex-col overflow-hidden">
          <div className="px-4 py-3 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
            <span className="font-semibold text-sm">Report</span>
            <button
              onClick={() => setReport(null)}
              className="text-xs text-zinc-400 hover:text-zinc-600"
            >
              ✕ Close
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4 text-sm">
            {Object.entries(report)
              .filter(([k]) => k !== "session_id")
              .map(([key, val]) => (
                <div key={key}>
                  <h3 className="font-semibold text-xs uppercase tracking-wider text-zinc-500 mb-1">
                    {key.replace(/_/g, " ")}
                  </h3>
                  <p className="text-zinc-700 dark:text-zinc-300 text-xs leading-relaxed whitespace-pre-wrap">
                    {String(val) || "—"}
                  </p>
                </div>
              ))}
          </div>
        </aside>
      )}
    </div>
  );
}
