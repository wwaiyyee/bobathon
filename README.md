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

IBM Bob was my **AI coding partner throughout the entire development lifecycle** of Analyx. As a solo developer building a complex multi-agent analytical platform during a hackathon, Bob was instrumental in turning an ambitious idea into a working product within the time constraints.

Here is a honest, specific account of how Bob was used at each stage.

---

### 🧠 Architecture Design & Planning

The project started with a whiteboard problem: *"How do you build a data analysis system where every answer is provably correct?"* I described this challenge to Bob and we worked through the architecture conversationally.

Bob helped me arrive at the core design decisions:

- **The 5-agent pipeline** — Router → Planner → Analyst → Validator → Reporter. Bob challenged me on the responsibility boundaries between agents and helped define clear data contracts between them (see [`agents/`](insight-os/backend/agents/)).
- **The tiered budget system** — Rather than running every question through the heaviest pipeline, Bob suggested classifying requests into tiers (Lookup / Analysis / Investigation / Report) each with calibrated compute limits (`max_tool_calls`, `max_llm_tokens`, `target_latency_s`). This shaped the entire [`router.py`](insight-os/backend/agents/router.py) and [`Budget`](insight-os/backend/models/core.py) model.
- **Evidence-first data modelling** — Bob helped me see that the domain model needed `Evidence` as a first-class entity, not just a log. Every `Finding` and `Claim` links to traceable evidence records. This design is baked into [`models/core.py`](insight-os/backend/models/core.py) with over 15 Pydantic types.

---

### 💻 Code Generation — What Bob Actually Wrote

Bob generated substantial portions of the backend through a series of targeted prompts. Below are the specific modules and the role Bob played in each:

#### `agents/router.py` — Request Tier Classification
I described the routing logic in plain English ("classify questions by complexity, assign a compute budget"). Bob produced the keyword-heuristic regex patterns (`_LOOKUP_SIGNALS`, `_INVESTIGATION_SIGNALS`, etc.) and the `TIER_BUDGETS` dictionary mapping each tier to its `Budget` constraints. I reviewed, tested, and added the edge case for long free-text questions that fall through the keyword checks.

#### `agents/analysis_agent.py` — Core Orchestrator
The `AnalysisAgent` is the heart of the pipeline. Bob scaffolded the `AgentResult` and `IntentResult` dataclasses, the async `run()` method signature, and the overall execution flow. The explicit `status_updates` list (used to stream progress to the frontend) was a Bob suggestion I accepted after discussion.

#### `validators/language_lint.py` — Causal Language Detection
This was one of the most interesting Bob collaborations. I explained the core requirement: *"LLMs tend to overstate causation — we need to catch phrases like 'caused' or 'led to' and rewrite them to associational language."* Bob produced the `CAUSAL_PATTERNS` regex list and the `ASSOCIATIONAL_REWRITES` mapping (e.g., `"caused"` → `"is associated with"`, `"due to"` → `"coinciding with"`) along with the `_match_case` helper to preserve sentence capitalisation. The resulting [`language_lint.py`](insight-os/backend/validators/language_lint.py) required minimal editing.

#### `models/core.py` — Domain Type Hierarchy
I described the conceptual hierarchy — sessions contain findings, findings contain claims, claims reference evidence — and Bob generated the full Pydantic model file. The enum design (`ClaimType`, `ClaimStrength`, `EvidenceStatus`, `SufficiencyVerdict`) came directly from a conversation about what metadata each claim needed to carry for the validation pipeline to make meaningful decisions.

#### `tools/` — Analytical Toolkit
Bob generated the scaffolding and implementation stubs for the analytical tools layer: `analysis_engine.py`, `chart_builder.py`, `data_profiler.py`, `data_quality.py`, `statistics.py`, `evidence.py`, and `join_checker.py`. For each tool I described the inputs, outputs, and key operations; Bob wrote the initial implementation that I then refined.

---

### 🔄 Iterative Refinement Through Dialogue

Development was not a single prompt-and-done process. It was a continuous back-and-forth where Bob's outputs evolved through conversation:

1. I would describe a requirement or show a failing behaviour
2. Bob would generate or revise code
3. I would review, test, and raise edge cases ("What if the LLM returns malformed JSON?", "What if the uploaded file has no header row?")
4. Bob would add fallback logic, extend error handling, or propose an alternative approach

A concrete example: the `ClaimStrength` enum was originally a boolean `is_strong`. Through a conversation with Bob about how the language linter should behave differently for speculative vs. moderate claims, we refactored it into a four-value enum (`strong`, `moderate`, `weak`, `speculative`) that now drives the linting logic in `language_lint.py`.

---

### 🐛 Debugging

Bob was used actively for debugging throughout the build. Specific cases:

- **Async session management** — An intermittent bug in `session_store.py` where concurrent requests would corrupt session state. I pasted the relevant code and stack trace into Bob; it identified the missing `await` on a nested `aiosqlite` call and the lack of per-session locking.
- **Parquet type coercion** — `PyArrow` was rejecting certain Excel files because of mixed-type columns. Bob diagnosed the issue from the error message and suggested the `coerce_to_utf8=True` flag on the write path.
- **Pydantic v2 model serialisation** — Several `model_dump()` calls were returning unexpected shapes after a dependency upgrade. Bob identified the breaking change between Pydantic v1 and v2 serialisation defaults and updated the affected call sites.

---

### 📝 Documentation & Code Organisation

Bob contributed:

- **Inline docstrings** on every public function, written to explain the *why* not just the *what*
- **Section header comments** (`# ---------------------------------------------------------------------------`) used consistently across all modules to divide logical blocks — visible throughout the codebase
- **`.env.example`** with every required and optional variable documented inline

