from collections.abc import Callable
from typing import Any, Literal, TypedDict, cast

import pandas as pd

from esql.execution.error import RuntimeError
from esql.execution.grouped_row import Accumulator, CellValue, GroupedRow, ProjectedValue
from esql.parser.types import (
    AggregatesDict,
    CompoundAggregateCondition,
    CompoundCondition,
    CompoundGroupCondition,
    EntryValue,
    GlobalAggregateCondition,
    GroupAggregate,
    GroupAggregateCondition,
    LogicalOperator,
    NotAggregateCondition,
    NotCondition,
    NotGroupCondition,
    ParsedCondition,
    ParsedHavingClause,
    ParsedSelectClause,
    ParsedSuchThatClause,
    ParsedSuchThatSection,
    ParsedWhereClause,
    SemiJoinCondition,
    SimpleCondition,
    SimpleGroupCondition,
    SortTerm,
    aggregate_key,
)
from esql.parser.util import find_group_in_such_that_section


class ResolvedSemiJoinCondition(TypedDict):
    """What `_resolve_semi_joins` leaves where a `SemiJoinCondition` was: the key values its inner
    condition matched, already computed.

    It is not a parsed shape, which is why it lives here and not in `parser/types.py`. A HAS node
    asks about the whole table rather than about the row in hand, so it cannot be answered during
    the per-row walk; resolving it up front is what lets `_evaluate_condition` stay an ordinary
    walk, and this is the node that walk actually meets.
    """

    key: str
    operator: Literal["HAS"]
    key_set: set[CellValue]


EvaluableCondition = ParsedCondition | ResolvedSemiJoinCondition
"""What `_evaluate_condition` takes: a parsed condition with its HAS nodes resolved.

`ParsedCondition` is the interchangeability of the two parsed hierarchies (see its definition);
this adds the one node kind that only exists after resolution. Every tree handed to the evaluator
has been through `_resolve_semi_joins` (the WHERE clause) or `_bind_entry_values` (a SUCH THAT
section) or neither, and none of those passes introduces anything else.
"""


