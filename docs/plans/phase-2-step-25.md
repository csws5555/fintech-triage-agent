# Phase 2 Step 25 Execution Plan

## Objective

Create the synchronous dependency-injected orchestration pipeline that applies
the deterministic route order, limits retrieval and local generation to
eligible branches, validates generated output, and returns typed
`PipelineAnswer` results.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 25 — Implement the orchestration pipeline
- Step 26 — Add validated buffered streaming (stop boundary)
- Step 30 — `test_pipeline.py` coverage requirements
- `personal project documentation/phase 2 flow chart.txt`
  — complete synchronous orchestration flow

## Scope

### Included

- Validate and normalize query input before any dependency call.
- Route in the exact roadmap priority order.
- Keep critical, static, unsupported, and clarification branches free from
  retrieval and local generation.
- Retrieve with both allowed and required policy scopes for urgent and normal
  generation branches.
- Fail closed on retriever construction, retrieval, sufficiency, prompt,
  structured-generation, or output-validation failures.
- Keep urgent responses deterministic; use detailed guidance only after
  sufficient retrieval and minimum safety guidance otherwise.
- Generate only for low/medium `generate` routes with sufficient approved
  context.
- Discard unsafe generated text and return only approved deterministic
  fallbacks.
- Return stable `PipelineAnswer` metadata with deterministic unique policy and
  chunk IDs.
- Allow injected router, retriever, chat model, and validator fakes without
  loading DistilBERT, Ollama, or Chroma.

### Excluded

- Step 26 streaming or async APIs.
- Classifier invocation; Step 25 receives `ClassificationResult`.
- API endpoints, frontend integration, logging, evaluation expansion, or
  persistence.
- Chroma rebuilding, ingestion, environment changes, or model training.

## Files to inspect

- `backend/app/ml/risk_router.py` — action ordering and reason codes.
- `backend/app/ml/retriever.py` — scoped retrieval and bound sufficiency.
- `backend/app/ml/grounding_prompt.py` — safe generation messages.
- `backend/app/ml/structured_generation.py` — bounded schema generation.
- `backend/app/ml/output_validator.py` — generated-answer safety boundary.
- `backend/app/ml/response_templates.py` — deterministic response wording.
- `backend/app/ml/triage_types.py` — pipeline input/output contracts.
- All related tests, imports, callers, policy text, and roadmap examples.

## Files expected to change

- Create `backend/app/ml/rag_pipeline.py`.
- Create `backend/tests/test_rag_pipeline.py`.
- Modify `backend/app/ml/response_templates.py` only for missing deterministic
  route wording required by the pipeline.
- Update this plan and `docs/IMPLEMENTATION_STATUS.md`.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — verify only.
- `backend/app/data/chromadb_store/` — read only through existing live
  regressions; no Step 25 unit test access.

## Compatibility constraints

- Preserve every Step 0–24 public interface.
- Reuse `ClassificationResult`, `TriageDecision`, `RetrievedPolicy`,
  `GeneratedSupportResponse`, `OutputValidationResult`, and `PipelineAnswer`.
- Reuse existing router, retriever, prompt, generation, validator, settings,
  and reviewed template interfaces without duplicating their logic.
- Pass `required_policy_ids` to every retrieval.
- Do not call the LLM for deterministic or urgent branches.
- Never put rejected generated text, provider errors, prompts, policy content,
  classifier details, scores, paths, or secrets in a `PipelineAnswer`.
- Default construction/import must not load local models or stores.

## Implementation milestones

1. [x] Read the complete Step 25 and Step 26 boundary; inspect all relevant
   interfaces, route reasons, policies, templates, callers, tests, and service
   constraints.
2. [x] Add only the missing deterministic templates and implement the lazy,
   dependency-injected synchronous pipeline.
3. [x] Add focused fake-based tests for every action, failure boundary,
   metadata contract, and no-call invariant.
4. [x] Run compilation, focused/full tests, applicable live regressions, and
   repository validations.
5. [x] Update continuity records and stop before Step 26.

## Acceptance criteria

- [x] Route handling follows the exact Step 25 order.
- [x] Deterministic branches call neither retrieval nor local generation.
- [x] Urgent branches never call the LLM and remain safe when retrieval fails.
- [x] Normal generation requires scoped, sufficient retrieval.
- [x] Structured or validation failure discards generated text and returns an
  approved fallback.
- [x] Successful generation returns validated text and complete typed metadata.
- [x] Every external component failure is contained without private details.
- [x] Constructor injection permits service-free unit tests.
- [x] Default construction is lazy.

## Testing plan

- Focused: `python -m pytest -q tests/test_rag_pipeline.py`
- Non-integration: `python -m pytest -q -m "not integration"`
- Integration regression: `python -m pytest -q -m integration`
- Validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Focused tests: no live services, classifier, or active store.
- Default generate routes require the configured loopback Ollama models and
  validated active Chroma store at runtime.
- Step 25 does not create the broader end-to-end live pipeline suite reserved
  for Step 31; existing live regressions may be rerun.

## Rollback considerations

- Step 25 changes source, tests, and continuity documents only.
- No environment, model, policy, manifest, or vector-store data changes.
- Rollback removes the pipeline/test/plan, reverts only the three new template
  functions, and preserves Steps 22–24 and unrelated user work.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Use lazy default retriever/model resolution so construction and
  deterministic routes remain service-free.
- Treat normal retrieval failure and insufficiency as deterministic fallback;
  urgent failure always returns minimum safety with human support.
- Keep Step 24 validation codes inside the validation boundary and expose one
  stable pipeline reason code; Step 34 owns structured logging.
- Add policy-derived deterministic templates only where current router signals
  otherwise lack correct wording.

## Unresolved risks

- Full real-query end-to-end pipeline evaluation remains scheduled for the
  roadmap's live integration/evaluation steps.

## Final results

- Created `backend/app/ml/rag_pipeline.py`,
  `backend/tests/test_rag_pipeline.py`, and this plan.
- Modified `backend/app/ml/response_templates.py` and
  `docs/IMPLEMENTATION_STATUS.md`.
- Compilation passed.
- Focused fake-based and real-router seam tests passed: 57.
- Non-integration tests passed: 384, with 3 integration tests deselected.
- Existing live regressions passed: 3, with 384 tests deselected and three
  Chroma deprecation warnings.
- Policy validation, protected Phase 1 baseline verification, and dependency
  validation passed.
- No active-store end-to-end pipeline operation was run; broader real-query
  pipeline integration remains scheduled for Step 31.
- No environment, model, policy, manifest, or vector-store data was modified.
- Remaining work: Step 26. It was not started.
