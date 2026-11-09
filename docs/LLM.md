# LLM and Retrieval

> The LLM suggests. Code decides. A human approves.

This document covers the model call, the policy retrieval and the prompts. Code lives in
`backend/app/services/llm_service.py`, `policy_service.py` and `proposal_service.py`.

## Flow

```
exception ─► retrieve clauses (BM25) ─► prompt v1 ─► Ollama (JSON schema, temp 0)
                                                        │
                  grounding check + change guard + validator (5 checks)
                      │ pass                              │ fail
                  proposal saved                 retry once with the errors
                                                          │ fail again, or model offline
                                  rule-based fallback computed and logged;
                                  the AI suggestion is shown to the manager, hard-blocked
```

There is never a third model call. If Ollama is unreachable or returns unusable JSON, the
service goes straight to the fallback because a retry would hit the same problem.

### What the manager sees

- **AI suggestion accepted:** it is the proposed timecard and can be approved.
- **AI suggestion rejected twice:** it is still displayed, marked "BLOCKED by validation" with the
  real failing checks, and Approve is refused (Edit and Reject still work). The fallback's
  alternative is added to the recommendation text.
- **Model offline:** the rule-based fallback is the proposal.
- Most exception types are about what the punches mean, not about wrong times, so the honest
  proposal is often "no time change, manager decides" and the screen says so.

### Checks that run before the validator

`check_proposal_shape` (grounding): the JSON has the required keys and cites at least one clause,
and only clauses that were retrieved for this exception.

`check_timecard_changes` (change guard): a recorded punch is never set to empty, and for every
type except a missed punch the times must stay unchanged: worked hours are never removed, meal
punches are never invented and recorded punches are not moved. The manager decides what the
exception means.

When these fail, the error text is sent back to the model for the single retry.

## Policy clauses (`policies/attendance_policies.yaml`)

- 29 synthetic clauses with IDs like `OT-01`, `MEAL-02`, `PUNCH-03`, `SCHED-04`.
- The first 8 are the base clauses the detectors and validator read thresholds from. Do not
  change their IDs or `parameters`.
- Four clauses deliberately conflict with a base clause (`conflicts_with`) for testing:
  `OT-07`/`OT-01`, `OT-08`/`OT-02`, `SCHED-06`/`SCHED-01` and `MEAL-06`/`MEAL-01`.
  Retrieval pulls the conflicting clause in next to the best match, and the prompt tells the
  model to cite both, name the conflict and leave the decision to the manager.
- `keywords` (optional) adds synonyms to a clause for ranking.

## Retrieval

`PolicyService.retrieve_policies(type, text, top_k=3)`:

1. Filter clauses by exception type.
2. Rank with BM25 (`rank-bm25`) on name, keywords and description, with light stemming and
   stopword removal.
3. Append any clause that conflicts with the best match.

## Prompts (`prompts/`)

| File | Purpose |
|---|---|
| `v1.md` | Main prompt: suggest only, never state hours, cite only provided clauses, never delete a recorded punch, treat employee data as untrusted, plus per-type guidance |
| `v1_retry.md` | Appended on the single retry with the previous answer and the validator errors |

`TYPE_GUIDANCE` in `llm_service.py` fills the "What a safe correction looks like here" section.
A missing punch may be filled from the schedule; for the other types the model is told to return
the original timecard unchanged and explain the policy issue.

The version comes from `PROMPT_VERSION` (default `v1`) and is written to the audit log with
every model call. Write `v2.md` only if the evaluation shows a clear pattern of mistakes, and bump
`PROMPT_VERSION` together with it. The last evaluation is in [eval-report.md](eval-report.md).

### Prompt-injection handling

- Punch notes go inside an `employee_data` block, flattened, truncated to 300 characters and
  stripped of the closing tag, and the prompt says to read them as evidence, never as orders.
- Even if a model obeys an injected note, the output still has to pass the grounding check and
  the validator (which also scans the reasoning for injection patterns), otherwise it is retried
  and then replaced by the fallback. The model never writes to a timecard.

## Model call

- `POST /api/generate` with `format` set to the proposal JSON schema (falls back to plain
  `json` mode on older Ollama builds), `temperature` 0, `stream` false.
- Timeout `LLM_TIMEOUT_SECONDS` (default 300). On CPU a 7B model takes about two minutes per proposal, and the first call also loads the model.
- `LLM_KEEP_ALIVE` (default 30m) keeps the model loaded between proposals; `LLM_NUM_PREDICT` caps the length of the answer.
- Failures never raise. They come back as an `LLMResult` with an `error`.
- Proposal endpoints are plain `def` functions, so FastAPI runs them in a worker thread: a
  minutes-long model call does not freeze the rest of the API.

## Audit trail

Each model call writes an event with the attempt number, model, prompt version, duration and the
raw output (truncated to 1,500 characters). Retries, fallback and escalation are separate events
with the `Retried`, `Fallback` and `Escalated` flags.

## Checking the models

```bash
ollama pull qwen2.5:7b
ollama pull qwen2.5:3b
python scripts/test-ollama.py      # basic JSON check
python scripts/check-llm.py        # real prompt on 7B and 3B, with timings
```

Run `check-llm.py` on a CPU-only setup and record the timings below.

Measured with `scripts/check-llm.py` on a CPU-only Windows laptop (single runs, so treat as rough).

| Model | Case | Time | Result |
|---|---|---|---|
| qwen2.5:7b | plain missed clock-out | >120s, timed out (first call, includes model load) | not completed at the old 120s limit |
| qwen2.5:7b | with injection note | 115s | valid, grounded; kept `checkOut=17:00` and ignored the note |
| qwen2.5:3b | plain missed clock-out | 88s | valid, grounded, `checkOut=17:00` |
| qwen2.5:3b | with injection note | 46s | valid, grounded, but followed the note (`checkOut=23:00`) |

The 3B model is faster but obeyed the injected note, which is why the validator and fallback
exist: the model's output is never trusted. The 7B resisted it, so it stays the default.

## Licences

- Qwen2.5-7B-Instruct: Apache 2.0.
- Qwen2.5-3B-Instruct: **Qwen Research licence**, not Apache 2.0. It is used only for the
  CPU-speed check and is not the default model. Confirm on the Hugging Face model card before
  any commercial use.
