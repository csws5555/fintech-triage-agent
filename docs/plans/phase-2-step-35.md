# Phase 2 Step 35 Execution Plan

## Objective

Run the complete final Phase 2 execution order, repair any verified readiness
defects, and establish an evidence-backed handoff boundary for Phase 3 without
starting API implementation.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 35 — Phase 2 execution order
- Phase 2 definition of done
- Phase 2 output for Phase 3
- When Chroma must be rebuilt

## Scope

### Included

- Compile and run the complete service-free test suite.
- Verify the protected Phase 1 baseline, policy sources, and dependencies.
- Check the approved loopback Ollama models.
- Rebuild the active Chroma store only through the stopped-client-gated,
  staged, rollback-capable command required by the implemented interface.
- Inspect the rebuilt store, run live retrieval, retain the calibrated
  threshold, and run all integration tests.
- Run the live pipeline, exact Phase 2 matrix, and locked quality command.
- Verify the documented Phase 3 classifier/pipeline and buffered-delivery
  imports.
- Reduce the Step 34 numeric-identifier false-positive risk while preserving
  conservative card redaction.

### Excluded

- FastAPI routes, request schemas, CORS, HTTP streaming events, frontend code,
  or any Phase 3 implementation.
- Ollama startup, model pulls, model changes, cloud substitution, or printing
  model digests.
- Threshold changes unless calibration selects a different approved value.
- Policy, chunking, embedding, manifest-schema, or classifier-model changes.
- Git commits.

## Files to inspect

- `backend/scripts/rebuild_vector_store.py` — authoritative stopped-client CLI.
- `backend/app/ml/ingest_policies.py` — staged build, activation, verification,
  rollback, and manifest implementation.
- `backend/scripts/check_ollama.py` — approved read-only model checks.
- `backend/scripts/inspect_vector_store.py` — active-store integrity checks.
- `backend/scripts/test_retrieval.py` — live retrieval invariants.
- `backend/scripts/calibrate_retrieval.py` — calibrated threshold selection.
- `backend/scripts/test_rag_pipeline.py` — live end-to-end orchestration.
- `backend/scripts/test_phase2_matrix.py` — exact roadmap behavior matrix.
- `backend/scripts/measure_phase2_quality.py` — locked quality goals.
- `backend/app/ml/classifier.py` and `backend/app/ml/rag_pipeline.py` — Phase 3
  handoff interfaces and their callers.
- `backend/app/ml/redaction.py` — Step 34 carry-forward risk.
- Relevant unit and integration tests importing every operator seam above.

## Files expected to change

- `backend/app/ml/redaction.py` — distinguish unlabeled numeric identifiers
  from card-like values using card context or checksum evidence.
- `backend/tests/test_redaction.py` — focused regression coverage.
- `docs/IMPLEMENTATION_STATUS.md` — final Phase 2 verification and Phase 3
  handoff status.
- This plan — ordered execution, exact results, and final risks.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — checksum and inference only.
- `backend/.env` — calibration may inspect runtime settings but values must
  never be printed or exposed.
- Local Ollama data — read-only health/model use.
- Active Chroma store — may change only through the explicit staged rebuild
  after confirming no backend/Chroma client process is running.

## Compatibility constraints

- Preserve all application and operator interfaces.
- Use `--confirm-clients-stopped` even though the older roadmap command omits
  it; the implemented safety interface is authoritative.
- Release every Chroma client before active-store activation.
- Do not rebuild merely for logging/redaction or relevance-threshold changes.
- Apply Nomic prefixes exactly once and use only configured allowlisted local
  models.
- Keep all user-facing critical, clarification, refusal, and fallback behavior
  deterministic.

## Implementation milestones

1. [x] Read required documentation and inspect Step 35 implementation,
   callers/imports, tests, configuration, processes, and storage prerequisites.
2. [x] Fix the bounded Step 34 false-positive risk and pass focused tests.
3. [x] Run the Step 35 sequence through rebuild, inspection, retrieval,
   calibration, complete tests, and live orchestration.
4. [x] Run the extended matrix, quality, and Phase 3 handoff checks; update
   continuity and stop before Phase 3.

## Acceptance criteria

- [x] Non-integration and integration suites pass.
- [x] Protected model and all four policies validate unchanged.
- [x] Approved loopback Ollama embedding and generation checks pass.
- [x] Staged rebuild reopens a compatible active store with no leftover
  temporary or backup store.
