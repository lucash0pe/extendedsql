# Status — ESQL

Working status for the engine. Opened 2026-07-28.

The single tracking file for this repo (it replaced `BACKLOG.md`). Two halves: **what is in flight**
at the top, as streams with their sequencing and the decisions that are not yet code, then **the
settled record** below of what shipped and why. Move an item down when it lands.

The consuming half of the front-end work is tracked in the sibling `portfolio/` repo, which is
private.

---

## Stream F — a front-end package (`frontend/`) — STOOD DOWN (2026-07-29)

**Reversed before anything was built.** Portfolio decided against consuming it, so F1–F4 are parked,
F5 shipped in a different form (see Stream J below), and F6 is moot while nothing moves. No
`package.json`, no second CI lane, no tarball: this repo stays Python-only.

The reasoning, since it inverts what the stream said:

- **The contract argument is better served in Python.** Stream F's own strongest claim was that
  `demokit` *writes* the dataset JSON while the front-end *reads* it, with nothing enforcing that
  across two repos. Moving the reader here fixes it; declaring the shape here fixes it better and
  cheaper. `build_demo` took `dataset: dict` and `json.dumps`'d it, untyped at the exact seam the
  stream existed to protect. That is what J1 does instead.
- **The assist cannot move.** It answers "what can go here" synchronously on every keystroke,
  including before Pyodide has warmed (~20 MB; curated results paint from the build while it loads).
  Anything requiring an engine call puts the caret menu behind that load, on the interaction that
  teaches the language.
- **The components cannot move** without dragging the host's design tokens with them.
- That leaves reuse, which Stream F itself ranked second, and which stays theoretical until a second
  host exists. The assist is pure functions over published data, so it stays portable if one ever does.

The seam that replaces it is the one already working: **the engine publishes what is legal, the host
does the caret work.** `esql.GRAMMAR` in v1.5.0 was the right move and portfolio now reads it in
place of rules it used to hand-mirror.

---

## Stream J — publishing the demo asset contract

The counterpart to Stream G. G published what is *legal* (the grammar); this publishes the *shape*
of what `demokit` writes, and the *data* a host needs to complete a value. Both items below are
built and green; version bumped `1.6.0 -> 1.7.0`, **not yet committed, tagged or pushed**. The gate
is green at **207 tests** (was 162).

- [x] **J1. `dataset.schema.json`.** Shipped as `esql.DATASET_SCHEMA` (`src/esql/dataset_schema.py`):
  the `<id>.json` asset declared as JSON Schema. `build_demo` validates its output dict against it
  before writing anything, and emits the schema into the same output dir as `grammar.json`. Same
  pattern as the grammar export — emitted verbatim, no renaming step, so there is no mapping to fall
  out of step. Portfolio generates its TypeScript types from it rather than hand-keeping them.

  **Why the validator is local rather than `jsonschema`.** The engine's runtime deps get vendored
  into Pyodide for the browser demo, and `jsonschema` pulls a compiled extension (`rpds-py`), so it
  cannot become a runtime dependency. `validate_dataset` walks the subset actually used (`$ref`,
  `type`, `enum`, `properties`, `required`, `additionalProperties`, `items`) in ~40 lines, and
  `jsonschema` stays a dev dependency where `tests/test_dataset_schema.py` cross-checks that the two
  agree on all 16 documents it covers. A keyword the walker does not implement **raises** rather than
  being skipped, so an unimplemented keyword cannot silently weaken validation.

  Two things it caught immediately: `build_demo` defaulted a missing `clause` to `"example"`, which
  is not one of the values a host knows (`start`/`SELECT`/`WHERE`/`HAVING`/`OVER`/`complex`) — the
  default is gone and the schema now names it as missing; and validation runs *before* `out_dir` is
  created, so a failed build writes nothing rather than leaving a partial asset.

