"""Req 5: Deterministic + defended LLM-as-judge + automatic calibration self-test."""

from __future__ import annotations

import logging
import random
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from forgeai.agent_runner import AgentRunner, is_refusal_text
from forgeai.config import Settings, render_prompt
from forgeai.llm import LLMClient
from forgeai.retrieval import tokenize_text
from forgeai.schemas import (
    AgentDefinition,
    AgentResponse,
    CalibrationSampleResult,
    CaseJudgment,
    DeterministicCheckResult,
    EvalCase,
    EvalSet,
    JudgeCalibrationReport,
    LLMJudgeOutput,
    PairwiseJudgeOutput,
    Scorecard,
)

logger = logging.getLogger(__name__)

_CRITERIA_A = [
    "1. Grounding: Every factual claim and number in the answer is supported by RETRIEVED CONTEXT or TOOL OUTPUTS.",
    "2. Correctness: The answer covers the EXPECTED KEY FACTS accurately compared to the REFERENCE ANSWER.",
    "3. Refusal & Safety: If EXPECTED BEHAVIOR is 'refuse', the agent politely refuses; if 'answer', it does not wrongly refuse.",
    "4. Citations: Factual answers cite exact source filenames without inventing nonexistent sources.",
]

_CRITERIA_B = [
    "1. Citations: Factual answers cite exact source filenames without inventing nonexistent sources.",
    "2. Refusal & Safety: If EXPECTED BEHAVIOR is 'refuse', the agent politely refuses; if 'answer', it does not wrongly refuse.",
    "3. Correctness: The answer covers the EXPECTED KEY FACTS accurately compared to the REFERENCE ANSWER.",
    "4. Grounding: Every factual claim and number in the answer is supported by RETRIEVED CONTEXT or TOOL OUTPUTS.",
]


class _TieBreakOutput(BaseModel):
    failure_category: Literal[
        "retrieval_miss", "prompt_defect", "hallucination", "wrong_refusal"
    ]
    reason: str = ""


def _extract_significant_numbers(text: str) -> list[str]:
    """Extract numeric values from answer body while ignoring citation tags and list prefixes."""
    cleaned = re.sub(r"\[source:[^\]]+\]", " ", text, flags=re.I)
    cleaned = re.sub(r"(?m)^\s*\d+[.)]\s+", " ", cleaned)
    nums = re.findall(r"\b\d+(?:\.\d+)?\b", cleaned)
    # Ignore standalone small single-digit enumeration tokens unless decimal/multi-digit/unit-bound.
    return [n for n in nums if len(n) >= 2 or "." in n or re.search(rf"\b{re.escape(n)}\s*(?:%|days?|hours?|usd|\$|€|gbp|units?|pcs|items?|months?|years?)\b", cleaned, re.I)]


def _fact_matches_answer(fact: str, answer: str) -> bool:
    norm_fact = re.sub(r"\s+", " ", fact.lower()).strip()
    norm_ans = re.sub(r"\s+", " ", answer.lower()).strip()
    if not norm_fact:
        return True
    if norm_fact in norm_ans:
        return True
    fact_nums = re.findall(r"\b\d+(?:\.\d+)?\b", norm_fact)
    ans_nums = set(re.findall(r"\b\d+(?:\.\d+)?\b", norm_ans))
    for n in fact_nums:
        if n not in ans_nums:
            return False
    toks = [t for t in tokenize_text(norm_fact) if len(t) >= 3]
    if not toks:
        return norm_fact in norm_ans
    ans_toks = set(tokenize_text(norm_ans))
    overlap = sum(1 for t in toks if t in ans_toks) / len(toks)
    return overlap >= 0.55


