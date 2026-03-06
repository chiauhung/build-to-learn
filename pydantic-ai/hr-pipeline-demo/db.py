"""
Shared DuckDB fixture — mock data modelled after real schemas.

Schemas:
  identity.company          — id, name, slug, status, industry_norm, products
  talent_acquisition.job    — id, company_id, title, status, created_at
  talent_acquisition.job_application
                            — id, company_id, job_id, first_name, last_name,
                              primary_contact_email, status, channel, source,
                              nationality, role_fit_score, culture_fit_score,
                              has_passed_screening, criteria_met_percentage,
                              submitted_at

Two companies:
  1001 — Growthly Tech      (technology, SG)
  1002 — BrightHire Bank    (financial services, SG)

Two jobs (one per company):
  job-g01 — Senior Software Engineer @ Growthly Tech
  job-b01 — Investment Analyst       @ BrightHire Bank

Applicants — all start as 'applied'; agent shortlists based on role_fit_score:
  Growthly (10):
    applied — Aisha (85), Darren (88), Wei Ling (91), Nurul (42), Rajan (72),
              Marcus (65), James (45), Priya (null), Mei (null), Faizal (null)
  BrightHire (5):
    applied — Ahmad (88), Sarah (72), Kevin (50), Fatimah (60), Raj (null)

Cost simulation (mirrors real data sensitivity):
  identity.*                   → $0.0025  (cheap, public-ish company info)
  talent_acquisition.job       → $0.01    (moderate)
  talent_acquisition.job_application → $0.25  (expensive — PII data)
"""

import duckdb


