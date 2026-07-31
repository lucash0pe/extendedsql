from datetime import date

import numpy as np
import pandas as pd
import pytest

from esql.parser.error import ParsingError, ParsingErrorType
from esql.parser.types import (
    AggregatesDict,
    CompoundAggregateCondition,
    CompoundCondition,
    CompoundGroupCondition,
    GlobalAggregate,
    GlobalAggregateCondition,
    GroupAggregate,
    GroupAggregateCondition,
    LogicalOperator,
    NotAggregateCondition,
    NotCondition,
    NotGroupCondition,
    ParsedHavingClause,
    ParsedSelectClause,
    ParsedSuchThatClause,
    ParsedSuchThatSection,
    ParsedWhereClause,
    SimpleCondition,
    SimpleGroupCondition,
    SortTerm,
)
from esql.parser.util import (
    _has_wrapping_parenthesis,
    _parse_such_that_section,
    _split_by_logical_operator,
    _split_condition,
    get_keyword_clauses,
    parse_having_clause,
    parse_order_by_clause,
    parse_over_clause,
    parse_select_clause,
    parse_such_that_clause,
    parse_where_clause,
)


@pytest.fixture
def column_dtypes(sales_test_data: pd.DataFrame) -> dict[str, np.dtype]:
    column_dtypes = sales_test_data.dtypes.to_dict()
    return column_dtypes


###########################################################################
# GET_KEYWORD_CLAUSES TESTS
###########################################################################
def test_get_keyword_clauses_splits_by_keywords_properly():
    keyword_clauses = get_keyword_clauses(
        query="SELECT cust, prod, date OVER bad, good, better, best WHERE quant > 10 and credit SUCH THAT bad.month = 7 and good.month = 8 and better.month = 9 and best.month = 10 having good.quant.sum > 100 and bad.quant.sum < 100 order by 2".lower()
    )
    expected = {
        "SELECT": "cust, prod, date",
        "OVER": "bad, good, better, best",
        "WHERE": "quant > 10 and credit",
        "SUCH THAT": "bad.month = 7 and good.month = 8 and better.month = 9 and best.month = 10",
        "HAVING": "good.quant.sum > 100 and bad.quant.sum < 100",
        "ORDER BY": "2",
    }
    assert keyword_clauses == expected


def test_get_keyword_clauses_splits_properly_with_missing_keywords():
    keyword_clauses = get_keyword_clauses(
        query="SELECT cust, prod, date OVER bad, good, better, best SUCH THAT bad.month = 7 and good.month = 8 and better.month = 9 and best.month = 10 HAVING good.quant.sum > 100 and bad.quant.sum < 100".lower()
    )
    expected = {
        "SELECT": "cust, prod, date",
        "OVER": "bad, good, better, best",
        "WHERE": None,
        "SUCH THAT": "bad.month = 7 and good.month = 8 and better.month = 9 and best.month = 10",
        "HAVING": "good.quant.sum > 100 and bad.quant.sum < 100",
        "ORDER BY": None,
    }
    assert keyword_clauses == expected


def test_get_keyword_clauses_raises_missing_select_error():
    with pytest.raises(ParsingError) as parsingError:
        get_keyword_clauses(
            query="OVER bad, good, better, best WHERE quant > 10 and credit SUCH THAT bad.month = 7 and good.month = 8 and better.month = 9 and best.month = 10 having good.quant.sum > 100 and bad.quant.sum < 100 and better order by 2".lower()
        )
    assert parsingError.value.error_type == ParsingErrorType.SELECT_CLAUSE


def test_get_keyword_clauses_raises_missing_clause_error():
    with pytest.raises(ParsingError) as parsingError:
        get_keyword_clauses(
            query="SELECT cust OVER bad, good WHERE quant > 10 SUCH THAT  HAVING good.quant.sum > 100 and bad.quant.sum < 100 and better order by 2".lower()
        )
    assert (
        parsingError.value.error_type == ParsingErrorType.MISSING_CLAUSE and "SUCH THAT" in parsingError.value.message
    )


