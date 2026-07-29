"""Null-safe WHERE / SUCH THAT / ORDER BY over columns that hold blank cells.

A text column enforced to pandas "string" dtype carries pd.NA for a blank; a numeric column
carries float nan. Referencing such a column in a WHERE or SUCH THAT condition, or an ORDER BY
over a grouping column that has a null bucket, used to raise ("boolean value of NA is ambiguous",
or a sort TypeError) straight to the caller (and, in the browser demo, to the visitor). These go
through the public df.esql.query(...) accessor and assert those paths return SQL-NULL-consistent
results instead of raising.
"""

import pandas as pd
import pytest


@pytest.fixture
def segue_data() -> pd.DataFrame:
    # Mirrors the demo's segued_from shape: a text column with blanks (pd.NA once the accessor
    # enforces "string" dtype), a non-null entity column, and a numeric measure.
    return pd.DataFrame(
        {
            "song": ["Scarlet", "Fire", "Fire", "Dark Star", "Fire"],
            "came_from": ["Cold Rain", "Scarlet", "Scarlet", None, None],
            "seconds": [500, 600, 620, 1200, 610],
        }
    )


def test_where_equality_on_nullable_column_does_not_raise(segue_data: pd.DataFrame):
    # came_from is NA for the cold opens; `= 'Scarlet'` must skip those rows, not raise.
    result = segue_data.esql.query("SELECT song, seconds.count WHERE came_from = 'Scarlet' ORDER BY 1")
    assert set(result["song"]) == {"Fire"}
    assert result[result["song"] == "Fire"]["seconds.count"].iloc[0] == 2


def test_where_inequality_on_nullable_column_excludes_nulls(segue_data: pd.DataFrame):
    # SQL NULL semantics: an NA operand compares as not-true, so `!= 'Scarlet'` keeps only the
    # present, non-matching rows (Cold Rain), never the NA rows.
    result = segue_data.esql.query("SELECT came_from, seconds.count WHERE came_from != 'Scarlet'")
    assert set(result["came_from"]) == {"Cold Rain"}


def test_order_by_grouping_column_with_null_bucket_sorts_nulls_last(segue_data: pd.DataFrame):
    # Grouping by the nullable column keeps a null bucket (the cold opens); ORDER BY must place it
    # last without raising.
    result = segue_data.esql.query("SELECT came_from, seconds.count WHERE song = 'Fire' ORDER BY 1")
    assert result["came_from"].isna().any(), "the null bucket must survive"
    assert pd.isna(result["came_from"].iloc[-1]), "nulls sort last"
    # present value 'Scarlet' (2 Fires) + the null bucket (1 cold-open Fire)
    assert len(result) == 2


def test_such_that_condition_on_nullable_column_does_not_raise(segue_data: pd.DataFrame):
    # A SUCH THAT group scoped by the nullable column: NA rows drop from that group instead of
    # raising, exactly like WHERE. Only Fire has came_from == 'Scarlet' rows (two of them).
    esql = "SELECT song, g.seconds.count OVER g SUCH THAT g.came_from = 'Scarlet' ORDER BY 1"
    result = segue_data.esql.query(esql)
    fire = result[result["song"] == "Fire"]
    assert fire["g.seconds.count"].iloc[0] == 2
