"""Pandas-backed CSV lookup tool over ingested tabular files."""

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd


def _match_filter(series: pd.Series, target: Any) -> pd.Series:
    target_str = str(target).strip()
    num_match = re.match(r"^(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)$", target_str)
    if num_match:
        op, num_s = num_match.groups()
        val = float(num_s)
        numeric_col = pd.to_numeric(series, errors="coerce")
        if op == ">=":
            return numeric_col >= val
        if op == "<=":
            return numeric_col <= val
        if op == ">":
            return numeric_col > val
        return numeric_col < val

    s_lower = series.astype(str).str.lower()
    t_lower = target_str.lower()
    return s_lower.str.contains(re.escape(t_lower), na=False)


def make_csv_lookup_tool(tables: dict[str, pd.DataFrame]):
    """Create a csv_lookup callable bound to the ingested CSV tables."""

    def csv_lookup_tool(
        file: str = "",
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> str:
        """Query ingested CSV tables by filename, column filters, or text query."""
        if not tables:
            return json.dumps({"error": "No CSV tables are loaded in this corpus."})

        selected_name: str | None = None
        if file:
            if file in tables:
                selected_name = file
            else:
                low = file.lower()
                for name in tables:
                    if low in name.lower():
                        selected_name = name
                        break
        elif len(tables) == 1:
            selected_name = next(iter(tables))
        else:
            # Pick table whose columns or content match query/filters best, else first.
            selected_name = next(iter(tables))

        if selected_name is None:
            return json.dumps(
                {
                    "error": f"CSV file '{file}' not found.",
                    "available_files": list(tables.keys()),
                }
            )

        df = tables[selected_name].copy()
        col_map = {str(c).lower(): str(c) for c in df.columns}

        if filters and isinstance(filters, dict):
            mask = pd.Series(True, index=df.index)
            unknown_cols: list[str] = []
            for k, v in filters.items():
                real_col = col_map.get(str(k).lower())
                if real_col is None:
                    # Try partial column name match.
                    for cl, orig in col_map.items():
                        if str(k).lower() in cl:
                            real_col = orig
                            break
                if real_col is None:
                    unknown_cols.append(str(k))
                    continue
                mask = mask & _match_filter(df[real_col], v)
            df = df[mask]
            if unknown_cols and df.empty:
                return json.dumps(
                    {
                        "file": selected_name,
                        "error": f"Unknown filter column(s): {unknown_cols}",
                        "columns": list(tables[selected_name].columns),
                    }
                )

        if query and query.strip():
            tokens = [t for t in re.findall(r"[\w.-]+", query.lower()) if len(t) >= 2]
            if tokens:
                row_text = df.astype(str).agg(" ".join, axis=1).str.lower()
                # Match rows containing all tokens if possible, else rank by token hits.
                hit_counts = sum(row_text.str.contains(re.escape(tok), na=False).astype(int) for tok in tokens)
                df = df.assign(_hits=hit_counts)
                df = df[df["_hits"] > 0].sort_values("_hits", ascending=False).drop(columns=["_hits"])

        safe_limit = max(1, min(int(limit or 10), 25))
        total_matches = int(len(df))
        rows = df.head(safe_limit).fillna("").to_dict(orient="records")
        return json.dumps(
            {
                "file": selected_name,
                "total_matches": total_matches,
                "returned_rows": len(rows),
                "rows": rows,
            },
            ensure_ascii=False,
        )

    return csv_lookup_tool
