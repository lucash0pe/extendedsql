"""Assert `public/docs/syntax.md` against `GRAMMAR` (G2).

The doc is prose and stays prose: nothing here rewrites it, and it is free to explain, motivate and
give examples in whatever words suit. What it is not free to do is *restate a rule wrongly*, which
is what J5 cost when a `summary` string described an escape the parser does not implement, and what
G3 found when the front end offered `song >` because nothing published the dtype axis.

So the guard is scoped to claims, and a claim is marked as one. `<!-- grammar:operators WHERE -->`
in front of a paragraph says "the operators named here are WHERE's operators", and this file checks
that against the parser's own token sets. Prose with no marker is not checked, because a regex over
English produces false positives and a gate that cries wolf gets bypassed.

Two directions matter and they catch different mistakes:

- **What the doc claims must be legal.** A marked list offering an operator the clause rejects sends
  a reader to write a query that does not parse.
- **What is legal must be documented.** An operator added to a clause and never written down is the
  silent half, and the one no reader can report.

The second is deliberately looser about *where*: it asks that the operator appear somewhere in that
clause's section, because the doc legitimately introduces `==` and `HAS` in their own paragraphs
rather than in the list.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from esql.grammar import GRAMMAR
from esql.parser.util import (
    AGGREGATE_FUNCTIONS,
    KEYWORDS,
    OPERATOR_DTYPES,
    QUOTE_CHARACTERS,
    SEMI_JOIN_OPERATOR,
)

SYNTAX_DOC = Path(__file__).resolve().parent.parent / "public" / "docs" / "syntax.md"
DOC = SYNTAX_DOC.read_text()

ALL_OPERATORS = {*GRAMMAR["operators"]["comparison"], SEMI_JOIN_OPERATOR}
# The doc writes text as "text" where the engine's dtype family is "string". One rename, declared.
DOC_DTYPE_NAMES = {"number": "number", "date": "date", "string": "text", "boolean": "boolean"}


def _backticked(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", text)


def _marked_span(marker: str) -> str:
    """The block following `<!-- grammar:<marker> -->`, up to the next blank line.

    A marker claims exactly the block it sits in front of, which is what keeps the guard from
    reading the paragraph after it as part of the claim.
    """
    opening = f"<!-- grammar:{marker} -->"
    assert opening in DOC, f"{SYNTAX_DOC.name} no longer marks '{marker}'. A claim cannot go unguarded by deleting its marker."
    body = DOC.split(opening, 1)[1].lstrip("\n")
    return body.split("\n\n", 1)[0]


def _operator_claim(clause: str) -> tuple[set[str], set[str]]:
    """What `<!-- grammar:operators <clause> also:a,b -->` claims: the operators in the block it
    precedes, and the ones it declares are documented elsewhere in the section."""
    pattern = rf"<!-- grammar:operators {re.escape(clause)}(?: also:([^ ]+))? -->\n(.*?)(?:\n\n|$)"
    match = re.search(pattern, DOC, flags=re.DOTALL)
    assert match, f"{SYNTAX_DOC.name} no longer marks {clause}'s operators. A claim cannot go unguarded by deleting its marker."
    also = {token for token in (match.group(1) or "").split(",") if token}
    listed = {token for token in _backticked(match.group(2)) if token in ALL_OPERATORS}
    return listed, also


def _section(keyword: str) -> str:
    """One clause's whole section, subsections included."""
    heading = f"\n## {keyword}\n"
    assert heading in DOC, f"{SYNTAX_DOC.name} has no section for {keyword}"
    body = DOC.split(heading, 1)[1]
    return body.split("\n## ", 1)[0]


###############################################################################
# Structure
###############################################################################
def test_every_keyword_has_a_section_in_the_documented_order():
    headings = re.findall(r"^## (.+)$", DOC, flags=re.MULTILINE)
    clause_headings = [heading for heading in headings if heading in KEYWORDS]
    assert clause_headings == list(KEYWORDS)


