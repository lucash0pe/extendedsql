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

from esql.dataset_schema import DATASET_SCHEMA
from esql.grammar import GRAMMAR
from esql.parser.error import ParsingError
from esql.parser.util import (
    AGGREGATE_FUNCTIONS,
    BARE_AGGREGATE_FUNCTIONS,
    CONDITIONAL_OPERATORS,
    DTYPE_FAMILIES,
    KEYWORDS,
    OPERATOR_DTYPES,
    SEMI_JOIN_OPERATOR,
    dtype_family,
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
def test_every_aggregate_form_parses(form: str, data: pd.DataFrame):
    aggregate = form.replace("group", "g1").replace("column", "quant").replace("function", "sum")
    over = " OVER g1" if aggregate.startswith("g1.") else ""
    data.esql.validate(f"SELECT cust, {aggregate}{over}")


@pytest.mark.parametrize("form", [form for form in GRAMMAR["aggregates"]["forms"] if "column" not in form])
def test_a_form_that_names_no_column_is_the_row_count(form: str):
    """The published forms are the four shapes, and two of them carry no column. That is a claim
    about meaning, not just about parsing: the number they return has to be the row count, or the
    bare form is just another spelling of something that borrows a column."""
    data = pd.DataFrame({"cust": ["a", "a", "b"], "quant": [1, 1, 2]})
    aggregate = form.replace("group", "g1")
    over = " OVER g1 SUCH THAT g1.quant > 0" if aggregate.startswith("g1.") else ""
    result = data.esql.query(f"SELECT cust, {aggregate}{over}")
    assert list(result[aggregate]) == [2, 1]


def test_every_function_that_can_stand_alone_has_both_of_its_forms_published():
    """The parser reads `BARE_AGGREGATE_FUNCTIONS` for legality and `forms` is what a host reads to
    offer them, so a form dropped from the list is surface the parser accepts and nobody can find.
    Parametrizing over `forms` cannot catch that: removing an entry removes its test with it."""
    forms = GRAMMAR["aggregates"]["forms"]
    for function in BARE_AGGREGATE_FUNCTIONS:
        assert function in forms, f"{function} can stand alone and no form says so"
        assert f"group.{function}" in forms, f"{function} can stand alone in a group and no form says so"


def test_a_column_count_counts_distinct_values_as_described(data: pd.DataFrame):
    """`slot_kinds["aggregate"]` says the column form counts distinct values, which is what makes
    the column in it bear on the answer at all. Two identical values, one count."""
    assert "distinct values" in GRAMMAR["slot_kinds"]["aggregate"]
    repeated = pd.DataFrame({"cust": ["a", "a"], "prod": ["x", "x"]})
    assert repeated.esql.query("SELECT cust, prod.count")["prod.count"].iloc[0] == 1


def test_the_any_dtype_rule_governs_the_column_form_only(data: pd.DataFrame):
    """The narrowing H4 forced. `any_dtype` says which functions a non-numeric *column* may be
    given, and the bare form gives none, so it sits outside the rule rather than inside it."""
    for function in GRAMMAR["aggregates"]["numeric_only"]:
        assert function not in GRAMMAR["aggregates"]["forms"], f"{function} claims a form with no column"


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


@pytest.mark.parametrize("clause", ["SELECT", "OVER", "SUCH THAT", "ORDER BY"])
def test_comma_separated_clauses_are_described_as_such(clause: str):
    assert GRAMMAR["clauses"][clause]["separator"] == ","


def test_order_by_accepts_both_described_slot_kinds(data: pd.DataFrame):
    """The two spellings the grammar declares, each run through the parser."""
    assert GRAMMAR["clauses"]["ORDER BY"]["accepts"] == ["sort_term", "grouping_attribute_index"]
    data.esql.validate("SELECT cust, quant.sum ORDER BY -quant.sum, cust")  # sort_term
    data.esql.validate("SELECT cust, quant.sum ORDER BY 1")  # grouping_attribute_index


def test_a_sort_term_must_be_projected_as_described(data: pd.DataFrame):
    assert "must be one the query projects" in GRAMMAR["slot_kinds"]["sort_term"]
    # `prod` is a column of the frame, but this query does not return it.
    with pytest.raises(ParsingError, match="is not a SELECT term"):
        data.esql.validate("SELECT cust, quant.sum ORDER BY prod")


def test_the_index_counts_grouping_attributes_not_select_terms_as_described(data: pd.DataFrame):
    """The number is bounded by the grouping attributes alone, which is exactly why it cannot reach
    an aggregate: `SELECT cust, quant.sum` has one attribute, so `2` is out of range rather than
    naming the aggregate."""
    assert "not the Nth" in GRAMMAR["slot_kinds"]["grouping_attribute_index"]
    data.esql.validate("SELECT cust, quant.sum ORDER BY 1")
    with pytest.raises(ParsingError, match="out of range"):
        data.esql.validate("SELECT cust, quant.sum ORDER BY 2")


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


###############################################################################
# Operator legality by dtype (G3)
###############################################################################
# The second axis. `clauses[c]["operators"]` is the first, and a host reading only that offers
# `song >` on a text column and watches the engine refuse it. Every cell of the table is bound below,
# in both directions, so a rule the parser applies cannot go unpublished and a published rule cannot
# be wrong.
COLUMN_OF_FAMILY = {"number": "num", "date": "dt", "string": "txt", "boolean": "flag"}
VALUE_OF_FAMILY = {"number": "1", "date": "'2020-01-01'", "string": "'a'", "boolean": "true"}
CELLS = [(op, family) for op in OPERATOR_DTYPES for family in DTYPE_FAMILIES]


@pytest.fixture
def typed() -> pd.DataFrame:
    """One column per dtype family, plus a text column to group by."""
    return pd.DataFrame(
        {
            "num": [1, 2],
            "dt": pd.to_datetime(["2020-01-01", "2020-01-02"]),
            "txt": ["a", "b"],
            "flag": [True, False],
            "g": ["x", "y"],
        }
    )


def test_the_published_families_are_the_ones_the_parser_sorts_columns_into(typed: pd.DataFrame):
    enforced = typed.esql.data
    assert GRAMMAR["operators"]["dtype_families"] == list(DTYPE_FAMILIES)
    for family, column in COLUMN_OF_FAMILY.items():
        assert dtype_family(enforced[column].dtype) == family


def test_the_families_are_the_vocabulary_a_demo_asset_speaks():
    """A host looks a column's `type` up in this table, so the two published artifacts have to use
    one set of names. If they diverge, every lookup misses and the host silently offers nothing."""
    assert sorted(DATASET_SCHEMA["$defs"]["ColumnType"]["enum"]) == sorted(DTYPE_FAMILIES)


def test_every_comparison_operator_has_a_dtype_rule():
    """A new operator cannot reach a host undeclared: `_parse_condition_value` reads this table, so
    an operator missing from it is rejected outright rather than defaulting to legal."""
    assert set(GRAMMAR["operators"]["dtypes"]) == set(CONDITIONAL_OPERATORS)


def test_every_rule_names_only_real_families():
    for operator, families in GRAMMAR["operators"]["dtypes"].items():
        assert families, f"{operator} applies to nothing"
        for family in families:
            assert family in DTYPE_FAMILIES, f"{operator} lists unknown dtype family {family!r}"


@pytest.mark.parametrize(("operator", "family"), CELLS)
def test_a_listed_dtype_parses_and_an_unlisted_one_raises(operator: str, family: str, typed: pd.DataFrame):
    column, value = COLUMN_OF_FAMILY[family], VALUE_OF_FAMILY[family]
    query = f"SELECT g WHERE {column} {operator} {value}"
    if family in GRAMMAR["operators"]["dtypes"][operator]:
        typed.esql.validate(query)  # must not raise
    else:
        with pytest.raises(ParsingError, match="does not apply to"):
            typed.esql.validate(query)


@pytest.mark.parametrize(("operator", "family"), CELLS)
def test_the_dtype_rule_is_the_same_in_such_that(operator: str, family: str, typed: pd.DataFrame):
    """The table is a property of the operator, not of the clause, and SUCH THAT compares raw column
    values exactly as WHERE does. HAVING has no cell in it: it compares aggregates, which are always
    numeric."""
    column, value = COLUMN_OF_FAMILY[family], VALUE_OF_FAMILY[family]
    query = f"SELECT g, g1.num.sum OVER g1 SUCH THAT g1.{column} {operator} {value}"
    if family in GRAMMAR["operators"]["dtypes"][operator]:
        typed.esql.validate(query)  # must not raise
    else:
        with pytest.raises(ParsingError, match="does not apply to"):
            typed.esql.validate(query)


def test_contains_no_longer_reaches_a_date_column(typed: pd.DataFrame):
    """The one cell this changed. `dt CONTAINS '2020'` used to parse and substring-match the date's
    ISO text, because pandas reports the object dtype dates are stored as as a string dtype -- so the
    guard meaning "text column" let dates through. It was never a stated behavior, and publishing it
    would have rested the contract on that loose check."""
    assert "date" not in GRAMMAR["operators"]["dtypes"]["CONTAINS"]
    with pytest.raises(ParsingError, match="'CONTAINS' does not apply to a date column"):
        typed.esql.validate("SELECT g WHERE dt CONTAINS '2020'")
