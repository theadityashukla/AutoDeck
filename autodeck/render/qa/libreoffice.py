"""Headless LibreOffice render to PNG — the truth-telling half of D5.

The design loop is: edit renderer code → render PPTX → rasterise → look. That loop is only
worth anything if the PNG shows what PowerPoint will show, which puts one requirement above
all others: **the fonts the deck declares must be installed here.** If they are not,
LibreOffice substitutes silently and the preview gallery, the visual sign-off, and the
Phase 3 vision critique are all judging a face the client will never see. The Phase 0 brief
calls this the check most likely to be skipped and most damaging to skip (B11 check #3), so
`render_pptx` verifies fonts before it renders and refuses rather than producing a
misleading image.

LibreOffice's `--convert-to png` only ever emits the first slide, so multi-slide decks go
through PDF and are rasterised with `pdftoppm`.

This is a **local-machine** operation. B10 keeps it out of CI, which has neither a font
stack nor a display stack; tests that call it carry the `render` marker.

Owning phase: 0 (spike 0.5); productionised in Phase 3b.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from autodeck.design.fonts import is_available, libreoffice_font_dirs
from autodeck.design.theme.tokens import DesignTokens

DEFAULT_DPI = 150
DEFAULT_TIMEOUT = 240


class RenderError(RuntimeError):
    """LibreOffice or the rasteriser failed, or a required tool is missing."""


class FontSubstitutionRisk(RenderError):
    """A declared font is not installed, so any render would be a substituted lie.

    Separate from `RenderError` because it is not a tooling failure — the pipeline works
    fine, it simply must not be trusted. See B11.
    """


@dataclass(frozen=True)
class RenderResult:
    """Rendered pages plus the provenance needed to judge them honestly."""

    images: list[Path]
    families: list[str]
    """The families the deck declared *and* that were confirmed installed."""
    dpi: int

    @property
    def page_count(self) -> int:
        return len(self.images)


def soffice_path() -> str:
    """Locate the LibreOffice binary."""
    for candidate in ("soffice", "libreoffice"):
        found = shutil.which(candidate)
        if found:
            return found
    raise RenderError(
        "LibreOffice not found. The preview loop needs it (D5); install libreoffice-impress. "
        "Per B10 this is a local-machine dependency and is not available in CI."
    )


#: The faces a deck draws, as `(bold, italic)`. Both families are drawn regular and bold
#: (the major family carries every bold headline; `heading` text in the minor family is
#: bold too); only the minor family is drawn italic.
_MAJOR_FACES: tuple[tuple[bool, bool], ...] = ((False, False), (True, False))
_MINOR_FACES: tuple[tuple[bool, bool], ...] = ((False, False), (True, False), (False, True))

#: Folders CoreText (what headless LibreOffice uses on macOS) reads fonts from. It does not
#: read `~/.local/share/fonts` or the repo's `fonts/`.
_MACOS_FONT_DIRS: tuple[str, ...] = (
    "~/Library/Fonts",
    "/Library/Fonts",
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
)

#: LibreOffice's own symbol fonts, legitimately embedded in PDFs it writes.
_ALLOWED_PDF_FAMILIES: frozenset[str] = frozenset({"opensymbol"})

_FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc"}


def _face_label(bold: bool, italic: bool) -> str:
    return {(False, False): "regular", (True, False): "bold", (False, True): "italic"}.get(
        (bold, italic), "bold italic"
    )


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _required_faces(tokens: DesignTokens) -> list[tuple[str, bool, bool]]:
    typography = tokens.typography
    required = [(typography.major, b, i) for b, i in _MAJOR_FACES]
    required += [(typography.minor, b, i) for b, i in _MINOR_FACES]
    seen: set[tuple[str, bool, bool]] = set()
    unique = []
    for item in required:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _macos_font_dirs() -> list[Path]:
    """CoreText folders plus LibreOffice's own bundled font folders (any platform)."""
    dirs = [Path(d).expanduser() for d in _MACOS_FONT_DIRS]
    dirs.extend(libreoffice_font_dirs())
    unique: list[Path] = []
    for d in dirs:
        if d.is_dir() and d not in unique:
            unique.append(d)
    return unique


