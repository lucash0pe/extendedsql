"""The declared shape of a demo dataset asset, plus the validator `build_demo` runs before writing.

`demokit.build_demo` composes a plain dict and `json.dumps` it. That dict is the contract between
this engine, which writes it, and a host front-end, which reads it, and until now it was untyped at
exactly that seam: a key renamed here surfaced downstream as `undefined` with nothing failing in
between.

This declares the shape as JSON Schema and publishes it the way `grammar.py` publishes the grammar
-- as a plain dict, emitted verbatim, with no renaming step on the way through, so there is no
mapping anywhere to fall out of step with what the engine actually writes. A host generates its own
types from `dataset.schema.json` rather than hand-keeping a copy of this shape.

`validate_dataset` is deliberately a small local walker rather than the `jsonschema` package. The
engine's runtime dependencies are installed into Pyodide by the browser demo, where every added
dependency is another wheel to vendor, and `jsonschema` pulls a compiled extension. So the subset of
JSON Schema used below (`$ref`/`$defs`, `type`, `enum`, `properties`, `required`,
`additionalProperties`, `items`) is walked directly and `jsonschema` stays a dev dependency, where
`tests/test_dataset_schema.py` cross-checks the two agree on every case it covers. If the schema
ever needs a keyword this walker does not implement, `validate_dataset` raises rather than ignoring
it, so an unimplemented keyword cannot silently weaken validation.
"""

from __future__ import annotations

from typing import Any

# The keywords `_walk` implements. A schema reaching it with anything else is a programming error
# here, not a bad document, and says so -- an unrecognized keyword would otherwise be skipped and
# the constraint it expresses would quietly stop being checked.
_SUPPORTED_KEYWORDS = frozenset(
    {
        "$ref",
        "$defs",
        "$id",
        "$schema",
        "title",
        "description",
        "type",
        "enum",
        "properties",
        "required",
        "additionalProperties",
        "items",
    }
)

_JSON_TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


