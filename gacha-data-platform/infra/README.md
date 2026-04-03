# Infra

GCP infrastructure as code using Pulumi (Python).

## Resources

```
Cloud SQL (Postgres)     ← Source database
Pub/Sub Topic + Sub      ← CDC message queue
Dataflow Job             ← Beam pipeline
BigQuery Dataset         ← Bronze / Silver / Gold
Cloud Run                ← UI + Chat
Langfuse (self-hosted)   ← On GKE or use Langfuse Cloud
```

## Deployment

```bash
cd infra
pulumi up          # Deploy all resources
pulumi destroy     # Tear down
```

## Stack Pattern

Two-stack deployment:
1. **`foundation`** — Networking, IAM, datasets, topics (rarely changes)
2. **`application`** — Dataflow job, Cloud Run services (changes often)

## CI/CD

GitHub Actions in `.github/workflows/`:
- **`ci.yml`** — Lint, test, type check on PR
- **`deploy.yml`** — Pulumi preview on PR, pulumi up on merge to main

## Local vs GCP

Everything runs locally via Docker Compose with no GCP dependency.
Pulumi config is for optional real deployment — proves you can do it, but reviewers don't need a GCP account to evaluate the project.
