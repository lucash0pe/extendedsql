import re
from datetime import date, datetime

import numpy as np
import pandas as pd

from esql.parser.error import ParsingError, ParsingErrorType
from esql.parser.types import (
    AggregatesDict,
    CompoundAggregateCondition,
    CompoundCondition,
    CompoundGroupCondition,
    EntryValue,
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
    SemiJoinCondition,
    SimpleCondition,
    SimpleGroupCondition,
    SortTerm,
    aggregate_key,
)

###########################################################################
# Grammar
###########################################################################
# The token sets the parser accepts. They are the grammar's only definition: the parser reads
# them here, `public/docs/syntax.md` describes them in prose, and downstream docs (the portfolio
# ESQL demo) generate against them rather than restating them.

# The six clause keywords, in the order a query must write them.
KEYWORDS = ("SELECT", "OVER", "WHERE", "SUCH THAT", "HAVING", "ORDER BY")

# The aggregate functions, valid in whichever of `AGGREGATE_FORMS` below admits them.
AGGREGATE_FUNCTIONS = ("sum", "avg", "min", "max", "count")

# `column.count` asks how many distinct values a column holds, not what they are, so it is the one
# function that works on any dtype. `_parse_aggregate` reads this rather than naming `count` itself.
DTYPE_AGNOSTIC_AGGREGATE_FUNCTIONS = ("count",)

# The functions that may be written bare, with no column: `count` on its own is the group's row
# count, and `g1.count` is group `g1`'s. This is a different rule from the one above, which happens
# to name the same function: that one is about which dtypes a column takes, this one about needing
# no column at all. Nothing else can be written this way, because every other function has to be
# told what to add up.
#
# It exists because the alternative was worse. Without a bare form, a row count had to borrow a
# column (`city.count`), and under a clause that auto-groups that reads as "the cities, counted"
# while returning the row count -- a wrong answer the syntax invites. See `.claude/status.md`, H4.
BARE_AGGREGATE_FUNCTIONS = ("count",)
NUMERIC_AGGREGATE_FUNCTIONS = tuple(f for f in AGGREGATE_FUNCTIONS if f not in DTYPE_AGNOSTIC_AGGREGATE_FUNCTIONS)

# Every way an aggregate can be spelled, in the order `_parse_aggregate` tries them. The bare forms
# are written out literally rather than as `function`, because only the functions above take one and
# a pattern would promise `sum` works that way too. `GRAMMAR` publishes this list, and a host reading
# it decides whether a projected label is a measure by matching against these shapes.
AGGREGATE_FORMS = (
    *BARE_AGGREGATE_FUNCTIONS,
    *(f"group.{function}" for function in BARE_AGGREGATE_FUNCTIONS),
    "column.function",
    "group.column.function",
)

# Comparison operators valid in a condition. `==` is read as `=`.
CONDITIONAL_OPERATORS = ("CONTAINS", ">=", "<=", "!=", "==", ">", "<", "=")

# Operators that compare text rather than order it. `CONTAINS` is a case-insensitive substring
# test and is the one operator here that is a word rather than a symbol, so it matches only on
# word boundaries.
TEXT_OPERATORS = ("CONTAINS",)

# The four value families every column is coerced into (`accessor._enforce_allowed_dtypes`), and the
# vocabulary the dtype rules below are written in. Also what a demo asset's `SchemaColumn.type`
# carries, so a host reading `OPERATOR_DTYPES` is already holding the key to look up with.
DTYPE_FAMILIES = ("number", "date", "string", "boolean")

# Which families each comparison operator accepts. Legality has two axes: the clause (below) and the
# column's dtype, and this is the second. `_parse_condition_value` gates on this table before it
# coerces anything, so it is the rule rather than a description of it -- which is what lets `GRAMMAR`
# publish it. Ordering a text or boolean column is meaningless, and CONTAINS is a substring test, so
# it needs text.
OPERATOR_DTYPES = {
    "=": DTYPE_FAMILIES,
    "==": DTYPE_FAMILIES,
    "!=": DTYPE_FAMILIES,
    ">": ("number", "date"),
    ">=": ("number", "date"),
    "<": ("number", "date"),
    "<=": ("number", "date"),
    "CONTAINS": ("string",),
}

# The semi-join predicate. `<key> HAS <condition>` keeps rows whose `<key>` value belongs to some
# row satisfying `<condition>`, which is how a query reaches across grains without a join. It is
# not a comparison and so is not one of CONDITIONAL_OPERATORS: what follows it is a whole
# condition, not a value.
SEMI_JOIN_OPERATOR = "HAS"

# Which operators each clause accepts. WHERE filters raw rows, so it takes everything. SUCH THAT
# scopes a group and runs over the same rows, so it takes the comparisons but not the semi-join,
# which filters before grouping. HAVING compares an aggregate, and every aggregate is numeric, so
# it takes neither the text operators nor the semi-join.
WHERE_OPERATORS = (*CONDITIONAL_OPERATORS, SEMI_JOIN_OPERATOR)
SUCH_THAT_OPERATORS = CONDITIONAL_OPERATORS
HAVING_OPERATORS = tuple(op for op in CONDITIONAL_OPERATORS if op not in TEXT_OPERATORS)

# An entry value on the right of a comparison: a grouping attribute, optionally offset by a number
# (`month - 1`). Only SUCH THAT takes one, because only there is there an output row to read the
# value from. See `_parse_entry_value`.
ENTRY_VALUE_PATTERN = re.compile(r"^(\w+)(?:\s*([+-])\s*(\d+(?:\.\d+)?))?$")

# The delimiters a text value can be written in, and the escape for holding one as data.
QUOTE_CHARACTERS = ("'", '"')
QUOTE_ESCAPE = "doubling"

# A date value, inside its quotes. Comparing a date column takes a quoted literal like every other
# text value does, so the quoting is `_is_quoted`'s question and this describes only the contents.
DATE_PATTERN = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")


###########################################################################
# Identifier Resolution
###########################################################################
# ESQL identifiers are case-insensitive; a DataFrame's column names are not. Every column and group
# reference in a query therefore resolves through one of the two functions below, which answer with
# the *canonical* spelling - the frame's for a column, the OVER clause's for a group - and the
# parsed query carries that rather than what was typed. Execution indexes rows by the frame's
# spelling (`execute.column_indices`), so anything else puts the column out of reach.
#
# That is exactly what it was until v1.9.0: `_prepare_query` lowercased the whole query before the
# parser knew which words were identifiers, and resolution was a plain `in column_dtypes` against
# the frame's real keys, so a frame with a `Cust` column could not be queried in any spelling and
# the error blamed `'cust'`, a word the query never contained. See `.claude/status.md`, K1.


