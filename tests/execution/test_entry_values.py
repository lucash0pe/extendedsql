"""Entry values in SUCH THAT, the EMF half of the Phi operator.

An entry value is a grouping attribute standing in for the value the output row being computed
holds for it, optionally offset: `prev.month = month - 1`. That makes a section a different
question per output row, and the rows answering it belong to a *different* grouping combination
than the row being computed, which is the whole difference from the MF form and the reason
execution keeps a second pass for it (`algorithms._accumulate_by_entry_value`).

So the cases that matter are the ones where that shows: an aggregate built from rows the output row
does not contain, a group that finds nothing, and the two passes running side by side in one query.
These go through the public df.esql.query(...) accessor.
"""

from datetime import date

import pandas as pd
import pytest

from esql.execution.algorithms import _evaluate_condition
from esql.execution.error import RuntimeError as ExecutionRuntimeError
from esql.parser.error import ParsingError


@pytest.fixture
def monthly_data() -> pd.DataFrame:
    # Two customers over three months. Customer `a` skips no month, `b` has no month 2, so its
    # month 3 finds no previous month to compare against.
    return pd.DataFrame(
        {
            "cust": ["a", "a", "a", "a", "b", "b"],
            "month": [1, 1, 2, 3, 1, 3],
            "prod": ["Ham", "Ham", "Ham", "Rice", "Ham", "Rice"],
            "quant": [10, 20, 30, 40, 100, 5],
        }
    )


###############################################################################
# The EMF form
###############################################################################
def test_an_offset_entry_value_reaches_the_previous_group(monthly_data: pd.DataFrame):
    result = monthly_data.esql.query(
        "SELECT cust, month, quant.avg, prev.quant.avg "
        "OVER prev "
        "SUCH THAT prev.cust = cust AND prev.month = month - 1 "
        "ORDER BY 1"
    )
    previous = dict(zip(zip(result["cust"], result["month"], strict=True), result["prev.quant.avg"], strict=True))
    # (a, 2) reads month 1's two rows, which its own group does not contain.
    assert previous[("a", 2)] == 15.0
    assert previous[("a", 3)] == 30.0
    assert previous[("b", 3)] == pytest.approx(float("nan"), nan_ok=True)


def test_a_group_with_no_previous_row_is_left_empty(monthly_data: pd.DataFrame):
    result = monthly_data.esql.query(
        "SELECT cust, month, prev.quant.sum OVER prev SUCH THAT prev.cust = cust AND prev.month = month - 1"
    )
    # Month 1 has no month 0 for either customer, and b has no month 2 to feed its month 3.
    empty = result[result["prev.quant.sum"].isna()]
    assert set(zip(empty["cust"], empty["month"], strict=True)) == {("a", 1), ("b", 1), ("b", 3)}


def test_a_positive_offset_reaches_the_following_group(monthly_data: pd.DataFrame):
    result = monthly_data.esql.query(
        "SELECT cust, month, next.quant.sum OVER next SUCH THAT next.cust = cust AND next.month = month + 1"
    )
    following = dict(zip(zip(result["cust"], result["month"], strict=True), result["next.quant.sum"], strict=True))
    assert following[("a", 1)] == 30
    assert following[("a", 2)] == 40


def test_an_entry_value_with_no_offset_reaches_every_group_sharing_it(monthly_data: pd.DataFrame):
    result = monthly_data.esql.query(
        "SELECT cust, month, quant.sum, all_months.quant.sum OVER all_months SUCH THAT all_months.cust = cust"
    )
    # Each row's own month against that customer's whole total, in one pass and no subquery.
    totals = dict(zip(zip(result["cust"], result["month"], strict=True), result["all_months.quant.sum"], strict=True))
    assert totals[("a", 1)] == totals[("a", 2)] == totals[("a", 3)] == 100
    assert totals[("b", 1)] == 105


def test_an_entry_value_works_on_a_text_attribute(monthly_data: pd.DataFrame):
    result = monthly_data.esql.query(
        "SELECT prod, quant.sum, others.quant.sum OVER others SUCH THAT others.prod != prod"
    )
    others = dict(zip(result["prod"], result["others.quant.sum"], strict=True))
    # Ham's own rows total 160 and Rice's 45, so each reads the other's.
    assert others["Ham"] == 45
    assert others["Rice"] == 160


def test_an_entry_value_works_on_a_date_attribute():
    data = pd.DataFrame(
        {
            "date": ["1977-05-07", "1977-05-08", "1977-05-08"],
            "seconds": [100, 200, 300],
        }
    )
    result = data.esql.query("SELECT date, earlier.seconds.sum OVER earlier SUCH THAT earlier.date < date")
    earlier = dict(zip(result["date"], result["earlier.seconds.sum"], strict=True))
    assert earlier[date(1977, 5, 8)] == 100
    assert pd.isna(earlier[date(1977, 5, 7)])


###############################################################################
# Composition
###############################################################################
def test_an_entry_value_combines_with_a_constant_in_the_same_section(monthly_data: pd.DataFrame):
    result = monthly_data.esql.query(
        "SELECT cust, month, prev.quant.sum "
        "OVER prev "
        "SUCH THAT prev.cust = cust AND prev.month = month - 1 AND prev.quant > 15"
    )
    previous = dict(zip(zip(result["cust"], result["month"], strict=True), result["prev.quant.sum"], strict=True))
    # Month 1 holds 10 and 20 for customer a; the constant drops the 10.
    assert previous[("a", 2)] == 20


