"""What a column's dtype actually is, which is not what the parser's signatures used to say.

Every `column_dtypes` parameter was declared `dict[str, np.dtype]`. `_enforce_allowed_dtypes` coerces
text columns to pandas `"string"`, whose dtype is `StringDtype` -- an `ExtensionDtype`, not a numpy
one -- so the annotation declared impossible the dtype of every column a text comparison reads.
`dtype_family` said so in prose ("reads an enforced dtype") while its signature said otherwise.

Bound here because the fix is one type alias, and an alias is exactly the kind of claim this repo
keeps finding to be false: `.claude/status.md`, Stream L.
"""

import numpy as np
import pandas as pd
import pytest
from pandas.api.extensions import ExtensionDtype

from esql.accessor import _enforce_allowed_dtypes
from esql.parser.util import dtype_family


@pytest.fixture
def enforced() -> pd.DataFrame:
    return _enforce_allowed_dtypes(
        pd.DataFrame(
            {
                "name": ["a", "b"],
                "quant": [1, 2],
                "ratio": [1.5, 2.5],
                "flag": [True, False],
                "day": ["2020-01-01", "2020-01-02"],
            }
        )
    )


def test_a_text_column_is_not_a_numpy_dtype(enforced: pd.DataFrame):
    """The claim that was false. If this ever becomes an np.dtype, `ColumnDtype` can narrow."""
    dtype = enforced.dtypes["name"]
    assert not isinstance(dtype, np.dtype)
    assert isinstance(dtype, ExtensionDtype)


def test_every_other_enforced_family_is_a_numpy_dtype(enforced: pd.DataFrame):
    """Which is why the annotation went unnoticed: only text leaves numpy."""
    for column in ("quant", "ratio", "flag", "day"):
        assert isinstance(enforced.dtypes[column], np.dtype), column


def test_dtype_family_answers_for_both_kinds(enforced: pd.DataFrame):
    """`dtype_family` is the function the wrong annotation sat on, and it is public because
    `demokit` reads it for a demo asset's `SchemaColumn.type`. It has always handled both."""
    families = {column: dtype_family(enforced.dtypes[column]) for column in enforced.columns}
    assert families == {
        "name": "string",
        "quant": "number",
        "ratio": "number",
        "flag": "boolean",
        "day": "date",
    }


def test_a_text_column_is_queryable_end_to_end(enforced: pd.DataFrame):
    """The behavior the annotation was wrong about, and which was never broken: the parser reads an
    ExtensionDtype column and compares against it."""
    result = enforced.esql.query("SELECT name, quant.sum WHERE name CONTAINS 'a'")
    assert list(result["name"]) == ["a"]
    assert list(result["quant.sum"]) == [1]


if __name__ == "__main__":
    pytest.main()
