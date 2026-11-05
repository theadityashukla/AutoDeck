"""Task 4.6 (B84): the audit report as a PDF, made for strict decks only."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from autodeck.audit import report_pdf
from autodeck.audit.report_pdf import (
    ReportPdfError,
    markdown_to_html,
    write_report_pdf,
    write_report_pdf_if_strict,
)

SAMPLE = """# Audit report — p

Run `r1` · provenance **strict**

## Claims

| Block | Claim | Verdict |
|---|---|---|
| `b1` | Costs fell 33% \\| pilot | supported |

> A quote with <b>markup</b> & an ampersand
> over two lines

- a point with *emphasis*
  - a nested point

---

Plain paragraph.
"""

needs_soffice = pytest.mark.skipif(
    shutil.which("soffice") is None and shutil.which("libreoffice") is None,
    reason="LibreOffice is not installed",
)


def test_the_html_carries_every_construct_the_report_uses() -> None:
    page = markdown_to_html(SAMPLE)
    assert "<h1>Audit report — p</h1>" in page and "<h2>Claims</h2>" in page
    assert "<code>r1</code>" in page and "<strong>strict</strong>" in page
    assert page.count("<th>") == 3 and "Costs fell 33% | pilot" in page
    assert "<blockquote>" in page and "<em>emphasis</em>" in page and "<hr>" in page


def test_nothing_in_the_report_is_interpreted_as_html() -> None:
    page = markdown_to_html(SAMPLE)
    assert "<b>markup</b>" not in page
    assert "&lt;b&gt;markup&lt;/b&gt; &amp; an ampersand" in page


def test_the_html_is_deterministic() -> None:
    assert markdown_to_html(SAMPLE) == markdown_to_html(SAMPLE)


def test_a_normal_deck_gets_no_pdf(tmp_path: Path) -> None:
    out = tmp_path / "audit.pdf"
    assert write_report_pdf_if_strict(SAMPLE, out, provenance="normal") is None
    assert not out.exists()


def test_a_failed_pdf_never_raises_from_the_strict_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise ReportPdfError("no LibreOffice")

    monkeypatch.setattr(report_pdf, "write_report_pdf", boom)
    assert write_report_pdf_if_strict(SAMPLE, tmp_path / "a.pdf", provenance="strict") is None


@needs_soffice
def test_a_strict_deck_gets_a_real_pdf(tmp_path: Path) -> None:
    out = write_report_pdf_if_strict(SAMPLE, tmp_path / "audit.pdf", provenance="strict")
    assert out is not None and out.read_bytes().startswith(b"%PDF")


@needs_soffice
def test_write_report_pdf_writes_where_asked(tmp_path: Path) -> None:
    out = write_report_pdf(SAMPLE, tmp_path / "nested" / "report.pdf")
    assert out.is_file() and out.stat().st_size > 1000
