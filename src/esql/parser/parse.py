import re

import pandas as pd

from esql.parser.types import ParsedQuery
from esql.parser.util import (
    get_keyword_clauses,
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
    # Find and separate quoted strings.
    pattern = r'"[^"]*"|\'[^\']*\''
    quoted_texts = re.findall(pattern, query)
    parts = re.split(f"({pattern})", query)

    # Lowercase all parts that are not within quotes.
    processed_parts = []
    quoted_index = 0
    for part in parts:
        if re.match(pattern, part):
            processed_parts.append(f"QUOTED{quoted_index}")
            quoted_index += 1
        else:
            processed_parts.append(part.lower())

    # Reinsert the quoted texts.
    query = "".join(processed_parts)
    for i, qt in enumerate(quoted_texts):
        query = query.replace(f"QUOTED{i}", qt, 1)

    return " ".join(query.split())


def _build_parsed_query(data: pd.DataFrame, query: str) -> ParsedQuery:
    column_dtypes = data.dtypes.to_dict()
    keyword_clauses = get_keyword_clauses(query)

    parsed_over_clause = parse_over_clause(over_clause=keyword_clauses["OVER"])

    parsed_select_clause = parse_select_clause(
        select_clause=keyword_clauses["SELECT"], groups=parsed_over_clause, column_dtypes=column_dtypes
    )

    parsed_where_clause = parse_where_clause(where_clause=keyword_clauses["WHERE"], column_dtypes=column_dtypes)

    parsed_such_that_clauses = parse_such_that_clause(
        such_that_clause=keyword_clauses["SUCH THAT"], groups=parsed_over_clause, column_dtypes=column_dtypes
    )

    (parsed_having_clause, aggregates) = parse_having_clause(
        having_clause=keyword_clauses["HAVING"], groups=parsed_over_clause, column_dtypes=column_dtypes
    )

    aggregates["global_scope"].extend(parsed_select_clause["aggregates"]["global_scope"])
    aggregates["group_specific"].extend(parsed_select_clause["aggregates"]["group_specific"])

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
