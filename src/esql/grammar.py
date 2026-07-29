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
    HAVING_OPERATORS,
    KEYWORDS,
    NUMERIC_AGGREGATE_FUNCTIONS,
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
    "aggregate_condition": "An aggregate compared against a number.",
    "grouping_attribute_index": (
        "A 1-based index into the SELECT grouping attributes. Negative reverses the sort."
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
        "accepts": ["group_condition"],
        "operators": list(SUCH_THAT_OPERATORS),
        "summary": (
            "One section per group, each scoping which rows feed that group's aggregates. A group "
            "may appear in only one section."
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
        "separator": None,
        "accepts": ["grouping_attribute_index"],
        "operators": [],
        "summary": "Sorts by one of the SELECT grouping attributes, chosen by 1-based position.",
    },
}

GRAMMAR = {
    # Also the order a query must write them in.
    "keywords": list(KEYWORDS),
    "clauses": CLAUSES,
    "slot_kinds": SLOT_KINDS,
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
    },
}
