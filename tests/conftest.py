"""Test isolation: keep relay state out of the developer's real ~/.relay."""

from __future__ import annotations

import os
import tempfile

# Must run before any `relay` import, since RELAY_HOME is read at module import time.
os.environ["RELAY_HOME"] = tempfile.mkdtemp(prefix="relay-test-")
