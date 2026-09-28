// Typed API client for the Analyx backend.
// All requests go through /api/* which Next.js rewrites to http://localhost:8000.

const BASE = "/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DatasetVersion {
  id: string;
  dataset_id: string;
  parquet_path: string;
  row_count: number;
  column_count: number;
  source_filename: string;
  file_size_bytes: number;
}

export interface DictionaryEntry {
  column: string;
  role: "date" | "measure" | "dimension" | "identifier" | "other";
  display_name: string | null;
  unit: string | null;
  currency_symbol: string | null;
  sample_values: unknown[];
}

export interface UploadResult {
  dataset_id: string;
  version: DatasetVersion;
  transformation_log: { step_type: string; description: string; rows_affected: number }[];
  dictionary_proposals: DictionaryEntry[];
}

export interface Finding {
  id: string;
  claim: string;
  claim_type: string;
  strength: string;
  metric: string | null;
  value: unknown;
  evidence_id: string | null;
  evidence_status: string;
  stale: boolean;
  depth: number;
}

export interface Evidence {
  id: string;
  metric: string | null;
  value: unknown;
  period: string | null;
  calculation: string | null;
  rows_used: number | null;
}

export interface Chart {
  id: string;
  chart_type: string;
  analytical_intent: string;
  vega_lite_spec: Record<string, unknown>;
  title: string | null;
}

export interface ChatResult {
  session_id: string;
  tier: string;
  answer: string;
  findings: Finding[];
  evidence: Evidence[];
  charts: Chart[];
  plan: unknown | null;
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------

export async function uploadDataset(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/datasets/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Upload failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function listDatasets(): Promise<{ datasets: { dataset_id: string; version: DatasetVersion }[] }> {
  const res = await fetch(`${BASE}/datasets`);
  if (!res.ok) throw new Error(`List failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Chat  (SSE stream)
// ---------------------------------------------------------------------------

export type SSEEvent =
  | { type: "status_update"; data: string }
  | { type: "result"; data: ChatResult }
  | { type: "clarification_needed"; data: { questions: string[] } }
  | { type: "error"; data: string }
  | { type: "done" };

export async function* streamChat(
  message: string,
  datasetIds: string[],
  sessionId?: string
): AsyncGenerator<SSEEvent> {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, datasets: datasetIds, session_id: sessionId ?? null }),
  });

  if (!res.ok || !res.body) {
    throw new Error(`Chat request failed: ${res.status} ${await res.text()}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6)) as SSEEvent;
        } catch {
          // skip malformed frames
        }
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export async function generateReport(sessionId: string) {
  const res = await fetch(`${BASE}/reports/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) throw new Error(`Report failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Analysis & Verification (Prove Finding, Inspect Rows)
// ---------------------------------------------------------------------------

export interface ProveResult {
  finding_id: string;
  matched: boolean;
  original_value: unknown;
  recomputed_value: unknown;
  tolerance: number;
  passed: boolean;
}

export async function proveFinding(sessionId: string, findingId: string): Promise<ProveResult> {
  const res = await fetch(`${BASE}/analysis/${sessionId}/findings/${findingId}/prove`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Prove failed: ${res.status}`);
  return res.json();
}

export interface FindingRowsResult {
  finding_id: string;
  rows: Record<string, unknown>[];
  filters_applied: Record<string, unknown>;
}

export async function getFindingRows(sessionId: string, findingId: string): Promise<FindingRowsResult> {
  const res = await fetch(`${BASE}/analysis/${sessionId}/findings/${findingId}/rows`);
  if (!res.ok) throw new Error(`Get finding rows failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Data Explorer (Rows, Quality, Dictionary)
// ---------------------------------------------------------------------------

export interface DatasetRowsResult {
  total_rows: number;
  page: number;
  page_size: number;
  rows: Record<string, unknown>[];
}

export async function getDatasetRows(
  datasetId: string,
  page = 1,
  pageSize = 50
): Promise<DatasetRowsResult> {
  const res = await fetch(`${BASE}/datasets/${datasetId}/rows?page=${page}&page_size=${pageSize}`);
  if (!res.ok) throw new Error(`Get dataset rows failed: ${res.status}`);
  return res.json();
}

export async function getDatasetQuality(datasetId: string) {
  const res = await fetch(`${BASE}/datasets/${datasetId}/quality`);
  if (!res.ok) throw new Error(`Get quality failed: ${res.status}`);
  return res.json();
}

export async function updateDictionary(datasetId: string, entries: DictionaryEntry[]) {
  const res = await fetch(`${BASE}/datasets/${datasetId}/dictionary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entries }),
  });
  if (!res.ok) throw new Error(`Update dictionary failed: ${res.status}`);
  return res.json();
}

export async function postClarificationAnswer(sessionId: string, answer: string) {
  const res = await fetch(`${BASE}/chat/${sessionId}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });
  if (!res.ok) throw new Error(`Post answer failed: ${res.status}`);
  return res.json();
}