---

### 🛠 Bob Features Used

| Bob Feature | How It Was Used |
|---|---|
| **Agent mode (code generation)** | Generating full module implementations from natural-language descriptions |
| **Plan mode** | Designing the multi-agent architecture and data model before writing code |
| **Iterative refinement** | Refining generated code through follow-up prompts and edge-case discussion |
| **Debugging assistance** | Pasting error traces and receiving targeted, context-aware fixes |
| **Documentation generation** | Generating docstrings and inline comments for all modules |

---

### Impact

Using IBM Bob as my AI coding partner allowed me to **build a production-quality analytical platform in hackathon time**. The most valuable aspect was not raw code generation — it was having a design partner to pressure-test architectural decisions, catch edge cases early, and maintain consistency across a codebase that grew to span 5 agents, 11 tools, 4 validators, and 15+ domain types.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Next.js Frontend                  │
│              (React 19 + Tailwind CSS)              │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP/REST
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
- **Dual LLM Support** — OpenAI (GPT-4o) or Anthropic (Claude) via configurable provider

---

## Tech Stack

### Frontend
| Technology  | Purpose             |
|-------------|---------------------|
| Next.js 16  | React framework     |
| React 19    | UI library          |
| Tailwind CSS 4 | Styling          |
| TypeScript  | Type safety         |

### Backend
| Technology     | Purpose                      |
|----------------|------------------------------|
| FastAPI        | API framework                |
| Python 3.11+   | Runtime                      |
| DuckDB         | In-process analytics engine  |
| Pandas / NumPy | Data manipulation            |
| SciPy / Scikit-learn | Statistical analysis   |
| PyArrow / Parquet | Columnar data storage     |
| OpenAI / Anthropic SDK | LLM providers         |
| Pydantic       | Data validation & models     |
| SQLite (aiosqlite) | Session persistence      |

---

## Project Structure

```
bobathon/
├── app/                        # Next.js frontend
│   ├── page.tsx                # Main page
│   ├── layout.tsx              # Root layout
│   └── globals.css             # Global styles
│
├── insight-os/backend/         # Python backend
│   ├── api/                    # FastAPI routes
│   │   ├── main.py             # App entrypoint & CORS
│   │   ├── datasets.py         # Dataset upload & management
│   │   ├── chat.py             # Conversational analysis
│   │   ├── analysis.py         # Direct analysis endpoints
│   │   └── reports.py          # Report generation
│   │
│   ├── agents/                 # Multi-agent system
│   │   ├── router.py           # Request tier classification
│   │   ├── planner.py          # Analysis plan generation
│   │   ├── analysis_agent.py   # Core analysis orchestrator
│   │   ├── report_agent.py     # 10-section report generation
│   │   └── validator.py        # LLM semantic review
│   │
│   ├── tools/                  # Analytical tools
│   │   ├── analysis_engine.py  # Core computation engine
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
│   │   ├── language_lint.py    # Causal language detection
│   │   ├── number_lint.py      # Numerical accuracy checks
│   │   ├── recompute.py        # Finding recomputation
│   │   └── evidence_status.py  # Evidence status scoring
│   │
│   ├── models/
│   │   └── core.py             # Pydantic domain models
│   │
│   ├── services/
│   │   ├── llm_client.py       # LLM abstraction (OpenAI/Anthropic)
│   │   └── session_store.py    # Session persistence
│   │
│   ├── data/                   # Runtime data storage
│   │   ├── uploads/            # Uploaded files
│   │   └── parquet/            # Converted parquet files
│   │
│   ├── requirements.txt
│   └── .env.example
│
├── package.json
└── README.md
```

---

## Getting Started

### Prerequisites

- **Node.js** 18+
- **Python** 3.11+
- **OpenAI API key** or **Anthropic API key**

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
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

```env
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER=openai          # or "anthropic"
STRONG_MODEL=gpt-4o
FAST_MODEL=gpt-4o-mini
```

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

Open [http://localhost:3000](http://localhost:3000) to use Analyx.

---

## API Endpoints

| Method | Endpoint         | Description                          |
|--------|------------------|--------------------------------------|
| GET    | `/health`        | Health check                         |
| POST   | `/datasets/`     | Upload a dataset (CSV/Excel)         |
| GET    | `/datasets/`     | List all datasets                    |
| POST   | `/chat/`         | Send a natural-language question     |
| POST   | `/analysis/`     | Run a direct analysis                |
| POST   | `/reports/`      | Generate a full analytical report    |

---

## How It Works

1. **Upload** — User uploads a CSV or Excel file. The ingestion pipeline detects encoding, infers headers, removes total rows, converts to Parquet, and builds a data dictionary with column roles (date, measure, dimension).

2. **Ask** — User asks a question in natural language (e.g., *"Why did revenue decline in Q3?"*).

3. **Route** — The Router classifies the question into a tier (Lookup / Analysis / Investigation / Report) using keyword heuristics, and assigns a compute budget.

4. **Plan** — The Planner sends the data schema (never raw data) to the LLM to produce a structured analysis plan with specs for each computation.

5. **Execute** — The Analysis Agent executes each spec using the analytical tools (DuckDB queries, statistical tests, anomaly detection, contribution analysis).

6. **Validate** — Every finding passes through the 3-layer validation pipeline:
   - Language lint catches causal overstatement
   - Numerical recomputation verifies correctness
   - Evidence status scores the claim's support level

7. **Synthesize** — The LLM generates a narrative answer using only evidence IDs and validated claims — never raw data.

8. **Report** — For report-tier questions, a 10-section professional report is generated with executive summary, methodology, limitations, and reproducibility metadata.

---

## License

This project was built for the BOBathon Hackathon.
