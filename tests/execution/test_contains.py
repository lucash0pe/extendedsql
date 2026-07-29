"""The CONTAINS operator: a case-insensitive substring test over a text column.

CONTAINS is the one entry in CONDITIONAL_OPERATORS that is a word rather than a symbol, so these
cover the two things that distinguishes: it has to match on word boundaries (a column named
`contains_tax` is not a split point), and it is only meaningful where a text column is compared,
so HAVING rejects it. These go through the public df.esql.query(...) accessor.
"""

import pandas as pd
import pytest

from esql.parser.error import ParsingError


@pytest.fixture
def song_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "song": ["Dark Star", "dark side", "Scarlet Begonias", "Fire on the Mountain", None],
            "venue": ["Fillmore", "Winterland", "Fillmore", "Winterland", "Fillmore"],
            "seconds": [1200, 800, 600, 700, 500],
        }
    )


def test_contains_matches_a_substring(song_data: pd.DataFrame):
    result = song_data.esql.query("SELECT song, seconds.sum WHERE song CONTAINS 'Star'")
    assert set(result["song"]) == {"Dark Star"}


def test_contains_is_case_insensitive_in_both_directions(song_data: pd.DataFrame):
    # 'dark' matches "Dark Star" (value lowercase, data capitalized) and "dark side" (both lower).
    lower = song_data.esql.query("SELECT song, seconds.sum WHERE song CONTAINS 'dark'")
    assert set(lower["song"]) == {"Dark Star", "dark side"}

    # And the same pattern capitalized picks out exactly the same two rows.
    upper = song_data.esql.query("SELECT song, seconds.sum WHERE song CONTAINS 'DARK'")
    assert set(upper["song"]) == set(lower["song"])


def test_contains_keyword_is_case_insensitive(song_data: pd.DataFrame):
    result = song_data.esql.query("SELECT song, seconds.sum WHERE song contains 'Star'")
    assert set(result["song"]) == {"Dark Star"}


def test_contains_matching_nothing_returns_an_empty_result(song_data: pd.DataFrame):
    result = song_data.esql.query("SELECT song, seconds.sum WHERE song CONTAINS 'Truckin'")
    assert result.empty


def test_contains_skips_null_cells_rather_than_raising(song_data: pd.DataFrame):
    # The last row's song is NA. SQL NULL semantics: it compares as not-true, so it drops out
    # instead of raising "boolean value of NA is ambiguous".
    result = song_data.esql.query("SELECT song, seconds.sum WHERE song CONTAINS 'e'")
    assert set(result["song"]) == {"Scarlet Begonias", "Fire on the Mountain", "dark side"}


def test_contains_works_in_a_such_that_group(song_data: pd.DataFrame):
    result = song_data.esql.query(
        "SELECT venue, g1.seconds.sum OVER g1 SUCH THAT g1.song CONTAINS 'dark' ORDER BY 1"
    )
    # Fillmore's only 'dark' song is Dark Star (1200); Winterland's is dark side (800).
    by_venue = dict(zip(result["venue"], result["g1.seconds.sum"], strict=True))
    assert by_venue == {"Fillmore": 1200, "Winterland": 800}


def test_contains_does_not_split_a_column_name_that_starts_with_it():
    # `contains_tax` begins with the operator's letters. Word-boundary matching means the
    # condition splits on `>`, not inside the column name.
    data = pd.DataFrame({"item": ["ham", "fish"], "contains_tax": [10, 0], "quant": [5, 7]})
    result = data.esql.query("SELECT item, quant.sum WHERE contains_tax > 5")
    assert set(result["item"]) == {"ham"}


def test_contains_on_a_numeric_column_is_a_parsing_error(song_data: pd.DataFrame):
    with pytest.raises(ParsingError, match="CONTAINS needs a text column"):
        song_data.esql.query("SELECT song, seconds.sum WHERE seconds CONTAINS '12'")


def test_contains_with_an_unquoted_value_is_a_parsing_error(song_data: pd.DataFrame):
    with pytest.raises(ParsingError, match="CONTAINS needs a quoted text value"):
        song_data.esql.query("SELECT song, seconds.sum WHERE song CONTAINS Star")


def test_contains_in_having_is_a_parsing_error(song_data: pd.DataFrame):
    with pytest.raises(ParsingError, match="HAVING compares an aggregate"):
        song_data.esql.query("SELECT song, seconds.sum HAVING seconds.sum CONTAINS '12'")


def test_a_quoted_value_containing_the_keyword_is_not_a_split_point():
    data = pd.DataFrame({"note": ["this contains stuff", "plain"], "quant": [1, 2]})
    result = data.esql.query("SELECT note, quant.sum WHERE note = 'this contains stuff'")
    assert set(result["note"]) == {"this contains stuff"}
