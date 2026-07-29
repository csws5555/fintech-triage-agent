"""Validate all approved Phase 2 policy files before Chroma ingestion.

Run from the backend directory:

    python scripts/validate_policies.py

The script exits with status 0 only when the expected four policy files are
present, individually valid, unique, approved, registered, and named after
their document IDs.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``python scripts/validate_policies.py`` to import the backend package
# reliably even though Python initially places backend/scripts on sys.path.
SCRIPT_FILE = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_FILE.parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ml.policy_loader import (  # noqa: E402
    PolicyDocument,
    PolicyValidationError,
    load_policy_file,
    validate_unique_document_ids,
)

EXPECTED_POLICY_FILES: tuple[str, ...] = (
    "fraud_policy.md",
    "card_replacement.md",
    "card_delivery.md",
    "international_fees.md",
)


def _load_runtime_configuration() -> tuple[Path, frozenset[str]]:
    """Load project settings and the reviewed policy registry."""

    try:
        from app.ml.policy_registry import KNOWN_POLICY_IDS
        from app.ml.rag_config import settings
    except Exception as exc:  # startup/configuration errors must fail closed
        raise PolicyValidationError(
            f"Unable to load application configuration or policy registry: {exc}"
        ) from exc

    return Path(settings.policies_dir), frozenset(KNOWN_POLICY_IDS)


def _discover_markdown_files(policies_dir: Path) -> set[str]:
    try:
        return {
            path.name
            for path in policies_dir.iterdir()
            if path.is_file() and path.suffix.casefold() == ".md"
        }
    except OSError as exc:
        raise PolicyValidationError(
            f"Unable to inspect the policy directory: {exc}"
        ) from exc


def _validate_collection(
    documents: tuple[PolicyDocument, ...],
    *,
    known_policy_ids: frozenset[str],
) -> None:
    """Apply collection-level registry and naming checks."""

    validate_unique_document_ids(documents)

    loaded_ids = {document.document_id for document in documents}

    missing_ids = sorted(known_policy_ids - loaded_ids)
    unknown_ids = sorted(loaded_ids - known_policy_ids)

    if missing_ids:
        raise PolicyValidationError(
            "Missing registered policy document IDs: " + ", ".join(missing_ids)
        )

    if unknown_ids:
        raise PolicyValidationError(
            "Unregistered policy document IDs are not allowed: "
            + ", ".join(unknown_ids)
        )

    for document in documents:
        expected_filename = f"{document.document_id}.md"

        if document.source_file != expected_filename:
            raise PolicyValidationError(
                f"{document.source_file}: filename must match document_id; "
                f"expected {expected_filename!r}."
            )

        # Defensive checks in addition to policy_loader validation.
        if document.metadata.get("status") != "approved":
            raise PolicyValidationError(
                f"{document.source_file}: policy status is not approved."
            )

        if document.metadata.get("jurisdiction") != "fictional_prototype":
            raise PolicyValidationError(
                f"{document.source_file}: policy jurisdiction is invalid."
            )

        if Path(document.source_file).name != document.source_file:
            raise PolicyValidationError(
                f"{document.source_file}: source_file is not a simple filename."
            )


def main() -> int:
    """Run validation and return a process exit status."""

    try:
        policies_dir, known_policy_ids = _load_runtime_configuration()

        if not policies_dir.exists():
            raise PolicyValidationError("Policy directory does not exist.")

        if not policies_dir.is_dir():
            raise PolicyValidationError("Configured policy path is not a directory.")

        discovered_files = _discover_markdown_files(policies_dir)
        expected_files = set(EXPECTED_POLICY_FILES)

        missing_files = sorted(expected_files - discovered_files)
        unexpected_files = sorted(discovered_files - expected_files)

        errors: list[str] = []

        if missing_files:
            errors.append("Missing policy files: " + ", ".join(missing_files))

        if unexpected_files:
            errors.append(
                "Unexpected Markdown files in the approved policy directory: "
                + ", ".join(unexpected_files)
            )

        loaded_documents: list[PolicyDocument] = []

        for filename in EXPECTED_POLICY_FILES:
            path = policies_dir / filename

            if not path.is_file():
                continue

            try:
                loaded_documents.append(load_policy_file(path))
            except PolicyValidationError as exc:
                errors.append(str(exc))

        if not errors:
            try:
                _validate_collection(
                    tuple(loaded_documents),
                    known_policy_ids=known_policy_ids,
                )
            except PolicyValidationError as exc:
                errors.append(str(exc))

        if errors:
            for error in errors:
                print(f"FAIL {error}", file=sys.stderr)

            print(
                f"Policy validation failed with {len(errors)} error(s).",
                file=sys.stderr,
            )
            return 1

        documents_by_file = {
            document.source_file: document for document in loaded_documents
        }

        for filename in EXPECTED_POLICY_FILES:
            # Accessing by expected name also guards against accidental omission.
            _ = documents_by_file[filename]
            print(f"PASS {filename}")

        print()
        print(f"{len(loaded_documents)} approved policy files validated.")
        return 0

    except PolicyValidationError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # The validation command is a safety gate.  Unexpected errors must also
        # fail closed rather than allowing ingestion to continue.
        print(
            f"FAIL Unexpected policy-validation error: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