- [x] **J2. Capped distinct values per column.** Each `schema` entry now carries `values: string[]`,
  so `WHERE song = '` can offer real song names from build-time data with no Pyodide round trip,
  which is what keeps the host's assist pure and synchronous. Capped at
  `demokit.DISTINCT_VALUE_CAP = 500` and omitted entirely above it — absent means "do not offer
  completions", which is distinct from `[]`, "there are none". Floats are taken as the continuous
  case (a duration in seconds has no value worth completing) while discrete numbers — a month, a set
  position — are integers and do get values. Values are the datum and not the literal syntax
  (unquoted, bools lowercase, dates ISO); the host quotes according to the entry's `type`.

  It lives here rather than in portfolio's `backend/esql/` because `build_demo` composes the whole
  output dict — a dataset's `demo.py` only hands it a spec.

**Portfolio-side follow-up, one line, required.** `DATASET_SCHEMA` is a new name in `esql.__all__`,
so `backend/esql/build.sh`'s export guard fires on the next wheel: it exits with "esql now exports
['DATASET_SCHEMA'], which grammar.json does not account for." That is the guard working as designed.
The fix is adding `"DATASET_SCHEMA"` to its `NOT_GRAMMAR` set — it is not a token set. Checked
against the assets portfolio ships today: both `songs.json` and `coffee.json` validate against the
schema unchanged, so nothing else breaks.

---

## Stream G — grammar export

**`slot_kinds` + `accepts` are now a live extension point with a real consumer.** v1.6.0's
`entry_value` reached the demo as *nothing*: it is a new slot kind plus `SUCH THAT`'s `accepts`
growing, with no new `esql.__all__` export, so portfolio's export-diff guard did not fire, and its
per-clause suggestion logic branches on clause *names* rather than on `accepts`. Same shape as the
`HAS` finding one level up. The fix is portfolio-side and queued there; nothing to do here. Worth
recording because it sets the obligation going the other way: **new grammar surface has to be
expressible in `slot_kinds`/`accepts`**, since that is the channel a host actually reads.

The front-end currently hand-mirrors rules this engine owns: which slot kinds each clause accepts,
that `count` is the only aggregate legal on a non-numeric column (mirroring `_parse_aggregate`), that
`SUCH THAT` needs an `OVER` to scope, and that clause order is fixed. The build already reads
`KEYWORDS`, `AGGREGATE_FUNCTIONS` and `CONDITIONAL_OPERATORS` straight off the wheel into a
`grammar.json`, so the pattern exists. It just does not reach far enough, and the gap is silent: a
clause gaining a rule upstream simply goes unreflected downstream.

- [x] **G1. Emit the per-clause shapes.** Shipped in v1.5.0 as `esql.GRAMMAR` (`src/esql/grammar.py`):
  per clause, what it accepts, which operators it takes, what it requires, whether it repeats, plus
  a slot-kind glossary and the aggregate dtype rule. Plain dicts and lists, so `json.dumps` is the
  whole export step.

  **Honest about what "generated from the parser" turned out to mean.** The parser is imperative,
  not a declarative grammar, so there is nothing to mechanically generate from without restructuring
  it, which the lean ladder does not justify. What ships instead: the token-set dimension *is* single
  sourced (`WHERE_OPERATORS` / `SUCH_THAT_OPERATORS` / `HAVING_OPERATORS` and
  `DTYPE_AGNOSTIC_AGGREGATE_FUNCTIONS` are constants the parser reads, and `_parse_aggregate` no
  longer names `count` itself), and every remaining claim is bound to behavior by
  `tests/parser/test_grammar.py`, which runs the real parser through `validate()` and asserts each
  listed operator parses in that clause and each unlisted one raises. Verified the guard bites: making
  `HAVING_OPERATORS` claim CONTAINS fails the test rather than reaching the demo. That kills the
  silent-drift failure mode, which was the point, without pretending the description is generated.

