"""Req 2: Groundability guard — verify requested topics against actual document support."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from forgeai.config import render_prompt
from forgeai.intake import save_requirements
from forgeai.llm import LLMClient
from forgeai.retrieval import HybridRetriever, token_overlap_ratio
from forgeai.schemas import GroundabilityItem, GroundabilityReport, RequirementsSpec

logger = logging.getLogger(__name__)


class _LLMGroundabilityVerdict(BaseModel):
    status: Literal["SUPPORTED", "PARTIAL", "UNSUPPORTED"]
    reason: str


def assess_topic_deterministically(
    llm_status: Literal["SUPPORTED", "PARTIAL", "UNSUPPORTED"],
    max_score: float,
    keyword_overlap: float,
) -> Literal["SUPPORTED", "PARTIAL", "UNSUPPORTED"]:
    """Combine LLM judgment with deterministic retrieval & keyword-overlap floors."""
    if max_score < 0.14 or keyword_overlap < 0.18:
        if max_score < 0.10 and keyword_overlap < 0.15:
            return "UNSUPPORTED"
        if llm_status == "UNSUPPORTED":
            return "UNSUPPORTED"
        return "PARTIAL" if llm_status == "SUPPORTED" else llm_status
    if llm_status == "UNSUPPORTED":
        return "UNSUPPORTED"
    if llm_status == "PARTIAL" or keyword_overlap < 0.30:
        return "PARTIAL"
    return "SUPPORTED"


def run_groundability_guard(
    requirements: RequirementsSpec,
    retriever: HybridRetriever,
    llm: LLMClient,
    run_dir: Path,
) -> tuple[GroundabilityReport, RequirementsSpec]:
    """Verify every must_answer_topic against corpus evidence and demote unsupported ones."""
    topics = list(dict.fromkeys(t.strip() for t in requirements.must_answer_topics if t.strip()))
    if not topics:
        topics = [requirements.brief[:200]]

    items: list[GroundabilityItem] = []
    supported: list[str] = []
    partial: list[str] = []
    unsupported: list[str] = []

    for topic in topics:
        hits = retriever.search(topic, top_k=4, apply_min_score=False)
        max_score = hits[0].score if hits else 0.0
        snippet_texts = [h.text for h in hits]
        overlap = token_overlap_ratio(topic, snippet_texts)

        evidence_text = (
            "\n\n".join(
                f"[{h.source_file} | {h.page_or_section} | score={h.score}]\n{h.text[:400]}"
                for h in hits
            )
            if hits
            else "NO_RETRIEVED_EVIDENCE"
        )
        prompt = render_prompt(
            "groundability_check",
            topic=topic,
            evidence_text=evidence_text,
        )
        verdict = llm.json_call(prompt, _LLMGroundabilityVerdict, temperature=0.0, max_tokens=400)
        final_status = assess_topic_deterministically(verdict.status, max_score, overlap)

        item = GroundabilityItem(
            topic=topic,
            status=final_status,
            retrieval_score=round(max_score, 4),
            keyword_overlap=round(overlap, 4),
            evidence_snippets=[h.text[:220] for h in hits[:2]],
            evidence_sources=list(dict.fromkeys(h.source_file for h in hits[:3])),
            reason=verdict.reason,
        )
        items.append(item)
        if final_status == "SUPPORTED":
            supported.append(topic)
        elif final_status == "PARTIAL":
            partial.append(topic)
        else:
            unsupported.append(topic)

    mostly_unsupported = len(unsupported) > (len(supported) + len(partial))
    warnings: list[str] = []
    if unsupported:
        warnings.append(
            f"Groundability Guard flagged {len(unsupported)} UNSUPPORTED topic(s) and moved them to must_refuse: "
            + ", ".join(unsupported)
        )
    if mostly_unsupported:
        warnings.append(
            "WARNING: Majority of requested topics are UNSUPPORTED by the document folder! "
            "Generated agent will strictly cover only the supported subset."
        )

    for w in warnings:
        logger.warning("%s", w)

    # Mutate updated requirements so generator NEVER promises unsupported topics.
    updated_reqs = requirements.model_copy(deep=True)
    if unsupported:
        unsupported_lower = {u.lower() for u in unsupported}
        updated_reqs.must_answer_topics = [
            t for t in updated_reqs.must_answer_topics if t.lower() not in unsupported_lower
        ]
        for u in unsupported:
            entry = f"{u} (unsupported by provided documents)"
            if not any(u.lower() in r.lower() for r in updated_reqs.must_refuse_topics):
                updated_reqs.must_refuse_topics.append(entry)
        updated_reqs.open_risks.append(
            "Groundability Guard demoted unsupported topics to refusal: " + "; ".join(unsupported)
        )
    if partial:
        updated_reqs.assumptions.append(
            "Partial document coverage on: " + "; ".join(partial) + " — agent must answer only what is explicitly documented."
        )

    save_requirements(updated_reqs, run_dir)

    report = GroundabilityReport(
        items=items,
        supported_topics=supported,
        partial_topics=partial,
        unsupported_topics=unsupported,
        mostly_unsupported=mostly_unsupported,
        warnings=warnings,
    )
    (run_dir / "groundability_report.json").write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return report, updated_reqs
