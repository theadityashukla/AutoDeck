"""Generate a real OOXML theme and write it into a PPTX package (D1).

The point of D1 is that a client can open the deck, add a slide by hand, and have it
inherit the look — and can see the brand palette in PowerPoint's own Design → Variants
colour UI. That only happens if the file contains a genuine `a:clrScheme` and
`a:fontScheme` in `ppt/theme/theme1.xml`. Colouring shapes one by one produces a deck that
looks right and behaves like a picture.

python-pptx has no API for authoring theme parts, so the theme XML is generated here and
substituted into the package by rewriting the zip entry. That is deliberate rather than a
workaround: the zip is the format, the substitution is explicit and inspectable, and it
keeps entry order under our control for A6's byte-comparability requirement later.

Inheritance itself needs no code here: python-pptx's bundled default master and layouts
reference the theme indirectly throughout (`+mj-lt`/`+mn-lt` for fonts, `schemeClr` for
colour, on every placeholder) rather than hardcoding a face or an RGB value, so swapping
`theme1.xml` is sufficient for a hand-added slide to inherit it. `tests/test_theme_master.py`
pins that property and proves it structurally and, for accent colours and font families, in
a real LibreOffice render (D5's headless loop). There is no PowerPoint in this environment
(B31): **the theme's colour/font pairing has not been observed in PowerPoint's own Design
panel, and one specific gap in the render loop below is known and unfixed — see
`_colour_value` and `tests/test_theme_master.py`'s module docstring.**

Owning phase: 0 (spike 0.4); productionised in Phase 3a (task 3a.1). See `extract.py` for
onboarding mode (a) — reading a theme back out of an existing client template, rather than
generating one from tokens as this module does.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from pptx import Presentation
from pptx.presentation import Presentation as PresentationType
from pptx.util import Emu

from autodeck.design.theme.tokens import DesignTokens

_THEME_PART = "ppt/theme/theme1.xml"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def build_theme_xml(tokens: DesignTokens) -> str:
    """Render `theme1.xml` for these tokens.

    The colour scheme uses `a:sysClr` for `dk1`/`lt1` where OOXML expects it — PowerPoint
    treats those two slots specially in the text/background UI, and a plain `srgbClr` there
    makes the Design panel show the pair in the wrong order.
    """
    scheme = tokens.palette.as_scheme()
    name = escape(tokens.name)

    colours = "".join(
        f"<a:{slot}>{_colour_value(slot, scheme[slot])}</a:{slot}>" for slot in scheme
    )

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<a:theme xmlns:a="{_A_NS}" name="{name}">'
        "<a:themeElements>"
        f'<a:clrScheme name="{name}">{colours}</a:clrScheme>'
        f'<a:fontScheme name="{name}">'
        f"{_font_list('major', tokens.typography.major)}"
        f"{_font_list('minor', tokens.typography.minor)}"
        "</a:fontScheme>"
        f"{_format_scheme(name)}"
        "</a:themeElements>"
        "<a:objectDefaults/><a:extraClrSchemeLst/>"
        "</a:theme>"
    )


def _colour_value(slot: str, hex_value: str) -> str:
    """`dk1`/`lt1` use `sysClr`+`lastClr`; every other slot is a plain `srgbClr`.

    **Known, unfixed gap, recorded rather than worked around (B31):** while writing 3a.1's
    inheritance tests, LibreOffice was observed to render `sysClr`'s literal system colour
    (plain black/white) for placeholder text, ignoring `lastClr` entirely — a title's text
    stayed black across every `dk1` value tried, and only turned the token's actual colour
    once this function was patched, locally, to emit a plain `srgbClr` there instead. That
    swap is **not** made here: it was never tried against real PowerPoint, and the whole
    reason `sysClr` is used is a PowerPoint-only behaviour (the Design panel's text/
    background pairing) that this environment cannot check either way. Swapping it would
    trade one unverified claim for another. The upshot: `tests/test_theme_master.py`'s
    render-marked tests confirm accent-colour and font inheritance, but **cannot** confirm
    that `dk1`/`lt1` reach hand-added slide text — that is one of the two PowerPoint-only
    checks carried to the owner at GATE 3.
    """
    if slot == "dk1":
        return f'<a:sysClr val="windowText" lastClr="{hex_value.upper()}"/>'
    if slot == "lt1":
        return f'<a:sysClr val="window" lastClr="{hex_value.upper()}"/>'
    return f'<a:srgbClr val="{hex_value.upper()}"/>'


def _font_list(kind: str, typeface: str) -> str:
    """A `majorFont`/`minorFont` entry.

    The empty `<a:ea/>` and `<a:cs/>` elements are required by the schema even when no
    East-Asian or complex-script face is specified; omitting them makes PowerPoint report
    the file as needing repair.
    """
    face = escape(typeface)
    return (
        f"<a:{kind}Font>"
        f'<a:latin typeface="{face}"/><a:ea typeface=""/><a:cs typeface=""/>'
        f"</a:{kind}Font>"
    )


def _format_scheme(name: str) -> str:
    """Fill, line, effect and background styles.

    Each list must contain exactly three entries — subtle, moderate, intense — or the
    package is invalid. These are kept deliberately flat: consulting decks are not the
    place for gradients and bevels, and a flat scheme means a shape recoloured from the
    palette looks the same whichever style slot it lands in.
    """
    solid = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    tinted = (
        '<a:solidFill><a:schemeClr val="phClr">'
        '<a:tint val="60000"/></a:schemeClr></a:solidFill>'
    )
    shaded = (
        '<a:solidFill><a:schemeClr val="phClr">'
        '<a:shade val="80000"/></a:schemeClr></a:solidFill>'
    )

    def line(width: int) -> str:
        return (
            f'<a:ln w="{width}" cap="flat" cmpd="sng" algn="ctr">'
            f'{solid}<a:prstDash val="solid"/><a:miter lim="800000"/>'
            "</a:ln>"
        )

    effects = "".join("<a:effectStyle><a:effectLst/></a:effectStyle>" for _ in range(3))

    return (
        f'<a:fmtScheme name="{name}">'
        f"<a:fillStyleLst>{solid}{tinted}{shaded}</a:fillStyleLst>"
        f"<a:lnStyleLst>{line(6350)}{line(12700)}{line(19050)}</a:lnStyleLst>"
        f"<a:effectStyleLst>{effects}</a:effectStyleLst>"
        f"<a:bgFillStyleLst>{solid}{tinted}{shaded}</a:bgFillStyleLst>"
        "</a:fmtScheme>"
    )


# ---------------------------------------------------------------------------
# Package assembly
# ---------------------------------------------------------------------------


def new_presentation(tokens: DesignTokens) -> PresentationType:
    """A blank presentation sized from the tokens, ready for component renderers."""
    presentation = Presentation()
    presentation.slide_width = Emu(tokens.slide_width_emu)
    presentation.slide_height = Emu(tokens.slide_height_emu)
    return presentation


def apply_theme(package: bytes, theme_xml: str) -> bytes:
    """Substitute `theme1.xml` inside a PPTX package.

    Entries are copied in their original order so the result differs from the input in
    exactly one part — which keeps the change reviewable and makes a later byte-comparison
    meaningful.
    """
    source = io.BytesIO(package)
    target = io.BytesIO()

    with zipfile.ZipFile(source) as original:
        if _THEME_PART not in original.namelist():
            raise ValueError(f"package has no {_THEME_PART}; cannot apply a theme")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as rewritten:
            for item in original.infolist():
                data = (
                    theme_xml.encode("utf-8")
                    if item.filename == _THEME_PART
                    else original.read(item.filename)
                )
                rewritten.writestr(item, data)

    return target.getvalue()


def save_themed(presentation: PresentationType, tokens: DesignTokens, path: Path) -> Path:
    """Write `presentation` to `path` with the tokens' theme applied.

    Fonts are checked first. Saving a deck that declares a family this machine does not
    have produces a file whose budgets were computed against nothing — so the check is
    here, at the boundary, rather than trusted to every caller.
    """
    tokens.require_fonts()

    buffer = io.BytesIO()
    presentation.save(buffer)
    themed = apply_theme(buffer.getvalue(), build_theme_xml(tokens))

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(themed)
    return path


def read_theme_xml(path: Path) -> str:
    """Read `theme1.xml` back out of a PPTX — used by tests and by the spike report."""
    with zipfile.ZipFile(Path(path)) as package:
        return package.read(_THEME_PART).decode("utf-8")