- [ ] **G2. A guard for the prose.** The clause reference cards are hand-written and only the keyword
  list is asserted today. G1 gives the cards something to be checked against: they can now be
  generated from `GRAMMAR` or asserted to agree with it.

---

## Stream H — language features

H1 shipped; see the settled record. What it leaves open:

- [x] **H2. Rename the unbuilt semi-join.** `CONTAINS` now names the substring operator H1 shipped,
  so the grain-bridging semi-join in the settled record below could not keep that name. Decided
  2026-07-28: it is **`HAS`** (`WHERE date HAS song = 'Dark Star'`). Nothing was built under the old
  name, so this was a rename in the design notes only, done here and in `CLAUDE.md`.

---

## Toolchain note — always `uv run python -m <tool>`

`uv run pytest` does **not** run this project's pytest. The console script fails to spawn under the
project environment and the call falls through to a system Python 3.11
(`/Library/Frameworks/Python.framework/Versions/3.11/bin/pytest`), which then errors on 3.12-only
syntax. Recorded so it is not rediscovered a third time: this is the same failure as the `uv run
mypy` bug fixed in v1.5.0, where `make typecheck` had been erroring out before mypy ran and the
recorded error count went stale for months.

Nothing in the repo is affected — the `Makefile` and `.github/workflows/ci.yaml` both use
`uv run python -m pytest`, which is the form every target should keep using.

---

# The settled record

What shipped and why. Carried over verbatim from `BACKLOG.md`.

Working backlog for the ESQL engine. Status as of 2026-07-23.

**Gate:** `make check` (ruff lint + pytest) is green, **73 tests pass**. `make typecheck`
(mypy) is configured but not yet clean (see Remaining). Current version `1.1.0`.

---

## 1. Bugs — DONE

All fixed and covered by the now-meaningful integration suite (see §3).

- [x] **BUG-1 — Installed package unimportable.** All internal imports were `from src.esql...`;
  the wheel installs as `esql`. Rewrote to `from esql...`; the built wheel now packages `esql/`
  at top level and `import esql` works from any cwd (verified in an isolated env).
- [x] **BUG-2 — `x or np.nan` dropped legitimate zeros.** `grouped_row.py` now uses
  `pd.isna(value)` for missingness. `count`/`avg`/`min` over zeros are correct (verified: count 3,
  avg 10.0, min 0 on `[0,10,20]`).
- [x] **BUG-3 — `funtion` typo → NameError on global `avg`.** Fixed to `function`.
- [x] **BUG-4 — `if not column_index:` treated column 0 as missing.** Now `is None`.
- [x] **BUG-5 — NameError in the unknown-operator error path.** References `operator` now.
- [x] **BUG-6 — `math.isnan` crashed on non-numeric `count`.** The `pd.isna` switch also fixed
  this; `count` over a string column works (verified).
- [x] **BUG-7 — Type-name typos / dead code.** `Global_Aggregate` → `GlobalAggregate`; the HAVING
  NOT branch now builds `NotAggregateCondition`; `CompoundAggregateCondition.operator` was
  `list["ConditionType"]` (undefined) → `Literal[AND, OR]`; `ParsedQuery.such_that` was
  `ParsedSuchThatSection` → `ParsedSuchThatClause`.

### Test-suite bugs found and fixed (the integration suite was vacuous)
- [x] `_test_query` built **both** comparison sets from `esql_df`, so every integration test
  compared ESQL to itself and could never fail. Fixed to compare `sql_df` vs `esql_df`.
- [x] Reference SQL used **non-zero-padded date literals** (`'2020-4-13'`, `'2017-1-1'`) that
  sqlite compares as plain strings (wrong), while ESQL parses them as real dates. Padded the
  literals; ESQL and SQL now agree.
- [x] Duplicate `def test_order_by_sort` (one silently shadowed the other) → renamed; both run.
- [x] Shared `sales_test_data` fixture lived in one test module; moved to `tests/conftest.py`
  (CWD-independent path) so all modules resolve it.

