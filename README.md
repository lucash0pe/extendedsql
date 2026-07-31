
# ExtendedSQL

ESQL is a query language based off of SQL. It solves the biggest problem with SQL: the inability to compute aggregates outside of the grouping attributes.

ESQL is based off of the SQL extension proposed in the two papers in `public/ref/`, [MFQueries](public/ref/MFQueries.pdf) and [Ad-Hoc OLAP Query Processing](public/ref/Ad-Hoc_OLAP_Query_Processing.pdf). The papers propose a concept of the Phi Operator in relational algebra and the basic syntax of the language, as well as the algorithm used to compute the resulting relation. Read the articles to learn more about the theory behind the query language.

## Why use ESQL

Since ESQL automatically groups by grouping attributes in the query, it is best used for data analysis (OLAP) rather than for transactional processes.

ESQL is designed to be able to include multiple aggregate queries for the five main aggregate functions (`sum`, `avg`, `min`, `max`, `count`), without the need of nested subqueries and repetitive selection, grouping, and aggregation. Therefore you can write queries that are much shorter than if you had to write a SQL query.

For example, using the `sales` table located in `public/data/`, you could write a SQL query that computes the average and maximum sales quantity for each customer, product, and year.

```sql
WITH groups AS (
    SELECT cust, prod, year
    FROM sales
    GROUP BY cust, prod, year
),
nj AS (
    SELECT cust, prod, year, AVG(quant) AS avg, MAX(quant) AS max
    FROM sales
    WHERE state = 'NJ'
    GROUP BY cust, prod, year
),
ny AS (
    SELECT cust, prod, year, AVG(quant) AS avg, MAX(quant) AS max
    FROM sales
    WHERE state = 'NY'
    GROUP BY cust, prod, year
),
ct AS (
    SELECT cust, prod, year, AVG(quant) AS avg, MAX(quant) AS max
    FROM sales
    WHERE state = 'CT'
    GROUP BY cust, prod, year
)
SELECT 
    g.cust, g.prod, g.year, nj.avg AS nj_avg, nj.max AS nj_max, 
    ny.avg AS ny_avg, ny.max AS ny_max, ct.avg AS ct_avg, ct.max AS ct_max
FROM groups g
LEFT JOIN nj ON nj.cust = g.cust AND nj.prod = g.prod AND nj.year = g.year
LEFT JOIN ny ON ny.cust = g.cust AND ny.prod = g.prod AND ny.year = g.year
LEFT JOIN ct ON ct.cust = g.cust AND ct.prod = g.prod AND ct.year = g.year
ORDER BY g.cust, g.prod, g.year
```

However, with ESQL, you could write the same query much easier.

```sql
SELECT cust, prod, year, nj.quant.avg, nj.quant.max,
ny.quant.avg, ny.quant.max, ct.quant.avg, ct.quant.max
OVER nj, ny, ct
SUCH THAT nj.state = 'NJ', ny.state = 'NY', ct.state = 'CT'
ORDER BY 3
```



## Using ESQL in your project

### Prerequisites

