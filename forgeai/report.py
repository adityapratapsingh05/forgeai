"""Req 7: Honest report and scorecard generator with trust notes."""

from __future__ import annotations

import json
from pathlib import Path

from forgeai.schemas import (
    AgentDefinition,
    BudgetStats,
    EvalSet,
    GroundabilityReport,
    IterationLog,
    JudgeCalibrationReport,
    RequirementsSpec,
    Scorecard,
)


def generate_report(
    run_name: str,
    requirements: RequirementsSpec,
    groundability: GroundabilityReport,
    final_agent: AgentDefinition,
    eval_set: EvalSet,
    initial_scorecard: Scorecard,
    final_scorecard: Scorecard,
    iteration_log: IterationLog,
    calibration: JudgeCalibrationReport,
    budget_stats: BudgetStats,
    run_dir: Path,
    tournament_results: list[dict[str, object]] | None = None,
) -> Path:
    """Write scorecard.json and honest report.md into run_dir."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "scorecard.json").write_text(
        final_scorecard.model_dump_json(indent=2),
        encoding="utf-8",
    )

    suspicious_perfect = final_scorecard.overall_score >= 0.999 or final_scorecard.pass_rate >= 0.999
    overfit_gap = round(final_scorecard.dev_score - final_scorecard.test_score, 4)

    lines: list[str] = [
        f"# ForgeAI Run Report — `{run_name}`",
        "",
    ]

    if suspicious_perfect:
        lines.extend(
            [
                "> [!WARNING]",
                "> **Suspiciously High Score Warning:** The final score is 100% (or near-100%). "
                "Auto-generated eval sets and small-model judges can overestimate true quality. "
                "Manual audit of responses and unseen real-user queries is strongly recommended.",
                "",
            ]
        )

    lines.extend(
        [
            "## 1. Brief & Requirements Summary",
            f"- **Original Brief:** {requirements.brief}",
            f"- **Scope:** {requirements.scope}",
            f"- **Audience:** {requirements.audience}",
            f"- **Tone:** {requirements.tone}",
            f"- **Clarifying Questions Asked:** {len(requirements.clarifier_qa)} (cap: 5)",
            f"- **Must-Answer Topics ({len(requirements.must_answer_topics)}):** {', '.join(requirements.must_answer_topics) or 'none'}",
            f"- **Must-Refuse Topics ({len(requirements.must_refuse_topics)}):** {', '.join(requirements.must_refuse_topics) or 'none'}",
            "",
            "## 2. Groundability Guard Findings",
            f"- **Supported:** {len(groundability.supported_topics)} | **Partial:** {len(groundability.partial_topics)} | **Unsupported (Demoted to Refusal):** {len(groundability.unsupported_topics)}",
        ]
    )
    if groundability.warnings:
        for w in groundability.warnings:
            lines.append(f"- **Warning:** {w}")
    lines.extend(
        [
            "",
            "| Topic | Status | Retrieval Score | Keyword Overlap | Reason |",
            "|---|---|---:|---:|---|",
        ]
    )
    for item in groundability.items:
        lines.append(
            f"| {item.topic} | **{item.status}** | {item.retrieval_score:.3f} | {item.keyword_overlap:.2f} | {item.reason.replace('|', '/')} |"
        )

    lines.extend(
        [
            "",
            "## 3. Final Agent Definition Summary",
            f"- **Name:** {final_agent.name}",
            f"- **Description:** {final_agent.description}",
            f"- **Retrieval Config:** `strategy={final_agent.retrieval.strategy}`, `chunk_size={final_agent.retrieval.chunk_size}`, `overlap={final_agent.retrieval.overlap}`, `top_k={final_agent.retrieval.top_k}`, `hybrid_alpha={final_agent.retrieval.hybrid_alpha}`, `min_score={final_agent.retrieval.min_score}`",
            f"- **Enabled Tools:** {', '.join(final_agent.tools) or 'none'}",
            "",
            "### Tool Selection Rationale (Included & Excluded)",
            "| Tool | Included | Rationale |",
            "|---|---|---|",
        ]
    )
    for tr in final_agent.tool_selection_rationale:
        lines.append(f"| `{tr.name}` | {'YES' if tr.included else 'NO'} | {tr.reason.replace('|', '/')} |")

    if tournament_results:
        lines.extend(
            [
                "",
                "### Prompt Tournament Summary",
                f"Matchups run on dev subset (both pairwise orders): `{json.dumps(tournament_results)}`",
            ]
        )

    lines.extend(
        [
            "",
            "## 4. Evaluation Set & Quality Filter Audit",
            f"- **Total Kept:** {eval_set.filter_stats.kept_total} (dev={len(eval_set.dev_ids)}, held-out test={len(eval_set.test_ids)})",
            f"- **By Category:** {eval_set.filter_stats.kept_by_category}",
            f"- **Raw Generated:** {eval_set.filter_stats.raw_generated}",
            f"- **Discarded (Duplicates):** {eval_set.filter_stats.discarded_duplicate}",
            f"- **Discarded (Ungrounded Facts):** {eval_set.filter_stats.discarded_ungrounded_facts}",
            f"- **Discarded (OOS Matched Docs):** {eval_set.filter_stats.discarded_oos_matched_docs}",
            f"- **Discarded (Invalid Schema):** {eval_set.filter_stats.discarded_invalid_schema}",
            "",
            "## 5. Scorecard & Optimization Progress",
            f"- **Initial Overall Score:** {initial_scorecard.overall_score:.4f} (pass rate {initial_scorecard.pass_rate:.1%})",
            f"- **Final Overall Score:** {final_scorecard.overall_score:.4f} (pass rate {final_scorecard.pass_rate:.1%}, {final_scorecard.passed_cases}/{final_scorecard.total_cases} passed)",
            f"- **Dev vs Held-Out Test Score:** Dev = **{final_scorecard.dev_score:.4f}** | Held-out Test = **{final_scorecard.test_score:.4f}** (gap = {overfit_gap:+.4f})",
            f"- **Optimizer Stop Reason:** `{iteration_log.stopped_reason}`",
            "",
            "| Iteration | Failure Category | Action | Dev Before -> After | Test Before -> After | Outcome |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    if iteration_log.iterations:
        for rec in iteration_log.iterations:
            lines.append(
                f"| {rec.iteration} | `{rec.dominant_failure_category}` | {rec.action_taken.replace('|', '/')[:90]} | "
                f"{rec.dev_score_before:.3f} -> {rec.dev_score_after:.3f} | "
                f"{rec.test_score_before:.3f} -> {rec.test_score_after:.3f} | "
                f"{'ACCEPTED' if rec.accepted else 'REVERTED'} |"
            )
    else:
        lines.append("| 0 | - | No optimization iterations applied | - | - | Baseline kept |")

    lines.extend(
        [
            "",
            "### Per-Category Scores (Final)",
            "| Category | Score |",
            "|---|---:|",
        ]
    )
    for cat, sc in sorted(final_scorecard.per_category_scores.items()):
        lines.append(f"| `{cat}` | {sc:.4f} |")

    lines.extend(
        [
            "",
            "### Per-Failure-Type Counts (Final)",
            "| Failure Category | Count |",
            "|---|---:|",
        ]
    )
    for ftype, cnt in sorted(final_scorecard.per_failure_type_counts.items()):
        lines.append(f"| `{ftype}` | {cnt} |")

    lines.extend(
        [
            "",
            "## 6. Judge Calibration & Cost Accounting",
            f"- **Calibration Accuracy (Gold vs Corrupted Self-Test):** **{calibration.accuracy:.1%}** ({calibration.correct_predictions}/{calibration.total_samples})",
            f"  - Gold Pass Rate: {calibration.gold_pass_rate:.1%} | Corrupted Catch Rate: {calibration.corrupted_catch_rate:.1%}",
            f"- **Judge Model Note:** {final_scorecard.judge_model_note}",
            f"- **Verbosity Warnings (>2.5x reference length):** {final_scorecard.verbosity_warning_count}",
            f"- **LLM Calls:** {budget_stats.total_calls} (cache hits={budget_stats.cache_hits}, misses={budget_stats.cache_misses})",
            f"- **Embed Calls:** {budget_stats.embed_calls} (cache hits={budget_stats.embed_cache_hits})",
            f"- **Tokens Used (Uncached):** {budget_stats.total_tokens} (prompt={budget_stats.prompt_tokens}, completion={budget_stats.completion_tokens})",
            f"- **Total Uncached Latency:** {budget_stats.total_latency_s:.2f}s",
            "",
            "## 7. WHAT STILL FAILS AND WHY",
        ]
    )

    failing_cases = [j for j in final_scorecard.case_judgments if j.final_verdict == "FAIL"]
    if not failing_cases:
        lines.append(
            "- Zero cases failed the current evaluation suite. **Caution:** Review edge cases manually before trusting in production."
        )
    else:
        for j in failing_cases:
            lines.extend(
                [
                    f"### `{j.case_id}` ({j.split} / {j.category}) — Failure Type: `{j.failure_category}`",
                    f"- **Question:** {j.question}",
                    f"- **Score:** {j.score:.3f} | **Expected Behavior:** `{j.expected_behavior}` | **Key-Fact Coverage:** {j.deterministic.key_fact_coverage:.2f}",
                    f"- **Retrieved Sources:** {', '.join(j.retrieved_sources) or 'none'} (Expected: {', '.join(j.expected_source_docs) or 'none'})",
                    f"- **Hallucinated Tokens:** {', '.join(j.deterministic.hallucinated_tokens) or 'none'} | **Missed Facts:** {j.deterministic.missed_facts}",
                    f"- **Judge Evidence / Root Cause:** {j.evidence}",
                    f"- **Agent Answer Excerpt:** {j.answer[:280].replace(chr(10), ' ')}",
                    "",
                ]
            )

    lines.extend(
        [
            "## 8. Trust Notes & Known Limitations",
            "- **Small-Model Capability:** Small local models (e.g. 3B parameters) can occasionally omit secondary atomic facts, misformat `<tool>` calls, or drift on multi-document synthesis.",
            "- **Judge Self-Preference:** When `JUDGE_MODEL` equals `LLM_MODEL`, LLM-as-judge scores may share blind spots with the generator; deterministic checks (key-fact overlap, exact number matching, citation existence) act as the primary guardrail.",
            "- **Auto-Generated Eval Bias:** Even after source-fact grounding and OOS retrieval filtering, synthetic eval questions may not reflect every messy phrasing real users use.",
            "- **Overfitting Guard:** Optimizer decisions used only the `dev` split; the held-out `test` split measures generalization.",
        ]
    )

    report_path = run_dir / "report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
