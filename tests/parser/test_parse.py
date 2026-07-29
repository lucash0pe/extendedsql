import pandas as pd
import pytest

from esql.parser.parse import _prepare_query, get_parsed_query
from esql.parser.types import (
    AggregatesDict,
    CompoundCondition,
    CompoundGroupCondition,
    GlobalAggregate,
    GroupAggregate,
    GroupAggregateCondition,
    LogicalOperator,
    NotCondition,
    NotGroupCondition,
    ParsedQuery,
    ParsedSelectClause,
    SimpleCondition,
    SimpleGroupCondition,
)


def test_prepare_query_returns_expected_structure():
    query = 'SELECT cust,         prod,         g1.quant.sum OVER g1,g2,g3      WHERE cust = "DAN" and month = 1 or prod =   "APLEHSVCDGhsfjadmg_hgdoe3v¡=3h8d" Such thAt g3.prod = \'bceL;lwhan\',g2.state="NY" HAvING g1.quant.avg > 0.5 orDer by     3'
    expected = 'select cust, prod, g1.quant.sum over g1,g2,g3 where cust = "DAN" and month = 1 or prod = "APLEHSVCDGhsfjadmg_hgdoe3v¡=3h8d" such that g3.prod = \'bceL;lwhan\',g2.state="NY" having g1.quant.avg > 0.5 order by 3'
    result = _prepare_query(query)
    assert result == expected


def test_get_parsed_query_returns_the_expected_structure(sales_test_data: pd.DataFrame):
    parsedQuery = get_parsed_query(
        data=sales_test_data,
        query='SELECT cust,         quant.avg,   prod,    g1.quant.sum,g2.state.count, quant.min,  g3.quant.max OVER g1,g2,g3      WHERE not cust != "DAN" and month > 5 or prod =   "APLEHSVCDGhsfjadmg_hgdoe3v¡=3h8d" Such thAt g1.year = 2020 and not g1.month    = 10,g2.state!="NY",g3.day=1 or g3.day=31 HAvING g1.quant.avg > 0.5 orDer by     1',
    )
    expected = ParsedQuery(
        data=sales_test_data,
        select=ParsedSelectClause(
            grouping_attributes=["cust", "prod"],
            aggregates=AggregatesDict(
                global_scope=[
                    GlobalAggregate(column="quant", function="avg"),
                    GlobalAggregate(column="quant", function="min"),
                ],
                group_specific=[
                    GroupAggregate(column="quant", function="sum", group="g1"),
                    GroupAggregate(column="state", function="count", group="g2"),
                    GroupAggregate(column="quant", function="max", group="g3"),
                ],
            ),
            select_items_in_order=[
                "cust",
                "quant.avg",
                "prod",
                "g1.quant.sum",
                "g2.state.count",
                "quant.min",
                "g3.quant.max",
            ],
        ),
        over=["g1", "g2", "g3"],
        where=CompoundCondition(
            operator=LogicalOperator.OR,
            conditions=[
                CompoundCondition(
                    operator=LogicalOperator.AND,
                    conditions=[
                        NotCondition(
                            operator=LogicalOperator.NOT,
                            condition=SimpleCondition(column="cust", operator="!=", value="DAN", is_emf=False),
                        ),
                        SimpleCondition(column="month", operator=">", value=5, is_emf=False),
                    ],
                ),
                SimpleCondition(column="prod", operator="=", value="APLEHSVCDGhsfjadmg_hgdoe3v¡=3h8d", is_emf=False),
            ],
        ),
        such_that=[
            CompoundGroupCondition(
                operator=LogicalOperator.AND,
                conditions=[
                    SimpleGroupCondition(group="g1", column="year", operator="=", value=2020, is_emf=False),
                    NotGroupCondition(
                        operator=LogicalOperator.NOT,
                        condition=SimpleGroupCondition(
                            group="g1", column="month", operator="=", value=10, is_emf=False
                        ),
                    ),
                ],
            ),
            SimpleGroupCondition(group="g2", column="state", operator="!=", value="NY", is_emf=False),
            CompoundGroupCondition(
                operator=LogicalOperator.OR,
                conditions=[
                    SimpleGroupCondition(group="g3", column="day", operator="=", value=1, is_emf=False),
                    SimpleGroupCondition(group="g3", column="day", operator="=", value=31, is_emf=False),
                ],
            ),
        ],
        having=GroupAggregateCondition(
            aggregate=GroupAggregate(group="g1", column="quant", function="avg"), operator=">", value=0.5
        ),
        order_by=1,
        aggregates=AggregatesDict(
            global_scope=[
                GlobalAggregate(column="quant", function="avg"),
                GlobalAggregate(column="quant", function="min"),
            ],
            group_specific=[
                GroupAggregate(group="g1", column="quant", function="avg"),
                GroupAggregate(column="quant", function="sum", group="g1"),
                GroupAggregate(column="state", function="count", group="g2"),
                GroupAggregate(column="quant", function="max", group="g3"),
            ],
        ),
    )
    assert (
        parsedQuery["select"] == expected["select"]
        and parsedQuery["over"] == expected["over"]
        and parsedQuery["where"] == expected["where"]
        and parsedQuery["such_that"] == expected["such_that"]
        and parsedQuery["having"] == expected["having"]
        and parsedQuery["order_by"] == expected["order_by"]
        and parsedQuery["aggregates"] == expected["aggregates"]
    )


def test_get_parsed_query_returns_expected_structure_with_missing_parts(sales_test_data: pd.DataFrame):
    parsedQuery = get_parsed_query(data=sales_test_data, query="select cust, prod")
    expected = expected = ParsedQuery(
        data=sales_test_data,
        select=ParsedSelectClause(
            grouping_attributes=["cust", "prod"],
            aggregates=AggregatesDict(global_scope=[], group_specific=[]),
            select_items_in_order=["cust", "prod"],
        ),
        # No OVER clause parses to no groups. Empty list rather than None, so the `group not in
        # groups` check in _parse_aggregate rejects `g1.quant.sum` with a ParsingError instead of
        # failing the membership test against None (see test_validate.py).
        over=[],
        where=None,
        such_that=None,
        having=None,
        order_by=0,
        aggregates=AggregatesDict(global_scope=[], group_specific=[]),
    )
    assert (
        parsedQuery["select"] == expected["select"]
        and parsedQuery["over"] == expected["over"]
        and parsedQuery["where"] == expected["where"]
        and parsedQuery["such_that"] == expected["such_that"]
        and parsedQuery["having"] == expected["having"]
        and parsedQuery["order_by"] == expected["order_by"]
        and parsedQuery["aggregates"] == expected["aggregates"]
    )


if __name__ == "__main__":
    pytest.main()
