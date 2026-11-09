# Timecard Exception Agent — Project Spec

**Goal:** find timecard exceptions, propose a policy-grounded fix with a local LLM, validate it with code, and change a timecard only after a manager approves. Every step is logged.

**Principle:** the LLM suggests, code decides, a human approves.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS, shadcn/ui |
| Frontend testing | Vitest (components), Playwright (end-to-end) |
| API client / mock | openapi-typescript (generated client), Prism (mock API) |
| Backend | Python 3.11+, FastAPI, Pydantic, SQLAlchemy |
| Database | SQLite (local) |
| Rules and validation | Plain Python; hypothesis for property tests |
| LLM | Ollama running Qwen2.5-7B (main) and Qwen2.5-3B (CPU check), strict JSON, temperature 0 |
| Retrieval | YAML policy clauses, filtered by exception type, ranked with BM25 (rank-bm25) |
| API testing | schemathesis (contract tests) |
| Code quality | ruff, mypy, pytest |
| CI / packaging | GitHub Actions, Docker Compose |

## Exception types

Missed punch · Overtime · Schedule conflict · Meal break

Extensions added after the plan (see [RULES_SPEC.md](RULES_SPEC.md) section 3E): Duplicate punch · Rest period violation · Consecutive days

## How it works

```
Exception → retrieve policy clauses → LLM (JSON) → validator ─ pass → manager review → timecard write
                                         ▲            │ fail
                                         └─ retry once┤ fail again
                                              rule-based fallback → still fails → escalate to manager
```

Validator checks: valid format · cited clauses exist · hours recalculated by code · no new exception created · values within limits.

## Data and API

- **Tables:** employees, schedules, punches, exceptions, proposals, decisions, audit_log
- **Endpoints:** `GET /exceptions`, `GET /exceptions/{id}`, `POST /exceptions/{id}/proposal`, `POST /proposals/{id}/decision`, `GET /exceptions/{id}/audit`
- **Shared shapes** (Pydantic): Exception, Proposal, Decision. Only the owner changes them.

## Repo layout and owners

| Folder | Contents | Owner |
|---|---|---|
| `frontend/` | Manager UI: queue, review, audit | Person 1 |
| `backend/` | API, database, audit log | Person 2 |
| `backend/app/` (rules) | Detectors, hours calculator, validator, fallback | Person 3 |
| `policies/`, `prompts/` | Policy clauses (YAML), versioned prompts | Person 4 |
| `eval/`, `data/`, `docs/` | Test data, scoring, CI, README, slides, video | Person 5 |

## 48-hour plan

| Phase | Hours | Goal |
|---|---|---|
| 0 | H0–3 | Setup: repo, CI, contracts, Ollama running |
| 1 | H3–12 | Test data, detectors, database, queue page |
| 2 | H12–24 | Vertical slice: LLM call, validator, review screen |
| 3 | H24–34 | Audit log, retry, fallback |
| 4 | H34–42 | Polish, tests, Docker install, frozen numbers |
| 5 | H42–48 | README, slides, 10-minute demo |

Key handoffs: OpenAPI file H3 · test data H6 · detectors H8 · real API H10 · proposal format H12 · LLM call H18 · validator H20 · fallback H26 · final numbers H38.

## Deliverables

Working app (`docker-compose up`), README with demo video, `docs/eval-report.md` (LLM alone vs LLM + safety checks), 5 slides.

Full detail: the PDF plan in the repo root.
