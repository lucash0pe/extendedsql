"""What makes two parsed aggregates the same aggregate.

The SELECT/HAVING merge in `_build_parsed_query` skips an aggregate `already present`, which is a
list membership test and therefore an equality test. Nothing pinned what that equality *is*, and the
answer used to be written down twice in disagreement: `GlobalAggregate` and `GroupAggregate` each
carried an `__eq__` comparing a chosen subset of the keys, while the equality that actually ran was
plain dict equality over all of them. The methods never ran -- a TypedDict constructs a `dict`, so no
instance is ever of the class the method is defined on -- so the disagreement was invisible.

These tests pin the equality that runs, so the two cannot drift apart again: deleting the dead
methods is provably a no-op, and reinstating their semantics fails here rather than silently
changing which aggregates merge. Getting this wrong is not a crash. An aggregate that merges when it
should not is computed once and read by two clauses; one that fails to merge is accumulated twice per
row, which silently doubles a sum, and that is BUG-8 from v1.1.
"""

from esql.parser.parse import get_parsed_query
from esql.parser.types import GlobalAggregate, GroupAggregate


def test_an_aggregate_is_a_plain_dict_and_compares_as_one():
    """The premise the merge rests on. A TypedDict has no identity of its own at runtime."""
    left = GlobalAggregate(column="quant", function="sum")
    right = GlobalAggregate(column="quant", function="sum")

    assert type(left) is dict
    assert left == right


def test_two_aggregates_differing_only_by_group_are_not_the_same_aggregate():
    """The case the deleted `__eq__` got wrong, and the reason it mattered.

    `GroupAggregate.__eq__` compared `group`, `column` and `function`; `GlobalAggregate.__eq__`
    compared only `column` and `function`, so by its rule the two below were equal. They are not:
    one is a total over every row, the other over one OVER group's rows, and merging them would
    drop a measure the query asked for.
    """
    global_scope = GlobalAggregate(column="quant", function="sum")
    group_specific = GroupAggregate(group="g1", column="quant", function="sum")

    assert global_scope != group_specific
    assert group_specific not in [global_scope]


def test_two_group_aggregates_differing_only_by_group_are_not_the_same_aggregate():
    """`g1.quant.sum` and `g2.quant.sum` answer over different rows."""
    assert GroupAggregate(group="g1", column="quant", function="sum") != GroupAggregate(
        group="g2", column="quant", function="sum"
    )


def test_the_bare_row_count_is_not_the_same_aggregate_as_a_column_count(sales_test_data):
    """`count` and `quant.count` differ only in `column`, and answer different questions.

    v1.15.0 made `column` None for the bare form, so this pair is exactly the case where a
    subset-of-keys equality that skipped `column` would merge two aggregates that must not merge.
    """
    row_count = GlobalAggregate(column=None, function="count")
    distinct_count = GlobalAggregate(column="quant", function="count")

    assert row_count != distinct_count

    parsed = get_parsed_query(sales_test_data, "SELECT cust, count, quant.count")
    assert parsed["aggregates"]["global_scope"] == [row_count, distinct_count]


def test_an_aggregate_named_in_select_and_having_is_merged_to_one(sales_test_data):
    """BUG-8's regression, at the seam rather than through the accessor.

    A duplicate is accumulated twice per row, which doubles a sum and converts an avg twice.
    """
    parsed = get_parsed_query(sales_test_data, "SELECT cust, quant.sum HAVING quant.sum > 25")

    assert parsed["aggregates"]["global_scope"] == [GlobalAggregate(column="quant", function="sum")]


def test_a_group_aggregate_in_select_and_having_is_merged_to_one(sales_test_data):
    """The same merge, in the scope where `group` is part of the identity being compared."""
    parsed = get_parsed_query(
        sales_test_data,
        "SELECT cust, g1.quant.sum OVER g1 SUCH THAT g1.state = 'NY' HAVING g1.quant.sum > 5",
    )

    assert parsed["aggregates"]["group_specific"] == [GroupAggregate(group="g1", column="quant", function="sum")]


def test_two_group_aggregates_differing_only_by_group_both_survive_the_merge(sales_test_data):
    """The dead `__eq__`'s semantics, caught where they would actually do damage.

    Asserting the two dicts are unequal is not enough, because a merge could compare them on a
    subset of their keys and never consult that. This is the query where such a merge loses a
    measure: `g1` and `g2` scope to different rows, so dropping one answers the wrong question
    under a label the query did ask for. Global and group aggregates cannot collide this way --
    they live in separate scope lists and are never compared -- so within `group_specific` is the
    only place `group` has to carry weight.
    """
    parsed = get_parsed_query(
        sales_test_data,
        "SELECT cust, g1.quant.sum, g2.quant.sum OVER g1, g2 SUCH THAT g1.state = 'NY', g2.state = 'NJ'",
    )

    assert parsed["aggregates"]["group_specific"] == [
        GroupAggregate(group="g1", column="quant", function="sum"),
        GroupAggregate(group="g2", column="quant", function="sum"),
    ]


def test_two_different_aggregates_on_one_column_both_survive_the_merge(sales_test_data):
    """Equality is over every key, so `function` separates these two."""
    parsed = get_parsed_query(sales_test_data, "SELECT cust, quant.sum HAVING quant.max > 5")

    assert parsed["aggregates"]["global_scope"] == [
        GlobalAggregate(column="quant", function="max"),
        GlobalAggregate(column="quant", function="sum"),
    ]
