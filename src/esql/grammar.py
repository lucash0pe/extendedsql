"""A machine-readable description of the ESQL grammar, for consumers that render it.

The token sets in `parser/util.py` say *what* the tokens are. This says what each clause does with
them: which slot kinds it accepts, which operators are legal in it, what it requires to be present,
and whether it repeats. A completion menu needs the second kind to answer "what can go here", and
until now the only copy of it lived hand-written in the demo front-end, in another repo, where a
rule added to the parser went unreflected and nothing failed.

Everything here is plain dicts, lists and strings, so `json.dumps(GRAMMAR)` is the whole export
step. The token sets are read from the parser rather than repeated, and every behavioral claim the
description makes is asserted against the real parser in `tests/parser/test_grammar.py`. That test
is what keeps this honest: it is a description, not the implementation, so drift is caught by
exercising the parser rather than by hoping the two stay in step.
"""

from esql.parser.types import LogicalOperator
from esql.parser.util import (
    AGGREGATE_FUNCTIONS,
    CONDITIONAL_OPERATORS,
    DTYPE_AGNOSTIC_AGGREGATE_FUNCTIONS,
    DTYPE_FAMILIES,
    HAVING_OPERATORS,
    KEYWORDS,
    NUMERIC_AGGREGATE_FUNCTIONS,
    OPERATOR_DTYPES,
    QUOTE_CHARACTERS,
    QUOTE_ESCAPE,
    SEMI_JOIN_OPERATOR,
    SUCH_THAT_OPERATORS,
    TEXT_OPERATORS,
    WHERE_OPERATORS,
)

# What can occupy a slot. A clause's "accepts" entry names kinds from here.
SLOT_KINDS = {
    "column": "A column of the queried DataFrame.",
    "aggregate": "`column.function`, or `group.column.function` for a group declared in OVER.",
    "group_name": "A group declared in OVER. Must match [A-Za-z0-9_]+.",
    "condition": "A comparison or semi-join, combinable with AND, OR, NOT and parentheses.",
    "group_condition": "A condition whose every column is prefixed with its group name.",
    "entry_value": (
        "In place of a literal on the right of a group condition: a SELECT grouping attribute, "
        "optionally offset by a number (`month - 1`). It stands for the value the grouped row "
        "being computed holds for that attribute, so the condition scopes the group per output "
        "row rather than to a constant."
    ),
    "aggregate_condition": "An aggregate compared against a number.",
    "sort_term": (
        "A SELECT term to sort the output by, either a grouping attribute or an aggregate, "
        "optionally prefixed with `-` to sort it descending. A term must be one the query "
        "projects, since the sort runs over the returned rows."
    ),
    "grouping_attribute_index": (
        "Shorthand for a sort term list: a count N of the SELECT grouping attributes, meaning sort "
        "by the first N of them in the order SELECT declares them. It is *first N*, not the Nth, so "
        "`2` sorts by the first attribute and then the second. Negative runs them all descending. "
        "This cannot reach an aggregate at any value, which is what `sort_term` is for."
    ),
}

CLAUSES = {
    "SELECT": {
        "required": True,
        "requires": [],
        "separator": ",",
        "accepts": ["column", "aggregate"],
        "operators": [],
        "summary": (
            "Projection. Every plain column is a grouping attribute, and at least one is required, "
            "so a query of only aggregates is rejected."
        ),
    },
    "OVER": {
        "required": False,
        "requires": [],
        "separator": ",",
        "accepts": ["group_name"],
        "operators": [],
        "summary": "Declares the group names that group-specific aggregates and SUCH THAT sections use.",
    },
    "WHERE": {
        "required": False,
        "requires": [],
        "separator": None,
        "accepts": ["condition"],
        "operators": list(WHERE_OPERATORS),
        "summary": "Filters rows before grouping. The only clause that accepts the HAS semi-join.",
    },
    "SUCH THAT": {
        "required": False,
        "requires": ["OVER"],
        "separator": ",",
        "accepts": ["group_condition", "entry_value"],
        "operators": list(SUCH_THAT_OPERATORS),
        "summary": (
            "One section per group, each scoping which rows feed that group's aggregates. A group "
            "may appear in only one section. The only clause that takes an entry value, which is "
            "what makes a query EMF rather than MF."
        ),
    },
    "HAVING": {
        "required": False,
        "requires": [],
        "separator": None,
        "accepts": ["aggregate_condition"],
        "operators": list(HAVING_OPERATORS),
        "summary": "Filters grouped rows by comparing an aggregate against a number.",
    },
    "ORDER BY": {
        "required": False,
        "requires": [],
        "separator": ",",
        "accepts": ["sort_term", "grouping_attribute_index"],
        "operators": [],
        "summary": (
            "Sorts the output by a list of SELECT terms, outermost first, each optionally prefixed "
            "with `-` for descending. A bare number is shorthand for the first N grouping "
            "attributes. Omitted, the row order is unspecified."
        ),
    },
}

# How a value is written. Only text needs a rule beyond "write it down": it is delimited, so it
# needs a way to hold its own delimiter. A host that offers completions has to know this to quote
# what it inserts, and hand-mirroring it is what J4 cost, so it is published rather than described.
LITERALS = {
    "text": {
        "delimiters": list(QUOTE_CHARACTERS),
        "escape": QUOTE_ESCAPE,
        "summary": (
            "A text value sits between a matched pair of ' or \". Either delimiter holds the other "
            "as ordinary text, and holds itself by being written twice. Only the delimiter in use "
            "is doubled: 'It''s' and \"It's\" both denote It's, while \"It''s\" denotes It''s, "
            "because inside \" an apostrophe is already ordinary text. A literal left unterminated "
            "is rejected rather than guessed at."
        ),
    },
}

GRAMMAR = {
    # Also the order a query must write them in.
    "keywords": list(KEYWORDS),
    "clauses": CLAUSES,
    "slot_kinds": SLOT_KINDS,
    "literals": LITERALS,
    "aggregates": {
        "functions": list(AGGREGATE_FUNCTIONS),
        "forms": ["column.function", "group.column.function"],
        "numeric_only": list(NUMERIC_AGGREGATE_FUNCTIONS),
        "any_dtype": list(DTYPE_AGNOSTIC_AGGREGATE_FUNCTIONS),
    },
    "operators": {
        "comparison": list(CONDITIONAL_OPERATORS),
        "text": list(TEXT_OPERATORS),
        "semi_join": SEMI_JOIN_OPERATOR,
        "logical": [op.value.upper() for op in LogicalOperator],
        # The second axis of operator legality, per G3. `clauses[c]["operators"]` says which
        # operators a clause takes; this says which column dtypes each operator applies to, and a
        # condition needs both. The keys of `dtypes` are the four families in `dtype_families`,
        # which are the same values a demo asset's `SchemaColumn.type` carries, so a host holding a
        # column's type can look up what may follow it. `_parse_condition_value` gates on this same
        # table, so it is the rule and not a description of one.
        "dtype_families": list(DTYPE_FAMILIES),
        "dtypes": {op: list(families) for op, families in OPERATOR_DTYPES.items()},
    },
}
