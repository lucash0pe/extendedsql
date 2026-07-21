import beartype
import pandas as pd
import pytest


def test_accessor_does_not_accept_types_other_than_string_for_query_and_int_for_decimal_places():
    args = [
        {"query": "string", "decimal_places": "string"},
        {"query": 4, "decimal_places": 3},
        {"query": "string", "decimal_places": 3.5},
        {"query": False, "decimal_places": 1},
    ]
    for arg in args:
        with pytest.raises(beartype.roar.BeartypeCallHintParamViolation):
            df = pd.DataFrame()
            df.esql.query(query=arg["query"], decimal_places=arg["decimal_places"])


def test_accessor_does_not_accept_negative_values_or_zero_for_decimal_places():
    dp_values = [-1, -10, 0]
    for dp in dp_values:
        with pytest.raises(beartype.roar.BeartypeCallHintParamViolation):
            df = pd.DataFrame()
            df.esql.query(query="query", decimal_places=dp)


if __name__ == "__main__":
    pytest.main()
