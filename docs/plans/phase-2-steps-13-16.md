# Phase 2 Steps 13–16 Execution Plan

## Objective

Add deterministic, Markdown-aware policy chunking and stable IDs, then build a
local Nomic embedding adapter and a staged, rollback-capable Chroma ingestion
workflow with a validated manifest.

Steps 13–16 are implemented and verified. Step 17 remains `NOT_STARTED`.

## Active execution — Step 16

Status: complete and verified.

### Scope

Included:

- A typed schema-version-2 ingestion manifest built from actual policy,
  embedding, Ollama, Chroma, configuration, and package facts.
- Deterministic serialization apart from the UTC creation timestamp.
- Strict loading and staleness validation with exact required fields.
- Manifest creation inside the temporary store before activation.
- Manifest validation against both the temporary and reopened active store.
- Focused fake-based unit tests and live staged integration coverage.

Excluded:

- Step 17 retrieval interfaces or search behavior.
- Chat generation, prompting, orchestration, API, or frontend work.
- Treating chat-model changes as vector-store staleness.
- Committing the ignored runtime manifest or Chroma database.

### Files expected to change

- Update `backend/app/ml/ingest_policies.py`.
- Update `backend/scripts/rebuild_vector_store.py`.
- Update `backend/tests/test_ingest_policies.py`.
- Update `backend/tests/test_vector_store_integration.py`.
- Update this plan and `docs/IMPLEMENTATION_STATUS.md`.
- Generate, but do not commit,
  `backend/app/data/chromadb_store/ingestion_manifest.json`.

### Reused interfaces

- `RagSettings`, including the configured manifest path, local Ollama URL,
  approved embedding model, prefixes, collection, cosine metric, chunk
  settings, and staged directories.
- `PolicyDocument`, `load_approved_policies(...)`, `source_hash`, and reviewed
  policy version metadata.
- Step 13–15 chunking, stable IDs, `VectorStoreBuildResult`, staged activation,
  collection verification, and rollback behavior.
- Installed `ollama.Client.list()` model records and
  `importlib.metadata.version(...)`.

### Compatibility and safety decisions

- Existing Step 15 entry points remain callable; successful builds now include
  and require a validated manifest as the Step 16 compatibility change.
- Schema fields are exact; unknown, missing, malformed, path-bearing, stale, or
  fabricated values fail closed.
- The embedding dimension comes from the live embedding batch and is checked
  against reopened stored vectors.
- The embedding digest is selected from the exact configured model in the
  local Ollama installed-model response; it is never hard-coded.
- Source hashes and versions are derived from validated `PolicyDocument`
  objects, with deterministic key order.
- Package versions are read from the installed environment.
- The manifest is written atomically within the temporary directory, then
  travels with the staged store. The prior active store remains rollback
  protected until reopened store and manifest validation pass.
- No absolute paths, environment values, secrets, policy bodies, or model
  weights enter the manifest.

### Service requirements

Ollama: required for live digest lookup and real dimensions. It must already be
running at the approved loopback URL with `nomic-embed-text`; it is not started
by the implementation.

Chroma: unit tests use fakes or filesystem-only manifest fixtures. Live
integration uses pytest temporary directories. Updating the project runtime
manifest requires the existing stopped-client-gated staged rebuild.

Protected classifier: not loaded or modified; the final checksum validator only
reads its reviewed artifacts.

### Implementation milestones

1. [x] Inspect documentation, callers, installed Ollama response shape,
   package versions, and the live Step 15 store.
2. [x] Implement manifest contracts, generation, serialization, and validation.
3. [x] Integrate manifest checks into temporary build and reopened activation.
4. [x] Add mismatch, safety, serialization, and live consistency tests.
5. [x] Run the protected project rebuild and all repository checks.
6. [x] Record exact results and stop before Step 17.

### Testing plan

- Focused unit:
  `python -m pytest -q tests/test_ingest_policies.py`
- Non-integration:
  `python -m pytest -q -m "not integration"`
- Live temporary store:
  `python -m pytest -q -m integration`
- Protected project rebuild:
  `python scripts/rebuild_vector_store.py --confirm-clients-stopped`
- Repository validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

### Rollback

Manifest generation occurs only in the temporary store. Activation continues
to move the previous active store to backup only after temporary collection and
manifest verification. Any reopened collection or manifest mismatch triggers
the existing restoration path; backup removal occurs only after both pass.
These remain staged Windows directory moves, not a universal atomic operation.

