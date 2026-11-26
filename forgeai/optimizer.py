"""Req 6: Targeted critic-optimizer loop (hard cap 3 iterations, revert on drop, dev/test split)."""

from __future__ import annotations

import difflib
import json
import logging
from collections import Counter
from pathlib import Path

import yaml
from pydantic import BaseModel

from forgeai.agent_runner import AgentRunner
from forgeai.budget import BudgetExceededError
from forgeai.config import Settings, render_prompt
from forgeai.generator import save_agent_definition
from forgeai.ingest import IngestedCorpus, ingest_corpus
from forgeai.judge import evaluate_agent, pairwise_judge_both_orders
from forgeai.llm import LLMClient
from forgeai.retrieval import HybridRetriever
from forgeai.schemas import (
    AgentDefinition,
    EvalSet,
    IterationLog,
    IterationRecord,
    Scorecard,
)

logger = logging.getLogger(__name__)

HARD_MAX_ITERATIONS = 3


class _PromptPatchOutput(BaseModel):
    updated_system_prompt: str
    change_summary: str


def _yaml_diff(old_agent: AgentDefinition, new_agent: AgentDefinition) -> str:
    old_lines = yaml.safe_dump(old_agent.model_dump(mode="json"), sort_keys=False).splitlines(keepends=True)
    new_lines = yaml.safe_dump(new_agent.model_dump(mode="json"), sort_keys=False).splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="agent_before.yaml",
            tofile="agent_after.yaml",
            n=2,
        )
    )


def _contains_eval_question(prompt_text: str, eval_set: EvalSet) -> bool:
    """Overfitting guard: reject patched prompts that copy any eval question verbatim."""
    low = prompt_text.lower()
    for c in eval_set.cases:
        q = c.question.strip().lower()
        if len(q) >= 20 and q in low:
            return True
    return False


