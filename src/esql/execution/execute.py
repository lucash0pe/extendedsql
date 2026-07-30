import pandas as pd

from esql.execution import algorithms
from esql.parser.types import ParsedQuery


def execute(parsed_query: ParsedQuery, decimal_places: int) -> pd.DataFrame:
    pd_datatable = parsed_query["data"]
    columns = pd_datatable.columns.tolist()
    column_indices = {column: index for index, column in enumerate(columns)}
    datatable = pd_datatable.values.tolist()

    grouped_table = algorithms.build_grouped_table(
        parsed_select_clause=parsed_query["select"],
        groups=parsed_query["over"],
        parsed_where_clause=parsed_query["where"],
        parsed_such_that_clause=parsed_query["such_that"],
        parsed_having_clause=parsed_query["having"],
        aggregates=parsed_query["aggregates"],
        datatable=datatable,
        column_indices=column_indices,
    )

    projected_table = algorithms.project_select_attributes(
        parsed_select_clause=parsed_query["select"], grouped_table=grouped_table, decimal_places=decimal_places
    )

    ordered_table = algorithms.order_by_sort(
        projected_table=projected_table,
        order_by=parsed_query["order_by"],
    )

    return pd.DataFrame(ordered_table)
