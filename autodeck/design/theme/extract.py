"""Theme extraction from an existing PowerPoint template — onboarding mode (a).

Mode (a) exists for the client who mandates a corporate template: instead of generating a
theme from `tokens.json` (mode b, `master_builder.py`), the palette and fonts are read back
*out of* the client's own `.pptx`/`.potx` so their deck looks like their template rather than
a guess at it.

**This module is not proven against a real corporate template — Q5 is unanswered (B31).**
No such template exists in this environment, so the path here is exercised only against a
synthetic template this module can also build (`build_synthetic_template`). That proves the
extraction *code runs end to end* — parses a `theme1.xml`, produces a loadable
`DesignTokens`, round-trips back into a themed deck. **It proves nothing about the
malformed, decade-old templates real clients actually mandate**, which is the only
interesting case and the one this module cannot claim to handle. See this module's
docstrings for the specific ways a real template is expected to break this path (colour-map
remapping, non-scheme colours on the actual title/body placeholders, embedded rather than
referenced fonts) and the handover note for task 3a.1.

Only colour and font-family are extracted. An OOXML theme carries no type scale and no
spacing — `Typography`'s point sizes and `Spacing` come from `DesignTokens`' own defaults
regardless of what the template contains, which is itself a gap: a client template usually
implies a scale via its slide master's `txStyles`, and this path does not read it.

Owning phase: Phase 3a (task 3a.1).
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from autodeck.design.theme.master_builder import apply_theme, build_theme_xml, new_presentation
from autodeck.design.theme.tokens import DesignTokens, Palette, Typography

_THEME_PART = "ppt/theme/theme1.xml"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

#: Slot order `a:clrScheme` is required to declare, and the order `Palette.as_scheme()`
#: produces — see `master_builder.build_theme_xml`.
_SCHEME_SLOTS = (
    "dk1",
    "lt1",
    "dk2",
    "lt2",
    "accent1",
    "accent2",
    "accent3",
    "accent4",
    "accent5",
    "accent6",
    "hlink",
    "folHlink",
)

#: What this path cannot see in a template's theme XML, however well-formed it is. Surfaced
#: on every `ExtractedTheme` so a caller cannot use the result without also seeing the gap.
EXTRACTION_GAPS: tuple[str, ...] = (
    "type scale (display/title/heading/body/caption/minimum point sizes) has no OOXML theme "
    "representation and is left at DesignTokens' own defaults, not the template's; a "
    "client's real template usually implies a different scale via its slide master's "
    "txStyles, which this path does not read",
    "spacing (baseline/gutter/margins/safe area) has no theme-level representation and is "
    "left at DesignTokens' own defaults",
    "colour extraction reads the <a:clrScheme> child order directly and assumes it already "
    "matches the dk1/lt1/dk2/lt2/accent1-6/hlink/folHlink slots; it does not read the slide "
    "master's <p:clrMap>, so a template that remaps those slots (a dark corporate theme "
    "commonly swaps bg1/tx1 against dk1/lt1) would be extracted with dark1/light1 swapped "
    "and this path would not notice",
    "a font named in <a:fontScheme> is trusted as an installed, usable family name; a real "
    "template's font may be embedded in the file itself rather than merely referenced, or "
    "may be a face this machine does not have — DesignTokens.require_fonts() catches the "
    "latter loudly (B11) but only once someone calls it, not during extraction itself",
)


class TemplateExtractionError(RuntimeError):
    """The template file has no usable theme, or its theme XML does not parse."""


@dataclass(frozen=True)
class ExtractedTheme:
    """The result of reading a template's theme — tokens plus the honesty about them."""

    tokens: DesignTokens
    source: Path
    gaps: tuple[str, ...] = EXTRACTION_GAPS


def extract_theme_xml(path: Path) -> str:
    """Pull `ppt/theme/theme1.xml` out of a `.pptx`/`.potx` package, undecoded.

    Raises:
        TemplateExtractionError: the file is not a zip, or has no theme part.
    """
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as package:
            if _THEME_PART not in package.namelist():
                raise TemplateExtractionError(
                    f"{path} has no {_THEME_PART}; it is not a usable PowerPoint template"
                )
            return package.read(_THEME_PART).decode("utf-8")
    except zipfile.BadZipFile as exc:
        raise TemplateExtractionError(f"{path} is not a valid .pptx/.potx package") from exc


