"""
Shared DuckDB fixture for all levels.

Usage (like a pytest fixture):
    from db import create_db

    conn = create_db()  # in-memory, seeded with all datasets
    conn.sql("SELECT * FROM sales.orders WHERE amount > 100").fetchdf()

Datasets & tables:
    sales.orders      — order_id, customer, amount, region
    sales.products    — product_id, name, price
    marketing.campaigns — campaign_id, name, spend, clicks
    hr.employees      — emp_id, name, dept, salary

Design:
    - DuckDB schemas = BQ datasets (sales, marketing, hr)
    - In-memory by default (no file), so each run starts fresh
    - Swap to real BQ later by replacing this module
"""

import duckdb


def create_db() -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB with seeded data. Like a pytest fixture."""
    conn = duckdb.connect(":memory:")

    # -- sales dataset --
    conn.execute("CREATE SCHEMA IF NOT EXISTS sales")
    conn.execute("""
        CREATE TABLE sales.orders (
            order_id   INTEGER,
            customer   VARCHAR,
            amount     DOUBLE,
            region     VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO sales.orders VALUES
            (1, 'Alice',   250.00, 'APAC'),
            (2, 'Bob',     130.50, 'NA'),
            (3, 'Charlie', 475.00, 'EMEA'),
            (4, 'Dana',     89.99, 'APAC'),
            (5, 'Eve',     312.00, 'NA')
    """)

    conn.execute("""
        CREATE TABLE sales.products (
            product_id VARCHAR,
            name       VARCHAR,
            price      DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO sales.products VALUES
            ('P1', 'Widget A', 25.00),
            ('P2', 'Widget B', 49.99),
            ('P3', 'Widget C', 99.00)
    """)

    # -- marketing dataset --
    conn.execute("CREATE SCHEMA IF NOT EXISTS marketing")
    conn.execute("""
        CREATE TABLE marketing.campaigns (
            campaign_id VARCHAR,
            name        VARCHAR,
            spend       INTEGER,
            clicks      INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO marketing.campaigns VALUES
            ('C1', 'Summer Sale',  5000, 12000),
            ('C2', 'Winter Push',  8000,  9500),
            ('C3', 'Spring Launch', 3200,  7800)
    """)

    # -- hr dataset (the "expensive" one for cost guardrail demos) --
    conn.execute("CREATE SCHEMA IF NOT EXISTS hr")
    conn.execute("""
        CREATE TABLE hr.employees (
            emp_id  VARCHAR,
            name    VARCHAR,
            dept    VARCHAR,
            salary  INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO hr.employees VALUES
            ('E1', 'Dana',  'Engineering', 120000),
            ('E2', 'Eve',   'Marketing',    95000),
            ('E3', 'Frank', 'Engineering', 135000),
            ('E4', 'Grace', 'Sales',        88000)
    """)

    return conn


# ---- Helpers that wrap DuckDB to feel like a BQ client ----

ALL_DATASETS = ["sales", "marketing", "hr"]


def list_tables(conn: duckdb.DuckDBPyConnection, schema: str) -> list[str]:
    """List tables in a schema (dataset)."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
        [schema],
    ).fetchall()
    return [r[0] for r in rows]


def run_query(conn: duckdb.DuckDBPyConnection, sql: str) -> str:
    """Execute SQL and return results as formatted text."""
    result = conn.execute(sql)
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()
    if not rows:
        return "No rows returned."

    # Format as text table
    header = " | ".join(columns)
    separator = "-" * len(header)
    lines = [header, separator]
    for row in rows:
        lines.append(" | ".join(str(v) for v in row))
    lines.append(f"\n({len(rows)} rows)")
    return "\n".join(lines)


def dry_run(conn: duckdb.DuckDBPyConnection, sql: str) -> dict:
    """Simulate a dry run using EXPLAIN. Returns fake cost estimate.

    DuckDB doesn't have BQ's bytesProcessed API, so we estimate based on
    which schemas are referenced. HR queries are "expensive" to make the
    cost guardrail demo interesting.
    """
    # Validate SQL parses
    conn.execute(f"EXPLAIN {sql}")

    # Fake cost: HR = 50GB, others = 500MB
    sql_lower = sql.lower()
    if "hr." in sql_lower:
        bytes_processed = 50_000_000_000  # 50 GB
    elif "marketing." in sql_lower:
        bytes_processed = 2_000_000_000  # 2 GB
    else:
        bytes_processed = 500_000_000  # 500 MB

    cost_per_tb = 5.0  # BQ on-demand pricing
    cost = (bytes_processed / 1e12) * cost_per_tb

    return {
        "sql": sql,
        "estimated_bytes": bytes_processed,
        "estimated_cost_usd": cost,
    }


if __name__ == "__main__":
    # Quick sanity check
    conn = create_db()
    for schema in ALL_DATASETS:
        tables = list_tables(conn, schema)
        print(f"{schema}: {tables}")
    print()
    print(run_query(conn, "SELECT * FROM sales.orders WHERE amount > 100"))
    print()
    print(dry_run(conn, "SELECT * FROM hr.employees"))