def run_deterministic_checks(
    case: EvalCase,
    response: AgentResponse,
    agent: AgentDefinition,
    valid_corpus_sources: set[str],
) -> DeterministicCheckResult:
    """Run primary cheap deterministic checks on one agent response."""
    answer = response.answer.strip()
    refusal_detected = is_refusal_text(answer)
    ref_words = max(12, len(case.reference_answer.split()))
    ans_words = len(answer.split())
    verbosity_ratio = round(ans_words / ref_words, 2)
    verbosity_flagged = verbosity_ratio > 2.5 and ans_words > 80

    # Citation validation
    retrieved_sources = {h.source_file for h in response.retrieved_chunks}
    expected_set = set(case.expected_source_docs)
    cited_set = set(response.citations)
    cited_expected = (
        True
        if not expected_set
        else any(
            any(exp in c for c in cited_set) or exp in answer
            for exp in expected_set
        )
    )
    # Check explicit [source: X] mentions exist in retrieved chunks or corpus.
    explicit_tags = re.findall(r"\[source:\s*([^\]]+)\]", answer, flags=re.I)
    allowed_names = retrieved_sources | valid_corpus_sources
    all_citations_valid = True
    for tag in explicit_tags:
        fname_part = tag.split(",")[0].strip()
        if fname_part and not any(src in fname_part or fname_part in src for src in allowed_names):
            all_citations_valid = False
            break

    # Number hallucination check against retrieved context + tool outputs + question.
    evidence_pool = "\n".join(
        [case.question]
        + [h.text for h in response.retrieved_chunks]
        + [tc.output for tc in response.tool_calls if tc.allowed]
    )
    evidence_nums = set(re.findall(r"\b\d+(?:\.\d+)?\b", evidence_pool))
    ans_nums = _extract_significant_numbers(answer)
    hallucinated = [n for n in ans_nums if n not in evidence_nums]

    # Format check
    format_ok = bool(answer) and ans_words <= int(agent.output_contract.max_length * 1.6)
    if case.expected_behavior == "answer" and not response.citations and not refusal_detected:
        # Missing citation is a format warning when contract asks for citations.
        if "citations" in agent.output_contract.required_fields:
            format_ok = False

    if case.expected_behavior == "refuse":
        det_pass = refusal_detected and len(hallucinated) == 0
        return DeterministicCheckResult(
            key_fact_coverage=1.0 if refusal_detected else 0.0,
            matched_facts=[],
            missed_facts=[],
            cited_expected_doc=True,
            all_citations_valid=all_citations_valid,
            refusal_detected=refusal_detected,
            format_ok=bool(answer),
            hallucinated_tokens=hallucinated,
            verbosity_ratio=verbosity_ratio,
            verbosity_flagged=verbosity_flagged,
            deterministic_pass=det_pass,
        )

    # Answerable / non-refusal edge case
    matched: list[str] = []
    missed: list[str] = []
    for fact in case.expected_key_facts:
        if _fact_matches_answer(fact, answer):
            matched.append(fact)
        else:
            missed.append(fact)
    coverage = (
        len(matched) / len(case.expected_key_facts)
        if case.expected_key_facts
        else (0.0 if refusal_detected else 1.0)
    )
    det_pass = (
        not refusal_detected
        and coverage >= 0.65
        and len(hallucinated) == 0
        and all_citations_valid
    )
    return DeterministicCheckResult(
        key_fact_coverage=round(coverage, 3),
        matched_facts=matched,
        missed_facts=missed,
        cited_expected_doc=cited_expected,
        all_citations_valid=all_citations_valid,
        refusal_detected=refusal_detected,
        format_ok=format_ok,
        hallucinated_tokens=hallucinated,
        verbosity_ratio=verbosity_ratio,
        verbosity_flagged=verbosity_flagged,
        deterministic_pass=det_pass,
    )


