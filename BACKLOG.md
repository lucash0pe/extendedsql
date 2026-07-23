# ESQL — Backlog

Working backlog for the ESQL engine. Status as of 2026-07-21.

**Gate:** `make check` (ruff lint + pytest) is green — **68 tests pass**. `make typecheck`
(mypy) is configured but not yet clean (see Remaining).

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
- [x] **README** — install snippet fixed (`git+https://github.com/lucash0pe/esql.git`), Python
  3.12, added a Development section.
- [x] **Version** — bumped `0.1.0 → 1.0.0`; wheel + sdist build clean. Local tag only (not pushed).

## v1.1 — In progress

- [x] **Curated demo examples.** `examples/generate_examples.py` defines the ESQL↔SQL example
  set (6 examples, simple → advanced), validates each ESQL query against its SQL equivalent via
  sqlite, and writes `public/examples/examples.json` for the website demo. `make examples`.
- [x] **Pyodide path verified.** The built wheel installs via `micropip` in a real Pyodide 0.27.2
  runtime (pandas 2.2.3 + numpy 2.0.2 shipped by Pyodide satisfy our deps; beartype pulled from
  PyPI) and `df.esql.query(...)` returns results identical to the native engine. No engine changes
  needed for the browser. **Recommendation:** self-host the Pyodide runtime + wheels (esql,
  beartype) in the website's `public/` on Cloudflare so the ESQL demo depends only on the site
  loading (no third-party CDN, no mini).
- [x] **BUG-8 (found via example generation) — aggregate reused in SELECT + HAVING.** An aggregate
  named in both clauses (e.g. `quant.sum`) was appended twice, so it was accumulated twice per row
  (silently **doubling** sum/count) and, for avg, converted twice (`'float' object is not
  subscriptable`). `parse.py` now dedups the merge. Regression tests cover both. *(This bug shipped
  in v1.0.0 and is fixed on `main` for v1.1.)*

- [ ] **EMF support (headline feature).** Entry-value conditions like `col = col + 1`.
  `_parse_emf_condition_value` is a TODO stub; the `is_emf` flag is parsed but not executed. Not
  advertised in the docs today, so it is net-new capability, not a fix.
- [ ] **CONTAINS / semi-join predicate (headline feature, requested for the GD demo).** A WHERE
  predicate that keeps rows whose *group* contains a row matching a condition — e.g.
  `WHERE date CONTAINS song = 'Dark Star'` → all songs from every show that also played Dark Star.
  Semantics: `WHERE <key> CONTAINS <inner condition>` = keep rows whose `<key>` value appears in
  the subset satisfying `<inner condition>` (a self semi-join on `<key>`). Bridges the two demo
  grains (songs ↔ shows) without joins, which ESQL doesn't have. Work: parser grammar + a new
  execution filter pass + tests + a `public/docs/syntax.md` section, then an example wired into the
  `website` demo. This is the "build engine + demo side by side" case — coordinate with `website`.
- [ ] **Nested / multi-grain aggregation (headline feature — the grain-bridging companion to
  CONTAINS).** Aggregate at a declared finer grain, then roll *that* up — an aggregate of an
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
  `public/docs/syntax.md` section + a `website` demo example. Pairs with CONTAINS: CONTAINS
  *filters* one grain by another; this *measures* across grains. Design captured now; build parked
  until the datasets/rename plumbing lands.
- [ ] **mypy clean pass.** 143 errors, all from the dynamic evaluator: union comparisons
  (`[operator]`) and TypedDict key-narrowing (`[typeddict-item]`/`[index]`) mypy can't follow
  through runtime `'group' in aggregate` checks. Options: type the cell/accumulator boundaries as
  `Any` (honest — a `_data_map` slot holds int|float|date or an avg `{'sum','count'}` dict), or
  model parsed conditions as dataclasses. Until then `typecheck` stays advisory.
- [ ] **Push the release** — `git push && git push --tags` when ready (remote: `lucash0pe/extendedsql`).

## 3. Engine-side prep for the website demo

The demo frontend AND its data now live entirely in `website/` (`src/demos/esql/` +
`scripts/esql-data/`); this repo is engine-only, with `sales.csv` as its sole fixture. See the
website repo for demo work.

- [x] Curated ESQL↔SQL example set + expected result tables — done, generated + SQL-validated in
  `website/scripts/esql-data/` (moved out of this repo along with the demo datasets).
- [x] Demo execution model decided: **in-browser via Pyodide** (the `esql` wheel), no backend.
- [x] `from esql import ESQLAccessor` / the `.esql` accessor is the stable entry point the wheel exposes.
- Next engine ask from the demo: the **CONTAINS predicate** above (§ headline features).
