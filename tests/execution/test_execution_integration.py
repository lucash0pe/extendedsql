import math
import sqlite3
from datetime import date

import pandas as pd
import pytest

from esql.accessor import _enforce_allowed_dtypes


def _execute_sql_query_through_sqlite3(sql: str) -> pd.DataFrame:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    with open("public/data/load_sales_table.sql") as sql_file:
        sql_script = sql_file.read()
        cur.executescript(sql_script)
    cur.execute(sql)
    rows = cur.fetchall()
    conn.close()
    return pd.DataFrame([dict(row) for row in rows])


def _debug_mismatched_result_sets(
    expected_set: set[list[int | str | bool | date]], received_set: set[list[int | str | bool | date]]
) -> None:
    missing = expected_set - received_set
    extra = received_set - expected_set
    print("\n\n--- DEBUG INFO ---")
    print(f"Total expected rows: {len(expected_set)}")
    print(f"Total received rows: {len(received_set)}")
    print(f"Missing rows ({len(missing)}):", missing)
    print(f"Extra rows ({len(extra)}):", extra)
    print("--- END DEBUG ---\n\n")


def _normalize_tuple(row):
    return tuple(None if isinstance(val, float) and math.isnan(val) else val for val in row)


def _test_query(sql: str, esql: str, data: pd.DataFrame) -> None:
    sql_df = _enforce_allowed_dtypes(
        _execute_sql_query_through_sqlite3(sql).round(2).reset_index(drop=True)
    )  # .sort_values(by='cust')
    esql_df = data.esql.query(esql).round(2).reset_index(drop=True)
    sql_set = {_normalize_tuple(row) for row in sql_df.to_numpy()}
    esql_set = {_normalize_tuple(row) for row in esql_df.to_numpy()}
    if sql_set != esql_set:
        _debug_mismatched_result_sets(expected_set=sql_set, received_set=esql_set)
    assert sql_set == esql_set, "Queries did not return the same result."


@pytest.mark.timeout(5)
def test_select_query(sales_test_data: pd.DataFrame):
    sql = """
        SELECT cust, prod, day, month, year, state, quant, date, credit FROM sales
    """
    esql = """
        SELECT cust, prod, day, month, year, state, quant, date, credit
    """
    _test_query(sql, esql, data=sales_test_data)


@pytest.mark.timeout(5)
def test_integer_where_query(sales_test_data: pd.DataFrame):
    sql = """
        SELECT cust, quant
        FROM sales
        WHERE quant != 100
        GROUP BY cust, quant
    """
    esql = """
        SELECT cust, quant
        WHERE quant != 100
    """
    _test_query(sql, esql, data=sales_test_data)


@pytest.mark.timeout(5)
def test_float_where_query(sales_test_data: pd.DataFrame):
    sql = """
        SELECT cust, quant
        FROM sales
        WHERE quant <= 55.5
        GROUP BY cust, quant
    """
    esql = """
        SELECT cust, quant
        WHERE quant <= 55.5
    """
    _test_query(sql, esql, data=sales_test_data)


@pytest.mark.timeout(5)
def test_boolean_where_query(sales_test_data: pd.DataFrame):
    sql = """
        SELECT cust, prod, quant, date
        FROM sales
        where credit = true
    """
    esql = """
        SELECT cust, prod, quant, date
        Where credit
    """
    _test_query(sql, esql, data=sales_test_data)


@pytest.mark.timeout(5)
def test_gt_date_where_query(sales_test_data: pd.DataFrame):
    sql = """
        select cust,prod, sum(quant) from sales
        where date > '2019-04-12'
        group by cust, prod
    """
    esql = """
        SELECT cust, prod, quant.sum
        where date > '2019-04-12'
    """
    _test_query(sql, esql, data=sales_test_data)


@pytest.mark.timeout(5)
def test_eq_date_where_query(sales_test_data: pd.DataFrame):
    sql = """
        select cust,prod, count(month) from sales
        where date = '2020-04-13'
        group by cust, prod
    """
    esql = """
        SELECT cust, prod, month.count
        where date = '2020-4-13'
    """
    _test_query(sql, esql, data=sales_test_data)


@pytest.mark.timeout(5)
def test_string_where_query(sales_test_data: pd.DataFrame):
    sql = """
        SELECT cust, prod, year
        from sales
        WHERE state = 'NY'
        GROUP BY cust, prod, year
    """
    esql = """
        SELECT cust, prod, year
        WHERE state = 'NY'
    """
    _test_query(sql, esql, data=sales_test_data)


