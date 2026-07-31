"""Start the local Phase 3 FastAPI application with one Uvicorn worker.

Run from the backend directory:

    python scripts/run_api.py

The application loads only the configured local classifier, active read-only
vector store, and approved loopback Ollama clients. Stop the API before any
separately authorized Chroma rebuild or store swap.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import uvicorn


SCRIPT_FILE = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_FILE.parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.config import (  # noqa: E402
    ApiSettings,
    api_settings,
    validate_api_settings,
)


ServerRunner = Callable[..., object]


def run_local_api(
    runtime_settings: ApiSettings = api_settings,
    *,
    server_runner: ServerRunner = uvicorn.run,
) -> None:
    """Run ``app.main:app`` with validated settings and one worker."""

    if not isinstance(runtime_settings, ApiSettings):
        raise TypeError("runtime_settings must be an ApiSettings instance.")
    if not callable(server_runner):
        raise TypeError("server_runner must be callable.")

    validate_api_settings(runtime_settings)
    server_runner(
        "app.main:app",
        host=runtime_settings.host,
        port=runtime_settings.port,
        log_level=runtime_settings.log_level.lower(),
        workers=1,
        reload=False,
    )


def main() -> int:
    """Start the local API and return after Uvicorn stops."""

    run_local_api()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
