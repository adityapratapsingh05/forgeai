"""Declarative tool registry with schemas and attachment triggers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from forgeai.tools.calculator import calculator_tool
from forgeai.tools.csv_lookup import make_csv_lookup_tool
from forgeai.tools.current_date import current_date_tool
from forgeai.tools.open_meteo import open_meteo_tool


@dataclass
class ToolSpec:
    """Metadata and callable for one registered tool."""

    name: str
    description: str
    args_schema: dict[str, str]
    func: Callable[..., str]
    when_to_attach: str
    trigger_keywords: list[str] = field(default_factory=list)
    requires_tabular_data: bool = False


class ToolRegistry:
    """Container for available tools and prompt/execution helpers."""

    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs: dict[str, ToolSpec] = {s.name: s for s in specs}

    def list_names(self) -> list[str]:
        return list(self._specs.keys())

    def all_specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def execute(self, name: str, args: dict[str, Any] | None = None) -> str:
        spec = self._specs.get(name)
        if spec is None:
            return f"tool_error: unknown tool '{name}'"
        safe_args = args if isinstance(args, dict) else {}
        try:
            return str(spec.func(**safe_args))
        except TypeError as exc:
            return f"tool_error: invalid arguments for '{name}': {exc}"
        except Exception as exc:
            return f"tool_error: '{name}' raised {exc}"

    def describe_for_prompt(self, allowed_names: list[str]) -> str:
        lines: list[str] = []
        for name in allowed_names:
            spec = self._specs.get(name)
            if spec is None:
                continue
            lines.append(
                f"- {spec.name}: {spec.description} | args={spec.args_schema}"
            )
        return "\n".join(lines)

    def describe_for_generator(self) -> str:
        lines: list[str] = []
        for spec in self._specs.values():
            lines.append(
                f"- {spec.name}: {spec.description}\n"
                f"  when_to_attach: {spec.when_to_attach}\n"
                f"  requires_tabular_data: {spec.requires_tabular_data}"
            )
        return "\n".join(lines)


def build_tool_registry(tables: dict[str, pd.DataFrame] | None = None) -> ToolRegistry:
    """Build the default ForgeAI tool registry bound to any ingested CSV tables."""
    csv_tables = tables or {}
    specs = [
        ToolSpec(
            name="csv_lookup",
            description="Look up or filter rows in ingested CSV tables.",
            args_schema={
                "file": "optional CSV filename",
                "query": "optional keyword search text",
                "filters": "optional {column: value_or_comparator} dict",
                "limit": "optional integer max rows (default 10)",
            },
            func=make_csv_lookup_tool(csv_tables),
            when_to_attach=(
                "Attach ONLY when CSV/tabular files exist in the corpus AND the brief or "
                "requirements involve looking up, filtering, or checking records/parts/prices/rows."
            ),
            trigger_keywords=[
                "csv", "table", "catalogue", "catalog", "lookup", "inventory", "stock",
                "part", "spare", "price", "sku", "rows", "filter", "database", "spreadsheet",
            ],
            requires_tabular_data=True,
        ),
        ToolSpec(
            name="calculator",
            description="Safely evaluate arithmetic expressions (totals, sums, unit price * qty, percentages).",
            args_schema={"expression": "arithmetic expression string, e.g. '4 * 125.50'"},
            func=calculator_tool,
            when_to_attach=(
                "Attach ONLY when the brief, requirements, or corpus involve arithmetic calculations, "
                "totals, cost estimates, quantities * unit prices, percentages, or numeric budgets."
            ),
            trigger_keywords=[
                "calculate", "calculation", "calculator", "total", "sum", "cost", "budget",
                "quantity", "quantities", "multiply", "price", "quote", "discount", "tax",
                "math", "arithmetic", "estimate", "percent", "subtotal", "amount",
            ],
            requires_tabular_data=False,
        ),
        ToolSpec(
            name="open_meteo",
            description="Fetch live current weather for a city or lat/lon using Open-Meteo.",
            args_schema={"place": "city/location name", "lat": "optional float", "lon": "optional float"},
            func=open_meteo_tool,
            when_to_attach=(
                "Attach ONLY when the brief or requirements explicitly ask for live weather, "
                "forecasts, temperature, wind, or meteorological conditions at a location."
            ),
            trigger_keywords=[
                "weather", "forecast", "temperature", "wind", "rain", "storm",
                "climate", "meteorolog", "sea state", "humidity",
            ],
            requires_tabular_data=False,
        ),
        ToolSpec(
            name="current_date",
            description="Get today's current local/UTC date, day of week, and timestamp.",
            args_schema={},
            func=current_date_tool,
            when_to_attach=(
                "Attach ONLY when the brief or requirements explicitly require knowing today's "
                "current date, deadlines relative to today, or age/tenure relative to today."
            ),
            trigger_keywords=[
                "today", "current date", "now", "deadline", "this week", "this month",
                "this year", "expires", "expiry", "overdue", "days until", "date-relative",
            ],
            requires_tabular_data=False,
        ),
    ]
    return ToolRegistry(specs)
