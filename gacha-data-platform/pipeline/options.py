"""Pipeline options for the Gacha CDC streaming pipeline."""

from apache_beam.options.pipeline_options import PipelineOptions


class GachaOptions(PipelineOptions):
    """Custom options for the Gacha CDC pipeline."""

    @classmethod
    def _add_argparse_args(cls, parser) -> None:
        parser.add_argument(
            "--project_id",
            default="gacha-local",
            help="GCP project ID (or emulator project).",
        )
        parser.add_argument(
            "--input_subscription",
            required=True,
            help="Pub/Sub subscription path, e.g. projects/gacha-local/subscriptions/cdc-sub",
        )
        parser.add_argument(
            "--dlq_topic",
            required=True,
            help="Pub/Sub DLQ topic path, e.g. projects/gacha-local/topics/cdc-dlq",
        )
        parser.add_argument(
            "--merge_window_minutes",
            type=int,
            default=2,
            help="How often (minutes) to trigger the windowed Silver merge.",
        )
        parser.add_argument(
            "--bigquery_endpoint",
            default="http://localhost:9050",
            help="BigQuery endpoint — override for the local emulator.",
        )
        parser.add_argument(
            "--pubsub_endpoint",
            default="localhost:8085",
            help="Pub/Sub emulator endpoint (host:port). Leave empty to use real GCP.",
        )
