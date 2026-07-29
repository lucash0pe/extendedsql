import re

import pandas as pd

from esql.parser.types import ParsedQuery
from esql.parser.util import (
    get_keyword_clauses,
    literal_spans,
    parse_having_clause,
    parse_order_by_clause,
    parse_over_clause,
    parse_select_clause,
    parse_such_that_clause,
    parse_where_clause,
)


def get_parsed_query(data: pd.DataFrame, query: str) -> ParsedQuery:
    prepared_query = _prepare_query(query)
    return _build_parsed_query(data=data, query=prepared_query)


def _prepare_query(query: str) -> str:
    """Canonicalize a query for parsing: lowercase it and collapse its whitespace, outside string
    literals only.

    Keywords, identifiers and operators are case-insensitive, so folding them here means the rest
    of the parser only ever sees one spelling. A literal is the opposite: its contents are data, so
    its case and its internal spacing are carried through exactly as written.

    Telling the two apart is what `literal_spans` is for, and getting it wrong here is what made a
    value holding an apostrophe silently match nothing (`.claude/status.md`, J4). The old pass
    found literals with the regex `'[^']*'`, which closes at the first quote it meets rather than
    at the one that ends the literal.
    """
    prepared = []
    cursor = 0
    for start, end in literal_spans(query):
        prepared.append(_fold(query[cursor:start]))
        prepared.append(query[start:end])  # verbatim: a literal's case and spacing are data
        cursor = end
    prepared.append(_fold(query[cursor:]))
    return "".join(prepared).strip()


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def _build_parsed_query(data: pd.DataFrame, query: str) -> ParsedQuery:
    column_dtypes = data.dtypes.to_dict()
    keyword_clauses = get_keyword_clauses(query)

    parsed_over_clause = parse_over_clause(over_clause=keyword_clauses["OVER"])

    parsed_select_clause = parse_select_clause(
        select_clause=keyword_clauses["SELECT"], groups=parsed_over_clause, column_dtypes=column_dtypes
    )

    parsed_where_clause = parse_where_clause(where_clause=keyword_clauses["WHERE"], column_dtypes=column_dtypes)

    parsed_such_that_clauses = parse_such_that_clause(
        such_that_clause=keyword_clauses["SUCH THAT"],
        groups=parsed_over_clause,
        column_dtypes=column_dtypes,
        grouping_attributes=parsed_select_clause["grouping_attributes"],
    )

    (parsed_having_clause, aggregates) = parse_having_clause(
        having_clause=keyword_clauses["HAVING"], groups=parsed_over_clause, column_dtypes=column_dtypes
    )

    # Merge the SELECT aggregates into those collected from HAVING, skipping any already
    # present. An aggregate named in both SELECT and HAVING (e.g. `quant.avg`) must appear
    # once: a duplicate is accumulated twice per row (doubling sum/count) and converted twice.
    for scope in ("global_scope", "group_specific"):
        for aggregate in parsed_select_clause["aggregates"][scope]:
            if aggregate not in aggregates[scope]:
                aggregates[scope].append(aggregate)

    order_by_clause = parse_order_by_clause(
        order_by_clause=keyword_clauses["ORDER BY"],
        number_of_select_grouping_attributes=len(parsed_select_clause["grouping_attributes"]),
    )

    return ParsedQuery(
        data=data,
        select=parsed_select_clause,
        over=parsed_over_clause,
        where=parsed_where_clause,
        such_that=parsed_such_that_clauses,
        having=parsed_having_clause,
        order_by=order_by_clause,
        aggregates=aggregates,
    )
