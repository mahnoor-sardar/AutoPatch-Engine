# Architecture (Weeks 1–2)

Simple monorepo. No shared libraries or plugin frameworks.

## Folders

- **backend/** — FastAPI, Celery, GitHub installation tokens, E2B clone, Tree-sitter symbols, FCM send.
- **web/** — Next.js 14 App Router status page only. Live dashboard is Weeks 7–8.
- **android-app/** — Kotlin Compose companion: register device and receive a test push. OTP, biometrics, and remote pause/kill come later.
- **infra/** — Docker Compose for local Postgres and Redis.
- **docs/** — How to run and how pieces connect.

## Communication

```
GitHub App webhook  -->  FastAPI  -->  PostgreSQL
                         FastAPI  -->  Redis/Celery  -->  E2B microVM (clone)
                         Celery   -->  Tree-sitter   -->  PostgreSQL (symbols)
Android app         -->  FastAPI (register device)
FastAPI             -->  Firebase Cloud Messaging --> Android
Web                 -->  FastAPI GET /health
```

No WebSocket server in Weeks 1–2.

## Out of scope until later

LangGraph/LiteLLM, repro/patch loop, Sentry/Datadog, OTP/biometric gates, mobile diff review, GitHub PR creation, pgvector, production deploy.