DATASET_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/lucash0pe/extendedsql/dataset.schema.json",
    "title": "Dataset",
    "description": (
        "One demo dataset asset, as written by esql.demokit.build_demo: the dataset's metadata, its "
        "column schema, its hand-authored dimensional structure, its SQL-validated examples, and "
        "the build-up walkthrough."
    ),
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "label", "description", "csv", "schema", "structure", "examples", "walkthrough"],
    "properties": {
        "id": {"type": "string", "description": "Dataset identifier. Also names the JSON and CSV files."},
        "label": {"type": "string", "description": "Display name."},
        "category": {
            "type": "string",
            "description": (
                "Optional presentation metadata, only used to group datasets in a multi-dataset "
                "picker. Absent unless the dataset spec declares it."
            ),
        },
        "description": {"type": "string", "description": "Prose blurb. Markdown."},
        "csv": {"type": "string", "description": "Filename of the sample CSV copied alongside this JSON."},
        "schema": {
            "type": "array",
            "description": "One entry per column of the queried table, in table order.",
            "items": {"$ref": "#/$defs/SchemaColumn"},
        },
        "structure": {"$ref": "#/$defs/DatasetStructure"},
        "examples": {
            "type": "array",
            "description": "Curated ESQL queries, each validated against its SQL equivalent at build time.",
            "items": {"$ref": "#/$defs/Example"},
        },
        "walkthrough": {
            "type": "array",
            "description": "One query grown a clause at a time. Validated like the examples but shipped without rows.",
            "items": {"$ref": "#/$defs/WalkStep"},
        },
    },
    "$defs": {
        "ColumnType": {
            "title": "ColumnType",
            "description": "The four value families the engine coerces every column into.",
            "type": "string",
            "enum": ["string", "number", "boolean", "date"],
        },
        "CellValue": {
            "title": "CellValue",
            "description": "One cell of a precomputed result row. Null where the aggregate had nothing to measure.",
            "type": ["string", "number", "boolean", "null"],
        },
        "SchemaColumn": {
            "title": "SchemaColumn",
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "type"],
            "properties": {
                "name": {"type": "string"},
                "type": {"$ref": "#/$defs/ColumnType"},
                "values": {
                    "type": "array",
                    "description": (
                        "The column's distinct values as text, for value completion in a host editor. "
                        "Present only when the column is discrete and its distinct count is within the "
                        "build's cap; absent means 'do not offer completions', not 'no values'. Text "
                        "regardless of the column's type, and unquoted: it is the datum, not the "
                        "literal syntax, so a host quotes it according to `type`."
                    ),
                    "items": {"type": "string"},
                },
            },
        },
        "Example": {
            "title": "Example",
            "description": "One curated query, shipped with the rows the engine returned for it at build time.",
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "tier", "clause", "title", "description", "esql", "sql", "columns", "rows"],
            "properties": {
                "id": {"type": "string"},
                "tier": {
                    "type": "string",
                    "description": (
                        "'starter' -- one simple idea, no OVER, whose SQL is validated but never shown. "
                        "'example' -- a worked query displayed with its SQL equivalent."
                    ),
                    "enum": ["starter", "example"],
                },
                "clause": {
                    "type": "string",
                    "description": (
                        "Which docs stream the example belongs to: a starter chip, one of the four "
                        "clause explainers, or a multi-clause query."
                    ),
                    "enum": ["start", "SELECT", "WHERE", "HAVING", "OVER", "complex"],
                },
                "title": {"type": "string"},
                "description": {"type": "string"},
                "esql": {"type": "string", "description": "The ESQL query, whitespace collapsed to single spaces."},
                "sql": {"type": "string", "description": "The hand-written SQL equivalent, as authored."},
                "columns": {
                    "type": "array",
                    "description": "Result column names, in order. Every row has this many cells.",
                    "items": {"type": "string"},
                },
                "rows": {
                    "type": "array",
                    "description": "The engine's result for `esql`, rounded to 2 decimal places.",
                    "items": {"type": "array", "items": {"$ref": "#/$defs/CellValue"}},
                },
            },
        },
        "WalkStep": {
            "title": "WalkStep",
            "description": "One step of the build-up. Runs live in the host editor, so it carries no rows.",
            "type": "object",
            "additionalProperties": False,
            "required": ["clause", "note", "esql"],
            "properties": {
                "clause": {"type": "string", "description": "The clause this step adds."},
                "note": {"type": "string", "description": "Teaching copy for the step."},
                "esql": {"type": "string", "description": "The query so far, whitespace collapsed."},
            },
        },
        "BranchColumn": {
            "title": "BranchColumn",
            "description": "A column that branches off a dimension (venue -> city/state, date -> month/year).",
            "type": "object",
            "additionalProperties": False,
            "required": ["column"],
            "properties": {"column": {"type": "string"}, "why": {"type": "string"}},
        },
        "StructureDimension": {
            "title": "StructureDimension",
            "type": "object",
            "additionalProperties": False,
            "required": ["column"],
            "properties": {
                "column": {"type": "string"},
                "role": {
                    "type": "string",
                    "description": "Free text -- 'entity', 'geo', 'time', 'position', 'relation', 'provenance', ...",
                },
                "direction": {"$ref": "#/$defs/SegueDirection"},
                "why": {"type": "string"},
                "branchesTo": {"type": "array", "items": {"$ref": "#/$defs/BranchColumn"}},
            },
        },
        "SegueDirection": {
            "title": "SegueDirection",
            "description": (
                "Which side of a relation a column names. 'out' = ran into the next; 'in' = came "
                "from the previous."
            ),
            "type": "string",
            "enum": ["out", "in"],
        },
        "StructureFlag": {
            "title": "StructureFlag",
            "type": "object",
            "additionalProperties": False,
            "required": ["column"],
            "properties": {
                "column": {"type": "string"},
                "direction": {"$ref": "#/$defs/SegueDirection"},
                "why": {"type": "string"},
            },
        },
        "StructureMeasure": {
            "title": "StructureMeasure",
            "type": "object",
            "additionalProperties": False,
            "required": ["column"],
            "properties": {
                "column": {"type": "string"},
                "unit": {"type": "string"},
                "note": {"type": "string"},
            },
        },
        "DatasetStructure": {
            "title": "DatasetStructure",
            "description": (
                "How the flat columns relate: the grain, the dimensions and what branches off them, "
                "the boolean flags, and the measures. Hand-authored per dataset and passed through "
                "verbatim; `build_demo` checks it only names real columns."
            ),
            "type": "object",
            "additionalProperties": False,
            "required": ["grain", "dimensions", "flags", "measures"],
            "properties": {
                "grain": {"type": "string", "description": "What one row is, in prose."},
                "dimensions": {"type": "array", "items": {"$ref": "#/$defs/StructureDimension"}},
                "flags": {"type": "array", "items": {"$ref": "#/$defs/StructureFlag"}},
                "measures": {"type": "array", "items": {"$ref": "#/$defs/StructureMeasure"}},
            },
        },
    },
}


