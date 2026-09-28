from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from models.core import AnalysisSession, Budget


class RequestTier(str, Enum):
    LOOKUP = "LOOKUP"
    ANALYSIS = "ANALYSIS"
    INVESTIGATION = "INVESTIGATION"
    REPORT = "REPORT"


# ---------------------------------------------------------------------------
# Tier budgets
# ---------------------------------------------------------------------------

TIER_BUDGETS = {
    RequestTier.LOOKUP: Budget(
        max_tool_calls=5,
        max_llm_tokens=2000,
        target_latency_s=5.0,
    ),
    RequestTier.ANALYSIS: Budget(
        max_tool_calls=15,
        max_llm_tokens=8000,
        target_latency_s=20.0,
    ),
    RequestTier.INVESTIGATION: Budget(
        max_tool_calls=30,
        max_llm_tokens=20000,
        target_latency_s=60.0,
    ),
    RequestTier.REPORT: Budget(
        max_tool_calls=40,
        max_llm_tokens=40000,
        target_latency_s=120.0,
    ),
}

# ---------------------------------------------------------------------------
# Keyword heuristics
# ---------------------------------------------------------------------------

_LOOKUP_SIGNALS = re.compile(
    r"\b(what is|what was|how much|how many|total|count|sum|show me|give me|tell me)\b",
    re.IGNORECASE,
)
_ANALYSIS_SIGNALS = re.compile(
    r"\b(compare|comparison|by region|by product|by category|by segment|breakdown|split|top|bottom|rank|vs\.?|versus)\b",
    re.IGNORECASE,
)
_INVESTIGATION_SIGNALS = re.compile(
    r"\b(why|explain|investigate|what caused|what drove|what happened|root cause|insight|dig into|deep dive|anomaly|anomalies|unusual|unexpected)\b",
    re.IGNORECASE,
)
_REPORT_SIGNALS = re.compile(
    r"\b(report|summary|generate report|export|full analysis|comprehensive|overview report|write up)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def route_request(question: str, session: AnalysisSession) -> RequestTier:
    """
    Classify the question into a RequestTier based on keyword/complexity heuristics.
    Tier determines the budget (max_tool_calls, max_llm_tokens, target_latency).
    """
    q = question.strip()

    # Report is the heaviest — check first
    if _REPORT_SIGNALS.search(q):
        return RequestTier.REPORT

    # Investigation: causal questions
    if _INVESTIGATION_SIGNALS.search(q):
        return RequestTier.INVESTIGATION

    # Analysis: comparisons, segmentations
    if _ANALYSIS_SIGNALS.search(q):
        return RequestTier.ANALYSIS

    # LOOKUP: single metric, single period
    # Also LOOKUP if query is short with no complex operators
    words = q.split()
    if _LOOKUP_SIGNALS.search(q) and len(words) <= 12:
        return RequestTier.LOOKUP

    # Default: ANALYSIS for anything else substantive
    if len(words) > 20:
        return RequestTier.INVESTIGATION

    return RequestTier.ANALYSIS


def get_tier_budget(tier: RequestTier) -> Budget:
    """Return a fresh Budget copy for the given tier."""
    template = TIER_BUDGETS[tier]
    return Budget(
        max_tool_calls=template.max_tool_calls,
        max_llm_tokens=template.max_llm_tokens,
        target_latency_s=template.target_latency_s,
    )
