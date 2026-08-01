from datetime import date
from enum import Enum
from typing import Literal, TypedDict, TypeGuard

import numpy as np
import pandas as pd
from pandas.api.extensions import ExtensionDtype

ColumnDtype = np.dtype | ExtensionDtype
"""The dtype of one column of the frame the parser reads.

Not `np.dtype`, which is what these signatures used to say and what every one of them was wrong
about. `accessor._enforce_allowed_dtypes` coerces text columns to pandas `"string"`, whose dtype is
`StringDtype` -- an `ExtensionDtype`, not a numpy one. So on `sales.csv` three of nine columns hold
a dtype the annotation called impossible, and they are the columns every text comparison reads.

The same shape as L1's missing `float`: a value the code always sees, declared out of existence.
`dtype_family` said as much in prose ("reads an enforced dtype") while its signature said otherwise.
"""


class GlobalAggregate(TypedDict):
    """One aggregate to compute per output row.

    `column` is None for the bare row count (`count`, or `g1.count` with a group), which is the one
    aggregate that names no column: it asks how many rows the group holds, and every row holds
    itself. Every other function needs a column, and `column.count` counts that column's *distinct*
    values, so a column named in an aggregate always bears on the answer.

    Two of these are equal when their keys are, which is plain dict equality: a TypedDict *is* a
    `dict` at runtime, so it carries no identity of its own. That is what the SELECT/HAVING merge in
    `_build_parsed_query` compares, and `tests/parser/test_aggregate_identity.py` pins it. This class
    used to define an `__eq__` that ignored `group`; it never ran, because no instance is ever of
    this type, and it disagreed with the equality that does run.
    """

    column: str | None
    function: str


class GroupAggregate(GlobalAggregate):
    """A `GlobalAggregate` scoped to one OVER group, so `group` is part of its identity."""

    group: str


class AggregatesDict(TypedDict):
    global_scope: list[GlobalAggregate]
    group_specific: list[GroupAggregate]


def is_group_aggregate(aggregate: GlobalAggregate | GroupAggregate) -> TypeGuard[GroupAggregate]:
    """Whether an aggregate is scoped to an OVER group, which is exactly whether it carries one.

    The rule had five homes -- `aggregate_key`, both places `parse_select_clause` and
    `_parse_aggregate_condition` file an aggregate into `global_scope` or `group_specific`, and the
    SELECT/HAVING merge -- each spelling `"group" in aggregate` and each unable to tell mypy what it
    had just decided. One home now, and the `TypeGuard` makes the decision visible to the checker
    rather than only to a reader.

    mypy cannot narrow a union of TypedDicts on an `in` check at all, whether the members are
    disjoint or one extends the other, which is why this is a function and not the inline test it
    looks like it could be.
    """
    return "group" in aggregate


def aggregate_key(aggregate: GlobalAggregate | GroupAggregate) -> str:
    """How an aggregate is spelled as a key: the parts it has, joined by dots.

    That is `column.function` or `group.column.function`, and for the bare row count, which has no
    column, `count` or `group.count`.

    The parser writes these into `select_items_in_order`, `GroupedRow` keys its data map by them and
    the HAVING evaluator looks one up, so all three have to agree exactly or a projected column
    silently comes back empty. It used to be three f-strings that happened to match, which held only
    because the whole query was lowercased before parsing; now that identifiers carry the frame's
    spelling, they have to be built from the same parts by the same code.
    """
    parts = [aggregate["group"]] if is_group_aggregate(aggregate) else []
    if aggregate["column"] is not None:
        parts.append(aggregate["column"])
    parts.append(aggregate["function"])
    return ".".join(parts)


class LogicalOperator(Enum):
    AND = "and"
    OR = "or"
    NOT = "not"


class EntryValue(TypedDict):
    """The value a grouping attribute holds in the output row being computed, offset by `delta`.

    This is what makes a query EMF (Extended Multi-Feature) rather than MF: a SUCH THAT condition
    written against one of these asks a different question of each output row, so
    `prev.month = month - 1` scopes group `prev` to the month before whichever month the row in
    hand is for, rather than to a fixed month. `delta` is 0 for a bare reference like
    `prev.cust = cust`.

    The rows that satisfy such a condition belong to a *different* grouping combination than the
    row being computed, which is why execution binds this to a literal per output row
    (`algorithms._bind_entry_values`) rather than evaluating it against the row in hand. Nothing
    downstream of that binding sees this shape.
    """

    attribute: str
    delta: float


class SortTerm(TypedDict):
    """One key of the output sort: a SELECT term, and which way to run it.

    `term` is a projected label, so it is the key a projected row is already indexed by, whether it
    names a grouping attribute (`song`) or an aggregate (`position.count`, `g1.quant.sum`). That is
    what lets execution sort by an aggregate at all: by the time the sort runs, an aggregate is just
    another column of the row.

    The integer form (`ORDER BY 2`) parses into a list of these rather than staying a number, so
    there is one thing to sort by and one place that knows what descending means.
    """

    term: str
    descending: bool


