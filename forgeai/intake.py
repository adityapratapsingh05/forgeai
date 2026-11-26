"""Req 1: Intake interviewer — doc folder profiling, <=5 clarifying questions, requirements spec."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import typer
from pydantic import BaseModel, Field

from forgeai.config import render_prompt
from forgeai.llm import LLMClient
from forgeai.schemas import ClarifierQA, DocProfile, RequirementsSpec

logger = logging.getLogger(__name__)

MAX_CLARIFYING_QUESTIONS = 5


class _QuestionItem(BaseModel):
    question: str
    target_dimension: str = "scope"


class _QuestionsDraft(BaseModel):
    questions: list[_QuestionItem] = Field(default_factory=list)


class _SimulatedAnswers(BaseModel):
    answers: list[str] = Field(default_factory=list)


class _RequirementsDraft(BaseModel):
    scope: str
    audience: str
    tone: str
    must_answer_topics: list[str] = Field(default_factory=list)
    must_refuse_topics: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_risks: list[str] = Field(default_factory=list)


def format_doc_profile_summary(profile: DocProfile) -> str:
    """Create a compact human- and LLM-readable summary of a DocProfile."""
    lines = [
        f"Files ({profile.file_count}, {profile.total_bytes} bytes), types={profile.doc_types}",
        f"Has tabular CSV data: {profile.has_tabular_data}",
        f"Top keywords: {', '.join(profile.topic_keywords[:15])}",
    ]
    for f in profile.files:
        heads = "; ".join(f.headings[:6]) if f.headings else "none"
        lines.append(
            f"- {f.filename} ({f.doc_type}, {f.word_count} words, title='{f.title}', headings=[{heads}])"
        )
    for t in profile.csv_tables:
        lines.append(
            f"- CSV {t.filename}: {t.row_count} rows, columns={t.columns}"
        )
    if profile.warnings:
        lines.append("Warnings: " + " | ".join(profile.warnings))
    return "\n".join(lines)


def cap_questions(questions: list[_QuestionItem], max_questions: int) -> list[_QuestionItem]:
    """Enforce the hard cap of at most 5 clarifying questions in code."""
    hard_limit = max(1, min(int(max_questions), MAX_CLARIFYING_QUESTIONS))
    return questions[:hard_limit]


def compute_requirements_hash(spec: RequirementsSpec) -> str:
    """Compute a stable short hash over requirements fields."""
    payload = spec.model_dump(exclude={"requirements_hash"})
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def render_requirements_md(spec: RequirementsSpec) -> str:
    """Render RequirementsSpec as clean markdown."""
    lines = [
        "# Requirements Specification",
        "",
        f"**Requirements Hash:** `{spec.requirements_hash}`",
        "",
        "## Original Brief",
        spec.brief.strip(),
        "",
        "## Scope",
        spec.scope.strip(),
        "",
        f"## Audience\n{spec.audience.strip()}",
        "",
        f"## Tone\n{spec.tone.strip()}",
        "",
        "## Must-Answer Topics",
    ]
    for item in spec.must_answer_topics:
        lines.append(f"- {item}")
    if not spec.must_answer_topics:
        lines.append("- (none)")

    lines.extend(["", "## Must-Refuse Topics"])
    for item in spec.must_refuse_topics:
        lines.append(f"- {item}")
    if not spec.must_refuse_topics:
        lines.append("- (none)")

    lines.extend(["", "## Assumptions"])
    for item in spec.assumptions:
        lines.append(f"- {item}")
    if not spec.assumptions:
        lines.append("- (none)")

    lines.extend(["", "## Open Risks"])
    for item in spec.open_risks:
        lines.append(f"- {item}")
    if not spec.open_risks:
        lines.append("- (none)")

    lines.extend(["", "## Clarifying Q&A"])
    for qa in spec.clarifier_qa:
        lines.append(f"- **[{qa.target_dimension}] {qa.question}**")
        lines.append(f"  - Answer: {qa.answer}")

    return "\n".join(lines) + "\n"


def save_requirements(spec: RequirementsSpec, run_dir: Path) -> None:
    """Persist requirements.json and requirements.md into run_dir."""
    run_dir.mkdir(parents=True, exist_ok=True)
    spec.requirements_hash = compute_requirements_hash(spec)
    (run_dir / "requirements.json").write_text(
        json.dumps(spec.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "requirements.md").write_text(
        render_requirements_md(spec),
        encoding="utf-8",
    )


def run_intake(
    brief: str,
    profile: DocProfile,
    llm: LLMClient,
    run_dir: Path,
    non_interactive: bool = False,
    max_questions: int = MAX_CLARIFYING_QUESTIONS,
    answers_file: Path | None = None,
) -> RequirementsSpec:
    """Run the intake interviewer stage and write requirements.json + requirements.md."""
    effective_cap = max(1, min(int(max_questions), MAX_CLARIFYING_QUESTIONS))
    profile_summary = format_doc_profile_summary(profile)

    q_prompt = render_prompt(
        "intake_questions",
        max_questions=effective_cap,
        brief=brief.strip(),
        doc_profile_summary=profile_summary,
    )
    q_draft = llm.json_call(q_prompt, _QuestionsDraft, temperature=0.1, max_tokens=900)
    capped_questions = cap_questions(q_draft.questions, effective_cap)

    qa_pairs: list[ClarifierQA] = []
    if capped_questions:
        if answers_file is not None and answers_file.exists():
            raw_ans = json.loads(answers_file.read_text(encoding="utf-8"))
            ans_list = raw_ans if isinstance(raw_ans, list) else raw_ans.get("answers", [])
            for idx, q in enumerate(capped_questions):
                ans = str(ans_list[idx]) if idx < len(ans_list) else "Proceed with document defaults."
                qa_pairs.append(
                    ClarifierQA(
                        question=q.question,
                        target_dimension=q.target_dimension,
                        answer=ans,
                    )
                )
        elif non_interactive:
            sim_prompt = render_prompt(
                "intake_simulator",
                brief=brief.strip(),
                doc_profile_summary=profile_summary,
                questions_json=json.dumps([q.model_dump() for q in capped_questions], indent=2),
            )
            sim = llm.json_call(sim_prompt, _SimulatedAnswers, temperature=0.1, max_tokens=900)
            for idx, q in enumerate(capped_questions):
                ans = (
                    sim.answers[idx].strip()
                    if idx < len(sim.answers) and sim.answers[idx].strip()
                    else "Follow only what is strictly supported in the documents."
                )
                qa_pairs.append(
                    ClarifierQA(
                        question=q.question,
                        target_dimension=q.target_dimension,
                        answer=ans,
                    )
                )
        else:
            for idx, q in enumerate(capped_questions, start=1):
                ans = typer.prompt(
                    f"Clarifying Q{idx}/{len(capped_questions)} [{q.target_dimension}]: {q.question}"
                )
                qa_pairs.append(
                    ClarifierQA(
                        question=q.question,
                        target_dimension=q.target_dimension,
                        answer=ans.strip() or "Use standard grounded defaults.",
                    )
                )

    qa_text = (
        "\n".join(
            f"- [{qa.target_dimension}] Q: {qa.question}\n  A: {qa.answer}"
            for qa in qa_pairs
        )
        or "No clarifying questions asked."
    )
    synth_prompt = render_prompt(
        "intake_synthesize",
        brief=brief.strip(),
        doc_profile_summary=profile_summary,
        qa_text=qa_text,
    )
    draft = llm.json_call(synth_prompt, _RequirementsDraft, temperature=0.1, max_tokens=1200)

    spec = RequirementsSpec(
        brief=brief.strip(),
        scope=draft.scope,
        audience=draft.audience,
        tone=draft.tone,
        must_answer_topics=draft.must_answer_topics,
        must_refuse_topics=draft.must_refuse_topics,
        assumptions=draft.assumptions,
        open_risks=draft.open_risks,
        clarifier_qa=qa_pairs,
    )
    save_requirements(spec, run_dir)
    logger.info("Intake completed: %d questions asked, %d must-answer topics.", len(qa_pairs), len(spec.must_answer_topics))
    return spec