def build_grouped_table(
    parsed_select_clause: ParsedSelectClause,
    groups: list[str] | None,
    parsed_where_clause: ParsedWhereClause | None,
    parsed_such_that_clause: ParsedSuchThatClause | None,
    parsed_having_clause: ParsedHavingClause | None,
    aggregates: AggregatesDict,
    datatable: list[list[CellValue]],
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

    grouped_rows: dict[tuple[CellValue, ...], GroupedRow] = {}
    for datatable_row in filtered_datatable:
        grouping_attribute_combination = tuple(
            datatable_row[column_indices[attribute]] for attribute in grouping_attributes
        )
        if grouping_attribute_combination in grouped_rows:
            # Indexed rather than `.get`, which answered `GroupedRow | None` on the one branch that
            # has just established the key is present.
            grouped_row = grouped_rows[grouping_attribute_combination]
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
        # `groups` is not None here: a SUCH THAT clause without an OVER to scope is refused at parse
        # time, so the two arrive together or not at all. That invariant lives in the parser, which
        # is the right place for it but not a place mypy can see from.
        for group in groups:  # type: ignore[union-attr]
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
        grouped_row.finalize_data_map()

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
    section: ParsedSuchThatSection,
    aggregates: list[GroupAggregate],
    grouped_rows: dict[tuple, GroupedRow],
    grouping_attributes: list[str],
    datatable: list[list[CellValue]],
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
    section: ParsedSuchThatSection,
    aggregates: list[GroupAggregate],
    grouped_rows: dict[tuple, GroupedRow],
    datatable: list[list[CellValue]],
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


def _has_entry_value(condition: ParsedSuchThatSection) -> bool:
    if "is_emf" in condition:
        return cast(SimpleGroupCondition, condition)["is_emf"]
    if "conditions" in condition:
        compound = cast(CompoundGroupCondition, condition)
        return any(_has_entry_value(sub_condition) for sub_condition in compound["conditions"])
    if "condition" in condition:
        return _has_entry_value(cast(NotGroupCondition, condition)["condition"])
    return False


def _bind_entry_values(
    condition: ParsedSuchThatSection, entry_values: dict[str, Accumulator]
) -> ParsedSuchThatSection:
    """Replace every entry value with the literal the grouped row being computed holds for it.

    The same shape as `_resolve_semi_joins`: a condition that is not a question about the row in
    hand is answered up front, so the per-row pass that follows is an ordinary comparison and
    `_evaluate_condition` needs to know nothing about entry values. Returns a new condition tree,
    leaving the parsed AST alone so it stays reusable across the other grouped rows.
    """
    if "is_emf" in condition:
        leaf = cast(SimpleGroupCondition, condition)
        if not leaf["is_emf"]:
            return condition
        entry_value = cast(EntryValue, leaf["value"])
        # An entry value can only name a SELECT grouping attribute (the parser refuses anything
        # else), and a grouping attribute's slot holds the row's own cell for it, set before any
        # aggregate touches the map. So this read is a plain value, never an accumulating shape.
        value = cast(CellValue | None, entry_values.get(entry_value["attribute"]))
        # A blank grouping cell has nothing to offset. It stays missing, and a comparison against a
        # missing operand reads as not-true in _evaluate_actual_vs_expected_value.
        if entry_value["delta"] and not _is_missing(value):
            value = cast(float, value) + entry_value["delta"]
        return cast(SimpleGroupCondition, {**leaf, "value": value, "is_emf": False})

    if "conditions" in condition:
        compound = cast(CompoundGroupCondition, condition)
        return CompoundGroupCondition(
            operator=compound["operator"],
            conditions=[
                _bind_entry_values(condition=sub_condition, entry_values=entry_values)
                for sub_condition in compound["conditions"]
            ],
        )

    if "condition" in condition:
        negation = cast(NotGroupCondition, condition)
        return NotGroupCondition(
            operator=negation["operator"],
            condition=_bind_entry_values(condition=negation["condition"], entry_values=entry_values),
        )

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


def _resolve_semi_joins(
    condition: ParsedWhereClause, datatable: list[list[CellValue]], column_indices: dict[str, int]
) -> EvaluableCondition:
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
        semi_join = cast(SemiJoinCondition, condition)
        key_index = column_indices.get(semi_join["key"])
        if key_index is None:
            raise RuntimeError(f"Column '{semi_join['key']}' not found in datatable")
        inner_condition = _resolve_semi_joins(
            condition=semi_join["condition"], datatable=datatable, column_indices=column_indices
        )
        # A row with a missing key contributes no key value, mirroring how a missing operand
        # compares as not-true in _evaluate_actual_vs_expected_value.
        key_set = {
            row[key_index]
            for row in datatable
            if not _is_missing(row[key_index])
            and _evaluate_condition(condition=inner_condition, row=row, column_indices=column_indices)
        }
        return ResolvedSemiJoinCondition(key=semi_join["key"], operator=semi_join["operator"], key_set=key_set)

    # A branch node keeps its shape and swaps its children, which is the one thing resolution
    # changes about it: a child may now be a `ResolvedSemiJoinCondition`. Declaring that would take
    # a parallel hierarchy of branch types whose only difference is the element type, so it is a
    # cast with the reason written here instead. `EvaluableCondition` is what the walk downstream
    # reads, and it admits either child.
    if "conditions" in condition:
        compound = cast(CompoundCondition, condition)
        return cast(
            EvaluableCondition,
            {
                **compound,
                "conditions": [
                    _resolve_semi_joins(condition=sub_condition, datatable=datatable, column_indices=column_indices)
                    for sub_condition in compound["conditions"]
                ],
            },
        )

    if "condition" in condition:
        negation = cast(NotCondition, condition)
        return cast(
            EvaluableCondition,
            {
                **negation,
                "condition": _resolve_semi_joins(
                    condition=negation["condition"], datatable=datatable, column_indices=column_indices
                ),
            },
        )

    return condition


def _evaluate_condition(condition: EvaluableCondition, row: list[CellValue], column_indices: dict[str, int]) -> bool:
    operator = condition["operator"]
    if "key_set" in condition:
        semi_join = cast(ResolvedSemiJoinCondition, condition)
        key_value = row[column_indices[semi_join["key"]]]
        # A missing key belongs to no group, so it drops rather than raising.
        return not _is_missing(key_value) and key_value in semi_join["key_set"]

    if "column" in condition:
        # A `column` key means a leaf, which is a `SimpleCondition` or the `SimpleGroupCondition`
        # that inherits it; the narrowing covers both, which is the point of that one inheritance.
        leaf = cast(SimpleCondition, condition)
        # Only _accumulate_by_entry_value knows which grouped row an entry value should read, so an
        # unbound one reaching here means the section took the wrong pass. Comparing against the
        # reference itself would silently match nothing rather than say so.
        if leaf["is_emf"]:
            raise RuntimeError(f"Entry value was not bound to a grouped row: '{condition}'")

        column_index = column_indices.get(leaf["column"])
        if column_index is None:
            raise RuntimeError(f"Column '{leaf['column']}' not found in datatable")
        actual_value = row[column_index]
        # `is_emf` is False here, so `value` is a literal rather than an `EntryValue`. The two share
        # a slot because a condition is parsed before it is known which pass will answer it.
        return _evaluate_actual_vs_expected_value(
            actual_value=actual_value,
            operator=leaf["operator"],
            condition_value=cast(CellValue, leaf["value"]),
        )

    if operator == LogicalOperator.AND:
        return all(
            _evaluate_condition(condition=and_condition, row=row, column_indices=column_indices)
            for and_condition in cast(CompoundCondition | CompoundGroupCondition, condition)["conditions"]
        )
    elif operator == LogicalOperator.OR:
        return any(
            _evaluate_condition(condition=or_condition, row=row, column_indices=column_indices)
            for or_condition in cast(CompoundCondition | CompoundGroupCondition, condition)["conditions"]
        )
    elif operator == LogicalOperator.NOT:
        negation = cast(NotCondition | NotGroupCondition, condition)
        return not _evaluate_condition(condition=negation["condition"], row=row, column_indices=column_indices)
    else:
        raise RuntimeError(f"Unknown logical operator: {operator}")


def _evaluate_having_clause(condition: ParsedHavingClause, data_map: dict[str, Accumulator]) -> bool:
    operator = condition["operator"]
    if operator == LogicalOperator.NOT:
        negation = cast(NotAggregateCondition, condition)
        return not _evaluate_having_clause(condition=negation["condition"], data_map=data_map)

    if "conditions" in condition:
        compound = cast(CompoundAggregateCondition, condition)
        if operator == LogicalOperator.AND:
            return all(
                _evaluate_having_clause(condition=and_condition, data_map=data_map)
                for and_condition in compound["conditions"]
            )
        elif operator == LogicalOperator.OR:
            return any(
                _evaluate_having_clause(condition=or_condition, data_map=data_map)
                for or_condition in compound["conditions"]
            )
        else:
            raise RuntimeError(f"Unknown logical operator in HAVING clause: '{operator}'")

    comparison = cast(GlobalAggregateCondition | GroupAggregateCondition, condition)
    condition_aggregate = comparison["aggregate"]
    if "function" not in condition_aggregate:
        raise RuntimeError(f"Could not recognize the condition in the HAVING clause: '{condition}'")

    return _evaluate_actual_vs_expected_value(
        # `build_grouped_table` finalizes every data map before it evaluates HAVING, and finalizing
        # is what turns the two accumulating shapes into answers (a set into its size, a
        # sum/count pair into the quotient). So a slot read here is a plain value or absent.
        actual_value=cast(ProjectedValue, data_map.get(aggregate_key(condition_aggregate))),
        operator=comparison["operator"],
        condition_value=comparison["value"],
    )


def _evaluate_actual_vs_expected_value(
    actual_value: CellValue | None, operator: str, condition_value: CellValue
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
    # The four ordering comparisons are deliberately un-narrowed, and the ignores are the sharp edge
    # left sharp rather than papered over with `Any`, which would also silence a real error here.
    # Both operands are the same dtype family by the time they arrive: the parser reads a comparison
    # value as its column's own kind (v1.12.0), and ordering on a string or bool column is refused
    # outright before execution (v1.11.0, and it is the published `GRAMMAR["operators"]["dtypes"]`
    # table). mypy sees neither guarantee, so it cross-products the union and reports every pairing
    # the parser has already ruled out. Narrowing here would restate that table in a third place.
    elif operator == ">":
        return actual_value > condition_value  # type: ignore[operator]
    elif operator == "<":
        return actual_value < condition_value  # type: ignore[operator]
    elif operator == ">=":
        return actual_value >= condition_value  # type: ignore[operator]
    elif operator == "<=":
        return actual_value <= condition_value  # type: ignore[operator]
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
) -> list[dict[str, ProjectedValue]]:
    select_items = parsed_select_clause["select_items_in_order"]
    projected_table = []
    for grouped_row in grouped_table:
        row: dict[str, ProjectedValue] = {}
        for select_item in select_items:
            # Finalized before this runs (`build_grouped_table`), so the accumulating shapes -- the
            # distinct-value set and the sum/count pair -- have already become answers. Same
            # invariant the HAVING evaluator reads under.
            value = cast(ProjectedValue, grouped_row.data_map.get(select_item))
            if isinstance(value, float):
                row[select_item] = round(value, decimal_places)
            else:
                row[select_item] = value
        projected_table.append(row)
    return projected_table


def _sort_key(value: ProjectedValue) -> tuple[int, Any]:
    """Null-safe ordering element: missing values (a blank grouping cell, pd.NA/nan/None) sort last
    and are tagged so they never get compared against a present value of another type. Without this,
    ORDER BY over a grouping column that holds blanks raises when the sort compares NA or None."""
    return (1, "") if _is_missing(value) else (0, value)


def _sort_by_term(term: str) -> Callable[[dict[str, ProjectedValue]], tuple[int, Any]]:
    """A sort key reading one projected term.

    A closure rather than the `lambda row, term=term:` default-argument trick it replaces. That trick
    binds the loop variable by value, which the sort below does not need -- each `sort()` finishes
    before the next iteration rebinds anything -- and a lambda with a default argument is one mypy
    cannot infer a type for.
    """
    return lambda row: _sort_key(row.get(term))


def order_by_sort(
    projected_table: list[dict[str, ProjectedValue]], order_by: list[SortTerm]
) -> list[dict[str, ProjectedValue]]:
    """Sort the projected rows by each term, outermost first.

    One pass per term, applied from the innermost key outwards, which is the standard way to get a
    multi-key sort where the keys run in different directions: Python's sort is stable, so each pass
    keeps the order the previous ones established among rows it considers equal. A single tuple key
    cannot do that, because `reverse` there flips every key at once.

    A term is a projected label, so an aggregate sorts exactly like a grouping attribute -- by the
    time the rows reach here the difference has already been projected away.
    """
    for sort_term in reversed(order_by):
        projected_table.sort(key=_sort_by_term(sort_term["term"]), reverse=sort_term["descending"])
    return projected_table