class DatasetSchemaError(Exception):
    """A dataset document does not match `DATASET_SCHEMA`. Carries every failure, not just the first."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        listed = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"dataset asset does not match DATASET_SCHEMA:\n{listed}")


def validate_dataset(document: Any, schema: dict[str, Any] | None = None) -> None:
    """Check `document` against `DATASET_SCHEMA`, raising `DatasetSchemaError` listing every failure.

    Returns None when the document matches. Reports all failures rather than the first, because the
    caller is a build step and one round trip per bad key is a poor way to fix a dataset spec.
    """
    root = DATASET_SCHEMA if schema is None else schema
    errors: list[str] = []
    _walk(document, root, root, "$", errors)
    if errors:
        raise DatasetSchemaError(errors)


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    """Follow a local `$ref` (`#/$defs/Name`) to the schema it names."""
    ref = schema.get("$ref")
    if ref is None:
        return schema
    if not ref.startswith("#/"):
        raise ValueError(f"only local refs are supported, got: {ref}")
    target: Any = root
    for token in ref[2:].split("/"):
        target = target[token]
    return _resolve(target, root)


def _type_name(node: Any) -> str:
    """The JSON type name for a Python value, for error messages. bool is checked first, since
    Python's bool is a subclass of int and would otherwise report as a number."""
    if isinstance(node, bool):
        return "boolean"
    if isinstance(node, int | float):
        return "number"
    for name, python_type in _JSON_TYPES.items():
        if isinstance(node, python_type):
            return name
    return type(node).__name__


def _matches_type(node: Any, name: str) -> bool:
    if name == "number":
        return isinstance(node, int | float) and not isinstance(node, bool)
    if name == "boolean":
        return isinstance(node, bool)
    expected = _JSON_TYPES.get(name)
    if expected is None:
        raise ValueError(f"unsupported schema type: {name}")
    # A bool is an int, so it would otherwise satisfy any type whose Python class it subclasses.
    return isinstance(node, expected) and not isinstance(node, bool)


def _walk(node: Any, schema: dict[str, Any], root: dict[str, Any], path: str, errors: list[str]) -> None:
    schema = _resolve(schema, root)

    unsupported = set(schema) - _SUPPORTED_KEYWORDS
    if unsupported:
        raise ValueError(
            f"{path}: DATASET_SCHEMA uses keywords validate_dataset does not implement: {sorted(unsupported)}"
        )

    declared = schema.get("type")
    if declared is not None:
        names = [declared] if isinstance(declared, str) else list(declared)
        if not any(_matches_type(node, name) for name in names):
            errors.append(f"{path}: expected {' or '.join(names)}, got {_type_name(node)}")
            return

    if "enum" in schema and node not in schema["enum"]:
        errors.append(f"{path}: {node!r} is not one of {schema['enum']}")
        return

    if isinstance(node, dict):
        for key in schema.get("required", []):
            if key not in node:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in sorted(set(node) - set(properties)):
                errors.append(f"{path}: unexpected property {key!r}")
        for key, value in node.items():
            if key in properties:
                _walk(value, properties[key], root, f"{path}.{key}", errors)

    elif isinstance(node, list) and "items" in schema:
        for index, item in enumerate(node):
            _walk(item, schema["items"], root, f"{path}[{index}]", errors)