You must have [Python 3.12 or higher](https://www.python.org/downloads/) installed on your local machine. 

### Install the package
```sh
pip3 install git+https://github.com/lucash0pe/extendedsql.git
```

### Use with a pandas DataFrame

Make sure that you have pandas installed on your local machine or in a virtual environment.

```sh
pip3 install pandas
```

Load your data into a pandas DataFrame. If you wanted to do this with `sales.csv` in `public/data/`, you would use the pandas `read_csv()` function.

```python
import pandas as pd

df = pd.read_csv('public/data/sales.csv')
```

Then import and use the ESQL Dataframe Accessor, which will return the query result set as a pandas DataFrame.

```python
from esql import ESQLAccessor

new_df = df.esql.query("SELECT cust, prod, quant.avg")
```

Queries are not case sensitive, and neither is matching a name in the query against a column of your
frame, so a frame whose columns are `Cust` and `Quant` takes `SELECT Cust, Quant.avg` and
`SELECT cust, quant.avg` alike. The result is labelled with your frame's spelling rather than the
query's, so the column names you get back do not depend on how the query was typed. A text value is
the exception and stays case sensitive, because its contents are data: see
[Case](public/docs/syntax.md#case).

One name is reserved in your data: a column called `count` (in any case) is refused, with a
`ParsingError` asking you to rename it. `count` on its own is a query's way of saying "how many
rows", so a column of that name would be a word with two readings and no way to pick between them.
Every other aggregate function needs a column before it, so a column named `sum` or `avg` is fine.

Aggregates are rounded to 2 decimal places by default. You can change this by passing a different value to the query as `decimal_places`.

```python
from esql import ESQLAccessor

query_output = df.esql.query(
    query="SELECT cust, prod, quant.avg",
    decimal_places=4
)
```

### Checking a query without running it

`validate` parses a query against the frame's columns and stops there. It returns `None` when the
query parses and raises the same `ParsingError` `query` would, so both share one error contract.

```python
from esql.parser.error import ParsingError

try:
    df.esql.validate("SELECT cust, quantt.avg")
except ParsingError as e:
    e.error_type  # ParsingErrorType.SELECT_CLAUSE — which clause it fell in
    e.token       # 'quantt.avg' — the fragment it rejected
    e.message     # "Invalid aggregate column: 'quantt.avg'"
```

Parsing is the cheap half of a query — microseconds against tens of milliseconds — so this is
usable for live feedback while someone is still typing. `token` is what lets an editor point at the
mistake rather than only name the clause. It is a fragment and not a character offset because the
parser runs on a whitespace-collapsed copy of the query, so offsets into it do not map back onto
what was typed. The fragment itself is spelled exactly as the query spelled it, so a literal match
finds it.

The token sets the parser accepts are exported for the same reason: `esql.KEYWORDS`,
`esql.AGGREGATE_FUNCTIONS`, `esql.CONDITIONAL_OPERATORS` and `esql.SEMI_JOIN_OPERATOR`. Anything
that documents or completes ESQL should read those rather than keep its own copy.

Token sets alone do not say where a token is legal, so `esql.GRAMMAR` carries the per-clause
shapes: what each clause accepts, which operators it takes, what it requires to be present, and
whether it repeats. It is plain dicts and lists, so `json.dumps(esql.GRAMMAR)` is the whole export
step for a consumer that renders a completion menu or a reference table.

```python
import esql

esql.GRAMMAR["clauses"]["HAVING"]["operators"]   # ['>=', '<=', '!=', '==', '>', '<', '=']
esql.GRAMMAR["clauses"]["SUCH THAT"]["requires"] # ['OVER']
esql.GRAMMAR["aggregates"]["numeric_only"]       # ['sum', 'avg', 'min', 'max']
```

`GRAMMAR` is a description rather than the parser itself, so `tests/parser/test_grammar.py` checks
every claim it makes by running the parser: each listed operator must parse in that clause and each
unlisted one must raise. A rule added to the parser without updating the description fails there.

### The demo asset shape

`esql.demokit.build_demo` is build-time tooling that validates a dataset's ESQL examples against
their SQL equivalents and writes the JSON a host demo front-end reads. `esql.DATASET_SCHEMA` is that
JSON's declared shape, as JSON Schema, exported the same way `GRAMMAR` is — a plain dict, published
verbatim, so a host generates its own types from it rather than hand-keeping a copy.

```python
import esql

esql.DATASET_SCHEMA["$defs"]["Example"]["required"]        # what every example carries
esql.DATASET_SCHEMA["$defs"]["ColumnType"]["enum"]         # ['string', 'number', 'boolean', 'date']
```

`build_demo` validates its output against the schema before writing anything and emits the schema
beside the assets as `dataset.schema.json`, so a shape error fails the build rather than reaching a
consumer as a missing key. Each column in the asset's `schema` also carries a `values` list — its
distinct values as text, capped, and omitted for continuous columns — so an editor can complete
`WHERE state = '` from build-time data without calling the engine.

## ESQL Input Data and Query Syntax

ESQL can only handle datatables with strings, numbers, booleans, and dates. When the esql.query is called on a DataFrame, these types will be enforced on values in the Dataframe. Dates should be in `yyyy-mm-dd` format to ensure that they are handled correctly. Columns with other datatypes will be casted and handled as strings.

Refer to the [documentation](public/docs/syntax.md) on the ESQL query syntax located in `public/docs/` for information on writing an ESQL query.

When writing conditions that include dates, write them in the in `yyyy-mm-dd` format within single or double quotes. 

Strings should also be inside single or double quotes. A value that itself contains a quote can be written two ways. Delimit it with the other kind, which is usually the more readable of the two:

```python
df.esql.query("""SELECT song WHERE song = "(I'm A) Road Runner" """)
```

Or double the delimiter to hold it as text, the way SQL does. This is the form that covers a value containing both kinds of quote:

```python
df.esql.query("""SELECT song WHERE song = '(I''m A) Road Runner'""")
df.esql.query("""SELECT title WHERE title = 'He said "it''s fine"'""")
```

A literal that is opened and never closed is rejected rather than guessed at, so a stray quote is a parsing error and not a silently empty result.


## Development

ESQL uses [uv](https://docs.astral.sh/uv/) for dependency management and packaging.

```sh
uv sync --extra dev   # install runtime + dev dependencies
make check            # the gate: ruff lint + pytest
make test             # tests only
make lint             # ruff
make typecheck        # mypy (advisory; see .claude/status.md)
make build            # build the wheel + sdist into dist/
```

The engine lives in `src/esql/` (`parser/` turns a query into a typed clause structure,
`execution/` computes the grouped result via the Φ-operator algorithm). See `.claude/status.md` for
tracked work.

