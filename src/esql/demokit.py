"""Build a validated ESQL demo asset from a dataset spec.

A demo asset is the JSON the portfolio ESQL editor loads for one dataset: its schema, its
dimensional structure, and a set of ESQL<->SQL examples. Each example pairs an ESQL query with
a hand-written SQL equivalent; `build_demo` runs both (the ESQL through this engine, the SQL
through sqlite over the same CSV) and asserts the two results agree as a set before writing the
JSON. An example that does not validate fails the build here rather than shipping a wrong table.

Each dataset owns only its `DATASET` spec (metadata + curated examples + the build-up
walkthrough) and calls `build_demo` with it; this module is the shared harness. It is build-time
tooling: the browser only ever calls `df.esql.query()`, never imports this module.

The asset's shape is declared in `dataset_schema.py` and checked here before anything is written,
and the schema itself is emitted alongside the assets as `dataset.schema.json`. That is the seam
this module exists at: it *writes* the JSON a host front-end *reads*, so the shape is published
from the writing side rather than mirrored by hand on the reading side.
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import NotRequired, TypedDict

import pandas as pd
from pandas.api import types as pdt

import esql.accessor  # noqa: F401  (registers the .esql accessor)
from esql.accessor import _enforce_allowed_dtypes
from esql.dataset_schema import DATASET_SCHEMA, DatasetSchemaError, validate_dataset
from esql.parser.util import dtype_family

# Whether a column ships its distinct values, for a host to offer as completions ("WHERE song = '"
# should suggest real song names). The question is "does completing this column help?", and the
# signal for that is the *ratio* of distinct values to rows: a dimension sits far below its row
# count (the Grateful Dead archive's 520 venues over 39,774 rows, 1.3%) while a measure or a
# free-text column climbs toward 100% and is useless to complete at any cardinality.
#
# A count alone did both jobs badly. At 500 it excluded that venue column by twenty, losing exactly
# the values a visitor most needs help spelling, and raising the count until venue fit would have
# started shipping `quant` (1,000 distinct over 10,000 rows), a measure nobody completes.
DIMENSION_RATIO = 0.05

# Below this, a column ships regardless of ratio. A ratio is meaningless on a small frame -- four
# states over fifty rows is 8%, plainly a dimension -- and any set this small is worth scrolling.
SMALL_VALUE_SET = 50

# The absolute ceiling, for asset size rather than usefulness: 5% of a million-row frame would pass
# the ratio test with 50,000 values and megabytes of JSON. 436 songs cost ~35 KB of a 60 KB asset,
# so this is generous while the assets stay small.
DISTINCT_VALUE_CAP = 2000


def _friendly_type(series: pd.Series) -> str:
    """The asset's `SchemaColumn.type` for a column of the enforced frame.

    Delegates to the parser's `dtype_family`, because the asset and the parser have to agree on what
    a column is: the asset tells a host `venue` is a string, and the host asks `GRAMMAR` which
    operators apply to a string. Two copies of this mapping is two chances for the answer a host is
    given to differ from the one the engine enforces.
    """
    return dtype_family(series.dtype)


def _value_text(value) -> str:
    """One distinct value as the text a query would carry, unquoted.

    The datum, not the literal syntax: a host knows the column's `type` and quotes accordingly. Bools
    render lowercase and dates ISO, which is what the parser accepts for each.
    """
    if isinstance(value, bool) or pdt.is_bool(value):
        return "true" if value else "false"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar
        value = value.item()
    if isinstance(value, int):
        return str(value)
    return str(value)


def _distinct_values(series: pd.Series, friendly_type: str) -> list[str] | None:
    """The column's distinct values as text, or None when it should not offer completions.

    None for a continuous column, for one whose distinct count is too high a share of its rows to be
    a dimension (`DIMENSION_RATIO`, with `SMALL_VALUE_SET` as the small-frame escape), and for one
    over `DISTINCT_VALUE_CAP` whatever its ratio; an empty list only when the column genuinely holds
    no non-null value. Floats are taken as the continuous case -- a measure like a duration in
    seconds has no value worth completing, while discrete numbers (a month, a set position) do and
    are integers.
    """
    if friendly_type == "number" and pdt.is_float_dtype(series.dtype):
        return None
    uniques = pd.unique(series.dropna())
    if len(uniques) > DISTINCT_VALUE_CAP:
        return None
    if len(uniques) > max(SMALL_VALUE_SET, DIMENSION_RATIO * len(series)):
        return None
    texts = [_value_text(v) for v in uniques]
    # Numbers sort numerically rather than as text, so a month list reads 1,2,...,10 not 1,10,11,2.
    return sorted(texts, key=float) if friendly_type == "number" else sorted(texts)


class SchemaColumn(TypedDict):
    """One entry of the asset's `schema`, mirroring `DATASET_SCHEMA`'s `SchemaColumn`.

    `values` is `NotRequired` because absent and empty mean different things to a host: absent is
    "do not offer completions for this column", `[]` is "there are none to offer". A plain dict said
    `dict[str, str]` from its two literal entries, which declared the list this function exists to
    add impossible, and widening the value type instead made `column["name"]` a `str | list[str]`
    everywhere it is read. The TypedDict says both things exactly.
    """

    name: str
    type: str
    values: NotRequired[list[str]]


def _schema(enforced: pd.DataFrame) -> list[SchemaColumn]:
    columns = []
    for name in enforced.columns:
        friendly_type = _friendly_type(enforced[name])
        column = SchemaColumn(name=str(name), type=friendly_type)
        values = _distinct_values(enforced[name], friendly_type)
        if values is not None:
            column["values"] = values
        columns.append(column)
    return columns


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
    """Validate a dataset's ESQL examples and write its `<id>.json` (+ a copy of the CSV and
    `dataset.schema.json`) into out_dir. `dataset` is the spec: id, label, description, examples[],
    walkthrough[], and an optional `category` (only used to group datasets in a multi-dataset
    picker). Each example needs a `clause`; `tier` defaults to "example".

    Two things fail the build rather than shipping: an example whose ESQL and SQL disagree, and an
    output document that does not match `DATASET_SCHEMA`."""
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
                # No default: "clause" names which docs stream the example belongs to, and there is
                # no sensible guess. Omitting it here lets the schema report it as missing rather
                # than manufacturing a value that is not one of the ones a host knows.
                **({"clause": ex["clause"]} if "clause" in ex else {}),
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

    # Validate before writing, so a shape error fails the build here rather than shipping an asset a
    # host reads as `undefined`. Same standing as the ESQL<->SQL check above: the whole point of this
    # module is that a broken demo asset cannot be written.
    try:
        validate_dataset(out)
    except DatasetSchemaError as error:
        raise SystemExit(f"[{ds['id']}] {error}") from None

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{ds['id']}.json").write_text(json.dumps(out, indent=2))
    (out_dir / f"{ds['id']}.csv").write_bytes(csv.read_bytes())
    # The shape every <id>.json in this directory satisfies, emitted verbatim beside them the way
    # grammar.json publishes esql.GRAMMAR. A host generates its types from this rather than keeping
    # a hand-written copy of the shape in step with it.
    (out_dir / "dataset.schema.json").write_text(json.dumps(DATASET_SCHEMA, indent=2))
    print(f"\nWrote {ds['id']} -> {out_dir / f'{ds['id']}.json'} (+ copied {ds['id']}.csv, dataset.schema.json)")
