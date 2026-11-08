# Timecard Exception Resolution Agent — Backend API

Backend implementation for the **Dayforce AI Innovation Challenge**.

> **Core Principle:** *"The LLM suggests. Code decides. A human approves."*

The backend autonomously identifies employee timecard exceptions, generates policy-grounded correction proposals, verifies them deterministically using code-level validation checks, and allows managers to approve, edit, reject, or escalate proposals. **Only an explicit manager approval or edit can alter employee timecard punch records.**

---

## 1. Architecture & Workflow

```
Timecard Exception (Missed punch, Overtime, Schedule conflict, Meal break)
      │
      ▼
1. Policy Retrieval (BM25 ranking over YAML clauses in policies/)
      │
      ▼
2. Proposal Generation (Ollama Qwen2.5 strict JSON or deterministic fallback)
      │
      ▼
3. Deterministic Safety Validator (5 Python checks: format, policy, net hours math, no new violations, injection defense)
      │
      ├── Passed ──► Status: "Awaiting Approval"
      │
      └── Failed ──► Retry once ──► If still fails: Fallback Engine ──► Blocked / Escalate
                              │
                              ▼
4. Manager Decision Review (UI via React dashboard)
      ├── Approve ──► Update employee punch records in database + Log audit event
      ├── Edit    ──► Deterministically re-validate edited times + Update punches + Log audit event
      ├── Reject  ──► Log reason + Timecard UNCHANGED + Log audit event
      └── Escalate──► Flag to HR Operations + Log audit event
```

---

## 2. Technology Stack

- **Python:** 3.11+
- **Web Framework:** FastAPI (with Pydantic v2 CamelModel serialization)
- **Database:** SQLite with SQLAlchemy 2.0 (seven relational tables)
- **Policy Retrieval:** BM25 (`rank-bm25`) indexing YAML policy files
- **LLM Engine:** Local Ollama (`qwen2.5:7b` / `qwen2.5:3b`, temperature 0.0, format `json`)
- **Testing & Verification:** Pytest, Schemathesis (contract testing), Ruff, Mypy (strict mode)
- **Containerization:** Docker Compose with health checks and persistent volume

---

## 3. Database Schema

The backend persists state across seven SQLAlchemy 2.0 relational models:

| Table | Model Class | Description |
|---|---|---|
| `employees` | `EmployeeModel` | Master employee records (shift assignments, departments) |
| `schedules` | `ScheduleModel` | Scheduled shift boundaries, dates, and break allocations |
| `punches` | `PunchModel` | Physical clock-in/out and meal break timestamps |
| `exceptions` | `ExceptionModel` | Detected anomalies with review lifecycle statuses |
| `proposals` | `ProposalModel` | AI-generated or fallback timecard proposals with validator reports |
| `decisions` | `DecisionModel` | Manager audit records (approve, edit, reject) |
| `audit_log` | `AuditEventModel` | Append-only chronological trace of all system and human events |

---

## 4. API Endpoints

All responses serialize in `camelCase` for frontend compatibility. Base URL: `http://localhost:8000/api/v1`

| Method | Path | Summary | Description |
|---|---|---|---|
| `GET` | `/health` | Health Check | System health and readiness verification |
| `GET` | `/api/v1/exceptions` | List Exceptions | Filter exceptions by search, type, status, and severity |
| `GET` | `/api/v1/exceptions/{id}` | Get Exception Detail | Detailed exception including employee and active proposal |
| `POST` | `/api/v1/exceptions/{id}/proposal` | Generate Proposal | Trigger BM25 retrieval, LLM proposal, 5-check validation |
| `POST` | `/api/v1/exceptions/{id}/escalate` | Escalate Exception | Escalate exception directly to manager/HR operations |
| `POST` | `/api/v1/proposals/{id}/decision` | Submit Decision | Manager action (`approve`, `edit`, `reject`) |
| `GET` | `/api/v1/exceptions/{id}/audit` | Exception Audit Trail | Chronological audit trail for specific exception |
| `GET` | `/api/v1/audit` | Global Audit Stream | Reverse-chronological audit log across all exceptions |

---

## 5. Local Setup & Quickstart

### Prerequisites
- Python 3.11 installed
- Git
- (Optional) Docker Compose & Ollama

### Step 1: Virtual Environment Setup
```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Install backend package and dev dependencies
pip install -e "backend[dev]"
```

### Step 2: Ingest Attendance Dataset
```powershell
python scripts/load_dataset.py --file data/sample_attendance.json
```

### Step 3: Start the Backend Server
```powershell
python -m uvicorn app.main:app --reload --app-dir backend --port 8000
```

Interactive documentation:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **OpenAPI Schema:** `http://localhost:8000/openapi.json`

---

## 6. Testing & Quality Verification

Run the full automated test suite (all 46 tests passing):
```powershell
# Run unit, contract, and integration tests
.\.venv\Scripts\python.exe -m pytest backend -v

# Run linting with Ruff
.\.venv\Scripts\python.exe -m ruff check backend

# Run strict type checking with Mypy
.\.venv\Scripts\python.exe -m mypy backend/app

# Verify git whitespace
git diff --check
```

---

## 7. Docker Deployment

To launch the full stack with Ollama and persistent database volume:

```powershell
docker compose up --build
```

Services started:
- `backend`: FastAPI server on port `8000` (with automated health check)
- `ollama`: Ollama server on port `11434`
- Volume `backend_data`: Persistent SQLite database storage

---

## 8. Integration Boundaries & Teammate Handoffs

- **Person 1 (Frontend):** Contract fully verified against `frontend/src/lib/api/types.ts`. All endpoints emit expected camelCase schemas (`AttendanceException`, `Proposal`, `DecisionResponse`, `AuditEvent`).
- **Person 3 (Rules & Validation Engine):** `detector_service.py` and `rules_adapter.py` contain dynamic import hooks for `app.rules`. When branch `origin/feature/rules-validation` is merged, detector functions, hours calculators, and proposal validators resolve automatically with zero code modifications.
- **Person 4 (LLM & Prompts):** `proposal_service.py` supports Ollama (`qwen2.5:7b`) with temperature 0.0, strict JSON schema output, and automated retry and deterministic fallback. Prompt templates are located in `prompts/`.
- **Person 5 (Attendance Dataset):** `dataset_service.py` and `scripts/load_dataset.py` support the agreed schema format (`employees`, `schedules`, `punches`, `exceptions`) with dependency-ordered loading and duplicate prevention.
