"""Empty-group HAVING and public-boundary error behavior.

These go through the public `df.esql.query(...)` accessor (the surface the browser demo runs),
not a parser helper. The regression: a HAVING that compares a group-specific aggregate which is
None for an empty SUCH THAT group used to raise a raw `TypeError` ('>' not supported between
NoneType and float) that leaked to the caller. It must now filter those rows out (SQL NULL
semantics), never raise.
"""

import pandas as pd
import pytest

from esql.parser.error import ParsingError


def test_having_on_fully_empty_group_returns_no_rows(sales_test_data: pd.DataFrame):
    # g2 matches no rows (no such state), so g2.quant.sum is None for every cust. The HAVING
    # comparison must exclude them all rather than raising.
    esql = (
        "SELECT cust, g1.quant.sum, g2.quant.sum OVER g1, g2 "
        "SUCH THAT g1.state = 'PA', g2.state = 'ZZ' "
        "HAVING g2.quant.sum > 0 ORDER BY 1"
    )
    result = sales_test_data.esql.query(esql)
    assert len(result) == 0


def test_having_on_partially_empty_group_keeps_only_populated_rows(sales_test_data: pd.DataFrame):
    # g1 is scoped to state 'PA'. A cust with no PA sales has g1.quant.sum == None and must drop;
    # a cust with PA sales survives. The surviving custs are exactly those with PA rows.
    esql = "SELECT cust, g1.quant.sum OVER g1 SUCH THAT g1.state = 'PA' HAVING g1.quant.sum > 0 ORDER BY 1"
    result = sales_test_data.esql.query(esql)

    expected = sales_test_data[sales_test_data["state"] == "PA"].groupby("cust")["quant"].sum()
    expected_custs = set(expected[expected > 0].index)
    assert set(result["cust"]) == expected_custs
    # And every surviving row has a real, positive aggregate (no leaked None).
    assert all(v > 0 for v in result["g1.quant.sum"])


def test_malformed_query_raises_parsing_error(sales_test_data: pd.DataFrame):
    # The public boundary surfaces a readable ParsingError (its last traceback line is what the
    # demo shows a visitor), not an opaque crash.
    with pytest.raises(ParsingError) as excinfo:
        sales_test_data.esql.query("this is not a valid query")
    assert str(excinfo.value)