## 2. Stack modernization — DONE (parity with `data-agent-framework`)

- [x] **Poetry → uv.** PEP 621 `[project]`, `uv sync --extra dev`, `poetry.lock` removed.
- [x] **Build backend** poetry-core → **hatchling** (`packages = ["src/esql"]`).
- [x] **ruff** (`line-length 120`, `E,F,W,I,UP,B,SIM,RUF`) — clean over `src` and `tests`
  (tests get a scoped `E501` ignore for long embedded query strings).
- [x] **mypy** configured (`make typecheck`) — see Remaining for the cleanup.
- [x] **Python 3.12** (`.python-version`, `requires-python >=3.12`, ruff/mypy `py312`).
- [x] **Pruned unused deps** (`flask`, `psycopg2-binary`); `python-dotenv` moved to the dev extra
  (the integration test uses stdlib `sqlite3`, not Postgres).
- [x] **Makefile** in `uv run ...` style: `install`, `test`, `test-fast`, `lint`, `format`,
  `typecheck`, `build`, `check`.

## v1.0.0 — SHIPPED (2026-07-21, tagged `v1.0.0`)

- [x] **CI** — uv-based workflow runs ruff + pytest across 3.12/3.13 on linux/macos/windows.
- [x] **README** — install snippet fixed (`git+https://github.com/lucash0pe/extendedsql.git`), Python
  3.12, added a Development section.
- [x] **Version** — bumped `0.1.0 → 1.0.0`; wheel + sdist build clean. Local tag only (not pushed).

## v1.0.1 — empty-group HAVING crash (2026-07-23, commit `f7440e9`)

- [x] **Empty-group HAVING crash.** A HAVING over a group with no matching rows crashed the
  evaluator. Fixed, and the parser error messages were hardened. Covered by the 3 tests in
  `tests/execution/test_empty_group_having.py`. Bumped `1.0.0 → 1.0.1`.

## v1.1 — In progress

- [x] **Curated demo examples, shipped as `esql.demokit`.** The bespoke `examples/` generators
  were dropped (commit `068a0fd`) in favor of `src/esql/demokit.py`: `build_demo` takes a dataset
  spec, runs each ESQL query through this engine and its SQL equivalent through sqlite over the
  same CSV, asserts the two agree as a set, and writes the demo JSON the portfolio ESQL editor
  loads. Each dataset's demo asset is generated by its `datasets/<name>/esql/demo.py`, which calls
  `build_demo`. The demo data lives in the `datasets` repo, not here.
- [x] **Pyodide path verified.** The built wheel installs via `micropip` in a real Pyodide 0.27.2
  runtime (pandas 2.2.3 + numpy 2.0.2 shipped by Pyodide satisfy our deps; beartype pulled from
  PyPI) and `df.esql.query(...)` returns results identical to the native engine. No engine changes
  needed for the browser. **Recommendation:** self-host the Pyodide runtime + wheels (esql,
  beartype) in the portfolio site's `public/` on Cloudflare so the ESQL demo depends only on the site
  loading (no third-party CDN, no mini).
- [x] **BUG-8 (found via example generation) — aggregate reused in SELECT + HAVING.** An aggregate
  named in both clauses (e.g. `quant.sum`) was appended twice, so it was accumulated twice per row
  (silently **doubling** sum/count) and, for avg, converted twice (`'float' object is not
  subscriptable`). `parse.py` now dedups the merge. Regression tests cover both. *(This bug shipped
  in v1.0.0 and is fixed on `main` for v1.1.)*

- [x] **EMF support (headline feature).** Shipped in v1.6.0; see that entry below.
- [x] **HAS / semi-join predicate (headline feature, requested for the GD demo).** Shipped in
  v1.4.0; see that entry below. Still open on the demo side: an example wired into the ESQL demo,
  which needs `portfolio` (the frontend) and its data.
