"""Identifiers are case-insensitive, and a mixed-case DataFrame column is reachable.

Regression cover for `.claude/status.md`, K1. `_prepare_query` used to lowercase the whole query
outside its string literals, and column resolution was then a plain `in column_dtypes` against the
frame's real, case-carrying keys. A frame whose columns were `Cust` and `Quant` was therefore
unqueryable in *every* spelling — `Cust`, `cust` and `CUST` all failed with
`Invalid column: 'cust'`, naming a word the query never contained — and nothing in the repo or the
demo noticed, because `sales.csv` and both portfolio datasets are lowercase throughout.

The fix moves case folding out of the query string and into the places that know the structure: the
keyword and operator matches fold case themselves, and every column and group reference goes
through `_resolve_column` / `_resolve_group`, which answer with the *canonical* spelling — the
frame's for a column, the OVER clause's for a group. What the parser hands execution is therefore
always something `execute`'s `column_indices` can index by.

The tests below are written against a frame that is mixed-case throughout, since that is the case
that used to be unreachable, and they check both halves: that the query works whatever it writes,
and that what comes back is labelled canonically.
"""

import inspect
from datetime import date

import pandas as pd
import pytest

from esql.accessor import _enforce_allowed_dtypes
from esql.parser.error import ParsingError, ParsingErrorType
from esql.parser.util import _parse_aggregate, _parse_condition_value


@pytest.fixture
def mixed_case_data() -> pd.DataFrame:
    """A frame spelled the way a caller's own frame usually is, rather than all lowercase."""
    return _enforce_allowed_dtypes(
        pd.DataFrame(
            {
                "Cust": ["Dan", "Dan", "Dan", "Emily", "Emily"],
                "Prod": ["Ham", "Butter", "Ham", "Ham", "Cherry"],
                "Quant": [10, 20, 30, 40, 50],
                "Month": [1, 2, 3, 1, 2],
                "SaleDate": ["2020-01-15", "2020-02-15", "2020-03-15", "2020-01-20", "2020-02-20"],
                "OnCredit": [True, False, True, True, False],
            }
        )
    )


###########################################################################
# The K1 case itself
###########################################################################
@pytest.mark.parametrize(
    "query",
    [
        "SELECT Cust, Quant.sum",  # the frame's own spelling
        "SELECT cust, quant.sum",  # all lowercase
        "SELECT CUST, QUANT.SUM",  # all uppercase
        "SELECT cUsT, QuAnT.SuM",  # neither
    ],
)
def test_a_mixed_case_column_is_reachable_in_any_spelling(mixed_case_data, query):
    """The bug: all four of these raised `Invalid column: 'cust'`."""
    result = mixed_case_data.esql.query(query)
    assert result.to_dict("records") == [
        {"Cust": "Dan", "Quant.sum": 60},
        {"Cust": "Emily", "Quant.sum": 90},
    ]


def test_the_result_is_labelled_with_the_frames_spelling(mixed_case_data):
    """Not the query's, so the labels are the same whatever the query wrote.

    This is what forces the parser to resolve rather than pass the written name through: the label
    is also the key execution looks the value up by (`types.aggregate_key`), so a query-spelled
    label would find nothing in the grouped row's data map.
    """
    lowercased = mixed_case_data.esql.query("SELECT cust, month, quant.avg")
    shouted = mixed_case_data.esql.query("SELECT CUST, MONTH, QUANT.AVG")
    assert list(lowercased.columns) == ["Cust", "Month", "Quant.avg"]
    assert list(shouted.columns) == ["Cust", "Month", "Quant.avg"]


###########################################################################
# The rest of the language, on the same frame
###########################################################################
def test_keywords_are_case_insensitive(mixed_case_data):
    result = mixed_case_data.esql.query("select Cust, Quant.sum WHERE Prod = 'Ham' Having Quant.sum > 20 order BY 1")
    assert result.to_dict("records") == [{"Cust": "Dan", "Quant.sum": 40}, {"Cust": "Emily", "Quant.sum": 40}]


def test_a_group_is_referenced_case_insensitively_and_labelled_as_over_declared_it(mixed_case_data):
    """A group's canonical spelling is the OVER clause's, since that is where it is declared."""
    result = mixed_case_data.esql.query("SELECT Cust, G1.Quant.sum OVER G1 SUCH THAT g1.MONTH = 1")
    assert result.to_dict("records") == [{"Cust": "Dan", "G1.Quant.sum": 10}, {"Cust": "Emily", "G1.Quant.sum": 40}]


def test_two_group_names_differing_only_in_case_are_rejected(mixed_case_data):
    """They name the same group, so a reference to either could not resolve to one of them. This is
    what leaves `_resolve_group` with no ambiguous case to answer."""
    with pytest.raises(ParsingError) as excinfo:
        mixed_case_data.esql.validate("SELECT Cust, g1.Quant.sum OVER G1, g1 SUCH THAT g1.Month = 1")
    assert excinfo.value.error_type is ParsingErrorType.OVER_CLAUSE
    assert excinfo.value.token == "g1"


