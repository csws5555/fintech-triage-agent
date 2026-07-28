# Phase 2 Step 24 Execution Plan

## Objective

Create a deterministic output validator that inspects actual generated answer
text and structured flags, records every applicable stable failure code, and
never returns rejected text.

## Roadmap source

`personal project documentation/phase 2 steps.md`

- Step 24 — Create output validation
- Step 25 — Implement the orchestration pipeline (stop boundary)
- Step 30 — `test_output_validator.py` coverage requirements
- `personal project documentation/phase 2 flow chart.txt`
  — output-validation boundary

## Scope

### Included

- Reject blank and over-limit answers.
- Reject requests for authentication secrets while allowing protective
  warnings such as “Never share your OTP.”
- Reject unverified completed-action claims while allowing instructional and
  confirmation wording.
- Reject unsupported refund, reimbursement, delivery, dispute,
  investigation, and fee-reversal guarantees while allowing explicit
  non-guarantees.
- Require all roadmap safety concepts for deterministic stolen-card routes.
- Reject prompt, routing, classifier, retrieval, and internal-metadata leaks
  without rejecting ordinary customer-safe use of “policy.”
- Reject `insufficient_policy` and `claimed_completed_action` structured flags.
- Collect all failure codes in deterministic order.
- Fail closed on malformed validator inputs or configuration.

### Excluded

- Step 25 fallback selection and final `PipelineAnswer` construction.
- Model invocation, prompt construction, retrieval, routing, or classification.
- Logging, API exposure, persistence, streaming, or retries.
- Semantic entailment beyond the explicit deterministic safety patterns.

## Files to inspect

- `backend/app/ml/triage_types.py` — generated and validation contracts.
- `backend/app/ml/rag_config.py` — response character limit and validation.
- `backend/app/ml/risk_router.py` — stolen-card route semantics.
- `backend/app/ml/response_templates.py` — approved safety templates.
- `backend/app/ml/structured_generation.py` — untrusted Step 23 output.
- Related router, response-template, generation, and roadmap tests.

## Files expected to change

- Create `backend/app/ml/output_validator.py`.
- Create `backend/tests/test_output_validator.py`.
- Update this plan and `docs/IMPLEMENTATION_STATUS.md`.

## Protected files

- `backend/saved_models/distilbert_fintech_pt/` — verify only.
- `backend/app/data/chromadb_store/` — not accessed by Step 24.

## Compatibility constraints

- Preserve every Step 0–23 public interface.
- Reuse `GeneratedSupportResponse`, `OutputValidationResult`,
  `TriageDecision`, `RetrievedPolicy`, `RagSettings`, and validated settings.
- Accept the future Step 25 `policies=` keyword without reimplementing
  retrieval sufficiency.
- Treat every generated flag as untrusted; inspect answer text independently.
- Return only validation state and codes, never rejected text.
- Unit tests require no Ollama, Chroma, classifier, environment mutation, or
  runtime store.

## Implementation milestones

1. [x] Read the complete Step 24, Step 25 boundary, and roadmap test section;
   inspect all relevant interfaces, imports, callers, route semantics, and
   services.
2. [x] Implement deterministic validation with ordered failure aggregation.
3. [x] Add focused tests for all failure codes, safe negations, multi-failure
   aggregation, route-sensitive safety content, and deterministic templates.
4. [x] Run compilation, focused/full tests, applicable integration
   regressions, and repository validations.
5. [x] Update continuity records and stop before Step 25.

## Acceptance criteria

- [x] Every Step 24 text and flag rule has a stable failure code.
- [x] Safe negations and customer-safe “policy” wording pass.
- [x] Unsafe requests, claims, guarantees, and leaks fail.
- [x] All applicable codes are returned once in deterministic order.
- [x] Stolen-card route answers require all four safety concepts.
- [x] Approved stolen-card deterministic templates pass the same checks.
- [x] Malformed input/configuration fails closed without exposing input.
- [x] No rejected answer text is returned by the validation contract.

## Testing plan

- Focused: `python -m pytest -q tests/test_output_validator.py`
- Non-integration: `python -m pytest -q -m "not integration"`
- Integration regression: `python -m pytest -q -m integration`
- Validation:
  `python -m compileall app scripts tests`,
  `python scripts/verify_phase1_baseline.py`,
  `python scripts/validate_policies.py`, and `python -m pip check`

## Live-service requirements

- Step 24 implementation and focused tests: no live services.
- Existing integration suite may be rerun for regression confidence against
  already-running loopback Ollama and pytest temporary Chroma.
- The active Chroma store is not accessed or modified by Step 24.

## Rollback considerations

- Step 24 changes source, tests, and continuity documents only.
- No environment, model, policy, manifest, or vector-store data changes.
- Rollback removes the Step 24 source, test, plan, and continuity entries
  while preserving Steps 22–23 and unrelated user work.

## Progress checklist

- [x] Repository and roadmap inspected
- [x] Callers/imports inspected
- [x] Implementation complete
- [x] Documentation status updated
- [x] Applicable tests run
- [x] `git diff` and `git status --short` inspected

## Decisions made

- Use the existing `OutputValidationResult` rather than returning an answer or
  fallback from this module; Step 25 owns fallback selection.
- Identify stolen-card safety routes from deterministic security signals and
  reason codes, not classifier confidence or generated text.
- Use conservative explicit language patterns with safe-negation masking,
  backed by positive and negative tests.

## Unresolved risks

- Regex validation is intentionally conservative and cannot provide full
  semantic understanding; future evaluation must expand adversarial phrasing.

## Final results

- Created `backend/app/ml/output_validator.py`,
  `backend/tests/test_output_validator.py`, and this plan.
- Modified `docs/IMPLEMENTATION_STATUS.md`.
- Compilation passed.
- Focused service-free validator tests passed: 91.
- Non-integration tests passed: 327, with 3 integration tests deselected.
- Existing live regressions passed: 3, with 327 tests deselected and three
  Chroma deprecation warnings.
- Policy validation, protected Phase 1 baseline verification, and dependency
  validation passed.
- No Ollama or Chroma service is required for Step 24 itself.
- No environment, model, policy, manifest, or vector-store data was modified.
- Remaining work: Step 25. It was not started.
