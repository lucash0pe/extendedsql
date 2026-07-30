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
from esql.demokit import DIMENSION_RATIO, DISTINCT_VALUE_CAP, _distinct_values, _schema, build_demo

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
# Distinct values -- the value-completion payload, and which columns earn one.
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


def test_a_column_too_distinct_to_be_a_dimension_ships_no_values(built):
    """`quant` is a measure (1000 distinct over 10,000 rows, 10%) and `date` is near-unique per row
    (1818, 18%). Both are above `DIMENSION_RATIO`, so neither offers completions at all -- which is
    different from offering none because it has none."""
    assert "values" not in _column(built["asset"], "date")
    assert "values" not in _column(built["asset"], "quant")


def test_a_continuous_column_ships_no_values_even_when_discrete_enough():
    series = pd.Series([1.5, 2.5, 1.5], name="duration")
    assert _distinct_values(series, "number") is None


def test_a_dimension_ships_its_values_however_many_it_has():
    """The case the count got wrong: 520 venues over 39,774 rows is 1.3%, plainly a dimension, and
    was excluded by twenty under `DISTINCT_VALUE_CAP = 500`."""
    venues = [f"venue {n}" for n in range(520)]
    series = pd.Series((venues * 77)[:39_774], dtype="string")
    assert _distinct_values(series, "string") == sorted(venues)


def test_a_small_value_set_ships_whatever_its_ratio():
    """Four states over fifty rows is 8%, over `DIMENSION_RATIO` and still obviously a dimension. A
    ratio says nothing on a frame this small, so a set this small does not have to pass it."""
    series = pd.Series((["CT", "NY", "NJ", "PA"] * 13)[:50], dtype="string")
    assert _distinct_values(series, "string") == ["CT", "NJ", "NY", "PA"]
    assert DIMENSION_RATIO * 50 < 4


def test_the_ratio_excludes_a_column_the_ceiling_would_admit():
    """1000 distinct over 2000 rows is half the frame: well under the ceiling, and not a dimension."""
    series = pd.Series(list(range(1000)) * 2, dtype="int64")
    assert len(series) == 2000 and DISTINCT_VALUE_CAP > 1000
    assert _distinct_values(series, "number") is None


def test_the_ceiling_bounds_the_asset_whatever_the_ratio():
    """A ratio alone would ship 50,000 values off a million-row frame. The ceiling is a ceiling, not
    a truncation: over it the column offers nothing rather than an arbitrary prefix."""
    rows = 200_000
    under = pd.Series((list(range(DISTINCT_VALUE_CAP)) * 100)[:rows], dtype="int64")
    over = pd.Series((list(range(DISTINCT_VALUE_CAP + 1)) * 100)[:rows], dtype="int64")
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
