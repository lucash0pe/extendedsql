import pytest

from esql.execution.algorithms import order_by_sort, project_select_attributes
from esql.execution.grouped_row import GroupedRow
from esql.parser.types import AggregatesDict, ParsedSelectClause, SortTerm


def _first(attributes: list[str], count: int, descending: bool = False) -> list[SortTerm]:
    """The sort `ORDER BY <count>` describes: the first `count` grouping attributes, in order.

    These tests predate named sort terms and were written against the integer form, so this keeps
    them saying what they said. The parser produces the same list from `ORDER BY <count>`.
    """
    return [SortTerm(term=attribute, descending=descending) for attribute in attributes[:count]]


def test_order_by_sort():
    grouping_attributes = ["cust", "prod"]
    order_by_0 = [
        {"cust": "Wally", "prod": "Butter", "round": 480.41, "sum": 55727},
        {"cust": "Boo", "prod": "Cherry", "round": 486.66, "sum": 48666},
        {"cust": "Helen", "prod": "Butter", "round": 464.56, "sum": 48779},
        {"cust": "Claire", "prod": "Butter", "round": 519.05, "sum": 67995},
        {"cust": "Wally", "prod": "Apple", "round": 534.51, "sum": 58262},
        {"cust": "Mia", "prod": "Butter", "round": 502.17, "sum": 54234},
        {"cust": "Claire", "prod": "Ham", "round": 507.43, "sum": 58354},
        {"cust": "Boo", "prod": "Ice", "round": 472.79, "sum": 45861},
        {"cust": "Mia", "prod": "Cherry", "round": 478.53, "sum": 51203},
        {"cust": "Helen", "prod": "Ice", "round": 515.34, "sum": 60295},
        {"cust": "Wally", "prod": "Ham", "round": 533.85, "sum": 59257},
        {"cust": "Helen", "prod": "Cherry", "round": 493.63, "sum": 61704},
        {"cust": "Wally", "prod": "Cherry", "round": 527.54, "sum": 63832},
        {"cust": "Mia", "prod": "Grapes", "round": 444.25, "sum": 45758},
    ]
    order_by_1 = [
        {"cust": "Boo", "prod": "Cherry", "round": 486.66, "sum": 48666},
        {"cust": "Boo", "prod": "Ice", "round": 472.79, "sum": 45861},
        {"cust": "Claire", "prod": "Butter", "round": 519.05, "sum": 67995},
        {"cust": "Claire", "prod": "Ham", "round": 507.43, "sum": 58354},
        {"cust": "Helen", "prod": "Butter", "round": 464.56, "sum": 48779},
        {"cust": "Helen", "prod": "Ice", "round": 515.34, "sum": 60295},
        {"cust": "Helen", "prod": "Cherry", "round": 493.63, "sum": 61704},
        {"cust": "Mia", "prod": "Butter", "round": 502.17, "sum": 54234},
        {"cust": "Mia", "prod": "Cherry", "round": 478.53, "sum": 51203},
        {"cust": "Mia", "prod": "Grapes", "round": 444.25, "sum": 45758},
        {"cust": "Wally", "prod": "Butter", "round": 480.41, "sum": 55727},
        {"cust": "Wally", "prod": "Apple", "round": 534.51, "sum": 58262},
        {"cust": "Wally", "prod": "Ham", "round": 533.85, "sum": 59257},
        {"cust": "Wally", "prod": "Cherry", "round": 527.54, "sum": 63832},
    ]
    order_by_2 = [
        {"cust": "Boo", "prod": "Cherry", "round": 486.66, "sum": 48666},
        {"cust": "Boo", "prod": "Ice", "round": 472.79, "sum": 45861},
        {"cust": "Claire", "prod": "Butter", "round": 519.05, "sum": 67995},
        {"cust": "Claire", "prod": "Ham", "round": 507.43, "sum": 58354},
        {"cust": "Helen", "prod": "Butter", "round": 464.56, "sum": 48779},
        {"cust": "Helen", "prod": "Cherry", "round": 493.63, "sum": 61704},
        {"cust": "Helen", "prod": "Ice", "round": 515.34, "sum": 60295},
        {"cust": "Mia", "prod": "Butter", "round": 502.17, "sum": 54234},
        {"cust": "Mia", "prod": "Cherry", "round": 478.53, "sum": 51203},
        {"cust": "Mia", "prod": "Grapes", "round": 444.25, "sum": 45758},
        {"cust": "Wally", "prod": "Apple", "round": 534.51, "sum": 58262},
        {"cust": "Wally", "prod": "Butter", "round": 480.41, "sum": 55727},
        {"cust": "Wally", "prod": "Cherry", "round": 527.54, "sum": 63832},
        {"cust": "Wally", "prod": "Ham", "round": 533.85, "sum": 59257},
    ]
    assert order_by_sort(projected_table=order_by_0, order_by=_first(grouping_attributes, 0)) == order_by_0
    assert order_by_sort(projected_table=order_by_0, order_by=_first(grouping_attributes, 1)) == order_by_1
    assert order_by_sort(projected_table=order_by_0, order_by=_first(grouping_attributes, 2)) == order_by_2


