"""Generate the curated ESQL demo examples.

Each example pairs an ESQL query with a hand-written SQL equivalent and a short
description. This script runs the ESQL query through the engine to produce the result
table, AND runs the SQL equivalent through sqlite over the same sample data to prove the
two are equivalent (set comparison, same harness as the integration tests). It then
writes public/examples/examples.json for the website demo to bundle.

Run: uv run python examples/generate_examples.py
"""

import json
import math
import sqlite3
from pathlib import Path

import pandas as pd

import esql.accessor  # noqa: F401  (registers the .esql accessor)
from esql.accessor import _enforce_allowed_dtypes

REPO_ROOT = Path(__file__).resolve().parent.parent
SALES_CSV = REPO_ROOT / "public" / "data" / "sales.csv"
LOAD_SQL = REPO_ROOT / "public" / "data" / "load_sales_table.sql"
OUT = REPO_ROOT / "public" / "examples" / "examples.json"


# Ordered simplest to most advanced, so the gallery teaches the language.
EXAMPLES = [
    {
        "id": "aggregates",
        "title": "Aggregates per group",
        "description": (
            "ESQL groups by the plain columns you name (like GROUP BY) and computes each "
            "aggregate as column.function. Here: count, average, and total quantity for "
            "each customer."
        ),
        "esql": "SELECT cust, quant.count, quant.avg, quant.sum ORDER BY 1",
        "sql": (
            "SELECT cust, COUNT(quant), ROUND(AVG(quant), 2), SUM(quant) "
            "FROM sales GROUP BY cust ORDER BY cust"
        ),
    },
    {
        "id": "where",
        "title": "Filter rows before aggregating (WHERE)",
        "description": (
            "WHERE removes rows before any aggregate is computed. A boolean column like "
            "credit can stand alone as a condition."
        ),
        "esql": "SELECT cust, quant.sum WHERE credit ORDER BY 1",
        "sql": "SELECT cust, SUM(quant) FROM sales WHERE credit = true GROUP BY cust ORDER BY cust",
    },
    {
        "id": "having",
        "title": "Filter groups by an aggregate (HAVING)",
        "description": (
            "HAVING keeps only the groups whose aggregate meets a condition. It can use "
            "aggregates that are not in the SELECT."
        ),
        "esql": "SELECT cust, quant.avg HAVING quant.avg > 505 ORDER BY 1",
        "sql": (
            "SELECT cust, ROUND(AVG(quant), 2) FROM sales "
            "GROUP BY cust HAVING AVG(quant) > 505 ORDER BY cust"
        ),
    },
    {
        "id": "over-states",
        "title": "Aggregates across groups, no subqueries (the Φ operator)",
        "description": (
            "The feature SQL lacks: OVER names sub-groups and SUCH THAT scopes each one, so "
            "one query returns the average quantity per customer in NJ, NY, and CT side by "
            "side. In SQL this needs three grouped subqueries joined back together."
        ),
        "esql": (
            "SELECT cust, nj.quant.avg, ny.quant.avg, ct.quant.avg "
            "OVER nj, ny, ct "
            "SUCH THAT nj.state = 'NJ', ny.state = 'NY', ct.state = 'CT' "
            "ORDER BY 1"
        ),
        "sql": (
            "WITH g AS (SELECT DISTINCT cust FROM sales), "
            "nj AS (SELECT cust, ROUND(AVG(quant),2) a FROM sales WHERE state='NJ' GROUP BY cust), "
            "ny AS (SELECT cust, ROUND(AVG(quant),2) a FROM sales WHERE state='NY' GROUP BY cust), "
            "ct AS (SELECT cust, ROUND(AVG(quant),2) a FROM sales WHERE state='CT' GROUP BY cust) "
            "SELECT g.cust, nj.a AS nj_a, ny.a AS ny_a, ct.a AS ct_a FROM g "
            "LEFT JOIN nj ON nj.cust=g.cust LEFT JOIN ny ON ny.cust=g.cust LEFT JOIN ct ON ct.cust=g.cust "
            "ORDER BY g.cust"
        ),
    },
    {
        "id": "over-quarters",
        "title": "Time buckets as groups",
        "description": (
            "The same mechanic turns months into quarters: average quantity per product for "
            "each quarter of the year, in one pass."
        ),
        "esql": (
            "SELECT prod, q1.quant.avg, q2.quant.avg, q3.quant.avg, q4.quant.avg "
            "OVER q1, q2, q3, q4 "
            "SUCH THAT q1.month <= 3, "
            "q2.month >= 4 and q2.month <= 6, "
            "q3.month >= 7 and q3.month <= 9, "
            "q4.month >= 10 "
            "ORDER BY 1"
        ),
        "sql": (
            "WITH g AS (SELECT DISTINCT prod FROM sales), "
            "q1 AS (SELECT prod, ROUND(AVG(quant),2) a FROM sales WHERE month<=3 GROUP BY prod), "
            "q2 AS (SELECT prod, ROUND(AVG(quant),2) a FROM sales WHERE month>=4 AND month<=6 GROUP BY prod), "
            "q3 AS (SELECT prod, ROUND(AVG(quant),2) a FROM sales WHERE month>=7 AND month<=9 GROUP BY prod), "
            "q4 AS (SELECT prod, ROUND(AVG(quant),2) a FROM sales WHERE month>=10 GROUP BY prod) "
            "SELECT g.prod, q1.a AS q1_a, q2.a AS q2_a, q3.a AS q3_a, q4.a AS q4_a FROM g "
            "LEFT JOIN q1 ON q1.prod=g.prod LEFT JOIN q2 ON q2.prod=g.prod "
            "LEFT JOIN q3 ON q3.prod=g.prod LEFT JOIN q4 ON q4.prod=g.prod "
            "ORDER BY g.prod"
        ),
    },
    {
        "id": "combined",
        "title": "Everything together",
        "description": (
            "WHERE, OVER/SUCH THAT, and ORDER BY in one query: total credit-sale quantity "
            "per customer, split into the first and second half of the year."
        ),
        "esql": (
            "SELECT cust, h1.quant.sum, h2.quant.sum "
            "OVER h1, h2 "
            "WHERE credit "
            "SUCH THAT h1.month <= 6, h2.month >= 7 "
            "ORDER BY 1"
        ),
        "sql": (
            "WITH g AS (SELECT DISTINCT cust FROM sales WHERE credit=true), "
            "h1 AS (SELECT cust, SUM(quant) s FROM sales WHERE credit=true AND month<=6 GROUP BY cust), "
            "h2 AS (SELECT cust, SUM(quant) s FROM sales WHERE credit=true AND month>=7 GROUP BY cust) "
            "SELECT g.cust, h1.s AS h1_s, h2.s AS h2_s FROM g "
            "LEFT JOIN h1 ON h1.cust=g.cust LEFT JOIN h2 ON h2.cust=g.cust "
            "ORDER BY g.cust"
        ),
    },
]


