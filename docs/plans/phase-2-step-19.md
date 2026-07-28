# Phase 2 Step 19 Execution Plan

## Objective

Add a deterministic, fail-closed retrieval sufficiency decision that verifies
the final Step 18 context against router scope, approval/version invariants,
the active ingestion manifest, and the configured context limit.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 19 — Determine retrieval sufficiency

## Scope

### Included

- Return insufficient for empty accepted context.
- Verify every policy is allowed and every required policy is represented.
- Reuse Step 18 candidate acceptance checks for approval and record safety.
- Reject conflicting versions for the same policy document.
- Verify retrieved versions and source filenames against the active manifest.
- Verify manifest retrieval configuration and record/count consistency.
- Enforce `RAG_MAX_CONTEXT_CHUNKS`.
- Provide both an injectable pure function and a retriever-bound convenience
  method using the manifest already validated during retriever construction.

### Excluded

- Step 20 threshold calibration.
- High-risk/static/generated response construction, reason-code selection, or
  orchestration; those behaviors require the later pipeline step.
- Generation, prompts, output validation, API, frontend, or logging.
- Policy, embedding, manifest, or Chroma-store rebuilds.

## Files to inspect

- `backend/app/ml/retriever.py` — accepted-context rules, manifest validation,
  runtime retriever, and target location.
- `backend/app/ml/triage_types.py` — `RetrievedPolicy` and `TriageDecision`.
- `backend/app/ml/ingest_policies.py` — strict `IngestionManifest` and loader.
- `backend/app/ml/rag_config.py` — configured maximum context.
- `backend/app/ml/risk_router.py` — allowed/required scope invariants.
- `backend/tests/test_retrieval_rules.py` — reusable Step 18 policy fixtures.
- `backend/tests/test_vector_store_integration.py` — real manifest/retriever
  coverage under a temporary store.

## Files expected to change

- Update `backend/app/ml/retriever.py`.
- Update `backend/tests/test_retrieval_rules.py`.
- Update `backend/tests/test_vector_store_integration.py`.
- Update this plan and `docs/IMPLEMENTATION_STATUS.md`.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — read only through the
  checksum verifier.
- `backend/app/data/chromadb_store/` — read-only smoke access only; no rebuild
  or swap.

## Compatibility constraints

- Preserve every Steps 0–18 interface.
- Keep the roadmap-compatible
  `retrieval_is_sufficient(policies, decision)` call shape; allow manifest and
  settings injection only as optional keywords.
- Reuse `RetrievedPolicy`, `TriageDecision`, `IngestionManifest`,
  `validate_retrieval_manifest(...)`, and Step 18 record acceptance logic.
- Return `False`, rather than raising, for malformed/stale runtime state or
  insufficient retrieval.
- Do not call Ollama, Chroma, the classifier, or the LLM in unit tests.

## Implementation milestones

1. [x] Inspect the complete Step 19 roadmap, existing manifest/retrieval
   contracts, router scope semantics, callers, and tests.
2. [x] Implement manifest-aware sufficiency and retriever-bound convenience
   behavior.
3. [x] Add focused tests for all seven roadmap conditions and fail-closed
   malformed state.
4. [x] Run compilation, focused/full tests, applicable temporary-store/live
   smoke checks, and repository validation.
5. [x] Update continuity records and stop before Step 20.

## Acceptance criteria

- [x] Empty policy context is insufficient.
- [x] Disallowed, unapproved, malformed, or below-threshold records are
  insufficient.
- [x] Missing required policy families are insufficient.
- [x] Conflicting policy versions are insufficient.
- [x] Manifest version/source/configuration/count conflicts are insufficient.
- [x] Context above the configured maximum is insufficient.
- [x] A valid accepted context satisfying all conditions returns `True`.
- [x] Missing or malformed active-manifest state returns `False`.

## Testing plan

- Focused:
  `python -m pytest -q tests/test_retrieval_rules.py tests/test_retriever.py`
- Non-integration: `python -m pytest -q -m "not integration"`
- Integration: `python -m pytest -q -m integration`
- Validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Ollama: not required for implementation or focused tests.
- Chroma: not required for implementation or focused tests.
- The existing integration marker may verify the bound method with an
  already-running approved loopback Ollama and pytest temporary Chroma store.
- The configured active store may be queried read-only for a final smoke check;
  no rebuild, swap, or mutation is required.

## Rollback considerations

- Step 19 changes source, tests, and continuity documents only.
- No persistent data format or runtime store changes.
- Rollback reverts only Step 19 edits while preserving uncommitted Steps 17–18
  and unrelated user work.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Store the constructor-validated manifest on `PolicyRetriever` and use it in
  a bound sufficiency method.
- The pure function optionally accepts a manifest; when omitted, it strictly
  loads the configured active manifest to preserve the roadmap's two-argument
  call shape.
- A record matches the manifest only when its document version equals
  `policy_versions[document_id]` and its safe source filename exists in
  `source_hashes`; `RetrievedPolicy` intentionally does not duplicate the
  source hash itself.
- Step 19 returns only a boolean. Deterministic safety fallbacks and generation
  gating are later orchestration responsibilities.

## Unresolved risks

- Sufficiency confirms only metadata available in `RetrievedPolicy`; chunk
  content hashes are validated during Step 17 conversion, while source hashes
  remain authoritative in the manifest and stored Chroma metadata.

## Final results

- Created `docs/plans/phase-2-step-19.md`.
- Modified `backend/app/ml/retriever.py`,
  `backend/tests/test_retrieval_rules.py`,
  `backend/tests/test_vector_store_integration.py`, and
  `docs/IMPLEMENTATION_STATUS.md`.
- Compilation passed.
- Focused tests passed: 61.
- Non-integration tests passed: 183, with 1 integration test deselected.
- The live temporary-store integration test passed: 1, with 183 tests
  deselected and three Chroma deprecation warnings.
- The read-only active-store Step 19 smoke check passed with four sufficient
  `card_delivery` chunks.
- Policy validation, protected Phase 1 baseline verification, and dependency
  validation passed.
- No persistent store was rebuilt, swapped, or modified.
- Remaining work: Step 20 calibration. It was not started.
