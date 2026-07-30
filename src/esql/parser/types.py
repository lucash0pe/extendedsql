from datetime import date
from enum import Enum
from typing import Literal, TypedDict

import pandas as pd


class GlobalAggregate(TypedDict):
    column: str
    function: str

    def __eq__(self, other):
        return self.column == other.column and self.function == other.function


class GroupAggregate(GlobalAggregate):
    group: str

    def __eq__(self, other):
        return self.group == other.group and self.column == other.column and self.function == other.function


class AggregatesDict(TypedDict):
    global_scope: list[GlobalAggregate]
    group_specific: list[GroupAggregate]


def aggregate_key(aggregate: GlobalAggregate | GroupAggregate) -> str:
    """How an aggregate is spelled as a key: `column.function`, or `group.column.function`.

    The parser writes these into `select_items_in_order`, `GroupedRow` keys its data map by them and
    the HAVING evaluator looks one up, so all three have to agree exactly or a projected column
    silently comes back empty. It used to be three f-strings that happened to match, which held only
    because the whole query was lowercased before parsing; now that identifiers carry the frame's
    spelling, they have to be built from the same parts by the same code.
    """
    if "group" in aggregate:
        return f"{aggregate['group']}.{aggregate['column']}.{aggregate['function']}"
    return f"{aggregate['column']}.{aggregate['function']}"


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
    group: str


class CompoundGroupCondition(CompoundCondition):
    conditions: list["ParsedSuchThatClause"]


class NotGroupCondition(NotCondition):
    condition: "ParsedSuchThatClause"


class GlobalAggregateCondition(TypedDict):
    aggregate: GlobalAggregate
    operator: str
    value: float


class GroupAggregateCondition(GlobalAggregateCondition):
    aggregate: GroupAggregate


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
    order_by: int
    aggregates: AggregatesDict
