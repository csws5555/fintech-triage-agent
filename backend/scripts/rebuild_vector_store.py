"""Explicit, stopped-client-gated Chroma and manifest rebuild."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Direct script execution initially places backend/scripts on sys.path. Add the
# backend package root so the documented command works from backend/.
SCRIPT_FILE = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_FILE.parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ml.ingest_policies import (  # noqa: E402
    VectorStoreRebuildError,
    rebuild_project_vector_store,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build and verify a temporary policy store, then activate it with "
            "backup and rollback protection. Windows directory moves are "
            "staged but are not guaranteed to be atomic."
        )
    )
    parser.add_argument(
        "--confirm-clients-stopped",
        action="store_true",
        help=(
            "Confirm that the backend and every Chroma client using the "
            "project store are stopped."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.confirm_clients_stopped:
        print(
            "REFUSED: rerun with --confirm-clients-stopped only after the "
            "backend and all Chroma clients are stopped.",
            file=sys.stderr,
        )
        return 2

    try:
        result = rebuild_project_vector_store(
            clients_stopped=True,
        )
    except VectorStoreRebuildError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print(
            "FAILED: unexpected local embedding or storage error.",
            file=sys.stderr,
        )
        return 1

    print(
        "PASS: active policy store and manifest rebuilt and reopened "
        "successfully; "
        f"chunks={result.chunk_count}, "
        f"embedding_dimensions={result.embedding_dimensions}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
