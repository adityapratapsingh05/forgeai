"""Pydantic v2 data contracts for all ForgeAI artifacts."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class DocumentChunk(BaseModel):
    """A single indexed chunk of a source document."""

    chunk_id: str
    source_file: str
    page_or_section: str = "section-1"
    text: str
    doc_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CSVTableProfile(BaseModel):
    """Summary metadata for an ingested CSV table."""

    filename: str
    row_count: int
    columns: list[str]
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)


class FileSummary(BaseModel):
    """Metadata for a single file in the document folder."""

    filename: str
    size_bytes: int
    doc_type: str
    title: str = ""
    headings: list[str] = Field(default_factory=list)
    word_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class DocProfile(BaseModel):
    """Auto-generated profile of a document folder."""

    docs_dir: str
    file_count: int
    files: list[FileSummary]
    total_bytes: int
    doc_types: list[str]
    topic_keywords: list[str]
    has_tabular_data: bool = False
    csv_tables: list[CSVTableProfile] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    doc_hash: str


class ClarifierQA(BaseModel):
    """A single intake clarifying question and answer."""

    question: str
    target_dimension: str = "scope"
    answer: str


class RequirementsSpec(BaseModel):
    """Structured requirements produced by the intake stage."""

    brief: str
    scope: str
    audience: str
    tone: str
    must_answer_topics: list[str] = Field(default_factory=list)
    must_refuse_topics: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_risks: list[str] = Field(default_factory=list)
    clarifier_qa: list[ClarifierQA] = Field(default_factory=list)
    requirements_hash: str = ""


class GroundabilityItem(BaseModel):
    """Groundability assessment for one topic or brief capability."""

    topic: str
    status: Literal["SUPPORTED", "PARTIAL", "UNSUPPORTED"]
    retrieval_score: float = 0.0
    keyword_overlap: float = 0.0
    evidence_snippets: list[str] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)
    reason: str = ""


class GroundabilityReport(BaseModel):
    """Full groundability verification report across all requested topics."""

    items: list[GroundabilityItem] = Field(default_factory=list)
    supported_topics: list[str] = Field(default_factory=list)
    partial_topics: list[str] = Field(default_factory=list)
    unsupported_topics: list[str] = Field(default_factory=list)
    mostly_unsupported: bool = False
    warnings: list[str] = Field(default_factory=list)


class RetrievalConfig(BaseModel):
    """Declarative retrieval configuration embedded in agent_definition.yaml."""

    chunk_size: int = Field(default=600, ge=150, le=3000)
    overlap: int = Field(default=80, ge=0, le=500)
    strategy: Literal["fixed", "paragraph", "heading-aware"] = "heading-aware"
    top_k: int = Field(default=5, ge=1, le=20)
    hybrid_alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    min_score: float = Field(default=0.20, ge=0.0, le=1.0)

    @field_validator("overlap")
    @classmethod
    def _validate_overlap(cls, v: int, info: Any) -> int:
        chunk_size = info.data.get("chunk_size", 600)
        if v >= chunk_size:
            return max(0, chunk_size // 4)
        return v


class OutputContract(BaseModel):
    """Structured output requirements for the generated agent."""

    format: str = "answer_with_citations"
    required_fields: list[str] = Field(default_factory=lambda: ["answer", "citations"])
    citation_style: str = "[source: filename, section]"
    refusal_message_template: str = (
        "I cannot answer this based on the provided documents: {reason}. "
        "Please consult an appropriate human contact."
    )
    max_length: int = Field(default=350, ge=50, le=2000)


class ToolSelectionEntry(BaseModel):
    """Inclusion or exclusion rationale for a single registry tool."""

    name: str
    included: bool
    reason: str


class RefusalPolicy(BaseModel):
    """Explicit refusal boundaries for the agent."""

    must_refuse_topics: list[str] = Field(default_factory=list)
    out_of_scope_behavior: str = (
        "Politely refuse using the refusal_message_template when evidence is missing or out of scope."
    )


class GeneratedFromMeta(BaseModel):
    """Provenance metadata for an agent definition."""

    requirements_hash: str
    doc_hash: str
    factory_version: str
    timestamp: str


class AgentDefinition(BaseModel):
    """Declarative YAML schema for a generated ForgeAI agent."""

    name: str
    description: str
    system_prompt: str
    tone: str
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    tools: list[str] = Field(default_factory=list)
    tool_selection_rationale: list[ToolSelectionEntry] = Field(default_factory=list)
    output_contract: OutputContract = Field(default_factory=OutputContract)
    refusal_policy: RefusalPolicy = Field(default_factory=RefusalPolicy)
    generated_from: GeneratedFromMeta


class EvalCase(BaseModel):
    """A single evaluation case generated from the source documents."""

    id: str
    category: Literal["answerable", "out_of_scope", "edge"]
    edge_subtype: str = ""
    question: str
    expected_source_docs: list[str] = Field(default_factory=list)
    expected_key_facts: list[str] = Field(default_factory=list)
    reference_answer: str = ""
    expected_behavior: Literal["answer", "refuse"] = "answer"
    requires_tool: str = ""
    source_chunk_id: str = ""


class EvalFilterStats(BaseModel):
    """Audit counts for quality filters applied during eval generation."""

    raw_generated: int = 0
    discarded_duplicate: int = 0
    discarded_ungrounded_facts: int = 0
    discarded_oos_matched_docs: int = 0
    discarded_invalid_schema: int = 0
    kept_total: int = 0
    kept_by_category: dict[str, int] = Field(default_factory=dict)


class EvalSet(BaseModel):
    """Frozen evaluation suite split into dev and held-out test sets."""

    cases: list[EvalCase]
    dev_ids: list[str] = Field(default_factory=list)
    test_ids: list[str] = Field(default_factory=list)
    filter_stats: EvalFilterStats = Field(default_factory=EvalFilterStats)


class ToolCallRecord(BaseModel):
    """Trace of one tool execution during an agent turn."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    output: str = ""
    allowed: bool = True
    error: str = ""


