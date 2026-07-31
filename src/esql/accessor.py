from typing import Annotated

import pandas as pd
from beartype import beartype
from beartype.vale import Is
from pandas.api.extensions import register_dataframe_accessor

from esql.execution.execute import execute
from esql.parser.error import ParsingError, ParsingErrorType
from esql.parser.parse import get_parsed_query
from esql.parser.util import BARE_AGGREGATE_FUNCTIONS

IntGreaterThanZero = Annotated[int, Is[lambda x: x > 0]]


@register_dataframe_accessor("esql")
class ESQLAccessor:
    def __init__(self, data: pd.DataFrame):
        _reject_reserved_columns(data)
        self.data = _enforce_allowed_dtypes(data)

    @beartype
    def query(self, query: str, decimal_places: IntGreaterThanZero = 2) -> pd.DataFrame:
        parsed_query = get_parsed_query(self.data, query)
        result_dataframe = execute(parsed_query, decimal_places)
        return result_dataframe

    @beartype
    def validate(self, query: str) -> None:
        """Parse `query` against this frame's columns without executing it.

        Returns None when the query parses and raises the same ParsingError `query` would
        otherwise raise, so both paths share one error contract. Parsing is the cheap half of a
        query — microseconds against tens of milliseconds — which is what makes this usable for
        live feedback while someone is still typing.

        It checks what the parser checks: clause order, syntax, that referenced columns exist,
        and that each aggregate function suits its column's dtype. A query that validates can
        still return zero rows.
        """
        get_parsed_query(self.data, query)


def _reject_reserved_columns(data: pd.DataFrame) -> None:
    """Refuse a frame whose columns use a name the language has taken.

    Only the names that can be written as a whole aggregate are taken: `count` means the row count
    wherever a grouping attribute could go, so a column of that name is a word with two readings.
    Every other function needs a column before it (`sum` is never an aggregate on its own), so a
    column may be called `sum` and this rule leaves it alone.

    Refused here, at the frame, rather than resolved per reference. Preferring one reading would
    leave `SELECT venue, count` legal and its meaning decided by the data handed in, and preferring
    the other would put the row count out of reach for that frame alone. Neither is something a
    query writer can see. Renaming the column is, so the error asks for that and names it.
    """
    reserved = {name.lower() for name in BARE_AGGREGATE_FUNCTIONS}
    for column in data.columns:
        if str(column).lower() in reserved:
            raise ParsingError(
                ParsingErrorType.RESERVED_COLUMN,
                f"Column '{column}' is named after the aggregate '{str(column).lower()}', which ESQL "
                f"reads as the row count wherever a column could go. Rename the column in the data.",
                token=str(column),
            )


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