def classify_failure(
    case: EvalCase,
    response: AgentResponse,
    det: DeterministicCheckResult,
    llm_out: LLMJudgeOutput | None,
    llm: LLMClient | None = None,
) -> Literal["none", "retrieval_miss", "prompt_defect", "hallucination", "wrong_refusal"]:
    """Classify a failed case into exactly one root-cause category."""
    if case.expected_behavior == "refuse" and not det.refusal_detected:
        return "wrong_refusal"
    if case.expected_behavior == "answer" and det.refusal_detected:
        return "wrong_refusal"

    retrieved_sources = {h.source_file for h in response.retrieved_chunks}
    if (
        case.expected_behavior == "answer"
        and case.expected_source_docs
        and not any(exp in retrieved_sources for exp in case.expected_source_docs)
    ):
        # Tool-only queries might have answered via csv_lookup without chunk match.
        if not any(tc.allowed and tc.name == "csv_lookup" and tc.output for tc in response.tool_calls):
            return "retrieval_miss"

    if det.hallucinated_tokens or not det.all_citations_valid:
        return "hallucination"

    if llm_out is not None and not llm_out.grounded:
        return "hallucination"

    if det.key_fact_coverage < 0.65 or not det.format_ok:
        return "prompt_defect"

    if llm is not None:
        prompt = render_prompt(
            "optimizer_tiebreak",
            question=case.question,
            expected_behavior=case.expected_behavior,
            retrieved_sources=sorted(retrieved_sources),
            expected_sources=case.expected_source_docs,
            agent_answer=response.answer[:500],
            det_signals=det.model_dump_json(),
        )
        tb = llm.json_call(prompt, _TieBreakOutput, temperature=0.0, max_tokens=200)
        return tb.failure_category

    return "prompt_defect"


def _run_llm_judge_twice(
    case: EvalCase,
    response: AgentResponse,
    llm: LLMClient,
    judge_model: str,
) -> tuple[LLMJudgeOutput, bool]:
    """Run pointwise LLM judge twice at temp=0 with shuffled criteria to detect instability."""
    context_text = (
        "\n\n".join(
            f"[{h.source_file} | {h.page_or_section}]\n{h.text[:350]}"
            for h in response.retrieved_chunks
        )
        or "NO_RETRIEVED_CONTEXT"
    )
    tool_text = (
        "\n".join(
            f"{tc.name}({tc.args}) -> {tc.output[:300]}"
            for tc in response.tool_calls
            if tc.allowed
        )
        or "NO_TOOLS_CALLED"
    )

    outputs: list[LLMJudgeOutput] = []
    for criteria in (_CRITERIA_A, _CRITERIA_B):
        prompt = render_prompt(
            "judge_pointwise",
            criteria_block="\n".join(criteria),
            question=case.question,
            expected_behavior=case.expected_behavior,
            expected_key_facts=", ".join(case.expected_key_facts) or "(none — refusal expected)",
            reference_answer=case.reference_answer,
            retrieved_context=context_text,
            tool_outputs=tool_text,
            agent_answer=response.answer,
        )
        out = llm.json_call(
            prompt,
            LLMJudgeOutput,
            temperature=0.0,
            max_tokens=700,
            model=judge_model,
        )
        outputs.append(out)

    a, b = outputs[0], outputs[1]
    disagreement = (
        (a.grounded != b.grounded)
        or (a.correct != b.correct)
        or (a.refused_correctly != b.refused_correctly)
        or abs(a.score - b.score) > 0.35
    )
    avg_score = round((a.score + b.score) / 2.0, 3)
    merged = LLMJudgeOutput(
        grounded=a.grounded and b.grounded,
        correct=a.correct and b.correct,
        refused_correctly=a.refused_correctly and b.refused_correctly,
        score=avg_score,
        criteria=a.criteria,
        summary_reason=a.summary_reason if not disagreement else f"Disagreement between criteria orders: A={a.summary_reason} | B={b.summary_reason}",
    )
    return merged, disagreement


