# Phase 3 Backend API Execution Plan

## Objective

Implement Phase 3 Step 11 by proving the assembled HTTP trust boundary rejects
invalid or privileged client input, preserves deterministic Phase 2 safety
behavior, enforces restrictive CORS and bounded shared execution, and leaks no
private runtime data. Preserve all Phase 1/2 interfaces and Phase 3 Steps 1–10
behavior.

## Roadmap source

`personal project documentation/phase 3 steps.md`

- Step 11 — Complete validation, security, CORS, concurrency, and leakage
  tests

## Scope

### Included

- Exercise chat request validation through the assembled HTTP routes, including
  malformed input and attempts to submit server-owned classification, routing,
  policy, retrieval, prompt, and validator fields.
- Exercise selected Phase 2 adversarial matrix cases through a real
  `FintechRagPipeline` deterministic-router seam with a fake classifier and no
  retriever, embedding model, Chroma client, chat model, or protected-model
  inference.
- Prove approved and unapproved CORS origins/preflights remain exact and never
  permit credentials.
- Prove one lifespan-owned classifier, pipeline, service container, and
  bounded executor are reused across HTTP requests.
- Prove successful and failed public bodies plus aggregate logs exclude
  prompts, policy internals, retrieval identifiers/scores/distances, local
  paths, stack traces, authentication headers, secrets, and exact classifier
  confidences.
- Retain and run the existing service-level concurrency and queue-limit tests.

### Excluded

- Phase 3 Step 12 or later cancellation-matrix, runner, deployment, or live
  integration work.
- Classification, routing, retrieval, generation, embedding, or validation
  changes.
- Active Chroma access or mutation, local Ollama calls, and classifier
  inference.
- New routes, request/response fields, middleware behavior, or public API
  changes.

## Files to inspect

- All `backend/app/api/` modules and `backend/app/main.py`
- Existing application, chat, middleware, error, service, streaming, model,
  health, and OpenAPI tests
- Phase 2 router, deterministic templates, orchestration pipeline, output
  validator, redaction tests, exact matrix cases, typed contracts, and all API
  caller/import sites

## Files expected to change

- `backend/tests/test_api_app.py` — prove shared service/dependency reuse across
  multiple HTTP requests without per-request construction.
- `backend/tests/test_api_chat.py` — add assembled validation,
  privileged-field rejection, deterministic adversarial seam, and body/log
  leakage coverage.
- `backend/tests/test_api_middleware.py` — complete approved/unapproved
  preflight and no-credentials assertions.
- `backend/tests/test_api_errors.py` — strengthen explicit stack-trace and
  private-runtime leakage assertions where needed.
- `docs/IMPLEMENTATION_STATUS.md` — record the verified Step 11 boundary.
- This plan — track decisions, commands, and final results.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — checksum verification only.
- `backend/.env` — do not expose or modify.
- Active/temporary/backup Chroma stores — do not open, rebuild, swap, or
  mutate.
- Local Ollama data — no access required.

## Compatibility constraints

- Preserve all Phase 1/2 public interfaces and Phase 3 Steps 1–10 contracts.
- Do not expose internal Phase 2 models, reason codes, classifications,
  retrieval data, policy/chunk identifiers, prompts, validator state,
  exception details, paths, headers, or secrets in responses or logs.
- Tests must not load the protected classifier, call Ollama, open Chroma,
  generate, embed, or require a running API process.
- Reuse the real deterministic router/pipeline only for branches that do not
  resolve retrieval or generation dependencies.

## Implementation milestones

1. [x] Inspect roadmap, API modules, callers/imports, Phase 2 safety seams,
   tests, documentation, and repository state.
2. [x] Add focused assembled HTTP validation, deterministic safety, reuse,
   CORS, and leakage coverage.
3. [x] Run focused and full verification; fix implementation-caused failures.
4. [x] Update status and final plan results; inspect diff/status; stop before
   Step 12.

## Acceptance criteria

- [x] Empty, blank, oversized, malformed, wrong-media-type, extra, and
  server-owned/trusted request fields are rejected through the HTTP boundary.
- [x] Selected prompt-injection, hidden-information, full-policy,
  refund-guarantee, sensitive-authentication-data, completed-action, and
  account-operation requests preserve deterministic safe behavior.
- [x] Approved/unapproved simple CORS and preflight behavior is restrictive and
  never includes credential permission.
- [x] Shared services are constructed once per lifespan and existing
  concurrency/queue bounds remain verified.
- [x] Public bodies and logs contain no private prompt, policy, retrieval,
  score/distance, path, stack-trace, header, secret, or exact-confidence data.
- [x] Tests require no live classifier, Ollama, Chroma, or running API.

## Testing plan

- Focused: `python -m pytest -q tests/test_api_chat.py
  tests/test_api_middleware.py tests/test_api_errors.py
  tests/test_api_services.py tests/test_api_app.py`
- Related: `python -m pytest -q tests/test_api_*.py`
- Compilation: `python -m compileall app scripts tests`
- Non-integration: `python -m pytest -q -m "not integration"`
- Validation: `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, `python -m pip check`
- Integration: NOT RUN unless service-free failures require live diagnosis;
  Step 11 adds tests only and has no live-service behavior.

## Live-service requirements

- Ollama: not required.
- Chroma: not required and not opened or mutated.
- Protected classifier: no inference; checksum verification only.
- Running FastAPI application: not required; tests run in process with fakes.

## Rollback considerations

- Test and documentation changes are reversible without migration.
- No model, policy, manifest, environment, or vector-store state changes.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Reuse `ServiceBuilder` and dependency overrides to exercise the assembled
  app without live services.
- Use `FintechRagPipeline()` only for deterministic static/unsupported routes;
  this tests the real router/template boundary without resolving optional
  retrieval or generation dependencies.
- Count existing Step 3 concurrency/queue tests toward Step 11 rather than
  duplicating the same lower-level scheduling matrix at the HTTP layer.

## Unresolved risks

- Starlette may emit its existing TestClient/HTTPX deprecation warning; it does
  not affect the API safety contract.

## Final results

- Files created: none.
- Files modified: `backend/tests/test_api_app.py`,
  `backend/tests/test_api_chat.py`, `backend/tests/test_api_errors.py`,
  `backend/tests/test_api_middleware.py`, `docs/IMPLEMENTATION_STATUS.md`, and
  this plan.
- Focused Step 11 boundary tests passed: 101 tests in 20.05s.
- An attempted `tests/test_api_*.py` wildcard command failed before collection
  because this Windows pytest invocation did not expand the wildcard. The
  explicit complete API command passed with 235 tests in 21.14s.
- Full compilation passed; the non-integration suite passed with 774 tests and
  3 integration tests deselected in 44.24s.
- Protected baseline verification passed for 5 artifacts, policy validation
  passed for 4 files, and `pip check` found no broken requirements.
- Live Ollama, Chroma, classifier inference, generation, embedding, a running
  server, and integration tests were not run because Step 11 is fully
  service-free and changes no runtime or persistent state.
- Remaining work: Phase 3 Step 12.