def create_db() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")

    # ── identity schema ──────────────────────────────────────────
    conn.execute("CREATE SCHEMA IF NOT EXISTS identity")
    conn.execute("""
        CREATE TABLE identity.company (
            id              INTEGER,
            name            VARCHAR,
            slug            VARCHAR,
            status          VARCHAR,
            industry_norm   VARCHAR,
            products        VARCHAR,
            is_live         BOOLEAN,
            created_at      VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO identity.company VALUES
            (1001, 'Growthly Tech',   'growthly-tech',   'active', 'technology',
             'talent_acquisition,talent_management', true,  '2023-01-15T08:00:00Z'),
            (1002, 'BrightHire Bank', 'brighthire-bank', 'active', 'financial_services_insurance',
             'talent_acquisition',                   true,  '2023-03-22T09:30:00Z')
    """)

    # ── talent_acquisition schema ─────────────────────────────────
    conn.execute("CREATE SCHEMA IF NOT EXISTS talent_acquisition")
    conn.execute("""
        CREATE TABLE talent_acquisition.job (
            id          VARCHAR,
            company_id  INTEGER,
            title       VARCHAR,
            status      VARCHAR,
            created_at  VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO talent_acquisition.job VALUES
            ('job-g01', 1001, 'Senior Software Engineer', 'active', '2024-01-10T10:00:00Z'),
            ('job-b01', 1002, 'Investment Analyst',        'active', '2024-02-05T09:00:00Z')
    """)

    conn.execute("""
        CREATE TABLE talent_acquisition.job_application (
            id                       VARCHAR,
            company_id               INTEGER,
            job_id                   VARCHAR,
            first_name               VARCHAR,
            last_name                VARCHAR,
            primary_contact_email    VARCHAR,
            status                   VARCHAR,
            channel                  VARCHAR,
            source                   VARCHAR,
            nationality              VARCHAR,
            role_fit_score           DOUBLE,
            culture_fit_score        DOUBLE,
            has_passed_screening     BOOLEAN,
            criteria_met_percentage  DOUBLE,
            submitted_at             VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO talent_acquisition.job_application VALUES
            -- Growthly Tech applicants (job-g01, company_id=1001)
            ('app-g01', 1001, 'job-g01', 'Aisha',   'Rahman',  'aisha.rahman@gmail.com',
             'applied', 'applied',   'company_careers_page', 'MY', 85.0, 78.0, true,  92.0, '2024-01-12T08:20:00Z'),
            ('app-g02', 1001, 'job-g01', 'Marcus',  'Tan',     'marcus.tan@outlook.com',
             'applied', 'applied',   'linkedin',             'SG', 65.0, null, true,  70.0, '2024-01-14T11:05:00Z'),
            ('app-g03', 1001, 'job-g01', 'Priya',   'Singh',   'priya.singh@yahoo.com',
             'applied', 'applied',   'jobstreet',            'IN', null, null, null,  null, '2024-01-18T09:45:00Z'),
            ('app-g04', 1001, 'job-g01', 'James',   'Lim',     'james.lim@gmail.com',
             'applied', 'applied',   'linkedin',             'SG', 45.0, 52.0, false, 40.0, '2024-01-11T14:30:00Z'),
            ('app-g05', 1001, 'job-g01', 'Mei',     'Chen',    'mei.chen@hotmail.com',
             'applied', 'imported',  null,                   'MY', null, null, null,  null, null),
            ('app-g06', 1001, 'job-g01', 'Marcus',  'Koh',     'marcus.koh@gmail.com',
             'applied', 'applied',   'linkedin',             'SG', 88.0, 82.0, true,  90.0, '2024-01-15T10:00:00Z'),
            ('app-g07', 1001, 'job-g01', 'Nurul',   'Ain',     'nurul.ain@gmail.com',
             'applied', 'applied',   'jobstreet',            'MY', 42.0, 38.0, false, 35.0, '2024-01-16T09:00:00Z'),
            ('app-g08', 1001, 'job-g01', 'Wei Ling','Loh',     'weiling.loh@gmail.com',
             'applied', 'applied',   'company_careers_page', 'SG', 91.0, 88.0, true,  97.0, '2024-01-17T08:30:00Z'),
            ('app-g09', 1001, 'job-g01', 'Rajan',   'Pillai',  'rajan.pillai@outlook.com',
             'applied', 'applied',   'linkedin',             'MY', 72.0, 70.0, true,  78.0, '2024-01-19T11:00:00Z'),
            ('app-g10', 1001, 'job-g01', 'Faizal',  'Hassan',  'faizal.hassan@yahoo.com',
             'applied', 'imported',  null,                   'MY', null, null, null,  null, null),

            -- BrightHire Bank applicants (job-b01, company_id=1002)
            ('app-b01', 1002, 'job-b01', 'Ahmad',   'Yusof',   'ahmad.yusof@gmail.com',
             'applied', 'applied',   'company_careers_page', 'MY', 88.0, 80.0, true,  95.0, '2024-02-07T08:00:00Z'),
            ('app-b02', 1002, 'job-b01', 'Sarah',   'Wong',    'sarah.wong@gmail.com',
             'applied', 'applied',   'linkedin',             'SG', 72.0, null, true,  75.0, '2024-02-08T10:30:00Z'),
            ('app-b03', 1002, 'job-b01', 'Kevin',   'Ng',      'kevin.ng@outlook.com',
             'applied', 'applied',   'jobstreet',            'SG', 50.0, 45.0, false, 38.0, '2024-02-06T13:00:00Z'),
            ('app-b04', 1002, 'job-b01', 'Fatimah', 'Ali',     'fatimah.ali@gmail.com',
             'applied', 'applied',   'company_careers_page', 'MY', 60.0, null, true,  65.0, '2024-02-09T09:15:00Z'),
            ('app-b05', 1002, 'job-b01', 'Raj',     'Kumar',   'raj.kumar@yahoo.com',
             'applied', 'imported',  null,                   'IN', null, null, null,  null, null)
    """)

    return conn


ALL_DATASETS = ["identity", "talent_acquisition"]


def list_tables(conn: duckdb.DuckDBPyConnection, schema: str) -> list[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
        [schema],
    ).fetchall()
    return [r[0] for r in rows]


def run_query(conn: duckdb.DuckDBPyConnection, sql: str) -> str:
    result = conn.execute(sql)
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()
    if not rows:
        return "No rows returned."
    header = " | ".join(columns)
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(" | ".join(str(v) for v in row))
    lines.append(f"({len(rows)} rows)")
    return "\n".join(lines)


def estimate_cost(sql: str) -> dict:
    """
    Fake cost estimation mirroring real data sensitivity.
      job_application  → expensive ($0.25) — PII: names, emails, scores
      job              → moderate  ($0.01)
      identity.*       → cheap     ($0.0025)
    """
    sql_lower = sql.lower()
    if "job_application" in sql_lower:
        bytes_processed = 50_000_000_000  # 50 GB → $0.25  (PII table)
    elif "talent_acquisition.job" in sql_lower:
        bytes_processed = 2_000_000_000  # 2 GB  → $0.01
    else:
        bytes_processed = 500_000_000  # 500 MB → $0.0025
    cost = (bytes_processed / 1e12) * 5.0  # BQ on-demand: $5/TB
    return {"bytes": bytes_processed, "cost_usd": round(cost, 4)}
