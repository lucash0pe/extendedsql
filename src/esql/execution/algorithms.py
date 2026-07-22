from datetime import date

from esql.execution.error import RuntimeError
from esql.execution.grouped_row import GroupedRow
from esql.parser.types import (
    AggregatesDict,
    LogicalOperator,
    ParsedHavingClause,
    ParsedSelectClause,
    ParsedSuchThatClause,
    ParsedWhereClause,
)
from esql.parser.util import find_group_in_such_that_section


def build_grouped_table(
    parsed_select_clause: ParsedSelectClause,
    groups: list[str] | None,
    parsed_where_clause: ParsedWhereClause | None,
    parsed_such_that_clause: ParsedSuchThatClause,
    parsed_having_clause: ParsedHavingClause,
    aggregates: AggregatesDict,
    datatable: list[list[int | str | bool | date]],
    column_indices: dict[str, int],
):
    grouping_attributes = parsed_select_clause["grouping_attributes"]
    global_aggregates = aggregates["global_scope"]
    group_aggregates = aggregates["group_specific"]

    filtered_datatable = datatable
    if parsed_where_clause:
        filtered_datatable = [
            datatable_row
            for datatable_row in datatable
            if _evaluate_condition(condition=parsed_where_clause, row=datatable_row, column_indices=column_indices)
        ]

    grouped_rows = {}
    for datatable_row in filtered_datatable:
        grouping_attribute_combination = tuple(
            datatable_row[column_indices[attribute]] for attribute in grouping_attributes
        )
        if grouping_attribute_combination in grouped_rows:
            grouped_row = grouped_rows.get(grouping_attribute_combination)
            for aggregate in global_aggregates:
                grouped_row.update_data_map(aggregate, datatable_row)
        else:
            grouped_row = GroupedRow(
                grouping_attributes=grouping_attributes,
                aggregates=aggregates,
                initial_row=datatable_row,
                column_indices=column_indices,
            )
            grouped_rows[grouping_attribute_combination] = grouped_row

    if parsed_such_that_clause:
        for group in groups:
            group_such_that_section = next(
                (
                    such_that_section
                    for such_that_section in parsed_such_that_clause
                    if find_group_in_such_that_section(such_that_section) == group
                ),
                None,
            )
            if not group_such_that_section:
                continue
            for datatable_row in filtered_datatable:
                if _evaluate_condition(
                    condition=group_such_that_section, row=datatable_row, column_indices=column_indices
                ):
                    grouping_attribute_combination = tuple(
                        datatable_row[column_indices[attribute]] for attribute in grouping_attributes
                    )
                    grouped_row = grouped_rows.get(grouping_attribute_combination)
                    if grouped_row:
                        for aggregate in group_aggregates:
                            if aggregate["group"] == group:
                                grouped_row.update_data_map(aggregate=aggregate, row=datatable_row)

    grouped_table = list(grouped_rows.values())
    for grouped_row in grouped_table:
        grouped_row.convert_avg_in_data_map()

    if parsed_having_clause:
        grouped_table = [
            grouped_row
            for grouped_row in grouped_table
            if _evaluate_having_clause(condition=parsed_having_clause, data_map=grouped_row.data_map)
        ]
    return grouped_table


###############################################################################
# Evaluation
###############################################################################
def _evaluate_condition(condition: dict, row: list, column_indices: dict[str, int]) -> bool:
    operator = condition.get("operator")
    if "column" in condition:
        column = condition.get("column")
        condition_value = condition.get("value")
        column_index = column_indices.get(column)
        if column_index is None:
            raise RuntimeError(f"Column '{column}' not found in datatable")
        actual_value = row[column_index]
        return _evaluate_actual_vs_expected_value(
            actual_value=actual_value, operator=operator, condition_value=condition_value
        )

    if operator == LogicalOperator.AND:
        return all(
            _evaluate_condition(condition=and_condition, row=row, column_indices=column_indices)
            for and_condition in condition.get("conditions", [])
        )
    elif operator == LogicalOperator.OR:
        return any(
            _evaluate_condition(condition=or_condition, row=row, column_indices=column_indices)
            for or_condition in condition.get("conditions", [])
        )
    elif operator == LogicalOperator.NOT:
        return not _evaluate_condition(condition=condition.get("condition"), row=row, column_indices=column_indices)
    else:
        raise RuntimeError(f"Unknown logical operator: {operator}")