def test_the_keyword_list_names_every_keyword_and_counts_them_right():
    span = _marked_span("keywords")
    assert _backticked(span) == list(KEYWORDS)
    assert f"has {len(KEYWORDS)} keywords" in span, "the count in the prose disagrees with KEYWORDS"


###############################################################################
# Operators, both directions
###############################################################################
@pytest.mark.parametrize("clause", ["WHERE", "SUCH THAT", "HAVING"])
def test_a_clause_documents_exactly_the_operators_it_accepts(clause: str):
    """Both directions at once, which is the only way that holds.

    The obvious looser check -- "every legal operator appears somewhere in the clause's section" --
    does not work, and testing it proved it: giving HAVING the `HAS` operator passed, because
    HAVING's section does mention `HAS`, in a sentence saying it is rejected. A mention that says
    the opposite still counts as a mention.

    So the marker carries the whole claim. The list it precedes is the claim, and `also:` names the
    operators documented elsewhere in the section, each of which still has to be found there. An
    operator that becomes legal is then undeclared until someone writes it down on purpose.
    """
    listed, also = _operator_claim(clause)
    assert listed, f"the marked list for {clause} names no operators"

    section = set(_backticked(_section(clause)))
    for operator in also:
        assert operator in section, f"{clause} declares `{operator}` documented elsewhere, and its section never writes it"

    assert listed | also == set(GRAMMAR["clauses"][clause]["operators"])


###############################################################################
# The tables that restate a published rule outright
###############################################################################
def test_the_operator_dtype_table_matches_the_rule_the_parser_enforces():
    """The newest hand-written mirror, and the one with the most to get wrong: four rows and three
    columns of yes/no that `OPERATOR_DTYPES` already answers."""
    rows = [row for row in _marked_span("operator-dtypes").splitlines() if row.startswith("|")]
    header, _separator, *body = rows
    column_operators = [_backticked(cell) for cell in header.split("|")[2:-1]]
    assert column_operators, "the dtype table has no operator columns"

    documented: dict[str, set[str]] = {operator: set() for group in column_operators for operator in group}
    for row in body:
        cells = [cell.strip() for cell in row.split("|")[1:-1]]
        family = cells[0]
        for group, verdict in zip(column_operators, cells[1:], strict=True):
            assert verdict in ("yes", "no"), f"unreadable verdict {verdict!r} for {family}"
            if verdict == "yes":
                for operator in group:
                    documented[operator].add(family)

    for operator, families in documented.items():
        real = {DOC_DTYPE_NAMES[family] for family in OPERATOR_DTYPES[operator]}
        assert families == real, f"the table says {operator} takes {sorted(families)}, the parser takes {sorted(real)}"


def test_every_operator_with_a_dtype_rule_appears_in_the_table():
    """`==` is the one comparison the table leaves out, and the doc says elsewhere that it reads as
    `=`. Anything else missing is a rule with no row."""
    header = _marked_span("operator-dtypes").splitlines()[0]
    tabled = {operator for cell in header.split("|")[2:-1] for operator in _backticked(cell)}
    assert set(OPERATOR_DTYPES) - tabled == {"=="}


###############################################################################
# Aggregates and literals
###############################################################################
def test_the_aggregate_function_list_is_the_real_one():
    # Deduped, since the paragraph names `count` again to say it is the one that takes any dtype.
    listed = dict.fromkeys(
        token for token in _backticked(_marked_span("aggregate-functions")) if token in AGGREGATE_FUNCTIONS
    )
    assert list(listed) == list(AGGREGATE_FUNCTIONS)


def test_the_documented_aggregate_forms_are_the_published_ones():
    span = _marked_span("aggregate-functions")
    for form in GRAMMAR["aggregates"]["forms"]:
        assert f"`{form}`" in span, f"the aggregate form {form} is published and undocumented"


def test_the_documented_text_delimiters_are_the_real_ones():
    delimiters = {token for token in _backticked(_marked_span("text-delimiters")) if token in QUOTE_CHARACTERS}
    assert delimiters == set(QUOTE_CHARACTERS)
