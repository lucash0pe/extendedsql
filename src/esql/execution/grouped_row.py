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
        self._data_map = self._build_data_map()

    def _build_data_map(self) -> dict[str, str | int | bool | date]:
        data_map = {}
        for attribute in self.grouping_attributes:
            index = self._column_indices[attribute]
            data_map[attribute] = self._initial_row[index]
        for aggregate in self.aggregates["global_scope"]:
            column = aggregate["column"]
            function = aggregate["function"]
            index = self._column_indices[column]
            value = self._initial_row[index]
            if pd.isna(value):
                continue
            key = aggregate_key(aggregate)
            if function in ["sum", "min", "max"]:
                data_map[key] = value
            elif function == "count":
                data_map[key] = 1
            elif function == "avg":
                data_map[key] = {"sum": value, "count": 1}
        return data_map

    def update_data_map(self, aggregate: GlobalAggregate | GroupAggregate, row: list[str | int | bool | date]) -> None:
        column = aggregate["column"]
        function = aggregate["function"]
        index = self._column_indices[column]
        value = row[index]
        if pd.isna(value):
            return
        key = aggregate_key(aggregate)
        if key not in self._data_map:
            if function in ["sum", "min", "max"]:
                self._data_map[key] = value
            elif function == "count":
                self._data_map[key] = 1
            elif function == "avg":
                self._data_map[key] = {"sum": value, "count": 1}
        else:
            if function == "sum":
                self._data_map[key] += value
            elif function == "min":
                if value < self._data_map[key]:
                    self._data_map[key] = value
            elif function == "max":
                if value > self._data_map[key]:
                    self._data_map[key] = value
            elif function == "count":
                self._data_map[key] += 1
            elif function == "avg":
                values = self._data_map[key]
                new_sum = values["sum"] + value
                new_count = values["count"] + 1
                self._data_map[key] = {"sum": new_sum, "count": new_count}

    # This must be called on all GroupedRows after they have been filtered by the WHERE and SUCH THAT clauses
    def convert_avg_in_data_map(self) -> None:
        for aggregate in self.aggregates["global_scope"] + self.aggregates["group_specific"]:
            if aggregate["function"] == "avg":
                key = aggregate_key(aggregate)
                if self._data_map.get(key):
                    _sum, _count = self._data_map[key]["sum"], self._data_map[key]["count"]
                    _avg = _sum / _count
                    self._data_map[key] = _avg

    @property
    def data_map(self):
        return self._data_map

    def __str__(self):
        return ", ".join(f"{k}: {v}" for k, v in self._data_map.items())

    def __repr__(self):
        return self.__str__()