@pytest.mark.timeout(5)
def test_mf_query(sales_test_data: pd.DataFrame):
    sql = """
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
            g.cust,
            g.prod,
            g.year,
            nj.avg AS nj_avg,
            nj.max AS nj_max,
            ny.avg AS ny_avg,
            ny.max AS ny_max,
            ct.avg AS ct_avg,
            ct.max AS ct_max
        FROM groups g
        LEFT JOIN nj ON nj.cust = g.cust AND nj.prod = g.prod AND nj.year = g.year
        LEFT JOIN ny ON ny.cust = g.cust AND ny.prod = g.prod AND ny.year = g.year
        LEFT JOIN ct ON ct.cust = g.cust AND ct.prod = g.prod AND ct.year = g.year
        ORDER BY g.cust, g.prod, g.year
    """
    esql = """
        SELECT cust, prod, year, nj.quant.avg, nj.quant.max, ny.quant.avg, ny.quant.max, ct.quant.avg, ct.quant.max
        OVER nj, ny, ct
        SUCH THAT nj.state = 'NJ', ny.state = 'NY', ct.state = 'CT'
    """
    _test_query(sql, esql, data=sales_test_data)


@pytest.mark.timeout(5)
def test_mf_query_with_where(sales_test_data: pd.DataFrame):
    sql = """
        WITH groups AS (
            SELECT cust, prod
            FROM sales
            GROUP BY cust, prod
        ),
        old AS (
            SELECT cust, prod , sum(quant) as sum, count(quant) as count
            FROM sales
            WHERE date < '2017-01-01' and credit = true
            GROUP BY cust, prod
        ),
        newer AS (
            SELECT cust, prod, sum(quant) as sum, count(quant) as count
            FROM sales
            WHERE date >= '2017-01-01' and date < '2018-12-31' and credit = true
            GROUP BY cust, prod
        ),
        new AS (
            SELECT cust, prod , sum(quant) as sum, count(quant) as count
            FROM sales
            WHERE date >= '2018-12-31' and credit = true
            GROUP BY cust, prod
        )
        SELECT
            g.cust cust,
            g.prod prod,
             old.sum old_sum, old.count old_count,
            newer.sum newer_sum, newer.count newer_count,
            new.sum new_sum,new.count new_count
        FROM groups g
        LEFT JOIN old ON old.cust = g.cust AND old.prod = g.prod
        LEFT JOIN newer ON newer.cust = g.cust AND newer.prod = g.prod
        LEFT JOIN new ON new.cust = g.cust AND new.prod = g.prod
        ORDER BY g.cust, g.prod
    """
    esql = """
        SELECT cust, prod, old.quant.sum, old.quant.count, newer.quant.sum, newer.quant.count, new.quant.sum, new.quant.count
        OVER old,newer,new
        WHERE credit
        SUCH THAT old.date < '2017-01-01',
                  newer.date >= '2017-01-01' and newer.date < '2018-12-31',
                  new.date >= '2018-12-31'
    """
    _test_query(sql, esql, data=sales_test_data)


@pytest.mark.timeout(5)
def test_mf_query_with_having(sales_test_data: pd.DataFrame):
    sql = """
        WITH groups AS (
            SELECT cust, state
            FROM sales
            GROUP BY cust, state
        ),
        q1 AS (
            SELECT cust, state , min(quant) AS min, MAX(quant) AS max
            FROM sales
            WHERE month = 1 or month = 2 or month = 3
            GROUP BY cust, state
        ),
        q2 AS (
            SELECT cust, state , min(quant) AS min, MAX(quant) AS max
            FROM sales
            WHERE month = 4 or month = 5 or month = 6
            GROUP BY cust, state
        ),
        q3 AS (
            SELECT cust, state , min(quant) AS min, MAX(quant) AS max
            FROM sales
            WHERE month = 7 or month = 8 or month = 9
            GROUP BY cust, state
        ),
        q4 AS (
            SELECT cust, state , min(quant) AS min, MAX(quant) AS max
            FROM sales
            WHERE month = 10 or month = 11 or month = 12
            GROUP BY cust, state
        )
        SELECT
            g.cust,
            g.state,
            q1.min AS q1_min,
            q1.max AS q1_max,
            q2.min AS q2_min,
            q2.max AS q2_max,
            q3.min AS q3_min,
            q3.max AS q3_max,
            q4.min AS q4_min,
            q4.max AS q4_max
        FROM groups g
        LEFT JOIN q1 ON q1.cust = g.cust AND q1.state = g.state
        LEFT JOIN q2 ON q2.cust = g.cust AND q2.state = g.state
        LEFT JOIN q3 ON q3.cust = g.cust AND q3.state = g.state
        LEFT JOIN q4 ON q4.cust = g.cust AND q4.state = g.state
        WHERE q1.max < 1000 and not q2.min < 20 or q3.max = 500
        ORDER BY g.cust, g.state
    """
    esql = """
        SELECT cust, state, q1.quant.min, q1.quant.max, q2.quant.min, q2.quant.max, q3.quant.min, q3.quant.max, q4.quant.min, q4.quant.max
        OVER q1,q2,q3,q4
        SUCH THAT q1.month = 1 or q1.month = 2 or q1.month = 3,
                  q2.month = 4 or q2.month = 5 or q2.month = 6,
                  q3.month = 7 or q3.month = 8 or q3.month = 9,
                  q4.month = 10 or q4.month = 11 or q4.month = 12
        HAVING q1.quant.max < 1000 and not q2.quant.min < 20 or q3.quant.max == 500
    """
    _test_query(sql, esql, data=sales_test_data)


if __name__ == "__main__":
    pytest.main()