def test_order_by_sort_works_when_grouping_attributes_are_not_at_the_front():
    grouping_attributes = ["cust", "prod"]
    order_by_0 = [
        {"round": 480.41, "cust": "Wally", "sum": 55727, "prod": "Butter"},
        {"round": 486.66, "cust": "Boo", "sum": 48666, "prod": "Cherry"},
        {"round": 464.56, "cust": "Helen", "sum": 48779, "prod": "Butter"},
        {"round": 534.51, "cust": "Wally", "sum": 58262, "prod": "Apple"},
        {"round": 472.79, "cust": "Boo", "sum": 45861, "prod": "Ice"},
        {"round": 515.34, "cust": "Helen", "sum": 60295, "prod": "Ice"},
        {"round": 533.85, "cust": "Wally", "sum": 59257, "prod": "Ham"},
        {"round": 493.63, "cust": "Helen", "sum": 61704, "prod": "Cherry"},
        {"round": 527.54, "cust": "Wally", "sum": 63832, "prod": "Cherry"},
    ]
    order_by_1 = [
        {"round": 486.66, "cust": "Boo", "sum": 48666, "prod": "Cherry"},
        {"round": 472.79, "cust": "Boo", "sum": 45861, "prod": "Ice"},
        {"round": 464.56, "cust": "Helen", "sum": 48779, "prod": "Butter"},
        {"round": 515.34, "cust": "Helen", "sum": 60295, "prod": "Ice"},
        {"round": 493.63, "cust": "Helen", "sum": 61704, "prod": "Cherry"},
        {"round": 480.41, "cust": "Wally", "sum": 55727, "prod": "Butter"},
        {"round": 534.51, "cust": "Wally", "sum": 58262, "prod": "Apple"},
        {"round": 533.85, "cust": "Wally", "sum": 59257, "prod": "Ham"},
        {"round": 527.54, "cust": "Wally", "sum": 63832, "prod": "Cherry"},
    ]
    order_by_2 = [
        {"round": 486.66, "cust": "Boo", "sum": 48666, "prod": "Cherry"},
        {"round": 472.79, "cust": "Boo", "sum": 45861, "prod": "Ice"},
        {"round": 464.56, "cust": "Helen", "sum": 48779, "prod": "Butter"},
        {"round": 493.63, "cust": "Helen", "sum": 61704, "prod": "Cherry"},
        {"round": 515.34, "cust": "Helen", "sum": 60295, "prod": "Ice"},
        {"round": 534.51, "cust": "Wally", "sum": 58262, "prod": "Apple"},
        {"round": 480.41, "cust": "Wally", "sum": 55727, "prod": "Butter"},
        {"round": 527.54, "cust": "Wally", "sum": 63832, "prod": "Cherry"},
        {"round": 533.85, "cust": "Wally", "sum": 59257, "prod": "Ham"},
    ]
    assert order_by_sort(projected_table=order_by_0, order_by=_first(grouping_attributes, 0)) == order_by_0
    assert order_by_sort(projected_table=order_by_0, order_by=_first(grouping_attributes, 1)) == order_by_1
    assert order_by_sort(projected_table=order_by_0, order_by=_first(grouping_attributes, 2)) == order_by_2