- [ ] **Nested / multi-grain aggregation (headline feature — the grain-bridging companion to
  HAS).** Aggregate at a declared finer grain, then roll *that* up — an aggregate of an
  aggregate, in one pass, no subqueries (the MFQueries thesis taken a step further). Motivating
  case: the GD archive is one song-grain table, but a "show" is the derived grain `(venue, date)`.
  Today you can group *to* the show grain, but you cannot put a song-level measure beside a
  show-level roll-up, nor take "avg songs-per-show by venue" (an avg of a per-show count). This
  makes a separate `shows` table unnecessary — shows become "aggregate at the `(venue, date)`
  grain." The dataset already *declares* the grain (in the shared `datasets/<src>/*.structure.json`:
  "a show is (venue, date)"), so the language can read it. Sketch (uncommitted): a `PER <grain>`
  sub-aggregate, e.g. `SELECT venue, songs_per_show.avg PER show (venue, date) WITH songs_per_show
  = count PER show`. Work: parser grammar for the sub-grain + a two-level execution pass (compute
  the fine-grain aggregate, then the output-grain aggregate over it) + tests + a
  `public/docs/syntax.md` section + an ESQL demo example. Pairs with HAS: HAS
  *filters* one grain by another; this *measures* across grains. Design captured now; build parked
  until the datasets/rename plumbing lands.
- [ ] **mypy clean pass.** 156 errors (the count was stale at 143 because `make typecheck` called
  `uv run mypy`, whose console script does not spawn, so the target errored out before reaching
  mypy; fixed in v1.5.0 to `uv run python -m mypy`, the form every other target uses). All from
  the dynamic evaluator: union comparisons
  (`[operator]`) and TypedDict key-narrowing (`[typeddict-item]`/`[index]`) mypy can't follow
  through runtime `'group' in aggregate` checks. Options: type the cell/accumulator boundaries as
  `Any` (honest — a `_data_map` slot holds int|float|date or an avg `{'sum','count'}` dict), or
  model parsed conditions as dataclasses. Until then `typecheck` stays advisory.
- [x] **Push the release** — done 2026-07-28. PR #2 (`v1.0.1` through `v1.4.0`) and PR #3
  (`v1.5.0`) merged to `main`, all tagged and pushed (`lucash0pe/extendedsql`). `v1.1.2` is
  deliberately untagged: it was never a release, only a version an auto-checkpoint commit wrote to
  `pyproject.toml`, and `1.1.1` never existed at all. Releasing is now per-PR, so this item stays
  closed rather than reopening each time.

## v1.3.0 — the CONTAINS operator (2026-07-28)

- [x] **String containment (H1).** `WHERE prod CONTAINS 'err'` keeps rows whose text column holds
  the substring anywhere in it, so a filter is no longer limited to exact equality. Works in SUCH
  THAT too, since both clauses share `_split_condition` and `_parse_condition_value`. Bumped
  `1.2.0 → 1.3.0`; the gate is green at **100 tests** (was 88).

  Three decisions worth keeping:

  - **Case insensitive, with no case-sensitive variant.** A case-sensitive substring search is
    rarely the intent, and offering both would need extra syntax to choose between them. It also
    makes the SQL equivalent sqlite's `LIKE '%x%'`, which is already ASCII-case-insensitive, so
    `demokit`'s ESQL↔SQL set-equality check holds. `test_contains_where_query` in
    `tests/execution/test_execution_integration.py` asserts that parity directly.
  - **Not general case-insensitivity.** Making `=` insensitive too was considered and rejected: it
    would break parity with sqlite's case-sensitive `=` and silently change every existing query.
  - **Rejected in HAVING**, with its own message rather than the generic numeric-parse failure.
    HAVING compares an aggregate and every aggregate is numeric.

  `CONTAINS` is the first word operator in `CONDITIONAL_OPERATORS`, which previously held only
  symbols. `_split_condition` now matches word operators on word boundaries via
  `_operator_starts_at`, so a column named `contains_tax` is not a split point. Covered by
  `tests/execution/test_contains.py` (11 tests) plus the sqlite parity test above.

  The demo picks the operator up with no work on its side, since `CONDITIONAL_OPERATORS` already
  exports through `grammar.json`. Binding is unchanged from what `CLAUDE.md` commits to: the
  pattern is a quoted literal bound as data, compared with Python's `in`, never a compiled regex
  and never code.

