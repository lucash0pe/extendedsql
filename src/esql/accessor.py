from typing import Annotated

import pandas as pd
from beartype import beartype
from beartype.vale import Is
from pandas.api.extensions import register_dataframe_accessor

from esql.execution.execute import execute
from esql.parser.parse import get_parsed_query

IntGreaterThanZero = Annotated[int, Is[lambda x: x > 0]]


@register_dataframe_accessor("esql")
class ESQLAccessor:
    def __init__(self, data: pd.DataFrame):
        self.data = _enforce_allowed_dtypes(data)

    @beartype
    def query(self, query: str, decimal_places: IntGreaterThanZero = 2) -> pd.DataFrame:
        parsed_query = get_parsed_query(self.data, query)
        result_dataframe = execute(parsed_query, decimal_places)
        return result_dataframe


def _enforce_allowed_dtypes(data: pd.DataFrame) -> pd.DataFrame:
    """
    Convert DataFrame columns so that each column's dtype is one of:
      - "string" for textual data
      - bool for boolean data
      - datetime.date for date/time data
      - int or float for numeric data

    For numeric columns, if they're already integer or float, they are left unchanged.
    Any columns that don't match the allowed types (except bool and datetime)
    will be converted to the "string" dtype.

    Parameters:
        df: The input DataFrame.

    Returns:
        pd.DataFrame: A new DataFrame with enforced dtypes.
    """
    data = data.copy()
    for column in data.columns:
        current_dtype = data[column].dtype
        if pd.api.types.is_bool_dtype(current_dtype) or pd.api.types.is_numeric_dtype(current_dtype):
            continue
        elif pd.api.types.is_datetime64_any_dtype(current_dtype):
            data[column] = pd.to_datetime(data[column]).dt.date
            continue
        elif pd.api.types.is_object_dtype(current_dtype):
            try:
                # Try to convert to datetime if possible
                converted = pd.to_datetime(data[column], format="%Y-%m-%d", errors="raise").dt.date
                data[column] = converted
                continue
            except (ValueError, TypeError):
                pass
        data[column] = data[column].astype("string")
    return data