def _coretext_faces() -> set[tuple[str, bool, bool]]:
    """`(normalised family, bold, italic)` for every font file CoreText would see."""
    from fontTools.ttLib import TTCollection, TTFont

    faces: set[tuple[str, bool, bool]] = set()

    def record(font: TTFont) -> None:
        names = font["name"]
        family = names.getDebugName(16) or names.getDebugName(1)
        subfamily = (names.getDebugName(17) or names.getDebugName(2) or "").lower()
        if not family:
            return
        bold = "bold" in subfamily or "black" in subfamily or "heavy" in subfamily
        italic = "italic" in subfamily or "oblique" in subfamily
        faces.add((_norm(family), bold, italic))
        # Weights between regular and bold (SemiBold, ...) are filed under their own
        # legacy family name ("Inter SemiBold"); the declared family is what matters here.
        legacy = names.getDebugName(1)
        if legacy:
            faces.add((_norm(legacy), "bold" in (names.getDebugName(2) or "").lower(), italic))

    for directory in _macos_font_dirs():
        for path in directory.rglob("*"):
            if path.suffix.lower() not in _FONT_EXTENSIONS:
                continue
            try:
                if path.suffix.lower() in {".ttc", ".otc"}:
                    collection = TTCollection(str(path), lazy=True)
                    for font in collection.fonts:
                        record(font)
                else:
                    font = TTFont(str(path), lazy=True)
                    record(font)
                    font.close()
            except Exception:  # an unreadable file is simply not a candidate
                continue
    return faces


