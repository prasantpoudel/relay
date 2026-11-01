"""``python -m relay.daemon`` — the long-lived process.

Binds loopback only. Anything else would expose the user's logged-in browser session to the network.
"""

from __future__ import annotations

import os

import uvicorn

from .app import create_app


def main() -> None:
    port = int(os.environ.get("RELAY_PORT", "8787"))
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
