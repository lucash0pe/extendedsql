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


class LogicalOperator(Enum):
    AND = "and"
    OR = "or"
    NOT = "not"


class SimpleCondition(TypedDict):
    column: str
    operator: str
    value: float | bool | str | date
    is_emf: bool  # EMF is when the comparison value is based on the entry value of the column.


class CompoundCondition(TypedDict):
    operator: Literal[LogicalOperator.AND, LogicalOperator.OR]
    conditions: list["ParsedWhereClause"]


class NotCondition(TypedDict):
    operator: Literal[LogicalOperator.NOT]
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


ParsedWhereClause = SimpleCondition | CompoundCondition | NotCondition

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
