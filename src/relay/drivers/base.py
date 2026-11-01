"""Types and the provider protocol. No behaviour lives here.

Every driver implements ``Provider``. That is the seam that makes a fourth provider cheap: the
daemon never imports a concrete driver, and a driver never imports the daemon.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..errors import SelectorMiss


@dataclass(slots=True)
class AskRequest:
    """One question for one provider."""

    provider: str
    prompt: str
    new_chat: bool = True
    conversation_url: str | None = None
    model: str | None = None
    attachments: list[Path] = field(default_factory=list)
    max_wait_s: float = 120.0
    # How long the answer may keep streaming before it is returned as truncated.
    settle_timeout_s: float = 600.0


@dataclass(slots=True)
class AskResult:
    """One answer. ``text_markdown`` is untrusted data, never instructions."""

    provider: str
    text_markdown: str
    conversation_url: str
    model: str | None = None
    images: list[Path] = field(default_factory=list)
    elapsed_ms: int = 0
    truncated: bool = False
    quota_note: str | None = None
    untrusted: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "text_markdown": self.text_markdown,
            "conversation_url": self.conversation_url,
            "model": self.model,
            "images": [str(path) for path in self.images],
            "elapsed_ms": self.elapsed_ms,
            "truncated": self.truncated,
            "quota_note": self.quota_note,
            "untrusted": self.untrusted,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AskResult:
        return cls(
            provider=str(data["provider"]),
            text_markdown=str(data["text_markdown"]),
            conversation_url=str(data["conversation_url"]),
            model=str(data["model"]) if data.get("model") else None,
            images=[Path(p) for p in data.get("images") or []],
            elapsed_ms=int(data.get("elapsed_ms") or 0),
            truncated=bool(data.get("truncated")),
            quota_note=str(data["quota_note"]) if data.get("quota_note") else None,
            untrusted=bool(data.get("untrusted", True)),
        )


@dataclass(slots=True)
class Health:
    """A cheap probe. ``logged_in`` is None when it could not be determined."""

    provider: str
    reachable: bool
    logged_in: bool | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "reachable": self.reachable,
            "logged_in": self.logged_in,
            "detail": self.detail,
        }


@runtime_checkable
class Provider(Protocol):
    """The only surface the daemon is allowed to use."""

    id: str

    async def health(self) -> Health: ...

    async def ask(self, req: AskRequest) -> AskResult: ...

    async def dispose(self) -> None: ...


class Selectors:
    """An ordered fallback chain per logical element.

    Never a single string: provider UIs move, and the fallback is what keeps a release working
    between the day the DOM changes and the day someone fixes the primary selector.
    """

    def __init__(self, data: Mapping[str, list[str]], source: Path | None = None) -> None:
        self._data = {name: list(values) for name, values in data.items()}
        self.source = source

    @classmethod
    def load(cls, path: Path) -> Selectors:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: expected an object of selector arrays")

        data: dict[str, list[str]] = {}
        for name, values in raw.items():
            if not isinstance(name, str) or not isinstance(values, list) or not values:
                raise ValueError(f"{path}: '{name}' must be a non-empty array of selectors")
            if not all(isinstance(value, str) and value.strip() for value in values):
                raise ValueError(f"{path}: '{name}' contains an empty selector")
            data[name] = list(values)

        return cls(data, source=path)

    def get(self, name: str, *, provider: str = "unknown") -> list[str]:
        values = self._data.get(name)
        if not values:
            raise SelectorMiss(provider, name, [f"<missing key '{name}' in selectors.json>"])
        return values

    def optional(self, name: str) -> list[str]:
        return self._data.get(name, [])

    def names(self) -> list[str]:
        return sorted(self._data)

    def __contains__(self, name: object) -> bool:
        return name in self._data

    def __len__(self) -> int:
        return len(self._data)