class RetrievedChunkHit(BaseModel):
    """A retrieved chunk with its hybrid and component scores."""

    chunk_id: str
    source_file: str
    page_or_section: str
    text: str
    score: float
    bm25_score: float = 0.0
    embed_score: float = 0.0


class AgentResponse(BaseModel):
    """Output returned by forgeai.agent_runner for one user query."""

    query: str
    answer: str
    citations: list[str] = Field(default_factory=list)
    retrieved_chunks: list[RetrievedChunkHit] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    refused: bool = False
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class DeterministicCheckResult(BaseModel):
    """Deterministic scoring signals for a single eval case."""

    key_fact_coverage: float = 0.0
    matched_facts: list[str] = Field(default_factory=list)
    missed_facts: list[str] = Field(default_factory=list)
    cited_expected_doc: bool = False
    all_citations_valid: bool = True
    refusal_detected: bool = False
    format_ok: bool = True
    hallucinated_tokens: list[str] = Field(default_factory=list)
    verbosity_ratio: float = 1.0
    verbosity_flagged: bool = False
    deterministic_pass: bool = False


class LLMJudgeCriterion(BaseModel):
    """Single criterion verdict returned by the LLM judge."""

    criterion: str
    passed: bool
    evidence_quote: str = ""
    reason: str = ""


class LLMJudgeOutput(BaseModel):
    """Structured JSON returned by the pointwise LLM judge."""

    grounded: bool
    correct: bool
    refused_correctly: bool
    score: float = Field(ge=0.0, le=1.0)
    criteria: list[LLMJudgeCriterion] = Field(default_factory=list)
    summary_reason: str = ""


class PairwiseJudgeOutput(BaseModel):
    """Structured JSON returned by the pairwise LLM judge."""

    winner: Literal["A", "B", "TIE"]
    reason: str = ""


class CaseJudgment(BaseModel):
    """Complete per-case evaluation output."""

    case_id: str
    split: Literal["dev", "test"] = "dev"
    category: Literal["answerable", "out_of_scope", "edge"]
    question: str
    answer: str
    expected_behavior: Literal["answer", "refuse"]
    retrieved_sources: list[str] = Field(default_factory=list)
    expected_source_docs: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    deterministic: DeterministicCheckResult
    llm_verdict: str = "PASS"
    llm_confidence: float = 1.0
    llm_disagreement: bool = False
    grounded: bool
    correct: bool
    score: float
    refused_correctly: bool
    final_verdict: Literal["PASS", "FAIL"]
    confidence: float
    failure_category: Literal[
        "none", "retrieval_miss", "prompt_defect", "hallucination", "wrong_refusal"
    ] = "none"
    evidence: str = ""


class Scorecard(BaseModel):
    """Aggregate evaluation metrics across a run of cases."""

    overall_score: float
    dev_score: float
    test_score: float
    pass_rate: float
    total_cases: int
    passed_cases: int
    per_category_scores: dict[str, float] = Field(default_factory=dict)
    per_failure_type_counts: dict[str, int] = Field(default_factory=dict)
    verbosity_warning_count: int = 0
    judge_model: str = ""
    same_model_as_generator: bool = True
    judge_model_note: str = ""
    case_judgments: list[CaseJudgment] = Field(default_factory=list)


class CalibrationSampleResult(BaseModel):
    """Outcome on one judge calibration test item."""

    sample_id: str
    expected_pass: bool
    predicted_pass: bool
    matched: bool
    reason: str


class JudgeCalibrationReport(BaseModel):
    """Self-test accuracy of the judge on gold vs corrupted answers."""

    total_samples: int
    correct_predictions: int
    accuracy: float
    gold_pass_rate: float
    corrupted_catch_rate: float
    samples: list[CalibrationSampleResult] = Field(default_factory=list)


class IterationRecord(BaseModel):
    """Audit record for one critic-optimizer iteration."""

    iteration: int
    dominant_failure_category: str
    failures_addressed: list[str] = Field(default_factory=list)
    action_taken: str
    rationale: str
    unified_diff: str
    dev_score_before: float
    dev_score_after: float
    test_score_before: float
    test_score_after: float
    overall_score_before: float
    overall_score_after: float
    per_category_before: dict[str, float] = Field(default_factory=dict)
    per_category_after: dict[str, float] = Field(default_factory=dict)
    accepted: bool
    status_note: str


class IterationLog(BaseModel):
    """Full optimization history across iterations."""

    max_iterations: int
    target_score: float
    iterations: list[IterationRecord] = Field(default_factory=list)
    stopped_reason: str = ""


class BudgetStats(BaseModel):
    """Cumulative LLM usage, latency, and cache hit statistics."""

    total_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    embed_calls: int = 0
    embed_cache_hits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_latency_s: float = 0.0
    max_tokens_budget: Optional[int] = None
    max_latency_budget_s: Optional[float] = None
    budget_exceeded: bool = False
    exceeded_reason: str = ""