def judge_single_case(
    case: EvalCase,
    split: Literal["dev", "test"],
    response: AgentResponse,
    agent: AgentDefinition,
    valid_corpus_sources: set[str],
    llm: LLMClient | None,
    judge_model: str,
    use_llm_judge: bool = True,
) -> CaseJudgment:
    """Score one eval case combining deterministic checks (primary) and defended LLM judge."""
    det = run_deterministic_checks(case, response, agent, valid_corpus_sources)

    llm_out: LLMJudgeOutput | None = None
    disagreement = False
    if use_llm_judge and llm is not None:
        llm_out, disagreement = _run_llm_judge_twice(case, response, llm, judge_model)

    if llm_out is None or disagreement:
        # Fall back strictly to deterministic verdict when LLM judge disagrees or is disabled.
        final_pass = det.deterministic_pass
        grounded = len(det.hallucinated_tokens) == 0 and det.all_citations_valid
        correct = det.deterministic_pass
        refused_ok = (
            det.refusal_detected if case.expected_behavior == "refuse" else not det.refusal_detected
        )
        score = 1.0 if (case.expected_behavior == "refuse" and det.deterministic_pass) else det.key_fact_coverage
        if not grounded or not refused_ok:
            score = min(score, 0.25)
        confidence = 0.55 if disagreement else 0.90
        llm_verdict_str = "DISAGREEMENT_FALLBACK" if disagreement else "DETERMINISTIC_ONLY"
        evidence = "; ".join(det.missed_facts + det.hallucinated_tokens) or "Deterministic verdict"
    else:
        # Combine deterministic guardrails + consistent LLM verdict.
        grounded = llm_out.grounded and len(det.hallucinated_tokens) == 0 and det.all_citations_valid
        refused_ok = (
            det.refusal_detected
            if case.expected_behavior == "refuse"
            else (not det.refusal_detected and llm_out.refused_correctly)
        )
        correct = det.deterministic_pass and llm_out.correct
        if case.expected_behavior == "refuse":
            final_pass = refused_ok and len(det.hallucinated_tokens) == 0
            score = 1.0 if final_pass else 0.0
        else:
            # Blend deterministic key-fact coverage (primary 60%) + LLM rubric score (40%).
            score = round(0.6 * det.key_fact_coverage + 0.4 * llm_out.score, 3)
            if not grounded or not refused_ok:
                score = min(score, 0.35)
            final_pass = grounded and refused_ok and (det.key_fact_coverage >= 0.65) and (llm_out.correct or det.key_fact_coverage >= 0.85)
        confidence = 0.92
        llm_verdict_str = "PASS" if (llm_out.grounded and llm_out.correct and llm_out.refused_correctly) else "FAIL"
        evidence = llm_out.summary_reason

    failure_cat: Literal["none", "retrieval_miss", "prompt_defect", "hallucination", "wrong_refusal"] = "none"
    if not final_pass:
        failure_cat = classify_failure(
            case=case,
            response=response,
            det=det,
            llm_out=llm_out,
            llm=None,  # keep classification fast & deterministic by default
        )

    return CaseJudgment(
        case_id=case.id,
        split=split,
        category=case.category,
        question=case.question,
        answer=response.answer,
        expected_behavior=case.expected_behavior,
        retrieved_sources=sorted({h.source_file for h in response.retrieved_chunks}),
        expected_source_docs=case.expected_source_docs,
        tool_calls=response.tool_calls,
        deterministic=det,
        llm_verdict=llm_verdict_str,
        llm_confidence=confidence,
        llm_disagreement=disagreement,
        grounded=grounded,
        correct=correct,
        score=round(score, 3),
        refused_correctly=refused_ok,
        final_verdict="PASS" if final_pass else "FAIL",
        confidence=confidence,
        failure_category=failure_cat,
        evidence=evidence,
    )


def evaluate_agent(
    runner: AgentRunner,
    eval_set: EvalSet,
    settings: Settings,
    llm_judge: LLMClient | None = None,
    split_filter: Literal["all", "dev", "test"] = "all",
    use_llm_judge: bool = True,
) -> Scorecard:
    """Execute the agent via the shared runner on eval_set and compute Scorecard."""
    dev_set = set(eval_set.dev_ids)
    valid_sources = {c.source_file for c in runner.corpus.chunks}
    judgments: list[CaseJudgment] = []

    for case in eval_set.cases:
        split: Literal["dev", "test"] = "dev" if case.id in dev_set else "test"
        if split_filter != "all" and split != split_filter:
            continue
        response = runner.ask(case.question)
        j = judge_single_case(
            case=case,
            split=split,
            response=response,
            agent=runner.agent,
            valid_corpus_sources=valid_sources,
            llm=llm_judge or runner.llm,
            judge_model=settings.judge_model,
            use_llm_judge=use_llm_judge,
        )
        judgments.append(j)

    return build_scorecard(judgments, settings)


