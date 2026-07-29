"""`build_demo` end to end over the sales fixture: what it writes, and what it refuses to write.

There was no coverage here before, which mattered more than it looked: this module composes the JSON
a host front-end reads, and the ESQL<->SQL check it is built around never looked at the shape of
what it emitted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from esql.dataset_schema import DATASET_SCHEMA, validate_dataset
from esql.demokit import DISTINCT_VALUE_CAP, _distinct_values, _schema, build_demo

REPO_ROOT = Path(__file__).resolve().parent.parent
SALES_CSV = REPO_ROOT / "public" / "data" / "sales.csv"
SALES_STRUCTURE = REPO_ROOT / "tests" / "fixtures" / "sales.structure.json"


def _spec() -> dict:
    return {
        "id": "sales",
        "label": "Sales",
        "description": "The engine's fixture table.",
        "examples": [
            {
                "id": "sum-by-cust",
                "tier": "starter",
                "clause": "SELECT",
                "title": "Total per customer",
                "description": "One row per customer.",
                "esql": "SELECT cust, quant.sum",
                "sql": "SELECT cust, SUM(quant) FROM sales GROUP BY cust",
            }
        ],
        "walkthrough": [
            {
                "clause": "SELECT",
                "note": "Every plain column is a grouping attribute.",
                "esql": "SELECT cust, quant.sum",
                "sql": "SELECT cust, SUM(quant) FROM sales GROUP BY cust",
            }
        ],
    }


@pytest.fixture
def built(tmp_path) -> dict:
    build_demo(_spec(), csv=SALES_CSV, structure=SALES_STRUCTURE, out_dir=tmp_path)
    return {
        "dir": tmp_path,
        "asset": json.loads((tmp_path / "sales.json").read_text()),
    }


def test_the_emitted_asset_matches_the_published_schema(built):
    assert validate_dataset(built["asset"]) is None


def test_the_schema_is_emitted_alongside_the_asset(built):
    written = json.loads((built["dir"] / "dataset.schema.json").read_text())
    assert written == DATASET_SCHEMA


def test_the_csv_is_copied_beside_the_asset(built):
    assert (built["dir"] / "sales.csv").read_bytes() == SALES_CSV.read_bytes()


def test_an_example_missing_its_clause_fails_the_build(tmp_path):
    spec = _spec()
    del spec["examples"][0]["clause"]
    with pytest.raises(SystemExit, match="missing required property 'clause'"):
        build_demo(spec, csv=SALES_CSV, structure=SALES_STRUCTURE, out_dir=tmp_path)


def test_a_failing_build_writes_nothing(tmp_path):
    spec = _spec()
    spec["examples"][0]["tier"] = "advanced"
    with pytest.raises(SystemExit):
        build_demo(spec, csv=SALES_CSV, structure=SALES_STRUCTURE, out_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_an_example_whose_sql_disagrees_still_fails_first(tmp_path):
    spec = _spec()
    spec["examples"][0]["sql"] = "SELECT cust, SUM(quant) + 1 FROM sales GROUP BY cust"
    with pytest.raises(SystemExit, match="ESQL and SQL disagree"):
        build_demo(spec, csv=SALES_CSV, structure=SALES_STRUCTURE, out_dir=tmp_path)


# --------------------------------------------------------------------------------------------
# Capped distinct values -- the value-completion payload.
# --------------------------------------------------------------------------------------------


def _column(asset: dict, name: str) -> dict:
    return next(c for c in asset["schema"] if c["name"] == name)


def test_a_discrete_text_column_ships_its_values(built):
    cust = _column(built["asset"], "cust")
    assert cust["type"] == "string"
    assert cust["values"] == sorted(cust["values"])
    assert "Dan" in cust["values"]


def test_a_boolean_column_ships_the_literals_the_parser_accepts(built):
    assert _column(built["asset"], "credit")["values"] == ["false", "true"]


def test_a_discrete_numeric_column_ships_values_sorted_numerically(built):
    month = _column(built["asset"], "month")
    assert month["values"] == [str(n) for n in range(1, 13)]


def test_a_column_over_the_cap_ships_no_values(built):
    """`date` holds 1818 distinct values, well past the cap, so it offers no completions at all --
    which is different from offering none because it has none."""
    assert "values" not in _column(built["asset"], "date")
    assert "values" not in _column(built["asset"], "quant")


def test_a_continuous_column_ships_no_values_even_under_the_cap():
    series = pd.Series([1.5, 2.5, 1.5], name="duration")
    assert _distinct_values(series, "number") is None


def test_the_cap_is_a_ceiling_not_a_truncation():
    under = pd.Series(range(DISTINCT_VALUE_CAP), dtype="int64")
    over = pd.Series(range(DISTINCT_VALUE_CAP + 1), dtype="int64")
    assert len(_distinct_values(under, "number")) == DISTINCT_VALUE_CAP
    assert _distinct_values(over, "number") is None


def test_nulls_are_not_offered_as_a_value():
    series = pd.Series(["a", None, "b"], dtype="string")
    assert _distinct_values(series, "string") == ["a", "b"]


def test_a_column_holding_only_nulls_ships_an_empty_list():
    """Empty is honest and distinguishable: there is nothing to complete, rather than too much."""
    series = pd.Series([None, None], dtype="string")
    assert _distinct_values(series, "string") == []


def test_dates_render_iso_which_is_what_the_parser_reads():
    frame = pd.DataFrame({"date": pd.to_datetime(["2016-06-17", "2016-11-28"]).date})
    assert _schema(frame)[0] == {"name": "date", "type": "date", "values": ["2016-06-17", "2016-11-28"]}
