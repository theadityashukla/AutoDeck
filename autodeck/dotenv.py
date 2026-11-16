"""Load provider keys from a local `.env` into the environment, without overriding it.

AutoDeck reads keys from the environment (registry, B8). Before this, `.env` reached the
process only if something else loaded it — VS Code's Python extension does, but only into
terminals opened *after* the file changed — so a key added to `.env` could be invisible to a
server started from an older terminal, with nothing saying why.

A variable already set in the environment always wins: `.env` fills gaps, it never replaces
what the shell says. Set `AUTODECK_NO_DOTENV=1` to skip loading (the test suite does, so a
developer's real keys never reach a test).
"""

from __future__ import annotations

import os
from pathlib import Path

DOTENV_PATH = Path(".env")


def load_dotenv(path: Path = DOTENV_PATH) -> list[str]:
    """Set every `NAME=value` in `path` that the environment lacks; return the names set.

    Accepts `export NAME=value`, spaces around `=`, and single or double quotes around the
    value. Blank lines and `#` comments are skipped. A missing file is not an error.
    """
    if os.environ.get("AUTODECK_NO_DOTENV") or not path.is_file():
        return []
    loaded: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if not name.isidentifier() or name in os.environ:
            continue
        os.environ[name] = value
        loaded.append(name)
    return loaded
