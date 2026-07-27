"""Verify that the protected Phase 1 model artifacts are unchanged."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
MANIFEST_PATH = BACKEND_DIR / "phase1_model_manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file_handle:
        for block in iter(
            lambda: file_handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def load_manifest() -> dict[str, Any]:
    try:
        loaded = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Unable to load {MANIFEST_PATH.name}: {exc}"
        ) from exc

    if not isinstance(loaded, dict):
        raise RuntimeError("Model manifest must be a JSON object.")

    return loaded


def main() -> int:
    try:
        manifest = load_manifest()
        model_directory = (
            BACKEND_DIR / str(manifest["model_directory"])
        )
        expected_files = manifest["files"]

        if not isinstance(expected_files, list) or not expected_files:
            raise RuntimeError(
                "Model manifest contains no file records."
            )

        failures: list[str] = []

        for record in expected_files:
            name = str(record["name"])
            path = model_directory / name

            if not path.is_file():
                failures.append(f"{name}: missing")
                continue

            actual_size = path.stat().st_size
            expected_size = int(record["bytes"])

            if actual_size != expected_size:
                failures.append(
                    f"{name}: expected {expected_size} bytes, "
                    f"received {actual_size}"
                )
                continue

            actual_hash = sha256_file(path)
            expected_hash = str(record["sha256"]).lower()

            if actual_hash != expected_hash:
                failures.append(f"{name}: SHA-256 mismatch")
                continue

            print(f"PASS {name}")

        if failures:
            for failure in failures:
                print(f"FAIL {failure}", file=sys.stderr)
            return 1

        print()
        print(
            f"{len(expected_files)} Phase 1 model artifacts "
            "match the protected baseline."
        )
        return 0
    except (KeyError, TypeError, ValueError, RuntimeError, OSError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