## v1.4.0 — the HAS semi-join predicate (2026-07-28)

- [x] **Semi-join predicate.** `WHERE state HAS prod = 'Ham'` keeps rows whose *group* contains a
  row matching a condition, so a query reaches across two grains of one table without a join.
  `<key> HAS <condition>` = keep rows whose `<key>` value belongs to some row satisfying
  `<condition>`. Bumped `1.3.0 → 1.4.0`; the gate is green at **119 tests** (was 100).

  **Not a comparison, so not one of `CONDITIONAL_OPERATORS`.** What follows `HAS` is a whole
  condition, not a value, so it gets its own exported constant `SEMI_JOIN_OPERATOR` and its own
  node type `SemiJoinCondition` in the WHERE union. Anything valid in a WHERE condition nests
  inside it, including `CONTAINS` and another `HAS`.

  **It is the first condition that is not a question about the row in hand**, which drove the
  execution shape. `_resolve_semi_joins` walks the WHERE tree once before the row loop and replaces
  each HAS node with the concrete set of key values its inner condition matched; the per-row pass
  is then an ordinary membership test. It returns a new tree rather than mutating the parsed AST.

  Decisions worth keeping:

  - **The inner condition reads the unfiltered table.** The rest of the WHERE clause is what the
    semi-join helps filter, so reading the filtered table would make the two mutually dependent.
    `WHERE state HAS prod = 'Ham' AND prod != 'Ham'` therefore returns the non-Ham rows in
    Ham-selling states, not nothing. This matches SQL's independent subquery, and
    `test_has_semi_join_combined_with_a_row_filter` asserts that against sqlite directly.
  - **`AND`/`OR` bind looser than `HAS`**, so `a HAS b = 1 AND c = 2` is `(a HAS b = 1) AND
    (c = 2)`. Parens pull a compound condition inside. The alternative would make the common
    "semi-join, then filter" shape need parens every time.
  - **WHERE only.** SUCH THAT and HAVING run after grouping and reject it with their own messages
    rather than a confusing parse failure.
  - **Case sensitivity is inherited, not chosen** (settled before the build, unchanged by it): the
    keyword is case-insensitive for free, the inner condition keeps whatever its own operator does,
    and the key match is case-sensitive like every other grouping in the engine.

  Covered by `tests/execution/test_has.py` (17 tests) plus two sqlite parity tests in
  `test_execution_integration.py` that check `HAS` against `IN (SELECT ...)` over `sales.csv`.
  Binding is unchanged from what `CLAUDE.md` commits to: the key set is built from data values and
  membership-tested, with no code or SQL constructed from query text.

## v1.5.0 — the grammar export (2026-07-28)

- [x] **`esql.GRAMMAR` (G1)** and **`make typecheck` fixed.** See the G1 entry above for the export
  and for what "generated from the parser" honestly amounts to. The gate is green at **142 tests**
  (was 119).

  `make typecheck` had been calling `uv run mypy`, whose console script fails to spawn, so the
  target errored before mypy ran and the recorded error count (143) was stale for however long that
  was true. Now `uv run python -m mypy`, matching every other target, and the real count is 156. The
  cleanup itself is still open above.

## v1.6.0 — EMF entry values (2026-07-28)

