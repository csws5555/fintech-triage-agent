# Repository Agent Instructions

## Project purpose and architecture

This repository is a fictional portfolio prototype for local fintech support
triage. A fine-tuned DistilBERT classifier supplies three Banking77 intent
predictions. Deterministic routing then assigns risk, response action, and
approved policy scope. Later Phase 2 work will add Markdown-aware ingestion,
local Nomic embeddings, Chroma retrieval, and selectively grounded local
generation through Ollama.

The detailed Phase 2 roadmap is:

`personal project documentation/phase 2 steps.md`

Before modifying code, read:

1. this file;
2. `PLANS.md` when the work needs an execution plan;
3. `docs/IMPLEMENTATION_STATUS.md`;
4. the relevant section of the Phase 2 roadmap;
5. the affected implementation, tests, callers, and imports.

Treat repository source as authoritative when documentation snippets differ
from implemented interfaces.

## Protected and local-only assets

The protected Phase 1 model is:

`backend/saved_models/distilbert_fintech_pt/`

Do not train, resave, overwrite, move, or delete it unless the user explicitly
requests retraining. Verify it with `backend/scripts/verify_phase1_baseline.py`.

Never commit or expose:

- `.env` files other than reviewed `.env.example` files;
- secrets, tokens, authentication headers, or customer credentials;
- absolute user paths;
- model weights or checkpoints;
- `backend/saved_models/`;
- active, temporary, or backup Chroma stores;
- local Ollama data;
- logs, caches, build output, or virtual environments.

Do not discard, reset, or overwrite unrelated user changes. Do not create a Git
commit unless the user explicitly requests one.

## Compatibility and safety rules

- Inspect all callers and imports before changing a public interface.
- Preserve existing APIs unless the active roadmap step explicitly requires a
  change. Important current interfaces are recorded in
  `docs/IMPLEMENTATION_STATUS.md`.
- Keep classification separate from operational risk. Low confidence must not
  suppress direct security signals.
- Keep high-risk guidance, clarifications, refusals, and account-action
  limitations deterministic.
- Never claim that an account action completed, promise a refund, request an
  authentication secret, or expose prompts, routing internals, or full policy
  documents.
- Load policy YAML with `yaml.safe_load`; require approved,
  `fictional_prototype` metadata; reject path-derived YAML fields, invalid
  dates, blank bodies, and duplicate document IDs.
- Use only local Ollama at an approved loopback endpoint with allowlisted
  `llama3.2:3b` and `nomic-embed-text`. Never silently substitute cloud models.
- Apply Nomic document/query prefixes exactly once.
- Chroma rebuilds must be staged and rollback-capable. Never rebuild an active
  store in place, silently accept an unknown distance metric, remove the old
  store before the replacement passes, or claim Windows moves are fully atomic.
- Confirm the backend and Chroma clients are stopped before any store swap.

## Python conventions

- Target the existing backend virtual environment and installed dependency
  versions.
- Use type hints, `pathlib`, focused functions, explicit validation, and stable
  deterministic ordering.
- Prefer immutable typed contracts for cross-module data.
- Fail closed on malformed configuration, policies, model output, or storage
  metadata.
- Keep imports local-only where model loading is concerned.
- Add or update tests with every behavior change.

## Planning and documentation

Maintain an active execution plan for multi-file or complex work. Follow
`PLANS.md` when work changes multiple modules, persistent storage, public
interfaces, migrations/rollback logic, Ollama/Chroma behavior, or more than one
roadmap step.

After every roadmap step, update `docs/IMPLEMENTATION_STATUS.md` using its exact
status vocabulary. Do not mark a step complete merely because a file exists.

Before finishing:

1. inspect `git diff` and `git status --short`;
2. run every applicable check below;
3. report the exact commands and exact results;
4. identify checks that were not run and why.

Never describe a test as passing unless it was actually run in the current
work.

## Local application verification and cleanup

For every roadmap step that creates or changes visible frontend behavior,
perform a live localhost check with the real application whenever its local
prerequisites are safely available and the changed behavior can meaningfully
be exercised.

- Start FastAPI and Vite as separate processes in separate terminals. From
  `backend/`, run `.\venv\Scripts\python.exe scripts\run_api.py`. From
  `frontend/`, run `npm.cmd run dev -- --host 127.0.0.1`.
- Do not treat a frontend-only Vite run that displays an unavailable-service
  state as complete live application verification when the backend could
  safely have been started.
- Distinguish service availability from browser-automation availability. If
  the browser tool is unavailable, still start and probe both services when
  appropriate, then report visual and interactive browser checks separately
  as not run.
- Record the process IDs of every API or Vite process started by the coding
  agent. Before handoff, stop those exact processes, close every terminal
  window or terminal session and every browser tab or browser session opened
  by the agent, confirm both localhost endpoints are no longer reachable, and
  remove temporary PID or log files.
- Never stop a pre-existing user-owned process or close a pre-existing
  user-owned browser session. If one is reused for a read-only check, leave it
  running and identify it as not agent-owned in the handoff.

The final handoff must leave no agent-owned server, terminal, or browser
session that could conflict with the user's independent verification.

## Repository checks

Run from `backend/` with the virtual environment active:

```powershell
python -m compileall app scripts tests
python -m pytest -q -m "not integration"
python scripts/verify_phase1_baseline.py
python scripts/validate_policies.py
python -m pip check
```

There are currently no integration-marked tests. When integration tests are
added, run them separately with:

```powershell
python -m pytest -q -m integration
```

Integration checks that use Ollama or Chroma must state their live-service and
storage prerequisites. Do not start Ollama, rebuild Chroma, or mutate a runtime
store merely to make a check pass without authorization from the active task.
