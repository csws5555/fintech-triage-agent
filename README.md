# Fintech Risk & Support Triage Agent

This is a fictional, local-only portfolio prototype for banking-intent
classification, deterministic risk routing, policy-restricted retrieval, and
validated support responses. It is not a production banking platform and is
not connected to customer accounts or transactions.

Detailed progress and exact verification results are maintained in
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

## Local prerequisites

The backend requires:

- the existing `backend/venv` environment with `backend/requirements.txt`
  installed;
- the protected local DistilBERT classifier under
  `backend/saved_models/distilbert_fintech_pt/`;
- a compatible active Chroma store and schema-version-2 ingestion manifest
  under `backend/app/data/chromadb_store/`;
- Ollama already running at the configured loopback URL;
- the allowlisted `llama3.2:3b` and `nomic-embed-text` models already
  installed; and
- a reviewed local `backend/.env` based on `backend/.env.example`.

The API does not start Ollama, pull models, build or repair Chroma, or retrain
the classifier. Stop the API and every Chroma client before any separately
authorized vector-store rebuild or swap.

## Activate the backend environment

```powershell
cd backend
venv\Scripts\Activate.ps1
```

All backend commands below run from `backend/` with that virtual environment
active.

## API configuration

The API loads `backend/.env` with operating-system environment variables taking
precedence. Every Phase 3 setting is required and validated at import/startup.

| Variable | Example | Purpose |
| --- | --- | --- |
| `API_ENVIRONMENT` | `development` | Explicit local runtime label. |
| `API_HOST` | `127.0.0.1` | Uvicorn bind host. Use loopback for this local unauthenticated prototype. |
| `API_PORT` | `8000` | Uvicorn TCP port, from 1 through 65535. |
| `API_PREFIX` | `/api/v1` | Absolute, versioned chat-route prefix without a trailing slash. |
| `API_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated exact HTTP(S) origins. Wildcards and credentials are rejected. |
| `API_REQUEST_TIMEOUT_SECONDS` | `90` | Maximum HTTP lifetime after a blocking chat job is submitted. |
| `API_QUEUE_TIMEOUT_SECONDS` | `5` | Maximum wait for bounded chat-compute capacity before submission. |
| `API_MAX_CONCURRENT_REQUESTS` | `1` | Per-process blocking chat-compute limit; valid range is 1–4. |
| `API_MAX_REQUEST_BODY_BYTES` | `4096` | Maximum chat request body size, including JSON overhead. |
| `API_HEALTH_TIMEOUT_SECONDS` | `3` | Bound for optional local readiness probes and recovery attempts. |
| `API_READINESS_RETRY_COOLDOWN_SECONDS` | `10` | Minimum interval between degraded-component recovery attempts. |
| `API_LOG_LEVEL` | `INFO` | Validated API/Uvicorn log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |

CORS permits only configured exact origins, `GET`, `POST`, and `OPTIONS`, and
the `Accept` and `Content-Type` request headers. Credentials are disabled.

## Start the API

```powershell
python scripts/run_api.py
```

The runner validates configuration and starts `app.main:app` with reload
disabled and exactly one Uvicorn worker. Keep one worker: each process owns a
classifier, pipeline, local clients, bounded executor, and readiness state.

Startup fails explicitly if mandatory configuration, classifier warming, or
pipeline construction fails. Ollama or Chroma unavailability can start the API
in degraded readiness so cheap liveness and safe diagnostics remain available.
Shutdown rejects new chat work, closes the API-owned executor, and releases
application state.

## Health endpoints

`GET /health/live` is a cheap process-liveness check. It performs no
classification, embedding, retrieval, or generation:

```json
{
  "status": "alive",
  "service": "fintech-triage-api"
}
```

`GET /health/ready` reports only safe component availability:

```json
{
  "status": "ready",
  "components": {
    "configuration": "ready",
    "classifier": "ready",
    "pipeline": "ready",
    "vector_store": "ready",
    "ollama_chat_model": "ready",
    "ollama_embedding_model": "ready"
  }
}
```

The endpoint returns HTTP 200 with `status` set to `ready` only when every
component is ready. Otherwise it returns HTTP 503 with `status: "degraded"` and
one or more components marked `unavailable`. Readiness uses a bounded installed
model inventory check; it does not generate text or create embeddings.

## JSON chat contract

Send only a customer `message`:

```text
POST /api/v1/chat
Content-Type: application/json
```

```json
{
  "message": "When should my first physical card arrive?"
}
```

Successful pipeline outcomes return HTTP 200:

```json
{
  "request_id": "0bb65a0c-71db-47ca-9bfa-b06e2764e98a",
  "answer": "Check the delivery estimate shown in the app and verify that the delivery address is correct.",
  "status": "answered",
  "response_mode": "grounded_generation",
  "risk_level": "low",
  "requires_human": false
}
```

`status` can be `answered`, `clarification_required`, `safety_guidance`,
`request_refused`, `action_not_confirmed`, `unsupported`, or
`service_fallback`. `response_mode` and `risk_level` reuse the stable Phase 2
public enums. High-risk guidance, clarification, hidden-information refusal,
unsupported requests, and unverified account-action responses remain
deterministic and do not depend on raw model output.

Clients cannot submit classifier output, risk, policy identifiers, retrieved
context, prompts, or validator state. Empty, whitespace-only, malformed,
oversized, wrong-content-type, over-length, or extra-field requests fail
closed.

Public errors use one stable envelope:

```json
{
  "request_id": "fe64a229-1a42-4b38-8c46-d554622154eb",
  "error": {
    "code": "invalid_request",
    "message": "The request is invalid.",
    "retryable": false
  }
}
```

Transport status codes are:

- `200` — safe pipeline result;
- `413` — request body too large;
- `415` — unsupported content type;
- `422` — malformed JSON or invalid request schema;
- `500` — unexpected internal API error;
- `503` — busy, classifier unavailable, or escaped support-service failure;
  and
- `504` — request execution timeout.

Error bodies do not expose exception text, stack traces, prompts, policy
content, model output, local paths, secrets, or routing internals.

## Buffered SSE chat contract

```text
POST /api/v1/chat/stream
Content-Type: application/json
Accept: text/event-stream
```

The request body is the same strict `{"message":"..."}` contract. Streaming is
validated buffered delivery, not raw model-token streaming: classification,
routing, retrieval, generation, and output validation finish before response
headers and customer text are sent.

A successful stream contains:

```text
event: metadata
data: {"request_id":"...","status":"safety_guidance","response_mode":"deterministic_safety","risk_level":"high","requires_human":false}

