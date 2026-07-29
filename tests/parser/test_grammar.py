"""Assert `esql.GRAMMAR` against the parser it describes.

GRAMMAR is a description, not the implementation, so on its own it is just a second copy of rules
the parser already enforces, which is the drift this was built to remove. These tests are what
close that gap: each claim in the description is checked by running the real parser through
`df.esql.validate(...)` and seeing whether it accepts or rejects.

The operator coverage test is the important one. For every clause it asserts both directions, that
each listed operator parses and each unlisted one raises, so adding an operator to the grammar
without teaching a clause about it fails here rather than silently reaching the demo.
"""

import json

import pandas as pd
import pytest

from esql.grammar import GRAMMAR
from esql.parser.error import ParsingError
from esql.parser.util import (
    AGGREGATE_FUNCTIONS,
    CONDITIONAL_OPERATORS,
    KEYWORDS,
    SEMI_JOIN_OPERATOR,
)

ALL_OPERATORS = (*CONDITIONAL_OPERATORS, SEMI_JOIN_OPERATOR)


@pytest.fixture
def data() -> pd.DataFrame:
    return pd.DataFrame({"cust": ["a", "b"], "prod": ["x", "y"], "quant": [1, 2]})


def _condition(operator: str, prefix: str = "") -> str:
    """A minimal valid condition using `operator`, prefixed for SUCH THAT's group notation."""
    if operator in GRAMMAR["operators"]["text"]:
        return f"{prefix}prod {operator} 'x'"
    if operator == SEMI_JOIN_OPERATOR:
        return f"{prefix}prod {operator} {prefix}quant > 1"
    return f"{prefix}quant {operator} 1"


def _query_using(clause: str, operator: str) -> str:
    if clause == "WHERE":
        return f"SELECT cust, quant.sum WHERE {_condition(operator)}"
    if clause == "SUCH THAT":
        return f"SELECT cust, g1.quant.sum OVER g1 SUCH THAT {_condition(operator, prefix='g1.')}"
    if clause == "HAVING":
        if operator in GRAMMAR["operators"]["text"]:
            return f"SELECT cust, quant.sum HAVING quant.sum {operator} 'x'"
        if operator == SEMI_JOIN_OPERATOR:
            return f"SELECT cust, quant.sum HAVING quant.sum {operator} prod = 'x'"
        return f"SELECT cust, quant.sum HAVING quant.sum {operator} 1"
    raise AssertionError(f"no query template for clause {clause}")


###############################################################################
# Shape
###############################################################################
def test_grammar_is_json_serializable():
    # The whole export step downstream is json.dumps, so a non-serializable value breaks the build.
    assert json.loads(json.dumps(GRAMMAR)) == GRAMMAR


def test_grammar_describes_exactly_the_real_clauses():
    assert GRAMMAR["keywords"] == list(KEYWORDS)
    assert list(GRAMMAR["clauses"]) == list(KEYWORDS)


def test_every_accepted_slot_kind_is_defined():
    for clause, shape in GRAMMAR["clauses"].items():
        for kind in shape["accepts"]:
            assert kind in GRAMMAR["slot_kinds"], f"{clause} accepts undefined slot kind {kind!r}"


def test_every_described_operator_is_a_real_operator():
    for clause, shape in GRAMMAR["clauses"].items():
        for operator in shape["operators"]:
            assert operator in ALL_OPERATORS, f"{clause} lists unknown operator {operator!r}"


def test_aggregate_functions_are_partitioned_by_dtype_rule():
    described = GRAMMAR["aggregates"]
    assert described["functions"] == list(AGGREGATE_FUNCTIONS)
    assert sorted(described["numeric_only"] + described["any_dtype"]) == sorted(AGGREGATE_FUNCTIONS)
    assert not set(described["numeric_only"]) & set(described["any_dtype"])


###############################################################################
# The description against the parser
###############################################################################
@pytest.mark.parametrize("clause", ["WHERE", "SUCH THAT", "HAVING"])
def test_listed_operators_parse_and_unlisted_ones_raise(clause: str, data: pd.DataFrame):
    allowed = set(GRAMMAR["clauses"][clause]["operators"])
    assert allowed, f"{clause} should list operators"

    for operator in ALL_OPERATORS:
        query = _query_using(clause, operator)
        if operator in allowed:
            data.esql.validate(query)  # must not raise
        else:
            with pytest.raises(ParsingError):
                data.esql.validate(query)


@pytest.mark.parametrize("function", GRAMMAR["aggregates"]["numeric_only"])
def test_numeric_only_aggregates_reject_a_text_column(function: str, data: pd.DataFrame):
    with pytest.raises(ParsingError, match="not a numeric type"):
        data.esql.validate(f"SELECT cust, prod.{function}")


@pytest.mark.parametrize("function", GRAMMAR["aggregates"]["any_dtype"])
def test_dtype_agnostic_aggregates_accept_a_text_column(function: str, data: pd.DataFrame):
    data.esql.validate(f"SELECT cust, prod.{function}")


@pytest.mark.parametrize("form", GRAMMAR["aggregates"]["forms"])
def test_both_aggregate_forms_parse(form: str, data: pd.DataFrame):
    aggregate = form.replace("group", "g1").replace("column", "quant").replace("function", "sum")
    over = " OVER g1" if "g1." in aggregate else ""
    data.esql.validate(f"SELECT cust, {aggregate}{over}")


