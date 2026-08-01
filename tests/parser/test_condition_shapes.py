"""What the two condition trees are made of, and the property that lets one walk answer both.

`parser/types.py` declares a WHERE clause and a SUCH THAT section as separate hierarchies built
from the same three node kinds. That claim used to be written as inheritance -- `CompoundGroupCondition`
extending `CompoundCondition` -- which asserted something stronger and false, and was itself wrong
about the level: it declared `conditions` as a list of *clauses* (a list of lists) while the parser
has always put sections there. Nothing caught it, because `_evaluate_condition` took a bare `dict`.

These tests bind the shape. The type-level half of the claim is bound by `make typecheck`.
"""

import pandas as pd
import pytest

from esql.execution.algorithms import _evaluate_condition
from esql.parser.parse import get_parsed_query
from esql.parser.types import LogicalOperator


@pytest.fixture
def parsed(sales_test_data: pd.DataFrame):
    def _parse(query: str):
        return get_parsed_query(sales_test_data, query)

    return _parse


def test_a_compound_such_that_section_holds_sections_not_clauses(parsed):
    """The nesting level the old annotation got wrong: one level of sections, not a list of lists."""
    section = parsed("select cust, g1.quant.sum over g1 such that g1.state = 'NY' and g1.quant > 5")["such_that"][0]
    assert section["operator"] is LogicalOperator.AND
    for child in section["conditions"]:
        assert isinstance(child, dict), "a compound section holds sections, not lists of them"
        assert child["column"] in ("state", "quant")


def test_a_negated_such_that_section_holds_one_section(parsed):
    section = parsed("select cust, g1.quant.sum over g1 such that not g1.state = 'NY'")["such_that"][0]
    assert section["operator"] is LogicalOperator.NOT
    assert isinstance(section["condition"], dict)
    assert section["condition"]["column"] == "state"


def test_the_two_trees_are_built_from_the_same_three_node_kinds(parsed):
    """A leaf, an AND/OR over children, a NOT over one child -- in both hierarchies, spelled the
    same way. This is what `ParsedCondition` names."""
    where = parsed("select cust, quant.sum where not (state = 'NY' and quant > 5)")["where"]
    such_that = parsed("select cust, g1.quant.sum over g1 such that not (g1.state = 'NY' and g1.quant > 5)")[
        "such_that"
    ][0]

    assert where["operator"] is such_that["operator"] is LogicalOperator.NOT
    assert set(where["condition"]) == {"operator", "conditions"}
    # The section leaf carries `group` on top of the leaf keys, which is the one real subtype here.
    assert set(such_that["condition"]) == {"operator", "conditions"}
    assert set(where["condition"]["conditions"][0]) | {"group"} == set(such_that["condition"]["conditions"][0])


def test_one_evaluator_walks_either_tree(parsed):
    """The interchangeability the engine actually relies on: `_evaluate_condition` is called with a
    WHERE clause and with a SUCH THAT section, and neither call knows which it got."""
    column_indices = {"state": 0, "quant": 1}
    row = ["NY", 10]

    where = parsed("select cust, quant.sum where state = 'NY' and quant > 5")["where"]
    such_that = parsed("select cust, g1.quant.sum over g1 such that g1.state = 'NY' and g1.quant > 5")["such_that"][0]

    assert _evaluate_condition(condition=where, row=row, column_indices=column_indices)
    assert _evaluate_condition(condition=such_that, row=row, column_indices=column_indices)

    assert not _evaluate_condition(condition=where, row=["CT", 10], column_indices=column_indices)
    assert not _evaluate_condition(condition=such_that, row=["CT", 10], column_indices=column_indices)


def test_a_group_scoped_leaf_is_a_leaf_with_a_group(parsed):
    """`SimpleGroupCondition` inherits `SimpleCondition` because it adds a key rather than replacing
    one. That is why the evaluator's leaf branch serves both without knowing which it has."""
    where_leaf = parsed("select cust, quant.sum where state = 'NY'")["where"]
    section_leaf = parsed("select cust, g1.quant.sum over g1 such that g1.state = 'NY'")["such_that"][0]

    assert set(section_leaf) - set(where_leaf) == {"group"}
    assert section_leaf["group"] == "g1"
    assert {key: section_leaf[key] for key in where_leaf} == where_leaf


if __name__ == "__main__":
    pytest.main()