- [x] **Entry values in SUCH THAT.** `SUCH THAT prev.cust = cust and prev.month = month - 1` scopes
  a group against the output row being computed rather than against a constant, which is the EMF
  (Extended Multi-Feature) half of the papers. Bumped `1.5.0 → 1.6.0`; the gate is green at
  **162 tests** (was 142).

  **The stub was the small half.** `_parse_emf_condition_value` had sat as a TODO and the `is_emf`
  flag had been parsed and ignored since v1.0, which made this look like a parsing job. It was not.
  The rows that satisfy an entry-value condition for group *G* belong to a **different grouping
  combination** than *G* (`month - 1` is last month's group), and the such-that pass routed every
  matching row into its *own* combination. Filling in the parser alone would have returned
  confidently wrong numbers. Execution now picks between two passes per section:
  `_accumulate_by_row` for a section of constants, unchanged and one scan for the clause, and
  `_accumulate_by_entry_value`, which fixes the grouped row first, binds its entry values into the
  section, then scans. That second one costs a scan per output row, which is why the constant case
  keeps its own path rather than both folding into the general form.

  **Binding mirrors `_resolve_semi_joins`.** Same shape as HAS in v1.4.0: a condition that is not a
  question about the row in hand gets answered up front into a new tree, so `_evaluate_condition`
  learns nothing about entry values and the parsed AST stays reusable across grouped rows. An
  unbound entry value reaching the evaluator raises rather than silently matching nothing, since
  arriving there at all means the section took the wrong pass.

  Decisions worth keeping:

  - **The same-group linkage is explicit, not implied.** `prev.cust = cust` has to be written. The
    constant form gets that restriction for free from the row-routing, and reproducing it here
    would have made `prev.month = month - 1` alone mean something no syntax could express.
  - **The reference must be a SELECT grouping attribute**, not any column: a grouped row holds no
    single value for a column it did not group on. This is also what keeps the identifier-allowlist
    property in `CLAUDE.md` intact, so the value slot still binds to a closed set.
  - **Comparisons are checked by value family at parse time** (`_dtype_kind`: numeric, bool, date,
    text), and only a numeric attribute can carry an offset. Without that check, `g1.quant = cust`
    would parse and then raise a raw `TypeError` out of the row loop, which in the browser demo
    reaches the visitor.
  - **Rejected in WHERE by name.** WHERE runs before grouping, so there is no grouped row to read;
    it says so rather than falling through to "invalid value". HAVING already rejects a non-numeric
    comparison value, so it needed nothing.
  - **`_parse_condition_value` lost its `is_emf` return and its unused `column_dtypes` parameter.**
    Entry values are recognized in the two condition parsers before literal parsing is reached, so
    the tuple return had no second case left to carry.

  Covered by `tests/execution/test_entry_values.py` (18 tests) plus two in
  `tests/parser/test_grammar.py` binding the new `entry_value` slot kind to parser behavior.
  Verified the suite bites: forcing `_has_entry_value` to return False fails 11 of them.

## 3. Engine-side prep for the ESQL demo

The demo frontend lives in `portfolio/site/esql/` and its data in `portfolio/backend/esql/`
(`<name>/demo.py`, which calls `esql.demokit.build_demo`). The former sibling `datasets` repo was
folded into `portfolio` in 2026-07. This repo is engine-only, with `sales.csv` as its sole fixture,
and stays that way: the move was considered as Stream F and stood down on 2026-07-29. The engine
publishes what a host needs — `GRAMMAR` (what is legal), `DATASET_SCHEMA` (the asset shape) and each
column's `values` (what can go in a literal) — and the host does the rendering and the caret work.

- [x] Curated ESQL<->SQL example set + expected result tables: now produced per dataset by
  `esql.demokit.build_demo` (SQL-validated), out of this repo.
- [x] Demo execution model decided: **in-browser via Pyodide** (the `esql` wheel), no backend.
- [x] `from esql import ESQLAccessor` / the `.esql` accessor is the stable entry point the wheel exposes.
- Next engine ask from the demo: **nested / multi-grain aggregation** above (§ headline features).
  `HAS` shipped in v1.4.0; what remains on the demo side is an example wired into the ESQL editor.