def test_get_keyword_clauses_raises_clause_order_error():
    with pytest.raises(ParsingError) as parsingError:
        get_keyword_clauses(
            query="SELECT cust WHERE quant > 10 OVER bad, good  SUCH THAT  HAVING good.quant.sum > 100 and bad.quant.sum < 100 and better order by 2".lower()
        )
    assert parsingError.value.error_type == ParsingErrorType.CLAUSE_ORDER and "WHERE" in parsingError.value.message


def test_get_keyword_clauses_returns_none_for_missing_keywords():
    keyword_clauses = get_keyword_clauses(query="SELECT cust, prod, date".lower())
    expected = {
        "SELECT": "cust, prod, date",
        "OVER": None,
        "WHERE": None,
        "SUCH THAT": None,
        "HAVING": None,
        "ORDER BY": None,
    }
    assert keyword_clauses == expected


def test_get_keyword_clauses_raises_error_for_missing_arguments_after_select():
    with pytest.raises(ParsingError) as parsingError:
        get_keyword_clauses(
            query="SELECT OVER bad, good  SUCH THAT  HAVING good.quant.sum > 100 and bad.quant.sum < 100 and better order by 2".lower()
        )
    assert (
        parsingError.value.error_type == ParsingErrorType.MISSING_CLAUSE and "No SELECT" in parsingError.value.message
    )


###########################################################################
# PARSE_OVER_CLAUSE TESTS
###########################################################################
def test_parse_over_clause_returns_expected_structure(column_dtypes: dict[str, np.dtype]):
    parsedOverClause = parse_over_clause(
        over_clause="Apples  ,   132537aaGGG, ___yuetsg___8   ,   728x2fegoql,   GGGGGGHHHHH_____   ",
        column_dtypes=column_dtypes,
    )
    expected = ["Apples", "132537aaGGG", "___yuetsg___8", "728x2fegoql", "GGGGGGHHHHH_____"]
    assert parsedOverClause == expected


def test_parse_over_clause_raises_error_for_invalid_characters(column_dtypes: dict[str, np.dtype]):
    invalid_groups = ["aa)hhhd", "$teven", "#678", "[george]", "wow!"]
    for group in invalid_groups:
        with pytest.raises(ParsingError) as parsingError:
            parse_over_clause(over_clause=f"{group}", column_dtypes=column_dtypes)
        assert parsingError.value.error_type == ParsingErrorType.OVER_CLAUSE


def test_parse_over_clause_rejects_a_group_named_after_a_column(column_dtypes: dict[str, np.dtype]):
    """A name cannot be both, or the first thing to the left of a dot reads two ways. Rejected at
    the declaration, where the query says which names it wants, rather than resolved per reference."""
    for group in ["quant", "QUANT"]:
        with pytest.raises(ParsingError, match="names the column"):
            parse_over_clause(over_clause=group, column_dtypes=column_dtypes)


###########################################################################
# PARSE_SELECT_CLAUSE TESTS
###########################################################################
def test_parse_select_clause_returns_expected_structure(column_dtypes: dict[str, np.dtype]):
    parsedSelectClause = parse_select_clause(
        select_clause="cust, prod, date, 1.quant.max, 2.quant.min, quant.sum, 3.quant.avg, 3.month.count",
        groups=["1", "2", "3"],
        column_dtypes=column_dtypes,
    )
    expected = ParsedSelectClause(
        grouping_attributes=["cust", "prod", "date"],
        aggregates=AggregatesDict(
            global_scope=[
                GlobalAggregate(column="quant", function="sum"),
            ],
            group_specific=[
                GroupAggregate(column="quant", function="max", group="1"),
                GroupAggregate(column="quant", function="min", group="2"),
                GroupAggregate(column="quant", function="avg", group="3"),
                GroupAggregate(column="month", function="count", group="3"),
            ],
        ),
        select_items_in_order=[
            "cust",
            "prod",
            "date",
            "1.quant.max",
            "2.quant.min",
            "quant.sum",
            "3.quant.avg",
            "3.month.count",
        ],
    )
    assert parsedSelectClause == expected


