"""BigQuery helpers for the Gacha CDC pipeline.

Supports both real GCP credentials and the local BigQuery emulator
(ghcr.io/goccy/bigquery-emulator). The emulator is used automatically
when no default credentials are found, or when an explicit endpoint is
provided.
"""

import logging
from typing import Any

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Module-level client cache — one client per endpoint so tests can inject
# different endpoints without global state leaking between calls.
_clients: dict[str, bigquery.Client] = {}


def get_client(
    project_id: str = "gacha-local",
    endpoint: str = "http://localhost:9050",
) -> bigquery.Client:
    """Return a BigQuery client.

    Tries to use application-default credentials first (real GCP). If
    credentials are not available, falls back to the emulator at
    ``endpoint`` using anonymous credentials — same pattern as the
    production reference code.

    Results are cached per (project_id, endpoint) pair.
    """
    cache_key = f"{project_id}@{endpoint}"
    if cache_key in _clients:
        return _clients[cache_key]

    try:
        client = bigquery.Client(project=project_id)
        # Verify credentials work by making a cheap call.
        list(client.list_datasets(max_results=1))
        logger.info("BigQuery: using application-default credentials")
    except Exception:
        logger.info("BigQuery: no credentials found, falling back to emulator at %s", endpoint)
        from google.auth.credentials import AnonymousCredentials

        client = bigquery.Client(
            project=project_id,
            credentials=AnonymousCredentials(),
            client_options={"api_endpoint": endpoint},
        )

    _clients[cache_key] = client
    return client


def write_to_bronze(
    table_name: str,
    rows: list[dict[str, Any]],
    project_id: str = "gacha-local",
    dataset: str = "bronze",
    endpoint: str = "http://localhost:9050",
) -> None:
    """Insert rows into a Bronze BigQuery table.

    Uses ``insert_rows_json`` (streaming insert).  Logs any row-level errors
    but does not raise — failed rows should be handled by the caller.

    Args:
        table_name:  Source table name, e.g. ``pulls``.
        rows:        List of dicts matching the bronze schema.
        project_id:  BigQuery project.
        dataset:     BigQuery dataset (default: ``bronze``).
        endpoint:    BigQuery API endpoint (for emulator).
    """
    client = get_client(project_id=project_id, endpoint=endpoint)
    table_ref = f"{project_id}.{dataset}.{table_name}"

    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        logger.error("write_to_bronze: insert errors for %s — %s", table_ref, errors)
    else:
        logger.debug("write_to_bronze: inserted %d rows into %s", len(rows), table_ref)


def merge_to_silver(
    table_name: str,
    project_id: str = "gacha-local",
    bronze_dataset: str = "bronze",
    silver_dataset: str = "silver",
    endpoint: str = "http://localhost:9050",
) -> None:
    """MERGE upsert rows from Bronze staging into Silver.

    Matches on ``id``.  Updates all fields on match; inserts the row when
    no match is found.  Only processes rows with ``event IN ('insert', 'update')``.

    Args:
        table_name:      Source table name, e.g. ``pulls``.
        project_id:      BigQuery project.
        bronze_dataset:  Dataset holding the raw/staging Bronze table.
        silver_dataset:  Dataset holding the curated Silver table.
        endpoint:        BigQuery API endpoint.
    """
    client = get_client(project_id=project_id, endpoint=endpoint)

    bronze_ref = f"`{project_id}.{bronze_dataset}.{table_name}`"
    silver_ref = f"`{project_id}.{silver_dataset}.silver_{table_name}`"

    sql = f"""
    MERGE {silver_ref} AS target
    USING (
        SELECT
            id,
            data,
            event,
            event_timestamp,
            ingested_at
        FROM {bronze_ref}
        WHERE event IN ('insert', 'update')
    ) AS source
    ON target.id = source.id
    WHEN MATCHED THEN
        UPDATE SET
            data             = source.data,
            event            = source.event,
            event_timestamp  = source.event_timestamp,
            ingested_at      = source.ingested_at
    WHEN NOT MATCHED THEN
        INSERT (id, data, event, event_timestamp, ingested_at)
        VALUES (source.id, source.data, source.event, source.event_timestamp, source.ingested_at)
    """

    try:
        job = client.query(sql)
        job.result()  # wait for completion
        logger.info("merge_to_silver: merged %s → silver_%s", table_name, table_name)
    except GoogleAPICallError as exc:
        logger.error("merge_to_silver: failed for %s — %s", table_name, exc)
        raise


def delete_from_silver(
    table_name: str,
    project_id: str = "gacha-local",
    bronze_dataset: str = "bronze",
    silver_dataset: str = "silver",
    endpoint: str = "http://localhost:9050",
) -> None:
    """DELETE rows from Silver that appear as deletes in Bronze staging.

    Matches on ``id``.  Only processes rows with ``event = 'delete'``.

    Args:
        table_name:      Source table name, e.g. ``player_inventory``.
        project_id:      BigQuery project.
        bronze_dataset:  Dataset holding the Bronze staging table.
        silver_dataset:  Dataset holding the Silver table.
        endpoint:        BigQuery API endpoint.
    """
    client = get_client(project_id=project_id, endpoint=endpoint)

    bronze_ref = f"`{project_id}.{bronze_dataset}.{table_name}`"
    silver_ref = f"`{project_id}.{silver_dataset}.silver_{table_name}`"

    sql = f"""
    DELETE FROM {silver_ref}
    WHERE id IN (
        SELECT id
        FROM {bronze_ref}
        WHERE event = 'delete'
    )
    """

    try:
        job = client.query(sql)
        job.result()
        logger.info("delete_from_silver: deleted from silver_%s", table_name)
    except GoogleAPICallError as exc:
        logger.error("delete_from_silver: failed for %s — %s", table_name, exc)
        raise