### Final results

Runtime file generated and ignored:

- `backend/app/data/chromadb_store/ingestion_manifest.json`

Files updated:

- `backend/app/ml/ingest_policies.py`
- `backend/scripts/rebuild_vector_store.py`
- `backend/tests/test_ingest_policies.py`
- `backend/tests/test_vector_store_integration.py`
- this plan
- `docs/IMPLEMENTATION_STATUS.md`

Interfaces added:

- `IngestionManifest`
- `create_ingestion_manifest(...)`
- `validate_ingestion_manifest(...)`
- `write_ingestion_manifest(...)`
- `load_ingestion_manifest(...)`
- `get_local_embedding_model_digest(...)`
- `get_required_package_versions()`

Compatibility change:

- `VectorStoreBuildResult.manifest` carries the verified staged manifest.
- Successful `build_vector_store(...)` calls now create the manifest, and
  `verify_vector_store(...)` requires and revalidates it after reopen.

Commands run from `backend/`:

- `python -m compileall app scripts tests` — exit code 0.
- Final `python -m pytest -q tests/test_ingest_policies.py` —
  `46 passed in 10.48s`.
- Final `python -m pytest -q -m "not integration"` —
  `122 passed, 1 deselected in 15.27s`.
- `python -m pytest -q -m integration` —
  `1 passed, 122 deselected, 3 warnings in 36.07s`; warnings are Chroma's
  existing legacy embedding-function configuration deprecation warning.
- `python scripts/rebuild_vector_store.py --confirm-clients-stopped` —
  active store and manifest rebuilt and reopened successfully with 67 chunks
  and 768-dimensional embeddings.
- `python scripts/verify_phase1_baseline.py` — five protected artifacts passed.
- `python scripts/validate_policies.py` — four approved policies passed.
- `python -m pip check` — no broken requirements found.

Live result:

- The local Ollama installed-model response supplied the real embedding-model
  digest; the manifest stores it without exposing it in tracked files or
  command output.
- Temporary and reopened active collection/manifest validation passed.
- The active ignored manifest reports schema version 2, four source documents,
  67 chunks, 768 dimensions, and four required package versions.
- No temporary or backup Chroma directory remains after successful activation.

Tests not run:

- None.

Next step:

- Step 17 remains `NOT_STARTED`; no retriever work was started.

## Active execution — Step 15

Status: complete and verified.

### Scope

Included:

- A shared Nomic embedding adapter with exact-once document/query prefixes.
- Validated, explicitly cosine Chroma collection creation.
- Temporary-store build and verification using approved policy chunks.
- A stopped-client-gated temporary → backup → active swap with rollback.
- Focused fake-based unit tests and an opt-in live Ollama/temporary-Chroma test.

Excluded:

- The Step 16 ingestion manifest.
- Retrieval interfaces for application traffic.
- Generation, orchestration, API, or frontend work.
- Starting Ollama or mutating the active project store from ordinary tests.

### Files expected to change

- Add `backend/app/ml/embeddings.py`.
- Update `backend/app/ml/ingest_policies.py`.
- Add `backend/scripts/rebuild_vector_store.py`.
- Add `backend/tests/test_embedding_adapter.py`.
- Update `backend/tests/test_ingest_policies.py`.
- Add `backend/tests/test_vector_store_integration.py`.
- Add `backend/pytest.ini` to register the integration marker.
- Update this plan and `docs/IMPLEMENTATION_STATUS.md`.

### Reused interfaces

- `RagSettings` and its validated local endpoint, allowlisted model, prefixes,
  collection name, cosine metric, chunk settings, and staged directory paths.
- `PolicyDocument`, `load_approved_policies(...)`, and reviewed storage
  metadata.
- `PolicyChunk`, `split_policy_documents(...)`,
  `validate_policy_chunks(...)`, and stable chunk IDs.
- `langchain_core.embeddings.Embeddings` and the installed
  `langchain_ollama.OllamaEmbeddings`.
- Public `chromadb.PersistentClient`, collection, `close()`, and
  `clear_system_cache()` APIs from installed `chromadb==1.5.9`.

### Compatibility and safety decisions

- Existing Steps 0–14 public interfaces remain unchanged.
- Ingestion supplies precomputed vectors directly to Chroma so prefixes are
  applied by the one shared adapter exactly once.
- Stored metadata is revalidated as approved and path-safe before insertion
  and after reopening.
