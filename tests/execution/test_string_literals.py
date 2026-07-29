"""String literals: what delimits one, and how it holds a delimiter as data.

A text value is written between a matched pair of ' or ", and holds that same character by
doubling it. Both quote kinds delimit, so most values needing an apostrophe can simply be written
in double quotes; doubling is what covers the rest, including a value needing both kinds.

These exist because the engine used to get this wrong in the worst available way. `WHERE song =
'(I'm A) Road Runner'` raised nothing and returned nothing: `_prepare_query` found literals with
the regex `'[^']*'`, which closes at the first quote it meets rather than at the one that ends the
literal, so everything after the apostrophe was treated as unquoted text and lowercased. The value
then parsed cleanly and matched no row. 62 of the 436 songs in the demo dataset carry an
apostrophe. See `.claude/status.md`, J4.

The same misreading reached two other things, covered below: a clause keyword inside a literal
split the clause there, and whitespace inside a literal was collapsed with the rest of the query.

These go through the public df.esql.query(...) accessor.
"""

import pandas as pd
import pytest

from esql.parser.error import ParsingError, ParsingErrorType


@pytest.fixture
def song_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "song": [
                "(I'm A) Road Runner",
                "He's Gone",
                "Dark Star",
                'Say "Hi"',
                "It's a \"Quote\"",
                "order by me",
                "Dark  Star",
            ],
            "venue": ["Fillmore", "Winterland", "Fillmore", "Winterland", "Fillmore", "Fillmore", "Winterland"],
            "seconds": [100, 200, 300, 400, 500, 600, 700],
        }
    )


###########################################################################
# The delimiters
###########################################################################
def test_the_other_quote_kind_holds_an_apostrophe(song_data: pd.DataFrame):
    result = song_data.esql.query("""SELECT song WHERE song = "(I'm A) Road Runner" """)
    assert list(result["song"]) == ["(I'm A) Road Runner"]


def test_a_single_quoted_value_holds_a_double_quote(song_data: pd.DataFrame):
    result = song_data.esql.query("""SELECT song WHERE song = 'Say "Hi"' """)
    assert list(result["song"]) == ['Say "Hi"']


def test_a_literal_ends_at_its_own_delimiter_not_the_other_kind(song_data: pd.DataFrame):
    """`'Dark Star' AND venue = "Fillmore"` is two literals, not one running to the last quote."""
    result = song_data.esql.query("""SELECT song WHERE song = 'Dark Star' AND venue = "Fillmore" """)
    assert list(result["song"]) == ["Dark Star"]


###########################################################################
# Doubling
###########################################################################
def test_doubling_holds_the_delimiter_as_data(song_data: pd.DataFrame):
    result = song_data.esql.query("""SELECT song WHERE song = '(I''m A) Road Runner'""")
    assert list(result["song"]) == ["(I'm A) Road Runner"]


def test_doubling_works_for_the_double_quote_too(song_data: pd.DataFrame):
    result = song_data.esql.query('''SELECT song WHERE song = "Say ""Hi"""''')
    assert list(result["song"]) == ['Say "Hi"']


def test_doubling_covers_a_value_needing_both_quote_kinds(song_data: pd.DataFrame):
    """The one case neither delimiter alone can express."""
    result = song_data.esql.query("""SELECT song WHERE song = 'It''s a "Quote"'""")
    assert list(result["song"]) == ['It\'s a "Quote"']


def test_a_doubled_delimiter_does_not_end_the_literal(song_data: pd.DataFrame):
    """The clause after it still parses, so the doubled pair was read as data and not as a close."""
    result = song_data.esql.query("""SELECT song WHERE song = 'He''s Gone' AND venue = 'Winterland'""")
    assert list(result["song"]) == ["He's Gone"]


def test_doubling_works_in_contains(song_data: pd.DataFrame):
    result = song_data.esql.query("""SELECT song WHERE song CONTAINS 'I''m'""")
    assert list(result["song"]) == ["(I'm A) Road Runner"]


###########################################################################
# The floor: an unterminated literal is rejected rather than guessed at
###########################################################################
def test_an_unbalanced_quote_raises_rather_than_matching_nothing(song_data: pd.DataFrame):
    """The J4 query itself. What matters is that it raises at all."""
    with pytest.raises(ParsingError) as parsing_error:
        song_data.esql.query("""SELECT song WHERE song = '(I'm A) Road Runner'""")
    assert parsing_error.value.error_type == ParsingErrorType.STRING_LITERAL
    assert "Unterminated" in parsing_error.value.message


def test_the_unterminated_message_names_both_ways_out(song_data: pd.DataFrame):
    with pytest.raises(ParsingError) as parsing_error:
        song_data.esql.query("""SELECT song WHERE song = 'He's Gone' AND seconds = 200""")
    message = parsing_error.value.message
    assert "''" in message
    assert '"' in message


def test_a_literal_opened_with_one_delimiter_and_closed_with_the_other_is_unterminated(
    song_data: pd.DataFrame,
):
    with pytest.raises(ParsingError) as parsing_error:
        song_data.esql.query("""SELECT song WHERE song = 'Dark Star" """)
    assert parsing_error.value.error_type == ParsingErrorType.STRING_LITERAL


def test_a_trailing_doubled_quote_does_not_close_the_literal(song_data: pd.DataFrame):
    """`'abc''` is an open literal holding `abc'`, not a closed one followed by a stray quote."""
    with pytest.raises(ParsingError) as parsing_error:
        song_data.esql.query("""SELECT song WHERE song = 'Dark Star''""")
    assert parsing_error.value.error_type == ParsingErrorType.STRING_LITERAL


###########################################################################
# What else the misreading reached
###########################################################################
def test_a_clause_keyword_inside_a_literal_does_not_split_the_clause(song_data: pd.DataFrame):
    """`'order by me'` used to have an ORDER BY clause cut out of the middle of it."""
    result = song_data.esql.query("""SELECT song WHERE song = 'order by me'""")
    assert list(result["song"]) == ["order by me"]


def test_a_logical_operator_inside_a_literal_does_not_split_the_condition(song_data: pd.DataFrame):
    song_data.loc[len(song_data)] = ["Scarlet and Fire", "Fillmore", 800]
    result = song_data.esql.query("""SELECT song WHERE song = 'Scarlet and Fire'""")
    assert list(result["song"]) == ["Scarlet and Fire"]


def test_whitespace_inside_a_literal_is_data(song_data: pd.DataFrame):
    """The whitespace collapse that canonicalizes a query has to stop at a literal's delimiters."""
    result = song_data.esql.query("""SELECT song WHERE song = 'Dark  Star'""")
    assert list(result["song"]) == ["Dark  Star"]


def test_case_inside_a_literal_is_data_while_the_rest_of_the_query_folds(song_data: pd.DataFrame):
    result = song_data.esql.query("""sElEcT song wHeRe song = 'Dark Star'""")
    assert list(result["song"]) == ["Dark Star"]
    assert song_data.esql.query("""SELECT song WHERE song = 'dark star'""").empty


def test_a_control_character_outside_a_literal_is_not_mistaken_for_one(song_data: pd.DataFrame):
    """The mask blanks literals to a filler byte, so nothing may infer literals back out of it."""
    song_data.loc[len(song_data)] = ["A\x00B", "Fillmore", 900]
    result = song_data.esql.query("SELECT SONG WHERE song = 'A\x00B'")
    assert list(result["song"]) == ["A\x00B"]
