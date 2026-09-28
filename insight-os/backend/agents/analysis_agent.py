from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from models.core import (
    AnalysisPlan,
    AnalysisSession,
    ClaimStrength,
    ClaimType,
    Evidence,
    EvidenceStatus,
    Finding,
    Chart,
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class IntentResult:
    question: str
    metrics_needed: List[str] = field(default_factory=list)
    dimensions_needed: List[str] = field(default_factory=list)
    time_expression: Optional[str] = None
    comparison_requested: bool = False
    why_question: bool = False


@dataclass
class AgentResult:
    findings: List[Finding] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    charts: List[Chart] = field(default_factory=list)
    answer_text: str = ""
    questions_for_user: List[str] = field(default_factory=list)
    plan_preview: Optional[AnalysisPlan] = None
    status_updates: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------


class AnalysisAgent:
    def __init__(self, llm_client):
        self.llm_client = llm_client

    async def run(
        self,
        session: AnalysisSession,
        question: str,
    ) -> AgentResult:
        result = AgentResult()
        result.status_updates.append("Starting analysis…")

        # Step 1: Understand intent
        intent = self._understand_intent(question, session)
        result.status_updates.append(f"Intent: {'comparison' if intent.comparison_requested else 'lookup'}")

        # Step 2: Check sufficiency
        from tools.sufficiency import check_sufficiency
        from tools.semantic_layer import resolve_time_anchor

        primary_dataset_id = session.dataset_ids[0] if session.dataset_ids else None
        if not primary_dataset_id:
            result.questions_for_user.append("Please upload a dataset before asking questions.")
            result.answer_text = "No dataset available."
            return result

        parquet_path = session.parquet_paths.get(primary_dataset_id, "")
        dictionary = session.dictionaries.get(primary_dataset_id, [])

        requirements = {
            "required_roles": [r for r in ["measure", "date"] if r in [str(e.role) for e in dictionary]],
            "required_metrics": intent.metrics_needed,
            "dimensions": intent.dimensions_needed,
            "time_expression": intent.time_expression,
            "min_rows": 5,
        }

        sufficiency = check_sufficiency(requirements, dictionary, parquet_path, {})
        result.status_updates.append(f"Sufficiency: {sufficiency.verdict}")

        from models.core import SufficiencyVerdict
        if sufficiency.verdict == SufficiencyVerdict.insufficient:
            missing_str = "; ".join(sufficiency.missing)
            result.questions_for_user.append(
                f"The data doesn't appear to have what's needed: {missing_str}. "
                "Can you upload additional data or clarify the question?"
            )
            result.answer_text = (
                f"I can't fully answer this question with the available data. "
                f"Missing: {missing_str}"
            )
            return result

        # Step 3: Build metric definitions
        from tools.semantic_layer import resolve_metric_pack
        metric_defs = resolve_metric_pack(dictionary)
        metric_defs_str = {k: v for k, v in metric_defs.items()}
        result.status_updates.append(f"Resolved {len(metric_defs_str)} metrics.")

        # Step 4: Create analysis plan
        from agents.planner import create_analysis_plan, plan_to_specs
        result.status_updates.append("Planning analysis…")
        plan = await create_analysis_plan(question, session, self.llm_client, metric_defs_str)
        result.plan_preview = plan
        session.plans.append(plan)

        # Step 5: Execute plan
        result.status_updates.append(f"Executing {len(plan.specs)} analysis spec(s)…")
        evidence_list = await self._execute_plan(plan, session, metric_defs_str)
        result.evidence.extend(evidence_list)
        session.evidence.extend(evidence_list)
        result.status_updates.append(f"Produced {len(evidence_list)} evidence record(s).")

        # Step 6: Create findings
        findings = self._create_findings_from_evidence(evidence_list, session)
        result.status_updates.append("Validating findings…")

        # Step 7: Validate findings
        findings = await self._validate_findings(findings, evidence_list, session)
        result.findings.extend(findings)
        session.findings.extend(findings)

        # Step 8: Build charts
        result.status_updates.append("Building charts…")
        charts = self._build_charts(findings, evidence_list, session)
        result.charts.extend(charts)
        session.charts.extend(charts)

        # Step 9: Insight tree (why questions)
        if intent.why_question and findings:
            result.status_updates.append("Running insight tree…")
            extra_findings: List[Finding] = []
            for root in findings[:2]:  # limit to top 2 root findings
                children = await self._run_insight_tree(root, session, depth=0, max_depth=2)
                extra_findings.extend(children)
            result.findings.extend(extra_findings)
            session.findings.extend(extra_findings)

        # Step 10: Generate answer (LLM receives only evidence IDs, not raw data)
        result.status_updates.append("Generating answer…")
        answer = await self._generate_answer(result.findings, evidence_list, session)
        result.answer_text = answer

        # Step 11: Add to conversation history
        session.conversation_history.append({"role": "user", "content": question})
        session.conversation_history.append({"role": "assistant", "content": answer})

        result.status_updates.append("Complete.")
        return result

    def _understand_intent(self, question: str, session: AnalysisSession) -> IntentResult:
        import re
        intent = IntentResult(question=question)

        q_lower = question.lower()

        # Detect why question
        intent.why_question = bool(re.search(r"\b(why|explain|what caused|investigate)\b", q_lower))

        # Detect comparison
        intent.comparison_requested = bool(
            re.search(r"\b(vs|versus|compare|difference|change|growth|decline|increase|decrease)\b", q_lower)
        )

        # Extract time expression
        time_patterns = [
            r"last (?:month|quarter|year|week)",
            r"this (?:month|quarter|year)",
            r"q[1-4]\s*\d{4}",
            r"\d{4}",
            r"ytd|year to date",
        ]
        for tp in time_patterns:
            m = re.search(tp, q_lower)
            if m:
                intent.time_expression = m.group()
                break

        # Detect metrics from session metric definitions
        for dataset_id in session.dataset_ids:
            dictionary = session.dictionaries.get(dataset_id, [])
            for entry in dictionary:
                if entry.column.lower() in q_lower or (entry.display_name and entry.display_name.lower() in q_lower):
                    if str(entry.role) == "measure":
                        intent.metrics_needed.append(entry.column)
                    elif str(entry.role) == "dimension":
                        intent.dimensions_needed.append(entry.column)

        return intent

    async def _execute_plan(
        self,
        plan: AnalysisPlan,
        session: AnalysisSession,
        metric_defs: Dict[str, str],
    ) -> List[Evidence]:
        from tools.analysis_engine import run_analysis_spec

        evidence_list: List[Evidence] = []
        primary_dataset_id = session.dataset_ids[0] if session.dataset_ids else ""
        parquet_path = session.parquet_paths.get(primary_dataset_id, "")
        version = session.dataset_versions.get(primary_dataset_id)
        version_id = version.id if version else ""

        for spec in plan.specs:
            try:
                ev = run_analysis_spec(spec, parquet_path, primary_dataset_id, version_id, metric_defs)
                evidence_list.append(ev)
                session.budget.tool_calls_used += 1
            except Exception as e:
                # Create an empty evidence record for failed specs
                evidence_list.append(
                    Evidence(
                        id=str(uuid.uuid4()),
                        metric=spec.metric,
                        value=None,
                        source_dataset=primary_dataset_id,
                        dataset_version_id=version_id,
                        calculation=f"Failed: {e}",
                        engine_version="1.0",
                    )
                )

            if session.budget.is_exhausted():
                break

        return evidence_list

    def _create_findings_from_evidence(
        self,
        evidence_list: List[Evidence],
        session: AnalysisSession,
    ) -> List[Finding]:
        findings: List[Finding] = []
        for ev in evidence_list:
            if ev.value is None:
                continue

            claim = self._summarise_evidence_as_claim(ev)
            claim_type = ClaimType.comparative if isinstance(ev.value, dict) and "current" in ev.value else ClaimType.factual

            finding = Finding(
                id=str(uuid.uuid4()),
                session_id=session.id,
                claim=claim,
                claim_type=claim_type,
                strength=ClaimStrength.moderate,
                metric=ev.metric,
                value=ev.value,
                evidence_id=ev.id,
                evidence_status=EvidenceStatus.supported,
            )
            ev.finding_id = finding.id
            findings.append(finding)

        return findings

    def _summarise_evidence_as_claim(self, ev: Evidence) -> str:
        """Turn an evidence record into a plain-English claim sentence."""
        metric = ev.metric or "the metric"
        value = ev.value

        if isinstance(value, dict):
            if "current" in value and "baseline" in value:
                current = value.get("current")
                baseline = value.get("baseline")
                change_pct = value.get("change_pct")
                current_period = value.get("current_period", "current period")
                baseline_period = value.get("baseline_period", "baseline period")

                if change_pct is not None:
                    direction = "increased" if change_pct > 0 else "decreased"
                    return (
                        f"{metric} {direction} by {abs(change_pct):.1f}% "
                        f"from {baseline_period} to {current_period} "
                        f"({baseline} → {current})."
                    )
                return f"{metric} was {current} in {current_period} vs {baseline} in {baseline_period}."

            if "anomalies" in value:
                count = value.get("anomaly_count", 0)
                return f"{count} anomalies detected in {metric}."

            if "segments" in value:
                dim = value.get("dimension", "")
                top = value.get("segments", [])[:1]
                if top:
                    seg = top[0].get("segment", "")
                    delta = top[0].get("delta", 0)
                    return f"{seg} is the largest contributor to change in {metric} (Δ{delta:+.2f})."

        if isinstance(value, (int, float)):
            unit = ev.unit or ""
            return f"{metric} is {value:,.2f} {unit}".strip() + "."

        return f"Analysis of {metric} complete."

    async def _validate_findings(
        self,
        findings: List[Finding],
        evidence_list: List[Evidence],
        session: AnalysisSession,
    ) -> List[Finding]:
        from validators.language_lint import lint_language
        from validators.recompute import recompute_finding
        from validators.evidence_status import compute_evidence_status

        primary_dataset_id = session.dataset_ids[0] if session.dataset_ids else ""
        parquet_path = session.parquet_paths.get(primary_dataset_id, "")

        evidence_map = {ev.id: ev for ev in evidence_list}

        for finding in findings:
            ev = evidence_map.get(finding.evidence_id or "")

            # Language lint
            lang_result = lint_language(finding.claim, finding.strength)
            if not lang_result.passed:
                finding.claim = lang_result.rewritten_text
                finding.validation_results["language_lint"] = {
                    "violations": lang_result.violations,
                    "rewritten": True,
                }

            if ev and parquet_path:
                # Recompute
                recompute = recompute_finding(finding, ev, parquet_path)
                finding.validation_results["recompute"] = {
                    "matched": recompute.matched,
                    "original": str(recompute.original_value),
                    "reproduced": str(recompute.recomputed_value),
                }

                # Update evidence status
                finding.evidence_status = compute_evidence_status(
                    finding, ev, recompute, [], 1.0
                )

        return findings

    async def _generate_answer(
        self,
        findings: List[Finding],
        evidence_list: List[Evidence],
        session: AnalysisSession,
    ) -> str:
        """
        Generate the narrative answer.
        The LLM receives only evidence IDs and claim summaries — NOT raw data.
        """
        if not findings:
            return "I couldn't find a clear answer with the available data."

        # Build a structured evidence summary (IDs + claims only, no raw numbers)
        evidence_summary = "\n".join(
            f"[Evidence {ev.id[:8]}] metric={ev.metric}, period={ev.period}"
            for ev in evidence_list[:10]
        )
        claim_summary = "\n".join(
            f"- {f.claim} (evidence: {f.evidence_id[:8] if f.evidence_id else 'n/a'}, status: {f.evidence_status})"
            for f in findings[:10]
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an analytical assistant. "
                    "Write a concise, evidence-based answer. "
                    "Do not invent numbers. Only reference findings from the evidence list. "
                    "Use associational language (not causal). "
                    "Disclose assumptions and caveats."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {session.conversation_history[-2]['content'] if len(session.conversation_history) >= 2 else (session.conversation_history[0]['content'] if session.conversation_history else '')}\n\n"
                    f"Evidence available:\n{evidence_summary}\n\n"
                    f"Validated findings:\n{claim_summary}\n\n"
                    "Write the answer using only these findings. Reference evidence IDs in parentheses."
                ),
            },
        ]

        try:
            session.budget.llm_tokens_used += 1000  # approximate
            answer = await self.llm_client.chat_completion(
                messages=messages,
                model=self.llm_client.fast_model,
            )
            return answer
        except Exception as e:
            # Fallback: compose answer deterministically from findings
            return "\n\n".join(f.claim for f in findings)

    async def _run_insight_tree(
        self,
        root_finding: Finding,
        session: AnalysisSession,
        depth: int = 0,
        max_depth: int = 2,
    ) -> List[Finding]:
        """
        Recursively explore 'why' questions for a finding.
        Bounded to max_depth to prevent runaway recursion.
        """
        if depth >= max_depth:
            return []
        if session.budget.is_exhausted():
            return []

        primary_dataset_id = session.dataset_ids[0] if session.dataset_ids else ""
        parquet_path = session.parquet_paths.get(primary_dataset_id, "")
        dictionary = session.dictionaries.get(primary_dataset_id, [])

        # Try contribution analysis on the root finding's metric
        if root_finding.metric:
            from tools.semantic_layer import resolve_metric_pack
            from tools.analysis_engine import contribution_analysis
            from models.core import TimeWindow

            metric_defs = resolve_metric_pack(dictionary)

            # Find a dimension to break down by
            dimension_cols = [
                e.column for e in dictionary
                if str(e.role) == "dimension" and e.column != root_finding.metric
            ]
            if not dimension_cols:
                return []

            date_cols = [e.column for e in dictionary if str(e.role) == "date"]
            date_col = date_cols[0] if date_cols else ""

            try:
                version_obj = session.dataset_versions.get(primary_dataset_id)
                ev = contribution_analysis(
                     parquet_path=parquet_path,
                     dataset_id=primary_dataset_id,
                     version_id=version_obj.id if version_obj else "",
                     metric=root_finding.metric,
                    date_col=date_col,
                    current_window=TimeWindow(),
                    baseline_window=TimeWindow(),
                    metric_definitions=metric_defs,
                    dimension=dimension_cols[0],
                )
                session.budget.tool_calls_used += 1
                session.evidence.append(ev)

                child_claim = self._summarise_evidence_as_claim(ev)
                child_finding = Finding(
                    id=str(uuid.uuid4()),
                    session_id=session.id,
                    claim=child_claim,
                    claim_type=ClaimType.comparative,
                    strength=ClaimStrength.moderate,
                    metric=root_finding.metric,
                    evidence_id=ev.id,
                    evidence_status=EvidenceStatus.supported,
                    parent_finding_id=root_finding.id,
                    depth=depth + 1,
                )
                ev.finding_id = child_finding.id

                # Recurse
                grandchildren = await self._run_insight_tree(
                    child_finding, session, depth + 1, max_depth
                )
                return [child_finding] + grandchildren

            except Exception:
                return []

        return []
