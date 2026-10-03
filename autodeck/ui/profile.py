"""Who is using the UI: the name an approval is recorded under (B42).

A UI approval is a person clicking "Approve & proceed", and the orchestrator records it
"by <name>" exactly as `autodeck approve --by <name>` does. Typing the name on every
approval adds nothing, so it is kept once, here, and editable in Settings > Profile.

Until it is saved, the name comes from `git config user.name`, then the system account.
The file lives in the user's home folder, not the repository: it describes the person at
this machine, not the project.
"""

from __future__ import annotations

import getpass
import json
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_PROFILE = Path.home() / ".autodeck" / "profile.json"
MAX_NAME = 80


def _git_name() -> str:
    try:
        out = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _system_name() -> str:
    try:
        return getpass.getuser().strip()
    except Exception:
        return ""


def read_profile(path: Path) -> dict[str, Any]:
    """`{name, source}`: the saved name, else git's, else the system account's."""
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        name = str(saved.get("name", "")).strip()
        if name:
            return {"name": name, "source": "saved"}
    except (OSError, ValueError, AttributeError):
        pass
    if name := _git_name():
        return {"name": name, "source": "git"}
    return {"name": _system_name(), "source": "system"}


def save_profile(path: Path, name: str) -> dict[str, Any]:
    from autodeck.ui.api import UIError

    name = " ".join(str(name).split())
    if not name:
        raise UIError("Type the name your approvals should carry.")
    if len(name) > MAX_NAME:
        raise UIError(f"Keep the name under {MAX_NAME} characters.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": name}, indent=2), encoding="utf-8")
    return {"name": name, "source": "saved"}


def approver_name(path: Path) -> str:
    """The name to record an approval under; refuses when none can be found."""
    from autodeck.ui.api import UIError

    name = read_profile(path)["name"]
    if not name:
        raise UIError("Set your name in Settings > Profile before approving.", status=409)
    return str(name)
