"""Generate synthetic documents for both ForgeAI demos using committed synthesis prompts."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from forgeai.llm import LLMClient

console = Console()
ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "demos" / "synthesis_prompts"

TARGETS: list[tuple[str, Path]] = [
    ("hr_leave_policy.txt", ROOT / "demos" / "hr_policy" / "docs" / "leave_policy.md"),
    ("hr_code_of_conduct.txt", ROOT / "demos" / "hr_policy" / "docs" / "code_of_conduct.md"),
    ("hr_travel_expense.txt", ROOT / "demos" / "hr_policy" / "docs" / "travel_expense_policy.md"),
    ("spares_catalogue_csv.txt", ROOT / "demos" / "ship_spares" / "docs" / "spares_catalogue.csv"),
    ("spares_supplier_terms.txt", ROOT / "demos" / "ship_spares" / "docs" / "supplier_terms.md"),
    ("spares_procurement_proc.txt", ROOT / "demos" / "ship_spares" / "docs" / "procurement_procedure.md"),
]


def _clean_output(text: str, is_csv: bool) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    if is_csv:
        # Strip any conversational preamble before header row.
        lines = cleaned.splitlines()
        for idx, line in enumerate(lines):
            if "part_no" in line and "unit_price" in line:
                cleaned = "\n".join(lines[idx:]).strip()
                break
    return cleaned + "\n"


def main() -> None:
    llm = LLMClient()
    try:
        for prompt_name, out_path in TARGETS:
            prompt_text = (PROMPTS / prompt_name).read_text(encoding="utf-8")
            console.print(f"Synthesizing [cyan]{out_path.relative_to(ROOT)}[/cyan] from {prompt_name}...")
            raw = llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You generate clean, realistic corporate/technical documents. Output ONLY the document content.",
                    },
                    {"role": "user", "content": prompt_text},
                ],
                temperature=0.2,
                max_tokens=3000,
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(_clean_output(raw, is_csv=out_path.suffix == ".csv"), encoding="utf-8")
            console.print(f"  Wrote {out_path.stat().st_size} bytes.")
    finally:
        llm.close()


if __name__ == "__main__":
    main()