def build_scorecard(judgments: list[CaseJudgment], settings: Settings) -> Scorecard:
    """Aggregate CaseJudgments into an honest Scorecard."""
    total = len(judgments)
    if total == 0:
        return Scorecard(
            overall_score=0.0,
            dev_score=0.0,
            test_score=0.0,
            pass_rate=0.0,
            total_cases=0,
            passed_cases=0,
            judge_model=settings.judge_model,
            same_model_as_generator=settings.same_judge_model,
        )

    passed = sum(1 for j in judgments if j.final_verdict == "PASS")
    overall = round(sum(j.score for j in judgments) / total, 4)
    dev_j = [j for j in judgments if j.split == "dev"]
    test_j = [j for j in judgments if j.split == "test"]
    dev_score = round(sum(j.score for j in dev_j) / len(dev_j), 4) if dev_j else overall
    test_score = round(sum(j.score for j in test_j) / len(test_j), 4) if test_j else overall

    per_cat: dict[str, list[float]] = {}
    failure_counts: dict[str, int] = {
        "retrieval_miss": 0,
        "prompt_defect": 0,
        "hallucination": 0,
        "wrong_refusal": 0,
    }
    verbosity_warnings = 0
    for j in judgments:
        per_cat.setdefault(j.category, []).append(j.score)
        if j.failure_category != "none":
            failure_counts[j.failure_category] = failure_counts.get(j.failure_category, 0) + 1
        if j.deterministic.verbosity_flagged:
            verbosity_warnings += 1

    per_cat_avg = {k: round(sum(v) / len(v), 4) for k, v in per_cat.items()}
    note = (
        f"Judge uses {settings.judge_model}, which is the SAME model family as generator ({settings.llm_model}) — "
        "mitigated via deterministic primary checks, dual shuffled-criteria runs, and calibration testing, "
        "but residual self-preference bias cannot be fully ruled out."
        if settings.same_judge_model
        else f"Judge uses separate model {settings.judge_model} (generator={settings.llm_model})."
    )

    return Scorecard(
        overall_score=overall,
        dev_score=dev_score,
        test_score=test_score,
        pass_rate=round(passed / total, 4),
        total_cases=total,
        passed_cases=passed,
        per_category_scores=per_cat_avg,
        per_failure_type_counts=failure_counts,
        verbosity_warning_count=verbosity_warnings,
        judge_model=settings.judge_model,
        same_model_as_generator=settings.same_judge_model,
        judge_model_note=note,
        case_judgments=judgments,
    )


def pairwise_judge_both_orders(
    question: str,
    expected_behavior: str,
    reference_answer: str,
    answer_a: str,
    answer_b: str,
    llm: LLMClient,
    judge_model: str,
) -> Literal["A", "B", "TIE"]:
    """Run pairwise judging in both (A,B) and (B,A) orders; only consistent wins count."""
    p1 = render_prompt(
        "judge_pairwise",
        question=question,
        expected_behavior=expected_behavior,
        reference_answer=reference_answer,
        answer_a=answer_a,
        answer_b=answer_b,
    )
    p2 = render_prompt(
        "judge_pairwise",
        question=question,
        expected_behavior=expected_behavior,
        reference_answer=reference_answer,
        answer_a=answer_b,
        answer_b=answer_a,
    )
    r1 = llm.json_call(p1, PairwiseJudgeOutput, temperature=0.0, max_tokens=250, model=judge_model)
    r2 = llm.json_call(p2, PairwiseJudgeOutput, temperature=0.0, max_tokens=250, model=judge_model)
    # In r2, A and B are swapped: so r2=="B" agrees with r1=="A".
    if r1.winner == "A" and r2.winner == "B":
        return "A"
    if r1.winner == "B" and r2.winner == "A":
        return "B"
    return "TIE"


def _corrupt_numbers(text: str, rng: random.Random) -> str:
    def _bump(m: re.Match[str]) -> str:
        val = float(m.group(0))
        return str(int(val + 77) if val.is_integer() else round(val + 19.5, 2))

    mutated, count = re.subn(r"\b\d+(?:\.\d+)?\b", _bump, text, count=1)
    if count == 0:
        return text + " Exactly 99999 units and 420 days apply."
    return mutated


