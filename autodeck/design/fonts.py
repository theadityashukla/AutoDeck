"""Font resolution — where a missing font becomes a loud error.

This is the smallest module in the design system and one of the most important. Text
budgets (§6.7) are computed from real glyph metrics; if the declared family is absent and
the measurement library quietly substitutes another face, **every computed budget is
wrong**, in the direction that produces overflow. That is the failure that stalled v1,
arriving through a different door (B11, and the Aptos checks in the Phase 0 brief).

So there is exactly one rule here: `resolve_family` either returns the real file or raises.
There is no fallback path, and nothing in the codebase catches `FontNotFoundError` and
carries on.

Owning phase: 0 (task 0.4).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: Searched in order. `AUTODECK_FONT_DIRS` (os.pathsep-separated) wins, then the repo's own
#: `fonts/`, then the platform locations Office and fontconfig use.
_DEFAULT_DIRS: tuple[str, ...] = (
    "fonts",
    "~/.local/share/fonts",
    "~/.fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "~/Library/Fonts",
    "/Library/Fonts",
    "/Library/Fonts/Microsoft",
    "/System/Library/Fonts",
    "C:/Windows/Fonts",
)

_EXTENSIONS = (".ttf", ".otf", ".ttc")

#: Documented in fonts/README.md; repeated in the error message because that is where
#: someone hitting this actually reads.
_APTOS_HINT = (
    "Aptos ships with Microsoft 365 and is not redistributable, so it cannot be committed "
    "or downloaded. Copy the TTFs from a local Office installation into fonts/, or point "
    "AUTODECK_FONT_DIRS at the system font directory. See fonts/README.md."
)


class FontNotFoundError(RuntimeError):
    """A declared font family could not be located.

    Deliberately fatal. Substituting a different face silently corrupts every text budget
    computed from it, and the resulting overflow surfaces much later as a layout bug rather
    than as a missing-font error.
    """


@dataclass(frozen=True)
class FontFile:
    """One resolved face."""

    family: str
    path: Path
    weight: str = "regular"


def search_dirs() -> list[Path]:
    """Directories searched for font files, in precedence order."""
    configured = os.environ.get("AUTODECK_FONT_DIRS", "")
    dirs = [Path(p).expanduser() for p in configured.split(os.pathsep) if p]
    dirs.extend(Path(p).expanduser() for p in _DEFAULT_DIRS)
    return [d for d in dirs if d.is_dir()]


def _normalise(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


@lru_cache(maxsize=64)
def resolve_family(family: str) -> FontFile:
    """Locate the regular face of `family`.

    Searches `AUTODECK_FONT_DIRS`, the repo `fonts/` directory, and the platform font
    directories, then falls back to `fc-match` on systems that have fontconfig — but only
    when fontconfig reports the family it was actually asked for. A fontconfig
    *substitution* is exactly the silent failure this function exists to prevent.

    Raises:
        FontNotFoundError: the family is not installed anywhere on this machine.
    """
    target = _normalise(family)

    for directory in search_dirs():
        for path in sorted(directory.rglob("*")):
            if path.suffix.lower() not in _EXTENSIONS:
                continue
            stem = _normalise(path.stem)
            # "Aptos" must not match "Aptos-Bold"; an exact stem or a "<family>-Regular".
            if stem == target or stem == f"{target}regular":
                return FontFile(family=family, path=path)

    matched = _fc_match(family)
    if matched is not None:
        return FontFile(family=family, path=matched)

    hint = f" {_APTOS_HINT}" if target.startswith("aptos") else ""
    searched = ", ".join(str(d) for d in search_dirs()) or "no existing directories"
    raise FontNotFoundError(
        f"font family {family!r} not found. Searched: {searched}.{hint} "
        "Budgets are computed from real glyph metrics, so a substituted face would make "
        "every text budget silently wrong — this is a hard error by design (B11)."
    )


def _fc_match(family: str) -> Path | None:
    """Ask fontconfig, accepting the answer only if it is not a substitution."""
    try:
        result = subprocess.run(
            ["fc-match", "--format=%{family}\t%{file}", family],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or "\t" not in result.stdout:
        return None

    families, _, file = result.stdout.partition("\t")
    wanted = _normalise(family)
    # fc-match always returns *something*; only trust it when the family came back.
    if not any(_normalise(name) == wanted for name in families.split(",")):
        return None
    path = Path(file.strip())
    return path if path.exists() else None


def is_available(family: str) -> bool:
    """Whether `family` resolves. For reporting and CLI checks — never for fallback."""
    try:
        resolve_family(family)
    except FontNotFoundError:
        return False
    return True


def installed_families() -> list[str]:
    """Families fontconfig reports, for the `autodeck fonts check` diagnostic."""
    try:
        result = subprocess.run(
            ["fc-list", "--format=%{family}\n"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    names = {line.split(",")[0].strip() for line in result.stdout.splitlines() if line.strip()}
    return sorted(names)
