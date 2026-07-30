"""The parse-only entry point, and the token a ParsingError carries.

Together these are what an editor needs to give live feedback: `validate` is cheap enough to run
while someone types, and `token` says which fragment of the query to point at.
"""

import pytest

from esql.parser.error import ParsingError, ParsingErrorType


def test_validate_accepts_a_query_that_parses(sales_test_data):
    assert sales_test_data.esql.validate("SELECT cust, quant.avg WHERE quant > 10") is None


def test_validate_accepts_every_clause_together(sales_test_data):
    query = (
        "SELECT cust, quant.max, g1.quant.sum OVER g1 WHERE quant > 5 "
        "SUCH THAT g1.state = 'NJ' HAVING quant.max > 1 ORDER BY 1"
    )
    assert sales_test_data.esql.validate(query) is None


def test_validate_does_not_execute_the_query(sales_test_data):
    """A valid query that matches no rows still validates — validity is not about results."""
    assert sales_test_data.esql.validate("SELECT cust, quant.avg WHERE quant > 100000000") is None


@pytest.mark.parametrize(
    ("query", "error_type", "token"),
    [
        ("SELECT cust, quantt.avg", ParsingErrorType.SELECT_CLAUSE, "quantt.avg"),
        ("SELECT cust, quant.summ", ParsingErrorType.SELECT_CLAUSE, "quant.summ"),
        ("SELECT nosuch", ParsingErrorType.SELECT_CLAUSE, "nosuch"),
        ("SELECT cust WHERE nosuch > 1", ParsingErrorType.WHERE_CLAUSE, "nosuch"),
        ("SELECT cust, quant.avg OVER g1!", ParsingErrorType.OVER_CLAUSE, "g1!"),
    ],
)
def test_validate_reports_the_offending_token(sales_test_data, query, error_type, token):
    with pytest.raises(ParsingError) as excinfo:
        sales_test_data.esql.validate(query)
    assert excinfo.value.error_type is error_type
    assert excinfo.value.token == token


def test_token_is_spelled_as_the_query_spelled_it(sales_test_data):
    """The token comes back exactly as written, so an editor can find it in what the user typed.

    It used to come back lowercased, because the parser ran on a lowercased copy of the query. That
    is the same fold that made a mixed-case column unreachable (K1); now that it is gone, a token
    matches literally rather than only case-insensitively.
    """
    with pytest.raises(ParsingError) as excinfo:
        sales_test_data.esql.validate("SELECT cust, QUANTT.avg")
    assert excinfo.value.token == "QUANTT.avg"


def test_group_prefixed_aggregate_without_over_is_a_parsing_error(sales_test_data):
    """Writing `g1.quant.sum` before declaring `OVER g1` is the ordinary way into this: it used to
    escape as a TypeError from a membership test against a None group list."""
    with pytest.raises(ParsingError) as excinfo:
        sales_test_data.esql.validate("SELECT cust, g1.quant.sum")
    assert excinfo.value.token == "g1.quant.sum"


def test_validate_and_query_raise_the_same_error(sales_test_data):
    """One error contract for both paths, so an editor can pre-check with validate and trust that
    a query which passes will not fail differently at run time."""
    bad = "SELECT cust, quantt.avg"
    with pytest.raises(ParsingError) as from_validate:
        sales_test_data.esql.validate(bad)
    with pytest.raises(ParsingError) as from_query:
        sales_test_data.esql.query(bad)
    assert from_validate.value.error_type is from_query.value.error_type
    assert from_validate.value.token == from_query.value.token
    assert from_validate.value.message == from_query.value.message


if __name__ == "__main__":
    pytest.main()
