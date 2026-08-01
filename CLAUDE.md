# CLAUDE.md

Guidance for working in the `extendedsql` (ESQL) repo. See the umbrella
`../CLAUDE.md` for how this engine fits the wider `tech-portfolio/`, and `README.md`
plus `.claude/status.md` for syntax, theory, and tracked work.

## What this is

ESQL is a SQL-extension query **engine**, distributed as the `esql` Python package and
used as a pandas DataFrame accessor: `df.esql.query("SELECT cust, prod, quant.avg")`. It
computes multi-aggregate OLAP results (the Phi-operator algorithm) without nested
subqueries. Layout:

- `src/esql/parser/` — turns a query string into a typed clause structure (AST).
- `src/esql/execution/` — computes the grouped result from that structure.

The one real input path is a user-supplied ESQL **query string** evaluated over an
in-memory DataFrame handed to the accessor.

## Commands (uv + make)

```sh
uv sync --extra dev   # runtime + dev deps
make check            # the gate: ruff lint + mypy + pytest
make test             # tests only
make lint             # ruff
make typecheck        # mypy, clean and enforced
make build            # wheel + sdist into dist/ (the in-browser demo installs this wheel)
```

## Conventions

- No em dashes in prose (repo convention).

## Security

This engine inherits the umbrella standard in [`../security-standards.md`](../security-standards.md);
its `data-agent-framework/api/CLAUDE.md` threat model is the worked reference.

**Inherited slice: §1, secure by construction.** The `query` accessor accepts an
**untrusted user query string** (`ESQLAccessor.query`), so the parser and execution path
must be safe against hostile input regardless of where the string arrives from. Trust the
channel, distrust the payload.

**Current posture (honest statement).** The path is **secure by construction, and no
string is ever interpolated into `eval`/`exec`/`pandas.eval`/`compile` or any SQL text.**
Concretely:

- The query is parsed into a **typed AST** (`parser/`), then **structurally interpreted**
  (`execution/` walks the AST and compares Python values). There is no dynamic code
  generation or evaluation anywhere in `src/esql/`.
- **Identifiers bind to an allowlist.** Every column, group, aggregate function, and
  operator is validated against a closed set before use: columns must exist in the handed
  DataFrame's dtypes, aggregate functions must be one of `sum/avg/min/max/count`, operators
  come from fixed lists, group names match a strict `[A-Za-z0-9_]` pattern. An unknown
  identifier raises a `ParsingError`, it is never executed.
- **Values bind as typed data**, parsed and coerced against the target column's dtype
  (numeric, bool, date, or quoted string), never as code. The one value that is not a
  literal, a SUCH THAT **entry value** (`prev.month = month - 1`), is no exception: it
  parses to an `EntryValue` naming a column plus a numeric offset, the column must be one
  of the SELECT grouping attributes, and execution resolves it by dict lookup against the
  grouped row. There is no expression evaluator behind it.

**Bounded surface: no I/O.** The engine reads only the **in-memory DataFrame it is handed**.
It performs no filesystem or network access, opens no data stores, and spawns no
processes, which bounds the attack surface to CPU/memory over caller-provided data.

**Demo security is owned elsewhere.** ESQL's in-browser demo (the Pyodide live editor that
runs the built wheel) lives in the sibling `portfolio/` repo, not here. Its client-side
controls (Pyodide sandbox, CSP, vendored-wheel and runtime integrity, no-exfil, the
report/error funnel) are owned and documented in `portfolio/` per §5 of the standard. Do
not duplicate or re-implement them in this engine.

When adding features (for example the pending nested / multi-grain
aggregation in `.claude/status.md`), preserve this property: parse to typed AST and interpret
structurally, bind identifiers to allowlists and values as data, never build or evaluate
code or SQL from query text.