class SimpleCondition(TypedDict):
    column: str
    operator: str
    value: float | bool | str | date | EntryValue
    is_emf: bool  # Whether `value` is an EntryValue rather than a literal.


class CompoundCondition(TypedDict):
    operator: Literal[LogicalOperator.AND, LogicalOperator.OR]
    conditions: list["ParsedWhereClause"]


class NotCondition(TypedDict):
    operator: Literal[LogicalOperator.NOT]
    condition: "ParsedWhereClause"


class SemiJoinCondition(TypedDict):
    """`<key> HAS <condition>`: keep rows whose `key` value belongs to some row satisfying `condition`.

    Unlike every other condition here this one is not a question about the row in hand, so the
    execution side resolves it against the whole table before the per-row pass (see
    `algorithms._resolve_semi_joins`).
    """

    key: str
    operator: Literal["HAS"]
    condition: "ParsedWhereClause"


class SimpleGroupCondition(SimpleCondition):
    """A `SimpleCondition` that also names the OVER group it scopes.

    The one real subtype among the group conditions, and the only one written as inheritance: it
    adds a key rather than restating one, so a SUCH THAT leaf *is* a where-clause leaf and
    `_evaluate_condition` reads it with the same code by inheriting, not by coincidence.
    """

    group: str


class CompoundGroupCondition(TypedDict):
    """AND/OR over SUCH THAT sections. The same *shape* as `CompoundCondition`, not a subtype of it.

    It used to inherit `CompoundCondition` and redeclare `conditions`, which TypedDict forbids for a
    reason: a `CompoundGroupCondition` is not usable everywhere a `CompoundCondition` is, because
    its children are group conditions. That claim cost 3 `[misc]` errors and most of the 17
    `[typeddict-item]` ones, and it was also *wrong about the level*: the redeclaration read
    `list[ParsedSuchThatClause]`, a list of *lists* of sections, while `_parse_such_that_section`
    has always put sections here. Nothing caught it because nothing checked it.

    What the two hierarchies actually share is that `_evaluate_condition` walks either one -- see
    `ParsedCondition` below, which is where that is now written down.
    """

    operator: Literal[LogicalOperator.AND, LogicalOperator.OR]
    conditions: list["ParsedSuchThatSection"]


class NotGroupCondition(TypedDict):
    """NOT over a SUCH THAT section. Standalone for the same reason as `CompoundGroupCondition`."""

    operator: Literal[LogicalOperator.NOT]
    condition: "ParsedSuchThatSection"


class GlobalAggregateCondition(TypedDict):
    aggregate: GlobalAggregate
    operator: str
    value: float


class GroupAggregateCondition(TypedDict):
    """A HAVING comparison against a group-scoped aggregate.

    Standalone rather than inheriting `GlobalAggregateCondition` and narrowing `aggregate`, which is
    the same forbidden override as above. The aggregates themselves *do* inherit
    (`GroupAggregate(GlobalAggregate)`), because that one adds a key instead of replacing one.
    """

    aggregate: GroupAggregate
    operator: str
    value: float


class CompoundAggregateCondition(TypedDict):
    operator: Literal[LogicalOperator.AND, LogicalOperator.OR]
    conditions: list["ParsedHavingClause"]


class NotAggregateCondition(TypedDict):
    operator: Literal[LogicalOperator.NOT]
    condition: "ParsedHavingClause"


class ParsedSelectClause(TypedDict):
    grouping_attributes: list[str]
    aggregates: AggregatesDict
    select_items_in_order: list[str]


ParsedWhereClause = SimpleCondition | CompoundCondition | NotCondition | SemiJoinCondition

ParsedSuchThatSection = SimpleGroupCondition | CompoundGroupCondition | NotGroupCondition
ParsedSuchThatClause = list[ParsedSuchThatSection]

ParsedCondition = ParsedWhereClause | ParsedSuchThatSection
"""Any condition tree `algorithms._evaluate_condition` walks: a WHERE clause, or one SUCH THAT
section.

This is the property the two hierarchies above really share, and it is a property of the
*evaluator*, not a subtype relationship between the shapes. Both are built from the same three
node kinds -- a leaf comparing a column, AND/OR over children, NOT over one child -- so one walk
answers either, which is why `_evaluate_condition` serves the WHERE filter and every SUCH THAT
section with one function.

Written here so that interchangeability is checked rather than assumed. It used to be asserted by
`CompoundGroupCondition` inheriting `CompoundCondition`, which claimed something stronger and
false, and hidden by `_evaluate_condition` taking a bare `dict`, which claimed nothing at all.
"""

ParsedHavingClause = (
    GlobalAggregateCondition | GroupAggregateCondition | CompoundAggregateCondition | NotAggregateCondition
)


class ParsedQuery(TypedDict):
    data: pd.DataFrame
    select: ParsedSelectClause
    over: list[str] | None
    where: ParsedWhereClause | None
    such_that: ParsedSuchThatClause | None
    having: ParsedHavingClause | None
    order_by: list[SortTerm]
    aggregates: AggregatesDict
