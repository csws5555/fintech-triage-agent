# Phase 2 Step 30 Execution Plan

## Objective

Complete and verify the service-free automated unit-test matrix required by
Step 30, reusing the extensive coverage already present from earlier roadmap
steps and adding only missing focused edge cases.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 30 — Add automated unit tests

## Scope

### Included

- Audit every Step 30 bullet against the current test suite.
- Preserve existing test modules and helpers where they already prove the
  required behavior.
- Add focused tests for uncovered configuration, classifier, and embedding
  edge cases.
- Run the complete Step 30 unit-test matrix without live Ollama or Chroma.

### Excluded

- Step 31 live integration tests.
- Live Ollama generation, embedding, or health probes.
- Live Chroma reads, rebuilds, swaps, or other persistent-store operations.
- Classifier retraining, protected-model changes, or live classifier inference.
- Application behavior changes not required to make Step 30 complete.

## Files to inspect

- `backend/app/ml/rag_config.py` — configuration validation under test.
- `backend/app/ml/classifier.py` — local classifier loading and output rules.
- `backend/app/ml/risk_router.py` — deterministic route matrix.
- `backend/app/ml/policy_registry.py` — approved intent-to-policy scope.
- `backend/app/ml/policy_loader.py` — policy metadata and hash validation.
- `backend/app/ml/embeddings.py` — exact-once Nomic prefixes and input checks.
- `backend/app/ml/retriever.py` — scoped retrieval and filtering rules.
- `backend/app/ml/output_validator.py` — deterministic output safety checks.
- `backend/app/ml/rag_pipeline.py` — orchestration and buffered async delivery.
- The corresponding `backend/tests/test_*.py` modules and their shared fakes.
- `backend/.env.example`, `backend/pytest.ini`, and
  `backend/requirements.txt` — test configuration and dependency constraints.

## Files expected to change

- `backend/tests/test_rag_config.py` — missing malformed-port and prefix cases.
- `backend/tests/test_classifier.py` — explicit long-input, exact-cardinality,
  out-of-range, and infinite-score cases.
- `backend/tests/test_embedding_adapter.py` — blank document-text cases.
- `docs/IMPLEMENTATION_STATUS.md` — Step 30 continuity record.
- This plan — progress, decisions, and exact verification results.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — verify only; never modify.
- `backend/app/data/chromadb_store/` — not required and must not be mutated.
- `backend/.env` and local Ollama data — not required and must not be exposed.

## Compatibility constraints

- Keep all current application interfaces unchanged.
- Retain `backend/tests/test_rag_pipeline.py` as the authoritative current
  pipeline test module rather than creating the roadmap's older
  `test_pipeline.py` name.
- Reuse `test_retriever.py` coverage for the mandatory metadata filter and
  no-unfiltered-fallback behavior.
- Unit tests must use fakes or pure functions and must not contact live Ollama,
  Chroma, or the protected classifier.

## Implementation milestones

1. [x] Read the required documentation and inspect all Step 30 modules,
   callers, imports, configuration, scripts, and existing tests.
2. [x] Add only the missing focused unit cases.
3. [x] Run the focused Step 30 matrix and practical repository checks.
4. [x] Update continuity records, inspect final diff/status, and stop before
   Step 31.

## Acceptance criteria

- [x] Every Step 30 roadmap bullet is covered by an identified automated test.
- [x] Configuration tests include malformed ports and incorrect Nomic
  prefixes.
- [x] Classifier tests explicitly cover exactly-three cardinality, long-input
  truncation, score bounds, and non-finite scores.
- [x] Embedding tests reject blank query and blank document content
  consistently.
- [x] Pipeline tests cover all deterministic, retrieval, generation,
  validation-fallback, and no-call branches.
- [x] `astream_answer()` yields only a complete approved/fallback answer and
  never rejected text.
- [x] The complete focused matrix runs without live services.

## Testing plan

- Unit: `python -m pytest -q tests/test_rag_config.py tests/test_classifier.py
  tests/test_risk_router.py tests/test_policy_registry.py
  tests/test_policy_loader.py tests/test_embedding_adapter.py
  tests/test_retrieval_rules.py tests/test_retriever.py
  tests/test_output_validator.py tests/test_rag_pipeline.py
  tests/test_async_streaming.py`
- Non-integration: `python -m pytest -q -m "not integration"`
- Validation: `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`
- Integration: NOT_RUN; Step 31 owns live integration tests and Step 30 must
  remain service-free.

## Live-service requirements

- Ollama: not required.
- Chroma: not required; no store reads or writes.
- Protected classifier: no inference; baseline verification only.

## Rollback considerations

- No persistent runtime data or service state changes.
- Rollback is limited to focused test additions and continuity documentation.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Reuse existing tests when their assertions already prove a roadmap
  requirement; do not duplicate them under new names.
- Treat `test_rag_pipeline.py` as the current equivalent of the roadmap's
  proposed `test_pipeline.py`.
- Count the fake-vector-store assertions in `test_retriever.py` as the
  authoritative proof that retrieval never retries without a policy filter.
- Add explicit missing edge cases without changing production interfaces.

## Unresolved risks

- Live integration behavior remains intentionally untested in this step; it is
  the scope of Step 31.

## Final results

- Created this plan.
- Modified `backend/tests/test_rag_config.py`,
  `backend/tests/test_classifier.py`,
  `backend/tests/test_embedding_adapter.py`, and
  `docs/IMPLEMENTATION_STATUS.md`.
- No application source, public interface, environment, policy, manifest,
  vector store, or protected model was changed.
- The initial pre-edit Step 30 matrix passed with 290 tests.
- The post-edit focused changed-file run passed: 48 tests in 11.72 seconds.
- The complete post-edit Step 30 matrix passed: 301 tests in 14.60 seconds.
- `python -m compileall app scripts tests`: exit code 0.
- `python -m pytest -q -m "not integration"`: 451 passed, 3 deselected in
  16.12 seconds; exit code 0.
- `python scripts/verify_phase1_baseline.py`: five protected artifacts passed.
- `python scripts/validate_policies.py`: four approved policies passed.
- `python -m pip check`: no broken requirements.
- `git diff --check`: exit code 0 with no whitespace errors; the final diff
  and `git status --short` were inspected, including unrelated pre-existing
  Phase 2 changes that were preserved.
- Live integration tests were not run because Step 30 is explicitly
  service-free and Step 31 owns live Ollama/Chroma verification.
- Remaining work: Step 31. It was not started.
