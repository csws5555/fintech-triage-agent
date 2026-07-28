# Phase 2 Step 23 Execution Plan

## Objective

Bind the approved local chat model to the existing
`GeneratedSupportResponse` schema and provide bounded, fail-closed structured
generation using only the Step 22 grounding messages.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 23 — Use structured internal output
- Step 24 — Create output validation (stop boundary)
- `personal project documentation/phase 2 flow chart.txt`
  — local structured-generation boundary

## Scope

### Included

- Bind the chat model with
  `with_structured_output(GeneratedSupportResponse)`.
- Invoke with validated Step 22 system/human messages.
- Retry once after an invocation or schema-result failure.
- Add stricter trusted output-format instructions on retry while retaining
  exactly the same approved customer and policy context.
- Return an approved deterministic fallback and stable internal failure code
  if binding or both invocations fail.
- Keep provider errors and malformed output private.

### Excluded

- Step 24 inspection or validation of generated answer text and flags.
- Step 25 routing, retrieval, sufficiency, or pipeline orchestration.
- Logging, persistence, API exposure, streaming, or asynchronous generation.
- Chroma access, classifier inference, policy ingestion, or model training.

## Files to inspect

- `backend/app/ml/chat_model.py` — approved lazy local model interface.
- `backend/app/ml/grounding_prompt.py` — trusted Step 22 message contract.
- `backend/app/ml/triage_types.py` — existing structured output schema.
- `backend/app/ml/response_templates.py` — approved deterministic fallback.
- Relevant chat-model, prompt, type, and future pipeline documentation/tests.

## Files expected to change

- Create `backend/app/ml/structured_generation.py`.
- Create `backend/tests/test_structured_generation.py`.
- Create `backend/tests/test_structured_generation_integration.py`.
- Update this plan and `docs/IMPLEMENTATION_STATUS.md`.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — verify only.
- `backend/app/data/chromadb_store/` — not accessed by Step 23.

## Compatibility constraints

- Preserve every Step 0–22 public interface.
- Reuse `get_chat_model`, Step 22 messages,
  `GeneratedSupportResponse`, and `insufficient_policy_response`.
- Never expose provider exceptions, malformed JSON, prompts, paths, model
  details, policy material, or customer data through failure results.
- Do not treat model-provided boolean flags as proof of answer safety.
- Do not retrieve or append policy context during retry.
- Unit tests require no Ollama, Chroma, classifier, or runtime store.

## Implementation milestones

1. [x] Read the complete Step 23 and Step 24 boundary and inspect relevant
   interfaces, imports, callers, tests, provider signatures, and services.
2. [x] Implement typed structured generation and bounded retry/fallback.
3. [x] Add focused fake-based tests and a narrow live Ollama integration test.
4. [x] Run compilation, focused/full tests, integration, and repository
   validations.
5. [x] Update continuity records and stop before Step 24.

## Acceptance criteria

- [x] The exact existing `GeneratedSupportResponse` schema is bound.
- [x] Successful structured results are returned without reinterpretation.
- [x] A first invocation/schema failure causes exactly one retry.
- [x] Retry retains identical approved policy and customer content.
- [x] Binding or retry exhaustion yields only the approved fallback and a
  stable internal failure code.
- [x] Provider errors and malformed raw output never enter the result.
- [x] Generated answer-text safety remains explicitly untrusted for Step 24.

## Testing plan

- Focused:
  `python -m pytest -q tests/test_structured_generation.py`
- Non-integration:
  `python -m pytest -q -m "not integration"`
- Integration:
  `python -m pytest -q tests/test_structured_generation_integration.py -m integration`
- Full integration regression:
  `python -m pytest -q -m integration`
- Validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Focused tests: no live services.
- Integration: an already-running loopback Ollama containing the allowlisted
  `llama3.2:3b` model.
- Chroma, the classifier, and the active vector store are not required.

## Rollback considerations

- Step 23 changes source, tests, and continuity documents only.
- No model, environment, policy, manifest, or vector-store data changes.
- Rollback removes the three Step 23 files and this plan's continuity entries
  while preserving Step 22 and unrelated user work.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Return a typed outcome so later orchestration can distinguish a real model
  result from an approved fallback without adding fields to the roadmap's
  existing model-output schema.
- Retry only invocation/schema-result failures. If structured binding cannot
  be constructed, fail closed immediately because there is no schema-bound
  runnable to invoke safely.
- Preserve model flags as untrusted data; Step 24 must inspect the answer text
  independently.

## Unresolved risks

- Real structured generation depends on local Ollama/provider schema support.
- A schema-valid response can still contain unsafe answer text; Step 24 remains
  mandatory before any model answer is customer-visible.

## Final results

- Created `backend/app/ml/structured_generation.py`,
  `backend/tests/test_structured_generation.py`,
  `backend/tests/test_structured_generation_integration.py`, and this plan.
- Modified `docs/IMPLEMENTATION_STATUS.md`.
- Compilation passed.
- Focused fake-based tests passed: 19.
- Non-integration tests passed: 236, with 3 integration tests deselected.
- The isolated live Step 23 generation test passed: 1.
- The full integration suite passed: 3, with 236 tests deselected and three
  Chroma deprecation warnings.
- Policy validation, protected Phase 1 baseline verification, and dependency
  validation passed.
- No environment, model, policy, manifest, or vector-store data was modified.
- Remaining work: Step 24. It was not started.
