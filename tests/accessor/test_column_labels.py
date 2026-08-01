"""A frame's column labels have to be strings, and the refusal happens at the frame.

pandas types a label as `Hashable`, so nothing about a DataFrame requires strings. This engine does:
a query names a column by writing it. Before this rule, an integer label was resolved happily by
`_resolve_column` and then reached `types.aggregate_key`'s `".".join`, which raised a raw `TypeError`
naming neither the column nor the query.
"""

import pandas as pd
import pytest

from esql.parser.error import ParsingError, ParsingErrorType


def test_an_integer_labelled_frame_is_refused_rather_than_raising_a_typeerror():
    """The case that filed the rule: `SELECT 0, 1.sum` used to reach `".".join` and raise
    `TypeError: sequence item 0: expected str instance, int found`."""
    data = pd.DataFrame({0: ["a", "b"], 1: [10, 20]})
    with pytest.raises(ParsingError, match="can only name a column that is a string"):
        data.esql.query("SELECT 0, 1.sum")


def test_the_frame_is_refused_before_any_query_is_read():
    """At the accessor rather than at the reference, like the reserved-name rule: the message is
    about the data, so a query that never names the offending column is refused too."""
    data = pd.DataFrame({"state": ["CA"], 7: [10]})
    with pytest.raises(ParsingError, match="is a int"):
        data.esql.validate("SELECT state")
    with pytest.raises(ParsingError, match="is a int"):
        data.esql  # noqa: B018 -- constructing the accessor is where the check runs


def test_the_error_names_the_column_and_its_type_and_asks_for_a_rename():
    data = pd.DataFrame({("a", "b"): [1]})
    with pytest.raises(ParsingError) as excinfo:
        data.esql  # noqa: B018
    error = excinfo.value
    assert error.error_type is ParsingErrorType.NON_STRING_COLUMN
    assert "is a tuple" in error.message
    assert "Rename the columns in the data" in error.message


@pytest.mark.parametrize("label", [0, 1.5, True, None, ("a", "b")])
def test_every_non_string_label_kind_is_refused(label):
    """Any hashable is a legal pandas label. None of them are writable in a query."""
    with pytest.raises(ParsingError, match="ESQL can only name a column"):
        pd.DataFrame({label: [1]}).esql  # noqa: B018


def test_a_string_labelled_frame_is_untouched():
    """The rule refuses only what it says it refuses: digits *as a string* are a legal label, and a
    query can name one, because the column resolver never needed the label to look like an
    identifier."""
    data = pd.DataFrame({"0": ["a", "b"], "quant": [10, 20]})
    result = data.esql.query("SELECT 0, quant.sum")
    assert list(result.columns) == ["0", "quant.sum"]


def test_the_refusal_is_not_a_coercion():
    """Refused rather than `str()`-coerced on the way in, so the caller's frame is never renamed
    behind their back. A frame holding both `0` and `'0'` is what makes coercion lossy: it would
    collapse two distinct columns into one label."""
    data = pd.DataFrame({0: [1], "0": [2]})
    with pytest.raises(ParsingError):
        data.esql  # noqa: B018
    assert list(data.columns) == [0, "0"]


if __name__ == "__main__":
    pytest.main()