def test_such_that_requires_over_as_described(data: pd.DataFrame):
    assert GRAMMAR["clauses"]["SUCH THAT"]["requires"] == ["OVER"]
    # Without OVER there is no group for the section to scope, so the group reference is rejected.
    with pytest.raises(ParsingError):
        data.esql.validate("SELECT cust, g1.quant.sum SUCH THAT g1.prod = 'x'")


def test_only_such_that_accepts_an_entry_value_as_described(data: pd.DataFrame):
    accepting = [clause for clause, shape in GRAMMAR["clauses"].items() if "entry_value" in shape["accepts"]]
    assert accepting == ["SUCH THAT"]
    data.esql.validate("SELECT cust, quant, g1.quant.sum OVER g1 SUCH THAT g1.quant = quant - 1")
    # Everywhere else the same reference is a column with no grouped row to read it from.
    with pytest.raises(ParsingError):
        data.esql.validate("SELECT cust, quant, quant.sum WHERE quant = quant - 1")


def test_an_entry_value_must_be_a_grouping_attribute_as_described(data: pd.DataFrame):
    assert "grouping attribute" in GRAMMAR["slot_kinds"]["entry_value"]
    # `quant` is projected but not grouped on, so a grouped row holds no single value for it.
    with pytest.raises(ParsingError, match="not a SELECT grouping attribute"):
        data.esql.validate("SELECT cust, g1.quant.sum OVER g1 SUCH THAT g1.quant = quant - 1")


def test_select_is_the_only_required_clause(data: pd.DataFrame):
    required = [clause for clause, shape in GRAMMAR["clauses"].items() if shape["required"]]
    assert required == ["SELECT"]
    # Every other clause is genuinely omittable: SELECT alone parses.
    data.esql.validate("SELECT cust, quant.sum")


def test_select_needs_a_grouping_attribute_as_described(data: pd.DataFrame):
    assert "column" in GRAMMAR["clauses"]["SELECT"]["accepts"]
    with pytest.raises(ParsingError, match="No grouping attributes"):
        data.esql.validate("SELECT quant.sum")


def test_clause_order_follows_the_described_keyword_order(data: pd.DataFrame):
    # HAVING before WHERE inverts the documented order and must be rejected.
    assert GRAMMAR["keywords"].index("WHERE") < GRAMMAR["keywords"].index("HAVING")
    with pytest.raises(ParsingError, match="Unexpected position"):
        data.esql.validate("SELECT cust, quant.sum HAVING quant.sum > 0 WHERE quant > 0")


@pytest.mark.parametrize("clause", ["SELECT", "OVER", "SUCH THAT"])
def test_comma_separated_clauses_are_described_as_such(clause: str):
    assert GRAMMAR["clauses"][clause]["separator"] == ","


def test_repeating_a_group_across_such_that_sections_is_rejected(data: pd.DataFrame):
    with pytest.raises(ParsingError, match="Multiple sections"):
        data.esql.validate("SELECT cust, g1.quant.sum OVER g1 SUCH THAT g1.prod = 'x', g1.quant > 1")


###############################################################################
# Text literals
###############################################################################
def test_every_described_delimiter_really_delimits(data: pd.DataFrame):
    for delimiter in GRAMMAR["literals"]["text"]["delimiters"]:
        data.esql.validate(f"SELECT cust WHERE prod = {delimiter}x{delimiter}")


def test_each_delimiter_holds_the_other_as_ordinary_text(data: pd.DataFrame):
    delimiters = GRAMMAR["literals"]["text"]["delimiters"]
    for delimiter in delimiters:
        other = next(d for d in delimiters if d != delimiter)
        data.esql.validate(f"SELECT cust WHERE prod = {delimiter}x{other}y{delimiter}")


def test_the_described_escape_is_the_one_the_parser_implements(data: pd.DataFrame):
    """`doubling` is the published name; this is what it has to mean."""
    assert GRAMMAR["literals"]["text"]["escape"] == "doubling"
    for delimiter in GRAMMAR["literals"]["text"]["delimiters"]:
        data.esql.validate(f"SELECT cust WHERE prod = {delimiter}x{delimiter * 2}y{delimiter}")


def test_an_unterminated_literal_is_rejected_as_described(data: pd.DataFrame):
    for delimiter in GRAMMAR["literals"]["text"]["delimiters"]:
        with pytest.raises(ParsingError, match="Unterminated"):
            data.esql.validate(f"SELECT cust WHERE prod = {delimiter}x")


def test_only_the_delimiter_in_use_is_doubled_as_described():
    """The three forms the `text` summary names, each checked for what it actually denotes.

    Nothing bound this before, and the summary was wrong about the third: it claimed `"It''s"`
    denoted It's. Inside a double-quoted value an apostrophe is already ordinary text, so a doubled
    one is two apostrophes. A host implementing from the old wording would have doubled both
    delimiters and produced values matching nothing, which is the failure J4 had just fixed.
    """
    data = pd.DataFrame({"t": ["It's", "It''s"], "n": [1, 2]})
    denotes = {
        """SELECT t WHERE t = 'It''s'""": "It's",
        '''SELECT t WHERE t = "It's"''': "It's",
        '''SELECT t WHERE t = "It''s"''': "It''s",
    }
    for query, expected in denotes.items():
        assert list(data.esql.query(query)["t"]) == [expected], query

    summary = GRAMMAR["literals"]["text"]["summary"]
    assert "Only the delimiter in use is doubled" in summary
