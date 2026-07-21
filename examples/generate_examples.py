"""Generate the curated ESQL demo examples for each sample dataset.

For every dataset, each example pairs an ESQL query with a hand-written SQL equivalent and
a short description. This runs the ESQL query through the engine to produce the result
table, AND runs the SQL equivalent through sqlite over the same data (loaded with pandas
to_sql) to prove the two are equivalent (set comparison). It writes public/examples/demo.json
for the website demo: a list of datasets, each with its schema and validated examples.

Datasets come from examples/generate_datasets.py. Run:
  uv run python examples/generate_datasets.py    # (re)generate the CSVs
  uv run python examples/generate_examples.py     # validate + write demo.json
"""

import json
import math
import sqlite3
from pathlib import Path

import pandas as pd
from pandas.api import types as pdt

import esql.accessor  # noqa: F401  (registers the .esql accessor)
from esql.accessor import _enforce_allowed_dtypes

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "public" / "data"
OUT = REPO_ROOT / "public" / "examples" / "demo.json"


DATASETS = [
    {
        "id": "streams",
        "label": "Music streaming",
        "description": (
            "Music streaming plays: how long each listener played each artist, where, and "
            "whether they were a premium subscriber."
        ),
        "examples": [
            {
                "id": "aggregates",
                "title": "Aggregates per group",
                "description": (
                    "ESQL groups by the plain columns you name (like GROUP BY) and computes each "
                    "aggregate as column.function. Here: number of plays, average, and total "
                    "minutes for each listener."
                ),
                "esql": "SELECT listener, minutes.count, minutes.avg, minutes.sum ORDER BY 1",
                "sql": (
                    "SELECT listener, COUNT(minutes), ROUND(AVG(minutes),2), SUM(minutes) "
                    "FROM streams GROUP BY listener ORDER BY listener"
                ),
            },
            {
                "id": "where",
                "title": "Filter rows before aggregating (WHERE)",
                "description": (
                    "WHERE removes rows before any aggregate is computed. A boolean column like "
                    "premium can stand alone as a condition. Average minutes per genre, premium "
                    "plays only."
                ),
                "esql": "SELECT genre, minutes.avg WHERE premium ORDER BY 1",
                "sql": (
                    "SELECT genre, ROUND(AVG(minutes),2) FROM streams "
                    "WHERE premium = 1 GROUP BY genre ORDER BY genre"
                ),
            },
            {
                "id": "having",
                "title": "Filter groups by an aggregate (HAVING)",
                "description": (
                    "HAVING keeps only the groups whose aggregate meets a condition. Listeners "
                    "whose average play is longer than 120 minutes."
                ),
                "esql": "SELECT listener, minutes.avg HAVING minutes.avg > 120 ORDER BY 1",
                "sql": (
                    "SELECT listener, ROUND(AVG(minutes),2) FROM streams "
                    "GROUP BY listener HAVING AVG(minutes) > 120 ORDER BY listener"
                ),
            },
            {
                "id": "over-regions",
                "title": "Aggregates across groups, no subqueries (the Φ operator)",
                "description": (
                    "The feature SQL lacks: OVER names sub-groups and SUCH THAT scopes each one, "
                    "so one query returns each listener's average minutes in the US, UK, and EU "
                    "side by side. In SQL this needs three grouped subqueries joined together."
                ),
                "esql": (
                    "SELECT listener, us.minutes.avg, uk.minutes.avg, eu.minutes.avg "
                    "OVER us, uk, eu "
                    "SUCH THAT us.region = 'US', uk.region = 'UK', eu.region = 'EU' "
                    "ORDER BY 1"
                ),
                "sql": (
                    "WITH g AS (SELECT DISTINCT listener FROM streams), "
                    "us AS (SELECT listener, ROUND(AVG(minutes),2) a FROM streams WHERE region='US' GROUP BY listener), "
                    "uk AS (SELECT listener, ROUND(AVG(minutes),2) a FROM streams WHERE region='UK' GROUP BY listener), "
                    "eu AS (SELECT listener, ROUND(AVG(minutes),2) a FROM streams WHERE region='EU' GROUP BY listener) "
                    "SELECT g.listener, us.a AS us_a, uk.a AS uk_a, eu.a AS eu_a FROM g "
                    "LEFT JOIN us ON us.listener=g.listener LEFT JOIN uk ON uk.listener=g.listener "
                    "LEFT JOIN eu ON eu.listener=g.listener ORDER BY g.listener"
                ),
            },
            {
                "id": "over-quarters",
                "title": "Time buckets as groups",
                "description": (
                    "The same mechanic turns months into quarters: average minutes per genre for "
                    "each quarter of the year, in one pass."
                ),
                "esql": (
                    "SELECT genre, q1.minutes.avg, q2.minutes.avg, q3.minutes.avg, q4.minutes.avg "
                    "OVER q1, q2, q3, q4 "
                    "SUCH THAT q1.month <= 3, q2.month >= 4 and q2.month <= 6, "
                    "q3.month >= 7 and q3.month <= 9, q4.month >= 10 "
                    "ORDER BY 1"
                ),
                "sql": (
                    "WITH g AS (SELECT DISTINCT genre FROM streams), "
                    "q1 AS (SELECT genre, ROUND(AVG(minutes),2) a FROM streams WHERE month<=3 GROUP BY genre), "
                    "q2 AS (SELECT genre, ROUND(AVG(minutes),2) a FROM streams WHERE month>=4 AND month<=6 GROUP BY genre), "
                    "q3 AS (SELECT genre, ROUND(AVG(minutes),2) a FROM streams WHERE month>=7 AND month<=9 GROUP BY genre), "
                    "q4 AS (SELECT genre, ROUND(AVG(minutes),2) a FROM streams WHERE month>=10 GROUP BY genre) "
                    "SELECT g.genre, q1.a AS q1_a, q2.a AS q2_a, q3.a AS q3_a, q4.a AS q4_a FROM g "
                    "LEFT JOIN q1 ON q1.genre=g.genre LEFT JOIN q2 ON q2.genre=g.genre "
                    "LEFT JOIN q3 ON q3.genre=g.genre LEFT JOIN q4 ON q4.genre=g.genre ORDER BY g.genre"
                ),
            },
            {
                "id": "combined",
                "title": "Everything together",
                "description": (
                    "WHERE, OVER/SUCH THAT, and ORDER BY in one query: total premium listening "
                    "minutes per listener, split into the first and second half of the year."
                ),
                "esql": (
                    "SELECT listener, h1.minutes.sum, h2.minutes.sum "
                    "OVER h1, h2 WHERE premium "
                    "SUCH THAT h1.month <= 6, h2.month >= 7 ORDER BY 1"
                ),
                "sql": (
                    "WITH g AS (SELECT DISTINCT listener FROM streams WHERE premium=1), "
                    "h1 AS (SELECT listener, SUM(minutes) s FROM streams WHERE premium=1 AND month<=6 GROUP BY listener), "
                    "h2 AS (SELECT listener, SUM(minutes) s FROM streams WHERE premium=1 AND month>=7 GROUP BY listener) "
                    "SELECT g.listener, h1.s AS h1_s, h2.s AS h2_s FROM g "
                    "LEFT JOIN h1 ON h1.listener=g.listener LEFT JOIN h2 ON h2.listener=g.listener "
                    "ORDER BY g.listener"
                ),
            },
        ],
    },
    {
        "id": "weather",
        "label": "Weather readings",
        "description": (
            "Daily weather readings by station and city: temperature, humidity, and whether it "
            "rained. Numbers behave nothing like the streaming set, which is the point."
        ),
        "examples": [
            {
                "id": "aggregates",
                "title": "Aggregates per group",
                "description": (
                    "Number of readings, and the average and highest temperature, for each city."
                ),
                "esql": "SELECT city, temp.count, temp.avg, temp.max ORDER BY 1",
                "sql": (
                    "SELECT city, COUNT(temp), ROUND(AVG(temp),2), MAX(temp) "
                    "FROM weather GROUP BY city ORDER BY city"
                ),
            },
            {
                "id": "where",
                "title": "Filter rows before aggregating (WHERE)",
                "description": (
                    "WHERE removes rows before aggregating. Average humidity per city, on rainy "
                    "days only."
                ),
                "esql": "SELECT city, humidity.avg WHERE rained ORDER BY 1",
                "sql": (
                    "SELECT city, ROUND(AVG(humidity),2) FROM weather "
                    "WHERE rained = 1 GROUP BY city ORDER BY city"
                ),
            },
            {
                "id": "having",
                "title": "Filter groups by an aggregate (HAVING)",
                "description": "Cities whose average temperature is above 55 degrees.",
                "esql": "SELECT city, temp.avg HAVING temp.avg > 55 ORDER BY 1",
                "sql": (
                    "SELECT city, ROUND(AVG(temp),2) FROM weather "
                    "GROUP BY city HAVING AVG(temp) > 55 ORDER BY city"
                ),
            },
            {
                "id": "over-seasons",
                "title": "Aggregates across groups, no subqueries (the Φ operator)",
                "description": (
                    "OVER and SUCH THAT split each city's readings into the four seasons, so one "
                    "query returns average temperature per city per season. Winter spans December, "
                    "January, and February, so its section uses OR."
                ),
                "esql": (
                    "SELECT city, winter.temp.avg, spring.temp.avg, summer.temp.avg, fall.temp.avg "
                    "OVER winter, spring, summer, fall "
                    "SUCH THAT winter.month <= 2 or winter.month = 12, "
                    "spring.month >= 3 and spring.month <= 5, "
                    "summer.month >= 6 and summer.month <= 8, "
                    "fall.month >= 9 and fall.month <= 11 "
                    "ORDER BY 1"
                ),
                "sql": (
                    "WITH g AS (SELECT DISTINCT city FROM weather), "
                    "winter AS (SELECT city, ROUND(AVG(temp),2) a FROM weather WHERE month<=2 OR month=12 GROUP BY city), "
                    "spring AS (SELECT city, ROUND(AVG(temp),2) a FROM weather WHERE month>=3 AND month<=5 GROUP BY city), "
                    "summer AS (SELECT city, ROUND(AVG(temp),2) a FROM weather WHERE month>=6 AND month<=8 GROUP BY city), "
                    "fall AS (SELECT city, ROUND(AVG(temp),2) a FROM weather WHERE month>=9 AND month<=11 GROUP BY city) "
                    "SELECT g.city, winter.a AS w_a, spring.a AS sp_a, summer.a AS su_a, fall.a AS f_a FROM g "
                    "LEFT JOIN winter ON winter.city=g.city LEFT JOIN spring ON spring.city=g.city "
                    "LEFT JOIN summer ON summer.city=g.city LEFT JOIN fall ON fall.city=g.city ORDER BY g.city"
                ),
            },
            {
                "id": "combined",
                "title": "Everything together",
                "description": (
                    "WHERE, OVER/SUCH THAT, and ORDER BY together: on rainy days, each city's "
                    "average temperature in the first vs second half of the year."
                ),
                "esql": (
                    "SELECT city, h1.temp.avg, h2.temp.avg "
                    "OVER h1, h2 WHERE rained "
                    "SUCH THAT h1.month <= 6, h2.month >= 7 ORDER BY 1"
                ),
                "sql": (
                    "WITH g AS (SELECT DISTINCT city FROM weather WHERE rained=1), "
                    "h1 AS (SELECT city, ROUND(AVG(temp),2) a FROM weather WHERE rained=1 AND month<=6 GROUP BY city), "
                    "h2 AS (SELECT city, ROUND(AVG(temp),2) a FROM weather WHERE rained=1 AND month>=7 GROUP BY city) "
                    "SELECT g.city, h1.a AS h1_a, h2.a AS h2_a FROM g "
                    "LEFT JOIN h1 ON h1.city=g.city LEFT JOIN h2 ON h2.city=g.city ORDER BY g.city"
                ),
            },
        ],
    },
]


