"""The HAS semi-join predicate: `<key> HAS <condition>`.

HAS keeps rows whose `key` value belongs to some row satisfying `condition`, which is how a query
reaches across grains without a join. It is the only condition that is not a question about the row
in hand, so the cases that matter are the ones where that distinction shows: the inner condition
reads the unfiltered table, and the key set is computed once rather than per row.

The fixture is one song-grain table where a "show" is the derived grain `date`, the motivating case
in .claude/status.md. These go through the public df.esql.query(...) accessor.
"""

from datetime import date

import pandas as pd
import pytest

from esql.parser.error import ParsingError

# The accessor coerces yyyy-mm-dd text to datetime.date, so the key set is built from real dates.
MAY_08 = date(1977, 5, 8)
MAY_22 = date(1977, 5, 22)


@pytest.fixture
def setlist_data() -> pd.DataFrame:
    # Two shows opened with Dark Star (05-08, 05-22) and one did not (05-09).
    return pd.DataFrame(
        {
            "date": ["1977-05-08", "1977-05-08", "1977-05-09", "1977-05-09", "1977-05-22"],
            "song": ["Dark Star", "Sugaree", "Scarlet", "Fire", "Dark Star"],
            "seconds": [1200, 400, 600, 700, 1100],
        }
    )


def test_has_keeps_every_row_of_a_matching_group(setlist_data: pd.DataFrame):
    result = setlist_data.esql.query("SELECT date, song, seconds.sum WHERE date HAS song = 'Dark Star' ORDER BY 1")
    # Both Dark Star dates come back whole, Sugaree included; the 05-09 show drops entirely.
    assert set(zip(result["date"], result["song"], strict=True)) == {
        (MAY_08, "Dark Star"),
        (MAY_08, "Sugaree"),
        (MAY_22, "Dark Star"),
    }


def test_the_inner_condition_reads_the_unfiltered_table(setlist_data: pd.DataFrame):
    # The AND removes every Dark Star row, but the key set was computed before that filter, so the
    # dates it found still stand. This is the grain-bridging case: "other songs played at a show
    # that also played Dark Star".
    result = setlist_data.esql.query(
        "SELECT date, song, seconds.sum WHERE date HAS song = 'Dark Star' AND song != 'Dark Star' ORDER BY 1"
    )
    assert set(zip(result["date"], result["song"], strict=True)) == {(MAY_08, "Sugaree")}


def test_has_composes_with_contains(setlist_data: pd.DataFrame):
    # HAS delegates case sensitivity to the inner operator, so a CONTAINS inside it is insensitive.
    result = setlist_data.esql.query("SELECT song, seconds.sum WHERE date HAS song CONTAINS 'dark' ORDER BY 1")
    assert set(result["song"]) == {"Dark Star", "Sugaree"}


def test_has_inner_condition_can_be_compound_when_parenthesized(setlist_data: pd.DataFrame):
    result = setlist_data.esql.query(
        "SELECT date, song, seconds.sum WHERE date HAS (song = 'Dark Star' AND seconds > 1150) ORDER BY 1"
    )
    # Only the 05-08 Dark Star ran past 1150, so 05-22 no longer qualifies.
    assert set(result["date"]) == {MAY_08}


def test_has_binds_tighter_than_and(setlist_data: pd.DataFrame):
    # Without parens the AND is the outer operator, so this is (date HAS song='Dark Star') AND
    # (seconds > 1150) and the second clause filters rows rather than narrowing the key set.
    result = setlist_data.esql.query(
        "SELECT date, song, seconds.sum WHERE date HAS song = 'Dark Star' AND seconds > 1150 ORDER BY 1"
    )
    assert set(zip(result["date"], result["song"], strict=True)) == {(MAY_08, "Dark Star")}


def test_has_works_under_or(setlist_data: pd.DataFrame):
    result = setlist_data.esql.query(
        "SELECT song, seconds.sum WHERE date HAS song = 'Scarlet' OR song = 'Sugaree' ORDER BY 1"
    )
    assert set(result["song"]) == {"Scarlet", "Fire", "Sugaree"}