event: chunk
data: {"request_id":"...","sequence":0,"text":"Freeze the card through the official app if you can, review recent activity, "}

event: chunk
data: {"request_id":"...","sequence":1,"text":"and use the official replacement process."}

event: done
data: {"request_id":"...","chunks":2}

```

Phase 4 clients must concatenate `chunk.text` in `sequence` order, treat `done`
as successful completion, treat `error` as terminal, and tolerate a disconnect
without a final event. The `metadata` event supplies safe status and risk
badges. A failure before headers uses the normal JSON error/status contract. An
unexpected failure after headers can emit one terminal
`stream_interrupted` error event.

## Local HTTP smoke checks

With the API running in another PowerShell session:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/chat `
  -ContentType 'application/json' `
  -Body (@{message='When should my first physical card arrive?'} | ConvertTo-Json)

$body = @{message='When should my replacement card arrive?'} |
  ConvertTo-Json -Compress
$response = Invoke-WebRequest `
  -UseBasicParsing `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/chat/stream `
  -Headers @{Accept='text/event-stream'} `
  -ContentType 'application/json' `
  -Body $body
$response.Content
```

Stop the API with `Ctrl+C` before any vector-store maintenance.

## Verification

Service-free release checks:

```powershell
python -m compileall app scripts tests
python -m pytest -q -m "not integration"
python scripts/verify_phase1_baseline.py
python scripts/validate_policies.py
python -m pip check
```

The non-integration suite uses fakes and dependency injection and does not
require live Ollama, active Chroma access, or classifier inference. The
baseline verifier reads the protected classifier artifacts without loading,
training, or saving the model.

Read-only live checks require the local prerequisites listed above:

```powershell
python scripts/check_ollama.py
python scripts/inspect_vector_store.py
python scripts/test_retrieval.py
python scripts/test_rag_pipeline.py
python -m pytest -q -m integration
```

These checks must not start Ollama, pull models, rebuild or swap the active
store, modify its manifest, or save the classifier. Local generated wording and
timings can vary. Unsafe or unverifiable generated text is discarded and
replaced by a safe fallback.

## Known prototype limitations

- There is no authentication or authorization.
- There is no account or transaction integration, and no account action can be
  performed or confirmed.
- Conversation history is neither accepted nor persisted.
- A timed-out or disconnected blocking job may finish in its executor thread;
  its capacity remains occupied until actual completion.
- Local model wording and timings vary, and generated output can be rejected by
  validation and replaced with a safe fallback.
- The API and all Chroma clients must be stopped before any vector-store
  rebuild or swap.

This prototype also omits production case management, audit controls, privacy
controls, regulatory review, deployment hardening, and transaction execution.

## Dependency maintenance

After deliberately changing the environment:

```powershell
python -m pip freeze > requirements.txt
```