def dtype_family(dtype: np.dtype) -> str:
    """Which of `DTYPE_FAMILIES` a column's dtype belongs to.

    Reads an **enforced** dtype, which is the only kind the parser ever sees: the accessor coerces
    every column into one of four families before parsing (`accessor._enforce_allowed_dtypes`), and
    dates land as `datetime.date` objects, so object dtype means date. Bool is checked before number
    because pandas counts it as numeric and here it is its own family.

    Public because `demokit` needs the same answer for a demo asset's `SchemaColumn.type`, and two
    copies of this mapping would let the asset disagree with the parser about what a column is.
    """
    if pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if pd.api.types.is_numeric_dtype(dtype):
        return "number"
    if pd.api.types.is_object_dtype(dtype):
        return "date"
    return "string"


def _resolve_column(name: str, column_dtypes: dict[str, np.dtype], error_type: ParsingErrorType) -> str | None:
    """The frame's spelling of the column `name` names, or None when it names no column.

    None means "not a column", which several callers need as an answer rather than an error: it is
    how a bare word falls through to being read as a literal.

    An exact match wins before a case-folded one, so a frame holding both `Cust` and `cust` is still
    queryable by writing either exactly. Only a reference matching neither exactly and both when
    folded is ambiguous, and that raises rather than silently picking one.
    """
    if name in column_dtypes:
        return name
    matches = [column for column in column_dtypes if str(column).lower() == name.lower()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ParsingError(
            error_type,
            f"'{name}' matches more than one column ({', '.join(sorted(str(m) for m in matches))}), "
            f"so which one it means is ambiguous. Write one of them exactly.",
            token=name,
        )
    return None


def _resolve_group(name: str, groups: list[str]) -> str | None:
    """The OVER clause's spelling of the group `name` names, or None when it names no group.

    There is no ambiguous case to handle: `parse_over_clause` rejects two group names that differ
    only in case, so a folded name matches at most one declared group.
    """
    for group in groups:
        if group.lower() == name.lower():
            return group
    return None


def _names_group(text: str, group: str) -> bool:
    """Whether `text` opens with `<group>.`, case-insensitively.

    Case folding preserves length, so a caller that gets True can slice `len(group) + 1` characters
    off `text` to reach what follows the prefix.
    """
    return text[: len(group) + 1].lower() == f"{group}.".lower()


###########################################################################
# Keyword & Clause Extraction
###########################################################################
def get_keyword_clauses(query: str) -> dict[str, str | None]:
    keyword_clauses: dict[str, str | None] = dict.fromkeys(KEYWORDS)

    # Find the location of each keyword in the query. Searching the mask rather than the query
    # keeps a keyword that appears inside a text value from splitting the clause there: without
    # it, `WHERE song = 'order by me'` cuts an ORDER BY clause out of the middle of the literal.
    masked = mask_literals(query)

    keyword_indices = []
    for keyword in keyword_clauses:
        # Case-insensitively, since the query arrives spelled however it was written. Case folding
        # preserves length, so an index found here is that index into `query` too.
        pattern = r"\b" + re.escape(keyword.strip()) + r"\b"
        matches = list(re.finditer(pattern, masked, re.IGNORECASE))
        if matches:
            keyword_indices.append(matches[0].start())
        else:
            keyword_indices.append(-1)

    if keyword_indices[0] != 0:
        raise ParsingError(ParsingErrorType.SELECT_CLAUSE, "Every query must start with SELECT")

    # Extract clauses based on keyword positions.
    previous_index = 0
    keywords = list(keyword_clauses.keys())
    previous_keyword = keywords[0]
    for keyword, keyword_index in zip(keywords[1:], keyword_indices[1:], strict=False):
        if keyword_index == -1:
            continue
        if keyword_index < previous_index:
            raise ParsingError(
                ParsingErrorType.CLAUSE_ORDER, f"Unexpected position of '{keyword.strip().upper()}'", token=keyword
            )
        clause = query[previous_index + len(previous_keyword) : keyword_index].strip()
        if not clause:
            raise ParsingError(
                ParsingErrorType.MISSING_CLAUSE,
                f"No {previous_keyword.strip().upper()} argument found",
                token=previous_keyword,
            )
        keyword_clauses[previous_keyword] = clause
        previous_index = keyword_index
        previous_keyword = keyword

    clause = query[previous_index + len(previous_keyword) :].strip()
    if not clause:
        raise ParsingError(
            ParsingErrorType.MISSING_CLAUSE,
            f"No {previous_keyword.strip().upper()} argument found",
            token=previous_keyword,
        )
    keyword_clauses[previous_keyword] = clause

    return keyword_clauses


###########################################################################
# OVER Clause Parsing
###########################################################################
def parse_over_clause(over_clause: str | None) -> list[str]:
    groups = []
    # No OVER clause means no groups, not an absent group list. Returning None here made a
    # group-prefixed aggregate written without OVER (`SELECT x, g1.y.sum`) fail the `group not in
    # groups` membership test in _parse_aggregate with a TypeError instead of a ParsingError.
    if over_clause is None:
        return groups
    pattern = r"^[a-zA-Z0-9_]+$"
    for group in (group.strip() for group in over_clause.split(",")):
        match = re.match(pattern, group)
        if not match:
            raise ParsingError(ParsingErrorType.OVER_CLAUSE, f"Invalid group name: '{group}'", token=group)
        # Group names are case-insensitive like every other identifier, so two that differ only in
        # case name the same group twice and a reference to either could not be resolved to one of
        # them. This is what lets `_resolve_group` answer without an ambiguous case.
        if existing := _resolve_group(group, groups):
            raise ParsingError(
                ParsingErrorType.OVER_CLAUSE,
                f"Group '{group}' is already declared as '{existing}'; group names are "
                f"case-insensitive, so these name the same group.",
                token=group,
            )
        groups.append(group)
    return groups


###########################################################################
# SELECT Clause Parsing
###########################################################################
def parse_select_clause(
    select_clause: str, groups: list[str], column_dtypes: dict[str, np.dtype]
) -> ParsedSelectClause:
    select_items_in_order = []
    grouping_attributes = []
    aggregates = AggregatesDict(global_scope=[], group_specific=[])

    for item in (s.strip() for s in select_clause.split(",")):
        # A dot means an aggregate, and so does a bare `count`. The bare form is read as the row
        # count even when the frame has a column of that name, which makes `count` a reserved word
        # in this position: the reading has to be the same for every frame, or the same query would
        # mean different things over different data. Such a column is still reachable everywhere
        # else, `count.count` and `WHERE count > 5` included.
        if "." in item or item.lower() in BARE_AGGREGATE_FUNCTIONS:
            aggregate_result = _parse_aggregate(
                aggregate=item, groups=groups, column_dtypes=column_dtypes, error_type=ParsingErrorType.SELECT_CLAUSE
            )
            if "group" in aggregate_result:
                aggregates["group_specific"].append(aggregate_result)
            else:
                aggregates["global_scope"].append(aggregate_result)
            # The canonical key rather than what was written: these are looked up in the grouped
            # row's data map, which is keyed the same way. See `types.aggregate_key`.
            select_items_in_order.append(aggregate_key(aggregate_result))
        else:
            column = _resolve_column(item, column_dtypes, ParsingErrorType.SELECT_CLAUSE)
            if column is None:
                # `SELECT cust, sum` is a function missing its column rather than a misspelled
                # column, and only one of those two mistakes is worth pointing at. `count` never
                # reaches here, so this call always raises. Checked *after* resolution, which is
                # what keeps a column named `sum` projectable while `count` stays reserved.
                if item.lower() in AGGREGATE_FUNCTIONS:
                    _bare_function(item, item, ParsingErrorType.SELECT_CLAUSE)
                raise ParsingError(ParsingErrorType.SELECT_CLAUSE, f"Invalid column: '{item}'", token=item)
            grouping_attributes.append(column)
            select_items_in_order.append(column)
    if len(grouping_attributes) == 0:
        raise ParsingError(
            ParsingErrorType.SELECT_CLAUSE, f"No grouping attributes given: '{select_clause}'", token=select_clause
        )

    return ParsedSelectClause(
        grouping_attributes=grouping_attributes, aggregates=aggregates, select_items_in_order=select_items_in_order
    )


###########################################################################
# WHERE Clause Parsing
###########################################################################
def parse_where_clause(where_clause: str | None, column_dtypes: dict[str, np.dtype]) -> ParsedWhereClause | None:
    if where_clause is None:
        return None
    return _parse_where_clause(where_clause, column_dtypes)


def _parse_where_clause(where_clause: str, column_dtypes: dict[str, np.dtype]) -> ParsedWhereClause:
    where_clause = where_clause.strip()
    if _has_wrapping_parenthesis(where_clause):
        return _parse_where_clause(where_clause[1:-1].strip(), column_dtypes)

    or_conditions = _split_by_logical_operator(where_clause, LogicalOperator.OR)
    if len(or_conditions) > 1:
        return CompoundCondition(
            operator=LogicalOperator.OR, conditions=[_parse_where_clause(cond, column_dtypes) for cond in or_conditions]
        )

    and_conditions = _split_by_logical_operator(where_clause, LogicalOperator.AND)
    if len(and_conditions) > 1:
        return CompoundCondition(
            operator=LogicalOperator.AND,
            conditions=[_parse_where_clause(cond, column_dtypes) for cond in and_conditions],
        )

    if where_clause.lower().startswith(LogicalOperator.NOT.value.lower() + " "):
        condition = where_clause[len(LogicalOperator.NOT.value) + 1 :].strip()
        return NotCondition(operator=LogicalOperator.NOT, condition=_parse_where_clause(condition, column_dtypes))

    # After AND/OR, so `a HAS b = 1 AND c = 2` reads as `(a HAS b = 1) AND (c = 2)`. Parenthesize
    # to pull a compound condition inside the HAS instead.
    semi_join = _split_on_semi_join(where_clause)
    if semi_join:
        return _parse_semi_join_condition(*semi_join, condition=where_clause, column_dtypes=column_dtypes)

    return _parse_simple_condition(where_clause, column_dtypes)


def _parse_semi_join_condition(
    key: str, inner: str, condition: str, column_dtypes: dict[str, np.dtype]
) -> SemiJoinCondition:
    if not key:
        raise ParsingError(
            ParsingErrorType.WHERE_CLAUSE,
            f"{SEMI_JOIN_OPERATOR} needs a column before it: '{condition}'",
            token=condition,
        )
    resolved_key = _resolve_column(key, column_dtypes, ParsingErrorType.WHERE_CLAUSE)
    if resolved_key is None:
        raise ParsingError(ParsingErrorType.WHERE_CLAUSE, f"Invalid column: {key}", token=key)
    if not inner:
        raise ParsingError(
            ParsingErrorType.WHERE_CLAUSE,
            f"{SEMI_JOIN_OPERATOR} needs a condition after it: '{condition}'",
            token=condition,
        )
    return SemiJoinCondition(
        key=resolved_key, operator=SEMI_JOIN_OPERATOR, condition=_parse_where_clause(inner, column_dtypes)
    )


def _parse_simple_condition(condition: str, column_dtypes: dict[str, np.dtype]) -> SimpleCondition:
    condition = condition.strip()
    split = _split_condition(condition)
    if not split:
        bare = _resolve_column(condition, column_dtypes, ParsingErrorType.WHERE_CLAUSE)
        if bare is not None and pd.api.types.is_bool_dtype(column_dtypes[bare]):
            return SimpleCondition(column=bare, operator="=", value=True, is_emf=False)
        raise ParsingError(
            ParsingErrorType.WHERE_CLAUSE, f"No conditional operator found in condition: '{condition}'", token=condition
        )

    written_column, operator, value = split
    column = _resolve_column(written_column, column_dtypes, ParsingErrorType.WHERE_CLAUSE)
    if column is None:
        raise ParsingError(ParsingErrorType.WHERE_CLAUSE, f"Invalid column: {written_column}", token=written_column)
    if operator and value == "":
        raise ParsingError(ParsingErrorType.WHERE_CLAUSE, f"Missing value for condition: {condition}", token=condition)

    # An entry value reads the grouped row being computed, and WHERE runs before there are any, so
    # it is rejected here by name rather than falling through to "invalid value".
    entry_value = _parse_entry_value(value, column_dtypes, ParsingErrorType.WHERE_CLAUSE)
    if entry_value:
        raise ParsingError(
            ParsingErrorType.WHERE_CLAUSE,
            f"'{entry_value['attribute']}' is a column, and WHERE filters rows before they are "
            f"grouped, so there is no grouped row to read it from. An entry value belongs in "
            f"SUCH THAT: '{condition}'",
            token=condition,
        )

    parsed_value = _parse_condition_value(
        column_dtype=column_dtypes[column],
        operator=operator,
        value=value,
        condition=condition,
        error_type=ParsingErrorType.WHERE_CLAUSE,
    )

    return SimpleCondition(column=column, operator=operator, value=parsed_value, is_emf=False)


###########################################################################
# SUCH THAT Clause Parsing
###########################################################################
def parse_such_that_clause(
    such_that_clause: str | None,
    groups: list[str],
    column_dtypes: dict[str, np.dtype],
    grouping_attributes: list[str],
) -> ParsedSuchThatClause | None:
    if such_that_clause is None:
        return None
    parsed_such_that_clause = []
    such_that_sections = such_that_clause.split(",")
    for section in such_that_sections:
        parsed_such_that_clause.append(
            _parse_such_that_section(
                section=section,
                groups=groups,
                column_dtypes=column_dtypes,
                grouping_attributes=grouping_attributes,
            )
        )
    groups_in_parsed_clause = set()
    for section in parsed_such_that_clause:
        group = find_group_in_such_that_section(section)
        if group in groups_in_parsed_clause:
            raise ParsingError(
                ParsingErrorType.SUCH_THAT_CLAUSE, f"Multiple sections contain group '{group}'.", token=group
            )
        groups_in_parsed_clause.add(group)
    return parsed_such_that_clause


def find_group_in_such_that_section(group_condition: ParsedSuchThatSection):
    if not group_condition:
        raise ParsingError(ParsingErrorType.SUCH_THAT_CLAUSE, "No group found in group condition.")
    group = group_condition.get("group")
    if not group:
        return find_group_in_such_that_section(group_condition.get("condition") or group_condition.get("conditions")[0])
    return group


def _parse_such_that_section(
    section: str, groups: list[str], column_dtypes: dict[str, np.dtype], grouping_attributes: list[str]
) -> ParsedSuchThatSection:
    section = section.strip()
    if _has_wrapping_parenthesis(section):
        return _parse_such_that_section(section[1:-1].strip(), groups, column_dtypes, grouping_attributes)

    or_conditions = _split_by_logical_operator(section, LogicalOperator.OR)
    if len(or_conditions) > 1:
        parsed_or_conditions = [
            _parse_such_that_section(cond, groups, column_dtypes, grouping_attributes) for cond in or_conditions
        ]
        groups_found = {groupCondition["group"] for groupCondition in parsed_or_conditions if "group" in groupCondition}
        if len(groups_found) != 1:
            raise ParsingError(
                ParsingErrorType.SUCH_THAT_CLAUSE,
                f"Multiple groups found in a clause: '{section}'\n"
                "Each comma separated clause must contain only one group.",
                token=section,
            )
        return CompoundGroupCondition(operator=LogicalOperator.OR, conditions=parsed_or_conditions)

    and_conditions = _split_by_logical_operator(section, LogicalOperator.AND)
    if len(and_conditions) > 1:
        parsed_and_conditions = [
            _parse_such_that_section(cond, groups, column_dtypes, grouping_attributes) for cond in and_conditions
        ]
        groups_found = {
            groupCondition["group"] for groupCondition in parsed_and_conditions if "group" in groupCondition
        }
        if len(groups_found) != 1:
            raise ParsingError(
                ParsingErrorType.SUCH_THAT_CLAUSE,
                f"Multiple groups found in a clause: '{section}'\n"
                "Each comma separated clause must contain only one group.",
                token=section,
            )
        return CompoundGroupCondition(operator=LogicalOperator.AND, conditions=parsed_and_conditions)

    if section.lower().startswith(LogicalOperator.NOT.value.lower() + " "):
        condition = section[len(LogicalOperator.NOT.value) + 1 :].strip()
        return NotGroupCondition(
            operator=LogicalOperator.NOT,
            condition=_parse_such_that_section(condition, groups, column_dtypes, grouping_attributes),
        )

    group_found = None
    for group in groups:
        if _names_group(section, group):
            group_found = group
            break
    if not group_found:
        raise ParsingError(
            ParsingErrorType.SUCH_THAT_CLAUSE, f"No valid group found in condition: '{section}'", token=section
        )

    if any(f"{other}.".lower() in section.lower() for other in groups if other != group_found):
        raise ParsingError(
            ParsingErrorType.SUCH_THAT_CLAUSE,
            f"Multiple groups found in a clause: '{section}'\nEach comma separated clause must contain only one group.",
            token=section,
        )

    return _parse_simple_group_condition(section, group_found, column_dtypes, grouping_attributes)


def _parse_simple_group_condition(
    condition: str, group: str, column_dtypes: dict[str, np.dtype], grouping_attributes: list[str]
) -> SimpleGroupCondition:
    condition = condition.strip()
    if _split_on_semi_join(condition):
        raise ParsingError(
            ParsingErrorType.SUCH_THAT_CLAUSE,
            f"{SEMI_JOIN_OPERATOR} filters rows before grouping, so it belongs in WHERE, "
            f"not SUCH THAT: '{condition}'",
            token=condition,
        )
    split = _split_condition(condition)
    if not split:
        if _names_group(condition, group):
            written_column = condition[len(group) + 1 :].strip()
            bare = _resolve_column(written_column, column_dtypes, ParsingErrorType.SUCH_THAT_CLAUSE)
            if bare is not None and pd.api.types.is_bool_dtype(column_dtypes[bare]):
                return SimpleGroupCondition(group=group, column=bare, operator="=", value=True, is_emf=False)
        raise ParsingError(ParsingErrorType.SUCH_THAT_CLAUSE, f"Invalid condition: '{condition}'", token=condition)

    left, operator, value = split
    if not _names_group(left, group):
        raise ParsingError(
            ParsingErrorType.SUCH_THAT_CLAUSE, f"Invalid group for condition: '{condition}'", token=condition
        )
    written_column = left[len(group) + 1 :]
    column = _resolve_column(written_column, column_dtypes, ParsingErrorType.SUCH_THAT_CLAUSE)
    if column is None:
        raise ParsingError(
            ParsingErrorType.SUCH_THAT_CLAUSE, f"Invalid column: '{written_column}'", token=written_column
        )
    if operator and value == "":
        raise ParsingError(
            ParsingErrorType.SUCH_THAT_CLAUSE, f"Missing value for condition: {condition}", token=condition
        )

    # An entry value makes this an EMF condition: what it compares against is not known until
    # execution reaches an output row, so parsing stops at the reference and validates it.
    entry_value = _parse_entry_value(value, column_dtypes, ParsingErrorType.SUCH_THAT_CLAUSE)
    if entry_value:
        _validate_entry_value(
            entry_value=entry_value,
            column=column,
            grouping_attributes=grouping_attributes,
            column_dtypes=column_dtypes,
            condition=condition,
        )
        return SimpleGroupCondition(group=group, column=column, operator=operator, value=entry_value, is_emf=True)

    parsed_value = _parse_condition_value(
        column_dtype=column_dtypes[column],
        operator=operator,
        value=value,
        condition=condition,
        error_type=ParsingErrorType.SUCH_THAT_CLAUSE,
    )

    return SimpleGroupCondition(group=group, column=column, operator=operator, value=parsed_value, is_emf=False)


###########################################################################
# HAVING Clause Parsing
###########################################################################
def parse_having_clause(
    having_clause: str | None, groups: list[str], column_dtypes: dict[str, np.dtype]
) -> tuple[ParsedHavingClause | None, AggregatesDict]:
    aggregates = AggregatesDict(global_scope=[], group_specific=[])
    if having_clause is None:
        return (None, aggregates)
    return _parse_having_clause(
        having_clause=having_clause, aggregates=aggregates, groups=groups, column_dtypes=column_dtypes
    )


def _parse_having_clause(
    having_clause: str, aggregates: AggregatesDict, groups: list[str], column_dtypes: dict[str, np.dtype]
) -> tuple[ParsedHavingClause, AggregatesDict]:
    having_clause = having_clause.strip()
    if _has_wrapping_parenthesis(having_clause):
        return _parse_having_clause(having_clause[1:-1].strip(), aggregates, groups, column_dtypes)

    or_conditions = _split_by_logical_operator(having_clause, LogicalOperator.OR)
    if len(or_conditions) > 1:
        conditions = []
        for condition in or_conditions:
            cond, aggregates = _parse_having_clause(condition, aggregates, groups, column_dtypes)
            conditions.append(cond)
        return (CompoundAggregateCondition(operator=LogicalOperator.OR, conditions=conditions), aggregates)

    and_conditions = _split_by_logical_operator(having_clause, LogicalOperator.AND)
    if len(and_conditions) > 1:
        conditions = []
        for condition in and_conditions:
            cond, aggregates = _parse_having_clause(condition, aggregates, groups, column_dtypes)
            conditions.append(cond)
        return (CompoundAggregateCondition(operator=LogicalOperator.AND, conditions=conditions), aggregates)

    if having_clause.lower().startswith(LogicalOperator.NOT.value.lower() + " "):
        having_clause = having_clause[len(LogicalOperator.NOT.value) + 1 :].strip()
        condition, aggregates = _parse_having_clause(having_clause, aggregates, groups, column_dtypes)
        return (NotAggregateCondition(operator=LogicalOperator.NOT, condition=condition), aggregates)

    return _parse_aggregate_condition(having_clause, aggregates, groups, column_dtypes)


def _parse_aggregate_condition(
    condition: str, aggregates: AggregatesDict, groups: list[str], column_dtypes: dict[str, np.dtype]
) -> tuple[GroupAggregateCondition | GlobalAggregateCondition, AggregatesDict]:
    condition = condition.strip()
    split = _split_condition(condition)
    if not split:
        raise ParsingError(
            ParsingErrorType.HAVING_CLAUSE,
            f"No conditional operator found in condition: '{condition}'",
            token=condition,
        )
    left, operator, right = split
    if operator == "CONTAINS":
        raise ParsingError(
            ParsingErrorType.HAVING_CLAUSE,
            f"CONTAINS compares text and HAVING compares an aggregate, which is numeric: '{condition}'",
            token=condition,
        )
    if _split_on_semi_join(condition):
        raise ParsingError(
            ParsingErrorType.HAVING_CLAUSE,
            f"{SEMI_JOIN_OPERATOR} filters rows, so it belongs in WHERE, not HAVING: '{condition}'",
            token=condition,
        )
    aggregate: GlobalAggregate | GroupAggregate = _parse_aggregate(
        aggregate=left, groups=groups, column_dtypes=column_dtypes, error_type=ParsingErrorType.HAVING_CLAUSE
    )

    try:
        numeric_value = float(right)
    except ValueError:
        raise ParsingError(
            ParsingErrorType.HAVING_CLAUSE, f"Invalid value for condition: {condition}", token=condition
        ) from None

    if "group" in aggregate:
        if aggregate not in aggregates["group_specific"]:
            aggregates["group_specific"].append(aggregate)
        return (GroupAggregateCondition(aggregate=aggregate, operator=operator, value=numeric_value), aggregates)
    if aggregate not in aggregates["global_scope"]:
        aggregates["global_scope"].append(aggregate)
    return (GlobalAggregateCondition(aggregate=aggregate, operator=operator, value=numeric_value), aggregates)


###########################################################################
# ORDER BY Clause Parsing
###########################################################################
def parse_order_by_clause(
    order_by_clause: str | None, grouping_attributes: list[str], select_items_in_order: list[str]
) -> list[SortTerm]:
    """Read ORDER BY as the list of keys the output is sorted by, outermost first.

    Two spellings, one result. A **term list** names SELECT terms and is the general form:
    `ORDER BY -position.count, song` sorts by the count descending, then by song. An **integer** is
    shorthand for the first N grouping attributes, which is what ESQL had before terms existed:
    `ORDER BY 2` is `ORDER BY <first>, <second>` and a negative runs them all descending. The
    integer parses into the same list, so nothing downstream knows there are two spellings.

    A term has to be something SELECT projects, because the sort runs over projected rows and a
    column that was never projected holds no value there. That is stricter than SQL, where ORDER BY
    can reach a column the query does not return, and it is forced by grouping: a column that is
    neither grouped on nor aggregated has no single value per output row to sort by.
    """
    if order_by_clause is None:
        return []
    written = order_by_clause.strip()
    if not written:
        return []

    index = _as_integer(written)
    if index is not None:
        return _sort_terms_from_index(index, written, grouping_attributes)

    terms = []
    for part in written.split(","):
        written_term = part.strip()
        descending = written_term.startswith("-")
        if descending:
            written_term = written_term[1:].strip()
        if not written_term:
            raise ParsingError(
                ParsingErrorType.ORDER_BY_CLAUSE, f"Empty sort term in: '{written}'", token=order_by_clause
            )
        terms.append(SortTerm(term=_resolve_sort_term(written_term, select_items_in_order), descending=descending))
    return terms


def _as_integer(written: str) -> int | None:
    """`written` as an int, or None when it is not one. None means "read it as a term list"."""
    try:
        return int(written)
    except ValueError:
        return None


def _sort_terms_from_index(index: int, written: str, grouping_attributes: list[str]) -> list[SortTerm]:
    """The integer shorthand: the first `|index|` grouping attributes, descending if it is negative.

    Note this is *first N*, not *the Nth*. `ORDER BY 2` sorts by the first grouping attribute and
    then by the second, which is why it cannot reach an aggregate however far it is extended: the
    sort it describes always begins at the first grouping attribute. That is what the term list is
    for, and why widening this number was not the fix.
    """
    if abs(index) > len(grouping_attributes):
        raise ParsingError(
            ParsingErrorType.ORDER_BY_CLAUSE,
            f"{written} out of range of the {len(grouping_attributes)} "
            "grouping attributes provided in the select clause.",
            token=written,
        )
    return [SortTerm(term=attribute, descending=index < 0) for attribute in grouping_attributes[: abs(index)]]


def _resolve_sort_term(written_term: str, select_items_in_order: list[str]) -> str:
    """The projected label `written_term` names, case-insensitively, or a ParsingError naming what is
    available. Sorting by something the query does not return is a mistake worth reporting with the
    list of what it could have meant, since the terms are right there in the query."""
    if written_term in select_items_in_order:
        return written_term
    matches = [item for item in select_items_in_order if item.lower() == written_term.lower()]
    if len(matches) == 1:
        return matches[0]
    raise ParsingError(
        ParsingErrorType.ORDER_BY_CLAUSE,
        f"'{written_term}' is not a SELECT term, so there is nothing to sort by. "
        f"Available: {', '.join(select_items_in_order)}.",
        token=written_term,
    )


###########################################################################
# Aggregate and Value Parsing
###########################################################################
def _parse_aggregate(
    aggregate: str,
    groups: list[str],
    column_dtypes: dict[str, np.dtype],
    error_type: ParsingErrorType,
) -> GlobalAggregate | GroupAggregate:
    """Read one aggregate in any of its four forms.

    `count` and `group.count` name no column: they are the row count, and the function has to be one
    of `BARE_AGGREGATE_FUNCTIONS`. `column.function` and `group.column.function` name one, and it has
    to exist and to suit the function's dtype rule.
    """
    parts = aggregate.split(".")

    # Format: count
    if len(parts) == 1:
        return GlobalAggregate(column=None, function=_bare_function(parts[0], aggregate, error_type))

    # Format: column.aggregate_function, or group.count
    if len(parts) == 2:
        written_left, written_function = parts
        # The bare form is checked first, so `g1.count` is group `g1`'s row count even when a column
        # is also called `g1`. The group is declared by the query itself, a few words earlier in
        # OVER, which makes it the more deliberate of the two readings.
        group = _resolve_group(written_left, groups)
        if group is not None and written_function.lower() in BARE_AGGREGATE_FUNCTIONS:
            return GroupAggregate(group=group, column=None, function=written_function.lower())
        column, func = _aggregate_column_and_function(
            written_column=written_left,
            written_function=written_function,
            aggregate=aggregate,
            column_dtypes=column_dtypes,
            error_type=error_type,
        )
        return GlobalAggregate(column=column, function=func)

    # Format: group.column.aggregate_function
    if len(parts) == 3:
        written_group, written_column, written_function = parts
        group = _resolve_group(written_group, groups)
        if group is None:
            raise ParsingError(error_type, f"Invalid aggregate group: '{aggregate}'", token=aggregate)
        column, func = _aggregate_column_and_function(
            written_column=written_column,
            written_function=written_function,
            aggregate=aggregate,
            column_dtypes=column_dtypes,
            error_type=error_type,
        )
        return GroupAggregate(group=group, column=column, function=func)

    raise ParsingError(
        error_type,
        f"Invalid aggregate: '{aggregate}'\n{_forms_sentence()}",
        token=aggregate,
    )


def _bare_function(written_function: str, aggregate: str, error_type: ParsingErrorType) -> str:
    """The function a bare aggregate names, or a ParsingError saying what a bare one may be.

    Only `count` can stand alone, so anything else here is a function that was written without the
    column it needs. Saying which of the two mistakes it is beats "invalid aggregate": the writer of
    `SELECT cust, sum` meant a column and left it out.
    """
    func = written_function.lower()
    if func in BARE_AGGREGATE_FUNCTIONS:
        return func
    if func in AGGREGATE_FUNCTIONS:
        raise ParsingError(
            error_type,
            f"'{aggregate}' needs a column to aggregate: write 'column.{func}'. "
            f"Only {', '.join(BARE_AGGREGATE_FUNCTIONS)} can be written on its own, as the row count.",
            token=aggregate,
        )
    raise ParsingError(
        error_type,
        f"Invalid aggregate: '{aggregate}'\n{_forms_sentence()}",
        token=aggregate,
    )


def _forms_sentence() -> str:
    return "Aggregate must be in one of the forms: " + ", ".join(AGGREGATE_FORMS)


def _aggregate_column_and_function(
    written_column: str,
    written_function: str,
    aggregate: str,
    column_dtypes: dict[str, np.dtype],
    error_type: ParsingErrorType,
) -> tuple[str, str]:
    """The column and function of an aggregate that names a column, checked against each other."""
    column = _resolve_column(written_column, column_dtypes, error_type)
    func = written_function.lower()
    if column is None:
        raise ParsingError(error_type, f"Invalid aggregate column: '{aggregate}'", token=aggregate)
    if func not in AGGREGATE_FUNCTIONS:
        raise ParsingError(error_type, f"Invalid aggregate function: '{aggregate}'", token=aggregate)
    if func not in DTYPE_AGNOSTIC_AGGREGATE_FUNCTIONS and not (
        pd.api.types.is_any_real_numeric_dtype(column_dtypes[column])
    ):
        raise ParsingError(
            error_type, f"Invalid aggregate. Column is not a numeric type: '{aggregate}'", token=aggregate
        )
    return column, func


def _parse_condition_value(
    column_dtype: np.dtype,
    operator: str,
    value: str,
    condition: str,
    error_type: ParsingErrorType,
) -> float | bool | str | date:
    """Read the right side of a comparison as the typed value its column holds.

    Two gates, in this order. First the **dtype** gate, `OPERATOR_DTYPES`: whether this operator
    means anything against this family of column at all, which is a question about the operator and
    answerable before the value is looked at. Then the coercion below, which is whether *this* value
    can be read as that family. Splitting them is what lets `GRAMMAR` publish the first as a table
    (G3) instead of a host inferring it from which conditions happen to be refused.
    """
    value = value.strip()

    allowed_families = OPERATOR_DTYPES.get(operator)
    if allowed_families is None:
        raise ParsingError(error_type, f"Invalid operator in condition: '{condition}'", token=condition)

    family = dtype_family(column_dtype)
    if family not in allowed_families:
        raise ParsingError(
            error_type,
            f"'{operator}' does not apply to a {family} column in condition: '{condition}'",
            token=condition,
        )

    # CONTAINS is the one operator whose value is not read as the column's own family: it is a
    # substring of the text, so any quoted text will do.
    if operator == "CONTAINS":
        if not _is_quoted(value):
            raise ParsingError(
                error_type, f"CONTAINS needs a quoted text value in condition: '{condition}'", token=condition
            )
        return _unquote(value)

    # Everything else compares against a value of the column's own family, so the coercion is chosen
    # by the family and not by the operator. Ordering and equality used to have a chain each, and
    # both chains ended by asking pandas whether the dtype was numeric -- which is True for a bool
    # column, so `credit = 1` read 1 as the value and matched the true rows (K3).
    if family == "number":
        return _numeric_value(value, condition, error_type)
    if family == "date":
        return _date_value(value, condition, error_type)
    if family == "boolean":
        if value.lower() not in ["true", "false"]:
            raise ParsingError(
                error_type,
                f"A boolean column compares against true or false in condition: '{condition}'",
                token=condition,
            )
        return value.lower() == "true"
    if not _is_quoted(value):
        raise ParsingError(error_type, f"A text value must be quoted in condition: '{condition}'", token=condition)
    return _unquote(value)


def _numeric_value(value: str, condition: str, error_type: ParsingErrorType) -> float | int:
    try:
        number = float(value)
    except ValueError:
        raise ParsingError(error_type, f"Invalid value in condition: '{condition}'", token=condition) from None
    return int(number) if number.is_integer() else number


def _date_value(value: str, condition: str, error_type: ParsingErrorType) -> date:
    """A date value is a quoted `YYYY-MM-DD` (or `YYYY/MM/DD`), and nothing else is guessed at.

    Anything quoted used to reach a date column as *text*, because pandas reports the object dtype
    dates are stored as as a string dtype: `date = 'hello'` compared a string against date objects
    and returned nothing, while `date != 'hello'` returned everything. Both were answers to a
    question nobody asked (K3).
    """
    if not _is_quoted_date(value):
        raise ParsingError(error_type, f"Invalid date in condition: '{condition}'", token=condition)
    try:
        return datetime.strptime(_unquote(value).replace("/", "-"), "%Y-%m-%d").date()
    except ValueError:
        raise ParsingError(error_type, f"Invalid date in condition: '{condition}'", token=condition) from None


###########################################################################
# Entry Value Parsing
###########################################################################
def _parse_entry_value(
    value: str, column_dtypes: dict[str, np.dtype], error_type: ParsingErrorType
) -> EntryValue | None:
    """Read `value` as `<column>` or `<column> ± <number>`, or None when it is not that shape.

    None means "this is a literal, not a column reference", so a caller falls through to the
    literal parsing below. The column has to exist for the shape to count, which is what keeps a
    bare word like `true` a literal rather than a dangling reference.

    Whether an entry value is *legal* where it was written is the caller's question, not this
    one's: WHERE rejects it outright and SUCH THAT checks it with `_validate_entry_value`.
    """
    match = ENTRY_VALUE_PATTERN.match(value.strip())
    if not match:
        return None
    written_attribute, sign, offset = match.groups()
    attribute = _resolve_column(written_attribute, column_dtypes, error_type)
    if attribute is None:
        return None
    if offset is None:
        return EntryValue(attribute=attribute, delta=0)
    delta = float(offset)
    delta = int(delta) if delta.is_integer() else delta
    return EntryValue(attribute=attribute, delta=-delta if sign == "-" else delta)


def _validate_entry_value(
    entry_value: EntryValue,
    column: str,
    grouping_attributes: list[str],
    column_dtypes: dict[str, np.dtype],
    condition: str,
) -> None:
    """Raise unless `entry_value` names something the output row actually holds and can be compared
    against `column`."""
    attribute = entry_value["attribute"]
    if attribute not in grouping_attributes:
        raise ParsingError(
            ParsingErrorType.SUCH_THAT_CLAUSE,
            f"'{attribute}' is not a SELECT grouping attribute, so a grouped row holds no single "
            f"value for it: '{condition}'",
            token=condition,
        )

    attribute_kind = _dtype_kind(column_dtypes[attribute])
    column_kind = _dtype_kind(column_dtypes[column])
    if attribute_kind != column_kind:
        raise ParsingError(
            ParsingErrorType.SUCH_THAT_CLAUSE,
            f"Cannot compare {column_kind} column '{column}' against {attribute_kind} "
            f"attribute '{attribute}': '{condition}'",
            token=condition,
        )
    if entry_value["delta"] and column_kind != "numeric":
        raise ParsingError(
            ParsingErrorType.SUCH_THAT_CLAUSE,
            f"Only a numeric attribute can be offset, and '{attribute}' is {attribute_kind}: '{condition}'",
            token=condition,
        )


def _dtype_kind(column_dtype: np.dtype) -> str:
    """Which family of values a column holds: numeric, bool, date or text.

    The order matters and matches how `_parse_condition_value` discriminates a literal. A bool
    column reads as numeric if asked the other way round, and a date column is object dtype, which
    `is_string_dtype` also answers True to, so object is settled before text.
    """
    if pd.api.types.is_bool_dtype(column_dtype):
        return "bool"
    if pd.api.types.is_any_real_numeric_dtype(column_dtype):
        return "numeric"
    if pd.api.types.is_object_dtype(column_dtype):
        return "date"
    return "text"


###########################################################################
# String Literal Scanning
###########################################################################
# A text value is delimited by a matched pair of ' or ", and holds its own delimiter by doubling
# it: 'It''s' denotes the four characters It's. Both quote kinds delimit, so "It's" says the same
# thing without doubling, and doubling is what covers a value needing both kinds.
#
# Everything that needs to find structure in a query reads a *mask* rather than tracking quote
# state itself. `mask_literals` blanks each literal, delimiters and all, to a filler of the same
# length, so an index into the mask is that same index into the original: a caller finds its
# operator or keyword or parenthesis in the mask and slices the original. One rule, one home.
#
# It used to have seven: four `in_single`/`in_double` scanners, `_is_quoted` reading first and last
# character, a date pattern spelling its delimiters as `['\"]` independently at each end, and in
# `_prepare_query` a regex, `'[^']*'`, which is the one that disagreed with the rest. On
# `song = '(I'm A) Road Runner'` it read `'(I'` as the whole literal, so the rest of the value was
# treated as unquoted text and lowercased, and the query then matched nothing while raising
# nothing. `get_keyword_clauses` made the eighth case by having no notion of a literal at all.
# See `.claude/status.md`, J4.

LITERAL_FILLER = "\x00"


def literal_spans(text: str) -> list[tuple[int, int]]:
    """Where each string literal sits in `text`, as half-open (start, end) with delimiters included.

    Raises when a literal is opened and never closed. That case is genuinely ambiguous rather than
    merely unusual: a lone `'` could be a delimiter or a datum, and no counting rule tells the two
    apart (`a = 'He's' AND b = 'x'` and `a = 'He's Gone'` differ only in what the writer meant).
    Rejecting is the only honest answer, and it beats the alternative this replaced, which was to
    guess and return a confident empty result.
    """
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char not in QUOTE_CHARACTERS:
            index += 1
            continue
        end = _end_of_literal(text, index)
        if end is None:
            other = next(q for q in QUOTE_CHARACTERS if q != char)
            raise ParsingError(
                ParsingErrorType.STRING_LITERAL,
                f"Unterminated {char} string literal. "
                f"Write {char}{char} to hold a {char} in the text, or delimit the value with "
                f"{other} instead.",
            )
        spans.append((index, end))
        index = end
    return spans


def mask_literals(text: str) -> str:
    """`text` with every string literal blanked to filler, index for index.

    The filler only has to be something no scanner looks for, which is why callers read the mask
    for structure and never test it for content. `_prepare_query` wants the literals themselves
    rather than the gaps between them, so it reads `literal_spans` directly: inferring them back
    out of the mask would mistake a control character in the query for one.
    """
    masked = list(text)
    for start, end in literal_spans(text):
        masked[start:end] = LITERAL_FILLER * (end - start)
    return "".join(masked)


def _end_of_literal(text: str, start: int) -> int | None:
    """The index just past the literal opening at `start`, or None when it is never closed."""
    quote = text[start]
    index = start + 1
    while index < len(text):
        if text[index] != quote:
            index += 1
        elif index + 1 < len(text) and text[index + 1] == quote:
            index += 2  # a doubled delimiter is data, not the end
        else:
            return index + 1
    return None


def _unquote(value: str) -> str:
    """The text a quoted literal denotes: delimiters off, each doubled delimiter collapsed to one."""
    quote = value[0]
    return value[1:-1].replace(quote * 2, quote)


def _is_quoted_date(value: str) -> bool:
    """Whether `value` is one string literal holding a date."""
    return _is_quoted(value) and bool(DATE_PATTERN.match(_unquote(value)))


###########################################################################
# Clause Structure Helper Functions
###########################################################################
def _split_condition(condition: str) -> tuple[str, str, str] | None:
    masked = mask_literals(condition)

    for i in range(len(masked)):
        for op in sorted(CONDITIONAL_OPERATORS, key=len, reverse=True):
            if _operator_starts_at(masked, i, op):
                return condition[:i].strip(), op, condition[i + len(op) :].strip()

    return None


def _operator_starts_at(condition: str, index: int, operator: str) -> bool:
    """Whether `operator` occupies `condition` at `index`.

    A word operator (CONTAINS) has to sit on word boundaries, or a column named `contains_tax`
    would split as the operator. A symbol operator (>=) cannot collide that way and matches
    directly. The comparison folds case, which is where operator case-insensitivity lives now that
    `_prepare_query` no longer lowercases the query; callers get the canonical spelling back either
    way, since what is returned is the constant rather than the matched text.
    """
    candidate = condition[index : index + len(operator)]
    if not operator.isalpha():
        return candidate == operator
    if candidate.lower() != operator.lower():
        return False
    before = condition[index - 1] if index > 0 else " "
    after = condition[index + len(operator)] if index + len(operator) < len(condition) else " "
    return not _is_word_char(before) and not _is_word_char(after)


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _split_on_semi_join(condition: str) -> tuple[str, str] | None:
    """Split `<key> HAS <inner condition>` on the first top-level HAS, or None if there is none.

    Top level means outside quotes and outside parentheses. A HAS nested inside a parenthesized
    subexpression belongs to that subexpression and is found when the recursion reaches it, so
    `a HAS (b HAS c = 1)` splits on the outer one here and the inner one a level down.
    """
    masked = mask_literals(condition)
    depth = 0

    for i, char in enumerate(masked):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1

        if depth:
            continue
        if _operator_starts_at(masked, i, SEMI_JOIN_OPERATOR):
            return condition[:i].strip(), condition[i + len(SEMI_JOIN_OPERATOR) :].strip()

    return None


def _is_quoted(value: str) -> bool:
    """Whether `value` is exactly one string literal, delimiters included.

    Exactly one, not "starts and ends with a quote": `'a' 'b'` is two literals and answers False,
    where reading only the first and last character called it a single literal holding `a' 'b`.
    """
    return len(value) >= 2 and value[0] in QUOTE_CHARACTERS and _end_of_literal(value, 0) == len(value)


def _has_wrapping_parenthesis(condition: str) -> bool:
    condition = condition.strip()
    if not (condition.startswith("(") and condition.endswith(")")):
        return False

    masked = mask_literals(condition)
    paren_level = 0
    for i, char in enumerate(masked):
        if char == "(":
            paren_level += 1
        elif char == ")":
            paren_level -= 1

        if paren_level == 0 and i < len(masked) - 1:
            return False

    return paren_level == 0


def _split_by_logical_operator(condition: str, operator: LogicalOperator) -> list[str]:
    masked = mask_literals(condition)
    parts = []
    current = ""
    paren_level = 0
    i = 0

    while i < len(masked):
        char = masked[i]

        # Track parentheses. Any inside a literal are filler by now, so they do not count.
        if char == "(":
            paren_level += 1
        elif char == ")":
            paren_level -= 1

        # Check for the logical operator (e.g., AND, OR) when outside parens.
        if (
            paren_level == 0
            and char == " "
            and i + 1 + len(operator.value) <= len(masked)
            and masked[i + 1 : i + 1 + len(operator.value)].lower() == operator.value.lower()
            and (i + 1 + len(operator.value) == len(masked) or masked[i + 1 + len(operator.value)] in (" ", ")"))
        ):
            parts.append(current.strip())
            current = ""
            i += len(operator.value) + 1
        else:
            current += condition[i]
            i += 1

    if current.strip():
        parts.append(current.strip())
    return parts
