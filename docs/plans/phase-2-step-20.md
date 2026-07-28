# Phase 2 Step 20 Execution Plan

## Objective

Calibrate the retrieval relevance threshold against separate calibration and
locked evaluation cases while reporting router and retriever behavior
independently and preserving all Step 19 safety invariants.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 20 — Calibrate the retrieval threshold

## Scope

### Included

- Add a strictly validated Step 20 calibration/evaluation dataset.
- Evaluate thresholds `0.20` through `0.50` in increments of `0.05`.
- Measure the five required router behaviors separately from retrieval.
- Measure expected-policy hits, Recall@4, false-positive policies,
  unsupported-query acceptance, false fallbacks, average context size, and
  required-policy-family coverage.
- Select a threshold using only calibration cases.
- Report the selected threshold once against the locked evaluation cases.
- Update `.env.example` and the ignored local `.env` to the selected value.

### Excluded

- Step 21 chat-model construction.
- The later 40–50-case Step 29 full evaluation dataset.
- Prompting, generation, output validation, pipeline orchestration, API,
  frontend, or logging.
- Policy, chunking, embedding, manifest, or Chroma-store changes.

## Files to inspect

- `backend/app/ml/rag_config.py` — configuration and evaluation-data path.
- `backend/app/ml/retriever.py` — threshold filtering and active retriever.
- `backend/app/ml/risk_router.py` — independently measured routing behavior.
- `backend/app/ml/policy_registry.py` — approved policy scope.
- `backend/app/ml/triage_types.py` — reused typed contracts.
- Existing router, retriever, configuration, and integration tests.

## Files expected to change

- Create `backend/tests/data/rag_evaluation_cases.json`.
- Create `backend/scripts/calibrate_retrieval.py`.
- Create `backend/tests/test_calibrate_retrieval.py`.
- Update `backend/.env.example` and the ignored `backend/.env`.
- Update this plan and `docs/IMPLEMENTATION_STATUS.md`.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — checksum verification only.
- `backend/app/data/chromadb_store/` — read-only calibration queries only.

## Compatibility constraints

- Preserve every Step 0–19 public interface.
- Reuse immutable settings and Pydantic contracts.
- Never perform an unfiltered retrieval.
- Unit tests use fake retrieval and do not require Ollama or Chroma.
- Dataset/schema/configuration/runtime failures must produce a nonzero script
  result without exposing private paths, prompts, or policy contents.
- Threshold-only configuration changes must not trigger a Chroma rebuild.

## Implementation milestones

1. [x] Read the roadmap and inspect all affected interfaces, imports, callers,
   tests, environment dependencies, and local-service constraints.
2. [x] Add the validated split dataset and deterministic calibration/reporting
   script.
3. [x] Add focused unit tests for validation, metrics, selection, locked-split
   isolation, and fail-closed behavior.
4. [x] Run live read-only calibration and update both threshold configuration
   files with the selected value.
5. [x] Run compilation, focused/full tests, validations, and final diff review.
6. [x] Update continuity records and stop before Step 21.

## Acceptance criteria

- [x] Exactly the seven roadmap thresholds are evaluated.
- [x] Calibration and evaluation IDs are nonempty, unique, and disjoint.
- [x] Router metrics cover every roadmap category.
- [x] Retriever metrics cover every roadmap metric.
- [x] Threshold selection cannot inspect locked evaluation outcomes.
- [x] Unsupported probes remain metadata-filtered.
- [x] Malformed cases and live retrieval failures fail closed.
- [x] `.env.example` and `.env` use the selected threshold.
- [x] No Chroma store or protected model artifact is modified.

## Testing plan

- Focused:
  `python -m pytest -q tests/test_calibrate_retrieval.py`
- Retrieval regression:
  `python -m pytest -q tests/test_retriever.py tests/test_retrieval_rules.py`
- Non-integration:
  `python -m pytest -q -m "not integration"`
- Live calibration:
  `python scripts/calibrate_retrieval.py`
- Integration:
  `python -m pytest -q -m integration`
- Validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Unit tests: no Ollama, Chroma, or classifier required.
- Live calibration: approved loopback Ollama with `nomic-embed-text` and the
  existing active Chroma store/manifest; read-only queries only.
- The protected classifier is not needed to select a retrieval threshold
  because router cases contain fixed typed predictions.

## Rollback considerations

- No persistent store changes are made.
- Reverting Step 20 removes its dataset/script/tests/docs and restores the two
  threshold configuration lines.
- Existing uncommitted Steps 17–19 and unrelated user work must remain intact.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Store fixed classifier predictions in the Step 20 cases so router evaluation
  is deterministic and separate from classifier quality.
- Permit explicitly marked unsupported semantic probes to use a reviewed,
  nonempty policy scope only inside calibration; the script never falls back
  to an unfiltered search.
- Use a safety-first deterministic threshold ordering based only on the
  calibration split, then calculate the locked evaluation report once.

## Unresolved risks

- The small Step 20 dataset calibrates the current four-policy prototype; Step
  29 must later expand the locked evaluation matrix before final reporting.
- Unsupported semantic probes accepted policy chunks at every approved
  threshold, including `0.50`. Normal operation must continue to enforce the
  deterministic router rule that unsupported requests never call retrieval.

## Final results

- Created `backend/scripts/calibrate_retrieval.py`,
  `backend/tests/data/rag_evaluation_cases.json`,
  `backend/tests/test_calibrate_retrieval.py`, and this plan.
- Modified `backend/app/ml/retriever.py`,
  `backend/tests/test_retriever.py`, `backend/.env.example`, the ignored local
  `backend/.env`, and `docs/IMPLEMENTATION_STATUS.md`.
- Live calibration selected `0.50`. Both ten-case router splits scored 100%;
  the locked retrieval split retained 100% expected-policy hit, Recall@4, and
  required-family coverage with no false fallback or false-positive policies.
- Unsupported forced-retrieval acceptance remained 100% across the tested
  range and is recorded as a routing-boundary risk.
- Compilation passed; focused Step 20/retrieval tests passed: 70.
- Non-integration tests passed: 192, with 1 integration test deselected.
- Live temporary-store integration passed: 1, with 192 tests deselected and
  three Chroma deprecation warnings.
- Policy validation, protected baseline verification, dependency validation,
  and threshold configuration consistency passed.
- No active store was rebuilt, swapped, or modified.
- Remaining work: Step 21. It was not started.
