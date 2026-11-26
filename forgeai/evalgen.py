"""Req 4: Grounded evaluation set generator with deterministic quality filters."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from forgeai.config import render_prompt
from forgeai.ingest import IngestedCorpus
from forgeai.llm import LLMClient
from forgeai.retrieval import HybridRetriever, tokenize_text
from forgeai.schemas import (
    AgentDefinition,
    DocumentChunk,
    EvalCase,
    EvalFilterStats,
    EvalSet,
    RequirementsSpec,
)

logger = logging.getLogger(__name__)


class _RawAnswerableCase(BaseModel):
    question: str
    expected_source_docs: list[str] = Field(default_factory=list)
    expected_key_facts: list[str] = Field(default_factory=list)
    reference_answer: str = ""


class _RawAnswerableBatch(BaseModel):
    cases: list[_RawAnswerableCase] = Field(default_factory=list)


class _RawOOSCase(BaseModel):
    question: str
    reason_out_of_scope: str = ""
    reference_answer: str = ""


class _RawOOSBatch(BaseModel):
    cases: list[_RawOOSCase] = Field(default_factory=list)


class _RawEdgeCase(BaseModel):
    edge_subtype: str = "ambiguous"
    question: str
    expected_source_docs: list[str] = Field(default_factory=list)
    expected_key_facts: list[str] = Field(default_factory=list)
    reference_answer: str = ""
    expected_behavior: Literal["answer", "refuse"] = "answer"
    requires_tool: str = ""


class _RawEdgeBatch(BaseModel):
    cases: list[_RawEdgeCase] = Field(default_factory=list)


def jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity of lowercased word tokens."""
    ta = set(tokenize_text(a))
    tb = set(tokenize_text(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def verify_fact_in_text(fact: str, source_text: str) -> bool:
    """Verify a short expected_key_fact literally or near-literally appears in source_text."""
    norm_fact = re.sub(r"\s+", " ", fact.lower()).strip()
    norm_src = re.sub(r"\s+", " ", source_text.lower()).strip()
    if not norm_fact or not norm_src:
        return False
    if norm_fact in norm_src:
        return True

    # Every number in the fact must appear in the source text.
    fact_nums = re.findall(r"\b\d+(?:\.\d+)?\b", norm_fact)
    src_nums = set(re.findall(r"\b\d+(?:\.\d+)?\b", norm_src))
    for num in fact_nums:
        if num not in src_nums:
            return False

    content_tokens = [t for t in tokenize_text(norm_fact) if len(t) >= 3]
    if not content_tokens:
        return False
    src_tokens = set(tokenize_text(norm_src))
    hits = sum(1 for t in content_tokens if t in src_tokens)
    return (hits / len(content_tokens)) >= 0.65


def sample_diverse_chunks(chunks: list[DocumentChunk], limit: int = 24) -> list[DocumentChunk]:
    """Sample chunks evenly across all source files so large folders stay bounded."""
    if len(chunks) <= limit:
        return list(chunks)
    by_file: dict[str, list[DocumentChunk]] = {}
    for ch in chunks:
        by_file.setdefault(ch.source_file, []).append(ch)
    sampled: list[DocumentChunk] = []
    idx = 0
    files = sorted(by_file.keys())
    while len(sampled) < limit:
        progressed = False
        for fname in files:
            group = by_file[fname]
            if idx < len(group):
                sampled.append(group[idx])
                progressed = True
                if len(sampled) >= limit:
                    break
        if not progressed:
            break
        idx += 1
    return sampled


def _format_chunks_for_prompt(chunks: list[DocumentChunk]) -> str:
    return "\n\n".join(
        f"--- CHUNK source_file={c.source_file} section={c.page_or_section} id={c.chunk_id} ---\n"
        f"{c.text[:900]}"
        for c in chunks
    )


def _stratified_split(cases: list[EvalCase]) -> tuple[list[str], list[str]]:
    """Split cases 50/50 into dev and held-out test sets stratified by category."""
    dev_ids: list[str] = []
    test_ids: list[str] = []
    by_cat: dict[str, list[EvalCase]] = {}
    for c in cases:
        by_cat.setdefault(c.category, []).append(c)
    for cat in sorted(by_cat.keys()):
        group = by_cat[cat]
        for idx, c in enumerate(group):
            if idx % 2 == 0:
                dev_ids.append(c.id)
            else:
                test_ids.append(c.id)
    return dev_ids, test_ids


def generate_eval_set(
    corpus: IngestedCorpus,
    retriever: HybridRetriever,
    requirements: RequirementsSpec,
    agent: AgentDefinition,
    llm: LLMClient,
    run_dir: Path,
    total_target: int = 30,
) -> EvalSet:
    """Generate and quality-filter >=20 grounded eval cases, frozen for the run."""
    target = max(20, int(total_target))
    quotas = {
        "answerable": max(10, round(target * 0.47)),
        "out_of_scope": max(5, round(target * 0.27)),
        "edge": max(5, target - max(10, round(target * 0.47)) - max(5, round(target * 0.27))),
    }

    doc_texts_by_file: dict[str, str] = {}
    for ch in corpus.chunks:
        doc_texts_by_file[ch.source_file] = (
            doc_texts_by_file.get(ch.source_file, "") + "\n" + ch.text
        )
    valid_files = set(doc_texts_by_file.keys())

    sampled = sample_diverse_chunks(corpus.chunks, limit=24)
    stats = EvalFilterStats()
    kept_by_cat: dict[str, list[EvalCase]] = {
        "answerable": [],
        "out_of_scope": [],
        "edge": [],
    }
    kept_questions: list[str] = []
    case_seq = 0

    def _is_duplicate(q: str) -> bool:
        return any(jaccard_similarity(q, prev) >= 0.72 for prev in kept_questions)

    def _next_id(prefix: str) -> str:
        nonlocal case_seq
        case_seq += 1
        return f"{prefix}_{case_seq:03d}"

    # Seed out_of_scope cases deterministically from demoted/must-refuse topics first.
    for topic in requirements.must_refuse_topics:
        if len(kept_by_cat["out_of_scope"]) >= quotas["out_of_scope"] // 2 + 1:
            break
        clean_topic = re.sub(r"\s*\(unsupported.*?\)\s*", "", topic, flags=re.I).strip()
        if not clean_topic:
            continue
        q = f"What does the policy or documentation say about {clean_topic}?"
        if not _is_duplicate(q) and retriever.max_raw_score(q) < 0.62:
            stats.raw_generated += 1
            kept_questions.append(q)
            kept_by_cat["out_of_scope"].append(
                EvalCase(
                    id=_next_id("oos"),
                    category="out_of_scope",
                    question=q,
                    expected_source_docs=[],
                    expected_key_facts=[],
                    reference_answer=f"I cannot answer questions about {clean_topic} because it is not covered in the provided documents.",
                    expected_behavior="refuse",
                )
            )

    # 1. Generate answerable cases (up to 3 batches if filtering drops items).
    chunk_batches = [sampled[i : i + 6] for i in range(0, len(sampled), 6)] or [sampled]
    for attempt in range(4):
        need = quotas["answerable"] - len(kept_by_cat["answerable"])
        if need <= 0:
            break
        batch_chunks = chunk_batches[attempt % len(chunk_batches)]
        ask_count = min(need + 3, 10)
        prompt = render_prompt(
            "evalgen_answerable",
            count=ask_count,
            chunks_text=_format_chunks_for_prompt(batch_chunks),
        )
        batch = llm.json_call(prompt, _RawAnswerableBatch, temperature=0.2, max_tokens=1800)
        for raw in batch.cases:
            stats.raw_generated += 1
            q = raw.question.strip()
            src_docs = [d.strip() for d in raw.expected_source_docs if d.strip() in valid_files]
            facts = [f.strip() for f in raw.expected_key_facts if f.strip()]
            if not q or not src_docs or not facts:
                stats.discarded_invalid_schema += 1
                continue
            if _is_duplicate(q):
                stats.discarded_duplicate += 1
                continue
            combined_src = "\n".join(doc_texts_by_file[d] for d in src_docs)
            if not all(verify_fact_in_text(f, combined_src) for f in facts):
                stats.discarded_ungrounded_facts += 1
                continue
            kept_questions.append(q)
            kept_by_cat["answerable"].append(
                EvalCase(
                    id=_next_id("ans"),
                    category="answerable",
                    question=q,
                    expected_source_docs=src_docs,
                    expected_key_facts=facts,
                    reference_answer=raw.reference_answer.strip() or "; ".join(facts),
                    expected_behavior="answer",
                )
            )
            if len(kept_by_cat["answerable"]) >= quotas["answerable"]:
                break

    # 2. Generate out_of_scope cases.
    doc_summary = (
        f"Files: {sorted(valid_files)}\n"
        f"Topics: {', '.join(corpus.profile.topic_keywords[:20])}\n"
        f"Must-answer topics: {', '.join(requirements.must_answer_topics)}"
    )
    for _attempt in range(3):
        need = quotas["out_of_scope"] - len(kept_by_cat["out_of_scope"])
        if need <= 0:
            break
        prompt = render_prompt(
            "evalgen_out_of_scope",
            count=need + 2,
            must_refuse_topics=", ".join(requirements.must_refuse_topics) or "none",
            doc_summary=doc_summary,
        )
        batch = llm.json_call(prompt, _RawOOSBatch, temperature=0.2, max_tokens=1400)
        for raw in batch.cases:
            stats.raw_generated += 1
            q = raw.question.strip()
            if not q:
                stats.discarded_invalid_schema += 1
                continue
            if _is_duplicate(q):
                stats.discarded_duplicate += 1
                continue
            if retriever.max_raw_score(q) >= 0.62:
                stats.discarded_oos_matched_docs += 1
                continue
            kept_questions.append(q)
            kept_by_cat["out_of_scope"].append(
                EvalCase(
                    id=_next_id("oos"),
                    category="out_of_scope",
                    question=q,
                    expected_source_docs=[],
                    expected_key_facts=[],
                    reference_answer=raw.reference_answer.strip()
                    or "I cannot answer this because the provided documents do not cover it.",
                    expected_behavior="refuse",
                )
            )
            if len(kept_by_cat["out_of_scope"]) >= quotas["out_of_scope"]:
                break

    # 3. Generate edge cases (multi_doc, ambiguous, tool_use, prompt_injection).
    tool_instruction = (
        f"requires using one of the allowed tools ({', '.join(agent.tools)}) with values from the chunks"
        if agent.tools
        else "since no tools are attached, skip tool_use and create ambiguous or multi_doc instead"
    )
    for attempt in range(3):
        need = quotas["edge"] - len(kept_by_cat["edge"])
        if need <= 0:
            break
        batch_chunks = chunk_batches[(attempt + 1) % len(chunk_batches)]
        prompt = render_prompt(
            "evalgen_edge",
            count=need + 3,
            tool_instruction=tool_instruction,
            allowed_tools=", ".join(agent.tools) or "none",
            chunks_text=_format_chunks_for_prompt(batch_chunks),
        )
        batch = llm.json_call(prompt, _RawEdgeBatch, temperature=0.2, max_tokens=1600)
        for raw in batch.cases:
            stats.raw_generated += 1
            q = raw.question.strip()
            if not q:
                stats.discarded_invalid_schema += 1
                continue
            if _is_duplicate(q):
                stats.discarded_duplicate += 1
                continue
            src_docs = [d.strip() for d in raw.expected_source_docs if d.strip() in valid_files]
            facts = [f.strip() for f in raw.expected_key_facts if f.strip()]
            behavior = raw.expected_behavior
            if behavior == "answer":
                if not src_docs or not facts:
                    stats.discarded_invalid_schema += 1
                    continue
                combined_src = "\n".join(doc_texts_by_file[d] for d in src_docs)
                # For tool_use (e.g. calculator computing derived totals), at least half of
                # facts (base part/price facts) must appear verbatim in source docs.
                if raw.requires_tool and raw.requires_tool in agent.tools:
                    ok = any(verify_fact_in_text(f, combined_src) for f in facts)
                else:
                    ok = all(verify_fact_in_text(f, combined_src) for f in facts)
                if not ok:
                    stats.discarded_ungrounded_facts += 1
                    continue

            kept_questions.append(q)
            kept_by_cat["edge"].append(
                EvalCase(
                    id=_next_id("edge"),
                    category="edge",
                    edge_subtype=raw.edge_subtype.strip() or "edge",
                    question=q,
                    expected_source_docs=src_docs,
                    expected_key_facts=facts,
                    reference_answer=raw.reference_answer.strip(),
                    expected_behavior=behavior,
                    requires_tool=raw.requires_tool if raw.requires_tool in agent.tools else "",
                )
            )
            if len(kept_by_cat["edge"]) >= quotas["edge"]:
                break

    all_cases = (
        kept_by_cat["answerable"]
        + kept_by_cat["out_of_scope"]
        + kept_by_cat["edge"]
    )
    stats.kept_total = len(all_cases)
    stats.kept_by_category = {k: len(v) for k, v in kept_by_cat.items()}
    dev_ids, test_ids = _stratified_split(all_cases)

    eval_set = EvalSet(
        cases=all_cases,
        dev_ids=dev_ids,
        test_ids=test_ids,
        filter_stats=stats,
    )
    (run_dir / "eval_set.json").write_text(
        eval_set.model_dump_json(indent=2),
        encoding="utf-8",
    )
    logger.info(
        "Generated eval_set.json: %d kept (%s), discarded=%d dup, %d ungrounded, %d oos_match",
        stats.kept_total,
        stats.kept_by_category,
        stats.discarded_duplicate,
        stats.discarded_ungrounded_facts,
        stats.discarded_oos_matched_docs,
    )
    return eval_set
