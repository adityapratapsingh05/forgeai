"""ForgeAI orchestrator CLI: intake -> groundability -> generate -> evalgen -> optimize -> report."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from forgeai.agent_runner import AgentRunner
from forgeai.budget import BudgetTracker
from forgeai.config import load_settings
from forgeai.evalgen import generate_eval_set
from forgeai.generator import generate_agent, generate_prompt_candidates, save_agent_definition
from forgeai.groundability import run_groundability_guard
from forgeai.ingest import ingest_corpus, load_documents
from forgeai.intake import run_intake
from forgeai.judge import evaluate_agent, run_judge_calibration
from forgeai.llm import LLMClient
from forgeai.optimizer import run_optimizer, run_prompt_tournament
from forgeai.report import generate_report
from forgeai.retrieval import HybridRetriever
from forgeai.schemas import (
    AgentDefinition,
    EvalSet,
    GroundabilityReport,
    IterationLog,
    JudgeCalibrationReport,
    RequirementsSpec,
    RetrievalConfig,
    Scorecard,
)
from forgeai.tools.registry import build_tool_registry

app = typer.Typer(add_completion=False, help="ForgeAI autonomous agent factory CLI.")
console = Console()


def _configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
        force=True,
    )


def run_factory_pipeline(
    brief_text: str,
    docs_dir: Path,
    run_name: str,
    non_interactive: bool = False,
    answers_file: Path | None = None,
    max_questions: int = 5,
    max_iters: int = 3,
    target_score: float = 0.85,
    token_budget: int | None = None,
    human_checkpoint: bool = False,
    force: bool = False,
    tournament: bool = False,
    eval_count: int = 30,
    runs_root: Path = Path("runs"),
) -> Path:
    """Execute the full resumable ForgeAI pipeline and return the run directory path."""
    settings = load_settings()
    run_dir = runs_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    budget = BudgetTracker(max_tokens=token_budget)
    llm = LLMClient(settings=settings, budget=budget)

    try:
        console.print(
            Panel(
                f"Run: [bold]{run_name}[/bold] | Docs: {docs_dir}\n"
                f"LLM: {settings.llm_model} @ {settings.llm_base_url} | Embed: {settings.embed_model}",
                title="ForgeAI Factory",
                border_style="cyan",
            )
        )

        # Stage 0: Ingest & Profile
        console.rule("[bold]Stage 1/6: Document Ingestion & Intake[/bold]")
        default_retrieval = RetrievalConfig()
        corpus = ingest_corpus(docs_dir, default_retrieval)
        (run_dir / "doc_profile.json").write_text(
            corpus.profile.model_dump_json(indent=2), encoding="utf-8"
        )
        for warn in corpus.profile.warnings:
            console.print(f"[yellow]Warning: {warn}[/yellow]")

        # Stage 1: Intake
        req_path = run_dir / "requirements.json"
        if req_path.exists() and not force:
            console.print("[dim]Skipping intake (cached requirements.json found).[/dim]")
            requirements = RequirementsSpec.model_validate_json(req_path.read_text(encoding="utf-8"))
        else:
            requirements = run_intake(
                brief=brief_text,
                profile=corpus.profile,
                llm=llm,
                run_dir=run_dir,
                non_interactive=non_interactive,
                max_questions=max_questions,
                answers_file=answers_file,
            )

        if human_checkpoint and not non_interactive:
            console.print(
                f"[yellow]Human checkpoint:[/yellow] Review/edit {run_dir / 'requirements.md'} if needed."
            )
            typer.confirm("Proceed to Groundability Guard?", default=True, abort=True)

        # Stage 2: Groundability Guard
        console.rule("[bold]Stage 2/6: Groundability Guard[/bold]")
        base_retriever = HybridRetriever(corpus.chunks, default_retrieval, llm)
        ground_path = run_dir / "groundability_report.json"
        if ground_path.exists() and not force:
            console.print("[dim]Skipping groundability (cached groundability_report.json found).[/dim]")
            groundability = GroundabilityReport.model_validate_json(
                ground_path.read_text(encoding="utf-8")
            )
            requirements = RequirementsSpec.model_validate_json(req_path.read_text(encoding="utf-8"))
        else:
            groundability, requirements = run_groundability_guard(
                requirements=requirements,
                retriever=base_retriever,
                llm=llm,
                run_dir=run_dir,
            )
        for w in groundability.warnings:
            console.print(f"[bold yellow]{w}[/bold yellow]")

        # Stage 3: Agent Generation
        console.rule("[bold]Stage 3/6: Agent Generator[/bold]")
        registry = build_tool_registry(corpus.tables)
        init_agent_path = run_dir / "agent_definition.initial.yaml"
        if init_agent_path.exists() and not force:
            console.print("[dim]Skipping generator (cached agent_definition.initial.yaml found).[/dim]")
            initial_agent = AgentDefinition.model_validate(
                yaml.safe_load(init_agent_path.read_text(encoding="utf-8"))
            )
        else:
            initial_agent = generate_agent(
                requirements=requirements,
                groundability=groundability,
                doc_profile=corpus.profile,
                registry=registry,
                llm=llm,
                settings=settings,
                run_dir=run_dir,
            )

        # Stage 4: Eval Generation (frozen for run)
        console.rule("[bold]Stage 4/6: Grounded Eval Generation[/bold]")
        eval_path = run_dir / "eval_set.json"
        if eval_path.exists() and not force:
            console.print("[dim]Skipping evalgen (cached eval_set.json found).[/dim]")
            eval_set = EvalSet.model_validate_json(eval_path.read_text(encoding="utf-8"))
        else:
            eval_set = generate_eval_set(
                corpus=corpus,
                retriever=base_retriever,
                requirements=requirements,
                agent=initial_agent,
                llm=llm,
                run_dir=run_dir,
                total_target=eval_count,
            )

        tournament_results: list[dict[str, object]] | None = None
        if tournament and not (run_dir / "iteration_log.json").exists():
            console.print("[cyan]Running prompt tournament (3 candidates)...[/cyan]")
            candidates = generate_prompt_candidates(initial_agent, requirements, llm)
            initial_agent, tournament_results = run_prompt_tournament(
                agent=initial_agent,
                candidate_prompts=candidates,
                docs_dir=docs_dir,
                corpus=corpus,
                retriever=base_retriever,
                eval_set=eval_set,
                llm=llm,
                settings=settings,
            )
            save_agent_definition(initial_agent, run_dir / "agent_definition.initial.yaml")

        # Stage 5: Judge Calibration + Critic-Optimizer Loop
        console.rule("[bold]Stage 5/6: Judge Calibration & Critic-Optimizer Loop[/bold]")
        cal_path = run_dir / "judge_calibration.json"
        valid_sources = {c.source_file for c in corpus.chunks}
        if cal_path.exists() and not force:
            calibration = JudgeCalibrationReport.model_validate_json(
                cal_path.read_text(encoding="utf-8")
            )
        else:
            calibration = run_judge_calibration(
                eval_set=eval_set,
                agent=initial_agent,
                valid_corpus_sources=valid_sources,
                llm=llm,
                settings=settings,
                run_dir=run_dir,
            )
        console.print(
            f"Judge Calibration Accuracy: [bold]{calibration.accuracy:.1%}[/bold] "
            f"({calibration.correct_predictions}/{calibration.total_samples})"
        )

        iter_path = run_dir / "iteration_log.json"
        scorecard_path = run_dir / "scorecard.json"
        final_agent_path = run_dir / "agent_definition.yaml"
        if iter_path.exists() and scorecard_path.exists() and final_agent_path.exists() and not force:
            console.print("[dim]Skipping optimizer (cached iteration_log.json & scorecard.json found).[/dim]")
            final_agent = AgentDefinition.model_validate(
                yaml.safe_load(final_agent_path.read_text(encoding="utf-8"))
            )
            iteration_log = IterationLog.model_validate_json(iter_path.read_text(encoding="utf-8"))
            final_scorecard = Scorecard.model_validate_json(scorecard_path.read_text(encoding="utf-8"))
            initial_scorecard = final_scorecard
        else:
            final_agent, initial_scorecard, final_scorecard, iteration_log = run_optimizer(
                initial_agent=initial_agent,
                docs_dir=docs_dir,
                eval_set=eval_set,
                llm=llm,
                settings=settings,
                run_dir=run_dir,
                max_iters=max_iters,
                target_score=target_score,
            )

        # Stage 6: Honest Reporting & Cache Stats
        console.rule("[bold]Stage 6/6: Honest Reporting[/bold]")
        budget.save(run_dir / "llm_cache_stats.json")
        report_path = generate_report(
            run_name=run_name,
            requirements=requirements,
            groundability=groundability,
            final_agent=final_agent,
            eval_set=eval_set,
            initial_scorecard=initial_scorecard,
            final_scorecard=final_scorecard,
            iteration_log=iteration_log,
            calibration=calibration,
            budget_stats=budget.stats,
            run_dir=run_dir,
            tournament_results=tournament_results,
        )

        summary_tbl = Table(title=f"Run Complete: {run_name}")
        summary_tbl.add_column("Metric")
        summary_tbl.add_column("Value")
        summary_tbl.add_row("Overall Score", f"{final_scorecard.overall_score:.4f}")
        summary_tbl.add_row("Dev vs Test Score", f"{final_scorecard.dev_score:.4f} / {final_scorecard.test_score:.4f}")
        summary_tbl.add_row("Pass Rate", f"{final_scorecard.pass_rate:.1%} ({final_scorecard.passed_cases}/{final_scorecard.total_cases})")
        summary_tbl.add_row("Tools Attached", ", ".join(final_agent.tools) or "none")
        summary_tbl.add_row("Unsupported Flagged", str(len(groundability.unsupported_topics)))
        summary_tbl.add_row("Report Path", str(report_path))
        console.print(summary_tbl)
        return run_dir
    finally:
        llm.close()


def run_regression_mode(
    old_run: Path,
    new_docs: Path,
    run_name: str,
    runs_root: Path = Path("runs"),
) -> Path:
    """Stretch: Re-run an old frozen eval_set.json against regenerated agent on updated docs."""
    old_eval = EvalSet.model_validate_json((old_run / "eval_set.json").read_text(encoding="utf-8"))
    old_agent = AgentDefinition.model_validate(
        yaml.safe_load((old_run / "agent_definition.yaml").read_text(encoding="utf-8"))
    )
    old_scorecard = Scorecard.model_validate_json(
        (old_run / "scorecard.json").read_text(encoding="utf-8")
    )
    settings = load_settings()
    budget = BudgetTracker()
    llm = LLMClient(settings=settings, budget=budget)
    out_dir = runs_root / run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        corpus = ingest_corpus(new_docs, old_agent.retrieval)
        runner = AgentRunner(agent=old_agent, docs_dir=new_docs, llm_client=llm, corpus=corpus)
        new_scorecard = evaluate_agent(runner=runner, eval_set=old_eval, settings=settings, llm_judge=llm)
        old_pass = {j.case_id for j in old_scorecard.case_judgments if j.final_verdict == "PASS"}
        new_pass = {j.case_id for j in new_scorecard.case_judgments if j.final_verdict == "PASS"}
        regressed = sorted(old_pass - new_pass)
        fixed = sorted(new_pass - old_pass)
        (out_dir / "regression_scorecard.json").write_text(
            new_scorecard.model_dump_json(indent=2), encoding="utf-8"
        )
        md = [
            f"# Regression Report — `{run_name}`",
            f"- Old run: `{old_run}` (score={old_scorecard.overall_score:.4f})",
            f"- New docs: `{new_docs}` (score={new_scorecard.overall_score:.4f})",
            f"- Regressed cases (passed before, failed now): {regressed or 'none'}",
            f"- Newly passing cases: {fixed or 'none'}",
        ]
        (out_dir / "regression_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        return out_dir
    finally:
        llm.close()


@app.command()
def main(
    brief: Optional[str] = typer.Option(None, "--brief", help="Brief text or path to brief.txt"),
    docs: Optional[Path] = typer.Option(None, "--docs", help="Path to documents folder"),
    run_name: str = typer.Option("forgeai_run", "--run-name", help="Output folder name under runs/"),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Run intake unattended"),
    answers: Optional[Path] = typer.Option(None, "--answers", help="Optional JSON answers file for intake"),
    max_questions: int = typer.Option(5, "--max-questions", help="Max clarifying questions (hard-capped at 5)"),
    max_iters: int = typer.Option(3, "--max-iters", help="Max optimizer iterations (hard-capped at 3)"),
    target: float = typer.Option(0.85, "--target", help="Target dev score for early stopping"),
    token_budget: Optional[int] = typer.Option(None, "--token-budget", help="Optional max uncached token budget"),
    human_checkpoint: bool = typer.Option(False, "--human-checkpoint", help="Pause after intake for approval"),
    force: bool = typer.Option(False, "--force", help="Re-run all stages ignoring cached artifacts"),
    tournament: bool = typer.Option(False, "--tournament", help="Run 3-prompt tournament before optimization"),
    eval_count: int = typer.Option(30, "--eval-count", help="Target number of eval cases (>=20)"),
    regression: bool = typer.Option(False, "--regression", help="Run regression check against an old frozen eval set"),
    old_run: Optional[Path] = typer.Option(None, "--old-run", help="Previous run directory for --regression"),
    new_docs: Optional[Path] = typer.Option(None, "--new-docs", help="New documents folder for --regression"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """ForgeAI autonomous agent factory CLI."""
    _configure_logging(verbose)
    if regression:
        if old_run is None or new_docs is None:
            raise typer.BadParameter("--regression requires both --old-run and --new-docs.")
        out = run_regression_mode(old_run=old_run, new_docs=new_docs, run_name=run_name)
        console.print(f"[green]Regression report written to {out / 'regression_report.md'}[/green]")
        return

    if not brief or docs is None:
        raise typer.BadParameter("--brief and --docs are required unless --regression is set.")

    brief_path = Path(brief)
    brief_text = brief_path.read_text(encoding="utf-8") if brief_path.exists() and brief_path.is_file() else brief

    run_factory_pipeline(
        brief_text=brief_text,
        docs_dir=docs,
        run_name=run_name,
        non_interactive=non_interactive,
        answers_file=answers,
        max_questions=max_questions,
        max_iters=max_iters,
        target_score=target,
        token_budget=token_budget,
        human_checkpoint=human_checkpoint,
        force=force,
        tournament=tournament,
        eval_count=eval_count,
    )


if __name__ == "__main__":
    app()
