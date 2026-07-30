"""Sorting the output by named SELECT terms, aggregates included (H3).

Before this, ORDER BY took one number meaning "the first N grouping attributes", so the second half
of the first question anyone asks of a dataset -- having counted something, sort by the count --
could not be written at all. Widening the number would not have fixed it: the sort it describes
always starts at the first grouping attribute, so `SELECT song, song.count ORDER BY 2` would sort by
song and then by the count, never by the count alone.

These go through the public accessor, since the point is what a query can now express.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest

from esql.parser.error import ParsingError


@pytest.fixture
def plays() -> pd.DataFrame:
    """Three songs with 3, 2 and 2 plays: enough for a tie, so the second sort key has work to do."""
    return pd.DataFrame(
        {
            "song": ["Truckin", "Truckin", "Truckin", "Dark Star", "Dark Star", "Sugaree", "Sugaree"],
            "venue": ["a", "b", "c", "a", "b", "a", "b"],
            "seconds": [10, 20, 30, 40, 50, 60, 70],
        }
    )


def _rows(result: pd.DataFrame, column: str = "song") -> list:
    return list(result[column])


###############################################################################
# The motivating query
###############################################################################
def test_sorting_by_an_aggregate_descending(plays: pd.DataFrame):
    """"Which did they play most" -- the query H3 was filed for."""
    result = plays.esql.query("SELECT song, seconds.count ORDER BY -seconds.count")
    assert _rows(result)[0] == "Truckin"
    assert list(result["seconds.count"]) == [3, 2, 2]


def test_sorting_by_an_aggregate_ascending(plays: pd.DataFrame):
    result = plays.esql.query("SELECT song, seconds.count ORDER BY seconds.count")
    assert list(result["seconds.count"]) == [2, 2, 3]


def test_a_second_term_breaks_the_tie(plays: pd.DataFrame):
    """Two songs have 2 plays each, so the count alone does not determine the order and `song` does."""
    result = plays.esql.query("SELECT song, seconds.count ORDER BY -seconds.count, song")
    assert _rows(result) == ["Truckin", "Dark Star", "Sugaree"]


def test_each_term_carries_its_own_direction(plays: pd.DataFrame):
    """The count descending, the tie broken descending: the pair a single reversed sort cannot make,
    since one `reverse` flips every key at once."""
    ascending_name = plays.esql.query("SELECT song, seconds.count ORDER BY -seconds.count, song")
    descending_name = plays.esql.query("SELECT song, seconds.count ORDER BY -seconds.count, -song")
    assert _rows(ascending_name) == ["Truckin", "Dark Star", "Sugaree"]
    assert _rows(descending_name) == ["Truckin", "Sugaree", "Dark Star"]


def test_sorting_by_a_group_specific_aggregate(plays: pd.DataFrame):
    result = plays.esql.query(
        "SELECT song, g1.seconds.sum OVER g1 SUCH THAT g1.venue = 'a' ORDER BY -g1.seconds.sum"
    )
    assert _rows(result) == ["Sugaree", "Dark Star", "Truckin"]


###############################################################################
# Named grouping attributes
###############################################################################
def test_sorting_by_a_named_grouping_attribute(plays: pd.DataFrame):
    result = plays.esql.query("SELECT song, seconds.count ORDER BY song")
    assert _rows(result) == ["Dark Star", "Sugaree", "Truckin"]


def test_sorting_by_a_named_attribute_descending(plays: pd.DataFrame):
    result = plays.esql.query("SELECT song, seconds.count ORDER BY -song")
    assert _rows(result) == ["Truckin", "Sugaree", "Dark Star"]


def test_a_term_is_resolved_case_insensitively(plays: pd.DataFrame):
    """Identifiers fold like everywhere else since v1.9.0, and an aggregate's function does too."""
    result = plays.esql.query("SELECT song, seconds.count ORDER BY -SECONDS.COUNT")
    assert _rows(result)[0] == "Truckin"


###############################################################################
# The integer shorthand still means what it meant
###############################################################################
def test_the_integer_form_sorts_by_the_first_n_attributes(plays: pd.DataFrame):
    by_number = plays.esql.query("SELECT song, venue, seconds.sum ORDER BY 2")
    by_name = plays.esql.query("SELECT song, venue, seconds.sum ORDER BY song, venue")
    assert by_number.equals(by_name)


def test_a_negative_integer_runs_every_attribute_descending(plays: pd.DataFrame):
    by_number = plays.esql.query("SELECT song, venue, seconds.sum ORDER BY -2")
    by_name = plays.esql.query("SELECT song, venue, seconds.sum ORDER BY -song, -venue")
    assert by_number.equals(by_name)


def test_zero_and_an_omitted_clause_agree(plays: pd.DataFrame):
    assert plays.esql.query("SELECT song, seconds.count ORDER BY 0").equals(
        plays.esql.query("SELECT song, seconds.count")
    )


###############################################################################
# Refusals
###############################################################################
def test_a_term_the_query_does_not_project_is_refused(plays: pd.DataFrame):
    """`venue` is a real column, but this query returns no value for it per output row."""
    with pytest.raises(ParsingError, match="'venue' is not a SELECT term"):
        plays.esql.query("SELECT song, seconds.count ORDER BY venue")


def test_the_refusal_names_what_could_have_been_meant(plays: pd.DataFrame):
    with pytest.raises(ParsingError, match=re.escape("Available: song, seconds.count")):
        plays.esql.query("SELECT song, seconds.count ORDER BY venue")


def test_an_aggregate_that_is_not_selected_is_refused(plays: pd.DataFrame):
    """Sorting by an aggregate the query never computes. It is not that the aggregate is illegal,
    it is that nothing in the output holds it."""
    with pytest.raises(ParsingError, match="is not a SELECT term"):
        plays.esql.query("SELECT song, seconds.count ORDER BY seconds.sum")


def test_an_index_past_the_grouping_attributes_is_refused(plays: pd.DataFrame):
    with pytest.raises(ParsingError, match="out of range"):
        plays.esql.query("SELECT song, seconds.count ORDER BY 2")


def test_an_empty_term_is_refused(plays: pd.DataFrame):
    with pytest.raises(ParsingError, match="Empty sort term"):
        plays.esql.query("SELECT song, seconds.count ORDER BY song, ")


###############################################################################
# Nulls
###############################################################################
def test_a_missing_aggregate_value_sorts_last_ascending():
    """A group whose SUCH THAT section matched nothing has no value for its aggregate. Ascending, a
    missing value sorts last rather than raising on a comparison against a number."""
    data = pd.DataFrame({"song": ["a", "b"], "venue": ["x", "y"], "seconds": [1, 2]})
    result = data.esql.query(
        "SELECT song, g1.seconds.sum OVER g1 SUCH THAT g1.venue = 'x' ORDER BY g1.seconds.sum"
    )
    assert _rows(result) == ["a", "b"]
    assert pd.isna(list(result["g1.seconds.sum"])[-1])
