# Analyx

> **AI-powered analytical intelligence platform that transforms raw data into validated, evidence-based insights through a multi-agent system.**

Built for the **BOBathon Hackathon** 🏆

---

## 📌 Table of Contents

- [Overview](#overview)
- [How I Used IBM Bob in My Development Process](#how-i-used-ibm-bob-in-my-development-process)
- [Architecture](#architecture)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Endpoints](#api-endpoints)
- [How It Works](#how-it-works)

---

## Overview

**Analyx** is a full-stack analytical intelligence platform that lets users upload datasets (CSV, Excel) and ask natural-language questions about their data. Instead of returning simple answers, Analyx runs a rigorous multi-agent analysis pipeline that produces **evidence-backed findings**, **validated claims**, and **professional reports** — complete with reproducibility metadata and data quality checks.

The system is designed around the principle that **every insight must have traceable evidence**. No hallucinated numbers, no causal overstatement — just validated, associational analysis.

---

## How I Used IBM Bob in My Development Process

IBM Bob was my **AI coding partner across every phase of this project** — from whiteboard architecture to production bug fixes. Below is a concrete, honest account of what Bob did and how I interacted with it.

---

### 🧠 Phase 1 — Architecture Design

The project started with a single design question: *"How do you build a data analysis system where every answer is provably correct?"* I brought this to Bob in Plan mode before writing a single line of code.

Through a series of conversational prompts, Bob helped me work out:

- **The 5-agent pipeline** — Router → Planner → Analyst → Validator → Reporter. Bob challenged me on the responsibility boundaries between agents and helped define clear data contracts between them. The result is the [`agents/`](insight-os/backend/agents/) directory.
- **The tiered budget system** — Rather than routing every question through the heaviest pipeline, Bob suggested classifying requests into four tiers (Lookup / Analysis / Investigation / Report), each with calibrated compute limits (`max_tool_calls`, `max_llm_tokens`, `target_latency_s`). This concept shaped the entire [`router.py`](insight-os/backend/agents/router.py) and the [`Budget`](insight-os/backend/models/core.py) model.
- **Evidence as a first-class domain object** — Bob helped me realise that `Evidence` needed to be a proper Pydantic model with its own ID, not just a log entry. Every `Finding` links back to a traceable `Evidence` record. This is baked into [`models/core.py`](insight-os/backend/models/core.py).

---

### 💻 Phase 2 — Backend Code Generation

Bob generated substantial portions of the backend through targeted prompts. Here is what was built, module by module:

#### `agents/router.py`
I described the routing logic in plain English. Bob produced the keyword-heuristic regex patterns (`_LOOKUP_SIGNALS`, `_INVESTIGATION_SIGNALS`, `_REPORT_SIGNALS`) and the `TIER_BUDGETS` dictionary. I reviewed and added edge-case handling for long free-text questions that fall through the keyword checks.

#### `agents/analysis_agent.py`
The `AnalysisAgent` is the core orchestrator. Bob scaffolded the `AgentResult` and `IntentResult` dataclasses, the async `run()` method, and the 11-step execution flow. The `status_updates` list (used to stream live progress to the frontend) was a Bob suggestion I accepted after discussion.

#### `validators/language_lint.py`
I explained: *"LLMs overstate causation — we need to catch phrases like 'caused' or 'led to' and rewrite them to associational language."* Bob produced the full `CAUSAL_PATTERNS` list and `ASSOCIATIONAL_REWRITES` dictionary (e.g. `"caused"` → `"is associated with"`, `"due to"` → `"coinciding with"`) and the `_match_case` helper to preserve sentence capitalisation.

#### `models/core.py`
I described the conceptual hierarchy — sessions contain findings, findings contain evidence — and Bob generated the complete Pydantic model file with 15+ types and a rich enum hierarchy (`ClaimType`, `ClaimStrength`, `EvidenceStatus`, `SufficiencyVerdict`).

#### `tools/` — Analytical Toolkit
Bob generated the scaffolding and initial implementations for: `analysis_engine.py`, `chart_builder.py`, `data_profiler.py`, `data_quality.py`, `statistics.py`, `evidence.py`, `join_checker.py`, `ingest.py`, `sufficiency.py`, and `python_executor.py`. For each I described the inputs, outputs, and key operations; Bob wrote the implementation I then refined.

#### `services/llm_client.py` and `services/session_store.py`
Bob built the LLM abstraction layer supporting OpenAI and Anthropic with automatic system prompt injection and graceful offline fallback. The `SessionStore` combining in-memory cache with SQLite persistence was also Bob-generated.

---

### 🔄 Phase 3 — Iterative Refinement

Development was a continuous dialogue:

1. I described a requirement or showed a failing behaviour
2. Bob generated or revised code
3. I reviewed, tested, raised edge cases ("What if the LLM returns malformed JSON?", "What if the uploaded file has no header row?")
4. Bob added fallback logic, extended error handling, or proposed an alternative

**A concrete example:** the `ClaimStrength` enum was originally a boolean `is_strong`. Through a conversation about how the language linter should behave differently for speculative vs. moderate claims, Bob refactored it into a four-value enum that now drives the linting logic in [`language_lint.py`](insight-os/backend/validators/language_lint.py).

---

### 🐛 Phase 4 — Bug Hunting and Fixes

During the cleanup and testing phase I asked Bob to read through the entire codebase and identify bugs. Bob found and fixed six issues in a single pass:

| Bug | File | What Bob Found |
|---|---|---|
| **Dummy `Finding` object for version ID** | `agents/analysis_agent.py` | `_run_insight_tree` was constructing a throwaway `Finding(id="", ...)` object just to call `.id` on it as a fallback — replaced with a proper `.get()` guard |
| **Deprecated `@app.on_event`** | `api/main.py` | FastAPI 0.111 deprecates the old event hook; Bob rewrote it as a proper `@asynccontextmanager` lifespan function |
| **Dead window-function SQL** | `tools/data_quality.py` | `SELECT COUNT(*) - COUNT(*) OVER () + COUNT(DISTINCT *)` executes but its result was immediately discarded; removed |
| **`IndexError` on empty history** | `agents/analysis_agent.py` | `session.conversation_history[-1]` was called before history was appended, crashing on the first message |
| **`int(str(i))` on pandas index** | `tools/ingest.py` | `_detect_header_row` cast the index via `str()` first — works for `RangeIndex` but raises `ValueError` for any other index type |
| **Unused list comprehension** | `tools/statistics.py` | `safe_col` was built from a single-item dict and never read; removed |

---

### 🌐 Phase 5 — Frontend UI (Bob-built end to end)

The entire Next.js frontend workspace was built by Bob. I described the workflow I wanted and Bob wrote all of it:

#### `app/lib/api.ts` — Typed API Client
Bob designed a clean async fetch client with:
- `uploadDataset()` — multipart POST
- `listDatasets()` — restore persisted datasets on load
- `streamChat()` — async generator that parses the SSE stream, yielding typed events (`status_update`, `result`, `clarification_needed`, `error`, `done`)
- `generateReport()` — triggers the 10-section report

#### `app/app/page.tsx` — Full Workspace UI
Bob built the complete single-page workspace:
- **Sidebar** — drag-and-drop style upload button, dataset list with active/inactive toggle (click to include/exclude from context), session-aware "Generate Report" button
- **Chat area** — streaming status pulses while the pipeline runs, user/assistant message bubbles, finding cards with colour-coded evidence status badges (✓ Supported / ~ Partial / ✗ Insufficient), tier and session metadata
- **Report panel** — slides in on the right when generated, shows all 10 sections, closeable

#### `next.config.ts` — API Proxy
Bob added a rewrite rule to proxy `/api/:path*` → `http://localhost:8000/:path*`, eliminating all CORS configuration from both sides.

---

### 🔒 Phase 6 — Project Cleanup

Bob also handled repository hygiene as a dedicated task:
- Rewrote `.gitignore` from a single `node_modules` line to a comprehensive file covering Python virtualenvs, `__pycache__`, `.env`, build output, runtime data files, and macOS `.DS_Store`
- Removed `.DS_Store` from git tracking
- Consolidated `insight-os/.gitignore` into the root
- Deleted unused default Next.js SVGs from `public/`
- Added `insight-os/backend/.venv/**` to ESLint's ignore list (it was scanning thousands of venv JS files)
- Caught and removed `SYSTEM_STATUS.md` from a commit after noticing it contained a live API key

---

### 🛠 Bob Features Used

| Bob Feature | How It Was Used |
|---|---|
| **Plan mode** | Designing the multi-agent architecture and data model hierarchy before any code was written |
| **Agent mode (code generation)** | Generating full module implementations from natural-language descriptions across 20+ files |
| **Codebase-wide analysis** | Reading every file in the project to find bugs — Bob traced the full call graph rather than just checking isolated snippets |
| **Iterative refinement** | Evolving generated code through follow-up prompts and edge-case discussion |
| **Debugging** | Pasting error traces and receiving targeted, context-aware fixes with explanations |
| **Documentation generation** | Generating docstrings, inline section headers, and this README |
| **Repository cleanup** | Auditing git state, fixing `.gitignore`, removing tracked artefacts |

---

### Impact

Bob allowed me to **build a production-quality analytical platform in hackathon time**. The most valuable aspect was not raw code generation speed — it was having a design partner that held the full context of the system, challenged architectural decisions, caught bugs I would have missed, and maintained consistency across a codebase spanning 5 agents, 11 tools, 4 validators, 2 services, and 15+ domain types.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Next.js Frontend                  │
│         (React 19 + Tailwind CSS + SSE client)      │
│  Upload │ Chat │ Findings │ Evidence │ Report panel  │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP/REST + SSE (/api/* proxy)
┌──────────────────────▼──────────────────────────────┐
│                   FastAPI Backend                    │
│  ┌───────────┐ ┌──────────┐ ┌────────┐ ┌─────────┐ │
│  │ /datasets │ │  /chat   │ │/analysis│ │/reports │ │
│  └───────────┘ └──────────┘ └────────┘ └─────────┘ │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                Multi-Agent Pipeline                  │
│                                                      │
│  ┌────────┐   ┌─────────┐   ┌──────────┐            │
│  │ Router │──▶│ Planner │──▶│ Analyst  │            │
│  │(Tier)  │   │ (Plan)  │   │(Execute) │            │
│  └────────┘   └─────────┘   └────┬─────┘            │
│                                  │                  │
│                ┌─────────────────▼────────────┐     │
│                │      Validation Layer        │     │
│                │  Language │ Recompute │ Status│     │
│                └─────────────────┬────────────┘     │
│                                  │                  │
│                         ┌────────▼────────┐         │
│                         │  Report Agent   │         │
│                         │  (10-section)   │         │
│                         └─────────────────┘         │
└──────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                  Tools & Services                    │
│  Analysis Engine │ Data Profiler │ Chart Builder     │
│  Statistics      │ DuckDB/Parquet│ Semantic Layer    │
│  Data Quality    │ Join Checker  │ Python Executor   │
└──────────────────────────────────────────────────────┘
```

---

## Key Features

- **Natural Language Data Analysis** — Ask questions about your data in plain English
- **Multi-Agent Pipeline** — Router → Planner → Analyst → Validator → Reporter
- **Tiered Request Budget** — Automatically classifies questions into 4 tiers (Lookup, Analysis, Investigation, Report) with calibrated compute budgets
- **Evidence-Based Insights** — Every finding is backed by a traceable evidence record with computation details
- **3-Layer Validation**:
  - **Language Lint** — Catches causal overstatement and rewrites to associational language
  - **Numerical Recomputation** — Independently re-derives findings to verify correctness
  - **Evidence Status Scoring** — Grades claims as supported, partially supported, or insufficient
- **Insight Tree** — Recursive "why?" exploration that decomposes findings by dimension (depth-bounded)
- **Professional Reports** — Auto-generated 10-section analytical reports (Executive Summary, Key Findings, Anomalies, Methodology, etc.)
- **Multi-Format Ingestion** — CSV, Excel, with automatic encoding detection, header inference, and total-row removal
- **DuckDB-Powered Analytics** — Fast in-process SQL for aggregations and statistical operations
- **Vega-Lite Charts** — Auto-generated chart specs matched to analytical intent
- **Full-Stack UI** — React chat interface with SSE streaming, evidence status badges, and report panel
- **Triple LLM Support** — OpenAI, Anthropic, or Google Gemini via configurable provider

---

## Tech Stack

### Frontend
| Technology     | Purpose                          |
|----------------|----------------------------------|
| Next.js 16     | React framework + API proxy      |
| React 19       | UI library                       |
| Tailwind CSS 4 | Styling                          |
| TypeScript     | Type safety                      |

### Backend
| Technology              | Purpose                      |
|-------------------------|------------------------------|
| FastAPI                 | API framework + SSE          |
| Python 3.11+            | Runtime                      |
| DuckDB                  | In-process analytics engine  |
| Pandas / NumPy          | Data manipulation            |
| SciPy / Scikit-learn    | Statistical analysis         |
| PyArrow / Parquet       | Columnar data storage        |
| OpenAI / Anthropic / Gemini SDK | LLM providers        |
| Pydantic                | Data validation & models     |
| SQLite (aiosqlite)      | Session + dataset persistence |

---

## Project Structure

```
bobathon/
├── app/                        # Next.js frontend
│   ├── app/
│   │   └── page.tsx            # Full workspace UI (upload, chat, findings, report)
│   ├── lib/
│   │   └── api.ts              # Typed fetch client (SSE streaming, upload, report)
│   ├── page.tsx                # Root — renders the workspace
│   ├── layout.tsx              # Root layout + metadata
│   └── globals.css             # Global styles
│
├── public/
│   └── samples/                # Sample CSV datasets for testing
│       ├── ecommerce_sales.csv
│       └── saas_revenue_metrics.csv
│
├── insight-os/backend/         # Python backend
│   ├── api/                    # FastAPI routes
│   │   ├── main.py             # App entrypoint, CORS, lifespan
│   │   ├── datasets.py         # Dataset upload & management
│   │   ├── chat.py             # Conversational analysis (SSE stream)
│   │   ├── analysis.py         # Findings, evidence, prove endpoints
│   │   └── reports.py          # Report generation & export
│   │
│   ├── agents/                 # Multi-agent system
│   │   ├── router.py           # Request tier classification
│   │   ├── planner.py          # Analysis plan generation
│   │   ├── analysis_agent.py   # Core analysis orchestrator
│   │   ├── report_agent.py     # 10-section report generation
│   │   └── validator.py        # LLM semantic review
│   │
│   ├── tools/                  # Analytical tools
│   │   ├── analysis_engine.py  # Core computation engine (DuckDB)
│   │   ├── chart_builder.py    # Vega-Lite chart generation
│   │   ├── data_profiler.py    # Dataset profiling
│   │   ├── data_quality.py     # Data quality checks
│   │   ├── statistics.py       # Statistical analysis
│   │   ├── semantic_layer.py   # Metric resolution
│   │   ├── sufficiency.py      # Data sufficiency checks
│   │   ├── ingest.py           # File ingestion pipeline
│   │   ├── evidence.py         # Evidence management
│   │   ├── join_checker.py     # Multi-dataset join analysis
│   │   └── python_executor.py  # Sandboxed code execution
│   │
│   ├── validators/             # Validation pipeline
│   │   ├── language_lint.py    # Causal language detection & rewrite
│   │   ├── number_lint.py      # Numerical accuracy checks
│   │   ├── recompute.py        # Finding recomputation
│   │   └── evidence_status.py  # Evidence status scoring
│   │
│   ├── models/
│   │   └── core.py             # Pydantic domain models (15+ types)
│   │
│   ├── services/
│   │   ├── llm_client.py       # LLM abstraction (OpenAI/Anthropic/Gemini)
│   │   └── session_store.py    # Session + dataset persistence (SQLite)
│   │
│   ├── data/                   # Runtime data storage (gitignored)
│   │   ├── uploads/
│   │   └── parquet/
│   │
│   ├── requirements.txt
│   └── .env.example
│
├── next.config.ts              # Next.js config with /api/* → backend proxy
├── package.json
└── README.md
```

---

## Getting Started

### Prerequisites

- **Node.js** 18+
- **Python** 3.11+
- **API key** for OpenAI, Anthropic, or Google Gemini

### 1. Clone the repository

```bash
git clone <repository-url>
cd bobathon
```

### 2. Set up the frontend

```bash
npm install
```

### 3. Set up the backend

```bash
cd insight-os/backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `insight-os/backend/.env` with your provider and key:

```env
# Choose one provider:
LLM_PROVIDER=openai          # or "anthropic" or "gemini"

OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# GEMINI_API_KEY=AIza...

STRONG_MODEL=gpt-4o          # gemini-1.5-pro  |  claude-3-5-sonnet-20241022
FAST_MODEL=gpt-4o-mini       # gemini-1.5-flash |  claude-3-haiku-20240307
```

> **No API key?** The system runs in offline/heuristic mode — the pipeline still executes, computes evidence, and validates findings; only the LLM narrative generation is replaced with deterministic templates.

### 5. Run the application

**Terminal 1 — Backend:**

```bash
cd insight-os/backend
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
```

**Terminal 2 — Frontend:**

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) — you'll land directly in the workspace.

---

## API Endpoints

| Method | Endpoint                                      | Description                                  |
|--------|-----------------------------------------------|----------------------------------------------|
| GET    | `/health`                                     | Health check                                 |
| POST   | `/datasets/upload`                            | Upload a CSV or Excel file                   |
| GET    | `/datasets`                                   | List all registered datasets                 |
| GET    | `/datasets/{id}`                              | Dataset info + column profile                |
| GET    | `/datasets/{id}/quality`                      | Data quality report                          |
| GET    | `/datasets/{id}/rows`                         | Paginated row viewer                         |
| POST   | `/chat`                                       | Send a question (SSE stream response)        |
| GET    | `/chat/{session_id}/history`                  | Conversation history                         |
| GET    | `/analysis/{session_id}/findings`             | All findings with evidence status            |
| POST   | `/analysis/{session_id}/findings/{id}/prove`  | Re-run computation to verify a finding       |
| POST   | `/reports/generate`                           | Generate a 10-section analytical report      |
| GET    | `/reports/{session_id}/markdown`              | Download report as Markdown                  |
| GET    | `/reports/{session_id}/html`                  | Download report as HTML                      |

---

## How It Works

1. **Upload** — User uploads a CSV or Excel file. The ingestion pipeline detects encoding, infers headers, removes total rows, converts to Parquet, and builds a data dictionary with column roles (date, measure, dimension). Datasets persist across server restarts via SQLite.

2. **Ask** — User types a question in the chat interface (e.g., *"Why did revenue decline in Q3?"*). The frontend sends it to `/chat` and opens an SSE stream.

3. **Route** — The Router classifies the question into a tier (Lookup / Analysis / Investigation / Report) using keyword heuristics and assigns a compute budget.

4. **Plan** — The Planner sends the data schema — never raw data — to the LLM to produce a structured analysis plan with typed specs for each computation.

5. **Execute** — The Analysis Agent executes each spec using the analytical tools: DuckDB queries, statistical tests, anomaly detection, contribution analysis. Each result is stored as a traceable `Evidence` record.

6. **Validate** — Every finding passes through the 3-layer validation pipeline:
   - Language lint catches causal overstatement and rewrites it
   - Numerical recomputation independently re-derives the finding
   - Evidence status scoring grades the claim (supported / partial / insufficient)

7. **Stream** — Status updates are streamed to the UI in real time via SSE. The final answer, findings, evidence records, and tier metadata are delivered in a single result event.

8. **Report** — Clicking "Generate Report" triggers the Report Agent to produce a 10-section professional report (Executive Summary, Key Findings, Anomalies, Data Quality, Methodology, Limitations, Next Steps, Reproducibility). The report panel slides in on the right.

---

## License

This project was built for the BOBathon Hackathon.
