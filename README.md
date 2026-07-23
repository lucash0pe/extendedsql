
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

Aggregates are rounded to 2 decimal places by default. You can change this by passing a different value to the query as `decimal_places`.

```python
from esql import ESQLAccessor

query_output = df.esql.query(
    query="SELECT cust, prod, quant.avg",
    decimal_places=4
)
```

## ESQL Input Data and Query Syntax

ESQL can only handle datatables with strings, numbers, booleans, and dates. When the esql.query is called on a DataFrame, these types will be enforced on values in the Dataframe. Dates should be in `yyyy-mm-dd` format to ensure that they are handled correctly. Columns with other datatypes will be casted and handled as strings.

Refer to the [documentation](public/docs/syntax.md) on the ESQL query syntax located in `public/docs/` for information on writing an ESQL query.

When writing conditions that include dates, write them in the in `yyyy-mm-dd` format within single or double quotes. 

Strings should also be inside single or double quotes. Keep in mind that escaping characters in python strings may cause problems. It is best to not include data in the datatable that require escape characters to match. If your data contains quotes, it is suggested that you use the opposite quotes to write them (e.g. " ' ' " or ' " " ').


## Development

ESQL uses [uv](https://docs.astral.sh/uv/) for dependency management and packaging.

```sh
uv sync --extra dev   # install runtime + dev dependencies
make check            # the gate: ruff lint + pytest
make test             # tests only
make lint             # ruff
make typecheck        # mypy (advisory; see BACKLOG.md)
make build            # build the wheel + sdist into dist/
```

The engine lives in `src/esql/` (`parser/` turns a query into a typed clause structure,
`execution/` computes the grouped result via the Φ-operator algorithm). See `BACKLOG.md` for
tracked work.