- Chroma's reported collection configuration must explicitly be cosine.
- Filesystem paths must be distinct sibling directories, and recursive
  removal is limited to validated temporary/backup paths.
- A project-store swap requires an explicit caller confirmation that the
  backend and all Chroma clients are stopped.
- Chroma clients are closed and their public system cache cleared before
  directory moves; the workflow does not claim moves are atomic on Windows.
- A pre-swap failure leaves the active store untouched. A post-swap failure
  preserves the failed replacement at the temporary path when possible and
  restores the prior active store.

### Service requirements

Ollama: required only for live integration and an actual rebuild. It must
already be running at the configured approved loopback endpoint with
`nomic-embed-text`; the implementation does not start it.

Chroma: unit tests use fakes. The integration test uses a pytest temporary
directory. The project store is touched only by the explicit rebuild command.

Protected classifier: not loaded; only the existing checksum verifier may read
it during final validation.

### Implementation milestones

1. [x] Inspect the roadmap, repository guidance, callers, installed APIs,
   store paths, and running local processes.
2. [x] Implement the adapter and validated temporary-store build/reopen checks.
3. [x] Implement and test the stopped-client-gated activation/rollback flow.
4. [x] Run applicable unit, integration, and repository validation commands.
5. [x] Record exact results and stop before Step 16.

### Testing plan

- Focused unit:
  `python -m pytest -q tests/test_embedding_adapter.py tests/test_ingest_policies.py`
- Non-integration:
  `python -m pytest -q -m "not integration"`
- Live temporary store:
  `python -m pytest -q -m integration`
- Repository validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

### Rollback

The rebuild stages all new data in the temporary directory. The previous active
directory is renamed to backup only after temporary verification. If activation
or reopened-store verification fails, the new active directory is moved back
to temporary and the backup is restored. The backup is deleted only after the
reopened active store passes. These are staged Windows directory moves, not a
filesystem-wide atomic transaction.

### Final results

Files created:

- `backend/app/ml/embeddings.py`
- `backend/scripts/rebuild_vector_store.py`
- `backend/tests/test_embedding_adapter.py`
- `backend/tests/test_vector_store_integration.py`
- `backend/pytest.ini`

Files updated:

- `backend/app/ml/ingest_policies.py`
- `backend/tests/test_ingest_policies.py`
- this plan
- `docs/IMPLEMENTATION_STATUS.md`

Interfaces added:

- `EmbeddingValidationError`
- `NomicRagEmbeddings`
- `build_embeddings(...)`
- `get_embeddings()`
- `VectorStoreBuildResult`
- `VectorStorePaths`
- `VectorStoreRebuildError`
- `build_vector_store(...)`
- `verify_vector_store(...)`
- `activate_staged_vector_store(...)`
- `rebuild_project_vector_store(...)`

Commands run from `backend/`:

- `python -m compileall app scripts tests` — exit code 0.
- `python -m pytest -q tests/test_embedding_adapter.py tests/test_ingest_policies.py`
  — `36 passed in 9.44s`.
- `python -m pytest -q -m "not integration"` —
  `101 passed, 1 deselected in 14.33s`.
- `python -m pytest -q -m integration` after the final integration-test update
  — `1 passed, 101 deselected, 3 warnings in 22.16s`; the warnings are
  Chroma's legacy embedding-function configuration deprecation warning.
- `python scripts/verify_phase1_baseline.py` — five protected artifacts passed.
- `python scripts/validate_policies.py` — four approved policies passed.
- `python -m pip check` — no broken requirements found.
- `python scripts/rebuild_vector_store.py --confirm-clients-stopped` —
  active store rebuilt and reopened successfully with 67 chunks and
  768-dimensional embeddings.

Live result:

- The configured loopback Ollama service and approved `nomic-embed-text` model
  produced embeddings successfully.
- The live test built, validated, activated, reopened, queried, and cleaned up
  a Chroma store under pytest's temporary directory.
- After the user supplied the required stopped-client confirmation,
  `python scripts/rebuild_vector_store.py --confirm-clients-stopped` rebuilt
  and reopened the project active store successfully with 67 chunks and
  768-dimensional embeddings.

Next step:

- At the Step 15 completion point, Step 16 was `NOT_STARTED`; its completed
  execution record now appears above.

## Active execution — Steps 13–14

Status: complete and verified.

### Scope

Included:

