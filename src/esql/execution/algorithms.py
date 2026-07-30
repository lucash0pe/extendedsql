from datetime import date

import pandas as pd

from esql.execution.error import RuntimeError
from esql.execution.grouped_row import GroupedRow
from esql.parser.types import (
    AggregatesDict,
    LogicalOperator,
    ParsedHavingClause,
    ParsedSelectClause,
    ParsedSuchThatClause,
    ParsedWhereClause,
    aggregate_key,
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
        resolved_where_clause = _resolve_semi_joins(
            condition=parsed_where_clause, datatable=datatable, column_indices=column_indices
        )
        filtered_datatable = [
            datatable_row
            for datatable_row in datatable
            if _evaluate_condition(condition=resolved_where_clause, row=datatable_row, column_indices=column_indices)
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
            section_aggregates = [aggregate for aggregate in group_aggregates if aggregate["group"] == group]
            if _has_entry_value(group_such_that_section):
                _accumulate_by_entry_value(
                    section=group_such_that_section,
                    aggregates=section_aggregates,
                    grouped_rows=grouped_rows,
                    datatable=filtered_datatable,
                    column_indices=column_indices,
                )
            else:
                _accumulate_by_row(
                    section=group_such_that_section,
                    aggregates=section_aggregates,
                    grouped_rows=grouped_rows,
                    grouping_attributes=grouping_attributes,
                    datatable=filtered_datatable,
                    column_indices=column_indices,
                )

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
# SUCH THAT Accumulation
###############################################################################
def _accumulate_by_row(
    section: dict,
    aggregates: list,
    grouped_rows: dict[tuple, GroupedRow],
    grouping_attributes: list[str],
    datatable: list[list],
    column_indices: dict[str, int],
) -> None:
    """Feed each row the section matches into the grouped row it belongs to.

    A section that compares against constants asks the same question of every row, so a row can
    only ever feed its own grouping combination and one pass over the table answers the whole
    clause.
    """
    for datatable_row in datatable:
        if not _evaluate_condition(condition=section, row=datatable_row, column_indices=column_indices):
            continue
        grouping_attribute_combination = tuple(
            datatable_row[column_indices[attribute]] for attribute in grouping_attributes
        )
        grouped_row = grouped_rows.get(grouping_attribute_combination)
        if not grouped_row:
            continue
        for aggregate in aggregates:
            grouped_row.update_data_map(aggregate=aggregate, row=datatable_row)


def _accumulate_by_entry_value(
    section: dict,
    aggregates: list,
    grouped_rows: dict[tuple, GroupedRow],
    datatable: list[list],
    column_indices: dict[str, int],
) -> None:
    """Feed each row the section matches into the grouped row whose entry values it was matched
    against.

    An entry value asks a different question of each output row, and the rows that answer it sit in
    a *different* grouping combination than the row being computed: `prev.month = month - 1` scopes
    `prev` to last month's rows, which belong to last month's group. The pass above cannot serve
    that, because it routes a matching row to its own combination. So the grouped row is fixed
    first, its entry values are bound into the section, and the table is scanned against the result.

    That is one scan per output row rather than one for the clause. It is the cost of the EMF form,
    which is why a section of constants keeps the cheaper pass.
    """
    for grouped_row in grouped_rows.values():
        bound_section = _bind_entry_values(condition=section, entry_values=grouped_row.data_map)
        for datatable_row in datatable:
            if not _evaluate_condition(condition=bound_section, row=datatable_row, column_indices=column_indices):
                continue
            for aggregate in aggregates:
                grouped_row.update_data_map(aggregate=aggregate, row=datatable_row)


def _has_entry_value(condition: dict) -> bool:
    if condition.get("is_emf"):
        return True
    if "conditions" in condition:
        return any(_has_entry_value(sub_condition) for sub_condition in condition["conditions"])
    if "condition" in condition:
        return _has_entry_value(condition["condition"])
    return False


def _bind_entry_values(condition: dict, entry_values: dict[str, str | int | bool | date]) -> dict:
    """Replace every entry value with the literal the grouped row being computed holds for it.

    The same shape as `_resolve_semi_joins`: a condition that is not a question about the row in
    hand is answered up front, so the per-row pass that follows is an ordinary comparison and
    `_evaluate_condition` needs to know nothing about entry values. Returns a new condition tree,
    leaving the parsed AST alone so it stays reusable across the other grouped rows.
    """
    if condition.get("is_emf"):
        entry_value = condition["value"]
        value = entry_values.get(entry_value["attribute"])
        # A blank grouping cell has nothing to offset. It stays missing, and a comparison against a
        # missing operand reads as not-true in _evaluate_actual_vs_expected_value.
        if entry_value["delta"] and not _is_missing(value):
            value = value + entry_value["delta"]
        return {**condition, "value": value, "is_emf": False}

    if "conditions" in condition:
        return {
            **condition,
            "conditions": [
                _bind_entry_values(condition=sub_condition, entry_values=entry_values)
                for sub_condition in condition["conditions"]
            ],
        }

    if "condition" in condition:
        return {
            **condition,
            "condition": _bind_entry_values(condition=condition["condition"], entry_values=entry_values),
        }

    return condition


###############################################################################
# Evaluation
###############################################################################
def _is_missing(value) -> bool:
    """True for any missing operand: Python None, or a pandas NA/NaN/NaT scalar. Text columns are
    enforced to pandas "string" dtype (accessor._enforce_allowed_dtypes), so a blank cell arrives
    as pd.NA, whose truthiness raises rather than reading as False; numeric blanks arrive as float
    nan. pd.isna collapses all of them into one test."""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        # pd.isna on a non-scalar (e.g. a list) returns an array; such a value is never missing here.
        return False


def _resolve_semi_joins(condition: dict, datatable: list[list], column_indices: dict[str, int]) -> dict:
    """Replace every HAS node with the concrete set of key values its inner condition matched.

    A semi-join asks about the whole table ("which key values have a row satisfying this"), not
    about the row in hand, so its answer is computed once here and the per-row pass that follows is
    an ordinary membership test. The inner condition sees the *unfiltered* table on purpose: the
    rest of the WHERE clause is what the semi-join is helping to filter, so reading the filtered
    table would make the two mutually dependent. `WHERE date HAS song = 'Dark Star' AND state =
    'CT'` therefore means "dates that ever had Dark Star, then the CT rows on those dates".

    Returns a new condition tree; the parsed AST is left alone so it stays reusable.
    """
    if "key" in condition:
        key_index = column_indices.get(condition["key"])
        if key_index is None:
            raise RuntimeError(f"Column '{condition['key']}' not found in datatable")
        inner_condition = _resolve_semi_joins(
            condition=condition["condition"], datatable=datatable, column_indices=column_indices
        )
        # A row with a missing key contributes no key value, mirroring how a missing operand
        # compares as not-true in _evaluate_actual_vs_expected_value.
        key_set = {
            row[key_index]
            for row in datatable
            if not _is_missing(row[key_index])
            and _evaluate_condition(condition=inner_condition, row=row, column_indices=column_indices)
        }
        return {"key": condition["key"], "operator": condition["operator"], "key_set": key_set}

    if "conditions" in condition:
        return {
            **condition,
            "conditions": [
                _resolve_semi_joins(condition=sub_condition, datatable=datatable, column_indices=column_indices)
                for sub_condition in condition["conditions"]
            ],
        }

    if "condition" in condition:
        return {
            **condition,
            "condition": _resolve_semi_joins(
                condition=condition["condition"], datatable=datatable, column_indices=column_indices
            ),
        }

    return condition


def _evaluate_condition(condition: dict, row: list, column_indices: dict[str, int]) -> bool:
    operator = condition.get("operator")
    if "key_set" in condition:
        key_value = row[column_indices[condition["key"]]]
        # A missing key belongs to no group, so it drops rather than raising.
        return not _is_missing(key_value) and key_value in condition["key_set"]

    if "column" in condition:
        # Only _accumulate_by_entry_value knows which grouped row an entry value should read, so an
        # unbound one reaching here means the section took the wrong pass. Comparing against the
        # reference itself would silently match nothing rather than say so.
        if condition.get("is_emf"):
            raise RuntimeError(f"Entry value was not bound to a grouped row: '{condition}'")

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
    if "function" not in condition_aggregate:
        raise RuntimeError(f"Could not recognize the condition in the HAVING clause: '{condition}'")

    return _evaluate_actual_vs_expected_value(
        actual_value=data_map.get(aggregate_key(condition_aggregate)),
        operator=operator,
        condition_value=condition.get("value"),
    )


def _evaluate_actual_vs_expected_value(
    actual_value: str | int | bool | date | None, operator: str, condition_value: str | int | bool | date
) -> bool:
    # SQL NULL semantics: a comparison with a missing operand is not true, so the row drops from
    # the result instead of raising. Two sources of a missing operand: a blank cell in the data
    # (pd.NA for a "string" column, float nan for a numeric one) referenced by a WHERE/SUCH THAT
    # condition, and an absent group-specific aggregate (None) when its SUCH THAT group matched no
    # rows for this grouping combination. Either one, compared directly, would otherwise raise, the
    # NA case as "boolean value of NA is ambiguous" and the None case as a raw TypeError, leaking
    # straight to the caller (and, in the browser demo, to the visitor). Collapsing to False here
    # means a NOT wrapped directly around such a condition reads as True rather than staying NULL,
    # a small divergence from strict three-valued logic and acceptable for this engine.
    if _is_missing(actual_value) or _is_missing(condition_value):
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
    elif operator == "CONTAINS":
        # Case-insensitive by design: a case-sensitive substring search is rarely what a query
        # means, and offering both would need extra syntax to pick between them. This also matches
        # sqlite's ASCII-case-insensitive LIKE '%x%', which is what `demokit` validates against.
        return str(condition_value).lower() in str(actual_value).lower()
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


def _sort_key(value):
    """Null-safe ordering element: missing values (a blank grouping cell, pd.NA/nan/None) sort last
    and are tagged so they never get compared against a present value of another type. Without this,
    ORDER BY over a grouping column that holds blanks raises when the sort compares NA or None."""
    return (1, "") if _is_missing(value) else (0, value)


def order_by_sort(
    projected_table: list[dict[str, str | int | bool | date]], order_by: int, grouping_attributes: list[str]
) -> list[dict[str, str | int | bool | date]]:
    if order_by > 0:
        grouping_attribute_sort_keys = tuple(grouping_attributes[:order_by])
        projected_table.sort(
            key=lambda row: tuple(_sort_key(row.get(attribute)) for attribute in grouping_attribute_sort_keys)
        )
    elif order_by < 0:
        grouping_attribute_sort_keys = tuple(grouping_attributes[: abs(order_by)])
        projected_table.sort(
            key=lambda row: tuple(_sort_key(row.get(attribute)) for attribute in grouping_attribute_sort_keys),
            reverse=True,
        )
    return projected_table