def _propose_targeted_patch(
    agent: AgentDefinition,
    dev_scorecard: Scorecard,
    eval_set: EvalSet,
    llm: LLMClient,
) -> tuple[AgentDefinition, str, str, str, list[str], bool]:
    """Select dominant dev failure cluster and apply a targeted non-regenerative fix."""
    failed_dev = [j for j in dev_scorecard.case_judgments if j.final_verdict == "FAIL"]
    counts = Counter(j.failure_category for j in failed_dev if j.failure_category != "none")
    if not counts:
        return agent, "none", "No dev failures remaining", "", [], False

    dominant, _ = counts.most_common(1)[0]
    addressed = [j.case_id for j in failed_dev if j.failure_category == dominant]
    candidate = agent.model_copy(deep=True)
    need_reindex = False

    if dominant == "retrieval_miss":
        old_cfg = candidate.retrieval
        new_top_k = min(10, old_cfg.top_k + 2)
        new_overlap = min(200, old_cfg.overlap + 40)
        new_alpha = 0.4 if old_cfg.hybrid_alpha >= 0.5 else 0.5
        candidate.retrieval.top_k = new_top_k
        candidate.retrieval.overlap = new_overlap
        candidate.retrieval.hybrid_alpha = new_alpha
        if old_cfg.chunk_size > 450:
            candidate.retrieval.chunk_size = max(400, old_cfg.chunk_size - 100)
        need_reindex = True
        action = (
            f"Adjusted retrieval params: top_k {old_cfg.top_k}->{candidate.retrieval.top_k}, "
            f"overlap {old_cfg.overlap}->{candidate.retrieval.overlap}, "
            f"chunk_size {old_cfg.chunk_size}->{candidate.retrieval.chunk_size}, "
            f"hybrid_alpha {old_cfg.hybrid_alpha}->{candidate.retrieval.hybrid_alpha}"
        )
        rationale = f"Address {len(addressed)} retrieval_miss dev case(s) by widening recall and chunk overlap."
        return candidate, dominant, action, rationale, addressed, need_reindex

    if dominant == "wrong_refusal":
        false_refusals = [
            j for j in failed_dev if j.failure_category == "wrong_refusal" and j.expected_behavior == "answer"
        ]
        missed_refusals = [
            j for j in failed_dev if j.failure_category == "wrong_refusal" and j.expected_behavior == "refuse"
        ]
        old_min = candidate.retrieval.min_score
        if len(false_refusals) >= len(missed_refusals):
            candidate.retrieval.min_score = round(max(0.08, old_min - 0.06), 3)
            rule_add = (
                "\n- IN-SCOPE RULE: Only refuse when NO relevant facts or tool results exist in the provided evidence. "
                "If partial or supporting facts are present, answer strictly with those cited facts."
            )
            action = f"Lowered min_score {old_min}->{candidate.retrieval.min_score} and clarified in-scope rule."
            rationale = f"Reduce {len(false_refusals)} false refusals on answerable dev queries."
        else:
            candidate.retrieval.min_score = round(min(0.40, old_min + 0.06), 3)
            rule_add = (
                "\n- STRICT REFUSAL RULE: If a topic is outside the provided documents or listed in must_refuse_topics, "
                "refuse immediately using the refusal template without guessing."
            )
            action = f"Raised min_score {old_min}->{candidate.retrieval.min_score} and strengthened refusal boundary."
            rationale = f"Catch {len(missed_refusals)} missed out-of-scope refusals on dev set."
        if rule_add.strip() not in candidate.system_prompt:
            candidate.system_prompt = candidate.system_prompt.strip() + rule_add
        return candidate, dominant, action, rationale, addressed, False

    if dominant == "hallucination":
        old_min = candidate.retrieval.min_score
        candidate.retrieval.min_score = round(min(0.35, old_min + 0.04), 3)
        hall_summary = "\n".join(
            f"- Case {j.case_id}: hallucinated tokens={j.deterministic.hallucinated_tokens}, evidence={j.evidence[:120]}"
            for j in failed_dev
            if j.failure_category == "hallucination"
        )[:900]
        patch_prompt = render_prompt(
            "optimizer_patch",
            failure_category="hallucination",
            current_system_prompt=candidate.system_prompt,
            failure_summary=hall_summary or "Numeric or entity claims appeared without support in retrieved chunks.",
        )
        patched = llm.json_call(patch_prompt, _PromptPatchOutput, temperature=0.1, max_tokens=1000)
        if not _contains_eval_question(patched.updated_system_prompt, eval_set):
            candidate.system_prompt = patched.updated_system_prompt.strip()
        else:
            candidate.system_prompt = (
                candidate.system_prompt.strip()
                + "\n- GROUNDING CONSTRAINT: Copy numbers, dates, and part codes verbatim from RETRIEVED EVIDENCE or TOOL OUTPUTS; never extrapolate."
            )
        action = f"Patched grounding constraints + raised min_score {old_min}->{candidate.retrieval.min_score}: {patched.change_summary}"
        rationale = f"Eliminate unsupported numbers/claims across {len(addressed)} hallucination dev case(s)."
        return candidate, dominant, action, rationale, addressed, False

    # prompt_defect
    defect_summary = "\n".join(
        f"- Case {j.case_id}: missed_facts={len(j.deterministic.missed_facts)}, format_ok={j.deterministic.format_ok}, evidence={j.evidence[:120]}"
        for j in failed_dev
        if j.failure_category == "prompt_defect"
    )[:900]
    patch_prompt = render_prompt(
        "optimizer_patch",
        failure_category="prompt_defect",
        current_system_prompt=candidate.system_prompt,
        failure_summary=defect_summary or "Agent missed atomic facts from retrieved chunks or omitted required citations.",
    )
    patched = llm.json_call(patch_prompt, _PromptPatchOutput, temperature=0.1, max_tokens=1000)
    if not _contains_eval_question(patched.updated_system_prompt, eval_set):
        candidate.system_prompt = patched.updated_system_prompt.strip()
        action = f"Patched system_prompt section: {patched.change_summary}"
    else:
        candidate.system_prompt = (
            candidate.system_prompt.strip()
            + "\n- COMPLETENESS & CITATION RULE: Include all relevant atomic numbers/conditions from evidence and end every claim with [source: filename, section]."
        )
        action = "Applied generic completeness & citation rule (rejected verbatim question leak)."
    rationale = f"Fix {len(addressed)} prompt_defect dev case(s) while preserving retrieved context."
    return candidate, dominant, action, rationale, addressed, False