def test_order_by_sort_works_with_numbers():
    grouping_attributes = ["round", "sum"]
    order_by_0 = [
        {"round": 480, "sum": 55727},
        {"round": 480, "sum": 48666},
        {"round": 520, "sum": 67995},
        {"round": 520, "sum": 58262},
        {"round": 500, "sum": 58354},
        {"round": 500, "sum": 54234},
        {"round": 480, "sum": 45861},
    ]
    order_by_1 = [
        {"round": 480, "sum": 55727},
        {"round": 480, "sum": 48666},
        {"round": 480, "sum": 45861},
        {"round": 500, "sum": 58354},
        {"round": 500, "sum": 54234},
        {"round": 520, "sum": 67995},
        {"round": 520, "sum": 58262},
    ]
    order_by_2 = [
        {"round": 480, "sum": 45861},
        {"round": 480, "sum": 48666},
        {"round": 480, "sum": 55727},
        {"round": 500, "sum": 54234},
        {"round": 500, "sum": 58354},
        {"round": 520, "sum": 58262},
        {"round": 520, "sum": 67995},
    ]
    assert order_by_sort(projected_table=order_by_0, order_by=_first(grouping_attributes, 0)) == order_by_0
    assert order_by_sort(projected_table=order_by_0, order_by=_first(grouping_attributes, 1)) == order_by_1
    assert order_by_sort(projected_table=order_by_0, order_by=_first(grouping_attributes, 2)) == order_by_2


def test_order_by_sort_with_numeric_attribute():
    grouping_attributes = ["cust", "num"]
    order_by_0 = [
        {"cust": "Wally", "num": 10},
        {"cust": "Boo", "num": 8},
        {"cust": "Boo", "num": 6},
        {"cust": "Wally", "num": 15},
        {"cust": "Helen", "num": 12},
        {"cust": "Claire", "num": 20},
        {"cust": "Mia", "num": 7},
        {"cust": "Helen", "num": 18},
        {"cust": "Mia", "num": 5},
        {"cust": "Wally", "num": 25},
        {"cust": "Mia", "num": 6},
    ]
    order_by_neg_1 = [
        {"cust": "Wally", "num": 10},
        {"cust": "Wally", "num": 15},
        {"cust": "Wally", "num": 25},
        {"cust": "Mia", "num": 7},
        {"cust": "Mia", "num": 5},
        {"cust": "Mia", "num": 6},
        {"cust": "Helen", "num": 12},
        {"cust": "Helen", "num": 18},
        {"cust": "Claire", "num": 20},
        {"cust": "Boo", "num": 8},
        {"cust": "Boo", "num": 6},
    ]
    order_by_neg_2 = [
        {"cust": "Wally", "num": 25},
        {"cust": "Wally", "num": 15},
        {"cust": "Wally", "num": 10},
        {"cust": "Mia", "num": 7},
        {"cust": "Mia", "num": 6},
        {"cust": "Mia", "num": 5},
        {"cust": "Helen", "num": 18},
        {"cust": "Helen", "num": 12},
        {"cust": "Claire", "num": 20},
        {"cust": "Boo", "num": 8},
        {"cust": "Boo", "num": 6},
    ]
    assert order_by_sort(projected_table=order_by_0, order_by=_first(grouping_attributes, 0)) == order_by_0
    assert (
        order_by_sort(projected_table=order_by_0, order_by=_first(grouping_attributes, 1, descending=True))
        == order_by_neg_1
    )
    assert (
        order_by_sort(projected_table=order_by_0, order_by=_first(grouping_attributes, 2, descending=True))
        == order_by_neg_2
    )