def _evaluate_having_clause(condition: ParsedHavingClause, data_map: dict[str, str | int | bool | date]) -> bool:
    operator = condition.get("operator")
    if operator == LogicalOperator.NOT:
        return not _evaluate_having_clause(condition=condition.get("condition"), data_map=data_map)

    if "conditions" in condition:
        if operator == LogicalOperator.AND:
            return all(
                _evaluate_having_clause(condition=and_condition, data_map=data_map)
                for and_condition in condition["conditions"]
            )
        elif operator == LogicalOperator.OR:
            return any(
                _evaluate_having_clause(condition=or_condition, data_map=data_map)
                for or_condition in condition["conditions"]
            )
        else:
            raise RuntimeError(f"Unknown logical operator in HAVING clause: '{operator}'")

    condition_aggregate = condition.get("aggregate")
    if "function" in condition_aggregate:
        if "group" in condition_aggregate:
            aggregate_key = (
                f"{condition_aggregate['group']}.{condition_aggregate['column']}.{condition_aggregate['function']}"
            )
        else:
            aggregate_key = f"{condition_aggregate['column']}.{condition_aggregate['function']}"
    else:
        raise RuntimeError(f"Could not recognize the condition in the HAVING clause: '{condition}'")

    return _evaluate_actual_vs_expected_value(
        actual_value=data_map.get(aggregate_key), operator=operator, condition_value=condition.get("value")
    )


def _evaluate_actual_vs_expected_value(
    actual_value: str | int | bool | date | None, operator: str, condition_value: str | int | bool | date
) -> bool:
    # SQL NULL semantics: a comparison with a missing operand is not true, so the row drops from
    # the result instead of raising. A group-specific aggregate is absent (None) when its SUCH
    # THAT group matched no rows for this grouping combination; comparing that None with an
    # ordering operator (>, <, >=, <=) would otherwise raise a raw TypeError that leaks straight
    # to the caller (and, in the browser demo, to the visitor). Collapsing to False here means a
    # NOT wrapped directly around such a condition reads as True rather than staying NULL, which
    # is a small divergence from strict three-valued logic and acceptable for this engine.
    if actual_value is None or condition_value is None:
        return False
    if operator in ["=", "=="]:
        return actual_value == condition_value
    elif operator == ">":
        return actual_value > condition_value
    elif operator == "<":
        return actual_value < condition_value
    elif operator == ">=":
        return actual_value >= condition_value
    elif operator == "<=":
        return actual_value <= condition_value
    elif operator == "!=":
        return actual_value != condition_value
    else:
        raise RuntimeError(f"Unknown operator in condition: '{operator}'")


###############################################################################
# Projection and Ordering
###############################################################################
def project_select_attributes(
    parsed_select_clause: ParsedSelectClause, grouped_table: list[GroupedRow], decimal_places: int
) -> list[dict[str, str | int | bool | date]]:
    select_items = parsed_select_clause["select_items_in_order"]
    projected_table = []
    for grouped_row in grouped_table:
        row = {}
        for select_item in select_items:
            value = grouped_row.data_map.get(select_item)
            if isinstance(value, float):
                row[select_item] = round(value, decimal_places)
            else:
                row[select_item] = value
        projected_table.append(row)
    return projected_table


def order_by_sort(
    projected_table: list[dict[str, str | int | bool | date]], order_by: int, grouping_attributes: list[str]
) -> list[dict[str, str | int | bool | date]]:
    if order_by > 0:
        grouping_attribute_sort_keys = tuple(grouping_attributes[:order_by])
        projected_table.sort(
            key=lambda row: tuple(row.get(grouping_attribute) for grouping_attribute in grouping_attribute_sort_keys)
        )
    elif order_by < 0:
        grouping_attribute_sort_keys = tuple(grouping_attributes[: abs(order_by)])
        projected_table.sort(
            key=lambda row: tuple(row.get(grouping_attribute) for grouping_attribute in grouping_attribute_sort_keys),
            reverse=True,
        )
    return projected_table
