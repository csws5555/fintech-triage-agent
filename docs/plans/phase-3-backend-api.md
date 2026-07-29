# Phase 3 Backend API Execution Plan

## Objective

Implement Phase 3 Step 4 by creating the FastAPI application factory,
initializing shared process services once during lifespan startup, exposing
typed dependencies, and releasing only API-owned resources at shutdown.

## Roadmap source

`personal project documentation/phase 3 steps.md`

- Step 4 — Implement lifespan initialization and typed dependencies

## Scope

### Included

- Add `create_app(...) -> FastAPI` and module-level `app`.
- Add an injectable `ServiceBuilder` startup seam.
- Validate RAG/API settings and eagerly warm the protected classifier cache.
- Inspect the active manifest/store and initialize optional local clients with
  bounded waits, degrading safely when they are unavailable.
- Construct one pipeline, chat service, and `AppServices` container.
- Add typed application-state dependencies and lifecycle-focused fake tests.

### Excluded

- Step 5 health routes or dynamic readiness recovery.
- Middleware, CORS installation, request IDs, logging, error handlers, chat
  routes, SSE, OpenAPI completion, runner scripts, or frontend work.
- Live inference, generation, embedding, Chroma mutation, or store rebuilds.

## Files to inspect

- `backend/app/api/config.py`
- `backend/app/api/models.py`
- `backend/app/api/services.py`
- `backend/app/ml/classifier.py`
- `backend/app/ml/rag_config.py`
- `backend/app/ml/ingest_policies.py`
- `backend/app/ml/retriever.py`
- `backend/app/ml/embeddings.py`
- `backend/app/ml/chat_model.py`
- `backend/app/ml/rag_pipeline.py`
- Existing callers/imports and Phase 2 streaming tests

## Files expected to change

- Create `backend/app/api/dependencies.py`
- Create `backend/app/main.py`
- Create `backend/tests/test_api_app.py`
- Modify `backend/app/api/__init__.py`
- Modify `docs/IMPLEMENTATION_STATUS.md`
- Modify this plan

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — verify only.
- `backend/.env` — do not expose or modify.
- Active/temporary/backup Chroma stores — read-only startup inspection only;
  no rebuild or mutation.
- Local Ollama data — no start, pull, generation, or embedding.

## Compatibility constraints

- Preserve all Phase 1/2 public interfaces, caches, safety checks, and
  deterministic fallback behavior.
- Retain the complete `ClassificationResult` and one shared pipeline.
- Optional local-service failures must degrade readiness; invalid settings,
  classifier warming failure, or pipeline construction failure must abort
  startup.
- Startup diagnostics must use stable safe codes, never raw exception details.
- Shutdown closes the API executor and removes state references without
  clearing ML caches or calling private Chroma cleanup.

## Implementation milestones

1. [x] Inspect roadmap, current interfaces, callers/imports, and repository
   state.
2. [x] Implement application factory, startup builder, lifespan, and typed
   dependencies.
3. [x] Add focused fake-based lifecycle and dependency tests.
4. [x] Run focused/full verification and fix regressions.
5. [x] Update status, plan results, diff, and repository status; stop before
   Step 5.

## Acceptance criteria

- [x] `create_app(...)` creates an app without loading heavyweight services
  until lifespan startup.
- [x] Startup validates settings, warms the classifier once, and stores exactly
  one internally consistent `AppServices` container.
- [x] Optional failures produce stable degraded readiness without preventing
  deterministic pipeline availability.
- [x] Mandatory failures abort startup and leave no services state behind.
- [x] Typed dependencies return the exact shared instances.
- [x] Repeated dependency use does not rebuild services.
- [x] Shutdown rejects new work, closes the executor, and removes app state.
- [x] Fake injection makes focused tests independent of live local services.

## Testing plan

- Focused: `python -m pytest -q tests/test_api_app.py tests/test_api_services.py`
- Compilation: `python -m compileall app scripts tests`
- Non-integration: `python -m pytest -q -m "not integration"`
- Validation: `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, `python -m pip check`
- Integration: NOT RUN unless a failure requires live diagnosis; Step 4 is
  designed for fake-based verification.

## Live-service requirements

- Ollama: not required.
- Chroma: not required and not mutated.
- Protected classifier: fake in focused tests; checksum verification only.
- Running FastAPI application: not required; lifespan is exercised in-process.

## Rollback considerations

- New API modules/tests and documentation can be reverted independently.
- No persistent model, policy, manifest, or vector-store state is changed.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Use a frozen callable-based `ServiceBuilder` so ordinary lifecycle tests
  replace every heavyweight dependency without monkeypatching global caches.
- Bound each optional local-service constructor with the API health timeout.
- Wrap mandatory configuration, classifier, pipeline, and API-service failures
  in `ApplicationStartupError` with stable text and suppressed private causes.
- Validate manifest/configured store facts separately from Ollama-dependent
  retriever initialization so readiness can identify degraded components
  without creating an embedding during manifest inspection.
- Inject successful retriever/chat clients into the one pipeline; pass `None`
  after optional failure because the inspected current constructor explicitly
  supports it and Phase 2 then fails closed on eligible routes.

## Unresolved risks

- None currently. Thread-backed optional initialization cannot forcibly stop a
  native client constructor after timeout; timed-out results are discarded and
  never attached to application state.

## Final results

- Files created: `backend/app/api/dependencies.py`, `backend/app/main.py`, and
  `backend/tests/test_api_app.py`.
- Files modified: `backend/app/api/__init__.py`,
  `docs/IMPLEMENTATION_STATUS.md`, and this plan.
- `python -m compileall app\api app\main.py tests\test_api_app.py` passed.
- `python -m pytest -q tests/test_api_app.py tests/test_api_services.py`
  passed in the final rerun: 17 tests in 33.79s.
- Related API/async tests passed: 130 tests.
- Full compilation passed; the final non-integration suite passed in 24.44s:
  665 tests with 3 integration tests deselected.
- Protected baseline verification passed for 5 artifacts, policy validation
  passed for 4 files, and `pip check` found no broken requirements.
- Live Ollama, Chroma, classifier inference, running API, CORS, routes, and
  integration tests were not run because Step 4 is fully fake-testable and
  does not authorize live-service mutation.
- Remaining work: Phase 3 Step 5 — health and readiness endpoints.
