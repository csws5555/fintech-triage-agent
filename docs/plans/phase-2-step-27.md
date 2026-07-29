# Phase 2 Step 27 Execution Plan

## Objective

Add a fail-closed Ollama health-check command that verifies the configured
loopback service, approved installed models and digests, one non-empty test
embedding, and one non-empty short generation without printing model output or
embedding contents.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 27 — Add Ollama health checks
- Step 5 — Existing loopback, allowlist, cloud-tag, and timeout configuration
- Step 15 — Existing local Ollama model inventory/digest conventions

## Scope

### Included

- Create `backend/scripts/check_ollama.py`.
- Revalidate the complete runtime configuration before contacting Ollama.
- Inspect installed models once through the configured loopback client.
- Require the configured chat and embedding models exactly once, accepting
  Ollama's `:latest` spelling only for an untagged configured model.
- Require valid SHA-256 digests for both installed models.
- Call Ollama's `/api/embed` operation with the approved embedding model and
  exact Nomic query prefix.
- Run a bounded, deterministic generation probe with the approved chat model.
- Reject malformed, empty, duplicate, unapproved, or cloud-tagged results.
- Print only the roadmap PASS summary and safe failure messages.
- Add focused fake-based tests that require no live service.

### Excluded

- Starting, stopping, pulling, deleting, or updating Ollama models.
- Chroma access, inspection, rebuild, activation, or persistent-store changes.
- Classifier loading or inference.
- Changes to policies, ingestion manifests, environment files, application
  orchestration, or any Step 28+ behavior.
- Printing digests, embeddings, generated probe text, provider payloads, or
  connection details.

## Files to inspect

- `backend/app/ml/rag_config.py` — authoritative loopback/model validation,
  allowlists, cloud-tag checks, and runtime limits.
- `backend/app/ml/ingest_policies.py` — current Ollama inventory, model-name
  matching, and digest conventions.
- `backend/app/ml/embeddings.py` — exact-once Nomic prefix and vector
  validation behavior.
- `backend/app/ml/chat_model.py` — approved chat-model settings and timeout
  behavior.
- `backend/scripts/*.py` — direct-execution and safe CLI conventions.
- Relevant tests and all Ollama imports/callers found by repository search.

## Files expected to change

- Create `backend/scripts/check_ollama.py`.
- Create `backend/tests/test_check_ollama.py`.
- Create this plan.
- Update `docs/IMPLEMENTATION_STATUS.md`.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — verify only; never modify.
- `backend/app/data/chromadb_store/` and staging/backup peers — no access or
  mutation.
- `backend/.env` and local Ollama data — read through existing settings/service
  APIs only; never print or modify.

## Compatibility constraints

- Preserve every existing Step 0–26 public interface.
- Reuse central `RagSettings` and `validate_rag_settings`; do not introduce a
  second configuration source.
- Use only the configured approved loopback endpoint and model names.
- Apply the configured Nomic query prefix exactly once to the health probe.
- Use the pinned `ollama==0.6.2` SDK interfaces.
- Health checks are read-only except for transient Ollama inference work.
- Any failed or malformed check returns a non-zero command status.

## Implementation milestones

1. [x] Read the required documentation, complete Step 27 section, prior active
   plan, related source/tests/configuration, imports, and callers.
2. [x] Implement the fail-closed health report and CLI summary.
3. [x] Add fake-based tests for success and every required failure boundary.
4. [x] Run compilation, focused/full tests, live health check when available,
   and repository validation commands.
5. [x] Update continuity records, inspect final diff/status, and stop before
   Step 28.

## Acceptance criteria

- [x] The command rejects a non-local endpoint before constructing a client.
- [x] Installed-model inspection succeeds and proves Ollama is reachable.
- [x] `llama3.2:3b` and `nomic-embed-text` are both installed exactly once.
- [x] Both configured models remain explicitly allowlisted and non-cloud.
- [x] Both installed records contain valid SHA-256 digests.
- [x] `/api/embed` returns exactly one non-empty vector.
- [x] Short generation returns a non-empty response.
- [x] Successful output contains every roadmap PASS line.
- [x] Output never contains embedding values, generated probe text, digests,
  provider payloads, secrets, or private paths.
- [x] Every failure exits non-zero and does not print a misleading PASS summary.

## Testing plan

- Focused unit:
  `python -m pytest -q tests/test_check_ollama.py`
- Non-integration:
  `python -m pytest -q -m "not integration"`
- Live Ollama:
  `python scripts/check_ollama.py`
- Integration: existing integration suite is not required because Step 27 has
  its own live command and does not alter application integration code.
- Validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Ollama: required only for the live command; it must already be running at
  the validated loopback URL with `llama3.2:3b` and `nomic-embed-text`
  installed. The command must not start or mutate the service.
- Chroma: not required and must not be opened or changed.
- Protected classifier: not required and must not be loaded.

## Rollback considerations

- Step 27 changes only a read-only script, tests, plan, and continuity status.
- No service, environment, model, manifest, policy, or store state is mutated.
- Rollback removes the new script, tests, and plan and reverts only the Step 27
  status notes.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Use the pinned Ollama Python client directly because its `embed` method maps
  to the roadmap-required `/api/embed` endpoint and allows one injectable fake
  seam for all service operations.
- Keep the command under `backend/scripts` rather than add an application
  module because health checking is an operator action, not request-path logic.
- Inspect installed models once and validate both records together so
  reachability, inspection, presence, uniqueness, and digest checks use one
  consistent service snapshot.
- Treat the untagged configured embedding model as matching Ollama's canonical
  `:latest` inventory name, consistent with existing ingestion behavior.

## Unresolved risks

- None for Step 27. Future runs of the live operator command still require the
  local service to be running with both approved models installed.

## Final results

- Created `backend/scripts/check_ollama.py`,
  `backend/tests/test_check_ollama.py`, and this plan.
- Modified `docs/IMPLEMENTATION_STATUS.md`.
- The first sandboxed compile/focused-test invocation could not launch the
  virtual environment's base interpreter. The approved rerun succeeded.
- `python -m compileall app scripts tests` passed with exit code 0.
- `python -m pytest -q tests/test_check_ollama.py` passed:
  27 tests in 0.63 seconds in the final run.
- The first sandboxed live-command invocation could not launch the virtual
  environment's base interpreter. The approved rerun succeeded.
- `python scripts/check_ollama.py` passed with all eight required PASS lines;
  it used the already-running loopback service and did not mutate Ollama or
  Chroma.
- `python -m pytest -q -m "not integration"` passed:
  421 tests, 3 deselected in 16.24 seconds in the final run.
- `python scripts/verify_phase1_baseline.py` passed: five protected artifacts.
- `python scripts/validate_policies.py` passed: four approved policies.
- `python -m pip check` passed: no broken requirements.
- The broader integration suite was not run because Step 27 changes no
  application or Chroma integration boundary and the dedicated live health
  command exercised both required Ollama endpoints.
- No environment, model, policy, manifest, or vector-store data was modified.
- Remaining work: Step 28. It was not started.
