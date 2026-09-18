# Local setup

## Prerequisites

- Git, Python 3.11+, Docker Desktop
- Node.js 20+ (web)
- Android Studio / JDK 17 (Android)
- ngrok or Cloudflare Tunnel (GitHub webhooks)
- Accounts when you exercise those paths: GitHub App, E2B, Firebase

## Environment

```text
cp .env.example .env
```

Fill GitHub, E2B, and Firebase values when you use those features. Do not commit `.env`, `.pem` files, or Firebase JSON credentials.

## Postgres and Redis

```text
docker compose -f infra/docker-compose.yml up -d
```

## Backend

```text
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Celery (second terminal, venv active, repo `backend/` as cwd):

```text
celery -A app.workers.celery_app worker --loglevel=info
```

Tests:

```text
cd backend
pytest
```

## GitHub App (webhook step)

Create a GitHub App with **Contents: Read**, **Pull requests: Write**, **Contents: Write**, and **Metadata: Read**. Subscribe to `installation` (and optionally `push`). Set the webhook URL to `https://<tunnel>/v1/github/webhook`. Install it on a private test repo. Put App ID, webhook secret, and PEM path in `.env`.

Pre-merge clone, install, and tests mint a **repository-scoped Contents: Read** installation token and authenticate Git with a command-local HTTP header. That token is not stored in `remote.origin.url`. PR publication happens only after the Android **merge** gate and uses a **separate** repository-scoped token with Contents: Write and Pull requests: Write, also command-local for `git push`. Write credentials must not be available to repository execution before merge approval.

## Web

```text
cd web
npm install
npm run dev
```

Opens the AutoPatch console (`http://localhost:3000`). Give the Next.js process the same server-only `API_KEY` as the backend (for example `web/.env.local`). The browser does not receive that key. The console calls `GET /health`, sandbox run/audit APIs, `GET /v1/github/connected`, and `GET /v1/ws/ticket`, then connects to `WS /v1/ws/runs` with a short-lived ticket subprotocol. `NEXT_PUBLIC_API_URL` is only the backend origin for the WebSocket host and display.

## Android

1. Copy `android-app/app/google-services.json.example` to `android-app/app/google-services.json` and replace with your Firebase Android app file.
2. Open `android-app/` in Android Studio, sync Gradle, run on a device/emulator with Play services.
3. Register the device against `http://<lan-ip>:8000` (not `localhost` on a physical phone). Set `AUTOPATCH_DEVICE_ENROLLMENT_SECRET` in `android-app/local.properties` to the same value as `DEVICE_ENROLLMENT_SECRET` in `.env`. That enrollment secret is not `API_KEY` and must not be placed in `NEXT_PUBLIC_*`.
4. Use **Send test push** or `POST /v1/devices/{device_id}/test-push` with header `X-API-Key`.

## Suggested Weeks 1–2 order

1. Compose + FastAPI health
2. Alembic schema
3. GitHub webhook HMAC
4. Celery + E2B clone
5. Tree-sitter index
6. Android register + FCM
7. Next.js health page
