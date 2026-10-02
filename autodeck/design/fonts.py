"""Font resolution — where a missing font becomes a loud error.

This is the smallest module in the design system and one of the most important. Text
budgets (§6.7) are computed from real glyph metrics; if the declared family is absent and
the measurement library quietly substitutes another face, **every computed budget is
wrong**, in the direction that produces overflow. That is the failure that stalled v1,
arriving through a different door (B11, and the Aptos checks in the Phase 0 brief).

So there is exactly one rule here: `resolve_face` either returns the real file or raises.
There is no fallback path, and nothing in the codebase catches `FontNotFoundError` and
carries on.

## A face, not a family — and why that distinction is load-bearing

This module used to expose `resolve_family(family)`, which returned the **regular** face
and nothing else. Every caller measuring bold text therefore measured regular-weight
advance widths: `TextStyle.bold` reached `Canvas.measure_block` intact and then changed
nothing. Every headline in this codebase is drawn bold, so every headline budget
under-predicted its own width — measured on the installed faces at 32pt, by **+6.1%** for
Inter Display and **+2.8%** for Inter — in the direction that overflows. A `quote`
headline predicted 839.8pt against an 852pt box, wrapped to a second line at render, and
the accent rule struck through it; the committed PNG is what caught it, because every
automated check compared the prediction against itself.

Substituting regular for bold *is* B11's silent substitution, arriving one level below
where B11 was written. So the rule above applies per face, not per family:

**A missing face is the same error as a missing family.** `resolve_face(family,
bold=True)` on a family that ships no bold raises `FontNotFoundError` naming the face. It
does not fall back to regular, and it does not synthesise. Synthesised bold is rejected
everywhere, with no exception, for a reason specific to this codebase rather than as a
matter of taste: a synthesised face has **no file to measure**, so a budget computed for
it would be an estimate of an estimate, and the whole point of `budgets.py` is that its
horizontal numbers come off a real `hmtx` table. A renderer handed `bold=True` with no
bold face will do *something* at render time; whatever that something is, this module
cannot measure it, and a budget it cannot measure is one it must refuse to issue.

The consequence is a real prerequisite, not a theoretical one: a declared family must
supply the faces the design system actually asks it for. `DesignTokens.require_fonts()`
checks regular, bold and italic up front for exactly that reason (see its docstring for
why bold-italic is checked lazily instead).

## The filename is a claim; the file is the evidence

Faces are found by filename convention (`<Family>-Bold.ttf`), which is a claim about what
is inside. Every candidate is then verified against the `OS/2.fsSelection` and
`head.macStyle` bits the file itself declares, and a file whose name and contents disagree
is passed over rather than trusted. This is not defensive decoration: on this container
`fc-match "Inter Display:bold:italic"` answers `InterDisplay-Italic.ttf` while *reporting*
weight 200 (bold), which is precisely the confident-but-wrong substitution B11 forbids —
and only reading the file catches it.

Owning phase: 0 (task 0.4). The face split is 3a's follow-up to 2b §6.1's line-height fix:
same shape of bug — a real measurement replaced by a convenient approximation, biased in
the overflow direction.
"""

from __future__ import annotations

import os
import subprocess
from contextlib import suppress
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
    """One resolved face: the file, and which face of `family` it actually is."""

    family: str
    path: Path
    bold: bool = False
    italic: bool = False

    @property
    def face(self) -> str:
        """`"regular"`, `"bold"`, `"italic"` or `"bold italic"` — for error messages."""
        return _face_name(self.bold, self.italic)


#: Filename suffixes tried, in order, for each face. Normalised the same way stems are, so
#: `Inter Display Bold.ttf`, `InterDisplay-Bold.ttf` and `interdisplay_bold.ttf` all match.
#: The regular face deliberately accepts only the bare family and `-Regular`: "Aptos" must
#: not resolve to "Aptos-Bold", which is the original reason this matching is exact.
_FACE_SUFFIXES: dict[tuple[bool, bool], tuple[str, ...]] = {
    (False, False): ("", "regular"),
    (True, False): ("bold",),
    (False, True): ("italic", "oblique"),
    (True, True): ("bolditalic", "boldoblique", "italicbold"),
}

#: `OS/2.fsSelection` bit 0 (ITALIC) and bit 5 (BOLD); `head.macStyle` bit 0 (bold) and
#: bit 1 (italic). Read together because sloppy fonts set one and leave the other at zero.
_FS_ITALIC, _FS_BOLD = 0x0001, 0x0020
_MAC_BOLD, _MAC_ITALIC = 0x0001, 0x0002


def _face_name(bold: bool, italic: bool) -> str:
    if bold and italic:
        return "bold italic"
    if bold:
        return "bold"
    if italic:
        return "italic"
    return "regular"


def search_dirs() -> list[Path]:
    """Directories searched for font files, in precedence order."""
    configured = os.environ.get("AUTODECK_FONT_DIRS", "")
    dirs = [Path(p).expanduser() for p in configured.split(os.pathsep) if p]
    dirs.extend(Path(p).expanduser() for p in _DEFAULT_DIRS)
    return [d for d in dirs if d.is_dir()]


