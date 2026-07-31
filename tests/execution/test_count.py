"""`count` counts rows, `column.count` counts that column's distinct values (H4).

The filing is worth restating because every test here is a case of it. `SELECT state, city.count`
returned the *row* count, so CA came back as 11,963 song-performances rather than its 61 cities, and
`song.count` and `position.count` returned that same 11,963: the column in `X.count` carried no
meaning except its nullness. It was there to satisfy dot-notation, and under a clause that
auto-groups, naming a column that has no bearing on the answer is what makes the answer misread.

So the row count gets its own spelling, with no column to borrow, and a column named in a count now
bears on the result. After this there is no way to write a row count that names an irrelevant column.

These go through the public accessor, since what changed is what a query means.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from esql.parser.error import ParsingError


@pytest.fixture
def plays() -> pd.DataFrame:
    """CA holds 3 rows over 2 cities, which is the whole filing in miniature: a row count and a
    distinct count that disagree. `seconds` carries a blank so nullness stays visible."""
    return pd.DataFrame(
        {
            "state": ["CA", "CA", "CA", "NY"],
            "city": ["SF", "SF", "LA", "NYC"],
            "seconds": [10.0, 20.0, None, 40.0],
            "played": [date(2020, 1, 1), date(2020, 1, 1), date(2021, 5, 5), date(2021, 5, 5)],
        }
    )


def _for(result: pd.DataFrame, state: str, column: str):
    return result[result["state"] == state][column].iloc[0]


###############################################################################
# The row count, which had no spelling at all
###############################################################################
def test_a_bare_count_is_the_row_count(plays: pd.DataFrame):
    result = plays.esql.query("SELECT state, count")
    assert _for(result, "CA", "count") == 3
    assert _for(result, "NY", "count") == 1


def test_the_two_counts_disagree_which_is_the_point(plays: pd.DataFrame):
    """3 rows over 2 cities. Before H4 both spellings answered 3, and only one of them reads as 3."""
    result = plays.esql.query("SELECT state, count, city.count")
    assert _for(result, "CA", "count") == 3
    assert _for(result, "CA", "city.count") == 2


def test_the_row_count_does_not_depend_on_any_column(plays: pd.DataFrame):
    """The filed symptom was that `city.count`, `song.count` and `position.count` all returned the
    same number. Now the number that is column-independent is the one that names no column."""
    result = plays.esql.query("SELECT state, count")
    without_a_null_column = plays.drop(columns=["seconds"]).esql.query("SELECT state, count")
    assert list(result["count"]) == list(without_a_null_column["count"])


def test_a_row_counts_even_where_its_values_are_missing(plays: pd.DataFrame):
    """A blank cell makes a row no less of a row, which is why the row count cannot be `X.count` for
    any X: `seconds.count` is 2 for CA precisely because one value is missing."""
    result = plays.esql.query("SELECT state, count, seconds.count")
    assert _for(result, "CA", "count") == 3
    assert _for(result, "CA", "seconds.count") == 2


###############################################################################
# The distinct count
###############################################################################
def test_a_column_count_counts_distinct_values(plays: pd.DataFrame):
    result = plays.esql.query("SELECT state, city.count")
    assert _for(result, "CA", "city.count") == 2


def test_a_distinct_count_works_on_every_dtype(plays: pd.DataFrame):
    """`count` is still the one function legal on a non-numeric column, which is what
    `GRAMMAR["aggregates"]["any_dtype"]` publishes. Distinctness does not change that."""
    result = plays.esql.query("SELECT state, city.count, played.count, seconds.count")
    assert _for(result, "CA", "city.count") == 2
    assert _for(result, "CA", "played.count") == 2
    assert _for(result, "CA", "seconds.count") == 2


def test_a_distinct_count_ignores_missing_values(plays: pd.DataFrame):
    """A missing value is not a value, which is also what SQL's COUNT(DISTINCT x) does."""
    assert _for(plays.esql.query("SELECT state, seconds.count"), "CA", "seconds.count") == 2


