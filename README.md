# AutoPatch Engine

AutoPatch Engine is an automated code-diagnosis and remediation platform that connects GitHub repositories with isolated E2B sandboxes to reproduce and analyze software failures.

## Current Progress

### Phase 1 — GitHub Integration

* GitHub App integration
* GitHub installation handling
* Repository synchronization
* Installation access-token generation
* GitHub webhook signature verification
* Push-event handling
* Repository and branch information

### Phase 2 — Sandbox & Repository Analysis

* E2B sandbox provisioning
* Secure repository cloning
* Source-file collection
* Python, JavaScript, JSX, TypeScript, and TSX source indexing
* Function, class, and method detection
* Repository symbol persistence
* Sandbox lifecycle management
* Approval gate before sandbox provisioning

### Phase 3 — Failure Diagnosis

* Stack-trace parsing
* Exception type extraction
* Exception message extraction
* Stack-frame extraction
* Stack-frame to indexed-symbol matching
* Diagnostic location identification
* Diagnostic confidence tracking

### Phase 4 — Failure Reproduction

* Automatic Python reproduction-test synthesis
* Reproduction test generation from diagnostic locations
* Isolated E2B reproduction execution
* Pytest-based failure verification
* Reproduction result capture
* Exit-code and stderr/stdout capture
* Reproduction attempt persistence
* End-to-end worker integration

## Phase 3–4 Pipeline

```text
GitHub Failure / Stack Trace
            ↓
     Parse Stack Trace
            ↓
     Locate Diagnostic
            ↓
   Generate Reproduction Test
            ↓
      Run Test in E2B
            ↓
      Capture Test Result
            ↓
   Confirm Failure Reproduced
            ↓
    Store Reproduction Attempt
```

## Example

For a failure such as:

```text
Traceback (most recent call last):
  File "backend/tests/fixtures/autopatch_phase34.py", line 2, in reproduce_failure
    return 1 / 0
ZeroDivisionError: division by zero
```

AutoPatch Engine:

1. Parses the exception and stack frame.
2. Locates `reproduce_failure` in the indexed repository symbols.
3. Generates a reproduction test.
4. Executes the test inside an isolated E2B sandbox.
5. Detects the expected `ZeroDivisionError`.
6. Stores the reproduction attempt and execution result.

Validated result:

```text
STATUS: completed
SYMBOLS: 61
ATTEMPTS: 1
EXIT CODE: 1
REPRODUCED: True
```

## Architecture

```text
                    GitHub
                       │
                       ▼
                FastAPI Backend
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
     GitHub App     Sandbox API   Database
                       │
                       ▼
                 Celery Worker
                       │
                       ▼
                  E2B Sandbox
                       │
          ┌────────────┴────────────┐
          │                         │
          ▼                         ▼
   Repository Source          Reproduction Test
          │                         │
          ▼                         ▼
     Tree-sitter                Pytest
          │                         │
          └────────────┬────────────┘
                       ▼
              Diagnostic Result
                       │
                       ▼
             Reproduction Attempt
```

## Backend Technology

* **FastAPI** — API backend
* **PostgreSQL** — application and analysis data
* **SQLAlchemy** — database ORM
* **Alembic** — database migrations
* **Celery** — background worker execution
* **Redis** — Celery broker/backend
* **E2B** — isolated code execution sandboxes
* **Tree-sitter** — source-code symbol indexing
* **Pytest** — reproduction-test execution

## Phase 3–4 Data Flow

The worker follows this flow:

```text
Sandbox Run
    ↓
Clone Repository
    ↓
Index Repository Symbols
    ↓
Read Stack Trace
    ↓
Locate Diagnostic Frame
    ↓
Generate ReproductionTest
    ↓
Execute Reproduction Test in E2B
    ↓
Create ReproductionAttempt
    ↓
Persist Result
    ↓
Complete Sandbox Run
```

## Validation

The current Phase 1–4 implementation has been validated with:

```text
27 passed
```

The Phase 3–4 end-to-end smoke test also successfully demonstrated:

```text
Diagnostic Location:
backend/tests/fixtures/autopatch_phase34.py
reproduce_failure

Reproduction:
True

Exit Code:
1
```

This confirms that the system can successfully move from a stack trace to a diagnostic location, generate a reproduction test, execute it inside E2B, and confirm that the reported failure is reproducible.

## Development

Create and activate the backend virtual environment:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Configure the required environment variables in `.env`.

Run the backend tests:

```powershell
python -m pytest -q
```

## Current Scope

Phases 1–4 establish the GitHub integration, sandbox execution, repository indexing, failure diagnosis, and failure reproduction pipeline.

Automatic patch generation, patch application, patch validation, and pull-request creation are **not yet part of the completed Phase 1–4 implementation**.