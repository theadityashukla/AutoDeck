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

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from autodeck.design.fonts import is_available
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


def check_render_fonts(tokens: DesignTokens) -> list[str]:
    """Confirm every declared family is installed for the renderer.

    Returns:
        The confirmed families.

    Raises:
        FontSubstitutionRisk: a declared family is missing.
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
    return families


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