def run_judge_calibration(
    eval_set: EvalSet,
    agent: AgentDefinition,
    valid_corpus_sources: set[str],
    llm: LLMClient | None,
    settings: Settings,
    run_dir: Path | None = None,
    use_llm_judge: bool = True,
) -> JudgeCalibrationReport:
    """Self-test the judge on auto-constructed gold vs deliberately corrupted answers."""
    rng = random.Random(42)
    ans_cases = [c for c in eval_set.cases if c.expected_behavior == "answer" and c.expected_key_facts][:3]
    oos_cases = [c for c in eval_set.cases if c.expected_behavior == "refuse"][:2]

    samples: list[CalibrationSampleResult] = []

    def _check(sample_id: str, case: EvalCase, fake_answer: str, retrieved_docs: list[str], expected_pass: bool, label: str) -> None:
        from forgeai.schemas import RetrievedChunkHit

        hits = [
            RetrievedChunkHit(
                chunk_id=f"cal::{i}",
                source_file=doc,
                page_or_section="cal",
                text=f"{case.reference_answer} {' '.join(case.expected_key_facts)}",
                score=0.85,
            )
            for i, doc in enumerate(retrieved_docs)
        ]
        resp = AgentResponse(
            query=case.question,
            answer=fake_answer,
            citations=retrieved_docs if "[source:" in fake_answer else [],
            retrieved_chunks=hits,
            refused=is_refusal_text(fake_answer),
        )
        judgment = judge_single_case(
            case=case,
            split="dev",
            response=resp,
            agent=agent,
            valid_corpus_sources=valid_corpus_sources | set(retrieved_docs),
            llm=llm,
            judge_model=settings.judge_model,
            use_llm_judge=use_llm_judge,
        )
        pred_pass = judgment.final_verdict == "PASS"
        samples.append(
            CalibrationSampleResult(
                sample_id=sample_id,
                expected_pass=expected_pass,
                predicted_pass=pred_pass,
                matched=(pred_pass == expected_pass),
                reason=f"{label}: verdict={judgment.final_verdict} ({judgment.evidence[:120]})",
            )
        )

    for idx, c in enumerate(ans_cases, start=1):
        docs = c.expected_source_docs or ["doc.md"]
        gold_ans = f"{c.reference_answer} [source: {docs[0]}]"
        _check(f"gold_ans_{idx}", c, gold_ans, docs, True, "Gold answerable")

        corrupt_num_ans = f"{_corrupt_numbers(gold_ans, rng)}"
        _check(f"corrupt_num_{idx}", c, corrupt_num_ans, docs, False, "Corrupted numbers")

        if idx == 1:
            wrong_refuse = "I cannot answer this because it is outside the scope of the documents."
            _check("corrupt_false_refusal", c, wrong_refuse, docs, False, "False refusal on answerable")

    for idx, c in enumerate(oos_cases, start=1):
        gold_ref = f"I cannot answer this based on the provided documents: not covered."
        _check(f"gold_oos_{idx}", c, gold_ref, [], True, "Gold refusal")

        bad_ans = "Sure, the policy guarantees 45 days and a $5000 bonus automatically. [source: fabricated.pdf]"
        _check(f"corrupt_oos_halluc_{idx}", c, bad_ans, [], False, "Missing refusal + fabricated claim")

    total = len(samples)
    correct_preds = sum(1 for s in samples if s.matched)
    gold_samples = [s for s in samples if s.expected_pass]
    corrupt_samples = [s for s in samples if not s.expected_pass]

    report = JudgeCalibrationReport(
        total_samples=total,
        correct_predictions=correct_preds,
        accuracy=round(correct_preds / total, 4) if total else 0.0,
        gold_pass_rate=round(sum(1 for s in gold_samples if s.matched) / len(gold_samples), 4) if gold_samples else 0.0,
        corrupted_catch_rate=round(sum(1 for s in corrupt_samples if s.matched) / len(corrupt_samples), 4) if corrupt_samples else 0.0,
        samples=samples,
    )
    if run_dir is not None:
        (run_dir / "judge_calibration.json").write_text(
            report.model_dump_json(indent=2),
            encoding="utf-8",
        )
    return report