def test_a_column_of_all_missing_values_has_no_count():
    """No value to count is not the same as counting zero: the aggregate is absent for that row,
    the same as any aggregate whose group matched nothing."""
    data = pd.DataFrame({"state": ["CA", "CA"], "seconds": [None, None]})
    assert pd.isna(data.esql.query("SELECT state, seconds.count")["seconds.count"].iloc[0])


###############################################################################
# Groups
###############################################################################
def test_a_group_takes_the_bare_form_too(plays: pd.DataFrame):
    """`g1.count` is group `g1`'s row count, which is the symmetry `g1.column.count` implies."""
    result = plays.esql.query("SELECT state, count, g1.count OVER g1 SUCH THAT g1.city = 'SF'")
    assert _for(result, "CA", "count") == 3
    assert _for(result, "CA", "g1.count") == 2


def test_a_group_count_is_missing_when_its_section_matches_nothing(plays: pd.DataFrame):
    result = plays.esql.query("SELECT state, g1.count OVER g1 SUCH THAT g1.city = 'SF'")
    assert pd.isna(_for(result, "NY", "g1.count"))


def test_a_group_cannot_be_named_after_a_column(plays: pd.DataFrame):
    """H4 is what makes this collision matter. `g1.count` is a group's row count, and if `g1` were
    also a column the same words would equally be that column's distinct count -- a query whose
    meaning depends on the frame it is handed. The name is refused where the query chooses it,
    rather than one reading being preferred at every reference."""
    with pytest.raises(ParsingError, match="names the column 'city'"):
        plays.esql.query("SELECT state, city.count OVER city SUCH THAT city.seconds > 5")


def test_a_group_column_count_is_distinct_within_the_group(plays: pd.DataFrame):
    result = plays.esql.query("SELECT state, g1.city.count, g1.count OVER g1 SUCH THAT g1.seconds > 5")
    assert _for(result, "CA", "g1.count") == 2  # the two rows with a present, matching value
    assert _for(result, "CA", "g1.city.count") == 1  # both of them are SF


###############################################################################
# The other clauses
###############################################################################
def test_having_filters_on_a_bare_count(plays: pd.DataFrame):
    result = plays.esql.query("SELECT state, count HAVING count > 1")
    assert list(result["state"]) == ["CA"]


def test_having_filters_on_a_distinct_count(plays: pd.DataFrame):
    assert list(plays.esql.query("SELECT state, city.count HAVING city.count > 1")["state"]) == ["CA"]


def test_a_count_named_in_both_select_and_having_is_computed_once(plays: pd.DataFrame):
    """BUG-8's shape. A duplicate aggregate used to be accumulated twice per row, and a row count
    reached from two clauses is the easiest way back into that."""
    assert _for(plays.esql.query("SELECT state, count HAVING count > 0"), "CA", "count") == 3


def test_order_by_takes_a_bare_count(plays: pd.DataFrame):
    result = plays.esql.query("SELECT state, count ORDER BY -count")
    assert list(result["state"]) == ["CA", "NY"]


def test_a_bare_count_folds_case_like_every_other_identifier(plays: pd.DataFrame):
    """And is labelled canonically, as v1.9.0 settled for columns and groups."""
    result = plays.esql.query("SELECT state, COUNT, G1.Count OVER g1 SUCH THAT g1.city = 'SF'")
    assert list(result.columns) == ["state", "count", "g1.count"]


###############################################################################
# What did not change
###############################################################################
def test_the_other_functions_still_run_over_rows(plays: pd.DataFrame):
    result = plays.esql.query("SELECT state, seconds.sum, seconds.avg, seconds.min, seconds.max")
    assert _for(result, "CA", "seconds.sum") == 30
    assert _for(result, "CA", "seconds.avg") == 15
    assert _for(result, "CA", "seconds.min") == 10
    assert _for(result, "CA", "seconds.max") == 20


