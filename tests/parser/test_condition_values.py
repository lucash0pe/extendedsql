"""How the right side of a comparison is read, per dtype family (K3).

`OPERATOR_DTYPES` answers whether an operator applies to a column at all; these cover the question
after it, which value that comparison accepts. Both used to be answered by one chain of pandas dtype
predicates, and it ended by asking whether the dtype was numeric -- True for a bool column, so a
boolean compared against a number, and anything quoted reached a date column as text because pandas
reports the object dtype dates are stored as as a string dtype.

The failures those produced were the dangerous kind: no error, and an answer to a question nobody
asked. `credit = 1` matched the true rows, `date = 'hello'` matched nothing, and `date != 'hello'`
matched everything.
"""

from __future__ import annotations

import pandas as pd
import pytest

from esql.parser.error import ParsingError


@pytest.fixture
def data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "n": [1, 2, 3],
            "dt": pd.to_datetime(["2020-01-01", "2020-06-15", "2021-03-02"]),
            "txt": ["a", "b", "c"],
            "flag": [True, False, True],
            "g": ["x", "y", "z"],
        }
    )


###############################################################################
# Boolean columns take booleans, and nothing else
###############################################################################
@pytest.mark.parametrize("written", ["true", "TRUE", "True"])
def test_a_boolean_column_takes_a_boolean_literal_in_any_case(written: str, data: pd.DataFrame):
    assert list(data.esql.query(f"SELECT g WHERE flag = {written}")["g"]) == ["x", "z"]


def test_a_boolean_column_takes_false_as_well(data: pd.DataFrame):
    assert list(data.esql.query("SELECT g WHERE flag = false")["g"]) == ["y"]


@pytest.mark.parametrize("value", ["1", "0", "5", "'true'", "yes"])
def test_a_boolean_column_refuses_anything_that_is_not_a_boolean(value: str, data: pd.DataFrame):
    """`1` is the one that mattered: it used to parse, because pandas counts a bool column as
    numeric, and `flag = 1` then matched the true rows. `'true'` was already refused, which is what
    made the pair incoherent -- the quoted spelling raised while the numeric one answered."""
    with pytest.raises(ParsingError, match="compares against true or false"):
        data.esql.query(f"SELECT g WHERE flag = {value}")


def test_negating_a_boolean_comparison_is_still_a_boolean_comparison(data: pd.DataFrame):
    assert list(data.esql.query("SELECT g WHERE flag != true")["g"]) == ["y"]


###############################################################################
# Date columns take a quoted date, and nothing else
###############################################################################
@pytest.mark.parametrize("written", ["'2020-06-15'", "'2020/06/15'"])
def test_a_date_column_takes_a_quoted_date_in_either_separator(written: str, data: pd.DataFrame):
    assert list(data.esql.query(f"SELECT g WHERE dt = {written}")["g"]) == ["y"]


def test_a_date_column_orders_by_a_quoted_date(data: pd.DataFrame):
    assert list(data.esql.query("SELECT g WHERE dt >= '2020-06-15'")["g"]) == ["y", "z"]


@pytest.mark.parametrize("operator", ["=", "!=", ">", "<="])
def test_a_date_column_refuses_text_that_is_not_a_date(operator: str, data: pd.DataFrame):
    """This is the silent half of K3. Under `=` the text was compared against date objects and
    matched nothing; under `!=` it matched everything. Neither raised."""
    with pytest.raises(ParsingError, match="Invalid date"):
        data.esql.query(f"SELECT g WHERE dt {operator} 'hello'")


def test_a_date_column_refuses_an_unquoted_date(data: pd.DataFrame):
    with pytest.raises(ParsingError, match="Invalid date"):
        data.esql.query("SELECT g WHERE dt = 2020-06-15")


def test_a_date_column_refuses_a_quoted_impossible_date(data: pd.DataFrame):
    """Right shape, no such day. `_is_quoted_date` matches the pattern; strptime is what knows
    February has 28 days."""
    with pytest.raises(ParsingError, match="Invalid date"):
        data.esql.query("SELECT g WHERE dt = '2020-02-30'")


###############################################################################
# Text and number columns
###############################################################################
def test_a_text_column_takes_a_quoted_value(data: pd.DataFrame):
    assert list(data.esql.query("SELECT g WHERE txt = 'b'")["g"]) == ["y"]


@pytest.mark.parametrize("value", ["b", "5", "true"])
def test_a_text_column_refuses_an_unquoted_value(value: str, data: pd.DataFrame):
    with pytest.raises(ParsingError, match="A text value must be quoted"):
        data.esql.query(f"SELECT g WHERE txt = {value}")


@pytest.mark.parametrize(("written", "expected"), [("2", ["y"]), ("2.0", ["y"])])
def test_a_number_column_takes_a_number_however_it_is_written(written: str, expected: list, data: pd.DataFrame):
    assert list(data.esql.query(f"SELECT g WHERE n = {written}")["g"]) == expected


@pytest.mark.parametrize("value", ["'2'", "two", "true"])
def test_a_number_column_refuses_a_value_that_is_not_a_number(value: str, data: pd.DataFrame):
    with pytest.raises(ParsingError, match="Invalid value"):
        data.esql.query(f"SELECT g WHERE n = {value}")


###############################################################################
# The same rules in SUCH THAT
###############################################################################
def test_the_value_rules_hold_in_such_that_too(data: pd.DataFrame):
    """`_parse_condition_value` serves both clauses, so a fix in one is a fix in both. Asserted
    rather than assumed, since the two clauses reach it by different paths."""
    with pytest.raises(ParsingError, match="compares against true or false"):
        data.esql.query("SELECT g, g1.n.sum OVER g1 SUCH THAT g1.flag = 1")
    with pytest.raises(ParsingError, match="Invalid date"):
        data.esql.query("SELECT g, g1.n.sum OVER g1 SUCH THAT g1.dt = 'hello'")