def test_parse_select_clause_raises_error_for_invalid_aggregate_group(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_select_clause(
            select_clause="cust, prod, date, quant.sum, 1.quant.max, 2.quant.min, 3.quant.avg",
            groups=["1", "2"],
            column_dtypes=column_dtypes,
        )
    assert (
        parsingError.value.error_type == ParsingErrorType.SELECT_CLAUSE
        and "Invalid aggregate group: '3.quant.avg'" in parsingError.value.message
    )


def test_parse_select_clause_raises_error_for_invalid_aggregate_column(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_select_clause(
            select_clause="cust, prod, date, quant.sum, 1.quant.max, 2.q.min, 3.quant.avg",
            groups=["1", "2", "3"],
            column_dtypes=column_dtypes,
        )
    assert (
        parsingError.value.error_type == ParsingErrorType.SELECT_CLAUSE
        and "Invalid aggregate column: '2.q.min'" in parsingError.value.message
    )


def test_parse_select_clause_raises_error_for_aggregate_with_non_numeric_column(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_select_clause(
            select_clause="cust, prod, date, quant.sum, 1.quant.max, 2.credit.min, 3.quant.avg",
            groups=["1", "2", "3"],
            column_dtypes=column_dtypes,
        )
    assert (
        parsingError.value.error_type == ParsingErrorType.SELECT_CLAUSE
        and "Invalid aggregate. Column is not a numeric type: '2.credit.min'" in parsingError.value.message
    )


def test_parse_select_clause_raises_error_for_invalid_aggregate_function(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_select_clause(
            select_clause="cust, prod, date, quant.mean, 1.quant.max, 3.quant.avg",
            groups=["1", "2", "3"],
            column_dtypes=column_dtypes,
        )
    assert (
        parsingError.value.error_type == ParsingErrorType.SELECT_CLAUSE
        and "Invalid aggregate function: 'quant.mean'" in parsingError.value.message
    )


def test_parse_select_clause_raises_error_for_invalid_column(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_select_clause(
            select_clause="cust_, prod, date, 1.quant.max, 3.quant.avg",
            groups=["1", "2", "3"],
            column_dtypes=column_dtypes,
        )
    assert (
        parsingError.value.error_type == ParsingErrorType.SELECT_CLAUSE
        and "Invalid column: 'cust_'" in parsingError.value.message
    )


def test_parse_select_clause_raises_error_when_there_are_no_column_grouping_attributes(
    column_dtypes: dict[str, np.dtype],
):
    with pytest.raises(ParsingError) as parsingError:
        parse_select_clause(
            select_clause="1.quant.max, 3.quant.avg, date.count", groups=["1", "2", "3"], column_dtypes=column_dtypes
        )
    assert parsingError.value.error_type == ParsingErrorType.SELECT_CLAUSE


###########################################################################
# PARSE_WHERE_CLAUSE TESTS
###########################################################################
def test_parse_where_clause_returns_expected_structure_with_logical_operators(column_dtypes: dict[str, np.dtype]):
    parsedWhereClause = parse_where_clause(
        where_clause="not (cust = 'Dan') and (month = 7 or month = 8 and year = 2020) and credit=True",
        column_dtypes=column_dtypes,
    )
    expected: ParsedWhereClause = CompoundCondition(
        operator=LogicalOperator.AND,
        conditions=[
            NotCondition(
                operator=LogicalOperator.NOT,
                condition=SimpleCondition(column="cust", operator="=", value="Dan", is_emf=False),
            ),
            CompoundCondition(
                operator=LogicalOperator.OR,
                conditions=[
                    SimpleCondition(column="month", operator="=", value=7, is_emf=False),
                    CompoundCondition(
                        operator=LogicalOperator.AND,
                        conditions=[
                            SimpleCondition(column="month", operator="=", value=8, is_emf=False),
                            SimpleCondition(column="year", operator="=", value=2020, is_emf=False),
                        ],
                    ),
                ],
            ),
            SimpleCondition(column="credit", operator="=", value=True, is_emf=False),
        ],
    )
    assert parsedWhereClause == expected


def test_parse_where_clause_can_handle_boolean_column_condition(column_dtypes: dict[str, np.dtype]):
    parsedWhereClause = parse_where_clause(where_clause="credit", column_dtypes=column_dtypes)
    expected: ParsedWhereClause = SimpleCondition(column="credit", operator="=", value=True, is_emf=False)
    assert parsedWhereClause == expected


def test_parse_where_clause_can_handle_valid_simple_conditions(column_dtypes: dict[str, np.dtype]):
    conditions = [
        ("cust", "==", "'Dan'"),
        ("quant", ">", 10),
        ("month", "<", 12),
        ("credit", "!=", True),
        ("credit", "=", False),
        ("credit", "==", True),
        ("quant", "<=", 21.6),
    ]
    for column, operator, value in conditions:
        parsedWhereClause = parse_where_clause(
            where_clause=f"{column} {operator} {value!s}", column_dtypes=column_dtypes
        )
        if isinstance(value, str):
            value = value[1:-1]
        expected: ParsedWhereClause = SimpleCondition(column=column, operator=operator, value=value, is_emf=False)
        assert parsedWhereClause == expected


def test_parse_where_clause_can_handle_valid_dates(column_dtypes: dict[str, np.dtype]):
    date_clauses = [
        (">=", "'2020-07-01'", date(2020, 7, 1)),
        ("<=", '"2021/12/07"', date(2021, 12, 7)),
        (">", "'2020/7-1'", date(2020, 7, 1)),
        ("<", "'2012-01/30'", date(2012, 1, 30)),
        ("!=", '"2020-7-1"', date(2020, 7, 1)),
        ("=", "'2020-07-01'", date(2020, 7, 1)),
        ("==", '"2020-7-1"', date(2020, 7, 1)),
    ]
    for operator, value, expected_date in date_clauses:
        parsedWhereClause = parse_where_clause(where_clause=f"date {operator} {value}", column_dtypes=column_dtypes)
        expected: ParsedWhereClause = SimpleCondition(
            column="date", operator=operator, value=expected_date, is_emf=False
        )
        assert parsedWhereClause == expected


def test_parse_where_clause_rejects_a_date_whose_quotes_do_not_match(column_dtypes: dict[str, np.dtype]):
    """A literal opened with one delimiter and closed with the other is not a literal.

    These two used to parse: the date pattern spelled its quotes as `['\"]` at each end
    independently, so it accepted a mismatched pair that no other value would have been allowed.
    """
    for value in ["'2020/7-1\"", "\"2020-7-1'"]:
        with pytest.raises(ParsingError) as parsingError:
            parse_where_clause(where_clause=f"date > {value}", column_dtypes=column_dtypes)
        assert "Unterminated" in parsingError.value.message


def test_parse_where_clause_raises_error_when_date_is_not_wrapped_in_quotes(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_where_clause(where_clause="date != 2019-10-8", column_dtypes=column_dtypes)
    assert parsingError.value.error_type == ParsingErrorType.WHERE_CLAUSE


def test_parse_where_clause_raises_error_for_invalid_dates(column_dtypes: dict[str, np.dtype]):
    dates = ["2023-13-01", "2023-02-29", "2023-00-01", "2023-01-00", "2023-4-31"]
    for date_str in dates:
        with pytest.raises(ParsingError) as parsingError:
            parse_where_clause(where_clause=f"date = '{date_str}'", column_dtypes=column_dtypes)
        assert parsingError.value.error_type == ParsingErrorType.WHERE_CLAUSE


def test_parse_where_clause_raises_error_for_missing_conditional_operators(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_where_clause(where_clause="cust 'Dan'", column_dtypes=column_dtypes)
    assert (
        parsingError.value.error_type == ParsingErrorType.WHERE_CLAUSE
        and "No conditional operator" in parsingError.value.message
    )


def test_parse_where_clause_raises_error_for_invalid_values(column_dtypes: dict[str, np.dtype]):
    """Two refusals live here, and they are answered at different points. `cust > 'Dan'` and
    `credit > true` are refused for the *operator*, before the value is read at all, because ordering
    a text or boolean column means nothing (`OPERATOR_DTYPES`). The rest are refused for the
    *value*: the operator applies, and `123` is not something a text column holds.

    The message names which of the two it was, since they call for different fixes: change the
    operator, or write the value the way that column's family is written."""
    refusals = {
        "cust = 123": "A text value must be quoted",
        "cust = 12.3": "A text value must be quoted",
        "cust = True": "A text value must be quoted",
        "cust = False": "A text value must be quoted",
        "cust > 'Dan'": "does not apply to a string column",
        "quant == '12'": "Invalid value",
        "month != true": "Invalid value",
        "credit > true": "does not apply to a boolean column",
        "credit = 1": "compares against true or false",
        "date = 'hello'": "Invalid date",
    }
    for invalid_value, expected in refusals.items():
        with pytest.raises(ParsingError) as parsingError:
            parse_where_clause(where_clause=invalid_value, column_dtypes=column_dtypes)
        assert parsingError.value.error_type == ParsingErrorType.WHERE_CLAUSE
        assert expected in parsingError.value.message, invalid_value


def test_parse_where_clause_raises_error_for_double_logical_operators(column_dtypes: dict[str, np.dtype]):
    invalid_clauses = ["cust = 'Dan' or or month = 7", "cust = 'Dan' and and month = 7"]
    for invalid_clause in invalid_clauses:
        with pytest.raises(ParsingError) as parsingError:
            parse_where_clause(where_clause=invalid_clause, column_dtypes=column_dtypes)
        assert parsingError.value.error_type == ParsingErrorType.WHERE_CLAUSE


###########################################################################
# PARSE_SUCH_THAT_CLAUSE TESTS
###########################################################################
def test_parse_such_that_section_returns_expected_structure_with_logical_operators(column_dtypes: dict[str, np.dtype]):
    parsedSuchThatSection = _parse_such_that_section(
        section="1.cust = 'Sam' or not (1.year = 2020 and not 1.credit)",
        groups=["1", "2", "3"],
        column_dtypes=column_dtypes,
        grouping_attributes=["cust"],
    )
    expected: ParsedSuchThatSection = CompoundGroupCondition(
        operator=LogicalOperator.OR,
        conditions=[
            SimpleCondition(group="1", column="cust", operator="=", value="Sam", is_emf=False),
            NotGroupCondition(
                operator=LogicalOperator.NOT,
                condition=CompoundGroupCondition(
                    operator=LogicalOperator.AND,
                    conditions=[
                        SimpleGroupCondition(group="1", column="year", operator="=", value=2020, is_emf=False),
                        NotGroupCondition(
                            operator=LogicalOperator.NOT,
                            condition=SimpleCondition(
                                group="1", column="credit", operator="=", value=True, is_emf=False
                            ),
                        ),
                    ],
                ),
            ),
        ],
    )
    assert parsedSuchThatSection == expected


def test_parse_such_that_section_raises_error_for_multiple_groups_in_a_clause(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        _parse_such_that_section(
            section="1.year = 2020 and 2.credit",
            groups=["1", "2"],
            column_dtypes=column_dtypes,
            grouping_attributes=["cust"],
        )
    assert (
        parsingError.value.error_type == ParsingErrorType.SUCH_THAT_CLAUSE
        and "Multiple groups" in parsingError.value.message
    )


def test_parse_such_that_section_raises_error_for_invalid_group(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        _parse_such_that_section(
            section="2.year = 2020 and 2.credit",
            groups=["1"],
            column_dtypes=column_dtypes,
            grouping_attributes=["cust"],
        )
    assert (
        parsingError.value.error_type == ParsingErrorType.SUCH_THAT_CLAUSE
        and "No valid group" in parsingError.value.message
    )


def test_parse_such_that_clause_returns_expected_list(column_dtypes: dict[str, np.dtype]):
    parsedSuchThatClause = parse_such_that_clause(
        such_that_clause="1.cust = 'Sam', 2.quant > 6 or 2.quant <= 500, 3.credit == true",
        groups=["1", "2", "3"],
        column_dtypes=column_dtypes,
        grouping_attributes=["cust"],
    )
    expected: ParsedSuchThatClause = [
        SimpleCondition(group="1", column="cust", operator="=", value="Sam", is_emf=False),
        CompoundGroupCondition(
            operator=LogicalOperator.OR,
            conditions=[
                SimpleCondition(group="2", column="quant", operator=">", value=6, is_emf=False),
                SimpleCondition(group="2", column="quant", operator="<=", value=500, is_emf=False),
            ],
        ),
        SimpleCondition(group="3", column="credit", operator="==", value=True, is_emf=False),
    ]
    assert parsedSuchThatClause == expected


def test_parse_such_that_clause_raises_error_for_multiple_sections_with_the_same_group(
    column_dtypes: dict[str, np.dtype],
):
    clauses = [
        "1.cust = 'Sam', 2.quant > 6 or 2.quant <= 500, 3.credit == true, 2.cust = 'Sam'",
        "1.year = 2020, 1.credit",
        "3.cust = 'Sam', (2.year = 2020 and not 2.credit), 3.year = 2021",
    ]
    for clause in clauses:
        with pytest.raises(ParsingError) as parsingError:
            parse_such_that_clause(
                such_that_clause=clause,
                groups=["1", "2", "3"],
                column_dtypes=column_dtypes,
                grouping_attributes=["cust"],
            )
        assert (
            parsingError.value.error_type == ParsingErrorType.SUCH_THAT_CLAUSE
            and "Multiple sections contain group" in parsingError.value.message
        )


###########################################################################
# PARSE_HAVING_CLAUSE TESTS
###########################################################################
def test_parse_having_clause_returns_expected_structure_with_logical_operators(column_dtypes: dict[str, np.dtype]):
    parsedHavingClause, _ = parse_having_clause(
        having_clause="1.quant.avg > 500 and 1.month.count < 50 or not quant.max >= 765 or (3.quant.min == 30 or quant.sum != 300)",
        groups=["1", "3"],
        column_dtypes=column_dtypes,
    )
    expected: ParsedHavingClause = CompoundAggregateCondition(
        operator=LogicalOperator.OR,
        conditions=[
            CompoundCondition(
                operator=LogicalOperator.AND,
                conditions=[
                    GroupAggregateCondition(
                        aggregate=GroupAggregate(group="1", column="quant", function="avg"),
                        operator=">",
                        value=float(500),
                    ),
                    GroupAggregateCondition(
                        aggregate=GroupAggregate(group="1", column="month", function="count"),
                        operator="<",
                        value=float(50),
                    ),
                ],
            ),
            NotAggregateCondition(
                operator=LogicalOperator.NOT,
                condition=GlobalAggregateCondition(
                    aggregate=GlobalAggregate(column="quant", function="max"), operator=">=", value=float(765)
                ),
            ),
            CompoundAggregateCondition(
                operator=LogicalOperator.OR,
                conditions=[
                    GroupAggregateCondition(
                        aggregate=GroupAggregate(group="3", column="quant", function="min"),
                        operator="==",
                        value=float(30),
                    ),
                    GlobalAggregateCondition(
                        aggregate=GlobalAggregate(column="quant", function="sum"), operator="!=", value=float(300)
                    ),
                ],
            ),
        ],
    )
    assert parsedHavingClause == expected


def test_parse_having_clause_returns_expected_aggregates_dict(column_dtypes: dict[str, np.dtype]):
    _, aggregates = parse_having_clause(
        having_clause="1.quant.avg > 500 and 1.quant.avg < 50 or not quant.max >= 765 or (3.quant.min == 30 or quant.sum != 300)",
        groups=["1", "3"],
        column_dtypes=column_dtypes,
    )
    expected = AggregatesDict(
        group_specific=[
            GlobalAggregate(group="1", column="quant", function="avg"),
            GlobalAggregate(group="3", column="quant", function="min"),
        ],
        global_scope=[GlobalAggregate(column="quant", function="max"), GlobalAggregate(column="quant", function="sum")],
    )
    assert aggregates == expected


def test_parse_having_clause_raises_error_for_invalid_group_in_aggregate(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_having_clause(having_clause="1.quant.avg > 500", groups=["2", "3"], column_dtypes=column_dtypes)
    assert (
        parsingError.value.error_type == ParsingErrorType.HAVING_CLAUSE
        and "Invalid aggregate group" in parsingError.value.message
    )


def test_parse_having_clause_raises_error_for_invalid_column_in_aggregate(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_having_clause(having_clause="2.cal.avg > 500", groups=["2", "3"], column_dtypes=column_dtypes)
    assert (
        parsingError.value.error_type == ParsingErrorType.HAVING_CLAUSE
        and "Invalid aggregate column" in parsingError.value.message
    )


def test_parse_having_clause_raises_error_for_non_numeric_column_in_aggregate(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_having_clause(having_clause="2.date.avg > 500", groups=["2", "3"], column_dtypes=column_dtypes)
    assert (
        parsingError.value.error_type == ParsingErrorType.HAVING_CLAUSE
        and "Column is not a numeric type" in parsingError.value.message
    )


def test_parse_having_clause_raises_error_for_invalid_function_in_aggregate(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_having_clause(having_clause="2.quant.mean > 500", groups=["2", "3"], column_dtypes=column_dtypes)
    assert (
        parsingError.value.error_type == ParsingErrorType.HAVING_CLAUSE
        and "Invalid aggregate function" in parsingError.value.message
    )


def test_parse_having_clause_raises_error_for_no_operator_in_condition(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_having_clause(having_clause="2.quant.avg 500", groups=["2", "3"], column_dtypes=column_dtypes)
    assert (
        parsingError.value.error_type == ParsingErrorType.HAVING_CLAUSE
        and "No conditional operator" in parsingError.value.message
    )


def test_parse_having_clause_raises_error_for_invalid_operator_in_condition(column_dtypes: dict[str, np.dtype]):
    with pytest.raises(ParsingError) as parsingError:
        parse_having_clause(having_clause="2.quant.avg ==== 500", groups=["2", "3"], column_dtypes=column_dtypes)
    assert (
        parsingError.value.error_type == ParsingErrorType.HAVING_CLAUSE
        and "Invalid value" in parsingError.value.message
    )


def test_parse_having_clause_raises_error_for_non_numeric_comparison_value(column_dtypes: dict[str, np.dtype]):
    values = ["'apple'", "'500'", "true", "'2020-2-2'", "55f55"]
    for value in values:
        with pytest.raises(ParsingError) as parsingError:
            parse_having_clause(having_clause=f"2.quant.avg != {value}", groups=["2", "3"], column_dtypes=column_dtypes)
        assert (
            parsingError.value.error_type == ParsingErrorType.HAVING_CLAUSE
            and "Invalid value" in parsingError.value.message
        )


###########################################################################
# PARSE_ORDER_BY_CLAUSE TESTS
###########################################################################
ORDER_BY_ATTRIBUTES = ["cust", "prod", "state"]
ORDER_BY_TERMS = ["cust", "prod", "state", "quant.sum", "g1.quant.avg"]


def _order_by(clause: str | None):
    return parse_order_by_clause(
        order_by_clause=clause, grouping_attributes=ORDER_BY_ATTRIBUTES, select_items_in_order=ORDER_BY_TERMS
    )


def test_order_by_clause_reads_the_integer_as_the_first_n_grouping_attributes():
    """Not the Nth: `ORDER BY 3` sorts by the first attribute, then the second, then the third."""
    assert _order_by("3") == [
        SortTerm(term="cust", descending=False),
        SortTerm(term="prod", descending=False),
        SortTerm(term="state", descending=False),
    ]


def test_order_by_clause_reads_a_negative_integer_as_all_of_them_descending():
    assert _order_by("-3") == [
        SortTerm(term="cust", descending=True),
        SortTerm(term="prod", descending=True),
        SortTerm(term="state", descending=True),
    ]


def test_order_by_clause_reads_a_named_term():
    assert _order_by("prod") == [SortTerm(term="prod", descending=False)]


def test_order_by_clause_reads_an_aggregate_term():
    assert _order_by("quant.sum") == [SortTerm(term="quant.sum", descending=False)]
    assert _order_by("g1.quant.avg") == [SortTerm(term="g1.quant.avg", descending=False)]


def test_order_by_clause_reads_a_leading_minus_as_descending():
    assert _order_by("-quant.sum") == [SortTerm(term="quant.sum", descending=True)]
    assert _order_by("- quant.sum") == [SortTerm(term="quant.sum", descending=True)]


def test_order_by_clause_reads_a_list_with_a_direction_per_term():
    assert _order_by("-quant.sum, cust") == [
        SortTerm(term="quant.sum", descending=True),
        SortTerm(term="cust", descending=False),
    ]


def test_order_by_clause_resolves_a_term_case_insensitively():
    assert _order_by("QUANT.SUM") == [SortTerm(term="quant.sum", descending=False)]
    assert _order_by("Cust") == [SortTerm(term="cust", descending=False)]


def test_order_by_clause_reads_nothing_as_no_sort():
    assert _order_by(None) == []
    assert _order_by("0") == []


def test_order_by_clause_raises_error_for_a_term_that_is_not_selected():
    """`quant` is a column of the frame but not a SELECT term, so a projected row holds no value
    for it. The error names what is available, since the answer is in the query already."""
    with pytest.raises(ParsingError) as parsingError:
        _order_by("quant")
    assert parsingError.value.error_type == ParsingErrorType.ORDER_BY_CLAUSE
    assert "is not a SELECT term" in parsingError.value.message
    assert "quant.sum" in parsingError.value.message


def test_order_by_clause_raises_error_for_a_non_integer_number():
    """`2.3` is not an index and is not a term either, so it is refused as a term."""
    with pytest.raises(ParsingError) as parsingError:
        _order_by("2.3")
    assert parsingError.value.error_type == ParsingErrorType.ORDER_BY_CLAUSE
    assert "is not a SELECT term" in parsingError.value.message


def test_order_by_clause_raises_error_for_an_empty_term_in_a_list():
    with pytest.raises(ParsingError) as parsingError:
        _order_by("cust, , prod")
    assert parsingError.value.error_type == ParsingErrorType.ORDER_BY_CLAUSE
    assert "Empty sort term" in parsingError.value.message


def test_order_by_clause_raises_error_for_out_of_range_inputs():
    out_of_range_values = ["-44", "1001", "-543578", "7"]
    for value in out_of_range_values:
        with pytest.raises(ParsingError) as parsingError:
            _order_by(value)
        assert (
            parsingError.value.error_type == ParsingErrorType.ORDER_BY_CLAUSE
            and f"{value} out of range" in parsingError.value.message
        )


###########################################################################
# CLAUSE STRUCTURE HELPER FUNCTIONS TESTS
###########################################################################
def test_split_by_operator_does_not_split_on_logical_operators_within_quotes():
    result = _split_by_logical_operator(condition="prod = 'dan and jess'", operator=LogicalOperator.AND)
    expected = ["prod = 'dan and jess'"]
    assert result == expected


def test_split_by_conditional_operator_does_not_split_on_conditional_operators_within_quotes():
    result = _split_condition(condition="'dan = jess>='")
    assert result is None


def test_split_by_conditional_operator_does_not_split_on_conditional_operators_within_quotes_found_outside_of_quotes():
    result = _split_condition(condition="prod = 'dan = jess'")
    expected = ("prod", "=", "'dan = jess'")
    assert result == expected


def test_has_wrapping_parenthesis_resturns_correct_result():
    tests = {
        "prod = 'dan'": False,
        " (prod = 'dan') ": True,
        "(prod = 'dan' and month = 7)": True,
        "(prod = 'dan') and (month = 7)": False,
        "(prod = 'Dan)' and month = 7)": True,
        "(prod = 'Dan') and month = 7)": False,
    }
    for string, expected in tests.items():
        result = _has_wrapping_parenthesis(string)
        assert result == expected


if __name__ == "__main__":
    pytest.main()