def _normalise(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _declared_face(path: Path) -> tuple[bool, bool] | None:
    """`(bold, italic)` as the font file itself declares them, or `None` if unreadable.

    The filename says what a file claims to be; this says what it is. `head` is a required
    table in every TrueType and OpenType font, so `None` here means the file could not be
    opened or parsed at all — in which case nothing downstream could measure it either.
    `OS/2.fsSelection` and `head.macStyle` are read together rather than one being trusted:
    fonts exist that set the bold bit in one and leave the other at zero.
    """
    from fontTools.ttLib import TTFont

    try:
        font = TTFont(str(path), fontNumber=0, lazy=True)
    except Exception:  # a corrupt or non-font file is simply not a candidate
        return None
    selection = 0
    try:
        with suppress(Exception):
            selection = int(font["OS/2"].fsSelection)  # type: ignore[attr-defined]
        mac = int(font["head"].macStyle)  # type: ignore[attr-defined]
    except Exception:  # as above: unreadable is not a match, it is not a candidate
        return None
    finally:
        font.close()

    bold = bool(selection & _FS_BOLD) or bool(mac & _MAC_BOLD)
    italic = bool(selection & _FS_ITALIC) or bool(mac & _MAC_ITALIC)
    return bold, italic


@lru_cache(maxsize=128)
def resolve_face(family: str, *, bold: bool = False, italic: bool = False) -> FontFile:
    """Locate the file for one **face** of `family`.

    Searches `AUTODECK_FONT_DIRS`, the repo `fonts/` directory, and the platform font
    directories for a file whose stem matches `family` plus one of `_FACE_SUFFIXES`, then
    verifies against the file's own style bits that it really is that face. Falls back to
    `fc-match` on systems with fontconfig — but only when fontconfig returns the family it
    was asked for *and* the file it names verifies as the requested face. A fontconfig
    substitution is exactly the silent failure this function exists to prevent, and it
    substitutes across faces as readily as across families.

    Raises:
        FontNotFoundError: that face of that family is not installed anywhere on this
            machine. Never downgraded to the regular face, and never synthesised — see the
            module docstring for why a face this module cannot measure is one it must
            refuse.
    """
    target = _normalise(family)
    wanted = (bold, italic)
    candidates = tuple(f"{target}{suffix}" for suffix in _FACE_SUFFIXES[wanted])
    mismatched: list[str] = []

    for directory in search_dirs():
        by_stem: dict[str, Path] = {}
        for path in sorted(directory.rglob("*")):
            if path.suffix.lower() not in _EXTENSIONS:
                continue
            by_stem.setdefault(_normalise(path.stem), path)
        for stem in candidates:
            path = by_stem.get(stem)
            if path is None:
                continue
            declared = _declared_face(path)
            if declared == wanted:
                return FontFile(family=family, path=path, bold=bold, italic=italic)
            if declared is not None:
                mismatched.append(f"{path} declares itself {_face_name(*declared)}")

    matched = _fc_match(family, bold=bold, italic=italic)
    if matched is not None:
        return FontFile(family=family, path=matched, bold=bold, italic=italic)

    hint = f" {_APTOS_HINT}" if target.startswith("aptos") else ""
    searched = ", ".join(str(d) for d in search_dirs()) or "no existing directories"
    found = f" Rejected: {'; '.join(sorted(set(mismatched)))}." if mismatched else ""
    raise FontNotFoundError(
        f"the {_face_name(bold, italic)} face of font family {family!r} was not found. "
        f"Searched: {searched}.{found}{hint} Budgets are computed from real glyph "
        "metrics, so falling back to the regular face would make every bold or italic "
        "budget silently wrong — this is a hard error by design (B11); see "
        "autodeck/design/fonts.py on why synthesised faces are refused rather than "
        "estimated."
    )


def _fc_match(family: str, *, bold: bool, italic: bool) -> Path | None:
    """Ask fontconfig, accepting the answer only if it is not a substitution.

    Two separate checks, because fontconfig substitutes along two axes. The family it
    reports must be the one asked for, and the file it names must verify as the requested
    face — fontconfig happily reports weight 200 for a file whose `OS/2` says 400, which
    is how `"Inter Display:bold:italic"` resolves to the plain italic file here.
    """
    query = family
    if bold:
        query += ":bold"
    if italic:
        query += ":italic"
    try:
        result = subprocess.run(
            ["fc-match", "--format=%{family}\t%{file}", query],
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
    wanted_family = _normalise(family)
    # fc-match always returns *something*; only trust it when the family came back.
    if not any(_normalise(name) == wanted_family for name in families.split(",")):
        return None
    path = Path(file.strip())
    if not path.exists() or _declared_face(path) != (bold, italic):
        return None
    return path


def is_available(family: str, *, bold: bool = False, italic: bool = False) -> bool:
    """Whether that face of `family` resolves. For reporting and CLI checks — never for
    fallback."""
    try:
        resolve_face(family, bold=bold, italic=italic)
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
