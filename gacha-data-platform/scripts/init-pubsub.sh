#!/bin/sh
# Create Pub/Sub topics and subscriptions on the emulator.
# Runs as a Docker init container after the emulator is healthy.
# NOTE: Uses POSIX sh (not bash) — no arrays or bashisms.

set -eu

PUBSUB_HOST="${PUBSUB_EMULATOR_HOST:-pubsub-emulator:8085}"
PROJECT="gacha-local"

echo "Waiting for Pub/Sub emulator at ${PUBSUB_HOST}..."
until curl -sf "http://${PUBSUB_HOST}" > /dev/null 2>&1; do
  sleep 1
done
echo "Pub/Sub emulator is up."

# Debezium routes all tables to one topic via ByLogicalTableRouter.
# Create the unified topic + subscription.
echo "Creating unified CDC topic: gacha-cdc-all"
curl -sf -X PUT "http://${PUBSUB_HOST}/v1/projects/${PROJECT}/topics/gacha-cdc-all" || true

echo "Creating CDC subscription: cdc-sub"
curl -sf -X PUT "http://${PUBSUB_HOST}/v1/projects/${PROJECT}/subscriptions/cdc-sub" \
  -H "Content-Type: application/json" \
  -d "{\"topic\": \"projects/${PROJECT}/topics/gacha-cdc-all\"}" || true

# DLQ topic + subscription
echo "Creating DLQ topic: cdc-dlq"
curl -sf -X PUT "http://${PUBSUB_HOST}/v1/projects/${PROJECT}/topics/cdc-dlq" || true

echo "Creating DLQ subscription: cdc-dlq-sub"
curl -sf -X PUT "http://${PUBSUB_HOST}/v1/projects/${PROJECT}/subscriptions/cdc-dlq-sub" \
  -H "Content-Type: application/json" \
  -d "{\"topic\": \"projects/${PROJECT}/topics/cdc-dlq\"}" || true

# Also create per-table topics in case Debezium publishes before the
# router transform kicks in (snapshot phase).
for table in pulls transactions players player_pity player_inventory; do
  TOPIC="gacha.public.${table}"
  echo "Creating per-table topic: ${TOPIC}"
  curl -sf -X PUT "http://${PUBSUB_HOST}/v1/projects/${PROJECT}/topics/${TOPIC}" || true
done

echo "Pub/Sub setup complete."