def test_finalizing_twice_leaves_the_same_values():
    """`finalize_data_map` dispatches on the accumulator's shape rather than on a flag, which is what
    makes a second pass a no-op. The flagged version raised "'float' object is not subscriptable" on
    an avg converted twice, which is how BUG-8's duplicate aggregate showed up."""
    aggregates: AggregatesDict = {
        "global_scope": [
            {"column": "quant", "function": "avg"},
            {"column": "quant", "function": "count"},
            {"column": None, "function": "count"},
        ],
        "group_specific": [],
    }
    row = GroupedRow(
        grouping_attributes=["cust"],
        aggregates=aggregates,
        initial_row=["Alice", 10.0],
        column_indices={"cust": 0, "quant": 1},
    )
    row.update_data_map(aggregates["global_scope"][0], ["Alice", 20.0])
    row.finalize_data_map()
    finalized = dict(row.data_map)
    row.finalize_data_map()
    assert row.data_map == finalized
    assert finalized["quant.avg"] == 15
    assert finalized["quant.count"] == 1
    assert finalized["count"] == 1


def test_projection_rounds_correctly():
    grouping_attributes = ["cust", "prod"]
    column_indices = {"cust": 0, "prod": 1, "quant1": 2, "quant2": 3}
    initial_row = ["Alice", "Apples", 12.514839, 3543.4]
    aggregates: AggregatesDict = {
        "global_scope": [
            {"column": "quant1", "function": "sum"},
            {"column": "quant1", "function": "count"},
            {"column": "quant2", "function": "sum"},
            {"column": "quant2", "function": "count"},
        ],
        "group_specific": [],
    }
    row = GroupedRow(
        grouping_attributes=grouping_attributes,
        aggregates=aggregates,
        initial_row=initial_row,
        column_indices=column_indices,
    )
    # As `build_grouped_table` does before projecting: a count is a set of distinct values and an
    # avg a running {sum, count} until this pass turns each into the number the query asked for.
    row.finalize_data_map()
    table = [row]
    parsed_select_clause = ParsedSelectClause(
        grouping_attributes=grouping_attributes,
        aggregates=aggregates,
        select_items_in_order=["cust", "prod", "quant1.sum", "quant1.count", "quant2.sum", "quant2.count"],
    )
    expected_result_1 = [
        {
            "cust": "Alice",
            "prod": "Apples",
            "quant1.sum": 12.5,
            "quant1.count": 1,
            "quant2.sum": 3543.4,
            "quant2.count": 1,
        }
    ]
    expected_result_3 = [
        {
            "cust": "Alice",
            "prod": "Apples",
            "quant1.sum": 12.515,
            "quant1.count": 1,
            "quant2.sum": 3543.400,
            "quant2.count": 1,
        }
    ]
    expected_result_5 = [
        {
            "cust": "Alice",
            "prod": "Apples",
            "quant1.sum": 12.51484,
            "quant1.count": 1,
            "quant2.sum": 3543.40000,
            "quant2.count": 1,
        }
    ]
    assert (
        project_select_attributes(parsed_select_clause=parsed_select_clause, grouped_table=table, decimal_places=1)
        == expected_result_1
    )
    assert (
        project_select_attributes(parsed_select_clause=parsed_select_clause, grouped_table=table, decimal_places=3)
        == expected_result_3
    )
    assert (
        project_select_attributes(parsed_select_clause=parsed_select_clause, grouped_table=table, decimal_places=5)
        == expected_result_5
    )


if __name__ == "__main__":
    pytest.main()