- Step 13 Markdown-aware splitting of validated `PolicyDocument` objects.
- Step 14 deterministic content-based vector-record IDs.
- Focused unit tests and continuity-document updates.

Excluded:

- Nomic embeddings, Ollama calls, Chroma clients or stores, ingestion
  manifests, retrieval, and all Step 15+ implementation.

### Files expected to change

- Add `backend/app/ml/ingest_policies.py`.
- Add `backend/tests/test_ingest_policies.py`.
- Update this plan.
- Update `docs/IMPLEMENTATION_STATUS.md`.

### Reused interfaces

- `PolicyDocument` and its reviewed `storage_metadata()`.
- `load_policy_directory(...)` and duplicate-document validation.
- `normalize_chunk_content(...)` and `compute_content_hash(...)`.
- `settings.chunk_size` and `settings.chunk_overlap`.
- Installed `MarkdownHeaderTextSplitter` and
  `RecursiveCharacterTextSplitter`.

### Compatibility and safety decisions

- Existing loader, classifier, router, and typed-result interfaces remain
  unchanged.
- The new chunk contract will be immutable and will never contain
  `PolicyDocument.source_path`.
- Stable IDs will use document slug, normalized section-path slug, and the
  first 12 content-hash characters; `chunk_index` remains metadata only.
- Slug collisions between different logical identities will fail closed.
- Repeated identical content in the same section will receive deterministic
  occurrence suffixes.

### Service requirements

Ollama: not required and will not be called.

Chroma: not required and no runtime store will be read or modified.

Protected classifier: not required and will only be checksum-verified during
the final repository checks.

### Implementation milestones

1. [x] Inspect roadmap, repository guidance, dependencies, callers, and pinned
   splitter interfaces.
2. [x] Implement and verify Step 13 chunking.
3. [x] Implement and verify Step 14 stable IDs.
4. [x] Run the full applicable validation set and update continuity records.

### Final results

Files created:

- `backend/app/ml/ingest_policies.py`
- `backend/tests/test_ingest_policies.py`

Interfaces added:

- `PolicyChunk`
- `PolicyChunkingError`
- `split_policy_document(...)`
- `split_policy_documents(...)`
- `build_stable_chunk_id(...)`
- `validate_policy_chunks(...)`

Commands run from `backend/`:

- `python -m compileall -q app scripts tests` — exit code 0.
- `python -m pytest -q tests/test_ingest_policies.py` —
  `19 passed in 3.84s`.
- `python -m pytest -q -m "not integration"` —
  `84 passed in 11.91s`.
- `python scripts/validate_policies.py` — four approved policies passed.
- `python scripts/verify_phase1_baseline.py` — five protected artifacts passed.
- `python -m pip check` — no broken requirements found.

Not run:

- Integration tests: none are required or implemented for Steps 13–14.
- Ollama and Chroma checks: not required; no live service or persistent store
  was used.

Next step:

- At the Steps 13–14 completion point, Step 15 was `NOT_STARTED`; its completed
  execution record now appears above.

### Rollback

Steps 13–14 add tracked source/tests only and do not mutate persistent runtime
data. Rollback consists of removing the new files and reverting only the
Step 13–14 continuity-document edits; unrelated working-tree changes must
remain untouched.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 13 — Split policies into retrieval chunks
- Step 14 — Build stable vector-record IDs
- Step 15 — Create the embedding adapter and safely build Chroma
- Step 16 — Create the ingestion manifest

## Shared constraints

- Preserve `PolicyDocument`, loader functions, `compute_source_hash`, and
  `compute_content_hash` unless a tested roadmap requirement demands a change.
- Never modify the protected Phase 1 model.
- Never store absolute paths, secrets, unapproved policy metadata, or full
  `.env` values.
- Do not write into the active Chroma store until a temporary store has passed
  validation and smoke tests.
- Do not begin a later step until the current step's unit acceptance criteria
  pass and `docs/IMPLEMENTATION_STATUS.md` is updated.

## Step 13 — Markdown-aware policy chunking

Status: complete and verified.

### Files expected to change

- Add `backend/app/ml/ingest_policies.py`
- Add `backend/tests/test_ingest_policies.py`
- Update `docs/IMPLEMENTATION_STATUS.md`

### Inspect first

- `backend/app/ml/policy_loader.py`
- `backend/app/ml/rag_config.py`
- `backend/app/ml/triage_types.py`
- all four policy Markdown files
- installed `langchain-text-splitters==1.1.2` interfaces

