"""Transport helpers that can be checked without launching anything."""

from __future__ import annotations

from pathlib import Path

import pytest

from relay.browser import chrome
from relay.errors import ProviderUnavailable


def test_relay_chrome_override_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    binary = tmp_path / "Chrome"
    binary.write_text("")
    monkeypatch.setenv("RELAY_CHROME", str(binary))

    assert chrome.chrome_binary() == binary


def test_missing_override_names_the_next_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RELAY_CHROME", str(tmp_path / "nope"))

    with pytest.raises(ProviderUnavailable, match="RELAY_CHROME"):
        chrome.chrome_binary()


def test_profile_lives_under_relay_home() -> None:
    """The dedicated profile is the login SSOT; it must never be the user's default profile."""
    assert chrome.PROFILE_DIR.parent.name == ".relay" or str(chrome.PROFILE_DIR).startswith("/")


def test_launch_flags_point_at_the_dedicated_profile() -> None:
    joined = " ".join(chrome.LAUNCH_FLAGS)

    assert chrome.CDP_PORT > 0
    assert "--no-first-run" in joined
    assert "--no-default-browser-check" in joined


def test_launch_command_includes_user_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binary = tmp_path / "Chrome"
    binary.write_text("")
    monkeypatch.setenv("RELAY_CHROME", str(binary))
    monkeypatch.setattr(chrome, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(chrome, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(chrome, "_process", None)

    captured: dict[str, object] = {}

    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: object) -> None:
            captured["argv"] = argv
            captured["kwargs"] = kwargs

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(chrome.subprocess, "Popen", FakePopen)

    chrome.launch()

    argv = captured["argv"]
    assert isinstance(argv, list)
    assert any(str(arg).startswith("--user-data-dir=") for arg in argv)
    assert any(str(arg).startswith("--remote-debugging-port=") for arg in argv)
    assert (tmp_path / "profile").stat().st_mode & 0o777 == 0o700
