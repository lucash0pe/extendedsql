"""`DATASET_SCHEMA` and the validator `build_demo` runs against it.

Two jobs here. The first half pins the constraints that matter -- what is required, what is
rejected, and that every failure is reported rather than just the first. The second half
cross-checks `validate_dataset` against the real `jsonschema` package on every one of those
documents, which is what earns the local walker: it is a subset implementation, so it is only
trustworthy for as long as something proves it agrees with the specification it is a subset of.
"""

from __future__ import annotations

import copy

import jsonschema
import pytest

from esql.dataset_schema import DATASET_SCHEMA, DatasetSchemaError, validate_dataset


def _minimal() -> dict:
    """The smallest document that validates. Every test mutates a copy of this."""
    return {
        "id": "sales",
        "label": "Sales",
        "description": "A tiny table.",
        "csv": "sales.csv",
        "schema": [
            {"name": "cust", "type": "string", "values": ["Dan", "Helen"]},
            {"name": "quant", "type": "number"},
        ],
        "structure": {
            "grain": "one row per sale",
            "dimensions": [{"column": "cust", "role": "entity", "why": "who bought"}],
            "flags": [],
            "measures": [{"column": "quant", "unit": "units"}],
        },
        "examples": [
            {
                "id": "by-cust",
                "tier": "starter",
                "clause": "SELECT",
                "title": "Per customer",
                "description": "One row per customer.",
                "esql": "SELECT cust, quant.sum",
                "sql": "SELECT cust, SUM(quant) FROM sales GROUP BY cust",
                "columns": ["cust", "quant_sum"],
                "rows": [["Dan", 825], ["Helen", None]],
            }
        ],
        "walkthrough": [{"clause": "SELECT", "note": "Start here.", "esql": "SELECT cust"}],
    }


def test_minimal_document_validates():
    assert validate_dataset(_minimal()) is None


def test_optional_category_is_accepted():
    document = _minimal()
    document["category"] = "retail"
    assert validate_dataset(document) is None


def test_missing_required_property_is_reported_with_its_path():
    document = _minimal()
    del document["csv"]
    with pytest.raises(DatasetSchemaError) as error:
        validate_dataset(document)
    assert error.value.errors == ["$: missing required property 'csv'"]


def test_unexpected_property_is_rejected():
    document = _minimal()
    document["schema"][0]["kind"] = "string"
    with pytest.raises(DatasetSchemaError) as error:
        validate_dataset(document)
    assert error.value.errors == ["$.schema[0]: unexpected property 'kind'"]


def test_wrong_type_names_what_it_got():
    document = _minimal()
    document["examples"][0]["columns"] = "cust"
    with pytest.raises(DatasetSchemaError) as error:
        validate_dataset(document)
    assert error.value.errors == ["$.examples[0].columns: expected array, got string"]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema", 0, "type"), "text"),
        (("examples", 0, "tier"), "advanced"),
        (("examples", 0, "clause"), "SUCH THAT"),
    ],
)
def test_values_outside_an_enum_are_rejected(path, value):
    document = _minimal()
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(DatasetSchemaError):
        validate_dataset(document)


def test_a_missing_clause_is_reported_rather_than_defaulted():
    """`build_demo` omits `clause` when the spec did not set one, so the schema is what names it."""
    document = _minimal()
    del document["examples"][0]["clause"]
    with pytest.raises(DatasetSchemaError) as error:
        validate_dataset(document)
    assert error.value.errors == ["$.examples[0]: missing required property 'clause'"]


def test_every_cell_value_family_is_allowed():
    document = _minimal()
    document["examples"][0]["columns"] = ["a", "b", "c", "d"]
    document["examples"][0]["rows"] = [["text", 1.5, True, None]]
    assert validate_dataset(document) is None


def test_a_cell_may_not_be_a_nested_structure():
    document = _minimal()
    document["examples"][0]["rows"] = [[{"sum": 1}]]
    with pytest.raises(DatasetSchemaError) as error:
        validate_dataset(document)
    assert error.value.errors == ["$.examples[0].rows[0][0]: expected string or number or boolean or null, got object"]


def test_all_failures_are_reported_not_just_the_first():
    document = _minimal()
    del document["id"]
    del document["label"]
    document["examples"][0]["tier"] = "advanced"
    with pytest.raises(DatasetSchemaError) as error:
        validate_dataset(document)
    assert len(error.value.errors) == 3


def test_the_walker_refuses_a_keyword_it_does_not_implement():
    """An unimplemented keyword must raise, not be skipped -- a skipped keyword is a constraint that
    silently stopped being checked."""
    schema = {"type": "object", "properties": {"n": {"type": "number", "minimum": 3}}}
    with pytest.raises(ValueError, match="minimum"):
        validate_dataset({"n": 1}, schema)


# --------------------------------------------------------------------------------------------
# The local walker against the real thing. `jsonschema` is imported outright rather than skipped
# past: it is a dev dependency, and a cross-check that quietly does not run leaves the walker
# unproven exactly when someone has broken the environment.
# --------------------------------------------------------------------------------------------


def _mutations() -> list[tuple[str, dict]]:
    """Every document the tests above assert on, plus the valid ones, labelled for failure output."""
    cases: list[tuple[str, dict]] = [("minimal", _minimal())]

    with_category = _minimal()
    with_category["category"] = "retail"
    cases.append(("category", with_category))

    every_cell = _minimal()
    every_cell["examples"][0]["columns"] = ["a", "b", "c", "d"]
    every_cell["examples"][0]["rows"] = [["text", 1.5, True, None]]
    cases.append(("cell families", every_cell))

    for label, mutate in [
        ("missing csv", lambda d: d.pop("csv")),
        ("extra property", lambda d: d["schema"][0].__setitem__("kind", "string")),
        ("wrong type", lambda d: d["examples"][0].__setitem__("columns", "cust")),
        ("bad column type", lambda d: d["schema"][0].__setitem__("type", "text")),
        ("bad tier", lambda d: d["examples"][0].__setitem__("tier", "advanced")),
        ("bad clause", lambda d: d["examples"][0].__setitem__("clause", "SUCH THAT")),
        ("missing clause", lambda d: d["examples"][0].pop("clause")),
        ("nested cell", lambda d: d["examples"][0].__setitem__("rows", [[{"sum": 1}]])),
        ("bool where string expected", lambda d: d["schema"][0].__setitem__("name", True)),
        ("int where string expected", lambda d: d.__setitem__("label", 3)),
        ("structure missing grain", lambda d: d["structure"].pop("grain")),
        ("bad segue direction", lambda d: d["structure"]["flags"].append({"column": "x", "direction": "sideways"})),
        ("null where object expected", lambda d: d.__setitem__("structure", None)),
    ]:
        document = _minimal()
        mutate(document)
        cases.append((label, document))
    return cases


_CROSS_CHECK_CASES = _mutations()


@pytest.mark.parametrize(
    ("label", "document"), _CROSS_CHECK_CASES, ids=[label for label, _ in _CROSS_CHECK_CASES]
)
def test_local_walker_agrees_with_jsonschema(label, document):
    validator = jsonschema.Draft202012Validator(DATASET_SCHEMA)
    reference_ok = validator.is_valid(document)

    try:
        validate_dataset(copy.deepcopy(document))
        local_ok = True
    except DatasetSchemaError:
        local_ok = False

    assert local_ok == reference_ok, f"{label}: local walker says {local_ok}, jsonschema says {reference_ok}"


def test_the_schema_is_itself_a_valid_json_schema():
    jsonschema.Draft202012Validator.check_schema(DATASET_SCHEMA)