def test_has_works_under_not(setlist_data: pd.DataFrame):
    result = setlist_data.esql.query("SELECT song, seconds.sum WHERE NOT (date HAS song = 'Dark Star') ORDER BY 1")
    assert set(result["song"]) == {"Scarlet", "Fire"}


def test_nested_has_resolves_the_outer_predicate_first(setlist_data: pd.DataFrame):
    # The inner HAS is itself a semi-join: dates that played a song that ran over 1150 seconds.
    result = setlist_data.esql.query(
        "SELECT date, song, seconds.sum WHERE date HAS (date HAS seconds > 1150) ORDER BY 1"
    )
    assert set(result["date"]) == {MAY_08}


def test_a_null_key_belongs_to_no_group():
    data = pd.DataFrame(
        {
            "date": ["1977-05-08", None, "1977-05-08"],
            "song": ["Dark Star", "Dark Star", "Sugaree"],
            "seconds": [1200, 900, 400],
        }
    )
    result = data.esql.query("SELECT song, seconds.sum WHERE date HAS song = 'Dark Star'")
    # The NA-dated Dark Star neither contributes a key nor survives the filter.
    assert set(result["song"]) == {"Dark Star", "Sugaree"}
    assert result[result["song"] == "Dark Star"]["seconds.sum"].iloc[0] == 1200


def test_has_works_on_a_numeric_key():
    data = pd.DataFrame({"year": [1977, 1977, 1980], "song": ["Dark Star", "Sugaree", "Fire"], "seconds": [1, 2, 3]})
    result = data.esql.query("SELECT song, seconds.sum WHERE year HAS song = 'Dark Star'")
    assert set(result["song"]) == {"Dark Star", "Sugaree"}


def test_a_column_name_containing_has_is_not_a_split_point():
    # `has_encore` starts with the keyword and `phase` contains it; neither is the operator.
    data = pd.DataFrame({"has_encore": [True, False], "phase": ["a", "b"], "quant": [5, 7]})
    result = data.esql.query("SELECT phase, quant.sum WHERE has_encore = true")
    assert set(result["phase"]) == {"a"}


def test_has_with_an_unknown_key_column_is_a_parsing_error(setlist_data: pd.DataFrame):
    with pytest.raises(ParsingError, match="Invalid column: venue"):
        setlist_data.esql.query("SELECT song, seconds.sum WHERE venue HAS song = 'Dark Star'")


def test_has_with_nothing_after_it_is_a_parsing_error(setlist_data: pd.DataFrame):
    with pytest.raises(ParsingError, match="HAS needs a condition after it"):
        setlist_data.esql.query("SELECT song, seconds.sum WHERE date HAS")


def test_has_with_nothing_before_it_is_a_parsing_error(setlist_data: pd.DataFrame):
    with pytest.raises(ParsingError, match="HAS needs a column before it"):
        setlist_data.esql.query("SELECT song, seconds.sum WHERE HAS song = 'Dark Star'")


def test_has_in_such_that_is_a_parsing_error(setlist_data: pd.DataFrame):
    with pytest.raises(ParsingError, match="belongs in WHERE, not SUCH THAT"):
        setlist_data.esql.query(
            "SELECT date, g1.seconds.sum OVER g1 SUCH THAT g1.date HAS g1.song = 'Dark Star'"
        )


def test_has_in_having_is_a_parsing_error(setlist_data: pd.DataFrame):
    with pytest.raises(ParsingError, match="belongs in WHERE, not HAVING"):
        setlist_data.esql.query("SELECT song, seconds.sum HAVING seconds.sum HAS song = 'Dark Star'")


def test_quoted_text_containing_the_keyword_is_not_a_split_point():
    data = pd.DataFrame({"note": ["the band has left", "plain"], "quant": [1, 2]})
    result = data.esql.query("SELECT note, quant.sum WHERE note = 'the band has left'")
    assert set(result["note"]) == {"the band has left"}
