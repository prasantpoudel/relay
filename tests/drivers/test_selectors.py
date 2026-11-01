"""Selector files are configuration, so they get validated like code."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from relay.drivers.base import Selectors
from relay.errors import SelectorMiss

PROVIDER_DIR = Path(__file__).resolve().parents[2] / "src" / "relay" / "drivers"
SELECTOR_FILES = sorted(PROVIDER_DIR.glob("*/selectors.json"))
REQUIRED = ("composer", "assistant_turn")


def test_every_shipped_provider_has_a_selector_file() -> None:
    names = {path.parent.name for path in SELECTOR_FILES}

    assert names == {"chatgpt", "gemini", "claude"}


@pytest.mark.parametrize("path", SELECTOR_FILES, ids=lambda p: p.parent.name)
def test_selector_file_loads_and_covers_the_core_elements(path: Path) -> None:
    selectors = Selectors.load(path)

    for name in REQUIRED:
        assert selectors.get(name, provider=path.parent.name)


@pytest.mark.parametrize("path", SELECTOR_FILES, ids=lambda p: p.parent.name)
def test_every_selector_entry_is_an_ordered_array(path: Path) -> None:
    data = json.loads(path.read_text())

    assert isinstance(data, dict)
    for name, values in data.items():
        assert isinstance(values, list), f"{path.name}: '{name}' is not an array"
        assert values, f"{path.name}: '{name}' is empty"
        assert all(isinstance(v, str) and v.strip() for v in values)


def test_missing_key_raises_selector_miss_not_keyerror() -> None:
    selectors = Selectors({"composer": ["#x"]})

    with pytest.raises(SelectorMiss) as caught:
        selectors.get("send", provider="chatgpt")

    assert "send" in str(caught.value)
    assert caught.value.http_status == 502


def test_load_rejects_an_empty_selector_array(tmp_path: Path) -> None:
    path = tmp_path / "selectors.json"
    path.write_text(json.dumps({"composer": []}))

    with pytest.raises(ValueError, match="non-empty"):
        Selectors.load(path)


def test_load_rejects_a_bare_string(tmp_path: Path) -> None:
    path = tmp_path / "selectors.json"
    path.write_text(json.dumps({"composer": "div#prompt-textarea"}))

    with pytest.raises(ValueError):
        Selectors.load(path)


def test_optional_returns_empty_list_instead_of_raising() -> None:
    selectors = Selectors({"composer": ["#x"]})

    assert selectors.optional("quota_banner") == []
    assert "quota_banner" not in selectors


def test_registry_builds_every_shipped_provider() -> None:
    from relay.drivers import PROVIDER_IDS, build_providers

    providers = build_providers()

    assert set(providers) == set(PROVIDER_IDS) == {"chatgpt", "gemini", "claude"}
    for provider in providers.values():
        assert provider.home_url.startswith("https://")
        assert "composer" in provider.selectors
        assert len(provider.selectors) >= 5


def test_unknown_provider_names_the_known_ones() -> None:
    from relay.drivers import get_provider
    from relay.errors import ProviderUnavailable

    with pytest.raises(ProviderUnavailable, match="chatgpt"):
        get_provider("gpt-4")
