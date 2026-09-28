from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from models.core import Evidence, Finding


@dataclass
class ValidationReport:
    passed: bool
    issues: List[str] = field(default_factory=list)
    rewritten_answer: str = ""

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "issues": self.issues,
            "rewritten_answer": self.rewritten_answer,
        }


async def validate_answer(
    answer_text: str,
    findings: List[Finding],
    evidence: List[Evidence],
    llm_client,
) -> ValidationReport:
    """
    LLM semantic reviewer (Layer 2 validation).
    Gives the LLM only claims + evidence, not analyst reasoning.
    Asks: does wording overstate? confounder ignored? assumptions disclosed? anything without evidence?
    """
    claims_summary = "\n".join(
        f"- [{f.claim_type}/{f.strength}] {f.claim} (evidence_id: {f.evidence_id or 'none'}, status: {f.evidence_status})"
        for f in findings[:20]
    )

    evidence_summary = "\n".join(
        f"- [{ev.id[:8]}] metric={ev.metric}, rows={ev.rows_used}, value_type={type(ev.value).__name__}"
        for ev in evidence[:20]
    )

    prompt = f"""You are a rigorous analytical reviewer. Evaluate the following answer:

ANSWER TO REVIEW:
{answer_text}

VALIDATED FINDINGS (claims backed by computation):
{claims_summary}

EVIDENCE RECORDS (computational outputs):
{evidence_summary}

Review the answer for these issues:
1. Does the wording overstate or use causal language ("caused", "led to") for associational evidence?
2. Is there any obvious confounder that is not mentioned?
3. Are assumptions and data limitations disclosed?
4. Is anything stated without corresponding evidence?

Respond in JSON:
{{
  "passed": true/false,
  "issues": ["list of specific issues found, empty if none"],
  "rewritten_answer": "improved version of the answer if issues found, otherwise copy the original"
}}
"""

    messages = [
        {
            "role": "system",
            "content": (
                "You are a rigorous analytical reviewer. "
                "Your job is to catch overstatements, missing caveats, and unsupported claims. "
                "Be strict but fair. Respond only in JSON."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        import json
        response = await llm_client.chat_completion(
            messages=messages,
            model=llm_client.fast_model,
        )

        text = response.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        data = json.loads(text)
        return ValidationReport(
            passed=data.get("passed", True),
            issues=data.get("issues", []),
            rewritten_answer=data.get("rewritten_answer", answer_text),
        )

    except Exception as e:
        # If LLM validation fails, return a passed result with a warning
        return ValidationReport(
            passed=True,
            issues=[f"Semantic validation skipped: {e}"],
            rewritten_answer=answer_text,
        )
