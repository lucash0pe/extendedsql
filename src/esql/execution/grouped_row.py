from datetime import date
from typing import Any

import pandas as pd

from esql.parser.types import AggregatesDict, GlobalAggregate, GroupAggregate, aggregate_key

CellValue = str | int | float | bool | date
"""A value as the frame holds it: what a row cell contains, and what a grouping attribute is.

`float` is in here because a float column is ordinary -- a duration in seconds, a price -- and it
is also what an avg finishes as.
"""

Accumulator = CellValue | set[CellValue] | dict[str, Any]
"""What a `_data_map` slot holds, which is not always an answer.

Two of the functions accumulate a shape rather than a running value, and `finalize_data_map` is
what turns each into the number the query asked for: a **column count** accumulates the *set* of
distinct values and finishes as its size, an **avg** accumulates a running `{"sum", "count"}` and
finishes as the quotient. So a slot is a plain `CellValue` only before those two have touched it,
or after that pass has run.
"""

ProjectedValue = CellValue | None
"""A finished value on its way to the caller. `None` when a select item names something the
grouped row holds no value for, which comes back as a blank cell rather than raising."""


class GroupedRow:
    """
    Each GroupedRow represents one unique combination of grouping attribute values
    and stores the computed aggregate values in a data map.
    """

    def __init__(
        self,
        grouping_attributes: list[str],
        aggregates: AggregatesDict,
        initial_row: list[CellValue],
        column_indices: dict[str, int],
    ):
        self.grouping_attributes = grouping_attributes
        self.aggregates = aggregates
        self._initial_row = initial_row
        self._column_indices = column_indices
        self._data_map: dict[str, Accumulator] = {}
        self._build_data_map()

    def _build_data_map(self) -> None:
        """The grouping attribute values, plus the first row's contribution to each aggregate.

        The first row is fed through `update_data_map` like every other one rather than being
        initialized separately here: the two used to spell out the same accumulators side by side,
        which is one rule in two places.
        """
        for attribute in self.grouping_attributes:
            index = self._column_indices[attribute]
            self._data_map[attribute] = self._initial_row[index]
        for aggregate in self.aggregates["global_scope"]:
            self.update_data_map(aggregate=aggregate, row=self._initial_row)

    def update_data_map(self, aggregate: GlobalAggregate | GroupAggregate, row: list[CellValue]) -> None:
        """Fold one row into one aggregate's running value.

        `count` accumulates rather than adds up, in two different ways. The **row count** (`count`,
        `g1.count`) names no column, so nothing about the row can be missing and every row counts.
        A **column count** (`quant.count`) counts the column's *distinct* values, so it accumulates
        the set of them and `finalize_data_map` takes its size; a missing value is not a value, and
        is skipped like it is for every other function.

        The ignores below are one sharp edge left sharp. Each branch knows the slot's shape because
        `function` is what put it there -- a `sum` slot holds what a previous `sum` wrote, an `avg`
        slot the running `{"sum", "count"}` -- but that ties a *value* to a *type*, which mypy
        cannot follow, so it offers every member of `Accumulator` instead. Typing the slot `Any`
        would silence these and every real error here with them.
        """
        function = aggregate["function"]
        key = aggregate_key(aggregate)

        if aggregate["column"] is None:
            self._data_map[key] = self._data_map.get(key, 0) + 1  # type: ignore[operator]
            return

        value = row[self._column_indices[aggregate["column"]]]
        if pd.isna(value):
            return

        if function == "count":
            self._data_map.setdefault(key, set()).add(value)  # type: ignore[union-attr]
        elif key not in self._data_map:
            if function in ["sum", "min", "max"]:
                self._data_map[key] = value
            elif function == "avg":
                self._data_map[key] = {"sum": value, "count": 1}
        elif function == "sum":
            self._data_map[key] += value  # type: ignore[operator]
        elif function == "min":
            if value < self._data_map[key]:  # type: ignore[operator]
                self._data_map[key] = value
        elif function == "max":
            if value > self._data_map[key]:  # type: ignore[operator]
                self._data_map[key] = value
        elif function == "avg":
            values = self._data_map[key]
            self._data_map[key] = {"sum": values["sum"] + value, "count": values["count"] + 1}  # type: ignore[index]

    # This must be called on all GroupedRows after they have been filtered by the WHERE and SUCH THAT clauses
    def finalize_data_map(self) -> None:
        """Turn each running accumulator into the value the query asked for: an avg's running
        `{sum, count}` into the quotient, a column count's set of distinct values into its size.

        Both conversions test the accumulator's shape rather than a flag, which makes the pass
        idempotent: converting an avg twice used to raise "'float' object is not subscriptable".
        """
        for aggregate in self.aggregates["global_scope"] + self.aggregates["group_specific"]:
            key = aggregate_key(aggregate)
            value = self._data_map.get(key)
            if isinstance(value, set):
                self._data_map[key] = len(value)
            elif aggregate["function"] == "avg" and isinstance(value, dict):
                self._data_map[key] = value["sum"] / value["count"]

    @property
    def data_map(self) -> dict[str, Accumulator]:
        return self._data_map

    def __str__(self):
        return ", ".join(f"{k}: {v}" for k, v in self._data_map.items())

    def __repr__(self):
        return self.__str__()
