"""The font checks around the LibreOffice render (no LibreOffice needed).

`pdffonts` output is saved as a string: the point is the parser and the comparison, not the
tool. Live run Xls: LibreOffice on macOS could not see Inter Display and drew bold titles in
Arial Black, which is what the ArialBlack fixture reproduces.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from autodeck.render.qa import libreoffice
from autodeck.render.qa.libreoffice import (
    FontSubstitutionRisk,
    RenderError,
    _verify_pdf_fonts,
    parse_pdffonts,
)

HEADER = (
    "name                                 type              encoding         emb sub uni "
    "object ID\n"
    "------------------------------------ ----------------- ---------------- --- --- --- "
    "---------\n"
)

GOOD = HEADER + (
    "ABCDEF+InterDisplay-Bold             CID TrueType      Identity-H       yes yes yes "
    "     5  0\n"
    "GHIJKL+Inter-Regular                 CID TrueType      Identity-H       yes yes yes "
    "     9  0\n"
    "MNOPQR+OpenSymbol                    CID TrueType      Identity-H       yes yes yes "
    "    12  0\n"
)

ARIAL_BLACK = HEADER + (
    "ABCDEF+ArialBlack                    CID TrueType      Identity-H       yes yes yes "
    "     5  0\n"
    "GHIJKL+Inter-Regular                 CID TrueType      Identity-H       yes yes yes "
    "     9  0\n"
)

FAMILIES = ["Inter Display", "Inter"]


def _fake_pdffonts(monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int = 0) -> None:
    monkeypatch.setattr(libreoffice.shutil, "which", lambda _name: "/usr/bin/pdffonts")
    monkeypatch.setattr(
        libreoffice.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout, "boom"),
    )


def test_parser_strips_subset_prefixes_and_style_suffixes() -> None:
    assert parse_pdffonts(GOOD) == {"interdisplay", "inter", "opensymbol"}


def test_parser_ignores_the_header_and_blank_lines() -> None:
    assert parse_pdffonts(HEADER + "\n") == set()


def test_declared_families_and_opensymbol_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_pdffonts(monkeypatch, GOOD)
    _verify_pdf_fonts(Path("x.pdf"), FAMILIES)


def test_arial_black_substitution_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_pdffonts(monkeypatch, ARIAL_BLACK)
    with pytest.raises(FontSubstitutionRisk) as raised:
        _verify_pdf_fonts(Path("x.pdf"), FAMILIES)
    message = str(raised.value)
    assert "arialblack" in message
    assert "Inter Display" in message


def test_missing_pdffonts_is_a_render_error_with_an_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(libreoffice.shutil, "which", lambda _name: None)
    with pytest.raises(RenderError, match="poppler"):
        _verify_pdf_fonts(Path("x.pdf"), FAMILIES)


def test_pdffonts_failure_is_a_render_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_pdffonts(monkeypatch, "", returncode=1)
    with pytest.raises(RenderError, match="pdffonts failed"):
        _verify_pdf_fonts(Path("x.pdf"), FAMILIES)
