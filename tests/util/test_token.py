"""Bearer token file: created once, readable only by the user, never logged."""

from __future__ import annotations

from pathlib import Path

from relay.util.token import read_or_create_token


def test_token_is_created_with_owner_only_permissions(tmp_path: Path) -> None:
    path = tmp_path / "token"

    token = read_or_create_token(path)

    assert token
    assert path.exists()
    assert path.stat().st_mode & 0o777 == 0o600


def test_token_is_stable_across_calls(tmp_path: Path) -> None:
    path = tmp_path / "token"

    first = read_or_create_token(path)
    second = read_or_create_token(path)

    assert first == second


def test_existing_token_is_reused(tmp_path: Path) -> None:
    path = tmp_path / "token"
    path.write_text("hand-written\n")

    assert read_or_create_token(path) == "hand-written"


def test_empty_token_file_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "token"
    path.write_text("   \n")

    token = read_or_create_token(path)

    assert token.strip()
    assert path.read_text().strip() == token


def test_parent_directory_is_created(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "token"

    read_or_create_token(path)

    assert path.exists()
