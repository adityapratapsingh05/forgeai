"""Req 3: Declarative agent generator + deterministic tool-selection post-check."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from forgeai.config import Settings, render_prompt
from forgeai.intake import format_doc_profile_summary
from forgeai.llm import LLMClient
from forgeai.schemas import (
    AgentDefinition,
    DocProfile,
    GeneratedFromMeta,
    GroundabilityReport,
    OutputContract,
    RefusalPolicy,
    RequirementsSpec,
    RetrievalConfig,
    ToolSelectionEntry,
)
from forgeai.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class _AgentDefinitionDraft(BaseModel):
    name: str
    description: str
    system_prompt: str
    tone: str
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    tools: list[str] = Field(default_factory=list)
    tool_selection_rationale: list[ToolSelectionEntry] = Field(default_factory=list)
    output_contract: OutputContract = Field(default_factory=OutputContract)
    refusal_policy: RefusalPolicy = Field(default_factory=RefusalPolicy)


class _PromptVariants(BaseModel):
    prompts: list[str] = Field(default_factory=list)


def _combined_intent_text(requirements: RequirementsSpec) -> str:
    parts = [
        requirements.brief,
        requirements.scope,
        " ".join(requirements.must_answer_topics),
        " ".join(f"{qa.question} {qa.answer}" for qa in requirements.clarifier_qa),
    ]
    return "\n".join(parts).lower()


def _has_trigger_match(text: str, keywords: list[str]) -> list[str]:
    matched: list[str] = []
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw.lower())}", text):
            matched.append(kw)
    return matched


def enforce_tool_selection(
    proposed_tools: list[str],
    llm_rationale: list[ToolSelectionEntry],
    requirements: RequirementsSpec,
    doc_profile: DocProfile,
    registry: ToolRegistry,
) -> tuple[list[str], list[ToolSelectionEntry]]:
    """Deterministic post-check rejecting ungrounded tools and documenting every tool."""
    intent_text = _combined_intent_text(requirements)
    proposed_set = {t.strip() for t in proposed_tools if t.strip()}
    llm_reason_map = {e.name: e.reason for e in llm_rationale}

    final_tools: list[str] = []
    final_rationale: list[ToolSelectionEntry] = []

    for spec in registry.all_specs():
        matched_kw = _has_trigger_match(intent_text, spec.trigger_keywords)
        # Strict per-tool deterministic eligibility rules:
        if spec.requires_tabular_data and not doc_profile.has_tabular_data:
            included = False
            reason = (
                "Excluded by deterministic post-check: no CSV/tabular files exist in the document folder."
            )
        elif spec.name == "csv_lookup":
            # Only attach csv_lookup if CSVs exist AND brief/requirements imply lookup/records/parts.
            if doc_profile.has_tabular_data and (matched_kw or spec.name in proposed_set):
                included = True
                reason = (
                    f"Included: corpus contains CSV table(s) {[t.filename for t in doc_profile.csv_tables]} "
                    f"and requirements match lookup keywords ({', '.join(matched_kw[:4]) or 'tabular lookup'})."
                )
            else:
                included = False
                reason = "Excluded: no tabular lookup requirement triggered."
        elif spec.name == "calculator":
            # Attach if math/cost/quantity/total keywords appear in requirements/brief.
            if matched_kw:
                included = True
                reason = (
                    f"Included: brief/requirements involve arithmetic or pricing calculations "
                    f"(matched: {', '.join(matched_kw[:5])})."
                )
            else:
                included = False
                reason = (
                    "Excluded by deterministic post-check: no arithmetic, totals, or quantity-calculation "
                    "requirements detected in brief/requirements."
                )
        elif spec.name == "open_meteo":
            # Weather tool is ONLY allowed if weather/forecast/climate is explicitly requested.
            if matched_kw:
                included = True
                reason = f"Included: explicit weather/forecast trigger ({', '.join(matched_kw[:4])})."
            else:
                included = False
                reason = (
                    "Excluded by deterministic post-check: no weather, forecast, or climate trigger "
                    "found in brief or requirements."
                )
        elif spec.name == "current_date":
            if matched_kw:
                included = True
                reason = f"Included: explicit date-relative trigger ({', '.join(matched_kw[:4])})."
            else:
                included = False
                reason = (
                    "Excluded by deterministic post-check: no date-relative reasoning (today/expiry/deadline) "
                    "requested in brief or requirements."
                )
        else:
            included = spec.name in proposed_set and bool(matched_kw)
            reason = llm_reason_map.get(spec.name, "Evaluated by registry rules.")

        if spec.name in proposed_set and not included:
            logger.warning(
                "Tool post-check REJECTED LLM-proposed tool '%s': %s", spec.name, reason
            )
        elif spec.name not in proposed_set and included:
            logger.info(
                "Tool post-check ATTACHED evidence-triggered tool '%s': %s", spec.name, reason
            )

        if included:
            final_tools.append(spec.name)
        final_rationale.append(
            ToolSelectionEntry(name=spec.name, included=included, reason=reason)
        )

    return final_tools, final_rationale


def save_agent_definition(agent: AgentDefinition, path: Path) -> None:
    """Serialize AgentDefinition to declarative YAML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = agent.model_dump(mode="json")
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def generate_agent(
    requirements: RequirementsSpec,
    groundability: GroundabilityReport,
    doc_profile: DocProfile,
    registry: ToolRegistry,
    llm: LLMClient,
    settings: Settings,
    run_dir: Path,
) -> AgentDefinition:
    """Synthesize and validate agent_definition.yaml with deterministic tool guardrails."""
    groundability_summary = "\n".join(
        f"- {item.topic}: {item.status} (score={item.retrieval_score}) — {item.reason}"
        for item in groundability.items
    )
    prompt = render_prompt(
        "generator_agent",
        requirements_json=requirements.model_dump_json(indent=2),
        groundability_summary=groundability_summary,
        doc_profile_summary=format_doc_profile_summary(doc_profile),
        tools_description=registry.describe_for_generator(),
    )
    draft = llm.json_call(prompt, _AgentDefinitionDraft, temperature=0.1, max_tokens=1600)

    final_tools, final_rationale = enforce_tool_selection(
        proposed_tools=draft.tools,
        llm_rationale=draft.tool_selection_rationale,
        requirements=requirements,
        doc_profile=doc_profile,
        registry=registry,
    )

    # Ensure all must_refuse topics (including demoted unsupported ones) are carried over.
    merged_refuse = list(
        dict.fromkeys(
            [t for t in requirements.must_refuse_topics if t.strip()]
            + [t for t in draft.refusal_policy.must_refuse_topics if t.strip()]
        )
    )
    refusal_policy = RefusalPolicy(
        must_refuse_topics=merged_refuse,
        out_of_scope_behavior=draft.refusal_policy.out_of_scope_behavior,
    )

    # Embed explicit refusal reminder into system_prompt if unsupported topics exist.
    sys_prompt = draft.system_prompt.strip()
    if groundability.unsupported_topics:
        refuse_list = "; ".join(groundability.unsupported_topics)
        if "not covered" not in sys_prompt.lower() and refuse_list.lower() not in sys_prompt.lower():
            sys_prompt += (
                f"\n\nUNSUPPORTED TOPICS (MUST REFUSE): Do NOT claim or guess answers about: {refuse_list}. "
                "State clearly that they are not covered in the provided documents."
            )

    agent = AgentDefinition(
        name=draft.name.strip() or "ForgeAI Assistant",
        description=draft.description.strip(),
        system_prompt=sys_prompt,
        tone=draft.tone.strip() or requirements.tone,
        retrieval=draft.retrieval,
        tools=final_tools,
        tool_selection_rationale=final_rationale,
        output_contract=draft.output_contract,
        refusal_policy=refusal_policy,
        generated_from=GeneratedFromMeta(
            requirements_hash=requirements.requirements_hash,
            doc_hash=doc_profile.doc_hash,
            factory_version=settings.factory_version,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )

    save_agent_definition(agent, run_dir / "agent_definition.initial.yaml")
    save_agent_definition(agent, run_dir / "agent_definition.yaml")
    logger.info("Generated initial agent '%s' with tools=%s", agent.name, agent.tools)
    return agent


def generate_prompt_candidates(
    agent: AgentDefinition,
    requirements: RequirementsSpec,
    llm: LLMClient,
) -> list[str]:
    """Stretch: generate 2 alternative candidate system prompts alongside the base prompt."""
    prompt = render_prompt(
        "generator_prompt_variant",
        description=agent.description,
        tone=agent.tone,
        tools=", ".join(agent.tools) or "none",
        must_answer=", ".join(requirements.must_answer_topics),
        must_refuse=", ".join(agent.refusal_policy.must_refuse_topics),
    )
    variants = llm.json_call(prompt, _PromptVariants, temperature=0.3, max_tokens=1200)
    candidates = [agent.system_prompt]
    for p in variants.prompts[:2]:
        if p.strip() and p.strip() not in candidates:
            candidates.append(p.strip())
    return candidates
