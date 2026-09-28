"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type ChatResult,
  type DictionaryEntry,
  type Finding,
  type Evidence,
  type Chart,
  type SSEEvent,
  type UploadResult,
  type ProveResult,
  type FindingRowsResult,
  type DatasetRowsResult,
  generateReport,
  listDatasets,
  streamChat,
  uploadDataset,
  proveFinding,
  getFindingRows,
  getDatasetRows,
  getDatasetQuality,
  updateDictionary,
  postClarificationAnswer,
} from "../lib/api";
import {
  Bot,
  Sparkles,
  Database,
  FileText,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Play,
  Eye,
  Download,
  RefreshCw,
  Layers,
  Table as TableIcon,
  BarChart3,
  ShieldCheck,
  Send,
  Upload,
  ChevronRight,
  ExternalLink,
  Activity,
  FileSpreadsheet,
  Check,
  HelpCircle,
  Cpu,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Message {
  role: "user" | "assistant" | "status" | "error";
  content: string;
  result?: ChatResult;
  statusUpdates?: string[];
  clarificationQuestions?: string[];
}

interface Dataset {
  dataset_id: string;
  filename: string;
  rows: number;
  cols: number;
  dictionary: DictionaryEntry[];
}

type TabType = "chat" | "explorer" | "report" | "audit";

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function AppPage() {
  const [activeTab, setActiveTab] = useState<TabType>("chat");
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [activeDatasets, setActiveDatasets] = useState<string[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>("");

  // Chat state
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [currentStep, setCurrentStep] = useState<string>("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [clarificationAnswer, setClarificationAnswer] = useState("");

  // Verification & Rows modal state
  const [provingId, setProvingId] = useState<string | null>(null);
  const [proofResults, setProofResults] = useState<Record<string, ProveResult>>({});
  const [inspectModal, setInspectModal] = useState<{
    open: boolean;
    findingId: string;
    loading: boolean;
    data: FindingRowsResult | null;
  }>({ open: false, findingId: "", loading: false, data: null });

  // Explorer state
  const [explorerRows, setExplorerRows] = useState<DatasetRowsResult | null>(null);
  const [explorerPage, setExplorerPage] = useState(1);
  const [explorerLoading, setExplorerLoading] = useState(false);
  const [qualityReport, setQualityReport] = useState<any>(null);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [editingDictionary, setEditingDictionary] = useState<DictionaryEntry[]>([]);
  const [dictSaving, setDictSaving] = useState(false);

  // Report state
  const [reportLoading, setReportLoading] = useState(false);
  const [report, setReport] = useState<Record<string, string> | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load datasets on mount
  const refreshDatasets = useCallback(async () => {
    try {
      const r = await listDatasets();
      const loaded: Dataset[] = r.datasets.map((d) => ({
        dataset_id: d.dataset_id,
        filename: d.version.source_filename,
        rows: d.version.row_count,
        cols: d.version.column_count,
        dictionary: [],
      }));
      setDatasets(loaded);
      if (loaded.length > 0 && activeDatasets.length === 0) {
        setActiveDatasets([loaded[0].dataset_id]);
        setSelectedDatasetId(loaded[0].dataset_id);
      }
    } catch (err) {
      console.error("Failed to load datasets", err);
    }
  }, [activeDatasets.length]);

  useEffect(() => {
    refreshDatasets();
  }, [refreshDatasets]);

  // Auto-scroll chat
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, currentStep]);

  // Load explorer data when selectedDatasetId changes
  useEffect(() => {
    if (!selectedDatasetId) return;

    setExplorerLoading(true);
    getDatasetRows(selectedDatasetId, explorerPage, 25)
      .then((res) => setExplorerRows(res))
      .catch((err) => console.error("Error loading rows", err))
      .finally(() => setExplorerLoading(false));

    setQualityLoading(true);
    getDatasetQuality(selectedDatasetId)
      .then((q) => setQualityReport(q))
      .catch((err) => console.error("Error loading quality", err))
      .finally(() => setQualityLoading(false));

    const cur = datasets.find((d) => d.dataset_id === selectedDatasetId);
    if (cur && cur.dictionary.length > 0) {
      setEditingDictionary(cur.dictionary);
    }
  }, [selectedDatasetId, explorerPage, datasets]);

  // ---------------------------------------------------------------------------
  // Upload Handler
  // ---------------------------------------------------------------------------

  const handleUploadFile = async (file: File) => {
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
      setActiveDatasets([ds.dataset_id]);
      setSelectedDatasetId(ds.dataset_id);
      setEditingDictionary(result.dictionary_proposals);

      setMessages((prev) => [
        ...prev,
        {
          role: "status",
          content: `✓ Ingested & vectorized "${file.name}" into Parquet (${result.version.row_count.toLocaleString()} rows, ${result.version.column_count} columns). Schema dictionary configured.`,
        },
      ]);
    } catch (err: unknown) {
      setMessages((prev) => [
        ...prev,
        { role: "error", content: `Upload error: ${String(err)}` },
      ]);
    } finally {
      setUploading(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleUploadFile(file);
    e.target.value = "";
  };

  // Quick Sample Loader
  const loadSampleDataset = async (samplePath: string, sampleName: string) => {
    try {
      setUploading(true);
      const response = await fetch(samplePath);
      const blob = await response.blob();
      const file = new File([blob], sampleName, { type: "text/csv" });
      await handleUploadFile(file);
    } catch (e) {
      console.error("Failed to load sample dataset", e);
    } finally {
      setUploading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Chat Execution
  // ---------------------------------------------------------------------------

  const sendMessage = async (promptOverride?: string) => {
    const text = (promptOverride || input).trim();
    if (!text || loading) return;
    if (activeDatasets.length === 0) {
      setMessages((prev) => [
        ...prev,
        { role: "error", content: "Please select or upload at least one dataset first." },
      ]);
      return;
    }

    if (!promptOverride) setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);
    setCurrentStep("Initializing multi-agent pipeline…");

    const statusList: string[] = [];

    try {
      const stream = streamChat(text, activeDatasets, sessionId);

      for await (const event of stream) {
        if (event.type === "status_update") {
          setCurrentStep(event.data);
          statusList.push(event.data);
        } else if (event.type === "result") {
          setCurrentStep("");
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              content: event.data.answer,
              result: event.data,
              statusUpdates: statusList,
            },
          ]);
          setSessionId(event.data.session_id);
        } else if (event.type === "clarification_needed") {
          setCurrentStep("");
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              content: "I need clarification to ensure accurate computational bounds:",
              clarificationQuestions: event.data.questions,
              statusUpdates: statusList,
            },
          ]);
        } else if (event.type === "error") {
          setCurrentStep("");
          setMessages((prev) => [
            ...prev,
            { role: "error", content: `Execution Error: ${event.data}` },
          ]);
        }
      }
    } catch (err: unknown) {
      setCurrentStep("");
      setMessages((prev) => [
        ...prev,
        { role: "error", content: `Pipeline request failed: ${String(err)}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const submitClarification = async () => {
    if (!sessionId || !clarificationAnswer.trim()) return;
    try {
      await postClarificationAnswer(sessionId, clarificationAnswer);
      const ans = clarificationAnswer;
      setClarificationAnswer("");
      sendMessage(ans);
    } catch (e) {
      console.error(e);
    }
  };

  // ---------------------------------------------------------------------------
  // Proof & Rows Inspection
  // ---------------------------------------------------------------------------

  const handleProveFinding = async (findingId: string) => {
    if (!sessionId) return;
    setProvingId(findingId);
    try {
      const res = await proveFinding(sessionId, findingId);
      setProofResults((prev) => ({ ...prev, [findingId]: res }));
    } catch (e) {
      console.error("Proof failed", e);
    } finally {
      setProvingId(null);
    }
  };

  const handleInspectRows = async (findingId: string) => {
    if (!sessionId) return;
    setInspectModal({ open: true, findingId, loading: true, data: null });
    try {
      const res = await getFindingRows(sessionId, findingId);
      setInspectModal({ open: true, findingId, loading: false, data: res });
    } catch (e) {
      setInspectModal({ open: true, findingId, loading: false, data: null });
    }
  };

  // ---------------------------------------------------------------------------
  // Report Generation
  // ---------------------------------------------------------------------------

  const handleGenerateReport = async () => {
    if (!sessionId) return;
    setReportLoading(true);
    try {
      const res = await generateReport(sessionId);
      setReport(res.report);
      setActiveTab("report");
    } catch (err: unknown) {
      console.error("Report failed", err);
    } finally {
      setReportLoading(false);
    }
  };

  const handleSaveDictionary = async () => {
    if (!selectedDatasetId || editingDictionary.length === 0) return;
    setDictSaving(true);
    try {
      await updateDictionary(selectedDatasetId, editingDictionary);
      refreshDatasets();
    } catch (e) {
      console.error("Failed to save dictionary", e);
    } finally {
      setDictSaving(false);
    }
  };

  // Current session evidence list from last message
  const lastResult = [...messages].reverse().find((m) => m.result)?.result;
  const currentEvidence: Evidence[] = lastResult?.evidence || [];

  return (
    <div className="flex h-screen overflow-hidden bg-[#07090e] text-slate-100 font-sans">
      {/* ------------------------------------------------------------------ */}
      {/* Sidebar                                                             */}
      {/* ------------------------------------------------------------------ */}
      <aside className="w-72 shrink-0 border-r border-slate-800/80 bg-[#0b0f19] flex flex-col justify-between">
        <div className="flex flex-col flex-1 min-h-0">
          {/* Logo & Platform Info */}
          <div className="px-5 py-4 border-b border-slate-800/80 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="h-8 w-8 rounded-lg bg-gradient-to-tr from-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                <Bot className="h-5 w-5 text-white" />
              </div>
              <div>
                <h1 className="text-sm font-bold tracking-tight text-white flex items-center gap-1.5">
                  Analyx
                  <span className="text-[10px] px-1.5 py-0.2 rounded bg-indigo-500/20 text-indigo-400 font-mono font-medium">
                    v1.0
                  </span>
                </h1>
                <p className="text-[11px] text-slate-400">Agentic Data Analyst</p>
              </div>
            </div>
          </div>

          {/* Quick Sample Dataset Cards */}
          <div className="p-4 border-b border-slate-800/80 bg-slate-900/30">
            <p className="text-[11px] uppercase tracking-wider font-semibold text-slate-400 mb-2 flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-cyan-400" />
              Quick-Start Samples
            </p>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() =>
                  loadSampleDataset("/samples/saas_revenue_metrics.csv", "saas_revenue_metrics.csv")
                }
                disabled={uploading}
                className="flex flex-col items-start p-2 rounded-lg border border-slate-700/60 bg-slate-800/50 hover:bg-indigo-950/40 hover:border-indigo-500/50 transition text-left group disabled:opacity-50"
              >
                <div className="flex items-center gap-1 text-[11px] font-medium text-slate-200 group-hover:text-indigo-300">
                  <FileSpreadsheet className="h-3 w-3 text-cyan-400" />
                  SaaS MRR
                </div>
                <span className="text-[10px] text-slate-400 mt-0.5">15 rows · 8 cols</span>
              </button>

              <button
                onClick={() =>
                  loadSampleDataset("/samples/ecommerce_sales.csv", "ecommerce_sales.csv")
                }
                disabled={uploading}
                className="flex flex-col items-start p-2 rounded-lg border border-slate-700/60 bg-slate-800/50 hover:bg-cyan-950/40 hover:border-cyan-500/50 transition text-left group disabled:opacity-50"
              >
                <div className="flex items-center gap-1 text-[11px] font-medium text-slate-200 group-hover:text-cyan-300">
                  <FileSpreadsheet className="h-3 w-3 text-cyan-400" />
                  E-Commerce
                </div>
                <span className="text-[10px] text-slate-400 mt-0.5">15 rows · 7 cols</span>
              </button>
            </div>
          </div>

          {/* Upload Button */}
          <div className="p-4 border-b border-slate-800/80">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="w-full flex items-center justify-center gap-2 rounded-lg border border-dashed border-indigo-500/40 bg-indigo-500/5 hover:bg-indigo-500/10 hover:border-indigo-400 py-2.5 text-xs font-medium text-indigo-300 transition-all disabled:opacity-50"
            >
              <Upload className="h-3.5 w-3.5" />
              {uploading ? "Ingesting Dataset…" : "Upload CSV or Excel"}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              className="hidden"
              onChange={handleFileChange}
            />
          </div>

          {/* Dataset Selector List */}
          <div className="flex-1 overflow-y-auto p-3 space-y-1.5 min-h-0">
            <div className="flex items-center justify-between px-2 mb-1">
              <span className="text-[11px] uppercase tracking-wider font-semibold text-slate-400">
                Active Datasets ({datasets.length})
              </span>
              <button
                onClick={refreshDatasets}
                title="Refresh datasets"
                className="text-slate-400 hover:text-slate-200"
              >
                <RefreshCw className="h-3 w-3" />
              </button>
            </div>

            {datasets.length === 0 && (
              <div className="text-center py-6 px-3 rounded-lg border border-slate-800/50 bg-slate-900/20">
                <Database className="h-6 w-6 text-slate-600 mx-auto mb-1.5" />
                <p className="text-xs text-slate-400 font-medium">No datasets loaded</p>
                <p className="text-[10px] text-slate-500 mt-0.5">Upload a CSV or choose a sample above.</p>
              </div>
            )}

            {datasets.map((ds) => {
              const isSelected = selectedDatasetId === ds.dataset_id;
              const isActive = activeDatasets.includes(ds.dataset_id);
              return (
                <div
                  key={ds.dataset_id}
                  onClick={() => {
                    setSelectedDatasetId(ds.dataset_id);
                    if (!activeDatasets.includes(ds.dataset_id)) {
                      setActiveDatasets((prev) => [...prev, ds.dataset_id]);
                    }
                  }}
                  className={`group relative p-2.5 rounded-lg border transition-all cursor-pointer ${
                    isSelected
                      ? "bg-slate-800/90 border-indigo-500/60 shadow-md shadow-indigo-950/30"
                      : "bg-slate-900/40 border-slate-800/60 hover:bg-slate-800/50 hover:border-slate-700"
                  }`}
                >
                  <div className="flex items-start justify-between gap-1.5">
                    <p className="text-xs font-semibold text-slate-200 truncate flex-1">
                      {ds.filename}
                    </p>
                    <span
                      onClick={(e) => {
                        e.stopPropagation();
                        setActiveDatasets((prev) =>
                          isActive
                            ? prev.filter((id) => id !== ds.dataset_id)
                            : [...prev, ds.dataset_id]
                        );
                      }}
                      className={`h-4 w-4 rounded flex items-center justify-center text-[9px] font-bold cursor-pointer transition ${
                        isActive
                          ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                          : "bg-slate-800 text-slate-500 border border-slate-700"
                      }`}
                      title={isActive ? "Included in analysis" : "Excluded from analysis"}
                    >
                      {isActive ? "✓" : "+"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-1.5 text-[10px] text-slate-400">
                    <span className="font-mono text-cyan-400">{ds.rows.toLocaleString()} rows</span>
                    <span>·</span>
                    <span className="font-mono">{ds.cols} cols</span>
                    <span>·</span>
                    <span className="text-[9px] px-1 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/60 font-mono">
                      Parquet
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Multi-Agent Architecture Badge */}
        <div className="p-3 border-t border-slate-800/80 bg-slate-900/50">
          <div className="flex items-center gap-2 text-[11px] text-slate-400 mb-1.5 font-medium">
            <Cpu className="h-3.5 w-3.5 text-indigo-400" />
            <span>Multi-Agent Engine</span>
          </div>
          <div className="flex items-center gap-1 text-[9px] text-slate-400 font-mono">
            <span className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700/60 text-indigo-300">
              Router
            </span>
            <span>→</span>
            <span className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700/60 text-cyan-300">
              Plan
            </span>
            <span>→</span>
            <span className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700/60 text-emerald-300">
              DuckDB
            </span>
            <span>→</span>
            <span className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700/60 text-purple-300">
              Verify
            </span>
          </div>
        </div>
      </aside>

      {/* ------------------------------------------------------------------ */}
      {/* Main Workspace Area                                                */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex-1 flex flex-col min-w-0 bg-[#080b11]">
        {/* Navigation Tabs Header */}
        <header className="h-14 border-b border-slate-800/80 bg-[#0b0f19]/80 backdrop-blur px-6 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-1 bg-slate-900/80 p-1 rounded-lg border border-slate-800">
            <button
              onClick={() => setActiveTab("chat")}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition ${
                activeTab === "chat"
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Bot className="h-3.5 w-3.5" />
              Investigation Chat
            </button>
            <button
              onClick={() => setActiveTab("explorer")}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition ${
                activeTab === "explorer"
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <TableIcon className="h-3.5 w-3.5" />
              Data Explorer & Dictionary
            </button>
            <button
              onClick={() => setActiveTab("report")}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition ${
                activeTab === "report"
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <FileText className="h-3.5 w-3.5" />
              10-Section Report
            </button>
            <button
              onClick={() => setActiveTab("audit")}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition ${
                activeTab === "audit"
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              Evidence Audit ({currentEvidence.length})
            </button>
          </div>

          {/* Right Header Status */}
          <div className="flex items-center gap-3">
            {sessionId && (
              <button
                onClick={handleGenerateReport}
                disabled={reportLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 hover:bg-indigo-500/20 text-xs font-medium transition disabled:opacity-50"
              >
                <FileText className="h-3.5 w-3.5" />
                {reportLoading ? "Synthesizing Report…" : "Generate Executive Report"}
              </button>
            )}
            <div className="h-2.5 w-2.5 rounded-full bg-emerald-500 animate-pulse" title="System Ready" />
          </div>
        </header>

        {/* ------------------------------------------------------------------ */}
        {/* VIEW 1: Investigation Chat                                         */}
        {/* ------------------------------------------------------------------ */}
        {activeTab === "chat" && (
          <div className="flex-1 flex flex-col min-h-0">
            {/* Messages Scroll Area */}
            <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
              {messages.length === 0 && (
                <div className="max-w-2xl mx-auto py-12 text-center">
                  <div className="h-16 w-16 mx-auto rounded-2xl bg-gradient-to-tr from-indigo-500/20 to-cyan-500/20 border border-indigo-500/30 flex items-center justify-center mb-4 shadow-xl shadow-indigo-500/10">
                    <Sparkles className="h-8 w-8 text-cyan-400" />
                  </div>
                  <h2 className="text-xl font-bold text-white mb-2">
                    Evidence-First Analytical Intelligence
                  </h2>
                  <p className="text-sm text-slate-400 max-w-md mx-auto mb-8">
                    Analyx executes real calculations with DuckDB, runs 3-layer claim validation, and produces verifiable findings with zero hallucinations.
                  </p>

                  {/* Suggestion Chips */}
                  <div className="text-left space-y-2 max-w-lg mx-auto">
                    <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                      Suggested Investigations:
                    </p>
                    <div className="grid grid-cols-1 gap-2">
                      {[
                        "What is the trend in MRR and which region has the highest performance?",
                        "Compare revenue and churn rate across different customer segments",
                        "Break down customer contribution and identify top growth drivers",
                        "Detect any outliers or anomalous departures in monthly metrics",
                      ].map((prompt, idx) => (
                        <button
                          key={idx}
                          onClick={() => sendMessage(prompt)}
                          disabled={loading || activeDatasets.length === 0}
                          className="flex items-center justify-between p-3 rounded-xl border border-slate-800 bg-slate-900/40 hover:bg-slate-800/60 hover:border-slate-700 transition text-left text-xs text-slate-300 group disabled:opacity-50"
                        >
                          <span>{prompt}</span>
                          <ChevronRight className="h-3.5 w-3.5 text-slate-500 group-hover:text-cyan-400 transition" />
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Chat Message List */}
              {messages.map((msg, i) => (
                <div key={i} className="max-w-3xl mx-auto">
                  {/* Status Bubble */}
                  {msg.role === "status" && (
                    <div className="flex items-center gap-2 py-1.5 px-3 rounded-lg bg-slate-900/60 border border-slate-800/80 text-xs text-slate-400">
                      <span className="h-2 w-2 rounded-full bg-cyan-400 animate-pulse" />
                      <span>{msg.content}</span>
                    </div>
                  )}

                  {/* Error Bubble */}
                  {msg.role === "error" && (
                    <div className="flex items-start gap-2 p-3 rounded-xl bg-red-950/40 border border-red-800/50 text-xs text-red-300">
                      <AlertTriangle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
                      <span>{msg.content}</span>
                    </div>
                  )}

                  {/* User Bubble */}
                  {msg.role === "user" && (
                    <div className="flex justify-end">
                      <div className="rounded-2xl rounded-tr-sm bg-gradient-to-r from-indigo-600 to-indigo-700 text-white px-5 py-3 text-sm shadow-md shadow-indigo-950/40 max-w-[80%] leading-relaxed">
                        {msg.content}
                      </div>
                    </div>
                  )}

                  {/* Assistant Bubble */}
                  {msg.role === "assistant" && (
                    <div className="space-y-4">
                      {/* Step Execution Log Accordion */}
                      {msg.statusUpdates && msg.statusUpdates.length > 0 && (
                        <div className="p-3 rounded-xl bg-slate-900/40 border border-slate-800 text-[11px] text-slate-400">
                          <p className="font-semibold text-slate-300 mb-1 flex items-center gap-1.5">
                            <Activity className="h-3.5 w-3.5 text-cyan-400" />
                            Agent Execution Timeline:
                          </p>
                          <div className="space-y-1 pl-4 border-l border-slate-800 mt-2">
                            {msg.statusUpdates.map((step, sIdx) => (
                              <div key={sIdx} className="flex items-center gap-1.5">
                                <span className="h-1.5 w-1.5 rounded-full bg-cyan-400" />
                                <span>{step}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Main Answer Card */}
                      <div className="rounded-2xl rounded-tl-sm bg-[#0d1322] border border-slate-800/90 p-5 shadow-lg shadow-black/20">
                        <div className="flex items-center gap-2 mb-3 pb-2 border-b border-slate-800/80 text-xs text-slate-400">
                          <Bot className="h-4 w-4 text-indigo-400" />
                          <span className="font-semibold text-slate-200">Analyx Synthesis</span>
                          {msg.result?.tier && (
                            <span className="ml-auto px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-mono text-[10px]">
                              {msg.result.tier} Tier
                            </span>
                          )}
                        </div>

                        <div className="text-sm leading-relaxed text-slate-200 whitespace-pre-wrap">
                          {msg.content}
                        </div>
                      </div>

                      {/* Clarification Needed Form */}
                      {msg.clarificationQuestions && msg.clarificationQuestions.length > 0 && (
                        <div className="p-4 rounded-xl border border-amber-500/30 bg-amber-950/20 space-y-3">
                          <p className="text-xs font-semibold text-amber-300 flex items-center gap-1.5">
                            <HelpCircle className="h-4 w-4 text-amber-400" />
                            Clarification Required by Planner:
                          </p>
                          <ul className="text-xs text-amber-200/80 list-disc list-inside space-y-1">
                            {msg.clarificationQuestions.map((q, qIdx) => (
                              <li key={qIdx}>{q}</li>
                            ))}
                          </ul>
                          <div className="flex gap-2">
                            <input
                              type="text"
                              value={clarificationAnswer}
                              onChange={(e) => setClarificationAnswer(e.target.value)}
                              placeholder="Provide clarifying scope or dimensions…"
                              className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 outline-none focus:border-amber-400"
                            />
                            <button
                              onClick={submitClarification}
                              className="px-3 py-1.5 rounded-lg bg-amber-500 text-slate-900 font-semibold text-xs hover:bg-amber-400 transition"
                            >
                              Submit Answer
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Findings Cards */}
                      {msg.result && msg.result.findings.length > 0 && (
                        <div className="space-y-3">
                          <p className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                            <ShieldCheck className="h-4 w-4 text-emerald-400" />
                            Evidence-Backed Findings ({msg.result.findings.length})
                          </p>
                          <div className="grid grid-cols-1 gap-3">
                            {msg.result.findings.map((f) => {
                              const proof = proofResults[f.id];
                              const isProving = provingId === f.id;

                              return (
                                <div
                                  key={f.id}
                                  className="rounded-xl border border-slate-800 bg-[#0b0f1a] p-4 space-y-3 shadow-md hover:border-slate-700 transition"
                                >
                                  <div className="flex items-start justify-between gap-3">
                                    <div className="space-y-1 flex-1">
                                      <div className="flex items-center gap-2">
                                        <span
                                          className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                                            f.evidence_status === "supported"
                                              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                                              : f.evidence_status === "partially_supported"
                                              ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                                              : "bg-rose-500/10 text-rose-400 border-rose-500/30"
                                          }`}
                                        >
                                          {f.evidence_status === "supported"
                                            ? "✓ Supported"
                                            : f.evidence_status === "partially_supported"
                                            ? "~ Partial"
                                            : "✗ Insufficient"}
                                        </span>
                                        {f.metric && (
                                          <span className="text-[11px] font-mono text-cyan-400">
                                            metric: {f.metric}
                                          </span>
                                        )}
                                      </div>
                                      <p className="text-sm font-medium text-slate-100">{f.claim}</p>
                                    </div>
                                  </div>

                                  {/* Verification Actions */}
                                  <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-800/80 text-xs">
                                    {/* Prove Button */}
                                    <button
                                      onClick={() => handleProveFinding(f.id)}
                                      disabled={isProving}
                                      className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 text-indigo-300 font-medium transition disabled:opacity-50"
                                    >
                                      <Play className="h-3 w-3" />
                                      {isProving ? "Recomputing…" : "Prove Finding"}
                                    </button>

                                    {/* Inspect Backing Rows */}
                                    <button
                                      onClick={() => handleInspectRows(f.id)}
                                      className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-750 border border-slate-700 text-slate-300 font-medium transition"
                                    >
                                      <Eye className="h-3 w-3" />
                                      Inspect DuckDB Rows
                                    </button>

                                    {f.evidence_id && (
                                      <span className="text-[10px] text-slate-500 font-mono ml-auto">
                                        Evidence ID: {f.evidence_id.slice(0, 8)}
                                      </span>
                                    )}
                                  </div>

                                  {/* Proof Result Display */}
                                  {proof && (
                                    <div
                                      className={`p-2.5 rounded-lg text-xs font-mono border ${
                                        proof.passed
                                          ? "bg-emerald-950/30 border-emerald-500/40 text-emerald-300"
                                          : "bg-rose-950/30 border-rose-500/40 text-rose-300"
                                      }`}
                                    >
                                      <div className="flex items-center justify-between">
                                        <span>
                                          {proof.passed ? "✓ Verification Passed" : "✗ Verification Failed"}
                                        </span>
                                        <span className="text-[10px] text-slate-400">
                                          Tolerance: {proof.tolerance}
                                        </span>
                                      </div>
                                      <div className="mt-1 text-[11px] text-slate-300">
                                        Original: <span className="text-white">{String(proof.original_value)}</span> ·
                                        Recomputed: <span className="text-cyan-300">{String(proof.recomputed_value)}</span> ·
                                        Matched: {proof.matched ? "Yes" : "No"}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {/* Charts Section */}
                      {msg.result && msg.result.charts.length > 0 && (
                        <div className="space-y-3">
                          <p className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                            <BarChart3 className="h-4 w-4 text-cyan-400" />
                            Visual Analytics ({msg.result.charts.length})
                          </p>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            {msg.result.charts.map((c) => (
                              <div
                                key={c.id}
                                className="rounded-xl border border-slate-800 bg-[#0b0f1a] p-4 space-y-2"
                              >
                                <div className="flex items-center justify-between">
                                  <h4 className="text-xs font-semibold text-slate-200">
                                    {c.title || "Metric Distribution"}
                                  </h4>
                                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                                    {c.chart_type}
                                  </span>
                                </div>
                                <div className="h-32 flex items-end gap-2 pt-4 px-2 border-b border-slate-800/80">
                                  {/* Simulated responsive Vega chart representation */}
                                  <div className="flex-1 h-3/4 bg-gradient-to-t from-indigo-600 to-cyan-400 rounded-t opacity-80" />
                                  <div className="flex-1 h-full bg-gradient-to-t from-indigo-600 to-cyan-400 rounded-t" />
                                  <div className="flex-1 h-1/2 bg-gradient-to-t from-indigo-600 to-cyan-400 rounded-t opacity-70" />
                                  <div className="flex-1 h-4/5 bg-gradient-to-t from-indigo-600 to-cyan-400 rounded-t opacity-90" />
                                </div>
                                <p className="text-[10px] text-slate-500 font-mono truncate">
                                  Analytical intent: {c.analytical_intent}
                                </p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}

              {/* In-Flight Status Indicator */}
              {loading && currentStep && (
                <div className="max-w-3xl mx-auto flex items-center gap-3 p-3.5 rounded-xl bg-slate-900/80 border border-indigo-500/30 shadow-lg text-xs text-indigo-300 animate-pulse">
                  <div className="h-2 w-2 rounded-full bg-cyan-400" />
                  <span className="font-medium">{currentStep}</span>
                </div>
              )}

              <div ref={bottomRef} />
            </div>

            {/* Input Bar */}
            <div className="p-4 border-t border-slate-800/80 bg-[#0b0f19]/90 backdrop-blur">
              <div className="max-w-3xl mx-auto flex gap-2">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      sendMessage();
                    }
                  }}
                  placeholder={
                    activeDatasets.length === 0
                      ? "Upload or select a dataset on the left to begin…"
                      : "Ask an analytical question (e.g. 'What is the trend in MRR and which region drove it?')"
                  }
                  disabled={loading || activeDatasets.length === 0}
                  rows={2}
                  className="flex-1 bg-slate-900/90 border border-slate-700/80 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50 resize-none transition leading-relaxed disabled:opacity-50"
                />
                <button
                  onClick={() => sendMessage()}
                  disabled={loading || !input.trim() || activeDatasets.length === 0}
                  className="self-end px-5 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm transition shadow-lg shadow-indigo-600/20 disabled:opacity-40 flex items-center gap-2"
                >
                  <Send className="h-4 w-4" />
                  Send
                </button>
              </div>
              <p className="text-[10px] text-slate-500 text-center mt-2">
                Analyx uses strictly associational language and verifiable DuckDB computations. Enter to send, Shift+Enter for newline.
              </p>
            </div>
          </div>
        )}

        {/* ------------------------------------------------------------------ */}
        {/* VIEW 2: Data Explorer & Dictionary                                 */}
        {/* ------------------------------------------------------------------ */}
        {activeTab === "explorer" && (
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <Database className="h-5 w-5 text-indigo-400" />
                  Dataset Explorer & Semantic Dictionary
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Inspect raw converted Parquet data, quality integrity checks, and column role classifications.
                </p>
              </div>
            </div>

            {/* Quality Scorecard */}
            {qualityReport && (
              <div className="rounded-xl border border-slate-800 bg-[#0b0f1a] p-4 space-y-3">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-emerald-400" />
                  Data Quality & Integrity Assessment
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800">
                    <span className="text-[10px] text-slate-400">Total Records</span>
                    <p className="text-lg font-bold font-mono text-white">
                      {explorerRows?.total_rows?.toLocaleString() || "—"}
                    </p>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800">
                    <span className="text-[10px] text-slate-400">Duplicate Rows</span>
                    <p className="text-lg font-bold font-mono text-emerald-400">
                      {qualityReport.duplicate_count ?? 0}
                    </p>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800">
                    <span className="text-[10px] text-slate-400">Quality Status</span>
                    <p className="text-lg font-bold font-mono text-cyan-400">
                      {qualityReport.passed ? "PASSED" : "REVIEW"}
                    </p>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800">
                    <span className="text-[10px] text-slate-400">Storage Engine</span>
                    <p className="text-lg font-bold font-mono text-indigo-300">
                      Apache Parquet
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Column Role Dictionary */}
            <div className="rounded-xl border border-slate-800 bg-[#0b0f1a] p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                  <Layers className="h-4 w-4 text-cyan-400" />
                  Semantic Layer & Role Definitions
                </h3>
                <button
                  onClick={handleSaveDictionary}
                  disabled={dictSaving}
                  className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition disabled:opacity-50"
                >
                  {dictSaving ? "Saving…" : "Save Dictionary"}
                </button>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-slate-800 text-slate-400 font-medium">
                    <tr>
                      <th className="py-2 px-3">Column Name</th>
                      <th className="py-2 px-3">Assigned Role</th>
                      <th className="py-2 px-3">Unit / Currency</th>
                      <th className="py-2 px-3">Sample Values</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 text-slate-300">
                    {editingDictionary.map((entry, idx) => (
                      <tr key={idx} className="hover:bg-slate-900/40">
                        <td className="py-2 px-3 font-mono font-semibold text-white">
                          {entry.column}
                        </td>
                        <td className="py-2 px-3">
                          <select
                            value={entry.role}
                            onChange={(e) => {
                              const val = e.target.value as any;
                              setEditingDictionary((prev) =>
                                prev.map((item, i) => (i === idx ? { ...item, role: val } : item))
                              );
                            }}
                            className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 outline-none"
                          >
                            <option value="measure">Measure (Metric)</option>
                            <option value="dimension">Dimension (Category)</option>
                            <option value="date">Date / Timestamp</option>
                            <option value="identifier">Identifier / Key</option>
                          </select>
                        </td>
                        <td className="py-2 px-3">
                          <input
                            type="text"
                            value={entry.unit || ""}
                            onChange={(e) => {
                              const val = e.target.value;
                              setEditingDictionary((prev) =>
                                prev.map((item, i) => (i === idx ? { ...item, unit: val } : item))
                              );
                            }}
                            placeholder="e.g. $, %, kg"
                            className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 w-24 outline-none"
                          />
                        </td>
                        <td className="py-2 px-3 font-mono text-[11px] text-slate-400 truncate max-w-xs">
                          {entry.sample_values ? entry.sample_values.slice(0, 3).join(", ") : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Paginated Row Viewer */}
            <div className="rounded-xl border border-slate-800 bg-[#0b0f1a] p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                  <TableIcon className="h-4 w-4 text-indigo-400" />
                  Raw Data Preview (Page {explorerPage})
                </h3>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setExplorerPage((p) => Math.max(1, p - 1))}
                    disabled={explorerPage <= 1 || explorerLoading}
                    className="px-2 py-1 rounded bg-slate-800 text-xs text-slate-300 disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => setExplorerPage((p) => p + 1)}
                    disabled={
                      explorerLoading ||
                      !explorerRows ||
                      explorerRows.rows.length < explorerRows.page_size
                    }
                    className="px-2 py-1 rounded bg-slate-800 text-xs text-slate-300 disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>

              {explorerLoading ? (
                <div className="py-8 text-center text-xs text-slate-400">Loading DuckDB records…</div>
              ) : explorerRows && explorerRows.rows.length > 0 ? (
                <div className="overflow-x-auto max-h-96">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-slate-800 text-slate-400 font-mono sticky top-0 bg-[#0b0f1a]">
                      <tr>
                        {Object.keys(explorerRows.rows[0]).map((key) => (
                          <th key={key} className="py-2 px-3 whitespace-nowrap">
                            {key}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono text-[11px] text-slate-300">
                      {explorerRows.rows.map((row, rIdx) => (
                        <tr key={rIdx} className="hover:bg-slate-900/50">
                          {Object.values(row).map((val, cIdx) => (
                            <td key={cIdx} className="py-1.5 px-3 whitespace-nowrap">
                              {String(val ?? "")}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="py-6 text-center text-xs text-slate-500">No rows returned.</div>
              )}
            </div>
          </div>
        )}

        {/* ------------------------------------------------------------------ */}
        {/* VIEW 3: 10-Section Executive Report                                 */}
        {/* ------------------------------------------------------------------ */}
        {activeTab === "report" && (
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <div className="flex items-center justify-between pb-4 border-b border-slate-800">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <FileText className="h-5 w-5 text-indigo-400" />
                  10-Section Professional Analytical Report
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Full executive report formatted according to analytical specification standards.
                </p>
              </div>

              {sessionId && (
                <div className="flex items-center gap-2">
                  <a
                    href={`/api/reports/${sessionId}/markdown`}
                    download
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Download Markdown
                  </a>
                  <a
                    href={`/api/reports/${sessionId}/html`}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition shadow-md"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    Download HTML
                  </a>
                </div>
              )}
            </div>

            {!report ? (
              <div className="text-center py-16 space-y-3">
                <FileText className="h-10 w-10 text-slate-600 mx-auto" />
                <h3 className="text-sm font-semibold text-slate-300">No Report Generated Yet</h3>
                <p className="text-xs text-slate-500 max-w-sm mx-auto">
                  Run an analytical investigation in the chat view first, then click "Generate Executive Report".
                </p>
                {sessionId && (
                  <button
                    onClick={handleGenerateReport}
                    disabled={reportLoading}
                    className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-500 transition"
                  >
                    {reportLoading ? "Generating 10 Sections…" : "Generate Report Now"}
                  </button>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 max-w-4xl mx-auto">
                {[
                  { key: "executive_summary", title: "1. Executive Summary" },
                  { key: "dataset_overview", title: "2. Dataset Overview" },
                  { key: "key_findings", title: "3. Key Findings" },
                  { key: "detailed_analysis", title: "4. Detailed Analysis" },
                  { key: "anomalies", title: "5. Anomalies & Outliers" },
                  { key: "data_quality", title: "6. Data Quality Assessment" },
                  { key: "assumptions_definitions", title: "7. Assumptions & Metric Definitions" },
                  { key: "limitations", title: "8. Limitations & Observational Caveats" },
                  { key: "next_steps", title: "9. Next Steps & Recommended Actions" },
                  {
                    key: "methodology_reproducibility",
                    title: "10. Methodology & Reproducibility Metadata",
                  },
                ].map(({ key, title }) => (
                  <div
                    key={key}
                    className="rounded-xl border border-slate-800 bg-[#0b0f1a] p-5 space-y-2 shadow-sm"
                  >
                    <h3 className="text-xs font-bold uppercase tracking-wider text-cyan-400">
                      {title}
                    </h3>
                    <div className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">
                      {report[key] || "—"}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ------------------------------------------------------------------ */}
        {/* VIEW 4: Evidence Audit Trail                                       */}
        {/* ------------------------------------------------------------------ */}
        {activeTab === "audit" && (
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <div>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <ShieldCheck className="h-5 w-5 text-indigo-400" />
                Computational Evidence Audit Trail
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Every finding generated in Analyx is tied to an immutable Evidence Record backed by DuckDB execution hashes.
              </p>
            </div>

            {currentEvidence.length === 0 ? (
              <div className="py-16 text-center text-xs text-slate-500">
                No evidence records generated in this session yet.
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-3 max-w-4xl mx-auto">
                {currentEvidence.map((ev) => (
                  <div
                    key={ev.id}
                    className="rounded-xl border border-slate-800 bg-[#0b0f1a] p-4 space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-white font-mono">
                        Evidence Record: {ev.id}
                      </span>
                      <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-mono">
                        DuckDB Verified
                      </span>
                    </div>

                    <div className="text-xs text-slate-300">
                      Metric: <span className="font-mono text-cyan-300">{ev.metric || "N/A"}</span> ·
                      Value: <span className="font-mono text-white">{String(ev.value ?? "N/A")}</span> ·
                      Rows Used: <span className="font-mono text-indigo-300">{ev.rows_used ?? "N/A"}</span>
                    </div>

                    {ev.calculation && (
                      <div className="p-2.5 rounded bg-slate-900 border border-slate-800 font-mono text-[11px] text-slate-400 break-all">
                        {ev.calculation}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Inspect Backing DuckDB Rows Modal                                  */}
      {/* ------------------------------------------------------------------ */}
      {inspectModal.open && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-6">
          <div className="w-full max-w-4xl bg-[#0b0f1a] border border-slate-800 rounded-2xl p-6 shadow-2xl flex flex-col max-h-[85vh]">
            <div className="flex items-center justify-between pb-4 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <TableIcon className="h-5 w-5 text-cyan-400" />
                <h3 className="text-sm font-bold text-white">
                  Backing DuckDB Rows for Finding
                </h3>
              </div>
              <button
                onClick={() => setInspectModal({ open: false, findingId: "", loading: false, data: null })}
                className="text-slate-400 hover:text-white text-xs px-2 py-1 rounded bg-slate-800"
              >
                ✕ Close
              </button>
            </div>

            <div className="flex-1 overflow-y-auto py-4 space-y-4">
              {inspectModal.loading ? (
                <div className="py-12 text-center text-xs text-slate-400 animate-pulse">
                  Querying filtered parquet records from DuckDB…
                </div>
              ) : inspectModal.data && inspectModal.data.rows.length > 0 ? (
                <>
                  <div className="text-xs text-slate-400">
                    Showing <span className="font-bold text-white">{inspectModal.data.rows.length}</span> rows backing this computation.
                  </div>
                  <div className="overflow-x-auto border border-slate-800 rounded-lg">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-900 border-b border-slate-800 font-mono text-slate-400">
                        <tr>
                          {Object.keys(inspectModal.data.rows[0]).map((col) => (
                            <th key={col} className="p-2 whitespace-nowrap">
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60 font-mono text-[11px] text-slate-300">
                        {inspectModal.data.rows.map((row, rIdx) => (
                          <tr key={rIdx} className="hover:bg-slate-900/50">
                            {Object.values(row).map((val, cIdx) => (
                              <td key={cIdx} className="p-2 whitespace-nowrap">
                                {String(val ?? "")}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <div className="py-8 text-center text-xs text-slate-500">
                  No filtered rows available for this finding.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
