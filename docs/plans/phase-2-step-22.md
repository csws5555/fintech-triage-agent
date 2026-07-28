# Phase 2 Step 22 Execution Plan

## Objective

Build a deterministic grounding prompt that keeps trusted system rules
separate from untrusted customer and approved policy-chunk data while exposing
only the minimum route state required for later grounded generation.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 22 — Build the grounding prompt
- `personal project documentation/phase 2 flow chart.txt`
  — grounding-prompt boundary

## Scope

### Included

- Return separate LangChain system and human messages.
- Include the required system role, policy-only rules, response style,
  escalation state, customer message, and approved policy chunks.
- JSON-encode untrusted customer and policy text inside explicit boundaries.
- Include only policy title, section, version, and chunk content.
- Validate that the route is low/medium grounded generation and the supplied
  context is approved, scoped, complete for required families, unique,
  version-consistent, and within the configured context limit.
- Reject local-path/model-location data before prompt construction.

### Excluded

- Step 23 `.with_structured_output(...)` binding or response schema requests.
- Step 24 generated-output validation and Step 25 orchestration.
- Model invocation, streaming, retrieval, classification, or deterministic
  response selection.
- Prompt logging, printing, persistence, or exposure through an API.

## Files to inspect

- `backend/app/ml/triage_types.py` — `TriageDecision` and `RetrievedPolicy`.
- `backend/app/ml/retriever.py` — accepted-context invariants.
- `backend/app/ml/rag_config.py` — message and context limits.
- `backend/app/ml/chat_model.py` — future prompt consumer.
- `backend/app/ml/risk_router.py` — route/action semantics.
- Existing router, retriever, and safety-template tests.

## Files expected to change

- Create `backend/app/ml/grounding_prompt.py`.
- Create `backend/tests/test_grounding_prompt.py`.
- Update this plan and `docs/IMPLEMENTATION_STATUS.md`.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — checksum verification only.
- `backend/app/data/chromadb_store/` — not accessed by Step 22.

## Compatibility constraints

- Preserve every Step 0–21 public interface.
- Reuse `TriageDecision`, `RetrievedPolicy`, `RagSettings`, and `settings`.
- Do not include raw relevance scores, classifier metadata, policy/chunk IDs,
  hashes, filenames, reason codes, security signals, or local paths.
- Do not construct prompts for unsupported, clarification, static, urgent,
  critical, insufficient, or incomplete-policy routes.
- Unit tests require no Ollama, Chroma, classifier, or active manifest.
- Fail closed without echoing rejected prompt data in errors.

## Implementation milestones

1. [x] Read the complete roadmap/flow-chart prompt sections and inspect all
   dependencies, imports, callers, tests, and service constraints.
2. [x] Implement the typed deterministic prompt builder and validation.
3. [x] Add focused tests for required content, separation, exclusion,
   injection boundaries, route/context failures, and path rejection.
4. [x] Run compilation, focused/full tests, applicable integration, and
   repository validations.
5. [x] Update continuity records and stop before Step 23.

## Acceptance criteria

- [x] Trusted rules appear only in the system message.
- [x] Untrusted customer/policy data appears only in the human message.
- [x] Customer and policy values are JSON encoded within explicit boundaries.
- [x] All roadmap-required rules and route state are present.
- [x] Forbidden metadata and local paths are absent.
- [x] Only approved, allowed, required-complete, unique chunks are accepted.
- [x] Non-generation and high/critical routes fail closed.
- [x] Prompt construction is deterministic and service-free.

## Testing plan

- Focused: `python -m pytest -q tests/test_grounding_prompt.py`
- Non-integration: `python -m pytest -q -m "not integration"`
- Integration: `python -m pytest -q -m integration`
- Validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Prompt implementation and focused tests: no live services.
- Existing integration suite may be rerun for regression confidence, but Step
  22 itself does not call Ollama or Chroma.

## Rollback considerations

- Step 22 changes source, tests, and continuity documents only.
- No environment, model, policy, manifest, or store data changes.
- Rollback removes the Step 22 files/plan while preserving uncommitted Steps
  17–21 and unrelated user work.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Use a `(SystemMessage, HumanMessage)` tuple rather than one interpolated
  string so untrusted data cannot be merged into trusted rules.
- Serialize untrusted values as JSON with stable field ordering and escaped
  newlines.
- Treat Step 22 as a pure builder; later steps decide when to invoke the model.

## Unresolved risks

- Model compliance with the prompt is not a trust boundary; Steps 23–24 must
  still enforce structured output and deterministic validation.

## Final results

- Created `backend/app/ml/grounding_prompt.py`,
  `backend/tests/test_grounding_prompt.py`, and this plan.
- Modified `docs/IMPLEMENTATION_STATUS.md`.
- Compilation passed.
- Focused service-free tests passed: 18.
- Non-integration tests passed: 217, with 2 integration tests deselected.
- Existing live regression tests passed: 2, with 217 tests deselected and
  three Chroma deprecation warnings.
- Policy validation, protected Phase 1 baseline verification, and dependency
  validation passed.
- No prompt was logged or printed, no model was invoked, and no Chroma,
  environment, policy, or model data was modified.
- Remaining work: Step 23. It was not started.
