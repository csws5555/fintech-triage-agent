# Phase 2 Step 18 Execution Plan

## Objective

Filter, deduplicate, rank, and limit the raw validated Step 17 retrieval
candidates while preserving required policy-family coverage.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 18 — Filter, deduplicate and rank retrieval results

## Scope

### Included

- Remove candidates below `RAG_MIN_RELEVANCE_SCORE`.
- Remove individually invalid, unapproved, or disallowed records.
- Rank accepted candidates deterministically by descending relevance.
- Deduplicate chunk IDs, normalized content, and content hashes.
- Remove the lower-ranked of highly overlapping adjacent chunks from the same
  document and section using a documented normalized-token ratio above 85%.
- Reserve the highest-ranked candidate from every represented required policy
  before filling remaining `RAG_MAX_CONTEXT_CHUNKS` slots.
- Extend `PolicyRetriever.retrieve(...)` with an optional required-policy scope
  while preserving existing Step 17 calls.

### Excluded

- Step 19 retrieval sufficiency decisions and conflicting-version/manifest
  sufficiency checks.
- Step 20 relevance-threshold calibration.
- Generation, prompts, orchestration, API, frontend, or logging.
- Chroma rebuilds, active-store swaps, policy changes, or embedding changes.

## Files to inspect

- `backend/app/ml/retriever.py` — Step 17 candidate creation and public API.
- `backend/app/ml/triage_types.py` — existing `RetrievedPolicy` contract.
- `backend/app/ml/rag_config.py` — threshold and context limits.
- `backend/app/ml/policy_registry.py` — authoritative policy IDs.
- `backend/app/ml/risk_router.py` — allowed and required scope semantics.
- `backend/tests/test_retriever.py` — Step 17 compatibility coverage.
- `backend/tests/test_vector_store_integration.py` — live temporary-store
  caller and score smoke check.

## Files expected to change

- Update `backend/app/ml/retriever.py`.
- Update `backend/tests/test_retriever.py`.
- Add `backend/tests/test_retrieval_rules.py`.
- Update `backend/tests/test_vector_store_integration.py` only if the final
  context limit changes its assertions.
- Update this plan and `docs/IMPLEMENTATION_STATUS.md`.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — read only through the
  baseline verifier.
- `backend/app/data/chromadb_store/` — no rebuild, swap, or write is required.

## Compatibility constraints

- Preserve all Steps 0–17 public interfaces and existing two-argument
  `PolicyRetriever.retrieve(...)` calls.
- Reuse `RetrievedPolicy`, `RagSettings`, `KNOWN_POLICY_IDS`, and the existing
  Step 17 candidate-integrity boundary.
- Required policy IDs must be unique, known, allowed, and representable within
  the configured global context limit.
- Filtering must be deterministic and must never allow a rejected candidate
  into later prompt context.
- Empty accepted results are valid Step 18 output; Step 19 will decide whether
  retrieval is sufficient.

## Implementation milestones

1. [x] Inspect the complete Step 18 roadmap, current retriever, result type,
   router scopes, callers, tests, and settings.
2. [x] Implement deterministic validation, thresholding, ranking,
   deduplication, overlap removal, diversity selection, and context limiting.
3. [x] Add focused fake/data-only tests and preserve Step 17 coverage.
4. [x] Run compilation, focused/full unit tests, applicable live integration,
   and repository validation.
5. [x] Update continuity records and stop before Step 19.

## Acceptance criteria

- [x] Candidates below the configured threshold are removed individually.
- [x] Invalid, unapproved, and disallowed records cannot enter final context.
- [x] Duplicate IDs, normalized text, and content hashes retain only the
  highest-ranked candidate.
- [x] Adjacent same-section chunks with normalized-token overlap above 85%
  retain only the higher-ranked chunk.
- [x] Non-adjacent or different-section chunks are not removed by overlap
  alone.
- [x] Required policy families are represented when accepted candidates exist.
- [x] Final output is deterministically relevance-ranked and within the global
  context limit.
- [x] Existing callers that omit `required_policy_ids` remain compatible.

## Testing plan

- Focused:
  `python -m pytest -q tests/test_retriever.py tests/test_retrieval_rules.py`
- Non-integration: `python -m pytest -q -m "not integration"`
- Integration: `python -m pytest -q -m integration`
- Validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Ollama: not required for implementation or unit tests.
- Chroma: not required for implementation or unit tests.
- Existing integration coverage uses an already-running approved loopback
  Ollama and a pytest temporary Chroma store only; the active store is not
  rebuilt or swapped.

## Rollback considerations

- Step 18 changes tracked source, tests, and continuity documents only.
- No persistent data or runtime store migration is involved.
- Rollback consists of reverting only the Step 18 edits while preserving the
  uncommitted Step 17 implementation and unrelated user changes.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Add `required_policy_ids` as an optional keyword to preserve the current
  Step 17 and documented future pipeline call shape.
- Keep filtering as a public pure function so all Step 18 behavior is tested
  without Ollama or Chroma.
- Define normalized-token overlap as multiset intersection divided by the
  smaller token count; only adjacent chunk indices in the same document and
  section are compared.
- Select required-family representatives before filling remaining slots, then
  return the chosen set in deterministic descending relevance order.

## Unresolved risks

- The 0.85 overlap rule and configured relevance threshold are initial values;
  Step 20 must calibrate retrieval quality without changing Step 18 safety
  invariants.

## Final results

Files created:

- `backend/tests/test_retrieval_rules.py`
- `docs/plans/phase-2-step-18.md`

Files updated:

- `backend/app/ml/retriever.py`
- `backend/tests/test_retriever.py`
- `backend/tests/test_vector_store_integration.py`
- `docs/IMPLEMENTATION_STATUS.md`

Interfaces added or changed:

- Added `filter_retrieval_candidates(...)`.
- Added `normalized_token_overlap_ratio(...)`.
- Added `ADJACENT_CHUNK_OVERLAP_THRESHOLD`.
- Extended `PolicyRetriever.retrieve(...)` with optional
  `required_policy_ids=()` while preserving existing calls.

Commands run from `backend/`:

- `.\venv\Scripts\python.exe -m compileall app scripts tests` — final run
  exited 0.
- `.\venv\Scripts\python.exe -m pytest -q tests/test_retriever.py tests/test_retrieval_rules.py`
  — initial run `48 passed in 22.35s`; final run after malformed-metadata
  hardening `49 passed in 21.42s`.
- `.\venv\Scripts\python.exe -m pytest -q -m "not integration"` —
  `171 passed, 1 deselected in 35.96s`.
- `.\venv\Scripts\python.exe -m pytest -q -m integration` —
  `1 passed, 171 deselected, 3 warnings in 50.91s`; the warnings are Chroma's
  existing legacy embedding-function configuration deprecation warning.
- Read-only active-store Step 18 smoke command — exit code 0; four accepted,
  unique, thresholded, context-limited `card_delivery` chunks returned.
- `.\venv\Scripts\python.exe scripts\verify_phase1_baseline.py` — five
  protected artifacts passed.
- `.\venv\Scripts\python.exe scripts\validate_policies.py` — four approved
  policies passed.
- `.\venv\Scripts\python.exe -m pip check` — no broken requirements.

Not run:

- No applicable checks were omitted.
- No active-store rebuild or swap was run because Step 18 changes no stored
  embeddings, metadata, policies, or manifest facts.

Remaining work:

- Step 19 — determine retrieval sufficiency.
