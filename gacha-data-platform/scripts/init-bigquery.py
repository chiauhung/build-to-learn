"""Create BigQuery datasets and tables on the emulator.

Runs once after the BigQuery emulator is healthy.
Creates: bronze dataset (raw CDC), silver dataset (cleaned).
"""

import sys
import time

from google.api_core.exceptions import Conflict
from google.auth.credentials import AnonymousCredentials
from google.cloud import bigquery

PROJECT = "gacha-local"
ENDPOINT = "http://bigquery-emulator:9050"
DATASETS = ["bronze", "silver"]

# Bronze schema — same for all source tables
BRONZE_FIELDS = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("data", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("event", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("event_timestamp", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("source_table", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_schema", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
]

# Silver schemas per table
SILVER_SCHEMAS = {
    "silver_pulls": [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("player_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("banner_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("character_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("rarity", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("pity_count", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("is_guaranteed", "BOOLEAN"),
        bigquery.SchemaField("pull_number", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("batch_id", "STRING"),
        bigquery.SchemaField("crystals_spent", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("pulled_at", "TIMESTAMP"),
    ],
    "silver_transactions": [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("player_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("package_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("crystals_added", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("amount_usd", "NUMERIC", mode="REQUIRED"),
        bigquery.SchemaField("payment_method", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payment_status", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("is_first_buy", "BOOLEAN"),
        bigquery.SchemaField("transacted_at", "TIMESTAMP"),
    ],
    "silver_players": [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("username", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("region", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("crystal_balance", "INTEGER"),
        bigquery.SchemaField("registered_at", "TIMESTAMP"),
        bigquery.SchemaField("updated_at", "TIMESTAMP"),
    ],
    "silver_player_pity": [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("player_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("banner_type", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("pity_count", "INTEGER"),
        bigquery.SchemaField("guaranteed_next", "BOOLEAN"),
        bigquery.SchemaField("updated_at", "TIMESTAMP"),
    ],
    "silver_player_inventory": [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("player_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("character_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("constellation", "INTEGER"),
        bigquery.SchemaField("obtained_at", "TIMESTAMP"),
        bigquery.SchemaField("updated_at", "TIMESTAMP"),
    ],
}

SOURCE_TABLES = ["pulls", "transactions", "players", "player_pity", "player_inventory"]


def wait_for_emulator(client: bigquery.Client, retries: int = 30) -> None:
    for i in range(retries):
        try:
            list(client.list_datasets(max_results=1))
            print("BigQuery emulator is up.")
            return
        except Exception:
            print(f"Waiting for BigQuery emulator... ({i + 1}/{retries})")
            time.sleep(2)
    print("BigQuery emulator not reachable. Exiting.")
    sys.exit(1)


def main() -> None:
    client = bigquery.Client(
        project=PROJECT,
        credentials=AnonymousCredentials(),
        client_options={"api_endpoint": ENDPOINT},
    )

    wait_for_emulator(client)

    # Create datasets
    for ds_name in DATASETS:
        ds_ref = bigquery.DatasetReference(PROJECT, ds_name)
        ds = bigquery.Dataset(ds_ref)
        try:
            client.create_dataset(ds)
            print(f"Created dataset: {ds_name}")
        except Conflict:
            print(f"Dataset already exists: {ds_name}")

    # Create Bronze tables (one per source table, same schema)
    for table_name in SOURCE_TABLES:
        table_ref = f"{PROJECT}.bronze.{table_name}"
        table = bigquery.Table(table_ref, schema=BRONZE_FIELDS)
        try:
            client.create_table(table)
            print(f"Created table: bronze.{table_name}")
        except Conflict:
            print(f"Table already exists: bronze.{table_name}")

    # Create Silver tables
    for table_name, schema in SILVER_SCHEMAS.items():
        table_ref = f"{PROJECT}.silver.{table_name}"
        table = bigquery.Table(table_ref, schema=schema)
        try:
            client.create_table(table)
            print(f"Created table: silver.{table_name}")
        except Conflict:
            print(f"Table already exists: silver.{table_name}")

    print("\nBigQuery setup complete.")


if __name__ == "__main__":
    main()
