"""Generic CLI chat runner that executes any ForgeAI agent_definition.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from forgeai.agent_runner import AgentRunner
from forgeai.llm import LLMClient
from forgeai.schemas import AgentDefinition

app = typer.Typer(add_completion=False, help="Run any generated ForgeAI agent interactively.")
console = Console()


def load_agent_definition(path: Path) -> AgentDefinition:
    """Load and validate an agent_definition.yaml file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AgentDefinition.model_validate(raw)


def _render_response(resp, debug: bool) -> None:
    console.print(Panel(resp.answer, title="Agent", border_style="cyan"))
    if resp.citations:
        console.print(f"[dim]Citations: {', '.join(resp.citations)}[/dim]")
    if resp.tool_calls:
        for tc in resp.tool_calls:
            status = "OK" if tc.allowed and not tc.error else f"BLOCKED/ERR ({tc.error})"
            console.print(f"[yellow]Tool {tc.name}({tc.args}) -> {status}[/yellow]")
            if debug and tc.output:
                console.print(f"[dim]  Output: {tc.output[:300]}[/dim]")
    if debug:
        tbl = Table(title="Retrieved Chunks", show_lines=True)
        tbl.add_column("Source")
        tbl.add_column("Section")
        tbl.add_column("Score")
        tbl.add_column("Snippet")
        for hit in resp.retrieved_chunks:
            tbl.add_row(
                hit.source_file,
                hit.page_or_section,
                f"{hit.score:.3f} (bm25={hit.bm25_score:.2f}, emb={hit.embed_score:.2f})",
                hit.text[:160].replace("\n", " "),
            )
        if not resp.retrieved_chunks:
            console.print("[red]Debug: 0 chunks met min_score threshold.[/red]")
        else:
            console.print(tbl)


@app.command()
def main(
    agent: Path = typer.Option(..., "--agent", exists=True, help="Path to agent_definition.yaml"),
    docs: Path = typer.Option(..., "--docs", exists=True, help="Path to documents folder"),
    question: Optional[str] = typer.Option(None, "--question", "-q", help="Single non-interactive question"),
    debug: bool = typer.Option(False, "--debug", help="Show retrieved chunks and tool details"),
) -> None:
    """Start an interactive or single-turn chat session with a generated ForgeAI agent."""
    definition = load_agent_definition(agent)
    llm = LLMClient()
    runner = AgentRunner(agent=definition, docs_dir=docs, llm_client=llm)

    console.print(
        Panel(
            f"[bold]{definition.name}[/bold]\n{definition.description}\n"
            f"Tools: {', '.join(definition.tools) or 'none'} | "
            f"Indexed chunks: {len(runner.corpus.chunks)}",
            title="ForgeAI Runner",
            border_style="green",
        )
    )

    if question:
        resp = runner.ask(question)
        _render_response(resp, debug=debug)
        llm.close()
        return

    console.print("[dim]Type your question, or 'exit' / 'quit' to stop.[/dim]")
    try:
        while True:
            user_q = typer.prompt("You")
            if user_q.strip().lower() in {"exit", "quit", ":q"}:
                break
            if not user_q.strip():
                continue
            resp = runner.ask(user_q)
            _render_response(resp, debug=debug)
    finally:
        llm.close()


if __name__ == "__main__":
    app()
