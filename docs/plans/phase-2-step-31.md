# Phase 2 Step 31 Execution Plan

## Objective

Add safe, read-only live integration commands for the active retriever and the
complete local classifier-to-answer pipeline, with service-free unit tests for
their validation and reporting logic.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 31 — Add live integration tests

## Scope

### Included

- Add `backend/scripts/test_retrieval.py` for active-manifest, active-Chroma,
  real-Nomic retrieval checks.
- Add `backend/scripts/test_rag_pipeline.py` for real classifier, router,
  active retrieval, actual grounding prompt, real structured Llama generation,
  validator, and final-answer checks.
- Report only the safe fields required by the roadmap.
- Add service-free focused tests using fakes for both command workflows.
- Restrict normal pytest discovery to `backend/tests/` so operator scripts
  named `test_*.py` are not collected as unit-test modules.

### Excluded

- Step 32 matrix documentation or implementation.
- Chroma rebuilds, swaps, writes, or temporary-store creation.
- Ollama startup, model pulls, or model changes.
- Classifier retraining or protected-model changes.
- Prompt, complete-policy, embedding-vector, digest, environment, or local-path
  output.

## Files to inspect

- `backend/tests/test_vector_store_integration.py` — existing temporary-store
  live coverage.
- `backend/tests/test_chat_model_integration.py` — current live model
  initialization check.
- `backend/tests/test_structured_generation_integration.py` — current real
  structured-output check.
- `backend/scripts/calibrate_retrieval.py` — validated dataset contracts and
  active-retriever construction patterns.
- `backend/scripts/check_ollama.py` and
  `backend/scripts/inspect_vector_store.py` — safe operator-command patterns.
- `backend/app/ml/classifier.py`, `risk_router.py`, `retriever.py`,
  `rag_pipeline.py`, `chat_model.py`, `grounding_prompt.py`,
  `structured_generation.py`, `output_validator.py`, and `triage_types.py` —
  authoritative interfaces used by the live flows.
- `backend/.env.example`, `backend/pytest.ini`, and
  `backend/requirements.txt` — live configuration and test discovery.

## Files expected to change

- `backend/scripts/test_retrieval.py` — new live active-store retrieval command.
- `backend/scripts/test_rag_pipeline.py` — new live end-to-end pipeline command.
- `backend/tests/test_live_retrieval_script.py` — service-free command tests.
- `backend/tests/test_live_rag_pipeline_script.py` — service-free reporting and
  end-to-end command tests.
- `backend/pytest.ini` — constrain pytest discovery to the test package.
- `docs/IMPLEMENTATION_STATUS.md` — Step 31 continuity record.
- This plan — progress and exact verification results.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — load and verify only.
- `backend/app/data/chromadb_store/` — read-only access only.
- `backend/.env` and local Ollama data — use through validated settings only;
  never print or modify.

## Compatibility constraints

- Preserve every existing application public interface.
- Use `get_retriever()`, `classify_intent()`, `risk_router`,
  `FintechRagPipeline`, `get_chat_model()`, and `OutputValidator` directly.
- Instrument LLM and validator calls through transparent wrappers rather than
  changing `PipelineAnswer` or production pipeline metadata.
- Keep unsupported routing deterministic. The raw unsupported retrieval probe
  uses an unrelated query that the configured threshold rejects; known
  Banking77-like unsupported queries remain protected primarily by the router.
- Do not expose hidden prompts or retrieved policy bodies in reports.

## Implementation milestones

1. [x] Read documentation and inspect existing live tests, source interfaces,
   callers/imports, configuration, and active prerequisites.
2. [x] Implement safe injectable live retrieval command and unit tests.
3. [x] Implement safe injectable live pipeline command and unit tests.
4. [x] Run focused unit, live, non-integration, and repository validation
   checks; update continuity and stop before Step 32.

## Acceptance criteria

- [x] Expected policies appear and no out-of-scope policy appears.
- [x] Required policy families are represented.
- [x] An unrelated unsupported probe returns no accepted chunk at the
  configured threshold.
- [x] Relevant-query score direction exceeds an unrelated query in the same
  policy scope.
- [x] Initial and replacement delivery retrieve different policy families.
- [x] The live pipeline uses the protected classifier, real router, active
  retriever, real Llama, actual prompt, structured output, and validator.
- [x] Pipeline reports contain every roadmap field and no hidden prompt or
  complete policy text.
