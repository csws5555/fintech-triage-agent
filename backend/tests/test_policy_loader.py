from __future__ import annotations

from pathlib import Path

import pytest

from app.ml.policy_loader import (
    DuplicatePolicyDocumentError,
    PolicyValidationError,
    compute_content_hash,
    load_policy_directory,
    load_policy_file,
)


def policy_text(
    *,
    document_id: str = "test_policy",
    status: str = "approved",
    effective_date: str = "2026-07-01",
    review_date: str = "2026-10-01",
    extra_metadata: str = "",
    body: str = "# Test Policy\n\nApproved test guidance.",
) -> str:
    return (
        "---\n"
        f"document_id: {document_id}\n"
        "title: Test Policy\n"
        'version: "1.0"\n'
        f'effective_date: "{effective_date}"\n'
        f'review_date: "{review_date}"\n'
        "owner: Test Operations\n"
        f"status: {status}\n"
        "product: cards\n"
        "policy_type: operations\n"
        "jurisdiction: fictional_prototype\n"
        f"{extra_metadata}"
        "---\n\n"
        f"{body}\n"
    )


def write_policy(
    directory: Path,
    name: str = "test_policy.md",
    **kwargs: str,
) -> Path:
    path = directory / name
    path.write_text(
        policy_text(**kwargs),
        encoding="utf-8",
    )
    return path


def test_valid_policy_loads_with_safe_metadata(
    tmp_path: Path,
) -> None:
    path = write_policy(tmp_path)
    document = load_policy_file(path)

    assert document.document_id == "test_policy"
    assert document.source_file == path.name
    assert document.metadata["status"] == "approved"
    assert document.metadata["jurisdiction"] == (
        "fictional_prototype"
    )
    assert "source_path" not in document.storage_metadata()


def test_draft_policy_is_rejected(tmp_path: Path) -> None:
    path = write_policy(tmp_path, status="draft")

    with pytest.raises(
        PolicyValidationError,
        match="approved",
    ):
        load_policy_file(path)


def test_missing_required_metadata_is_rejected(
    tmp_path: Path,
) -> None:
    text = policy_text().replace(
        "owner: Test Operations\n",
        "",
    )
    path = tmp_path / "missing.md"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(
        PolicyValidationError,
        match="owner",
    ):
        load_policy_file(path)


def test_duplicate_document_ids_are_rejected(
    tmp_path: Path,
) -> None:
    write_policy(tmp_path, "one.md", document_id="duplicate")
    write_policy(tmp_path, "two.md", document_id="duplicate")

    with pytest.raises(DuplicatePolicyDocumentError):
        load_policy_directory(tmp_path)


def test_empty_body_is_rejected(tmp_path: Path) -> None:
    path = write_policy(tmp_path, body="   ")

    with pytest.raises(
        PolicyValidationError,
        match="body",
    ):
        load_policy_file(path)


def test_invalid_date_order_is_rejected(tmp_path: Path) -> None:
    path = write_policy(
        tmp_path,
        effective_date="2026-10-02",
        review_date="2026-10-01",
    )

    with pytest.raises(
        PolicyValidationError,
        match="effective_date",
    ):
        load_policy_file(path)


@pytest.mark.parametrize(
    "metadata",
    (
        "source_path: C:\\\\private\\\\policy.md\n",
        "source_file: policy.md\n",
        "absolute_path: C:\\\\private\\\\policy.md\n",
    ),
)
def test_yaml_path_fields_are_rejected(
    tmp_path: Path,
    metadata: str,
) -> None:
    path = write_policy(
        tmp_path,
        extra_metadata=metadata,
    )

    with pytest.raises(
        PolicyValidationError,
        match="not allowed",
    ):
        load_policy_file(path)


def test_source_filename_comes_from_path_name(
    tmp_path: Path,
) -> None:
    path = write_policy(
        tmp_path,
        "actual-name.md",
    )

    document = load_policy_file(path)

    assert document.source_file == "actual-name.md"
    assert Path(document.source_file).name == document.source_file


def test_source_and_chunk_hashes_have_distinct_meaning(
    tmp_path: Path,
) -> None:
    path = write_policy(tmp_path)
    document = load_policy_file(path)

    chunk_hash = compute_content_hash(document.body)

    assert len(document.source_hash) == 64
    assert len(chunk_hash) == 64
    assert document.source_hash != chunk_hash