def test_sum_over_count_is_no_longer_avg_and_avg_is_still_right(plays: pd.DataFrame):
    """The objection raised against H4 and overruled: `sum / count` equalling `avg` is a SQL
    identity, not a law. With `count` defined as distinct it simply does not hold, and `avg` keeps
    its own definition rather than inheriting one."""
    result = plays.esql.query("SELECT state, seconds.sum, seconds.count, seconds.avg")
    data = plays[plays["state"] == "CA"]["seconds"]
    assert _for(result, "CA", "seconds.avg") == data.mean()
    assert _for(result, "CA", "seconds.sum") / _for(result, "CA", "seconds.count") == data.mean()

    duplicated = pd.DataFrame({"state": ["CA", "CA"], "seconds": [10.0, 10.0]})
    doubled = duplicated.esql.query("SELECT state, seconds.sum, seconds.count, seconds.avg")
    assert doubled["seconds.avg"].iloc[0] == 10  # the mean of two tens
    assert doubled["seconds.sum"].iloc[0] / doubled["seconds.count"].iloc[0] == 20  # 20 over 1 value


###############################################################################
# Refusals, and the reserved word
###############################################################################
@pytest.mark.parametrize("function", ["sum", "avg", "min", "max"])
def test_every_other_function_needs_a_column(plays: pd.DataFrame, function: str):
    with pytest.raises(ParsingError, match=f"needs a column to aggregate: write 'column.{function}'"):
        plays.esql.query(f"SELECT state, {function}")


def test_the_refusal_says_which_function_can_stand_alone(plays: pd.DataFrame):
    with pytest.raises(ParsingError, match="Only count can be written on its own"):
        plays.esql.query("SELECT state, sum")


def test_a_bare_function_is_refused_in_having_too(plays: pd.DataFrame):
    with pytest.raises(ParsingError, match="needs a column to aggregate"):
        plays.esql.query("SELECT state, count HAVING sum > 1")


def test_a_word_that_is_neither_a_column_nor_a_function_is_still_an_invalid_column(plays: pd.DataFrame):
    with pytest.raises(ParsingError, match="Invalid column: 'nope'"):
        plays.esql.query("SELECT state, nope")


def test_a_frame_with_a_column_called_count_is_refused():
    """`count` means the row count wherever a column could go, so a column of that name is a word
    with two readings and no way for a query writer to say which. Preferring one would make
    `SELECT venue, count` mean different things over different data; preferring the other would put
    the row count out of reach for that frame alone. The name is refused where it was chosen."""
    data = pd.DataFrame({"state": ["CA", "CA"], "count": [7, 7]})
    with pytest.raises(ParsingError, match="Rename the column in the data"):
        data.esql.query("SELECT state")


def test_the_frame_is_refused_before_any_query_is_read():
    """At the accessor, not at the reference: a query that never writes the word is refused too,
    which is what makes the message about the data rather than about the query."""
    data = pd.DataFrame({"state": ["CA"], "count": [7]})
    with pytest.raises(ParsingError, match="named after the aggregate"):
        data.esql.validate("SELECT state")
    with pytest.raises(ParsingError, match="named after the aggregate"):
        data.esql  # noqa: B018 -- constructing the accessor is where the check runs


@pytest.mark.parametrize("spelling", ["Count", "COUNT"])
def test_the_reserved_name_is_refused_in_any_case(spelling: str):
    """Identifiers fold case, so a differently cased column is the same collision."""
    with pytest.raises(ParsingError, match=f"Column '{spelling}'"):
        pd.DataFrame({"state": ["CA"], spelling: [7]}).esql.query("SELECT state")


def test_a_column_named_for_another_function_is_left_alone():
    """Only a name that can be a whole aggregate is reserved. `sum` is never one on its own, so it
    has a single reading as a column and the frame is accepted: `SELECT state, sum` projects it, and
    the refusal for a missing column runs only once the word has failed to name one."""
    data = pd.DataFrame({"state": ["CA"], "sum": [7]})
    assert list(data.esql.query("SELECT state, sum").columns) == ["state", "sum"]
    assert data.esql.query("SELECT state, sum.sum")["sum.sum"].iloc[0] == 7
