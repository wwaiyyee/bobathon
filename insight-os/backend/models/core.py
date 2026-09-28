from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ColumnRole(str, Enum):
    date = "date"
    measure = "measure"
    dimension = "dimension"
    identifier = "identifier"
    other = "other"


class ClaimType(str, Enum):
    factual = "factual"
    comparative = "comparative"
    trend = "trend"
    causal = "causal"
    definition = "definition"
    suggestion = "suggestion"
    question = "question"


class ClaimStrength(str, Enum):
    strong = "strong"
    moderate = "moderate"
    weak = "weak"
    speculative = "speculative"


class EvidenceStatus(str, Enum):
    supported = "supported"
    partially_supported = "partially_supported"
    insufficient_evidence = "insufficient_evidence"
    not_applicable = "not_applicable"


class SufficiencyVerdict(str, Enum):
    sufficient = "sufficient"
    partial = "partial"
    insufficient = "insufficient"


class SessionStatus(str, Enum):
    idle = "idle"
    running = "running"
    waiting_for_user = "waiting_for_user"
    complete = "complete"
    error = "error"


# ---------------------------------------------------------------------------
# Dataset models
# ---------------------------------------------------------------------------


class DatasetVersion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    dataset_id: str
    version_number: int = 1
    parquet_path: str
    content_hash: str
    row_count: int
    column_count: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    source_filename: str
    file_size_bytes: int


class Dataset(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    slug: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    current_version_id: Optional[str] = None
    versions: List[DatasetVersion] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Dictionary / metric models
# ---------------------------------------------------------------------------


class DataDictionaryEntry(BaseModel):
    column: str
    role: ColumnRole = ColumnRole.other
    display_name: Optional[str] = None
    description: Optional[str] = None
    unit: Optional[str] = None
    currency_symbol: Optional[str] = None
    is_confirmed: bool = False
    sample_values: List[Any] = Field(default_factory=list)


class MetricDefinition(BaseModel):
    name: str
    display_name: str
    sql_expression: str
    unit: Optional[str] = None
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Assumptions and transformations
# ---------------------------------------------------------------------------


class Assumption(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    text: str
    source: str = "system"
    confirmed: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TransformationStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    step_type: str  # e.g. "remove_total_row", "encoding_detected", "header_detected"
    description: str
    rows_affected: int = 0
    requires_approval: bool = False
    approved: Optional[bool] = None
    detail: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Analysis planning
# ---------------------------------------------------------------------------


class TimeWindow(BaseModel):
    start: Optional[str] = None  # ISO date string
    end: Optional[str] = None
    label: Optional[str] = None  # e.g. "last month"


class AnalysisSpec(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    analysis_type: str  # compare_periods, contribution, anomaly, distribution, etc.
    metric: str
    date_col: Optional[str] = None
    current_window: Optional[TimeWindow] = None
    baseline_window: Optional[TimeWindow] = None
    dimensions: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    assumption_ids: List[str] = Field(default_factory=list)


class AnalysisPlan(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    question: str
    specs: List[AnalysisSpec] = Field(default_factory=list)
    metric_definitions: Dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reasoning: Optional[str] = None


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    finding_id: Optional[str] = None
    claim: Optional[str] = None
    metric: Optional[str] = None
    value: Optional[Any] = None
    unit: Optional[str] = None
    period: Optional[str] = None
    baseline_period: Optional[str] = None
    source_dataset: Optional[str] = None
    dataset_version_id: Optional[str] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    rows_used: Optional[int] = None
    calculation: Optional[str] = None
    query: Optional[str] = None
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    assumption_ids: List[str] = Field(default_factory=list)
    engine_version: str = "1.0"
    created_by: str = "engine"
    reproduced: Optional[bool] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    claim: str
    claim_type: ClaimType = ClaimType.factual
    strength: ClaimStrength = ClaimStrength.moderate
    metric: Optional[str] = None
    value: Optional[Any] = None
    unit: Optional[str] = None
    interpretation: Optional[str] = None
    evidence_id: Optional[str] = None
    evidence_status: EvidenceStatus = EvidenceStatus.insufficient_evidence
    validation_results: Dict[str, Any] = Field(default_factory=dict)
    stale: bool = False
    parent_finding_id: Optional[str] = None
    depth: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------


class Chart(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    finding_id: Optional[str] = None
    session_id: Optional[str] = None
    chart_type: str
    analytical_intent: str
    vega_lite_spec: Dict[str, Any] = Field(default_factory=dict)
    source_data_ref: Optional[str] = None
    title: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


class Budget(BaseModel):
    max_tool_calls: int = 20
    max_llm_tokens: int = 16000
    target_latency_s: float = 30.0
    tool_calls_used: int = 0
    llm_tokens_used: int = 0

    def remaining_tool_calls(self) -> int:
        return max(0, self.max_tool_calls - self.tool_calls_used)

    def remaining_tokens(self) -> int:
        return max(0, self.max_llm_tokens - self.llm_tokens_used)

    def is_exhausted(self) -> bool:
        return self.tool_calls_used >= self.max_tool_calls or self.llm_tokens_used >= self.max_llm_tokens


# ---------------------------------------------------------------------------
# AnalysisSession
# ---------------------------------------------------------------------------


class AnalysisSession(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: SessionStatus = SessionStatus.idle
    dataset_ids: List[str] = Field(default_factory=list)
    # dataset_id -> DatasetVersion
    dataset_versions: Dict[str, DatasetVersion] = Field(default_factory=dict)
    # dataset_id -> parquet_path
    parquet_paths: Dict[str, str] = Field(default_factory=dict)
    # dataset_id -> list[DataDictionaryEntry]
    dictionaries: Dict[str, List[DataDictionaryEntry]] = Field(default_factory=dict)
    metric_definitions: Dict[str, MetricDefinition] = Field(default_factory=dict)
    assumptions: List[Assumption] = Field(default_factory=list)
    transformations: List[TransformationStep] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    charts: List[Chart] = Field(default_factory=list)
    plans: List[AnalysisPlan] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    pending_questions: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def get_evidence_by_id(self, evidence_id: str) -> Optional[Evidence]:
        for e in self.evidence:
            if e.id == evidence_id:
                return e
        return None

    def get_finding_by_id(self, finding_id: str) -> Optional[Finding]:
        for f in self.findings:
            if f.id == finding_id:
                return f
        return None
