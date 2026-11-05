"""The audit report as a PDF, for strict decks only (Phase 4 task 4.6, B84).

Who reads the audit report decides how much it is worth polishing. The owner answered Q4:
it is internal, and it is a document someone reads only when a deck goes for approval — a
**strict** deck (MLR, B55), where a reviewer signs off the claims. In normal use nobody has
time to review it; it is still written as a log (Markdown and manifest, A6), but no PDF is
made and nobody is asked to read it.

So `gate2` and `gate3` call `write_report_pdf_if_strict`, which does nothing for a normal
deck. `autodeck audit-pdf RUN` makes one on request for any deck.

The Markdown is the source of truth and the PDF a faithful rendering of it: the converter
below handles exactly what `report.render` and `gate3.render_final_report` emit (headings,
paragraphs, lists, tables, blockquotes, rules, bold, italics, inline code) and escapes
everything else. No markup is interpreted beyond that, so a quote in the report can never
become HTML. LibreOffice, already required to render decks, turns the HTML into the PDF.
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

PDF_TIMEOUT_S = 120

_CSS = """
body { font-family: 'Carlito', 'Calibri', 'Liberation Sans', sans-serif; font-size: 10pt;
       line-height: 1.4; color: #1a1a1a; margin: 0; }
h1 { font-size: 18pt; margin: 0 0 6pt; }
h2 { font-size: 13pt; margin: 16pt 0 4pt; border-bottom: 1px solid #999; }
h3 { font-size: 11pt; margin: 12pt 0 4pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 9pt; }
th, td { border: 1px solid #bbb; padding: 3pt 5pt; vertical-align: top; text-align: left; }
th { background: #eee; }
blockquote { margin: 4pt 0 2pt 12pt; padding-left: 8pt; border-left: 3px solid #999;
             font-family: 'DejaVu Serif', serif; }
code { font-family: 'DejaVu Sans Mono', monospace; font-size: 9pt; }
hr { border: 0; border-top: 1px solid #ccc; margin: 10pt 0; }
"""


class ReportPdfError(RuntimeError):
    """The PDF could not be made (no LibreOffice, a conversion failure)."""


# -- Markdown (the report's subset) to HTML --------------------------------------------


def _inline(text: str) -> str:
    """Escape, then apply `code`, **bold** and *italics* — in that order, so the contents of
    a code span are never read as emphasis."""
    parts = re.split(r"(`[^`]+`)", text)
    out: list[str] = []
    for part in parts:
        if len(part) >= 2 and part.startswith("`") and part.endswith("`"):
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        escaped = html.escape(part)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", escaped)
        out.append(escaped)
    return "".join(out)


def _cells(row: str) -> list[str]:
    body = row.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells = re.split(r"(?<!\\)\|", body)
    return [c.strip().replace("\\|", "|") for c in cells]


def markdown_to_html(markdown: str, *, title: str = "Audit report") -> str:
    """The report's Markdown as a standalone HTML page. Deterministic."""
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append("<p>" + "<br>".join(_inline(p) for p in paragraph) + "</p>")
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush()
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if re.fullmatch(r"-{3,}|\*{3,}", stripped):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if (
            stripped.startswith("|")
            and i + 1 < len(lines)
            and re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?", lines[i + 1].strip())
        ):
            flush()
            header = _cells(stripped)
            rows: list[list[str]] = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            out.append(
                "<table><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in header) + "</tr>"
            )
            out.extend(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>"
                for row in rows
            )
            out.append("</table>")
            continue
        if stripped.startswith(">"):
            flush()
            quoted: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quoted.append(lines[i].strip()[1:].lstrip())
                i += 1
            out.append(
                "<blockquote>" + "<br>".join(html.escape(q) for q in quoted) + "</blockquote>"
            )
            continue
        if re.match(r"^\s*[-*]\s+", line):
            flush()
            items: list[tuple[int, str]] = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                indent = len(lines[i]) - len(lines[i].lstrip())
                items.append((indent, re.sub(r"^\s*[-*]\s+", "", lines[i])))
                i += 1
            out.append("<ul>")
            out.extend(
                f'<li style="margin-left:{indent * 6}pt">{_inline(text)}</li>'
                for indent, text in items
            )
            out.append("</ul>")
            continue
        paragraph.append(stripped)
        i += 1
    flush()
    body = "\n".join(out)
    return (
        '<!DOCTYPE html>\n<html><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head>"
        f"<body>\n{body}\n</body></html>\n"
    )


# -- PDF --------------------------------------------------------------------------------


def write_report_pdf(markdown: str, out_pdf: Path, *, title: str = "Audit report") -> Path:
    """Render `markdown` to `out_pdf` through LibreOffice. Returns the path written.

    Raises:
        ReportPdfError: LibreOffice is not installed, or the conversion failed.
    """
    from autodeck.render.qa.libreoffice import soffice_path

    try:
        soffice = soffice_path()
    except Exception as exc:  # the renderer's own "not installed" error
        raise ReportPdfError(f"LibreOffice is needed to make the PDF: {exc}") from exc
    out_pdf = Path(out_pdf)
    with tempfile.TemporaryDirectory(prefix="autodeck-report-") as scratch:
        source = Path(scratch) / (out_pdf.stem + ".html")
        source.write_text(markdown_to_html(markdown, title=title), encoding="utf-8")
        command = [
            soffice, "--headless", "--norestore", "--convert-to", "pdf:writer_web_pdf_Export",
            "--outdir", scratch, str(source),
        ]  # fmt: skip
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=PDF_TIMEOUT_S
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReportPdfError(f"LibreOffice could not convert the report: {exc}") from exc
        made = Path(scratch) / (out_pdf.stem + ".pdf")
        if result.returncode != 0 or not made.is_file():
            raise ReportPdfError(
                "LibreOffice did not produce a PDF "
                f"(exit {result.returncode}): {(result.stderr or result.stdout).strip()[:300]}"
            )
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(made), str(out_pdf))
    return out_pdf


def write_report_pdf_if_strict(
    markdown: str, out_pdf: Path, *, provenance: str, title: str = "Audit report"
) -> Path | None:
    """The PDF for a strict deck; nothing for a normal one (B84). Never raises: a failed PDF
    is reported by returning None and leaves the Markdown report, the record, intact."""
    if provenance != "strict":
        return None
    try:
        return write_report_pdf(markdown, out_pdf, title=title)
    except ReportPdfError:
        return None


__all__ = [
    "ReportPdfError",
    "markdown_to_html",
    "write_report_pdf",
    "write_report_pdf_if_strict",
]
