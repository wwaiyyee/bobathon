from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from models.core import Evidence

# ---------------------------------------------------------------------------
# Number extraction
# ---------------------------------------------------------------------------

# Matches numbers like: 1,234.56  |  1.234,56  |  $1,234  |  12.5%  |  -0.03
_NUMBER_PATTERN = re.compile(
    r"""
    (?<![a-zA-Z])        # not preceded by a letter
    [-+]?                # optional sign
    (?:
        \d{1,3}(?:,\d{3})*(?:\.\d+)?   # US format: 1,234.56
        |
        \d{1,3}(?:\.\d{3})*(?:,\d+)?   # EU format: 1.234,56
        |
        \d+(?:\.\d+)?                   # plain integer or decimal
    )
    (?:%|\s*(?:million|billion|thousand|k|m|bn))?  # optional unit suffix
    (?![a-zA-Z])         # not followed by a letter
    """,
    re.VERBOSE | re.IGNORECASE,
)


def extract_numbers_from_text(text: str) -> List[float]:
    """Extract all numeric values from free text."""
    matches = _NUMBER_PATTERN.findall(text)
    results: List[float] = []
    for m in matches:
        try:
            clean = m.strip().lower()
            multiplier = 1.0
            if clean.endswith("%"):
                clean = clean[:-1]
                multiplier = 0.01
            elif "billion" in clean or clean.endswith("bn"):
                clean = re.sub(r"[^\d.]", "", clean)
                multiplier = 1e9
            elif "million" in clean or clean.endswith("m"):
                clean = re.sub(r"[^\d.]", "", clean)
                multiplier = 1e6
            elif "thousand" in clean or clean.endswith("k"):
                clean = re.sub(r"[^\d.]", "", clean)
                multiplier = 1e3
            else:
                clean = re.sub(r"[,$€£¥₹]", "", clean)
            results.append(float(clean) * multiplier)
        except (ValueError, AttributeError):
            pass
    return results


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class NumberLintResult:
    passed: bool
    ungrounded_numbers: List[str] = field(default_factory=list)
    grounded_numbers: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "passed": self.passed,
            "ungrounded_numbers": self.ungrounded_numbers,
            "grounded_numbers": self.grounded_numbers,
        }


# ---------------------------------------------------------------------------
# Main lint function
# ---------------------------------------------------------------------------


def lint_numbers_in_text(
    text: str,
    evidence_store: List[Evidence],
    tolerance: float = 0.01,
) -> NumberLintResult:
    """
    Check that all numeric claims in *text* can be grounded in *evidence_store*.
    Returns NumberLintResult with which numbers are grounded vs. ungrounded.
    """
    text_numbers = extract_numbers_from_text(text)

    # Collect all numeric values from evidence
    evidence_values: List[float] = []
    for ev in evidence_store:
        _collect_numeric_values(ev.value, evidence_values)
        _collect_numeric_values(ev.outputs, evidence_values)

    grounded: List[str] = []
    ungrounded: List[str] = []

    for num in text_numbers:
        if _is_grounded(num, evidence_values, tolerance):
            grounded.append(str(num))
        else:
            ungrounded.append(str(num))

    passed = len(ungrounded) == 0
    return NumberLintResult(
        passed=passed,
        ungrounded_numbers=ungrounded,
        grounded_numbers=grounded,
    )


def _collect_numeric_values(value: Any, results: List[float]) -> None:
    """Recursively collect numeric values from a nested structure."""
    if isinstance(value, (int, float)):
        try:
            results.append(float(value))
        except (ValueError, TypeError):
            pass
    elif isinstance(value, dict):
        for v in value.values():
            _collect_numeric_values(v, results)
    elif isinstance(value, list):
        for item in value:
            _collect_numeric_values(item, results)


def _is_grounded(
    num: float,
    evidence_values: List[float],
    tolerance: float,
) -> bool:
    """Return True if *num* matches any value in *evidence_values* within tolerance."""
    if not evidence_values:
        return False
    for ev in evidence_values:
        if ev == 0 and num == 0:
            return True
        if ev == 0:
            continue
        if abs(num - ev) / abs(ev) <= tolerance:
            return True
    return False