def extract_tokens(path: Path, *, name: str) -> ExtractedTheme:
    """Read colours and fonts out of a template's theme into a loadable `DesignTokens`.

    `name` becomes `DesignTokens.name` — the template's theme XML carries its own `name`
    attribute, but that is usually a generic Office default ("Office Theme") rather than
    anything a client would recognise, so the caller names it instead.

    Raises:
        TemplateExtractionError: no usable theme part, or the colour/font scheme is
            incomplete — both loud rather than silently defaulting a client's own colours.
    """
    xml = extract_theme_xml(path)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise TemplateExtractionError(f"{path}: theme1.xml does not parse as XML") from exc

    scheme_el = root.find(f".//{{{_A_NS}}}clrScheme")
    if scheme_el is None:
        raise TemplateExtractionError(f"{path}: theme1.xml has no <a:clrScheme>")

    colours: dict[str, str] = {}
    for child in scheme_el:
        slot = child.tag.rsplit("}", 1)[-1]
        value = _resolve_colour(child)
        if value is not None:
            colours[slot] = value

    missing = [slot for slot in _SCHEME_SLOTS if slot not in colours]
    if missing:
        raise TemplateExtractionError(
            f"{path}: <a:clrScheme> is missing slot(s) {missing} — an incomplete colour "
            "scheme, not something to fill in with a guess"
        )

    font_scheme_el = root.find(f".//{{{_A_NS}}}fontScheme")
    if font_scheme_el is None:
        raise TemplateExtractionError(f"{path}: theme1.xml has no <a:fontScheme>")
    major = _latin_typeface(font_scheme_el, "majorFont", path)
    minor = _latin_typeface(font_scheme_el, "minorFont", path)

    palette = Palette(
        dk1=colours["dk1"],
        lt1=colours["lt1"],
        dk2=colours["dk2"],
        lt2=colours["lt2"],
        accent1=colours["accent1"],
        accent2=colours["accent2"],
        accent3=colours["accent3"],
        accent4=colours["accent4"],
        accent5=colours["accent5"],
        accent6=colours["accent6"],
        hyperlink=colours["hlink"],
        followed_hyperlink=colours["folHlink"],
    )
    typography = Typography(major=major, minor=minor)
    tokens = DesignTokens(name=name, palette=palette, typography=typography)
    return ExtractedTheme(tokens=tokens, source=Path(path))


def _resolve_colour(slot_el: ET.Element) -> str | None:
    """A colour slot is either a direct `a:srgbClr` or a `a:sysClr` with `lastClr`."""
    srgb = slot_el.find(f"{{{_A_NS}}}srgbClr")
    if srgb is not None and srgb.get("val"):
        return srgb.get("val")
    sys_clr = slot_el.find(f"{{{_A_NS}}}sysClr")
    if sys_clr is not None and sys_clr.get("lastClr"):
        return sys_clr.get("lastClr")
    return None


def _latin_typeface(font_scheme_el: ET.Element, kind: str, path: Path) -> str:
    font_el = font_scheme_el.find(f"{{{_A_NS}}}{kind}")
    if font_el is None:
        raise TemplateExtractionError(f"{path}: <a:fontScheme> has no <a:{kind}>")
    latin = font_el.find(f"{{{_A_NS}}}latin")
    typeface = latin.get("typeface") if latin is not None else None
    if not typeface:
        raise TemplateExtractionError(f"{path}: <a:{kind}> has no <a:latin typeface=...>")
    return typeface


# ---------------------------------------------------------------------------
# Synthetic template — proves the path runs; proves nothing about a real one
# ---------------------------------------------------------------------------


def build_synthetic_template(path: Path, *, tokens: DesignTokens | None = None) -> Path:
    """Write a stand-in "corporate template" `.pptx` for exercising `extract_tokens`.

    This is a well-formed theme built the same way `master_builder` builds any other —
    identity `<p:clrMap>`, direct `<a:srgbClr>`/`<a:sysClr>` slots, one referenced (not
    embedded) font per major/minor role. **It is not a stand-in for a real client
    template.** The templates real clients mandate are the malformed, decade-old kind: a
    remapped `<p:clrMap>`, placeholders with direct colour/font overrides that ignore the
    theme entirely, embedded fonts, or a theme XML some now-unsupported version of
    PowerPoint wrote. None of that is reproduced here, so a pass against this file is
    evidence the code runs, not evidence it survives contact with a real one.
    """
    tokens = tokens or DesignTokens(
        name="Synthetic Corporate Template",
        palette=Palette(
            dk1="1B1B1B",
            lt1="FFFFFF",
            dk2="3C2A21",
            lt2="F7F0E8",
            accent1="8C2F39",
            accent2="D4A017",
            accent3="4C6E5D",
            accent4="3E5C76",
            accent5="6D435A",
            accent6="8A8D91",
            hyperlink="8C2F39",
            followed_hyperlink="6D435A",
        ),
        typography=Typography(major="Inter Display", minor="Inter"),
    )

    presentation = new_presentation(tokens)
    buffer = io.BytesIO()
    presentation.save(buffer)
    themed = apply_theme(buffer.getvalue(), build_theme_xml(tokens))

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(themed)
    return path
