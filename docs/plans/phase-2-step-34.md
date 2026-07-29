# Phase 2 Step 34 Execution Plan

## Objective

Provide a fail-closed, service-free logging safety boundary that redacts the
secret patterns named by the roadmap and permits only the approved aggregate
metadata fields in structured log records.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 34 — Add safe logging and redaction
- Phase 2 output for Phase 3 — Phase 3 owns request IDs and log emission
- When Chroma must be rebuilt — logging-rule changes do not require a rebuild

## Scope

### Included

- Redact payment-card-like digit sequences, contextual OTP/PIN/CVV values,
  password fields, bearer tokens, and API-key-like strings.
- Provide stable `[REDACTED]` replacement and idempotent behavior.
- Provide an allowlisted structured-log sanitizer containing exactly the
  roadmap-approved field names.
- Provide deterministic rounded confidence ranges so raw classifier
  confidence values need not be logged.
- Add focused service-free tests for every secret family, false-positive
  boundaries, multiple secrets, fail-closed inputs, and log-field allowlisting.

### Excluded

- FastAPI request logging, request-ID creation, or log-handler configuration.
- Logging raw customer messages, conversations, policies, prompts, model
  output, reasoning, authentication headers, or environment values.
- Changes to pipeline/classifier/router public contracts.
- Persistent telemetry, Chroma changes, Ollama calls, classifier inference, or
  Step 35 work.

## Files to inspect

- `backend/app/ml/triage_types.py` — existing typed classifier, routing,
  retrieval, validation, and response contracts.
- `backend/app/ml/classifier.py` — authoritative confidence semantics.
- `backend/app/ml/rag_pipeline.py` — current public orchestration interface and
  Phase 3 handoff boundary.
- `backend/app/ml/output_validator.py` — existing secret terminology and
  validation failure-code conventions.
- `backend/tests/` — test style and service-free test organization.

## Files expected to change

- `backend/app/ml/redaction.py` — new Step 34 redaction and safe-log helpers.
- `backend/tests/test_redaction.py` — new focused service-free tests.
- `docs/IMPLEMENTATION_STATUS.md` — Step 34 status and continuation handoff.
- This plan — progress, decisions, exact checks, and final results.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — baseline verification only.
- `backend/app/data/chromadb_store/` — no access or mutation required.
- `backend/.env` and local Ollama data — do not read, print, or modify.

## Compatibility constraints

- Preserve all existing public interfaces.
- Use only standard-library code; do not add dependencies or configuration.
- Keep the redactor deterministic, idempotent, and conservative in favor of
  protecting possible secrets.
- Reject unapproved structured-log keys instead of silently accepting raw or
  future fields.
- Do not stringify arbitrary objects because their representations may expose
  private runtime data.

## Implementation milestones

1. [x] Read required documentation and inspect implementation, callers,
   imports, tests, configuration, repository state, and service dependencies.
2. [x] Implement redaction, confidence bucketing, and allowlisted log-record
   sanitization.
3. [x] Add and pass focused service-free tests.
4. [x] Run practical repository validation, update continuity, and stop before
   Step 35.

## Acceptance criteria

- [x] Every roadmap secret family is replaced with `[REDACTED]`.
- [x] Contextual short codes are not redacted when authentication context is
  absent.
- [x] Reapplying redaction does not alter already-redacted output.
- [x] Only approved structured-log fields can pass the sanitizer.
- [x] Raw classifier scores can be converted into rounded ranges.
- [x] Unit tests require no Ollama, Chroma, environment mutation, or protected
  classifier load.

## Testing plan

- Unit: `python -m pytest -q tests/test_redaction.py`
- Related: `python -m pytest -q tests/test_classifier.py
  tests/test_rag_pipeline.py tests/test_output_validator.py
  tests/test_redaction.py`
- Non-integration: `python -m pytest -q -m "not integration"`
- Validation: `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Ollama: not required.
- Chroma: not required; no store read, write, rebuild, or swap.
- Protected classifier: not required except the standard checksum-only
  baseline verifier.

## Rollback considerations

- Step 34 creates source/tests/plan files and updates continuity documentation
  only; it makes no persistent runtime changes.
- Rollback does not require a Chroma rebuild or service operation.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Keep actual request-log emission in Phase 3, as the roadmap assigns request
  IDs and safe logging to that phase and the current repository has no API
  logging surface.
- Add an exact structured-field allowlist so callers cannot accidentally add
  raw messages, prompts, policies, headers, or model output.
- Represent confidence as deterministic tenth-wide ranges rather than exact
  scores.

## Unresolved risks

- Regex redaction is intentionally conservative: payment-card-length numeric
  identifiers may be over-redacted, while novel unlabeled secret formats still
  require the default-deny structured field allowlist and caller discipline.

## Final results

- Created `backend/app/ml/redaction.py`,
  `backend/tests/test_redaction.py`, and this plan.
- Modified `docs/IMPLEMENTATION_STATUS.md`.
- `python -m pytest -q tests/test_redaction.py`: initial run exposed two edge
  cases (`2 failed, 52 passed`); after fixes, final run passed
  `54 passed in 0.12s`.
- `python -m compileall app scripts tests`: passed with exit code 0.
- Related classifier/pipeline/validator/redaction tests:
  `215 passed in 15.45s`.
- Full service-free suite:
  `537 passed, 3 deselected in 17.71s`.
- Protected baseline verification passed 5 artifacts; policy validation passed
  4 policies; `pip check` reported no broken requirements.
- `git diff --check` passed; final diff and status were inspected. Existing
  unrelated Phase 2 changes remain preserved.
- Live Ollama/Chroma and integration checks were not run because Step 34 uses
  only standard-library code and changes no model, service, store, policy,
  pipeline, or runtime configuration.
- Remaining work: Step 35. It was not started.
