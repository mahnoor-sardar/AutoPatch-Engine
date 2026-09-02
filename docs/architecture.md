# Architecture (Weeks 1–2)

Simple monorepo. No shared libraries or plugin frameworks.

## Folders

- **backend/** — FastAPI, Celery, GitHub installation tokens, E2B clone, Tree-sitter symbols, FCM send.
- **web/** — Next.js 14 App Router console: home, runs, repositories, activity, settings. It uses REST plus `GET/WS /v1/ws/runs`.
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
Web                 -->  FastAPI GET /health, /v1/sandbox/*, /v1/github/connected
Web                 -->  FastAPI WebSocket /v1/ws/runs
```

The console consumes the run list, per-run audit, global audit, diagnosis, and connected repositories. Approval OTP/HMAC remains on Android.

The original Weeks 1–2 “out of scope” list is historical. Repro/patch, OTP gates, GitHub PRs, and the live web console now exist. This file is not a complete feature inventory.
