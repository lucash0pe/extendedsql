"""Build a validated ESQL demo asset from a dataset spec.

A demo asset is the JSON the portfolio ESQL editor loads for one dataset: its schema, its
dimensional structure, and a set of ESQL<->SQL examples. Each example pairs an ESQL query with
a hand-written SQL equivalent; `build_demo` runs both (the ESQL through this engine, the SQL
through sqlite over the same CSV) and asserts the two results agree as a set before writing the
JSON. An example that does not validate fails the build here rather than shipping a wrong table.

Each dataset owns only its `DATASET` spec (metadata + curated examples + the build-up
walkthrough) and calls `build_demo` with it; this module is the shared harness. It is build-time
tooling: the browser only ever calls `df.esql.query()`, never imports this module.
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

import pandas as pd
from pandas.api import types as pdt

import esql.accessor  # noqa: F401  (registers the .esql accessor)
from esql.accessor import _enforce_allowed_dtypes


def _friendly_type(series: pd.Series) -> str:
    dt = series.dtype
    if pdt.is_bool_dtype(dt):
        return "boolean"
    if pdt.is_numeric_dtype(dt):
        return "number"
    non_null = series.dropna()
    if len(non_null) and hasattr(non_null.iloc[0], "isoformat"):
        return "date"
    return "string"


def _schema(enforced: pd.DataFrame) -> list[dict]:
    return [{"name": c, "type": _friendly_type(enforced[c])} for c in enforced.columns]


def _run_sql(sql: str, raw: pd.DataFrame, table: str) -> pd.DataFrame:
    conn = sqlite3.connect(":memory:")
    raw.to_sql(table, conn, index=False)
    out = pd.read_sql_query(sql, conn)
    conn.close()
    return out


def _norm(row) -> tuple:
    return tuple(None if isinstance(v, float) and math.isnan(v) else v for v in row)


def _check(esql: str, sql: str, raw: pd.DataFrame, table: str, label: str) -> pd.DataFrame:
    """Run the ESQL through the engine and the SQL through sqlite over the same CSV, and assert the
    two agree as a set. Returns the engine's DataFrame; fails the build on any disagreement."""
    esql_df = raw.esql.query(esql).round(2).reset_index(drop=True)
    sql_df = _run_sql(sql, raw, table).round(2).reset_index(drop=True)
    esql_set = {_norm(r) for r in esql_df.to_numpy()}
    sql_set = {_norm(r) for r in sql_df.to_numpy()}
    if esql_set != sql_set:
        raise SystemExit(
            f"[{label}] ESQL and SQL disagree:\n"
            f"  only in ESQL: {sorted(map(str, esql_set - sql_set))[:5]}\n"
            f"  only in SQL:  {sorted(map(str, sql_set - esql_set))[:5]}"
        )
    return esql_df


def _jsonable(v):
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 2)
    if hasattr(v, "item"):  # numpy scalar
        return v.item()
    return v


def _load_structure(path: Path, columns: set[str], dataset_id: str) -> dict:
    """Load this dataset's dimensional structure and check it only names real columns."""
    structure = json.loads(path.read_text())
    named: set[str] = set()
    for dim in structure.get("dimensions", []):
        named.add(dim["column"])
        named.update(b["column"] for b in dim.get("branchesTo", []))
    named.update(f["column"] for f in structure.get("flags", []))
    named.update(m["column"] for m in structure.get("measures", []))
    missing = named - columns
    if missing:
        raise SystemExit(f"[{dataset_id}] structure names columns not in the CSV: {sorted(missing)}")
    return structure


def build_demo(dataset: dict, *, csv: Path, structure: Path, out_dir: Path) -> None:
    """Validate a dataset's ESQL examples and write its `<id>.json` (+ a copy of the CSV) into
    out_dir. `dataset` is the spec: id, label, description, examples[], walkthrough[], and an
    optional `category` (only used to group datasets in a multi-dataset picker)."""
    ds = dataset
    raw = pd.read_csv(csv)
    enforced = _enforce_allowed_dtypes(raw)
    schema = _schema(enforced)
    structure_doc = _load_structure(structure, {c["name"] for c in schema}, ds["id"])
    examples = []
    for ex in ds["examples"]:
        esql_df = _check(ex["esql"], ex["sql"], raw, ds["id"], f"{ds['id']}/{ex['id']}")
        examples.append(
            {
                "id": ex["id"],
                "tier": ex.get("tier", "example"),
                "clause": ex.get("clause", "example"),
                "title": ex["title"],
                "description": ex["description"],
                "esql": " ".join(ex["esql"].split()),
                "sql": ex["sql"],
                "columns": list(esql_df.columns),
                "rows": [[_jsonable(v) for v in row] for row in esql_df.to_numpy().tolist()],
            }
        )
        print(f"[ok] {ds['id']}/{ex['id']}: {len(examples[-1]['rows'])} rows")

    # The build-up walkthrough: validated like the examples, but shipped without rows (each step
    # runs live in the editor, so only its ESQL and teaching copy ship).
    walkthrough = []
    for i, step in enumerate(ds["walkthrough"], 1):
        _check(step["esql"], step["sql"], raw, ds["id"], f"{ds['id']}/walkthrough-{i}")
        walkthrough.append(
            {
                "clause": step["clause"],
                "note": step["note"],
                "esql": " ".join(step["esql"].split()),
            }
        )
        print(f"[ok] {ds['id']}/walkthrough-{i}: {step['clause']}")

    out = {
        "id": ds["id"],
        "label": ds["label"],
        # category is optional presentation metadata — only used to group datasets in a
        # multi-dataset picker. Included in the asset only when the spec declares it.
        **({"category": ds["category"]} if ds.get("category") else {}),
        "description": ds["description"],
        "csv": f"{ds['id']}.csv",
        "schema": schema,
        "structure": structure_doc,
        "examples": examples,
        "walkthrough": walkthrough,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{ds['id']}.json").write_text(json.dumps(out, indent=2))
    (out_dir / f"{ds['id']}.csv").write_bytes(csv.read_bytes())
    print(f"\nWrote {ds['id']} -> {out_dir / f'{ds['id']}.json'} (+ copied {ds['id']}.csv)")
