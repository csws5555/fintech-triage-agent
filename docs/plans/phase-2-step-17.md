# Phase 2 Step 17 Execution Plan

## Objective

Add a fail-closed, policy-aware retriever that searches the existing active
cosine Chroma collection with the stripped customer message and a mandatory
approved-policy metadata filter.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 17 — Create the retriever

## Scope

### Included

- Validate the active schema-version-2 ingestion manifest against the current
  collection, embedding model and digest, cosine metric, exact Nomic prefixes,
  and chunk settings.
- Reject blank queries, empty policy scopes, and unknown policy IDs.
- Search with `similarity_search_with_score(...)`, `RAG_CANDIDATE_K`, and a
  mandatory `document_id` `$in` filter.
- Convert cosine distance to a clamped relevance score without relabeling the
  raw distance.
- Convert safe stored candidates to the existing `RetrievedPolicy` contract.
- Add fake-based unit coverage and a live temporary-store score-ordering smoke
  check.

### Excluded

- Step 18 threshold filtering, deduplication, reranking, policy-diversity, and
  final context limits.
- Step 19 retrieval sufficiency and Step 20 threshold calibration.
- Generation, prompting, orchestration, API, frontend, and logging work.
- Rebuilding or modifying the configured active Chroma store.

## Files to inspect

- `backend/app/ml/rag_config.py` — retrieval settings and active paths.
- `backend/app/ml/triage_types.py` — existing `RetrievedPolicy` contract.
- `backend/app/ml/policy_registry.py` — authoritative policy allowlist.
- `backend/app/ml/embeddings.py` — exact-once query prefixing.
- `backend/app/ml/ingest_policies.py` — manifest, digest, stable ID, and
  metadata contracts.
- `backend/tests/test_vector_store_integration.py` — existing temporary-store
  integration workflow.
- Installed `langchain-chroma==1.1.0` source — score and filter behavior.

## Files expected to change

- Add `backend/app/ml/retriever.py`.
- Add `backend/tests/test_retriever.py`.
- Update `backend/tests/test_vector_store_integration.py`.
- Update this plan and `docs/IMPLEMENTATION_STATUS.md`.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — read only through the
  baseline verifier; never train, resave, move, or delete.
- `backend/app/data/chromadb_store/` — read only for optional runtime
  retrieval; unit tests use fakes and integration uses a pytest temporary
  directory.

## Compatibility constraints

- Preserve every existing Steps 0–16 public interface.
- Keep `retrieve(query=..., allowed_policy_ids=...)` compatible with the future
  pipeline call documented in Step 25.
- Use `RetrievedPolicy` rather than adding a duplicate result contract.
- Use the shared `NomicRagEmbeddings`; do not prepend classifier intents or
  apply an embedding prefix in the retriever.
- Never issue an unfiltered query as a fallback.
- Fail closed on malformed manifests, model-digest lookup failures, invalid
  stored metadata, non-finite distances, or filter leakage.

## Implementation milestones

1. [x] Inspect the roadmap, repository guidance, current interfaces, callers,
   installed wrapper behavior, and service/storage dependencies.
2. [x] Implement manifest validation, filtered retrieval, score conversion,
   and safe candidate conversion.
3. [x] Add focused unit tests and live temporary-store smoke coverage.
4. [x] Run applicable compilation, test, integration, and validation commands.
5. [x] Update continuity records and stop before Step 18.

## Acceptance criteria

- [x] Blank queries and empty/unknown policy scopes fail before vector search.
- [x] The exact stripped customer query reaches the shared embedding adapter.
- [x] Every search has the required `document_id: {"$in": ...}` filter.
- [x] Manifest mismatches for every Step 17 field fail before search.
- [x] Cosine distances convert with `max(0, min(1, 1 - distance))`.
- [x] Returned candidates use `RetrievedPolicy` and retain stable chunk IDs.
- [x] Invalid, unapproved, disallowed, or malformed stored records fail closed.
- [x] No Step 18 threshold, deduplication, or final-context behavior is added.

## Testing plan

- Unit: `python -m pytest -q tests/test_retriever.py`
- Related unit:
  `python -m pytest -q tests/test_embedding_adapter.py tests/test_ingest_policies.py tests/test_retriever.py`
- Non-integration: `python -m pytest -q -m "not integration"`
- Integration: `python -m pytest -q -m integration`
- Validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Ollama: not required for unit tests. The integration test requires an
  already-running approved loopback Ollama with `nomic-embed-text`; the code
  does not start it.
- Chroma: unit tests use a fake vector store. Integration creates, activates,
  reopens, queries, and removes only a pytest temporary store.

## Rollback considerations

- Step 17 adds source/tests/documentation only.
- Ordinary retrieval opens the configured active store read-only from the
  application perspective; it does not rebuild or swap directories.
- Reverting Step 17 consists of removing the new source/test files and
  reverting only the Step 17 integration and continuity edits.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Use installed `langchain-chroma==1.1.0` with
  `create_collection_if_not_exists=False`; inspected source passes `filter`
  directly to Chroma's `where` argument and returns raw distances.
- Validate the current local embedding-model digest through the existing
  Ollama helper when constructing the cached runtime retriever.
- Treat invalid stored candidates as storage-integrity failures. Step 18 will
  add ranking/filtering rules for otherwise valid candidates, not tolerate a
  corrupted approved store.

## Unresolved risks

- Chroma emits its existing legacy embedding-function configuration
  deprecation warning when the integration test reopens the store. Retrieval
  behavior remains verified with the pinned versions.
- Step 18 must still calibrate and apply thresholds, deduplication, ranking,
  policy diversity, and context limits; Step 17 intentionally returns raw
  validated candidates.

## Final results

Files created:

- `backend/app/ml/retriever.py`
- `backend/tests/test_retriever.py`
- `docs/plans/phase-2-step-17.md`

Files updated:

- `backend/tests/test_vector_store_integration.py`
- `docs/IMPLEMENTATION_STATUS.md`

Interfaces added:

- `PolicyRetrievalError`
- `PolicyRetriever`
- `PolicyRetriever.retrieve(...)`
- `cosine_distance_to_relevance(...)`
- `validate_retrieval_manifest(...)`
- `get_retriever()`

Commands run from `backend/`:

- `.\venv\Scripts\python.exe -m compileall app scripts tests` — exit code 0.
- `.\venv\Scripts\python.exe -m pytest -q tests/test_retriever.py` —
  `28 passed in 83.81s`.
- `.\venv\Scripts\python.exe -m pytest -q tests/test_embedding_adapter.py tests/test_ingest_policies.py tests/test_retriever.py`
  — `85 passed in 11.67s`.
- `.\venv\Scripts\python.exe -m pytest -q -m "not integration"` —
  `150 passed, 1 deselected in 32.88s`.
- `.\venv\Scripts\python.exe -m pytest -q -m integration` —
  `1 passed, 150 deselected, 3 warnings in 25.25s`; the warnings are Chroma's
  existing legacy embedding-function configuration deprecation warning.
- `.\venv\Scripts\python.exe scripts\verify_phase1_baseline.py` — five
  protected artifacts passed.
- `.\venv\Scripts\python.exe scripts\validate_policies.py` — four approved
  policies passed.
- `.\venv\Scripts\python.exe -m pip check` — no broken requirements.
- Read-only active-store smoke command using `get_retriever()` — exit code 0;
  eight approved `card_delivery` candidates returned through the filtered
  runtime path.

Not run:

- No checks were omitted.
- The active Chroma store was not rebuilt or swapped because Step 17 is
  retrieval-only.

Remaining work:

- Step 18 — filter, deduplicate, and rank retrieval results.
