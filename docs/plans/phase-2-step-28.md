# Phase 2 Step 28 Execution Plan

## Objective

Add a read-only, fail-closed vector-store inspection command that reports the
safe manifest and collection facts required by the roadmap, detects unsafe or
inconsistent stored records, and never prints policy bodies or absolute local
paths.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 28 — Add vector-store inspection
- Steps 15–16 — Existing Chroma configuration, record validation, and manifest
- Steps 17–19 — Existing runtime-manifest and approved-record constraints

## Scope

### Included

- Create `backend/scripts/inspect_vector_store.py`.
- Load and validate the active schema-version-2 ingestion manifest.
- Open the configured active Chroma collection without creating or changing it.
- Read IDs, metadata, one embedding sample, collection count, and collection
  configuration through public APIs.
- Print every Step 28 summary field without printing stored documents.
- Detect duplicate IDs/content hashes, unapproved/unknown records, missing
  metadata, unsafe source paths, collection/manifest mismatches, and
  runtime-ingestion manifest mismatches.
- Exit nonzero for every mandated integrity failure and malformed/unsafe state.
- Add focused fake-based unit tests that do not require live Chroma or Ollama.

### Excluded

- Rebuilding, repairing, activating, moving, or deleting any Chroma store.
- Starting or contacting Ollama.
- Loading or changing the protected classifier.
- Printing policy bodies, embeddings, secrets, environment contents, absolute
  paths, or private runtime data.
- Step 29 evaluation-dataset work.

## Files to inspect

- `backend/app/ml/ingest_policies.py` — manifest, metadata, Chroma, and package
  validation contracts.
- `backend/app/ml/rag_config.py` — authoritative runtime settings and paths.
- `backend/app/ml/policy_loader.py` — approved-policy loading and hashes.
- `backend/app/ml/policy_registry.py` — authoritative known policy IDs.
- `backend/app/ml/retriever.py` — active manifest and stored-record constraints.
- `backend/scripts/rebuild_vector_store.py` and
  `backend/scripts/check_ollama.py` — safe direct-script conventions.
- Related ingestion/retrieval tests and every caller/import found by search.

## Files expected to change

- Create `backend/scripts/inspect_vector_store.py`.
- Create `backend/tests/test_inspect_vector_store.py`.
- Create this plan.
- Update `docs/IMPLEMENTATION_STATUS.md`.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — verify only; never modify.
- `backend/app/data/chromadb_store/` — open read-only; never rebuild or mutate.
- Chroma staging/backup directories — do not access or mutate.
- `backend/.env`, local Ollama data, and policy bodies — never print or modify.

## Compatibility constraints

- Preserve all existing Step 0–27 application and operator interfaces.
- Reuse strict manifest/policy/settings validation rather than create another
  configuration source.
- Use only Chroma public read operations and never request stored documents.
- Render the active path relative to `backend/`, not as an absolute user path.
- Treat unavailable or malformed collection configuration/metadata as failure.
- Keep the test seam injectable without requiring a live Chroma or Ollama
  service.

## Implementation milestones

1. [x] Read required documentation, the complete Step 28 section, relevant
   prior plan, implementation, tests, callers, imports, and configuration.
2. [x] Implement the read-only inspection report and CLI.
3. [x] Add fake-based success, mismatch, safety, and output tests.
4. [x] Run focused/full checks and the live read-only inspector when available.
5. [x] Update continuity records, inspect final diff/status, and stop before
   Step 29.

## Acceptance criteria

- [x] Every roadmap field is printed using safe deterministic formatting.
- [x] No collection documents, embedding values, secrets, or absolute paths are
  printed.
- [x] Manifest/collection count mismatch fails.
- [x] Duplicate IDs fail.
- [x] Unapproved and unknown-policy records fail.
- [x] Collection name, metric, or dimensions differing from the manifest fail.
- [x] Runtime ingestion settings, approved policies, or package versions
  differing from the manifest fail.
- [x] Missing/malformed metadata and unsafe source paths fail closed.
- [x] Duplicate content hashes are reported.
- [x] The active store is not created or modified.

## Testing plan

- Focused unit:
  `python -m pytest -q tests/test_inspect_vector_store.py`
- Non-integration:
  `python -m pytest -q -m "not integration"`
- Live read-only Chroma:
  `python scripts/inspect_vector_store.py`
- Validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Ollama: not required; the manifest digest is inspected, not refreshed.
- Chroma: required only for the live read-only command; the configured active
  store must already exist and must not be rebuilt or swapped.
- Protected classifier: not required and must not be loaded.

## Rollback considerations

- The command performs no persistent writes or service changes.
- Rollback removes the new script, tests, and plan and reverts only Step 28
  continuity notes.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Report the active store as `app/data/chromadb_store` (or another safe
  repository-relative path) so the required path field does not expose a user
  directory.
- Use the manifest's recorded embedding-model digest for runtime validation;
  Step 28 is store inspection and does not need a live Ollama inventory call.
- Read only IDs, metadata, and one embedding sample. Stored policy documents are
  neither requested nor printed.
- Treat missing metadata and unsafe source paths as integrity failures in
  addition to the roadmap's explicitly mandated failures.

## Unresolved risks

- None for Step 28. Future live inspections require the existing active Chroma
  store to be present and readable, but do not require Ollama.

## Final results

- Created `backend/scripts/inspect_vector_store.py`,
  `backend/tests/test_inspect_vector_store.py`, and this plan.
- Modified `docs/IMPLEMENTATION_STATUS.md`.
- The first sandboxed compile/focused-test command could not launch the virtual
  environment's base interpreter; the approved rerun compiled successfully.
- The first focused run found two failures because valid blank Markdown header
  metadata was treated as malformed. The check was corrected to preserve the
  existing chunk contract.
- Final `python -m pytest -q tests/test_inspect_vector_store.py`:
  15 passed in 23.40 seconds.
- Final `python -m compileall app scripts tests`: exit code 0.
- `python -m pytest -q -m "not integration"`:
  436 passed, 3 deselected in 34.05 seconds.
- The first sandboxed live inspector invocation could not launch the virtual
  environment's base interpreter; the approved rerun passed.
- `python scripts/inspect_vector_store.py`: exit code 0; the active store
  reported 67/67 chunks, cosine configuration, 768 dimensions, four policy
  sources, no unsafe records, no manifest mismatches, and a PASS result.
- `python scripts/verify_phase1_baseline.py`: five protected artifacts passed.
- `python scripts/validate_policies.py`: four approved policy files passed.
- `python -m pip check`: no broken requirements.
- Ollama-dependent and store-rebuild integration tests were not run because
  Step 28 contacts no Ollama service and performs no rebuild or store mutation.
- No environment, model, policy, manifest, or vector-store data was modified.
- Remaining work: Step 29. It was not started.
