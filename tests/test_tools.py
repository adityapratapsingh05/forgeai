"""Tests for ForgeAI tools (calculator safety, csv_lookup, open_meteo offline, current_date)."""

from __future__ import annotations

import json
import httpx
import pandas as pd
import pytest

from forgeai.tools.calculator import UnsafeExpressionError, calculator_tool, safe_calculate
from forgeai.tools.csv_lookup import make_csv_lookup_tool
from forgeai.tools.current_date import current_date_tool
from forgeai.tools.open_meteo import open_meteo_tool


def test_calculator_valid_expressions() -> None:
    assert safe_calculate("4 * 125.50") == 502.0
    assert safe_calculate("round(sqrt(16) + 10 / 4, 2)") == 6.5
    assert "result=502" in calculator_tool("4 * 125.50")


@pytest.mark.parametrize(
    "bad_expr",
    [
        "__import__('os').system('echo hi')",
        "open('/etc/passwd').read()",
        "(1).__class__.__mro__",
        "2 ** 5000",
        "10 / 0",
        "True + 1",
        "lambda x: x",
        "[x for x in [1,2]]",
    ],
)
def test_calculator_blocks_unsafe_expressions(bad_expr: str) -> None:
    with pytest.raises(UnsafeExpressionError):
        safe_calculate(bad_expr)
    out = calculator_tool(bad_expr)
    assert out.startswith("calculator_error:")


def test_csv_lookup_filters_and_query() -> None:
    df = pd.DataFrame(
        [
            {"part_no": "P-101", "description": "Fuel filter", "unit_price": 45.0, "stock_qty": 12},
            {"part_no": "P-202", "description": "Oil pump seal", "unit_price": 120.0, "stock_qty": 3},
            {"part_no": "P-303", "description": "Gasket kit", "unit_price": 18.5, "stock_qty": 0},
        ]
    )
    lookup = make_csv_lookup_tool({"spares.csv": df})

    res1 = json.loads(lookup(file="spares.csv", filters={"unit_price": ">=100"}))
    assert res1["total_matches"] == 1
    assert res1["rows"][0]["part_no"] == "P-202"

    res2 = json.loads(lookup(query="fuel filter"))
    assert res2["total_matches"] == 1
    assert res2["rows"][0]["part_no"] == "P-101"

    res_missing = json.loads(lookup(file="nonexistent.csv"))
    assert "error" in res_missing


def test_current_date_tool() -> None:
    data = json.loads(current_date_tool())
    assert "local_date" in data and len(data["local_date"]) == 10
    assert "weekday" in data


def test_open_meteo_graceful_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *args, **kwargs):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr("forgeai.tools.open_meteo.httpx.Client", FailingClient)
    out = json.loads(open_meteo_tool(place="Rotterdam"))
    assert out["ok"] is False
    assert "unavailable" in out["error"]