- [x] Deterministic routes do not call the LLM or validator.
- [x] Live commands fail closed with nonzero exit status.

## Testing plan

- Unit: `python -m pytest -q tests/test_live_retrieval_script.py
  tests/test_live_rag_pipeline_script.py`
- Related unit: `python -m pytest -q tests/test_retriever.py
  tests/test_rag_pipeline.py tests/test_classifier.py
  tests/test_output_validator.py`
- Integration: `python scripts/test_retrieval.py`,
  `python scripts/test_rag_pipeline.py`, and
  `python -m pytest -q -m integration`
- Non-integration: `python -m pytest -q -m "not integration"`
- Validation: `python -m compileall app scripts tests`,
  `python scripts/check_ollama.py`,
  `python scripts/inspect_vector_store.py`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Ollama: already-running approved loopback service with `llama3.2:3b` and
  `nomic-embed-text`.
- Chroma: existing active schema-version-2 cosine store and compatible
  manifest; read-only access only.
- Protected classifier: existing verified local model; inference only.

## Rollback considerations

- The commands perform no persistent writes and require no rollback.
- Source rollback is limited to the two scripts, their unit tests, pytest
  discovery configuration, this plan, and continuity documentation.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Use an explicitly unrelated cooking query for the raw unsupported threshold
  probe because current calibration evidence shows several banking-like
  unsupported queries still have high vector similarity and must remain gated
  by the deterministic router.
- Use transparent wrappers to record real structured-model invocations and
  validator outcomes without changing production contracts.
- Run only two grounded-generation pipeline probes to exercise the complete
  LLM path while keeping the live command bounded; deterministic probes cover
  urgent, critical, clarification, static-refusal, and unsupported branches.
- Add `testpaths = tests` because the roadmap-mandated operator script names
  begin with `test_` and should not become pytest modules.

## Unresolved risks

- Live local-model output can vary across model/runtime upgrades even at
  temperature zero; validation and strict pass criteria fail closed.

## Final results

- Created `backend/scripts/test_retrieval.py`,
  `backend/scripts/test_rag_pipeline.py`,
  `backend/tests/test_live_retrieval_script.py`,
  `backend/tests/test_live_rag_pipeline_script.py`, and this plan.
- Modified `backend/pytest.ini` and `docs/IMPLEMENTATION_STATUS.md`.
- No application interface, environment, policy, active store, manifest,
  model, or protected classifier artifact was changed.
- `python -m pytest -q tests/test_live_retrieval_script.py
  tests/test_live_rag_pipeline_script.py`: 9 passed in 14.67 seconds.
- Focused and related six-module service-free run: 199 passed in 15.14
  seconds.
- `python scripts/test_retrieval.py`: exit code 0; all six live read-only
  retrieval invariants passed.
- The first `python scripts/test_rag_pipeline.py` run failed closed on the
  first probe because the original wording correctly routed to classifier
  clarification. The probe was changed to explicit initial-delivery wording.
- Final `python scripts/test_rag_pipeline.py`: exit code 0; seven probes passed,
  including two real grounded/validated generations and five deterministic
  no-LLM routes.
- `python -m pytest -q -m integration`: 3 passed, 460 deselected, 3 Chroma
  legacy-configuration deprecation warnings in 28.70 seconds.
- `python -m compileall app scripts tests`: exit code 0.
- `python -m pytest -q -m "not integration"`: 460 passed, 3 deselected in
  15.92 seconds.
- `python scripts/check_ollama.py`: all eight read-only checks passed.
- `python scripts/inspect_vector_store.py`: active 67-record cosine store
  passed with no integrity failure.
- `python scripts/verify_phase1_baseline.py`: five protected artifacts passed.
- `python scripts/validate_policies.py`: four approved policies passed.
- `python -m pip check`: no broken requirements.
- `git diff --check`: exit code 0 with no whitespace errors; final diff and
  status were inspected and unrelated pre-existing Phase 2 changes were
  preserved.
- No test was omitted. No destructive or active-store mutation command ran.
- Remaining work: Step 32. It was not started.

## Compact handoff

Step 31 is `COMPLETE_AND_VERIFIED`. Its read-only live retrieval and bounded
end-to-end pipeline checks, focused tests, and pytest discovery guard are in
place; all recorded verification passed. No production interface, protected
model, policy, or active Chroma data changed. Continue with Step 32 only, while
retaining the live-model variability, Chroma deprecation warning, and
router-before-retrieval safety boundary documented above.
