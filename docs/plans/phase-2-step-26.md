# Phase 2 Step 26 Execution Plan

## Objective

Add synchronous and asynchronous validated buffered delivery to the existing
pipeline so Phase 3 can consume small display chunks without ever receiving
raw local-model tokens or unvalidated generated text.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 26 — Implement safe buffered streaming
- Step 25 — Existing complete-answer orchestration and validation boundary
- Step 30 — Streaming and async test expectations
- `personal project documentation/phase 2 flow chart.txt`
  — validated buffered delivery stage

## Scope

### Included

- Add `FintechRagPipeline.stream_answer(...) -> Iterator[str]`.
- Add
  `FintechRagPipeline.astream_answer(...) -> AsyncIterator[str]`.
- Generate the complete `PipelineAnswer` through `answer()` before yielding.
- Split only the final approved answer into bounded display chunks while
  preserving the exact text when chunks are joined.
- Use the same delivery path for generated, deterministic, clarification, and
  fallback responses.
- Keep blocking pipeline execution off the event loop in the async method.
- Add focused service-free synchronous and asynchronous tests.

### Excluded

- Raw Ollama token streaming or provider streaming APIs.
- FastAPI routes, streaming event schemas, disconnect handling, or frontend
  integration.
- Ollama health checks, vector-store inspection, evaluation expansion,
  logging, or any Step 27+ work.
- Changes to routing, retrieval, generation, validation, policies, ingestion,
  settings, environment files, or persistent stores.

## Files to inspect

- `backend/app/ml/rag_pipeline.py` — target class and complete-answer safety
  boundary.
- `backend/app/ml/triage_types.py` — `PipelineAnswer` contract.
- `backend/app/ml/structured_generation.py` — full structured-generation
  behavior that must remain buffered.
- `backend/app/ml/output_validator.py` — approval boundary before delivery.
- `backend/tests/test_rag_pipeline.py` — existing fakes, branch coverage, and
  compatibility expectations.
- All imports and callers found by repository search.

## Files expected to change

- `backend/app/ml/rag_pipeline.py` — add both buffered delivery methods and
  exact text chunking.
- Create `backend/tests/test_streaming.py` — synchronous buffered delivery
  tests.
- Create `backend/tests/test_async_streaming.py` — asynchronous buffered
  delivery and event-loop behavior tests.
- Create this plan.
- Update `docs/IMPLEMENTATION_STATUS.md`.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — verify only.
- `backend/app/data/chromadb_store/` — no access or mutation is required.
- `.env` and other local runtime data — no access or mutation is required.

## Compatibility constraints

- Preserve `FintechRagPipeline.answer(...)` and every Step 0–25 public
  interface.
- Reuse `answer()` as the sole orchestration and approval boundary; do not
  duplicate route, retrieval, generation, or validator logic.
- Reconstructing all yielded chunks must exactly equal `PipelineAnswer.answer`.
- No chunk may be yielded until `answer()` has returned successfully.
- Never expose provider tokens, rejected text, prompts, policy content,
  internal errors, or private runtime data.
- Constructor and deterministic delivery must remain lazy and service-free.

## Implementation milestones

1. [x] Read the documentation and complete Step 26 section; inspect pipeline
   interfaces, dependencies, callers, tests, and service constraints.
2. [x] Add exact, bounded display chunking plus synchronous and asynchronous
   delivery methods.
3. [x] Add focused fake-based tests for buffering, exact reconstruction,
   fallbacks, validation rejection, errors, and async behavior.
4. [x] Run compilation, focused/full tests, and repository validations.
5. [x] Update continuity records, inspect the final diff/status, and stop
   before Step 27.

## Acceptance criteria

- [x] Sync and async public streaming methods exist with the roadmap
  signatures.
- [x] Both methods deliver only the complete result selected by `answer()`.
- [x] Joined chunks exactly reproduce the approved answer.
- [x] Display chunks are non-empty and bounded.
- [x] Unsafe generated output is discarded before the first chunk.
- [x] Static, clarification, urgent, fallback, and generated answers share the
  same buffered delivery mechanism.
- [x] Input or pipeline errors do not yield partial text.
- [x] The async method does not run blocking answer work on the event-loop
  thread.
- [x] No live Ollama, Chroma, or classifier dependency is required by focused
  tests.

## Testing plan

- Focused sync:
  `python -m pytest -q tests/test_streaming.py`
- Focused async:
  `python -m pytest -q tests/test_async_streaming.py`
- Pipeline regression:
  `python -m pytest -q tests/test_rag_pipeline.py`
- Non-integration:
  `python -m pytest -q -m "not integration"`
- Integration: `NOT_RUN` unless needed to diagnose an implementation-caused
  regression; Step 26 does not change any live-service boundary.
- Validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Ollama: not required for implementation or focused tests. Runtime generated
  answers continue to use the existing approved loopback model through
  `answer()`.
- Chroma: not required for implementation or focused tests. Runtime eligible
  routes continue to use the existing validated active store through
  `answer()`.
- Protected classifier: not loaded by the streaming unit tests.

## Rollback considerations

- Step 26 changes only source, tests, and continuity documentation.
- No environment, model, policy, manifest, or vector-store data changes.
- Rollback removes the two delivery methods, private chunk helper, focused
  tests, and this plan while retaining the Step 25 synchronous pipeline.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Use `answer()` as the only approval boundary so all response modes inherit
  the existing safety behavior.
- Use deterministic character-bounded chunks because they preserve exact text
  and put a hard upper bound on every yielded display chunk.
- Run `answer()` through a worker thread in `astream_answer()` because the
  existing retrieval and local-generation stack is synchronous and may block.
- Keep the display chunk size as a module constant rather than introducing a
  new environment or ingestion setting; delivery chunking does not affect
  policy, prompt, model, or store compatibility.

## Unresolved risks

- Phase 3 still owns typed transport events, cancellation/disconnection
  handling, and HTTP streaming integration.
- Live Ollama/Chroma integrations were not run because Step 26 is a delivery
  wrapper over the already verified `answer()` boundary and does not change
  either service integration.

## Final results

- Created `backend/tests/test_streaming.py`,
  `backend/tests/test_async_streaming.py`, and this plan.
- Modified `backend/app/ml/rag_pipeline.py` and
  `docs/IMPLEMENTATION_STATUS.md`.
- The first combined compile/focused-test command was blocked before execution
  by sandbox access to the virtual environment's base interpreter. The exact
  command was rerun with approved execution access.
- `python -m compileall app scripts tests` passed with exit code 0.
- `python -m pytest -q tests/test_streaming.py` passed in its final run:
  6 tests.
- `python -m pytest -q tests/test_async_streaming.py` passed: 4 tests.
- `python -m pytest -q tests/test_rag_pipeline.py` passed: 57 tests.
- `python -m pytest -q -m "not integration"` passed in its final run:
  394 tests, 3 deselected.
- `python scripts/validate_policies.py` passed: four approved policies.
- `python scripts/verify_phase1_baseline.py` passed: five protected artifacts.
- `python -m pip check` passed: no broken requirements.
- `git diff --check` passed with exit code 0.
- Live integration tests were not run because Step 26 does not change Ollama,
  Chroma, embeddings, retrieval, generation, or persistent storage.
- No environment, model, policy, manifest, or vector-store data was modified.
- Remaining work: Step 27. It was not started.
