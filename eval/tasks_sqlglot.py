"""SQLGlot task set. Ground truth is computed by sqlglot itself, never by a model."""

from __future__ import annotations

import random

import sqlglot
from sqlglot import parse_one, transpile

from eval.tasks import Task

SYSTEM_HINT = ("For SQL transpilation results, return the exact transpiled SQL string. "
               "For tables, list table names separated by commas. For yes/no questions use 'yes' or 'no'.")


def generate(per_category: int = 6, seed: int = 42) -> list[Task]:
    rng = random.Random(seed)
    tasks: list[Task] = []

    # Transpile BigQuery -> Postgres
    queries = [
        "SELECT id, name FROM users WHERE active = TRUE",
        "SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id",
        "SELECT COUNT(DISTINCT email) FROM subscribers WHERE created_at > '2024-01-01'",
    ]
    for i in range(per_category):
        sql = queries[i % len(queries)]
        result = transpile(sql, read="bigquery", write="postgres")
        expected = result[0] if result else sql
        tasks.append(Task(f"transpile_bq_pg-{i}", "transpile",
                          f"Transpile this BigQuery SQL to Postgres: {sql}",
                          expected))

    # List tables a query touches
    table_queries = [
        "SELECT a FROM users WHERE id = 1",
        "SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id",
        "SELECT amount FROM invoices JOIN vendors ON invoices.vendor_id = vendors.id WHERE vendors.country = 'US'",
    ]
    for i in range(per_category):
        sql = table_queries[i % len(table_queries)]
        q = parse_one(sql)
        tables = sorted({str(t) for t in q.find_all(sqlglot.exp.Table)})
        expected = ", ".join(tables) if tables else "none"
        tasks.append(Task(f"list_tables-{i}", "list_tables",
                          f"What tables does the query '{sql}' reference?",
                          expected))

    # Format SQL (identity / clean normalization)
    format_queries = [
        "SELECT a FROM t WHERE a > 1",
        "SELECT id, name, email FROM users WHERE active = TRUE AND created_at > '2024-01-01' ORDER BY name",
    ]
    for i in range(per_category):
        sql = format_queries[i % len(format_queries)]
        clean = transpile(sql, identity=True)[0]
        tasks.append(Task(f"format_sql-{i}", "format_sql",
                          f"Normalize this SQL using sqlglot (identity transpile): {sql}",
                          clean))

    # Transpile MySQL -> BigQuery
    for i in range(per_category):
        sql = "SELECT 1 + 2 FROM dual"
        result = transpile(sql, read="mysql", write="bigquery")
        expected = result[0] if result else sql
        tasks.append(Task(f"transpile_mysql_bq-{i}", "transpile",
                          f"Transpile this MySQL SQL to BigQuery: {sql}",
                          expected))

    return tasks


def score(task: Task, answer: str) -> bool:
    a = answer.strip()
    if task.category == "transpile":
        # Normalize whitespace for comparison
        norm = lambda s: " ".join(s.split())
        return norm(a) == norm(task.expected)
    if task.category == "list_tables":
        # Accept either exact or comma-separated match; allow any order
        got = {x.strip() for x in a.split(",")} if a.lower() != "none" else set()
        exp = {x.strip() for x in task.expected.split(",")} if task.expected.lower() != "none" else set()
        return got == exp
    if task.category == "format_sql":
        # Compare normalized SQL (ignore pretty-print whitespace differences)
        norm = lambda s: " ".join(s.split())
        return norm(a) == norm(task.expected)
    raise ValueError(task.category)