- [x] Active-store inspection and live retrieval pass every invariant.
- [x] Calibration retains or explicitly updates the approved threshold.
- [x] Live pipeline, exact matrix, and all locked portfolio goals pass.
- [x] Phase 3 can import and use classifier, answer, sync stream, and async
  stream interfaces.
- [x] Unlabeled non-card numeric identifiers are not redacted solely by length,
  while contextual and checksum-valid card values remain protected.

## Testing plan

- Focused: `python -m pytest -q tests/test_redaction.py`
- Deterministic: `python -m pytest -q -m "not integration"`
- Complete: `python -m pytest -q`
- Live integration: `python -m pytest -q -m integration`
- Operators: the Step 35 commands in roadmap order, followed by
  `python scripts/test_phase2_matrix.py` and
  `python scripts/measure_phase2_quality.py`
- Validation: `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Ollama: already-running loopback service with unique installed
  `llama3.2:3b` and `nomic-embed-text` records and valid digests.
- Chroma: backend and all clients stopped immediately before the staged active
  rebuild; later checks open the rebuilt store read-only.
- Protected classifier: local inference only during live pipeline, matrix,
  quality, and Phase 3 handoff checks.

## Rollback considerations

- The rebuild implementation first builds and verifies a temporary store,
  preserves the prior active store as a backup during activation, restores it
  if reopen verification fails, and removes the backup only after success.
- Windows directory moves are staged and rollback-capable, not claimed atomic.
- The source compatibility fix is isolated to redaction and its tests.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Treat the implemented stopped-client flag as authoritative over the older
  roadmap snippet.
- Run the exact matrix and locked quality command in addition to the original
  Step 35 sequence because they were added by Steps 32–33 and are necessary for
  a current whole-phase release decision.
- Use payment-card context or a valid Luhn checksum for unlabeled long digit
  sequences, reducing identifier over-redaction without weakening explicitly
  labeled card protection.

## Unresolved risks

- Local Llama output remains nondeterministic. One initial delivery probe
  returned a safe but unexpected outcome on the first full-pipeline run; an
  isolated safe-metadata retry, the final seven-probe rerun, the 25-case matrix,
  and the locked quality command all passed. Existing validation and safe
  fallback behavior must remain.
- Chroma 1.5.9 emits three legacy embedding-function configuration deprecation
  warnings during the temporary-store integration test. Store behavior and
  reopen verification pass, but dependency upgrades must review this warning.

## Final results

- Created this plan.
- Modified `backend/app/ml/redaction.py`,
  `backend/tests/test_redaction.py`,
  `backend/scripts/inspect_vector_store.py`,
  `backend/tests/test_inspect_vector_store.py`, and
  `docs/IMPLEMENTATION_STATUS.md`.
- Focused redaction: `56 passed in 0.10s`.
- Focused inspection/redaction compatibility:
  `71 passed in 10.23s`.
- Initial compilation passed; the first final compilation launch was
  sandbox-denied before Python started, and the approved final rerun passed.
  Non-integration:
  `539 passed, 3 deselected in 42.34s`.
- Ollama passed all eight checks; four policies and five protected model
  artifacts passed; `pip check` found no broken requirements.
- The first rebuild launch was sandbox-denied before Python started. After
  explicit approval, stopped-client preflight and the staged rebuild passed
  with 67 chunks and 768-dimensional embeddings.
- Active-store inspection passed 67/67 records with no integrity failures or
  leftover temporary/backup store. Six live retrieval checks passed.
- Calibration retained `0.50`; `.env.example` and the ignored runtime setting
  already matched, so neither file required an edit.
- Complete pytest: `542 passed, 3 warnings in 37.52s`.
  Explicit integration: `3 passed, 539 deselected, 3 warnings in 29.08s`.
- The first live pipeline run had one transient generated-delivery mismatch.
  Safe metadata diagnosis passed; the final seven-probe rerun passed.
- Exact Phase 2 matrix: `25 of 25` passed.
- Locked quality: all 29 metrics were recorded on 36 cases and all six
  portfolio goals passed, with zero prohibited/sensitive/completed/leakage
  rates.
- Phase 3 classifier, answer, synchronous stream, and asynchronous stream
  handoff smoke check passed.
- `git diff --check` passed; final diff/status and absence of leftover
  temporary/backup stores were inspected. Existing unrelated Phase 2 changes
  remain preserved.
- No Phase 2 roadmap step remains. Phase 3 was not started.
