# Phase 2 Step 21 Execution Plan

## Objective

Create a lazy, validated local `ChatOllama` adapter configured exclusively from
the existing allowlisted loopback settings, ready for later prompt and
structured-output steps without invoking generation in Step 21.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 21 — Create the local chat model

## Scope

### Included

- Construct `ChatOllama` with the configured model, endpoint, temperature,
  context size, output limit, initialization validation, and timeout.
- Revalidate `RagSettings` before constructing the client.
- Cache one process-wide client lazily.
- Fail closed with a stable local error when construction or provider
  validation fails.
- Verify the returned object supports the invocation, streaming, and
  structured-output interfaces needed by later steps.
- Add fake-based unit tests and a live initialization-only integration test.

### Excluded

- Step 22 grounding prompts.
- Step 23 structured response schemas or `.with_structured_output(...)` calls.
- Step 24 output validation and Step 25 pipeline gating.
- Any customer query, policy context, generation request, or streaming output.
- Ollama startup, model pulls, Chroma access, classifier loading, or store
  mutation.

## Files to inspect

- `backend/app/ml/rag_config.py` — validated local-only model and runtime
  parameters.
- `backend/app/ml/embeddings.py` — existing lazy local-provider adapter pattern.
- `backend/app/ml/triage_types.py` — future structured-output boundary.
- Installed `langchain_ollama.ChatOllama` constructor and model fields.
- Existing configuration, embedding, and integration tests.

## Files expected to change

- Create `backend/app/ml/chat_model.py`.
- Create `backend/tests/test_chat_model.py`.
- Create `backend/tests/test_chat_model_integration.py`.
- Update this plan and `docs/IMPLEMENTATION_STATUS.md`.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — checksum verification only.
- `backend/app/data/chromadb_store/` — not accessed by Step 21.

## Compatibility constraints

- Preserve every Step 0–20 public interface.
- Reuse `RagSettings`, `settings`, and `validate_rag_settings(...)`.
- Use only the configured allowlisted `llama3.2:3b` at an approved loopback
  endpoint; never substitute a cloud or alternate model.
- Importing the module must not contact Ollama.
- Unit tests must not contact Ollama or Chroma.
- Do not expose provider exception details, endpoints, credentials, prompts,
  local paths, or model data in stable errors.

## Implementation milestones

1. [x] Read the complete Step 21 roadmap and inspect configuration, provider
   API, imports, callers, tests, and service dependencies.
2. [x] Implement the lazy validated local chat-model adapter.
3. [x] Add fake-based unit tests and live initialization-only coverage.
4. [x] Run compilation, focused/full tests, live integration, and repository
   validations.
5. [x] Update continuity records and stop before Step 22.

## Acceptance criteria

- [x] Every roadmap constructor argument is passed exactly once.
- [x] Invalid settings fail before the provider factory is called.
- [x] Provider initialization failures are wrapped in a stable local error.
- [x] Malformed provider objects are rejected.
- [x] `get_chat_model()` caches one successfully validated client.
- [x] Unit tests require no live services.
- [x] Live initialization confirms the approved configured model is installed.
- [x] No prompt, generation, Chroma, classifier, or persistent-store work is
  introduced.

## Testing plan

- Focused: `python -m pytest -q tests/test_chat_model.py`
- Non-integration: `python -m pytest -q -m "not integration"`
- Integration: `python -m pytest -q -m integration`
- Live smoke:
  `python -c "from app.ml.chat_model import get_chat_model; ..."`
- Validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Unit tests: no Ollama, Chroma, or classifier.
- Integration/smoke: running approved loopback Ollama with installed
  `llama3.2:3b`; initialization only, no customer prompt or generated answer.
- Chroma: not required.

## Rollback considerations

- Step 21 changes Python source, tests, and continuity documentation only.
- No persistent runtime data or environment settings change.
- Rollback removes the Step 21 adapter/tests/plan while preserving uncommitted
  Steps 17–20 and unrelated user work.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Use a dedicated `chat_model.py` adapter rather than creating the later
  `rag_pipeline.py` early.
- Keep model creation lazy through `get_chat_model()` so imports and
  deterministic routes do not contact Ollama.
- Validate the minimal future-compatible chat-model surface without invoking
  `.with_structured_output(...)` until Step 23.

## Unresolved risks

- Live initialization depends on the locally installed model and Ollama
  availability; provider behavior may change on a future dependency upgrade.

## Final results

- Created `backend/app/ml/chat_model.py`,
  `backend/tests/test_chat_model.py`,
  `backend/tests/test_chat_model_integration.py`, and this plan.
- Modified `docs/IMPLEMENTATION_STATUS.md`.
- Compilation passed.
- Focused fake-based tests passed: 7.
- Non-integration tests passed: 199, with 2 integration tests deselected.
- Live integration passed: 2, with 199 tests deselected and three Chroma
  deprecation warnings from the pre-existing temporary-store test.
- The direct initialization-only smoke check passed for the approved
  `llama3.2:3b` model.
- Policy validation, protected Phase 1 baseline verification, and dependency
  validation passed.
- No prompt was built, no generation request was sent, and no Chroma or model
  data was modified.
- Remaining work: Step 22. It was not started.
