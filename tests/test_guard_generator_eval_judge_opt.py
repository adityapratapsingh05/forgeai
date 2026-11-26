"""Tests for groundability, tool post-check, eval filters, judge checks/calibration, and optimizer caps."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from forgeai.budget import BudgetTracker
from forgeai.config import Settings
from forgeai.evalgen import jaccard_similarity, sample_diverse_chunks, verify_fact_in_text
from forgeai.generator import enforce_tool_selection
from forgeai.groundability import assess_topic_deterministically, run_groundability_guard
from forgeai.ingest import ingest_corpus
from forgeai.judge import classify_failure, run_deterministic_checks, run_judge_calibration
from forgeai.llm import LLMClient
from forgeai.optimizer import HARD_MAX_ITERATIONS, _contains_eval_question, run_optimizer
from forgeai.retrieval import HybridRetriever
from forgeai.schemas import (
    AgentDefinition,
    AgentResponse,
    CSVTableProfile,
    DocProfile,
    DocumentChunk,
    EvalCase,
    EvalSet,
    GeneratedFromMeta,
    OutputContract,
    RefusalPolicy,
    RequirementsSpec,
    RetrievalConfig,
    RetrievedChunkHit,
)
from forgeai.tools.registry import build_tool_registry


def test_groundability_deterministic_floor() -> None:
    assert assess_topic_deterministically("SUPPORTED", max_score=0.05, keyword_overlap=0.05) == "UNSUPPORTED"
    assert assess_topic_deterministically("SUPPORTED", max_score=0.45, keyword_overlap=0.50) == "SUPPORTED"
    assert assess_topic_deterministically("SUPPORTED", max_score=0.35, keyword_overlap=0.10) == "PARTIAL"


def test_groundability_recognizes_csv_fields_even_when_judge_disagrees(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "spares_catalogue.csv").write_text(
        "part_no,part_name,unit_price,lead_time_days\n"
        "SP1001,Main Engine Oil Cooler,1250,15\n",
        encoding="utf-8",
    )
    requirements = RequirementsSpec(
        brief="Look up spare-part pricing and lead times.",
        scope="Spares catalogue",
        audience="Procurement officers",
        tone="technical",
        must_answer_topics=["Unit price and lead time retrieval"],
    )
    retrieval = RetrievalConfig(hybrid_alpha=0.0)
    corpus = ingest_corpus(docs_dir, retrieval)
    retriever = HybridRetriever(corpus.chunks, retrieval)

    class RejectingGroundabilityJudge:
        def json_call(self, prompt, pydantic_schema, **kwargs):
            return pydantic_schema(status="UNSUPPORTED", reason="No matching prose evidence.")

    report, updated_requirements = run_groundability_guard(
        requirements=requirements,
        retriever=retriever,
        llm=RejectingGroundabilityJudge(),
        run_dir=tmp_path / "run",
    )

    assert report.items[0].status == "SUPPORTED"
    assert "spares_catalogue.csv" in report.items[0].evidence_sources
    assert updated_requirements.must_answer_topics == ["Unit price and lead time retrieval"]
    assert not updated_requirements.must_refuse_topics


def test_tool_selection_post_check() -> None:
    registry = build_tool_registry({})
    hr_reqs = RequirementsSpec(
        brief="Answer HR leave, travel, and conduct policy questions for shore staff.",
        scope="HR policies",
        audience="Shore staff",
        tone="professional",
        must_answer_topics=["annual leave", "expense reimbursement"],
    )
    hr_profile = DocProfile(
        docs_dir="demos/hr_policy/docs",
        file_count=3,
        files=[],
        total_bytes=1000,
        doc_types=["md"],
        topic_keywords=["leave", "travel", "policy"],
        has_tabular_data=False,
        csv_tables=[],
        doc_hash="abc",
    )
    # Even if LLM wrongly proposes open_meteo and csv_lookup, post-check MUST reject them.
    tools, rationale = enforce_tool_selection(
        proposed_tools=["open_meteo", "csv_lookup", "current_date"],
        llm_rationale=[],
        requirements=hr_reqs,
        doc_profile=hr_profile,
        registry=registry,
    )
    assert "open_meteo" not in tools
    assert "csv_lookup" not in tools
    assert "current_date" not in tools
    assert len(rationale) == len(registry.list_names())

    spares_reqs = RequirementsSpec(
        brief="Look up marine spare parts in the CSV catalogue and calculate total quote costs for quantities.",
        scope="Spares procurement",
        audience="Procurement officers",
        tone="concise",
        must_answer_topics=["part lookup", "calculate total order cost"],
    )
    spares_profile = DocProfile(
        docs_dir="demos/ship_spares/docs",
        file_count=3,
        files=[],
        total_bytes=2000,
        doc_types=["csv", "md"],
        topic_keywords=["part", "price", "supplier"],
        has_tabular_data=True,
        csv_tables=[CSVTableProfile(filename="spares.csv", row_count=60, columns=["part_no", "unit_price"])],
        doc_hash="def",
    )
    spares_tools, _ = enforce_tool_selection(
        proposed_tools=["open_meteo"],
        llm_rationale=[],
        requirements=spares_reqs,
        doc_profile=spares_profile,
        registry=registry,
    )
    assert "csv_lookup" in spares_tools
    assert "calculator" in spares_tools
    assert "open_meteo" not in spares_tools


def test_evalgen_quality_filters() -> None:
    src = "Full-time staff get 24 days of annual leave and up to 5 days carry-over."
    assert verify_fact_in_text("24 days of annual leave", src) is True
    assert verify_fact_in_text("45 days of annual leave", src) is False
    assert jaccard_similarity("How many annual leave days?", "How many days of annual leave?") >= 0.72

    chunks = [
        DocumentChunk(chunk_id=f"a::{i}", source_file="a.md", text=f"text {i}", doc_type="md")
        for i in range(10)
    ] + [
        DocumentChunk(chunk_id=f"b::{i}", source_file="b.md", text=f"text {i}", doc_type="md")
        for i in range(10)
    ]
    sampled = sample_diverse_chunks(chunks, limit=6)
    assert len(sampled) == 6
    assert {c.source_file for c in sampled} == {"a.md", "b.md"}


def _sample_agent() -> AgentDefinition:
    return AgentDefinition(
        name="Test Agent",
        description="HR test agent",
        system_prompt="Answer strictly from documents.",
        tone="professional",
        retrieval=RetrievalConfig(hybrid_alpha=0.0),
        tools=[],
        output_contract=OutputContract(),
        refusal_policy=RefusalPolicy(must_refuse_topics=["stock options"]),
        generated_from=GeneratedFromMeta(
            requirements_hash="r1", doc_hash="d1", factory_version="0.1.0", timestamp="now"
        ),
    )


def test_deterministic_judge_and_calibration(tmp_path: Path) -> None:
    agent = _sample_agent()
    case_ans = EvalCase(
        id="ans_1",
        category="answerable",
        question="How many annual leave days do shore staff get?",
        expected_source_docs=["leave.md"],
        expected_key_facts=["24 days annual leave"],
        reference_answer="Shore staff receive 24 days annual leave per year.",
        expected_behavior="answer",
    )
    case_oos = EvalCase(
        id="oos_1",
        category="out_of_scope",
        question="How do employee stock options vest?",
        expected_source_docs=[],
        expected_key_facts=[],
        reference_answer="Not covered in the documents.",
        expected_behavior="refuse",
    )

    good_resp = AgentResponse(
        query=case_ans.question,
        answer="Shore staff receive 24 days annual leave per year. [source: leave.md, section-1]",
        citations=["leave.md"],
        retrieved_chunks=[
            RetrievedChunkHit(
                chunk_id="c1",
                source_file="leave.md",
                page_or_section="section-1",
                text="Shore staff receive 24 days annual leave per year.",
                score=0.8,
            )
        ],
    )
    det_good = run_deterministic_checks(case_ans, good_resp, agent, {"leave.md"})
    assert det_good.deterministic_pass is True
    assert det_good.hallucinated_tokens == []

    halluc_resp = AgentResponse(
        query=case_ans.question,
        answer="Shore staff receive 24 days annual leave plus a $5000 travel bonus. [source: leave.md]",
        citations=["leave.md"],
        retrieved_chunks=good_resp.retrieved_chunks,
    )
    det_halluc = run_deterministic_checks(case_ans, halluc_resp, agent, {"leave.md"})
    assert det_halluc.deterministic_pass is False
    assert "5000" in det_halluc.hallucinated_tokens
    assert classify_failure(case_ans, halluc_resp, det_halluc, None) == "hallucination"

    # Calibration self-test in deterministic mode
    eval_set = EvalSet(cases=[case_ans, case_oos], dev_ids=["ans_1", "oos_1"], test_ids=[])
    settings = Settings(
        llm_base_url="http://mock/v1",
        llm_model="m",
        llm_api_key="k",
        embed_model="e",
        judge_model="m",
        timeout_seconds=5,
        max_retries=1,
        cache_dir=tmp_path,
    )
    cal = run_judge_calibration(
        eval_set=eval_set,
        agent=agent,
        valid_corpus_sources={"leave.md"},
        llm=None,
        settings=settings,
        run_dir=tmp_path,
        use_llm_judge=False,
    )
    assert cal.accuracy == 1.0
    assert cal.corrupted_catch_rate == 1.0


def test_optimizer_hard_cap_and_revert(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "leave.md").write_text("Shore staff receive 24 days annual leave.", encoding="utf-8")

    # Mock LLM that causes the agent to give a slightly worse answer after patch -> triggers REVERT.
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        msgs = body.get("messages", [])
        sys_txt = msgs[0]["content"] if msgs else ""
        user_txt = msgs[-1]["content"] if msgs else ""
        if "Prompt Optimizer" in sys_txt or "CURRENT SYSTEM PROMPT" in user_txt:
            content = json.dumps(
                {
                    "updated_system_prompt": "PATCHED_WORSE_PROMPT: Always refuse everything.",
                    "change_summary": "Over-strict patch",
                }
            )
        elif "PATCHED_WORSE_PROMPT" in sys_txt:
            content = "I cannot answer this."
        else:
            content = "Shore staff receive 24 days annual leave. [source: leave.md]"
        call_count["n"] += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    settings = Settings(
        llm_base_url="http://mock/v1",
        llm_model="m",
        llm_api_key="k",
        embed_model="e",
        judge_model="m",
        timeout_seconds=5,
        max_retries=1,
        cache_dir=tmp_path / "cache",
    )
    llm = LLMClient(
        settings=settings,
        budget=BudgetTracker(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    eval_set = EvalSet(
        cases=[
            EvalCase(
                id="ans_1",
                category="answerable",
                question="How many annual leave days?",
                expected_source_docs=["leave.md"],
                expected_key_facts=["24 days annual leave", "carryover 5 days"],
                reference_answer="24 days annual leave",
                expected_behavior="answer",
            ),
            EvalCase(
                id="ans_2",
                category="answerable",
                question="Do shore staff get annual leave?",
                expected_source_docs=["leave.md"],
                expected_key_facts=["24 days annual leave"],
                reference_answer="24 days annual leave",
                expected_behavior="answer",
            ),
        ],
        dev_ids=["ans_1"],
        test_ids=["ans_2"],
    )
    assert _contains_eval_question("Answer: How many annual leave days?", eval_set) is True

    agent = _sample_agent()
    final_agent, init_sc, final_sc, log = run_optimizer(
        initial_agent=agent,
        docs_dir=docs_dir,
        eval_set=eval_set,
        llm=llm,
        settings=settings,
        run_dir=tmp_path / "run",
        max_iters=10,  # Should be hard-capped to 3
        target_score=0.95,
        use_llm_judge=False,
    )
    assert log.max_iterations == HARD_MAX_ITERATIONS == 3
    assert len(log.iterations) == 1
    assert log.iterations[0].accepted is False
    assert "REVERTED" in log.iterations[0].status_note
    assert final_agent.system_prompt == agent.system_prompt
    assert final_sc.dev_score == init_sc.dev_score
