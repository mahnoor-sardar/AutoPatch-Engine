# AutoPatch Engine

Autonomous Cloud Incident Investigator & Verified Bug-Fixer (Mahify).

Weeks 1–2 foundations: GitHub App webhooks, FastAPI, PostgreSQL, E2B sandbox clone, Tree-sitter indexing, and an Android companion with a test Firebase push.

The AI patching agent, OTP gates, Sentry/Datadog ingest, and production dashboard are **not** in this phase.

## Layout

| Path | Role |
|------|------|
| `backend/` | FastAPI, Celery, GitHub App, E2B, Tree-sitter, FCM |
| `web/` | Next.js 14 status page (`GET /health`) |
| `android/` | Kotlin + Jetpack Compose companion |
| `infra/` | Docker Compose for Postgres 16 and Redis 7 |
| `docs/` | Setup and architecture |

## Quick start

See [docs/setup.md](docs/setup.md). Architecture: [docs/architecture.md](docs/architecture.md).


<!-- pipeline test -->