def _fontconfig_faces() -> set[tuple[str, bool, bool]]:
    try:
        result = subprocess.run(
            ["fc-list", ":", "family", "style"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    faces: set[tuple[str, bool, bool]] = set()
    for line in result.stdout.splitlines():
        families, _, styles = line.partition(":style=")
        style_text = styles.lower()
        bold = "bold" in style_text
        italic = "italic" in style_text or "oblique" in style_text
        for family in families.split(","):
            faces.add((_norm(family), bold, italic))
    return faces


def _renderer_faces() -> set[tuple[str, bool, bool]]:
    """Every face the renderer (not Python) can see on this machine."""
    if sys.platform == "darwin":
        return _coretext_faces()
    # LibreOffice also reads its own bundled fonts (Carlito, ...) without fontconfig.
    return _fontconfig_faces() | _coretext_faces()


def check_render_fonts(tokens: DesignTokens) -> list[str]:
    """Confirm every face the deck draws is installed where *both* readers look.

    Two readers, two checks, and both must pass. Python's own lookup (`design.fonts`) is
    what layout is *measured* with. LibreOffice is what the preview is *drawn* by, and it
    reads a different place: CoreText folders on macOS (it cannot see `~/.local/share/fonts`
    or the repo's `fonts/`), fontconfig elsewhere. A face present for one and not the other
    gives measured-versus-drawn mismatches, e.g. Arial Black standing in for a bold Inter
    Display, wrapping a title one line later than it was budgeted.

    Returns:
        The confirmed families.

    Raises:
        FontSubstitutionRisk: a declared face is missing for either reader.
    """
    families = sorted(tokens.typography.families())
    missing = [family for family in families if not is_available(family)]
    if missing:
        raise FontSubstitutionRisk(
            f"{', '.join(missing)} not installed, so LibreOffice would substitute another "
            "face and every preview PNG would show a deck that does not exist. Install the "
            "family (see fonts/README.md) or render with a token set whose fonts are "
            "present. Refusing to render rather than produce a misleading image (B11)."
        )

    visible = _renderer_faces()
    absent = [
        f"{family} {_face_label(bold, italic)}"
        for family, bold, italic in _required_faces(tokens)
        if (_norm(family), bold, italic) not in visible
    ]
    if absent:
        where = (
            "the macOS font folders CoreText reads (~/Library/Fonts, /Library/Fonts)"
            if sys.platform == "darwin"
            else "fontconfig (fc-list)"
        )
        raise FontSubstitutionRisk(
            f"{', '.join(absent)} not visible to LibreOffice: it looks in {where}, which is "
            "not where Python found the font. LibreOffice would substitute another face and "
            "every preview PNG would show a deck that does not exist. Install the family "
            "there (scripts/install-dev-fonts.sh does both on macOS) or render with a token "
            "set whose fonts are present. Refusing to render rather than produce a "
            "misleading image (B11)."
        )
    return families


_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_STYLE_SUFFIX = re.compile(
    r"(bolditalic|boldoblique|semibold|extrabold|bold|italic|oblique|regular|medium|light)+$"
)


def _pdf_font_family(name: str) -> str:
    """`ABCDEF+InterDisplay-Bold` -> `interdisplay`."""
    name = _SUBSET_PREFIX.sub("", name.strip())
    base = _norm(name)
    stripped = _STYLE_SUFFIX.sub("", base)
    return stripped or base


def parse_pdffonts(output: str) -> set[str]:
    """Normalised family names from `pdffonts` output (name is the first column)."""
    lines = output.splitlines()
    families: set[str] = set()
    started = False
    for line in lines:
        if line.startswith("---"):
            started = True
            continue
        if not started or not line.strip():
            continue
        families.add(_pdf_font_family(line.split()[0]))
    return families


def _verify_pdf_fonts(pdf: Path, families: Sequence[str]) -> None:
    """Fail if the PDF embeds a family the deck did not declare.

    The PDF records what LibreOffice actually drew with, so this catches a substitution the
    pre-render font check could not predict.
    """
    if shutil.which("pdffonts") is None:
        raise RenderError(
            "pdffonts not found (install poppler / poppler-utils). It reads the fonts "
            "LibreOffice actually embedded, to catch silent substitution."
        )
    try:
        result = subprocess.run(
            ["pdffonts", str(pdf)], capture_output=True, text=True, timeout=60, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError("pdffonts timed out") from exc
    if result.returncode != 0:
        raise RenderError(f"pdffonts failed: {result.stderr.strip()}")

    declared = {_norm(family) for family in families}
    drawn = parse_pdffonts(result.stdout)
    allowed = declared | _ALLOWED_PDF_FAMILIES
    substituted = sorted(f for f in drawn if f not in allowed)
    if substituted:
        raise FontSubstitutionRisk(
            f"LibreOffice drew with {', '.join(substituted)} (normalised name from the PDF), "
            f"not the declared {', '.join(sorted(families))}: it substituted a face, so the "
            "preview PNGs would not match the measured layout. Install the declared faces "
            "where LibreOffice can see them (see fonts/README.md). Refusing to produce a "
            "misleading image (B11)."
        )


def render_pptx(
    pptx: Path,
    output_dir: Path,
    tokens: DesignTokens,
    *,
    dpi: int = DEFAULT_DPI,
    timeout: int = DEFAULT_TIMEOUT,
) -> RenderResult:
    """Render every slide of `pptx` to a PNG in `output_dir`.

    Raises:
        FontSubstitutionRisk: a declared font is absent — checked *before* rendering.
        RenderError: LibreOffice or pdftoppm failed.
    """
    families = check_render_fonts(tokens)

    pptx = Path(pptx).resolve()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as scratch:
        scratch_dir = Path(scratch)
        pdf = _to_pdf(pptx, scratch_dir, timeout)
        _verify_pdf_fonts(pdf, families)
        images = _to_pngs(pdf, output_dir, pptx.stem, dpi, timeout)

    return RenderResult(images=images, families=families, dpi=dpi)


def _to_pdf(pptx: Path, scratch: Path, timeout: int) -> Path:
    # A private profile directory keeps concurrent renders from fighting over the default
    # one, which LibreOffice locks.
    profile = scratch / "profile"
    command = [
        soffice_path(),
        f"-env:UserInstallation=file://{profile}",
        "--headless",
        "--norestore",
        "--convert-to",
        "pdf",
        str(pptx),
        "--outdir",
        str(scratch),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"LibreOffice timed out after {timeout}s on {pptx.name}") from exc

    pdf = scratch / f"{pptx.stem}.pdf"
    if not pdf.exists():
        raise RenderError(
            f"LibreOffice produced no PDF for {pptx.name}. "
            f"stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}"
        )
    return pdf


def _to_pngs(pdf: Path, output_dir: Path, stem: str, dpi: int, timeout: int) -> list[Path]:
    if shutil.which("pdftoppm") is None:
        raise RenderError(
            "pdftoppm not found (install poppler-utils). LibreOffice's own PNG export only "
            "emits the first slide, so multi-slide decks are rasterised from PDF."
        )

    prefix = output_dir / stem
    command = ["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(prefix)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"pdftoppm timed out after {timeout}s") from exc

    if result.returncode != 0:
        raise RenderError(f"pdftoppm failed: {result.stderr.strip()}")

    images = sorted(output_dir.glob(f"{stem}-*.png"))
    if not images:
        raise RenderError(f"pdftoppm produced no images for {pdf.name}")
    return images