def _run_sql(sql: str) -> pd.DataFrame:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.executescript(LOAD_SQL.read_text())
    cur.execute(sql)
    rows = cur.fetchall()
    conn.close()
    return pd.DataFrame([dict(r) for r in rows])


def _norm(row) -> tuple:
    return tuple(None if isinstance(v, float) and math.isnan(v) else v for v in row)


def _jsonable(v):
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 2)
    if hasattr(v, "item"):  # numpy scalar
        return v.item()
    return v


def main() -> None:
    data = _enforce_allowed_dtypes(pd.read_csv(SALES_CSV))
    out = []
    for ex in EXAMPLES:
        esql_df = data.esql.query(ex["esql"]).round(2).reset_index(drop=True)
        sql_df = _run_sql(ex["sql"]).round(2).reset_index(drop=True)

        esql_set = {_norm(r) for r in esql_df.to_numpy()}
        sql_set = {_norm(r) for r in sql_df.to_numpy()}
        if esql_set != sql_set:
            raise SystemExit(
                f"[{ex['id']}] ESQL and SQL disagree:\n  only in ESQL: {esql_set - sql_set}\n"
                f"  only in SQL:  {sql_set - esql_set}"
            )

        out.append(
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
        print(f"[ok] {ex['id']}: {len(out[-1]['rows'])} rows, {len(out[-1]['columns'])} cols")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {len(out)} examples -> {OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