def test_an_entry_value_works_under_not(monthly_data: pd.DataFrame):
    result = monthly_data.esql.query(
        "SELECT cust, quant.sum, others.quant.sum OVER others SUCH THAT NOT (others.cust = cust)"
    )
    others = dict(zip(result["cust"], result["others.quant.sum"], strict=True))
    assert others["a"] == 105
    assert others["b"] == 100


def test_an_entry_value_section_runs_beside_a_constant_section(monthly_data: pd.DataFrame):
    result = monthly_data.esql.query(
        "SELECT cust, month, ham.quant.sum, prev.quant.sum "
        "OVER ham, prev "
        "SUCH THAT ham.prod = 'Ham', prev.cust = cust AND prev.month = month - 1"
    )
    rows = {(row["cust"], row["month"]): row for _, row in result.iterrows()}
    # The constant section still routes each row to its own group, the entry-value one does not.
    assert rows[("a", 1)]["ham.quant.sum"] == 30
    assert pd.isna(rows[("a", 3)]["ham.quant.sum"])
    assert rows[("a", 3)]["prev.quant.sum"] == 30


def test_where_filters_the_rows_an_entry_value_can_reach(monthly_data: pd.DataFrame):
    result = monthly_data.esql.query(
        "SELECT cust, month, prev.quant.sum "
        "OVER prev "
        "WHERE quant > 15 "
        "SUCH THAT prev.cust = cust AND prev.month = month - 1"
    )
    previous = dict(zip(zip(result["cust"], result["month"], strict=True), result["prev.quant.sum"], strict=True))
    # WHERE runs first, so month 1 keeps only its 20 and that is all month 2 finds.
    assert previous[("a", 2)] == 20


def test_a_blank_grouping_value_matches_nothing():
    data = pd.DataFrame({"cust": ["a", None, "a"], "month": [1, 1, 2], "quant": [10, 99, 20]})
    result = data.esql.query(
        "SELECT cust, month, prev.quant.sum OVER prev SUCH THAT prev.cust = cust AND prev.month = month - 1"
    )
    # The blank-customer row neither reaches a group nor raises comparing against the missing value.
    assert result["prev.quant.sum"].notna().sum() == 1
    assert result[result["month"] == 2]["prev.quant.sum"].iloc[0] == 10


###############################################################################
# Rejections
###############################################################################
def test_an_entry_value_in_where_is_a_parsing_error(monthly_data: pd.DataFrame):
    with pytest.raises(ParsingError, match="An entry value belongs in SUCH THAT"):
        monthly_data.esql.query("SELECT cust, quant.sum WHERE month = month - 1")


def test_referencing_a_column_that_is_not_grouped_on_is_a_parsing_error(monthly_data: pd.DataFrame):
    with pytest.raises(ParsingError, match="'month' is not a SELECT grouping attribute"):
        monthly_data.esql.query("SELECT cust, g1.quant.sum OVER g1 SUCH THAT g1.month = month - 1")


def test_comparing_across_value_families_is_a_parsing_error(monthly_data: pd.DataFrame):
    with pytest.raises(ParsingError, match="Cannot compare numeric column 'quant' against text attribute 'cust'"):
        monthly_data.esql.query("SELECT cust, g1.quant.sum OVER g1 SUCH THAT g1.quant = cust")


def test_offsetting_a_non_numeric_attribute_is_a_parsing_error(monthly_data: pd.DataFrame):
    with pytest.raises(ParsingError, match="Only a numeric attribute can be offset"):
        monthly_data.esql.query("SELECT cust, g1.quant.sum OVER g1 SUCH THAT g1.cust = cust - 1")


def test_an_unknown_word_is_read_as_a_literal_not_a_reference(monthly_data: pd.DataFrame):
    # `nope` is no column, so this never becomes an entry value and fails as a bad value instead.
    with pytest.raises(ParsingError, match="Invalid column reference or value"):
        monthly_data.esql.query("SELECT cust, g1.quant.sum OVER g1 SUCH THAT g1.cust = nope")


def test_a_quoted_attribute_name_is_a_literal_not_a_reference(monthly_data: pd.DataFrame):
    # Quoting it asks for rows whose prod is the text "cust", of which there are none.
    result = monthly_data.esql.query("SELECT cust, g1.quant.sum OVER g1 SUCH THAT g1.prod = 'cust'")
    assert result["g1.quant.sum"].isna().all()


def test_an_unbound_entry_value_raises_rather_than_matching_nothing():
    # The parsed shape as it stands before _bind_entry_values reaches it. Only the entry-value pass
    # knows which grouped row to read, so arriving here at all is a routing bug, and a silent
    # never-matches would hide it.
    condition = {"column": "month", "operator": "=", "value": {"attribute": "month", "delta": -1}, "is_emf": True}
    with pytest.raises(ExecutionRuntimeError, match="was not bound to a grouped row"):
        _evaluate_condition(condition=condition, row=[1], column_indices={"month": 0})