### Implementation requirements

- Accept validated `PolicyDocument` objects rather than reparsing YAML.
- Split `PolicyDocument.body` with `MarkdownHeaderTextSplitter` using H1–H3
  metadata and `strip_headers=False`.
- Split oversized sections with `RecursiveCharacterTextSplitter` using
  `settings.chunk_size` and `settings.chunk_overlap`.
- Preserve heading text, discard blank chunks, and normalize whitespace only
  when meaning remains unchanged.
- Carry reviewed storage metadata and derive `header_1`, `header_2`,
  `header_3`, `section_path`, `chunk_index`, and `content_hash`.
- Do not add absolute `source_path` data to chunk metadata.

### Acceptance criteria

- All four approved policies produce at least one nonblank chunk.
- YAML front matter never appears in chunk content.
- Heading text remains in relevant chunks.
- Every chunk has complete safe metadata and a valid, content-derived SHA-256.
- Chunk ordering and indices are deterministic across identical runs.
- Every chunk respects configured size behavior, allowing only documented
  splitter edge cases for indivisible content.

### Unit tests

- H1–H3 metadata and section-path construction.
- Header retention.
- Oversized-section splitting and overlap.
- Blank-section removal.
- deterministic chunk ordering.
- absence of YAML and absolute paths.
- distinct source and content hashes.
- all four real policies chunk successfully.

Command:

```powershell
python -m pytest -q tests/test_ingest_policies.py
```

### Integration and services

Ollama: not required.

Chroma: not required.
Integration test: not required for this step.

### Stop boundary

Stop after chunking tests and the existing non-integration suite pass. Update
the status document to mark Step 13 accurately before implementing stable IDs.

## Step 14 — Stable content-based record IDs

Status: complete and verified.

### Files expected to change

- Update `backend/app/ml/ingest_policies.py`
- Update `backend/tests/test_ingest_policies.py`
- Update `docs/IMPLEMENTATION_STATUS.md`

### Inspect first

- Step 13 chunk contract and tests
- `compute_content_hash(...)` in `policy_loader.py`
- every current consumer/import of `ingest_policies.py`

### Implementation requirements

- Build IDs from document slug, normalized section-path slug, and the first 12
  characters of `content_hash`.
- Never use `document_id + chunk_index` as primary identity.
- Add a deterministic occurrence suffix such as `-02` only when identical
  content repeats in the same section.
- Retain `chunk_index` solely as inspection metadata.
- Reject blank, duplicate, path-bearing, or unsafe IDs before insertion.

### Acceptance criteria

- Identical inputs produce identical IDs across repeated runs.
- Inserting earlier unrelated content does not renumber unchanged
  content-based IDs.
- All IDs are nonblank, unique, path-free, and filesystem-independent.
- Repeated identical content receives stable occurrence suffixes.

### Unit tests

- deterministic slug normalization.
- stable rebuild IDs.
- duplicate occurrence suffixes.
- uniqueness validation.
- rejection of blank/path-bearing IDs.
- proof that `chunk_index` is not primary identity.

Command:

```powershell
python -m pytest -q tests/test_ingest_policies.py
```

### Integration and services

Ollama: not required.

Chroma: not required.
Integration test: not required for this step.

### Stop boundary

Stop after stable-ID tests and the full non-integration suite pass. Update the
status document before adding embeddings or persistent storage behavior.

## Step 15 — Nomic adapter and staged Chroma rebuild

Status: complete and verified.

### Files expected to change

- Add `backend/app/ml/embeddings.py`
- Update `backend/app/ml/ingest_policies.py`
- Add `backend/scripts/rebuild_vector_store.py`
- Add `backend/tests/test_embedding_adapter.py`
- Update `backend/tests/test_ingest_policies.py`
- Add integration tests only if their live prerequisites are explicit
- Update `docs/IMPLEMENTATION_STATUS.md`

### Inspect first

- installed `langchain-ollama==1.1.0`,
  `langchain-chroma==1.1.0`, and `chromadb==1.5.9` APIs
- `rag_config.py` paths, model allowlists, prefixes, and distance metric
- Step 13–14 chunk and stable-ID contracts
- `.gitignore` Chroma exclusions
- all prospective callers before defining public ingestion APIs

### Implementation requirements

- Implement `NomicRagEmbeddings` and cached `get_embeddings()`.
- Apply `search_document:` and `search_query:` exactly once, including when
  callers accidentally provide an already-prefixed string.
