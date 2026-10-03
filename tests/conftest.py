"""Suite-wide settings."""

from __future__ import annotations

import os

# The CLI loads ./.env at startup (autodeck/dotenv.py). Tests run from the repo root, where a
# developer's real keys live; they must never reach a test.
os.environ["AUTODECK_NO_DOTENV"] = "1"
