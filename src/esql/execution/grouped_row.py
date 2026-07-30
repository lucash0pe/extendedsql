from datetime import date

import pandas as pd

from esql.parser.types import AggregatesDict, GlobalAggregate, GroupAggregate, aggregate_key


class GroupedRow:
    """
    Each GroupedRow represents one unique combination of grouping attribute values
    and stores the computed aggregate values in a data map.
    """

    def __init__(
        self,
        grouping_attributes: list[str],
        aggregates: AggregatesDict,
        initial_row: list[str | int | bool | date],
        column_indices: dict[str, int],
    ):
        self.grouping_attributes = grouping_attributes
        self.aggregates = aggregates
        self._initial_row = initial_row
        self._column_indices = column_indices
        self._data_map: dict[str, str | int | bool | date] = {}
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

    def update_data_map(self, aggregate: GlobalAggregate | GroupAggregate, row: list[str | int | bool | date]) -> None:
        """Fold one row into one aggregate's running value.

        `count` accumulates rather than adds up, in two different ways. The **row count** (`count`,
        `g1.count`) names no column, so nothing about the row can be missing and every row counts.
        A **column count** (`quant.count`) counts the column's *distinct* values, so it accumulates
        the set of them and `finalize_data_map` takes its size; a missing value is not a value, and
        is skipped like it is for every other function.
        """
        function = aggregate["function"]
        key = aggregate_key(aggregate)

        if aggregate["column"] is None:
            self._data_map[key] = self._data_map.get(key, 0) + 1
            return

        value = row[self._column_indices[aggregate["column"]]]
        if pd.isna(value):
            return

        if function == "count":
            self._data_map.setdefault(key, set()).add(value)
        elif key not in self._data_map:
            if function in ["sum", "min", "max"]:
                self._data_map[key] = value
            elif function == "avg":
                self._data_map[key] = {"sum": value, "count": 1}
        elif function == "sum":
            self._data_map[key] += value
        elif function == "min":
            if value < self._data_map[key]:
                self._data_map[key] = value
        elif function == "max":
            if value > self._data_map[key]:
                self._data_map[key] = value
        elif function == "avg":
            values = self._data_map[key]
            self._data_map[key] = {"sum": values["sum"] + value, "count": values["count"] + 1}

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
    def data_map(self):
        return self._data_map

    def __str__(self):
        return ", ".join(f"{k}: {v}" for k, v in self._data_map.items())

    def __repr__(self):
        return self.__str__()