def test_an_entry_value_attribute_is_case_insensitive(mixed_case_data):
    """The EMF case: `_parse_entry_value` resolves the attribute it names, and `_validate_entry_value`
    then checks the resolved name against the SELECT grouping attributes, which are resolved too."""
    result = mixed_case_data.esql.query(
        "SELECT Cust, Month, PREV.Quant.sum OVER prev SUCH THAT prev.CUST = cust and prev.MONTH = month - 1"
    )
    dans = result[result["Cust"] == "Dan"].sort_values("Month")
    assert list(dans["Month"]) == [1, 2, 3]
    assert pd.isna(dans["prev.Quant.sum"].iloc[0])  # no month 0, so nothing to roll up
    assert list(dans["prev.Quant.sum"].iloc[1:]) == [10, 20]


def test_a_semi_join_key_is_case_insensitive(mixed_case_data):
    result = mixed_case_data.esql.query("SELECT Cust, Quant.sum WHERE CUST HAS prod = 'Butter'")
    assert result.to_dict("records") == [{"Cust": "Dan", "Quant.sum": 60}]


def test_an_aggregate_named_in_both_select_and_having_is_still_one_aggregate(mixed_case_data):
    """Written in different cases in the two clauses, it must still dedup to one.

    The merge in `_build_parsed_query` compares parsed aggregates, so both have to canonicalize the
    same way. If they did not, the aggregate would be accumulated twice per row and the sum would
    silently double, which is BUG-8 from v1.1 arriving by a different route.
    """
    result = mixed_case_data.esql.query("SELECT cust, QUANT.SUM HAVING quant.sum > 70")
    assert result.to_dict("records") == [{"Cust": "Emily", "Quant.sum": 90}]


def test_a_bare_boolean_column_is_case_insensitive_in_where_and_such_that(mixed_case_data):
    where = mixed_case_data.esql.query("SELECT Cust, Quant.sum WHERE ONCREDIT")
    such_that = mixed_case_data.esql.query("SELECT Cust, g1.Quant.sum OVER g1 SUCH THAT G1.oncredit")
    assert where.to_dict("records") == [{"Cust": "Dan", "Quant.sum": 40}, {"Cust": "Emily", "Quant.sum": 40}]
    assert such_that.to_dict("records") == [
        {"Cust": "Dan", "g1.Quant.sum": 40},
        {"Cust": "Emily", "g1.Quant.sum": 40},
    ]


def test_contains_and_a_date_comparison_resolve_their_columns_too(mixed_case_data):
    """The two condition values that are not plain numbers, so they take their own branches in
    `_parse_condition_value` and read the resolved column's dtype rather than the written name's."""
    contains = mixed_case_data.esql.query("SELECT Cust, Quant.sum WHERE PROD CONTAINS 'err'")
    dates = mixed_case_data.esql.query("SELECT Cust, SALEDATE WHERE saledate > '2020-03-01'")
    assert contains.to_dict("records") == [{"Cust": "Emily", "Quant.sum": 50}]
    assert dates.to_dict("records") == [{"Cust": "Dan", "SaleDate": date(2020, 3, 15)}]


###########################################################################
# What is *not* case-insensitive
###########################################################################
def test_a_literals_case_is_data_and_is_not_folded(mixed_case_data):
    """The other half of the same pass: outside a literal case is a spelling, inside it is a value.

    `=` is case-sensitive by design (v1.3.0), so folding a literal here would silently widen every
    equality comparison in the language.
    """
    assert mixed_case_data.esql.query("SELECT Cust WHERE Prod = 'Ham'").to_dict("records") == [
        {"Cust": "Dan"},
        {"Cust": "Emily"},
    ]
    assert mixed_case_data.esql.query("SELECT Cust WHERE Prod = 'HAM'").empty


def test_a_reference_matching_two_columns_when_folded_is_ambiguous():
    """A frame *can* hold `Cust` and `cust` at once, and then a folded reference has two answers.

    Resolution tries an exact match first, so both columns stay reachable by writing either exactly.
    Only a third spelling is ambiguous, and that raises rather than picking one.
    """
    data = _enforce_allowed_dtypes(pd.DataFrame({"Cust": ["Dan"], "cust": ["dan"], "Quant": [1]}))

    assert data.esql.query("SELECT Cust").to_dict("records") == [{"Cust": "Dan"}]
    assert data.esql.query("SELECT cust").to_dict("records") == [{"cust": "dan"}]

    with pytest.raises(ParsingError) as excinfo:
        data.esql.validate("SELECT CUST")
    assert excinfo.value.error_type is ParsingErrorType.SELECT_CLAUSE
    assert excinfo.value.token == "CUST"
    assert "ambiguous" in excinfo.value.message


###########################################################################
# K2
###########################################################################
@pytest.mark.parametrize("function", [_parse_aggregate, _parse_condition_value])
def test_error_type_is_a_required_argument(function):
    """K2. Both of these used to default it to `A or B`, which is `A` for any truthy `A`, so the
    second clause name had never meant anything. Every call site passes one explicitly, which is why
    it was harmless and why it had to go: it read as if it selected a clause per caller, sitting in
    the code that reports which clause rejected a value. Required, so a future caller cannot
    silently inherit `SELECT CLAUSE` for a WHERE failure.
    """
    assert inspect.signature(function).parameters["error_type"].default is inspect.Parameter.empty
