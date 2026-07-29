# Phase 2 Step 29 Execution Plan

## Objective

Expand the Phase 2 RAG evaluation dataset to 45 strictly validated cases that
cover every roadmap category and record routing, response-mode, policy-scope,
safety-concept, human-support, and LLM-call expectations without contacting
live services.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 20 — Existing calibration/evaluation split and retrieval metrics
- Step 29 — Expanded 40–50-case evaluation dataset
- Step 32 — Required Phase 2 matrix used as supporting coverage guidance

## Scope

### Included

- Preserve the existing threshold list, calibration split, retrieval
  expectations, and `load_calibration_cases(...)` entry point.
- Expand `backend/tests/data/rag_evaluation_cases.json` from 20 to 45 cases.
- Add all Step 29 expected outcome and safety fields to every case.
- Record explicit category labels and require complete coverage of all 39
  roadmap categories.
- Strictly validate response modes, concepts, human/LLM flags, case IDs,
  category ownership, and cross-field routing invariants.
- Add focused tests for count, category coverage, safe outcome fields, router
  compatibility, and malformed-dataset rejection.

### Excluded

- Step 30's broader module-by-module automated unit-test expansion.
- Live retrieval, Chroma mutation, threshold reselection, or store rebuild.
- Live Ollama generation or output-quality scoring.
- Protected classifier inference, retraining, or model-file changes.
- Phase 2 metric reporting from Step 33.

## Files to inspect

- `backend/tests/data/rag_evaluation_cases.json` — current 20-case schema and
  fixtures.
- `backend/scripts/calibrate_retrieval.py` — sole dataset loader and evaluator.
- `backend/tests/test_calibrate_retrieval.py` — current strict-loader and
  calibration tests.
- `backend/app/ml/triage_types.py` — response mode and routing contracts.
- `backend/app/ml/risk_router.py` — authoritative deterministic route behavior.
- `backend/app/ml/rag_pipeline.py` — action-to-response-mode and LLM-call
  behavior.
- `backend/app/ml/policy_registry.py` — approved policy IDs.
- `backend/app/ml/response_templates.py` and relevant tests — required and
  prohibited safety concepts.

## Files expected to change

- `backend/tests/data/rag_evaluation_cases.json` — schema version 2 and 45
  cases.
- `backend/scripts/calibrate_retrieval.py` — backward-compatible typed access
  to Step 29 fields and strict schema validation.
- `backend/tests/test_calibrate_retrieval.py` — focused Step 29 validation.
- `docs/IMPLEMENTATION_STATUS.md` — Step 29 continuity record.
- This plan — implementation progress and exact verification results.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — verify only; never modify.
- `backend/app/data/chromadb_store/` — not required; never open or mutate.
- `backend/.env` and local Ollama data — not required; never inspect or change.

## Compatibility constraints

- Keep `load_calibration_cases(...)`, `CalibrationCase`, the two split names,
  threshold selection, router evaluation, and retriever evaluation usable by
  existing callers.
- Keep the original 10 calibration cases unchanged in query and routing intent
  so the selected threshold is not trained on newly added evaluation cases.
- Use only the four IDs in `KNOWN_POLICY_IDS`.
- Require `should_call_llm` exactly for `generate` routes and require response
  modes to agree with the current pipeline action branches.
- Do not claim the expanded locked set has passed live retrieval or generation.

## Implementation milestones

1. [x] Read the required documentation and inspect the dataset, loader,
   callers, imports, pipeline, router, policy registry, templates, and tests.
2. [x] Implement schema version 2 validation and the 45-case dataset.
3. [x] Add focused Step 29 tests and run service-free verification.
4. [x] Run practical repository checks, update continuity records, inspect the
   final diff/status, and stop before Step 30.

## Acceptance criteria

- [x] The dataset contains 40–50 unique cases and exactly 45 project cases.
- [x] Every Step 29 required category is represented.
- [x] Every case has three ranked unique predictions and consistent margin.
- [x] Every case records expected risk, action, response mode, policy scope,
  required/prohibited concepts, human support, and LLM-call behavior.
- [x] Existing router evaluation remains compatible and passes for both splits.
- [x] Calibration and locked evaluation remain separate.
- [x] Malformed categories and inconsistent outcome flags fail closed.
- [x] Focused tests require no Ollama, Chroma, or protected-model loading.

## Testing plan

- Unit: `python -m pytest -q tests/test_calibrate_retrieval.py`
- Related: `python -m pytest -q tests/test_risk_router.py tests/test_rag_pipeline.py tests/test_output_validator.py`
- Non-integration: `python -m pytest -q -m "not integration"`
- Validation: `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`
- Integration: NOT_RUN unless needed to diagnose an implementation failure;
  Step 29 is a service-free static evaluation-data step.

## Live-service requirements

- Ollama: not required.
- Chroma: not required; no store reads or writes.
- Protected classifier: not required for fixtures; baseline verification only.

## Rollback considerations

- No persistent runtime storage or service state changes.
- Rollback is limited to the dataset, loader/tests, this plan, and continuity
  notes.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Evolve the existing file to schema version 2 rather than create a parallel
  source of truth.
- Retain the Step 20 fields because the calibration script is an existing
  public operator workflow.
- Add explicit category labels so required Step 29 coverage is machine
  verifiable rather than inferred from query wording.
- Add outcome fields directly to `CalibrationCase` so future tests can consume
  one validated typed contract without reparsing JSON.

## Unresolved risks

- The expanded locked cases are service-free fixtures in Step 29. Their live
  retrieval and LLM behavior remains intentionally unverified until the later
  roadmap integration and quality-measurement steps.

## Final results

- Created this plan.
- Modified `backend/tests/data/rag_evaluation_cases.json`,
  `backend/scripts/calibrate_retrieval.py`,
  `backend/tests/test_calibrate_retrieval.py`, and
  `docs/IMPLEMENTATION_STATUS.md`.
- `python -m compileall app scripts tests`: exit code 0.
- `python -m pytest -q tests/test_calibrate_retrieval.py`:
  final run 12 passed in 9.01 seconds.
- The first related-test invocation was denied while the sandbox attempted to
  launch the virtual environment's base interpreter. The approved rerun passed:
  `python -m pytest -q tests/test_risk_router.py tests/test_rag_pipeline.py
  tests/test_output_validator.py`: 170 passed in 9.87 seconds.
- `python -m pytest -q -m "not integration"`:
  final run 440 passed, 3 deselected in 17.07 seconds.
- `python scripts/verify_phase1_baseline.py`: five protected artifacts passed.
- `python scripts/validate_policies.py`: four approved policies passed.
- `python -m pip check`: no broken requirements.
- Live Ollama, Chroma, and integration tests were not run because Step 29 is a
  static service-free dataset step. Live outcomes remain for Steps 31 and 33.
- No environment, model, policy, manifest, or vector-store data was modified.
- Remaining work: Step 30. It was not started.
