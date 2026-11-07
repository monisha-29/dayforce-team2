# Timecard Exception Agent

An agent that finds timecard exceptions (missed punch, overtime, schedule conflict, meal break), proposes a **policy-grounded** fix with a local LLM, **validates** it with deterministic code, and changes a timecard **only after a manager approves**. Every step is logged for audit.

> **The LLM suggests. Code decides. A human approves.**

Full details: [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) · Plan: the PDF in this folder.

## How it works

```
Exception → retrieve policy clauses → LLM (strict JSON) → validator ─ pass → manager review → timecard write
                                          ▲                  │ fail
                                          └── retry once ◄───┤ fail again
                                                       rule-based fallback → (still fails) escalate
```

## Repository layout

| Folder | Contents | Owner |
|---|---|---|
| `frontend/` | React + TypeScript + Vite manager UI | Person 1 |
| `backend/` | FastAPI API, DB, audit log | Person 2 |
| `backend/app/rules/` *(to add)* | Detectors, hours calculator, validator, fallback | Person 3 |
| `policies/`, `prompts/` | YAML policy clauses, versioned prompts | Person 4 |
| `eval/`, `data/` | Synthetic data, labels, scoring scripts | Person 5 |
| `docs/` | Spec, rules, evaluation report | All |
| `scripts/` | Setup and environment checks | Person 5 |

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Git | any | source control |
| Python | 3.11+ | backend, rules, eval |
| Node.js | 20+ | frontend |
| Ollama | latest | local LLM |
| Docker Desktop | optional | `docker-compose up` |

## Setup (Phase 0)

### Windows (PowerShell)

```powershell
.\scripts\setup.ps1          # creates .venv, installs backend deps, copies .env
.\scripts\check-env.ps1      # verifies tools, API, and Ollama
```

### macOS / Linux

```bash
./scripts/setup.sh
./scripts/check-env.sh
```

### Manual steps

**1. Backend**
```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e "backend[dev]"
cp .env.example .env            # Windows: copy .env.example .env
```
Person 2 adds the FastAPI app (`backend/app/main.py`); after that:
```bash
uvicorn app.main:app --reload --app-dir backend    # http://localhost:8000/docs
```

**2. LLM (Ollama)**
```bash
ollama pull qwen2.5:7b
ollama pull qwen2.5:3b
python scripts/test-ollama.py    # must print valid JSON
```

**3. Frontend** (Person 1 — see [frontend/README.md](frontend/README.md))
```bash
npm create vite@latest frontend -- --template react-ts
```
then Tailwind, shadcn/ui, OpenAPI client generation and the Prism mock as described there.

**4. Everything with Docker** (final form, Phase 4)
```bash
docker-compose up
```

## Common commands

| Task | Command |
|---|---|
| Run API | `uvicorn app.main:app --reload --app-dir backend` |
| Backend tests | `pytest backend` |
| Lint / format | `ruff check backend` · `ruff format backend` |
| Type check | `mypy backend/app` |
| Mock API | `npx prism mock backend/openapi.json -p 4010` |

## Model & licence

Local inference with **Qwen2.5-7B-Instruct** (and 3B for CPU checks) via Ollama. The Qwen2.5 7B/3B models are released under the Apache 2.0 licence *(verify on the model card before release — 3B is under the Qwen Research licence on some builds; Person 4 to confirm)*. No data leaves the machine. All employee data and policies are synthetic.

## Team

| # | Role |
|---|---|
| 1 | Frontend |
| 2 | Backend |
| 3 | Rules & validation |
| 4 | LLM & retrieval |
| 5 | Evaluation & delivery |

## Status

- [x] Phase 0 scaffolding (environment only; no application code yet)
- [ ] Phase 1 — Data & detection
- [ ] Phase 2 — Vertical slice
- [ ] Phase 3 — Audit & fallback
- [ ] Phase 4 — Polish & test
- [ ] Phase 5 — Deliver (demo video: *TBD*)

Evaluation results: `docs/eval-report.md` *(to be written)*.