def _render_iteration_log_md(log: IterationLog) -> str:
    lines = [
        "# Critic-Optimizer Iteration Log",
        "",
        f"- **Max iterations:** {log.max_iterations}",
        f"- **Target score (dev):** {log.target_score:.2f}",
        f"- **Stop reason:** {log.stopped_reason}",
        "",
    ]
    for rec in log.iterations:
        lines.extend(
            [
                f"## Iteration {rec.iteration} — {'ACCEPTED' if rec.accepted else 'REVERTED'}",
                f"- **Dominant failure category:** `{rec.dominant_failure_category}`",
                f"- **Failures addressed:** {', '.join(rec.failures_addressed) or 'none'}",
                f"- **Action taken:** {rec.action_taken}",
                f"- **Rationale:** {rec.rationale}",
                f"- **Dev score:** {rec.dev_score_before:.4f} -> {rec.dev_score_after:.4f}",
                f"- **Held-out Test score:** {rec.test_score_before:.4f} -> {rec.test_score_after:.4f}",
                f"- **Overall score:** {rec.overall_score_before:.4f} -> {rec.overall_score_after:.4f}",
                f"- **Status:** {rec.status_note}",
                "",
                "```diff",
                rec.unified_diff.strip() or "(no diff)",
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def run_prompt_tournament(
    agent: AgentDefinition,
    candidate_prompts: list[str],
    docs_dir: Path,
    corpus: IngestedCorpus,
    retriever: HybridRetriever,
    eval_set: EvalSet,
    llm: LLMClient,
    settings: Settings,
) -> tuple[AgentDefinition, list[dict[str, object]]]:
    """Stretch: compare candidate system prompts on dev subset with both-order pairwise judging."""
    if len(candidate_prompts) <= 1:
        return agent, []
    dev_cases = [c for c in eval_set.cases if c.id in set(eval_set.dev_ids)][:6]
    if not dev_cases:
        return agent, []

    answers_by_idx: dict[int, list[str]] = {}
    for idx, prompt_text in enumerate(candidate_prompts):
        cand_agent = agent.model_copy(deep=True)
        cand_agent.system_prompt = prompt_text
        runner = AgentRunner(
            agent=cand_agent,
            docs_dir=docs_dir,
            llm_client=llm,
            corpus=corpus,
            retriever=retriever,
        )
        answers_by_idx[idx] = [runner.ask(c.question).answer for c in dev_cases]

    wins = {i: 0 for i in range(len(candidate_prompts))}
    matchups: list[dict[str, object]] = []
    for i in range(len(candidate_prompts)):
        for j in range(i + 1, len(candidate_prompts)):
            i_wins, j_wins, ties = 0, 0, 0
            for k, case in enumerate(dev_cases):
                verdict = pairwise_judge_both_orders(
                    question=case.question,
                    expected_behavior=case.expected_behavior,
                    reference_answer=case.reference_answer,
                    answer_a=answers_by_idx[i][k],
                    answer_b=answers_by_idx[j][k],
                    llm=llm,
                    judge_model=settings.judge_model,
                )
                if verdict == "A":
                    wins[i] += 1
                    i_wins += 1
                elif verdict == "B":
                    wins[j] += 1
                    j_wins += 1
                else:
                    ties += 1
            matchups.append(
                {
                    "candidate_a": i,
                    "candidate_b": j,
                    "a_wins": i_wins,
                    "b_wins": j_wins,
                    "ties": ties,
                }
            )

    best_idx = max(wins, key=lambda idx: wins[idx])
    winner = agent.model_copy(deep=True)
    winner.system_prompt = candidate_prompts[best_idx]
    return winner, matchups


def run_optimizer(
    initial_agent: AgentDefinition,
    docs_dir: Path,
    eval_set: EvalSet,
    llm: LLMClient,
    settings: Settings,
    run_dir: Path,
    max_iters: int = HARD_MAX_ITERATIONS,
    target_score: float = 0.85,
    min_gain: float = 0.005,
    use_llm_judge: bool = True,
) -> tuple[AgentDefinition, Scorecard, Scorecard, IterationLog]:
    """Run bounded critic-optimizer loop (max 3 iters), reverting if dev score drops."""
    effective_max = max(0, min(int(max_iters), HARD_MAX_ITERATIONS))

    current_agent = initial_agent.model_copy(deep=True)
    current_corpus = ingest_corpus(docs_dir, current_agent.retrieval)
    current_retriever = HybridRetriever(current_corpus.chunks, current_agent.retrieval, llm)
    current_runner = AgentRunner(
        agent=current_agent,
        docs_dir=docs_dir,
        llm_client=llm,
        corpus=current_corpus,
        retriever=current_retriever,
    )

    initial_scorecard = evaluate_agent(
        runner=current_runner,
        eval_set=eval_set,
        settings=settings,
        llm_judge=llm,
        split_filter="all",
        use_llm_judge=use_llm_judge,
    )
    current_scorecard = initial_scorecard
    records: list[IterationRecord] = []
    stopped_reason = "completed_max_iterations"

    if current_scorecard.dev_score >= target_score:
        stopped_reason = f"target_reached_initially ({current_scorecard.dev_score:.3f} >= {target_score:.2f})"
    elif effective_max == 0:
        stopped_reason = "max_iterations_zero"
    else:
        for it in range(1, effective_max + 1):
            try:
                llm.budget.ensure_within_budget()
            except BudgetExceededError as exc:
                stopped_reason = f"budget_exceeded: {exc}"
                break

            dev_only_cards = [j for j in current_scorecard.case_judgments if j.split == "dev"]
            dev_failed = [j for j in dev_only_cards if j.final_verdict == "FAIL"]
            if not dev_failed:
                stopped_reason = "no_dev_failures_remaining"
                break

            cand_agent, dom_cat, action, rationale, addressed, need_reindex = _propose_targeted_patch(
                agent=current_agent,
                dev_scorecard=Scorecard(
                    overall_score=current_scorecard.dev_score,
                    dev_score=current_scorecard.dev_score,
                    test_score=current_scorecard.test_score,
                    pass_rate=current_scorecard.pass_rate,
                    total_cases=len(dev_only_cards),
                    passed_cases=len(dev_only_cards) - len(dev_failed),
                    case_judgments=dev_only_cards,
                ),
                eval_set=eval_set,
                llm=llm,
            )

            diff_str = _yaml_diff(current_agent, cand_agent)
            if not diff_str.strip():
                stopped_reason = "no_applicable_patch"
                break

            if need_reindex:
                cand_corpus = ingest_corpus(docs_dir, cand_agent.retrieval)
                cand_retriever = HybridRetriever(cand_corpus.chunks, cand_agent.retrieval, llm)
            else:
                cand_corpus = current_corpus
                cand_retriever = HybridRetriever(
                    current_corpus.chunks, cand_agent.retrieval, llm
                )

            cand_runner = AgentRunner(
                agent=cand_agent,
                docs_dir=docs_dir,
                llm_client=llm,
                corpus=cand_corpus,
                retriever=cand_retriever,
            )
            try:
                cand_scorecard = evaluate_agent(
                    runner=cand_runner,
                    eval_set=eval_set,
                    settings=settings,
                    llm_judge=llm,
                    split_filter="all",
                    use_llm_judge=use_llm_judge,
                )
            except BudgetExceededError as exc:
                stopped_reason = f"budget_exceeded_during_eval: {exc}"
                break

            gain = cand_scorecard.dev_score - current_scorecard.dev_score
            accepted = gain >= min_gain

            if accepted:
                status_note = f"Accepted patch (+{gain:.4f} dev score)."
                rec = IterationRecord(
                    iteration=it,
                    dominant_failure_category=dom_cat,
                    failures_addressed=addressed,
                    action_taken=action,
                    rationale=rationale,
                    unified_diff=diff_str,
                    dev_score_before=current_scorecard.dev_score,
                    dev_score_after=cand_scorecard.dev_score,
                    test_score_before=current_scorecard.test_score,
                    test_score_after=cand_scorecard.test_score,
                    overall_score_before=current_scorecard.overall_score,
                    overall_score_after=cand_scorecard.overall_score,
                    per_category_before=current_scorecard.per_category_scores,
                    per_category_after=cand_scorecard.per_category_scores,
                    accepted=True,
                    status_note=status_note,
                )
                current_agent = cand_agent
                current_corpus = cand_corpus
                current_retriever = cand_retriever
                current_scorecard = cand_scorecard
            else:
                status_note = (
                    f"REVERTED patch (dev score delta {gain:+.4f} < min_gain {min_gain:.3f})."
                )
                rec = IterationRecord(
                    iteration=it,
                    dominant_failure_category=dom_cat,
                    failures_addressed=addressed,
                    action_taken=action,
                    rationale=rationale,
                    unified_diff=diff_str,
                    dev_score_before=current_scorecard.dev_score,
                    dev_score_after=cand_scorecard.dev_score,
                    test_score_before=current_scorecard.test_score,
                    test_score_after=cand_scorecard.test_score,
                    overall_score_before=current_scorecard.overall_score,
                    overall_score_after=cand_scorecard.overall_score,
                    per_category_before=current_scorecard.per_category_scores,
                    per_category_after=cand_scorecard.per_category_scores,
                    accepted=False,
                    status_note=status_note,
                )

            records.append(rec)
            logger.info("Iteration %d: %s", it, status_note)

            if not accepted:
                stopped_reason = f"early_stop_no_improvement_iter_{it}"
                break
            if current_scorecard.dev_score >= target_score:
                stopped_reason = f"target_reached_iter_{it} ({current_scorecard.dev_score:.3f} >= {target_score:.2f})"
                break

    save_agent_definition(current_agent, run_dir / "agent_definition.yaml")
    log = IterationLog(
        max_iterations=effective_max,
        target_score=target_score,
        iterations=records,
        stopped_reason=stopped_reason,
    )
    (run_dir / "iteration_log.json").write_text(
        log.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (run_dir / "iteration_log.md").write_text(
        _render_iteration_log_md(log),
        encoding="utf-8",
    )
    return current_agent, initial_scorecard, current_scorecard, log
