# Timecard Exception Agent

An agent that finds timecard exceptions, proposes a **policy-grounded** fix with a local LLM, **validates** it with deterministic code, and changes a timecard **only after a manager approves**. Every step is logged for audit.

> **The LLM suggests. Code decides. A human approves.**

Plan: the PDF in this folder · Spec: [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) · Rules: [docs/RULES_SPEC.md](docs/RULES_SPEC.md) · LLM: [docs/LLM.md](docs/LLM.md) · Evaluation: [docs/eval-report.md](docs/eval-report.md)

## Exception types

The four from the project plan: **missed punch**, **overtime**, **schedule conflict**, **meal break**.
Three extensions (defined in [docs/RULES_SPEC.md](docs/RULES_SPEC.md) section 3E): **duplicate punch**, **rest period violation**, **consecutive days**.

## How it works

```
Exception → retrieve policy clauses → LLM (strict JSON) → grounding check + validator ─ pass → manager review → timecard write
                                          ▲                          │ fail
                                          └── retry once, with the errors ◄──┤ fail again
                                                    AI suggestion shown but hard-blocked  +  rule-based fallback recorded
```

- **Detect** (plain code): four core detectors plus duplicate, rest-period and consecutive-day checks.
- **Retrieve**: clauses are filtered by exception type and ranked with BM25; the clause the detector assigned always comes first.
- **Propose**: Qwen2.5 via Ollama, JSON schema enforced, temperature 0. The prompt is versioned in `prompts/`.
- **Validate**: only retrieved clauses may be cited; recorded punches are never deleted; hours are recalculated by code; no new exception may be created; values must be within limits.
- **Approve**: nothing touches a timecard until a manager approves. A blocked proposal cannot be approved.
- **Audit**: every step is logged with the model, prompt version, raw model output, retries, fallback, decision and a trace ID.
- **Attendance**: the Attendance Records page and the dashboard read real punches and schedules (`/api/v1/attendance`, `/api/v1/attendance/summary`). Status is worked out in code: no punches on a scheduled day is *Absent*, a first clock-in more than 5 minutes after the schedule start is *Late*, otherwise *Present*. There is no "on leave" status because the data has no leave records.

## Quick start

**Everything with Docker** (UI, API and Ollama; the first start downloads about 6.5 GB of models):

```bash
docker compose up --build
```

UI <http://localhost:5173> · API docs <http://localhost:8000/docs>. The API starts with a demo dataset loaded.
To reuse the Ollama already running on your machine (no second 6.5 GB download), add the override file: `docker compose -f docker-compose.yml -f docker-compose.host-ollama.yml up --build`. Stop any local backend on port 8000 first, because the UI container calls the API there.
*The Docker setup has not yet been verified on a clean machine.*

**Locally on Windows (PowerShell), step by step from a fresh machine:**

Prerequisites: Python 3.11+, Node.js 20+ and Git. About 10 GB of free disk is needed (models 6.5 GB, `node_modules` 0.5 GB). Keep the project outside OneDrive (for example `C:\dev\dayforce`), because OneDrive locks files during `npm install`.

*1. Install Ollama and download the models*

```powershell
winget install Ollama.Ollama            # or download the installer from https://ollama.com/download
# Close and reopen PowerShell so `ollama` is on PATH, then:
ollama --version
ollama pull qwen2.5:7b                  # main model, about 4.7 GB
ollama pull qwen2.5:3b                  # faster model, about 1.9 GB
ollama list                             # both should be listed
```

Ollama runs in the background after installing and listens on <http://localhost:11434>. If it is not running, start it with `ollama serve` in its own terminal.

*2. Get the code and set up the backend*

```powershell
git clone <repo-url> dayforce ; cd dayforce
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -e "backend[dev]"
python scripts\check-llm.py             # optional: confirms the backend can reach the models
```

*3. Load the demo data and start the API*

```powershell
python scripts\load_dataset.py --file data\demo_attendance.json    # 92 exceptions, all 7 types
python -m uvicorn app.main:app --app-dir backend --port 8000       # leave running
```

Check it at <http://localhost:8000/docs>.

*4. Start the UI (second terminal)*

```powershell
cd frontend
Set-Content .env.local "VITE_USE_MOCK_API=false"
npm ci --legacy-peer-deps
npm run dev
```

Open <http://localhost:5173>.

`VITE_USE_MOCK_API=false` makes the UI use the real API instead of its built-in fake data. With it set to `true` (the default), every page shows sample data. To reload the demo data, stop the API first, delete `timecard_demo.db`, then run the load command again; this also clears saved proposals and decisions. Copy `.env.example` to `.env` to change the model or timeouts. A 7B model on CPU takes 1 to 3 minutes per proposal; set `LLM_MODEL=qwen2.5:3b` for faster demos.

## Repository layout

| Folder | Contents |
|---|---|
| `frontend/` | React + TypeScript + Vite manager UI (dashboard, queue, review, attendance, audit, escalated) |
| `backend/app/api`, `services`, `models`, `schemas` | FastAPI endpoints, services, database, audit log |
| `backend/app/rules/` | Detectors, hours calculator, validator, fallback |
| `backend/app/services/llm_service.py` | Prompt loading, Ollama call, grounding and change checks |
| `policies/`, `prompts/` | Policy clauses (YAML) and versioned prompts |
| `data/`, `eval/`, `scripts/` | Generated dataset, evaluation scripts, tooling |
| `docs/` | Spec, rules, LLM notes, evaluation report |

## Common commands

| Task | Command |
|---|---|
| Backend tests | `pytest backend` |
| Dataset tests | `pytest tests` |
| Lint / types | `ruff check backend` · `mypy --config-file backend/pyproject.toml backend/app` |
| Frontend checks | `cd frontend` then `npm run lint` · `npx tsc --noEmit` · `npm test` |
| Regenerate dataset | `python scripts/generate_dataset.py` (cases fall on weekdays; only consecutive-day streaks and Friday-night overnight shifts touch a weekend) |
| Demo dataset | `python scripts/build_demo_dataset.py` then `python scripts/load_dataset.py --file data/demo_attendance.json` |
| Score the detectors | `python eval/run_detectors.py --data data --out p.json` then `python eval/evaluate.py --truth data/ground_truth.csv --predictions p.json` |
| Evaluate the LLM | `python eval/run_llm_eval.py --limit 14` then `python eval/make_report.py` |
| Check the models | `python scripts/check-llm.py` |

## Model and licence

Local inference with **Qwen2.5-7B-Instruct** (Apache 2.0) via Ollama. **Qwen2.5-3B-Instruct** is used for faster runs and the CPU-speed check; it is released under the Qwen Research licence, so confirm its terms on the model card before any commercial use. No data leaves the machine, and all employee data and policies are synthetic. Details: [docs/LLM.md](docs/LLM.md).

## Team

| # | Role |
|---|---|
| 1 | Frontend |
| 2 | Backend |
| 3 | Rules & validation |
| 4 | LLM & retrieval |
| 5 | Evaluation & delivery |

## Status

- [x] Phase 0 — setup, contracts, models running
- [x] Phase 1 — data, detectors, database, queue
- [x] Phase 2 — LLM call, validator, review screen
- [x] Phase 3 — audit log, retry, fallback
- [x] Phase 4 — tests and CI (backend, dataset and frontend unit tests; lint and types clean). Not yet done: Playwright end-to-end test, clean-machine Docker install test
- [ ] Phase 5 — slides and the 10-minute demo video (*TBD*)