- Validate blank inputs consistently and return base embedding results without
  altering dimensions.
- Use one adapter for ingestion and future retrieval.
- Inspect the installed Chroma API and explicitly create cosine configuration;
  stop on incompatible configuration rather than using an unknown default.
- Implement the roadmap's temporary → verify → backup → activate → reopen →
  verify sequence.
- Release Chroma references before Windows directory moves.
- Restore the backup if activation or reopened-store checks fail.
- Remove the backup only after the new active store passes.

### Acceptance criteria

- Unit tests prove exact-once prefixing and input validation without Ollama.
- A live test embedding succeeds and determines dimensions dynamically.
- Temporary collection count equals inserted chunk count.
- Every stored record is approved, uses a stable ID, and contains safe metadata.
- Temporary and reopened active stores pass count and retrieval smoke checks.
- A simulated failure preserves or restores the previous active store.
- No operation claims filesystem-wide atomicity.

### Unit tests

- document and query prefixing exactly once.
- blank input behavior.
- base-adapter exception propagation.
- staged-path selection.
- pre-swap failure leaves active store untouched.
- post-swap failure invokes restoration.
- cosine configuration incompatibility fails closed.

Commands:

```powershell
python -m pytest -q tests/test_embedding_adapter.py tests/test_ingest_policies.py
python -m pytest -q -m "not integration"
```

### Integration and services

Ollama: required for live Nomic embedding tests; it must already be running at
the approved loopback URL. Do not start it implicitly.

Chroma: required in a temporary test directory for integration tests.

Active project Chroma store: must not be touched by ordinary tests.

Prospective integration command:

```powershell
python -m pytest -q -m integration
```

The rebuild script may run only after the user confirms the backend and all
Chroma clients are stopped.

### Stop boundary

Stop after unit tests pass and report whether live integration was run. Do not
swap the project store or proceed to manifest finalization unless temporary
ingestion, reopen checks, and rollback behavior have succeeded.

## Step 16 — Ingestion manifest

Status: complete and verified.

### Files expected to change

- Update `backend/app/ml/ingest_policies.py`
- Update `backend/scripts/rebuild_vector_store.py`
- Update `backend/tests/test_ingest_policies.py`
- Update/add integration tests for manifest/store consistency
- Generate, but do not commit,
  `backend/app/data/chromadb_store/ingestion_manifest.json`
- Update `docs/IMPLEMENTATION_STATUS.md`

### Inspect first

- actual Step 15 collection metadata and dimension result
- Ollama installed-model response containing the embedding-model digest
- installed package versions
- policy `source_hash` and version metadata
- `INGESTION_MANIFEST_PATH` in `rag_config.py`

### Implementation requirements

- Generate schema version 2 from actual runtime facts.
- Record collection name, cosine metric, embedding model and local digest,
  calculated dimensions, exact prefixes, chunk settings/strategies, source and
  chunk counts, UTC creation time, source hashes, policy versions, and relevant
  package versions.
- Use `source_document_count` and `chunk_count` with their exact meanings.
- Never hard-code dimensions or fabricate the Ollama digest.
- Validate the manifest against the reopened active collection before declaring
  ingestion successful.
- Treat chat-model information as optional and non-staleness-affecting.

### Acceptance criteria

- Manifest schema and required values validate deterministically.
- Source hashes and policy versions exactly match loaded policies.
- `chunk_count` equals the reopened Chroma count.
- Embedding dimensions come from a real vector.
- Embedding digest comes from the local Ollama model response.
- Prefix, metric, model, chunking, and stable-ID settings match the active store.
- Malformed, stale, or mismatched manifests fail closed.

### Unit tests

- required manifest fields and types.
- source-document count versus chunk count semantics.
- mismatch detection for counts, hashes, versions, prefixes, metric, model,
  dimensions, and ID strategy.
- deterministic serialization apart from timestamp.
- no absolute paths or secrets.

### Integration and services

Ollama: required to obtain the real local embedding-model digest and dimensions.

Chroma: required to validate manifest/store count and configuration.

Integration command:

```powershell
python -m pytest -q -m integration
```

### Stop boundary

Stop after the reopened active store and manifest pass their integration checks,
the old store is safely retained or removed according to the successful staged
flow, and `docs/IMPLEMENTATION_STATUS.md` records exact commands and results.
Do not begin Step 17 retrieval in the same task without a new or explicitly
continued plan.