def _friendly_type(series: pd.Series) -> str:
    dt = series.dtype
    if pdt.is_bool_dtype(dt):
        return "boolean"
    if pdt.is_numeric_dtype(dt):
        return "number"
    non_null = series.dropna()
    if len(non_null) and hasattr(non_null.iloc[0], "isoformat"):
        return "date"
    return "string"


def _schema(enforced: pd.DataFrame) -> list[dict]:
    return [{"name": c, "type": _friendly_type(enforced[c])} for c in enforced.columns]


def _run_sql(sql: str, raw: pd.DataFrame, table: str) -> pd.DataFrame:
    conn = sqlite3.connect(":memory:")
    raw.to_sql(table, conn, index=False)
    out = pd.read_sql_query(sql, conn)
    conn.close()
    return out


def _norm(row) -> tuple:
    return tuple(None if isinstance(v, float) and math.isnan(v) else v for v in row)


def _jsonable(v):
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 2)
    if hasattr(v, "item"):  # numpy scalar
        return v.item()
    return v


def main() -> None:
    out_datasets = []
    for ds in DATASETS:
        raw = pd.read_csv(DATA / f"{ds['id']}.csv")
        enforced = _enforce_allowed_dtypes(raw)
        examples = []
        for ex in ds["examples"]:
            esql_df = raw.esql.query(ex["esql"]).round(2).reset_index(drop=True)
            sql_df = _run_sql(ex["sql"], raw, ds["id"]).round(2).reset_index(drop=True)

            esql_set = {_norm(r) for r in esql_df.to_numpy()}
            sql_set = {_norm(r) for r in sql_df.to_numpy()}
            if esql_set != sql_set:
                raise SystemExit(
                    f"[{ds['id']}/{ex['id']}] ESQL and SQL disagree:\n"
                    f"  only in ESQL: {sorted(esql_set - sql_set)[:5]}\n"
                    f"  only in SQL:  {sorted(sql_set - esql_set)[:5]}"
                )

            examples.append(
                {
                    "id": ex["id"],
                    "title": ex["title"],
                    "description": ex["description"],
                    "esql": " ".join(ex["esql"].split()),
                    "sql": ex["sql"],
                    "columns": list(esql_df.columns),
                    "rows": [[_jsonable(v) for v in row] for row in esql_df.to_numpy().tolist()],
                }
            )
            print(f"[ok] {ds['id']}/{ex['id']}: {len(examples[-1]['rows'])} rows")

        out_datasets.append(
            {
                "id": ds["id"],
                "label": ds["label"],
                "description": ds["description"],
                "csv": f"{ds['id']}.csv",
                "schema": _schema(enforced),
                "examples": examples,
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out_datasets, indent=2))
    print(f"\nWrote {len(out_datasets)} datasets -> {OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
