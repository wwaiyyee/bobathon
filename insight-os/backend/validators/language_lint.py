from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from models.core import ClaimStrength

# ---------------------------------------------------------------------------
# Patterns and rewrites
# ---------------------------------------------------------------------------

CAUSAL_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bcaused\b", re.IGNORECASE),
    re.compile(r"\bbecause\b", re.IGNORECASE),
    re.compile(r"\bdue to\b", re.IGNORECASE),
    re.compile(r"\bled to\b", re.IGNORECASE),
    re.compile(r"\bdriven by\b", re.IGNORECASE),
    re.compile(r"\bresulted in\b", re.IGNORECASE),
    re.compile(r"\bresponsible for\b", re.IGNORECASE),
    re.compile(r"\bproved that\b", re.IGNORECASE),
    re.compile(r"\bconfirms that\b", re.IGNORECASE),
    re.compile(r"\bshows that\b", re.IGNORECASE),
    re.compile(r"\bdemonstrates that\b", re.IGNORECASE),
    re.compile(r"\btherefore\b", re.IGNORECASE),
    re.compile(r"\bconsequently\b", re.IGNORECASE),
    re.compile(r"\bexplains why\b", re.IGNORECASE),
]

ASSOCIATIONAL_REWRITES: Dict[str, str] = {
    "caused": "is associated with",
    "because": "in a pattern consistent with",
    "due to": "coinciding with",
    "led to": "corresponds with",
    "driven by": "accounts for",
    "resulted in": "coincides with",
    "responsible for": "associated with",
    "proved that": "suggests that",
    "confirms that": "is consistent with",
    "shows that": "is associated with",
    "demonstrates that": "is consistent with",
    "therefore": "which corresponds with",
    "consequently": "and correspondingly",
    "explains why": "is associated with",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class LanguageLintResult:
    passed: bool
    violations: List[str] = field(default_factory=list)
    rewritten_text: str = ""

    def to_dict(self):
        return {
            "passed": self.passed,
            "violations": self.violations,
            "rewritten_text": self.rewritten_text,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lint_language(text: str, claim_strength: ClaimStrength) -> LanguageLintResult:
    """
    Check text for causal language that overreaches the claim strength.
    If claim_strength is not 'causal', causal language is a violation.
    """
    # If the claim is explicitly marked as causal, allow causal language
    if claim_strength == ClaimStrength.strong:
        # Still lint — strong claims can still be associational
        pass

    violations: List[str] = []
    for pattern in CAUSAL_PATTERNS:
        match = pattern.search(text)
        if match:
            violations.append(f"Causal language detected: '{match.group()}' — use associational language instead.")

    rewritten = rewrite_causal_to_associational(text)
    passed = len(violations) == 0

    return LanguageLintResult(
        passed=passed,
        violations=violations,
        rewritten_text=rewritten,
    )


def rewrite_causal_to_associational(text: str) -> str:
    """Replace causal phrases with associational equivalents."""
    result = text
    for causal_phrase, associational_phrase in ASSOCIATIONAL_REWRITES.items():
        # Case-insensitive replacement, preserve sentence case
        pattern = re.compile(re.escape(causal_phrase), re.IGNORECASE)
        result = pattern.sub(
            lambda m: _match_case(m.group(), associational_phrase),
            result,
        )
    return result


def _match_case(original: str, replacement: str) -> str:
    """Match the capitalisation style of the original phrase."""
    if original and original[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement
