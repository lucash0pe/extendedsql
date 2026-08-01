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
of what `demokit` writes, and the *data* a host needs to complete a value. J1 and J2 shipped in
v1.7.0 (commit `5e6770d`, tagged and pushed), J4 and J5 in v1.8.0, and J3 in v1.10.0, which closes
the stream. The gate is green at **250 tests** (was 162).

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

- [x] **J3. The cap is set almost exactly wrong, and is probably the wrong instrument.** Filed from
  portfolio 2026-07-29 after wiring J2 into the editor. The Grateful Dead dataset has **520** distinct
  venues against `DISTINCT_VALUE_CAP = 500`, so `venue` ships nothing and `WHERE venue = '` offers
  nothing — the one column where a visitor most needs help spelling (`Magoo's Pizza Parlor`). Missing
  by twenty is not a judgement being vindicated; it is a number that happened to land there.

  Raising it to 1000 fixes this dataset for a few KB (436 songs cost ~35 KB of a 60 KB asset). The
  sharper point is that **a count is a proxy for the question actually being asked**, which is "does
  completing this column help?" The signal for that is the *ratio*: `venue` is 520 distinct over
  39,774 rows — 1.3%, plainly a dimension. The case worth protecting against is a free-text column,
  which sits near 100% and is useless to complete at any cardinality. So: a ratio test with a
  generous absolute ceiling for asset-size safety, rather than one count doing both jobs badly.

  Either fix unblocks portfolio. The ratio version is the one worth having.

  **Shipped in v1.10.0**, the ratio version. See that entry in the settled record: the count could
  not have been raised to admit venue without also admitting `quant`, so the cheap fix was not
  available even as a stopgap.

- [x] **J4. A quote inside a same-quoted literal parses and then matches nothing.** Shipped in
  v1.8.0; see that entry in the settled record. Both candidate fixes were taken, doubling *and*
  rejection, because they turned out to be the same change once the quote rule had one home.

- [x] **J5. `literals.text.summary` states something the parser does not do.** Filed from portfolio
  2026-07-29 while consuming 1.8.0. The summary says `'It''s'`, `"It's"` and `"It''s"` "all denote
  It's". The third does not — verified against the 1.8.0 wheel, `"It''s"` denotes **`It''s`**, two
  apostrophes:

  | written | denotes |
  |---|---|
  | `'It''s'` | `It's` |
  | `"It's"` | `It's` |
  | `"It''s"` | `It''s` |

  The *behaviour* looks right and portfolio built against it: only the active delimiter needs
  doubling, so inside `"` an apostrophe is ordinary text and `''` is two of them. It is the published
  claim that is wrong, which is the more dangerous half — a host that implements from `summary`
  doubles both delimiters and silently produces values that match nothing, the exact failure J4 just
  fixed. `tests/parser/test_grammar.py` binds every claim `GRAMMAR` makes about *clauses* to the real
  parser; this one is prose in a `summary` string and nothing binds it.

  Worth considering whether the literal rules deserve the same treatment the clause rules got — the
  three forms above are three assertions waiting to be written.

  **Fixed before v1.8.0 was pushed**, so no wheel ever carried the wrong wording. The summary now
  says only the delimiter *in use* is doubled and names `"It''s"` as the case that does not collapse,
  and `test_only_the_delimiter_in_use_is_doubled_as_described` runs all three forms through the
  engine and asserts what each denotes. Caught because portfolio consumed the claim rather than the
  behavior, which is the reading-side check working: the engine's own tests exercised
  `'x''y'` and `"x""y"`, both correct, and never the mixed form the prose got wrong. The general
  lesson is the one J5 names, that a `summary` string is prose nothing binds; these three are now
  bound, the rest are not.

**Portfolio-side follow-up, one line, required.** `DATASET_SCHEMA` is a new name in `esql.__all__`,
so `backend/esql/build.sh`'s export guard fires on the next wheel: it exits with "esql now exports
['DATASET_SCHEMA'], which grammar.json does not account for." That is the guard working as designed.
The fix is adding `"DATASET_SCHEMA"` to its `NOT_GRAMMAR` set — it is not a token set. Checked
against the assets portfolio ships today: both `songs.json` and `coffee.json` validate against the
schema unchanged, so nothing else breaks. **Done in portfolio 2026-07-29**, along with the
`entry_value` consumption Stream G notes below; the demo now runs 1.7.0 with the gate green.

---

## Stream G — grammar export

**`slot_kinds` + `accepts` are now a live extension point with a real consumer.** v1.6.0's
`entry_value` reached the demo as *nothing*: it is a new slot kind plus `SUCH THAT`'s `accepts`
growing, with no new `esql.__all__` export, so portfolio's export-diff guard did not fire, and its
per-clause suggestion logic branches on clause *names* rather than on `accepts`. Same shape as the
`HAS` finding one level up. The fix is portfolio-side and queued there; nothing to do here. Worth
recording because it sets the obligation going the other way: **new grammar surface has to be
expressible in `slot_kinds`/`accepts`**, since that is the channel a host actually reads.

**Done in portfolio 2026-07-29.** Its caret menu now derives from `accepts` rather than from clause
names, and a `unhandledSlotKinds` check fails its suite when this repo declares a kind it has no case
for — the reading-side twin of the export-diff guard. Entry values are offered.

- [x] **G3. `operators` is per clause but legality is also per *dtype*, and that half is unpublished.**
  Filed from portfolio 2026-07-29, found by testing the engine rather than reading it. The parser
  rejects an ordering comparison on a non-numeric column:

  | | `=` `!=` | `>` `>=` `<` `<=` | `CONTAINS` |
  |---|---|---|---|
  | number | ✓ | ✓ | ✗ needs text |
  | date | ✓ | ✓ | ✗ |
  | string | ✓ | **rejected** | ✓ |
  | boolean | ✓ | **rejected** | ✗ |

  `GRAMMAR["clauses"][c]["operators"]` carries only the per-clause axis, so a host reading it offers
  `>` on a text column and the engine refuses. Portfolio hits this today: its menu suggests `song >`.

  This is the same shape as the aggregate dtype rule, which **is** published
  (`aggregates.any_dtype`, so `count` is known to be the only one legal on a non-numeric column).
  The operator axis needs its counterpart — a per-operator dtype list, or a dtype-keyed operator set
  alongside the clause-keyed one. Without it the host has exactly two options, and both are bad:
  offer illegal operators, or hand-mirror the table above, which is the restatement Stream G exists
  to end. **Portfolio is deliberately not implementing this until it can be read** — the table is
  recorded here as a finding, not as a spec for someone to copy downstream.

  **Shipped in v1.11.0** as `GRAMMAR["operators"]["dtypes"]`, per-operator. See that entry in the
  settled record. One correction to the table above, found by probing the parser cell by cell rather
  than trusting the filing: **`date CONTAINS` was accepted**, not rejected, and it worked -- it
  substring-matched the date's ISO text. That cell is now genuinely rejected, which is the one
  behavior change in the release.

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

- [x] **G2. A guard for the prose.** The clause reference cards are hand-written and only the keyword
  list is asserted today. G1 gives the cards something to be checked against: they can now be
  generated from `GRAMMAR` or asserted to agree with it.

  **Shipped in v1.14.0**, asserted rather than generated. See that entry in the settled record. With
  it, Stream G closes: `slot_kinds`/`accepts`, the operator dtype axis and the prose that restates
  them are all bound to the parser.

---

## Stream H — language features

**Closed 2026-07-30.** H1 (CONTAINS) shipped in v1.3.0, H2 was a rename in the design notes, H3
(ORDER BY by name) in v1.13.0 and H4 (the two counts) in v1.15.0. What each one settled:

- [x] **H4. `count` should count rows bare, and count *distinct* on a column.** Filed from portfolio
  2026-07-29, from a visitor reading a result and being wrong about it in the way the syntax invites.

  **What happened.** `SELECT state, city.count` returns 11,963 for CA. That is the row count — CA has
  11,963 song-performances and **61 distinct cities**. The reader expected 61, which is what the
  syntax says: under a clause that auto-groups, `city.count` reads as "the cities, counted".

  **The column is doing nothing.** `city.count`, `song.count` and `position.count` all return 11,963
  for CA; only `duration.count` differs (10,850), and only because it has 3,269 nulls. So the column
  in `X.count` carries no meaning except its nullness. It is there to satisfy dot-notation, and
  naming a column that has no bearing on the answer is what makes the result misread.

  **The root cause is that ESQL has no `COUNT(*)`.** SQL can count rows without naming a column;
  dot-notation cannot, so every row count borrows a column, and auto-grouping turns the borrowed name
  into an apparent meaning. All 13 curated demo examples borrow `position` this way.

  **The proposal, which is the dataset owner's call and their preference:**

  - `count` — bare, no column: the row count. The `COUNT(*)` that is missing today.
  - `column.count` — the **distinct** values of that column. What the syntax already looks like.
  - `sum` / `avg` / `min` / `max` — unchanged, over rows.

  Two objections were raised from portfolio and both were overruled, correctly. That old queries
  change meaning does not matter: every query that exists is in the demo and gets rewritten. That
  `sum / count` would stop equalling `avg` is a SQL identity, not a law — if `count` is defined as
  distinct then the identity simply does not hold, and `avg` keeps its own definition.

  What makes it worth the migration is that it removes the misleading form rather than documenting
  it: after this, there is no way to spell "row count" that names an irrelevant column.

  **Two things to decide, both affecting what portfolio can read:**

  1. **`aggregates.forms` grows a bare form.** It currently publishes
     `["column.function", "group.column.function"]`. A bare `count` is a third shape, and if a group
     can take one (`g1.count`, the group's row count — expected for symmetry with `g1.column.count`)
     a fourth. Portfolio's result table decides what is a *measure* by looking for a dot with an
     aggregate name after it, so a bare `count` column would be filed as a **dimension** and rendered
     in the label block instead of as a number. That is fixed by reading `forms` instead of assuming
     a dot, which portfolio is doing now — but only works if `forms` actually carries the new shape.
  2. **`aggregates.any_dtype` narrows.** "Only `count` is legal on a non-numeric column" would govern
     only `column.count`, since the bare form takes no column at all.

  **Sequencing: land it with D1** (splitting `position` into set position and show position). Both
  rewrite all 13 curated examples, the walkthrough, `songs.structure.json` and every SQL equivalent
  the docs show side by side. Doing them separately means paying that twice, and `esql-smoke` catches
  a partial migration either way.

  **The engine half shipped in v1.15.0**, both decisions taken as filed: `forms` grew the two bare
  shapes and `any_dtype` narrowed to the column form. See that entry in the settled record. The
  sequencing note stands for the *portfolio* half, which is where the 13 examples live: nothing
  downstream has to move until it moves with D1, since a query written the old way still parses --
  it just answers the distinct count now, which is the one thing to watch for in that migration.

- [x] **H3. `ORDER BY` cannot sort by an aggregate.** Filed from portfolio 2026-07-29.
  `SELECT song, position.count ORDER BY position.count` raises `[ORDER_BY_CLAUSE] Invalid value`, and
  `ORDER BY 2` raises "out of range of the 1 grouping attributes" — confirming the index counts only
  SELECT's plain columns, so an aggregate is unreachable by either spelling.

  This is the obvious next thing a visitor wants: having just computed a count, sort by it. "Which
  songs did they play most" is the first question anyone asks of this dataset, and the language
  cannot currently express its second half. It is also why portfolio still offers nothing in
  `ORDER BY` — a 1-based index into grouping attributes is not something a caret menu completes
  well, and the thing that *would* be worth offering is the aggregate list.

  Whether it extends the index to cover SELECT's full term list or takes the aggregate by name is
  this repo's call; the grammar's `grouping_attribute_index` slot kind would need to change either
  way, which makes it a `slot_kinds`/`accepts` change and therefore visible downstream by design.

  **Shipped in v1.13.0**, by name. The choice was forced rather than preferred: `ORDER BY n` sorts by
  the *first n* grouping attributes, not the nth, so an index extended over SELECT's full term list
  still always begins at the first grouping attribute and can never sort by an aggregate alone. The
  filing offered the two as alternatives; only one of them works. See that entry in the settled record.

- [x] **H2. Rename the unbuilt semi-join.** `CONTAINS` now names the substring operator H1 shipped,
  so the grain-bridging semi-join in the settled record below could not keep that name. Decided
  2026-07-28: it is **`HAS`** (`WHERE date HAS song = 'Dark Star'`). Nothing was built under the old
  name, so this was a rename in the design notes only, done here and in `CLAUDE.md`.

---

## Stream K — parser correctness

Opened 2026-07-29. Findings from the v1.8.0 work that are **not** about a missing feature: the
parser accepts a query and answers it wrongly, or refuses one it should take. J4 was the first of
these and is fixed; these two were turned up alongside it. **Both shipped in v1.9.0**; see that entry
in the settled record. **Reopened 2026-07-29** by K3 below, turned up the same way, by probing the
parser rather than reading it, and closed again by v1.12.0.

The shape they share with J4 is worth naming, because it is what to look for next: **a rule the
parser applies by rewriting the query string before it knows the query's structure.** Lowercasing
the whole query was the J4 root, and K1 was the other half of the same pass. With the fold gone,
`_prepare_query` now rewrites only whitespace, so nothing in the parser depends on a string
substitution made before the structure is known. That whole failure mode is closed rather than
patched twice.

- [x] **K1. A mixed-case DataFrame column cannot be queried at all.** Found while fixing J4, by
  testing what `_prepare_query` does rather than reading it. Hand the accessor a frame whose columns
  are `Cust` and `Quant` and **every spelling fails**:

  ```
  df = pd.DataFrame({"Cust": [...], "Quant": [...]})
  df.esql.query("SELECT Cust, Quant.sum")   -> [SELECT CLAUSE] Invalid column: 'cust'
  df.esql.query("SELECT cust, quant.sum")   -> [SELECT CLAUSE] Invalid column: 'cust'
  df.esql.query("SELECT CUST, QUANT.SUM")   -> [SELECT CLAUSE] Invalid column: 'cust'
  ```

  The column is unreachable. `_prepare_query` lowercases every identifier, then resolution is a
  plain `in column_dtypes` against the frame's real, case-carrying keys, so the query can only ever
  name a column the frame spells in lowercase. What looks like "ESQL is not case sensitive"
  (`public/docs/syntax.md`) is really "ESQL lowercases your query and hopes your columns match".

  **Not fixed in v1.8.0 on purpose.** The honest fix is to stop folding identifiers in the string
  and resolve them case-insensitively at lookup, where the structure is known: roughly twelve
  `column_dtypes` sites routed through one resolver. That is a real change to identifier semantics
  and deserves its own pass, not a rider on a literal-scanning fix. The error message is also
  actively misleading, since it reports `'cust'` for a query that said `Cust`.

  Nothing in the repo or the demo hits this today: `sales.csv` and both portfolio datasets are
  lowercase throughout, which is why it has gone unnoticed. It bites the first person who points the
  accessor at their own frame, which is the entire published use.

  **Fixed in v1.9.0**, as filed: the fold is gone and the twelve sites go through `_resolve_column`.

- [x] **K2. Two default arguments are dead, and read as if they were not.** `_parse_condition_value`
  and `_parse_aggregate` each default `error_type` to `A or B`:

  ```python
  error_type=ParsingErrorType.SELECT_CLAUSE or ParsingErrorType.SUCH_THAT_CLAUSE,
  error_type=ParsingErrorType.SELECT_CLAUSE or ParsingErrorType.HAVING_CLAUSE,
  ```

  `A or B` is `A` for any truthy `A`, so the second name has never meant anything. **Harmless
  today**, since every one of the four call sites passes `error_type` explicitly and no default is
  ever taken. That is exactly why it should go: it is a line that looks like it selects a clause per
  caller and does not, sitting in the function that reports which clause rejected a value. Delete
  the defaults and make the parameter required, so a future caller cannot silently inherit
  `SELECT CLAUSE` for a WHERE failure.

  **Done in v1.9.0.** Both parameters are required and
  `test_error_type_is_a_required_argument` pins that, so a default cannot come back.

- [x] **K3. A boolean column compares against a number, because pandas counts bool as numeric.**
  Found while building G3, by probing every operator against every dtype family. `WHERE credit = 1`
  parses and **matches the true rows**, `credit = 0` matches the false ones, and `credit = 5` matches
  nothing:

  ```
  df.esql.query("SELECT g WHERE flag = 1")       -> the True rows
  df.esql.query("SELECT g WHERE flag = 5")       -> no rows, no error
  df.esql.query("SELECT g WHERE flag = 'true'")  -> [WHERE CLAUSE] Invalid value
  ```

  The asymmetry is what makes it a bug rather than a lenient convenience: the *quoted* boolean is
  refused while the numeric one is silently accepted, so the two spellings a person is most likely to
  reach for behave in opposite ways. The cause is `_parse_condition_value`'s coercion chain ending in
  `is_numeric_dtype(column_dtype)`, which is **True for a bool column**, so a bool falls through to
  the numeric branch and `1` becomes the value it compares against. `dtype_family` already knows bool
  is its own family (it checks bool before number, exactly because pandas conflates them), so the fix
  is to let the coercion dispatch on the family the same way the dtype gate now does.

  **Deliberately not fixed in v1.11.0.** G3 published *operator* legality, and `=` on a boolean column
  is legal; this is about which *values* that comparison accepts, a second question the same function
  answers. Folding it in would have put an unrelated behavior change under a release about publishing
  a table. It is small and self-contained: dispatch the `=`/`!=`/`==` branch on `family` rather than on
  four dtype predicates, and a bool column then takes only `true`/`false`.

  Worth noting the same chain is why `credit = 5` returns an empty table instead of an error, which is
  the softer version of the same problem.

  **Shipped in v1.12.0.** The fix found a second instance of the same root cause on the way in: a date
  column accepted *any* quoted text, so `date = 'hello'` matched nothing and `date != 'hello'` matched
  everything. Same chain, same shape, both closed by one dispatch. See that entry in the settled
  record.

---

## Stream L — claims the type system makes

Opened 2026-07-31, and closed the same day by v1.15.1. Findings from asking why `make typecheck`
reported 152 errors when the suite was green. The answer is that **the count was never a count of
problems** (61 lines produced 153 errors, because comparing two union-typed operands reports every
illegal pairing), but two of the things it was pointing at were real, and both are the shape this
repo keeps finding: **a claim written down that nothing binds, which is therefore free to be false.**

The type annotations were the last unbound claim surface. `GRAMMAR` is bound to the parser (G1),
`syntax.md` is bound to `GRAMMAR` (G2), and `literals.text.summary` was bound after J5 caught it
lying. A type annotation is the same kind of statement -- it says what a value is -- and until
`typecheck` is clean nothing checks it, so it drifts exactly like prose does.

- [x] **L1. `_data_map`'s annotation was false, and its own release made it false.** Shipped in
  v1.15.0 before merge; see that entry in the settled record. The slot was declared
  `dict[str, str | int | bool | date]` while holding a `set` (the distinct count v1.15.0 had just
  added), a running `{"sum", "count"}` dict, and floats. The union was also wrong about `float` at
  all nine sites that spelled it out, which is older: a float column is ordinary, so `quant.sum`
  over one always returned a value the type called impossible.

- [x] **L2. Two `__eq__` methods that never ran, on the types the aggregate merge compares.**
  Shipped in v1.15.1; see that entry in the settled record. Same shape as **K2**'s dead `A or B`
  defaults -- a line that looks like it selects behavior and does not -- but sitting on the code path
  whose bug was BUG-8's silent doubling, which makes it worth more than tidiness.

**What to look for next, since this is now the third instance.** K2, L1 and L2 are all *a second
statement of a rule that no longer had to agree with the first*.

**Reopened 2026-08-01** by L3, which is the same investigation continued: the remaining clusters
were read one by one rather than counted, and one of them was pointing at a live defect.

- [x] **L4. Four more false claims, no behavior change.** Shipped alongside L3's filing;
  `datatable` was declared `list[list[int | str | bool | date]]`, the **same missing `float`** L1
  found at nine other sites and the one site L1 missed, so a float column's cells were declared
  impossible in the function that scans them. `build_grouped_table` declared
  `parsed_such_that_clause` and `parsed_having_clause` non-optional while `execute` passes `None`
  for both and the body guards for it. And L1's own ignore on the avg accumulator named
  `[index]` where the line also raises `[operator]`, so three errors sat uncovered behind a comment
  that looked like it covered them -- worth recording because a *partial* ignore reads exactly like
  a complete one. 66 -> 58 errors, gate green at 436.

- [ ] **L3. A frame whose columns are not strings raises a raw `TypeError` from inside the parser.**
  Found by asking what the six `dict[Hashable, Any]` errors in `parse.py` were actually pointing at,
  rather than silencing them: pandas types column labels as `Hashable` because they need not be
  strings, and this engine assumes throughout that they are.

  ```
  df = pd.DataFrame({0: ['a', 'b'], 1: [10, 20]})
  df.esql.query("SELECT 0, 1.sum")
  -> TypeError: sequence item 0: expected str instance, int found
  ```

  It gets as far as `types.aggregate_key`'s `".".join(parts)`. `_resolve_column` finds the column
  happily -- an integer label is a legal key in the dtypes dict -- so nothing refuses the frame, and
  what reaches the caller is a raw Python error naming neither the column nor the query. In the
  browser demo that reaches the visitor, which is the same failure `_dtype_kind` was added to prevent
  in v1.6.0 and that `STRING_LITERAL` got its own error type for in v1.8.0.

  **The instrument already exists and the precedent is exact.** v1.15.0 refuses a frame whose column
  is named `count`, at `df.esql` rather than at query time, because the name is the thing that can be
  changed and the collision should be refused where it is chosen. A non-string column name is the
  same case, so `accessor._reject_reserved_columns` is the place and it wants a sibling. The open
  question is only whether to **refuse** the frame or **coerce** the labels with `str()`: coercing
  makes `SELECT 0` work but silently renames the caller's columns, and a frame with both `0` and
  `"0"` then collides. Refusing is consistent with every other collision rule this engine has taken.
  This changes what `df.esql` accepts, so it is a decision, not a cleanup.

- [ ] **L5. The condition-tree types claim an inheritance the evaluator does not need.**
  `CompoundGroupCondition` inherits `CompoundCondition` and overrides `conditions` with a different
  element type, which TypedDict forbids (3 `[misc]`, and most of the 17 `[typeddict-item]` follow
  from it). The thing worth knowing is *why* it is written that way and why it has been harmless:
  **`_evaluate_condition` is declared `condition: dict` and genuinely evaluates both trees** -- the
  WHERE clause and each SUCH THAT section -- because both really do have the same shape. The
  inheritance is an attempt to say so, and the `dict` annotation is an opt-out that hides whether it
  is true.

  So the fix is probably *not* the dataclass migration the mypy item proposes. It is to name the
  thing that is actually shared: a `ParsedCondition` union that `_evaluate_condition` takes, so the
  interchangeability the code relies on is written down and checked, and the two hierarchies stop
  claiming a subtype relationship neither needs. Cheaper than dataclasses and it documents a real
  property instead of a modelling accident. Worth doing on the G1 reasoning, not for the count.

- [ ] **L6. `make typecheck` reported a count that was eight errors stale, from `.mypy_cache`.**
  Found 2026-08-01 by running the target on a clean checkout of `d03f2b0` and getting **66**, then
  getting **58** from the same tree after `rm -rf .mypy_cache`. Nothing was edited in between.

  **What makes it worth an item rather than a shrug is what the stale errors said.** Two of them
  named `build_grouped_table` as declaring `parsed_such_that_clause` non-optional — the exact claim
  **L4 had already deleted**, against a signature that reads `ParsedSuchThatClause | None` in the
  tree. So the target did not merely over-count: it reported a specific, plausible, checkable defect
  that had been fixed, naming a line and a type. Read in good faith it sends you to fix something
  already correct, which is worse than a wrong total.

  **This is the third stale count in this repo, and the first two are already recorded above.** The
  number was stale at 143 for however long `make typecheck` was calling `uv run mypy` (fixed in
  v1.5.0), and the backlog item's **68 / 30 / 17 / 6** was stale the moment L4 landed. Three
  different mechanisms — a target that errored before the tool ran, a note not updated after a fix,
  and now a cache — producing the same failure, which is this stream's own thesis arriving at the
  instrument doing the measuring: **the count is a claim, and nothing binds it either.**

  **The cheap half is knowing, not fixing.** Whatever the cache mechanism turns out to be (mtime
  granularity across edits landing in the same second is the likely one, and worth confirming before
  blaming mypy), any count recorded in this file should come from a cleared cache, because an
  incremental one cannot be told from a clean one by reading the output. That is a line in the
  toolchain note, not a code change.

  **The half worth building: a baseline, now, rather than after L5.** This stream's premise is that
  until `typecheck` is clean nothing checks the annotations, so they drift like prose — which defers
  the binding until a rewrite that is explicitly "its own pass". A frozen baseline binds them
  *today*: the 58 known errors pass, anything new fails, and `typecheck` can join `make check` and CI
  without waiting for L5. L1, L2 and L4 all entered as drift on a surface nothing was watching, and a
  baseline is the only proposal here that stops the fourth one arriving the same way rather than
  being found by reading. It also makes L5 measurable — the baseline shrinks by the cluster, which is
  the evidence the model change was the right one.

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

**And clear `.mypy_cache` before recording an error count** (L6). `make typecheck` on an unchanged
tree reported 66 from an incremental cache and 58 after `rm -rf .mypy_cache` — including two errors
against a `build_grouped_table` signature L4 had already changed. A stale run is not distinguishable
from a clean one by reading its output, and this file has now carried a wrong count three times.

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
- [ ] **mypy clean pass.** **58 errors** (68 before L4, 153 before the accumulator types landed in v1.15.0, 157
  before v1.15.0's feature work, 159 before v1.9.0, and recorded as 156 until v1.8.0; the count was
  stale at 143 before that because `make typecheck` called
  `uv run mypy`, whose console script does not spawn, so the target errored out before reaching
  mypy; fixed in v1.5.0 to `uv run python -m mypy`, the form every other target uses).

  **The count was never a count of problems.** 153 errors came from 61 lines, because a comparison
  between two union-typed operands reports every illegal *pairing*: four ordering lines in
  `_evaluate_actual_vs_expected_value` produced 60 of them between them. Naming what the values
  actually are (`CellValue` / `Accumulator` / `ProjectedValue`) and then leaving nine genuinely
  un-narrowable lines as targeted `# type: ignore[...]` with the invariant written next to them took
  it to 68 without a single behavior change. `--warn-unused-ignores` is clean, so no ignore is
  suppressing nothing.

  What is left is two clusters and a tail: **26 `[arg-type]`**, **17 `[typeddict-item]`** plus
  `[index]`, mostly TypedDict key-narrowing mypy cannot follow through runtime `'group' in
  aggregate` checks, and **4 `[misc]`** (the 6 included the dead `__eq__` methods, deleted in
  v1.15.1), over 5 files rather than 7.
  ~~The remaining fix is to model parsed conditions as dataclasses rather than TypedDicts~~ — **L5
  argues that is the wrong instrument**: what the two hierarchies need is a `ParsedCondition` union
  naming the interchangeability `_evaluate_condition` already relies on, which is cheaper and states
  a real property. Read L5 before starting a dataclass pass.
  Until then `typecheck` stays advisory: it is not in `make check` and not in CI — though **L6
  proposes a baseline that would let it join both now**, without waiting for the model change.
  **Any count recorded here must come from a cleared `.mypy_cache`** (L6): an incremental run
  reported 66 against this same tree, including two errors on a signature L4 had already fixed.
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

## v1.8.0 — string literals get one scanner and an escape (2026-07-29)

- [x] **J4, plus two more the same misreading reached.** `SELECT song WHERE song = '(I'm A) Road
  Runner'` returned 0 rows and raised nothing. It now parses when the quote is doubled or the other
  delimiter is used, and raises when it is neither. Bumped `1.7.0 -> 1.8.0`; the gate is green at
  **229 tests** (was 207).

  **The filed mechanism was wrong, which is worth recording because it moved the fix.** J4 said the
  parse "ends the literal at the apostrophe". It does not: `_split_condition` reads
  `'(I'm A) Road Runner'` correctly, and so does every other scanner in `util.py`. The damage was in
  `_prepare_query`, which lowercases a query outside its quoted text and found that text with the
  regex `'[^']*'`. That regex closes at the *first* quote it meets, so it read `'(I'` as the whole
  literal and lowercased the rest of the value as if it were keywords. The literal then parsed
  cleanly, as `(I'm a) road runner`, and matched no row. Case-mangling, not truncation.

  **So the real defect was that the quote rule had seven homes**: four `in_single`/`in_double`
  scanners, `_is_quoted` reading first and last character, a date pattern spelling its delimiters as
  `['\"]` independently at each end, and that regex, which was the one that disagreed.
  `get_keyword_clauses` made an eighth case by having no notion of a literal at all. All of them now
  read `mask_literals`, which blanks each literal (delimiters included) to a filler of the same length so
  an index into the mask is that index into the original: a caller finds its operator, keyword or
  parenthesis in the mask and slices the original. Unifying them is what made "reject" and "double"
  stop being alternatives: with one scanner, doubling is `_end_of_literal` skipping a doubled pair
  and `_unquote` collapsing it, and rejection is that same scanner reaching the end still open.

  **Two further silent-wrong bugs fell out of the same root**, both found by testing rather than
  reading, and both now covered:

  - **A clause keyword inside a literal split the clause there.** `WHERE song = 'order by me'` cut
    an ORDER BY out of the middle of the value. `get_keyword_clauses` was searching the query rather
    than the mask.
  - **Whitespace inside a literal was collapsed with the query's.** `'Dark  Star'` silently became
    `'Dark Star'`. `_prepare_query` reinserted quoted text *before* its `" ".join(query.split())`.

  Decisions worth keeping:

  - **Doubling applies to both delimiters, and either delimiter still holds the other verbatim.**
    Only the delimiter *in use* is doubled, so `"It's"` and `'It''s'` denote the same four
    characters while `"It''s"` denotes two apostrophes, and a value needing
    both kinds is expressible at all, which is the case no single-delimiter rule reaches.
  - **An unterminated literal raises rather than being guessed at.** No counting rule recovers the
    writer's intent here: `a = 'He's' AND b = 'x'` and `a = 'He's Gone'` differ only in what was
    meant, and pairing first-to-last resolves the second while destroying the first. Rejecting is
    the only honest reading, and the message names both ways out.
  - **It gets its own `ParsingErrorType.STRING_LITERAL`.** Delimiters are read before the query is
    split into clauses, so there is no clause to blame; labelling it `[SELECT CLAUSE]` pointed at
    the wrong place. This is a new enum value, so a host switching on `error_type` sees a new case.
  - **A date literal lost its private quote rule.** `date_pattern` spelled its delimiters as
    `['\"]` at each end independently, so it alone accepted a mismatched pair (`'2020/7-1"`) that no
    other value could use. It now matches the *unquoted* text and lets `_is_quoted` answer the
    quoting question. One test asserted the old sloppiness and was inverted.
  - **`_is_quoted` means "exactly one literal", not "starts and ends with a quote".** `'a' 'b'` used
    to pass as a single literal holding `a' 'b`.
  - **`literal_spans` is the primitive and `mask_literals` is built on it.** `_prepare_query` wants
    the literals themselves rather than the gaps between them, and recovering them from the mask
    would mean testing for the filler byte, which a control character in the query would satisfy.
    Covered, since the alternative was a sentinel collision nobody would ever see reported.

  **Published, not just described.** `GRAMMAR["literals"]["text"]` now carries the delimiters, the
  escape name and a summary, so a host quotes what it inserts by reading the rule rather than
  mirroring it. That is the Stream G obligation going the right way: hand-mirroring this is exactly
  what J4 cost. Bound to parser behavior by four tests in `tests/parser/test_grammar.py`; the
  behavior itself is covered by `tests/execution/test_string_literals.py` (17 tests). Verified both
  bite: breaking the doubling skip fails 5, and pointing `get_keyword_clauses` back at the raw query
  fails 1.

  **Prose updated to match**, since both places understated what is now possible: `README.md` said
  to use the opposite quote and to avoid data needing escapes, and `public/docs/syntax.md` had no
  account of literals at all. It now has a **Text values** section covering the delimiters, doubling,
  that case and spacing inside a literal are data, and that an unterminated one is an error. Every
  example in both was run against the engine rather than written from memory.

  **What this turned up and did not fix** is filed as **Stream K** above: a mixed-case DataFrame
  column is unreachable in any spelling (K1, the other half of the same `_prepare_query` pass), and
  two dead `A or B` default arguments (K2). Both shipped in v1.9.0, below.

## v1.9.0 — identifiers resolve instead of being folded (2026-07-29)

- [x] **K1 and K2.** A frame whose columns are `Cust` and `Quant` is now queryable, in any spelling,
  and the two dead `A or B` defaults are gone. Bumped `1.8.0 -> 1.9.0`; the gate is green at
  **247 tests** (was 230).

  **The fix is a deletion, not an addition.** `_prepare_query` no longer lowercases; it collapses
  whitespace and nothing else. Everything the fold was silently doing for the parser now happens
  where the structure is known:

  - **Keywords and operators fold case themselves.** `get_keyword_clauses` searches with
    `re.IGNORECASE`, and `_operator_starts_at` already compared case-insensitively — it just carried
    a comment crediting `_prepare_query` for it. The AND/OR split, the NOT prefix and the
    `true`/`false` literals were likewise already folding on their own. So four of the six things the
    fold appeared to be responsible for did not need it at all, which is why the change is small.
  - **Identifiers resolve through `_resolve_column` / `_resolve_group`**, which answer with the
    **canonical** spelling: the frame's for a column, the OVER clause's for a group. This is the part
    that makes the fix work rather than just move the bug. Execution indexes rows by the frame's
    spelling (`execute.column_indices`), so a parsed query carrying the *query's* spelling would
    reach the row loop and fail there instead. All twelve `column_dtypes` sites route through the one
    resolver.
  - **An aggregate function lowercases** to its canonical name, so `QUANT.SUM` and `quant.sum` are
    the same aggregate. That matters beyond cosmetics: the SELECT/HAVING dedup in
    `_build_parsed_query` compares parsed aggregates, so without it `SELECT quant.sum HAVING
    QUANT.SUM > 0` would accumulate twice per row and silently double the sum — BUG-8 from v1.1
    arriving by a new route. Covered.

  Decisions worth keeping:

  - **Resolution tries an exact match first, then a case-folded one.** A frame *can* hold `Cust` and
    `cust` at once, and exact-first keeps both reachable by writing either. Only a third spelling
    (`CUST`) is genuinely ambiguous, and that raises and names both candidates rather than picking
    one. Rejecting the whole frame up front was the alternative and is worse: it refuses queries
    that have one obvious answer.
  - **Two group names differing only in case are rejected.** They name the same group, so
    `_resolve_group` would have an ambiguous case to answer. Rejecting in `parse_over_clause` is
    where the information is, and it subsumes the exact-duplicate `OVER g1, g1`, which used to parse
    and mean nothing.
  - **The result is labelled canonically, not as the query wrote it.** `SELECT CUST, QUANT.SUM`
    returns columns `Cust` and `Quant.sum`. The label is also the key execution looks the value up
    by, so a query-spelled label would find nothing in the grouped row's data map; making it
    canonical is what keeps the two in step by construction rather than by both being lowercase.
  - **`ParsingError.token` now comes back spelled exactly as the query spelled it.** This is a
    published contract *improvement* and the one visible behavior change beyond the fix: a token used
    to be lowercased, so `README.md` told a consumer to match it case-insensitively. It matches
    literally now. Both README and the `ParsingError` docstring were saying the old thing.
  - **`aggregate_key` has one home.** The `column.function` / `group.column.function` key was three
    f-strings in three files — the parser's select items, `GroupedRow`, and the HAVING evaluator —
    which agreed only because everything was lowercase. Once identifiers carry the frame's spelling
    they have to be built by the same code, so it moved to `parser/types.py`. A mismatch here is
    silent: the projected column comes back empty rather than raising.

  Covered by `tests/parser/test_identifier_case.py` (17 tests) exercising every clause against a
  frame that is mixed-case throughout, which is the case that used to be unreachable, plus the two
  existing tests that asserted the old behavior and were inverted
  (`_prepare_query` and the error token). Verified the suite bites, by reverting each part of the fix
  in turn: restoring the fold fails 4, making `_resolve_column` exact-only fails 12, pointing
  `select_items_in_order` back at the written text fails 6, dropping `re.IGNORECASE` fails 13, and
  making `_names_group` case-sensitive fails 2.

  **Prose updated to match**, because `public/docs/syntax.md` already claimed "ESQL is not case
  sensitive" and that claim was **false** for the entire published use. It now has a **Case** section
  saying what is folded, what is not, and what a result is labelled with; the OVER section names the
  case-collision rule; and `README.md` says it in the accessor walkthrough, since pointing the
  accessor at your own frame is where this bit.

  **Considered and declined: publishing the case rule in `GRAMMAR`.** It is the kind of rule a host
  could mirror wrongly, which is the Stream G argument for exporting it. But no host needs it: a
  caret menu inserts canonical names off the dataset asset, and a host pre-checking a typed query
  calls `validate`, which now answers correctly. Following the same discipline G3 records — do not
  publish surface before there is a reader — it stays prose. Reopen if a consumer needs to decide
  legality for itself.

  **Portfolio-side follow-up: none required.** No new name in `esql.__all__`, no new slot kind and no
  new `GRAMMAR` key, so neither the export-diff guard nor the `unhandledSlotKinds` check fires. Both
  portfolio datasets are lowercase throughout, so every result label is byte-identical to 1.8.0. The
  one thing worth knowing is that `ParsingError.token` is now literal, which makes portfolio's
  existing case-insensitive match correct but no longer necessary.

  **Portfolio-side follow-up, optional.** No export guard fires: `literals` is a new key inside
  `GRAMMAR` rather than a new name in `esql.__all__`, and no slot kind changed, so `grammar.json`
  simply grows a key. Portfolio's `quoteFor` (pick a delimiter by content) is still correct and
  still the better default, since a delimiter swap reads better than a doubled quote. What changes
  is that it no longer has to be the *only* answer, and a visitor typing the apostrophe form by hand
  now gets an error telling them what to do instead of a confident empty table.

## v1.10.0 — value completions are decided by ratio, not by one count (2026-07-29)

- [x] **J3.** `demokit` now asks "is this column a dimension?" rather than "does it have few enough
  values?". Bumped `1.9.0 -> 1.10.0`; the gate is green at **250 tests** (was 247).

  Three constants, because the old single count was answering three questions at once and getting two
  of them wrong:

  - **`DIMENSION_RATIO = 0.05`** — distinct values as a share of rows. This is the real test, since a
    dimension sits far below its row count and a measure or free-text column climbs toward 100%.
  - **`SMALL_VALUE_SET = 50`** — ships regardless of ratio. A ratio says nothing on a small frame
    (four states over fifty rows is 8%), and any set this small is worth scrolling anyway. Without it
    the fix would have broken small demo datasets to fix a large one.
  - **`DISTINCT_VALUE_CAP = 2000`** — asset size only, not usefulness. 5% of a million-row frame is
    50,000 values, so the ceiling has to stay.

  **5% is not an arbitrary pick: it is the only band that keeps every current decision.** Checked
  against `sales.csv` column by column, and the new rule reproduces the old verdict on all nine
  while admitting venue:

  | column | distinct / rows | ratio | ships |
  |---|---|---|---|
  | `state` / `year` / `cust` / `prod` / `month` / `day` / `credit` | 2–31 / 10,000 | ≤0.3% | yes, as before |
  | `quant` (a measure) | 1,000 / 10,000 | 10% | no, as before |
  | `date` (near-unique) | 1,818 / 10,000 | 18% | no, as before |
  | `venue` (the filed case) | 520 / 39,774 | 1.3% | **yes**, 6.5 KB of JSON |

  That band matters in both directions. Raising the count to 1000 as the cheap fix would have
  admitted `quant` at 10% — a thousand quantities nobody completes — so the count could not be set to
  include venue without also including a measure. The ratio separates them by an order of magnitude.

  **`values` in `DATASET_SCHEMA` no longer describes itself as capped**, since "within the build's
  cap" is now only a third of the rule. It says the build judged the column a dimension by its
  distinct count as a share of its rows, without naming the numbers: a published description that
  carries a threshold is a second copy of it, and J5 is the standing lesson about prose nothing binds.

  **Portfolio-side follow-up: rebuild, nothing to change.** No new name in `esql.__all__`, no
  `GRAMMAR` key and no slot kind, so neither guard fires. The visible effect is that a build against
  1.10.0 emits `values` for `venue`, and `WHERE venue = '` starts completing.

## v1.11.0 — operator legality by dtype, published and enforced from one table (2026-07-29)

- [x] **G3.** The second axis of operator legality is now readable: `GRAMMAR["operators"]["dtypes"]`
  gives, per operator, which of the four dtype families it applies to. Bumped `1.10.0 -> 1.11.0`; the
  gate is green at **319 tests** (was 250).

  **It is the rule, not a description of it.** `OPERATOR_DTYPES` in `parser/util.py` is a single table
  that `_parse_condition_value` gates on *before* it coerces anything, and `GRAMMAR` exports verbatim.
  That is stronger than G1 managed: G1 could only bind its description to behavior with tests, because
  the parser had no declarative rule to read. Here the export and the enforcement are the same object,
  so the two cannot drift at all.

  Splitting the gate out made the function say what it means. It answers two questions and used to
  answer them in one tangle of dtype predicates: *does this operator apply to this kind of column*
  (about the operator, answerable before the value is read) and *can this value be read as that kind*
  (about the value). Now the first is a table lookup and the branches below only pick a coercion.

  **The filed table was wrong in one cell, and probing found it.** `date CONTAINS '2020'` was
  **accepted** and worked, substring-matching the date's ISO rendering, because dates are stored as
  object dtype and pandas reports object dtype as a *string* dtype -- so the guard meaning "text
  column" let dates through. Decided to reject it: the behavior was never stated anywhere, publishing
  it would rest the contract on that loose check, and a range (`date >= '2020-01-01' AND date <=
  '2020-12-31'`) is the honest spelling. This is the release's one behavior change. The old
  `is_string_dtype` guard inside the CONTAINS branch is gone, because the gate now answers that
  question first and a guard that can no longer fire is the K2 mistake again.

  **One vocabulary, in one place.** `dtype_family` is now the only definition of the four families,
  and `demokit._friendly_type` -- which decides a demo asset's `SchemaColumn.type` -- delegates to it
  instead of keeping its own copy. That copy was a live hazard, not a tidiness point: a host reads a
  column's `type` from the asset and looks it up in this table, so if the asset called something a
  string that the parser treats as a date, every lookup would miss and the host would silently offer
  nothing. `test_the_families_are_the_vocabulary_a_demo_asset_speaks` binds the two enums together.
  It also fixed a real disagreement in passing: an all-null object column is a *date* column to the
  parser, and the old `_friendly_type` called it a string, because it read the first non-null value
  and there wasn't one.

  **Bound in both directions, and verified to bite.** `tests/parser/test_grammar.py` runs all 32
  cells (8 operators x 4 families) through the real parser in WHERE, and again in SUCH THAT since the
  rule belongs to the operator rather than the clause. Tampering confirms each guard fails loudly:
  claiming date takes CONTAINS fails 1, dropping an operator's rule fails 4, disabling the gate fails
  23, renaming a family in the asset schema fails 1, and widening `>=` to text fails 2.

  **Turned up and deliberately not fixed: K3**, a boolean column comparing against a number
  (`WHERE credit = 1` matches the true rows). Filed in Stream K above. That is about which values a
  legal comparison accepts, not about which comparisons are legal, and it did not belong in a release
  about publishing the second.

  **Portfolio-side follow-up: one read, no guard fires.** `dtypes` and `dtype_families` are new keys
  *inside* `GRAMMAR["operators"]`, not new names in `esql.__all__`, and no slot kind changed, so
  `grammar.json` simply grows two keys. The menu can stop offering `song >` by intersecting the
  clause's `operators` with `dtypes[op]` for the column's `type`, which it already has from the asset.

## v1.12.0 — a comparison value is read as its column's own kind (2026-07-30)

- [x] **K3, and a second instance of it found on the way in.** Bumped `1.11.0 -> 1.12.0`; the gate is
  green at **348 tests** (was 319).

  **What was wrong.** `_parse_condition_value` chose its coercion with a chain of pandas dtype
  predicates, one chain for ordering and a near-identical one for equality, and both ended by asking
  whether the column was numeric. Two families answer that question wrongly:

  | written | did | does |
  |---|---|---|
  | `credit = 1` | matched the true rows | refused |
  | `credit = 0` | matched the false rows | refused |
  | `credit = 5` | matched nothing, no error | refused |
  | `credit = 'true'` | refused | refused |
  | `date = 'hello'` | matched nothing, no error | refused |
  | `date != 'hello'` | matched **everything**, no error | refused |

  A bool column is numeric to pandas, so a boolean fell into the numeric branch and `1` became the
  value. Object dtype is a *string* dtype to pandas, so any quoted text fell into the text branch and
  reached a date column as a string, comparing unequal to every date.

  **Both are the same failure mode, and it is the one worth naming: an answer instead of an error.**
  Nothing raised. `credit = 1` looks like it worked and did something defensible; `date != 'hello'`
  returned the whole table. A person reading either result has no way to know the query was refused
  on its merits or answered on a misreading. That is why this was worth a release rather than a
  footnote, and it is the same reason J4 was.

  **The fix is one dispatch on `dtype_family`,** which G3 had already established as the one place
  the four families are defined. Ordering and equality no longer have a chain each: the value is read
  as the column's family, and the operator only decides whether ordering is allowed at all (which the
  `OPERATOR_DTYPES` gate answered before this point). `CONTAINS` stays the single exception, because
  its value is a substring rather than a value of the column's kind. Two small helpers, `_numeric_value`
  and `_date_value`, replace what the two chains each spelled out inline.

  So the released shape is: **`OPERATOR_DTYPES` says whether the operator applies, `dtype_family` says
  how to read the value.** Neither question is answered by asking pandas about a dtype in the middle of
  the other one, which is what let a bool and a date slip through.

  **The error messages now name which question refused the query,** because the two call for different
  fixes: `'>' does not apply to a string column` means change the operator, `A text value must be
  quoted` means write the value differently. `test_parse_where_clause_raises_error_for_invalid_values`
  went from asserting that *some* error was raised to asserting *which*, over all ten cases.

  Covered by `tests/parser/test_condition_values.py` (29 tests) over all four families in WHERE and
  SUCH THAT. Verified the guards bite: restoring the numeric fallback for bools fails 7, letting a date
  take any quoted text fails 8, and letting a text column take an unquoted word fails 4.

  **Portfolio-side follow-up: none, but worth a look at the curated examples.** No export changed.
  Any query spelling a boolean as `= 1` or comparing a date against non-date text would now be a
  parsing error rather than a quiet result, and `esql-smoke` catches it if one exists.

## v1.13.0 — ORDER BY takes named terms, aggregates included (2026-07-30)

- [x] **H3.** `SELECT song, position.count ORDER BY -position.count` answers "which did they play
  most", which the language could not express at all. Bumped `1.12.0 -> 1.13.0`; the gate is green at
  **376 tests** (was 348).

  ```sh
  ORDER BY song                    -- alphabetically
  ORDER BY -position.count         -- most played first
  ORDER BY -position.count, song   -- most played first, ties broken alphabetically
  ORDER BY 2                       -- unchanged: the first two grouping attributes
  ```

  **The filing offered two options and only one of them works.** It asked whether to extend the index
  over SELECT's full term list or take the aggregate by name. `ORDER BY n` does not mean "the nth
  attribute", it means "**the first n** attributes, in order" -- so an extended index still always
  begins at the first grouping attribute, and `SELECT song, position.count ORDER BY 2` would sort by
  song and then by the count, never by the count alone. The motivating query stays unreachable under
  that option however far the number is widened. Found by reading `order_by_sort`, not by assuming
  the index meant what an index usually means.

  **The integer stays, as sugar over the general form.** `ORDER BY 2` parses into the same
  `list[SortTerm]` the term list produces, so there is one thing to sort by and one place that knows
  what descending means. Nothing downstream knows there are two spellings, all 13 curated examples
  keep working, and the migration H4 will pay for anyway does not have to be paid twice.

  **`-` for descending rather than `DESC`.** ESQL already spelled descending with a sign
  (`ORDER BY -2`), so this adds no keyword and leaves one way to say it. `ASC`/`DESC` was the
  alternative and was declined for that reason: it would have left `-2` as a second, inconsistent
  spelling of the same thing.

  **A term must be projected.** Stricter than SQL, which can order by a column it does not return,
  and forced by grouping: a column that is neither grouped on nor aggregated has no single value in
  an output row. The refusal lists the terms that were available, since the answer is already in the
  query.

  **One sort pass per term, innermost first,** rather than one pass over a tuple key. Python's sort
  is stable, so each pass preserves what the previous ones established, and that is what lets each
  term carry its own direction -- `reverse` on a tuple key flips every key at once, so
  `-position.count, song` is not expressible that way.

  **Also corrected: `grouping_attribute_index`'s published description was wrong.** It said "a
  1-based index into the SELECT grouping attributes", which is what the name suggests and not what
  the parser does. Same shape as J5: a `slot_kinds` string that nothing bound to behavior. It now
  says first-N rather than Nth, and `test_the_index_counts_grouping_attributes_not_select_terms_as_described`
  binds it.

  Covered by `tests/execution/test_order_by_terms.py` (21 tests) through the public accessor.
  Verified the guards bite: applying the keys outermost-first fails 6, using one direction for every
  key fails 2, accepting any word as a term fails 6, and ignoring the minus sign fails 9.

  **Portfolio-side follow-up: the `unhandledSlotKinds` check will fire, by design.** `sort_term` is a
  new slot kind and `ORDER BY`'s `accepts` grew, which is exactly the channel Stream G built for this.
  Its caret menu can now offer something in ORDER BY for the first time: the SELECT terms of the query
  in hand, which is a list it already has. `ORDER BY`'s `separator` also changed from `null` to `","`.

## v1.14.0 — the prose is bound to the grammar (2026-07-30)

- [x] **G2, which closes Stream G.** `tests/test_syntax_docs.py` asserts `public/docs/syntax.md`
  against `GRAMMAR` and the parser's token sets. Bumped `1.13.0 -> 1.14.0`; the gate is green at
  **386 tests** (was 376).

  **Asserted, not generated.** Generating the doc from `GRAMMAR` was the other option G2 named and
  would have meant a build step for a document whose value is the half no export can hold: what a
  clause is *for*, why `HAS` is not a comparison, what an entry value is doing. So the doc stays
  hand-written and prose stays unchecked; only the parts that *restate a rule* are bound.

  **A claim is marked as one.** `<!-- grammar:operators WHERE also:==,HAS -->` in front of a
  paragraph says the operators named there are WHERE's operators, and `also:` names the ones written
  elsewhere in the section. Six markers: keywords, aggregate functions, the three clause operator
  lists, the operator-dtype table, and the text delimiters. Unmarked prose is not checked, because a
  regex over English produces false positives and a gate that cries wolf gets bypassed.

  **The loose version of this test does not work, and writing it proved that.** The first cut asked
  "does every legal operator appear somewhere in the clause's section", both directions covered by
  one cheap check. Tampering found it passes when HAVING gains the `HAS` operator, because HAVING's
  section *does* mention `HAS` -- in a sentence saying it is rejected. A mention that says the
  opposite still counts as a mention. That is why the marker carries the whole claim now: the list
  plus its `also:` set must equal the clause's operators exactly, and each `also:` name still has to
  be found in the section. Worth recording because the loose check is the one that looks sufficient.

  **What the doc got to say for itself.** Two places disagreed with the parser only in vocabulary,
  not in substance: the doc writes "text" where the engine's dtype family is "string". That is a
  rename declared in one dict in the test rather than a change to either side, since "text column"
  is the right words for a reader and `string` is the right key for a host.

  Verified the guards bite, seven ways: documenting CONTAINS in HAVING, HAVING gaining an operator
  nobody documents, WHERE losing one the doc still promises, an `also:` name written nowhere, a
  wrong cell in the dtype table, a deleted marker, and a new aggregate function shipping
  undocumented. Each fails, and the deleted-marker case is the one that matters most: a claim cannot
  go unguarded by quietly removing its marker.

  **Portfolio-side follow-up: none.** No export changed and no new name. Worth knowing that the
  reference cards portfolio renders are its own copy of this material, and this guard covers only
  the doc in this repo. The same marker idea is available there if its cards are ever worth binding.

## v1.15.0 — `count` counts rows, `column.count` counts distinct (2026-07-30)

- [x] **H4, which closes Stream H.** `SELECT state, count` is the row count, and `state.count` is now
  the number of distinct states. Bumped `1.14.0 -> 1.15.0`; the gate is green at **428 tests**
  (was 386).

  ```sh
  SELECT cust, count              -- how many rows this customer has
  SELECT cust, prod.count         -- how many distinct products
  SELECT cust, g1.count OVER g1 SUCH THAT g1.state = 'NY'   -- how many rows in the group
  ```

  **What was wrong was an answer, not an error**, which is the same shape as K3 and J4. `city.count`,
  `song.count` and `position.count` all returned 11,963 for CA, the row count, because the column in
  `X.count` carried no meaning except its nullness. Under a clause that groups automatically,
  `city.count` reads as "the cities, counted" and CA has 61 of those. Nothing raised, and nothing
  could: the query was answerable, just not the question the syntax spelled.

  **The root cause was a missing spelling.** ESQL had no `COUNT(*)`, so every row count borrowed a
  column, and dot-notation turned the borrowed name into an apparent meaning. Giving the row count a
  form with no column removes the misleading one rather than documenting it: after this there is no
  way to write a row count that names an irrelevant column, which is what made the migration worth
  paying for.

  Decisions worth keeping:

  - **`count` is a reserved name and a frame using it for a column is refused.** Three positions
    were tried and the first two were wrong. *Prefer the aggregate* leaves `SELECT venue, count`
    legal and meaning different things over different data. *Prefer the column* puts the row count
    out of reach for that frame alone. Both are invisible to whoever writes the query, and the thing
    that is visible -- the column's name -- is the thing that can be changed, so
    `accessor._reject_reserved_columns` refuses the frame, names the column and asks for a rename.
    Same instrument as the group-name rule below and the same reasoning: refuse the collision where
    the name is chosen rather than resolve it at every reference.

    **Only names that can be a whole aggregate are taken**, which is `BARE_AGGREGATE_FUNCTIONS` and
    today means `count` alone. `sum` is never an aggregate by itself, so a column may be called
    `sum`, `SELECT cust, sum` projects it and `sum.sum` is its total. Reserving all five would have
    cost four names to protect against an ambiguity only one of them has.

    **It gets its own `ParsingErrorType.RESERVED_COLUMN`**, and it is raised when the accessor is
    handed the frame rather than when a query is parsed, so it names a *column* rather than a query
    token. Same shape as `STRING_LITERAL` in v1.8.0: a new enum value, so a host switching on
    `error_type` sees a new case. Worth knowing that `df.esql` itself now raises for such a frame,
    before any query exists.
  - **A group cannot be named after a column**, which is the collision H4 created and the one place
    a tiebreak was the wrong instrument. `g1.count` is a group's row count, and if `g1` were also a
    column the same words would equally be that column's distinct count. The first cut preferred the
    group, on the reasoning that OVER declares it a few words earlier; that left the query legal and
    its *meaning* dependent on the frame handed in, which is the failure H4 exists to remove rather
    than a smaller version of it to accept. `parse_over_clause` now rejects the name where the query
    chooses it, next to the case-collision rule it already enforced, and `_parse_aggregate`'s
    two-part branch is a lookup rather than a decision.

    Both rules landed on the same answer from opposite directions, which is worth noting: a name
    the language reads two ways is refused where it is written down, in the OVER clause for a group
    and in the data for a column.
  - **`sum / count` is no longer `avg`, and that is not a bug to fix.** It is a SQL identity, not a
    law; with `count` defined as distinct it does not hold, and `avg` keeps its own definition over
    rows. Pinned by a test so nobody restores it by "fixing" avg.
  - **A distinct count skips blanks; a row count does not.** A missing value is not a value (SQL's
    `COUNT(DISTINCT x)` agrees), while a blank cell makes a row no less of a row. A column that is
    blank everywhere has *no* count rather than zero, the same as any aggregate with nothing to
    compute.
  - **Both bare forms are published literally**, as `count` and `group.count` in
    `GRAMMAR["aggregates"]["forms"]`, rather than as a `function` pattern. Only `count` takes the
    form, and a pattern would promise `sum` does too.
  - **`any_dtype` narrowed rather than moved.** It answers "which functions may a non-numeric
    *column* be given", and the bare form gives no column, so it sits outside the rule instead of
    becoming an exception to it. The narrowing is published in `slot_kinds["aggregate"]`, since the
    list itself is only a list of names.

  **The accumulator was already the right shape to extend.** A count is now a set of distinct values
  and an avg was already a running `{sum, count}`, so both are finished by one pass:
  `convert_avg_in_data_map` became `finalize_data_map` and dispatches on the accumulator's *shape*
  rather than a flag, which makes it idempotent -- converting an avg twice used to raise "'float'
  object is not subscriptable". `_build_data_map` also stopped spelling out the same accumulators the
  update path spells out, and feeds the first row through `update_data_map` like every other row.

  **What the slot holds is now named, because this release is what made the old claim false.**
  `_data_map` was annotated `dict[str, str | int | bool | date]`, and the distinct count added a
  `set` to it that the union never admitted, alongside the avg's `dict` and an avg's `float` result
  that it had never admitted either. The union was also wrong about `float` at all nine sites that
  spelled it out: a float column is ordinary, and `SELECT cust, quant.sum` over one returns floats.
  Fixed here rather than left for a follow-up, on the J5 precedent -- the annotation is this
  release's own line, so no wheel ever carried it. It is now three named types with the distinction
  the one union was blurring: `CellValue` (what the frame holds), `Accumulator` (what a slot holds
  *mid-flight*, which is not always an answer) and `ProjectedValue` (what reaches the caller, `None`
  included). See the mypy item above for what that did to the error count and why the count was
  never a count of problems.

  **Validated against SQL, not just against itself.** Two new sqlite parity tests over `sales.csv`
  pin the two counts to `COUNT(*)` and `COUNT(DISTINCT state)`, and they disagree on that data, so a
  test agreeing with both would prove nothing. The three MF parity queries that used `count(quant)`
  now say `count(distinct quant)`, which is what their ESQL side asks for. Covered by
  `tests/execution/test_count.py` (30 tests) plus the grammar bindings, and the two collision rules
  by one test either side of each seam: `parse_over_clause` directly and the accessor for the query
  that motivates it, the reserved column at `df.esql` and through `query` and `validate`.

  **Verified the guards bite**, and two of them did not at first, which is the part worth recording.
  Reverting the distinct count fails 9, un-reserving the bare word in SELECT fails 21, reading
  `g1.count` as a column fails 7, and skipping a row that holds a blank fails 6. But **dropping a
  bare form from `forms` passed**: the test that runs the forms is parametrized over the list, so
  deleting an entry deletes its own test -- a shape worth watching for anywhere a published list
  drives its own coverage. It is now bound to `BARE_AGGREGATE_FUNCTIONS`, which the parser reads, and
  fails. **Idempotence passed too**, because nothing called the finalize pass twice; it has a unit
  test now rather than a docstring claiming a property nothing exercised.

  **Prose updated to match**, and the G2 guard fired on the way through, which is it working: the
  aggregate-forms assertion failed the moment `GRAMMAR` grew `group.count` and `syntax.md` still said
  "two forms". SELECT gained a **Counting** section with the table of four spellings, the reserved
  word, the blank-cell rule and the `sum / count` note; HAVING says the bare form works there too;
  ORDER BY's examples now sort by `-count` rather than by a borrowed `-position.count`. Every example
  was run against the engine over `sales.csv`.

  **Portfolio-side follow-up, required, and this is the migration H4 was filed with.** No new name in
  `esql.__all__` and no new slot kind, so neither the export-diff guard nor `unhandledSlotKinds`
  fires -- `grammar.json` simply carries four forms where it carried two. What does change is
  *meaning*: all 13 curated examples borrow `position` for a row count and now answer the distinct
  count instead. `RESERVED_COLUMN` is a new `error_type` its funnel should have a case for, and any
  dataset with a `count` column now fails its build with that message rather than at query time. They still parse, so nothing fails loudly; `esql-smoke` compares against the SQL
  equivalent and is what catches them. Land it with D1 as filed. The result table must also read
  `forms` rather than looking for a dot, or a bare `count` column is filed as a dimension.

## v1.15.1 — two `__eq__` methods that never ran (2026-07-31)

- [x] **L2, which closes Stream L.** `GlobalAggregate` and `GroupAggregate` each carried an `__eq__`
  comparing a chosen subset of their keys. Neither ever ran. Bumped `1.15.0 -> 1.15.1`; the gate is
  green at **436 tests** (was 428). No behavior change, by construction: the methods were unreachable
  before and are absent now.

  **Why they could not run.** A TypedDict is not a class with methods. `GlobalAggregate(...)`
  constructs a plain `dict`, so `type(instance)` is `dict` and Python resolves `==` on `dict`; the
  function object sits on a type nothing is ever an instance of. They would have raised
  `AttributeError` if they had, since they used `self.column` attribute access on what is a dict.

  **Why it was worth more than tidiness.** They sat on the comparison the SELECT/HAVING merge in
  `_build_parsed_query` performs -- `if aggregate not in aggregates[scope]` is a membership test and
  therefore an equality test -- and that merge is BUG-8's fix from v1.1. So the file declaring the
  aggregate shapes stated a rule for how aggregates compare, on the path where getting it wrong
  silently doubles a sum, and the rule was both dead and *wrong*: `GlobalAggregate.__eq__` ignored
  `group`, while the dict equality that actually runs compares every key.

  **The gap the tamper test found, which is the part worth recording.** The first cut asserted the
  two dicts unequal and asserted the merge dedups. Reinstating the dead semantics as a *live* merge
  rule -- dedup on `column` and `function`, ignoring `group` -- **passed all seven tests**. Asserting
  two values are unequal proves nothing about a comparison that never consults them. The case that
  bites is two group aggregates in one query (`g1.quant.sum` and `g2.quant.sum`, which scope to
  different rows), and there was no such query in the file. There is now, and it fails under that
  tamper. Global and group aggregates cannot collide this way at all, since they live in separate
  scope lists and are never compared, so `group_specific` is the only place `group` carries weight.

  Covered by `tests/parser/test_aggregate_identity.py` (8 tests), which pins the equality that *runs*
  rather than the one that was written down. Verified three ways: removing the dedup guard fails 2,
  the ignore-`group` tamper above fails 1, and **putting the deleted `__eq__` back verbatim passes**,
  which is the evidence that deleting it is a no-op rather than an assertion that it is.

  **Portfolio-side follow-up: none.** No export, no new name, no `GRAMMAR` key, no behavior.

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
