"""Mode (a) — client corporate template: the extraction path (3a.1, B31, Q5).

**Read this before trusting anything in this file.** Every test here runs the extraction
path against a *synthetic* template this module builds itself
(`extract.build_synthetic_template`). That proves `extract_tokens` parses a real
`theme1.xml`, produces a loadable `DesignTokens`, and round-trips back into a themed deck —
i.e. that the code runs end to end. **It says nothing about a real client's mandated
template**, which per B31/Q5 does not exist in this environment and has never been tried
against this path — see this task's handover note for the owner-facing record of that gap,
and `extract.py`'s module docstring for the specific, concrete ways a real template is
expected to break it — a remapped `<p:clrMap>`, direct formatting on the placeholders
themselves, embedded fonts — none of which this synthetic fixture reproduces.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from autodeck.design.theme.extract import (
    EXTRACTION_GAPS,
    ExtractedTheme,
    TemplateExtractionError,
    build_synthetic_template,
    extract_theme_xml,
    extract_tokens,
)
from autodeck.design.theme.master_builder import build_theme_xml
from autodeck.design.theme.tokens import DesignTokens, Palette, Typography


def test_extracting_the_synthetic_templates_own_theme_round_trips(tmp_path: Path) -> None:
    """The path this task must prove runs: template on disk -> loadable `DesignTokens`."""
    template = build_synthetic_template(tmp_path / "synthetic.pptx")

    extracted = extract_tokens(template, name="Extracted Corp")

    assert isinstance(extracted, ExtractedTheme)
    assert extracted.tokens.name == "Extracted Corp"
    assert extracted.tokens.typography.major == "Inter Display"
    assert extracted.tokens.typography.minor == "Inter"
    # The extracted DesignTokens must itself be usable everywhere a hand-authored one is.
    assert DesignTokens.model_validate(extracted.tokens.model_dump())


def test_extraction_recovers_every_declared_palette_slot(tmp_path: Path) -> None:
    custom = DesignTokens(
        name="Custom",
        palette=Palette(
            dk1="101010",
            lt1="FAFAFA",
            dk2="202020",
            lt2="EAEAEA",
            accent1="AA1122",
            accent2="22AA33",
            accent3="3344AA",
            accent4="AA8811",
            accent5="7711AA",
            accent6="119999",
            hyperlink="AA1122",
            followed_hyperlink="7711AA",
        ),
        typography=Typography(major="Inter Display", minor="Inter"),
    )
    template = build_synthetic_template(tmp_path / "synthetic.pptx", tokens=custom)

    extracted = extract_tokens(template, name="Custom Extracted")

    assert extracted.tokens.palette == custom.palette


def test_extracted_tokens_produce_a_theme_xml_carrying_the_same_colours(tmp_path: Path) -> None:
    """The point of extraction — the result must be usable by `master_builder` like any
    other token set."""
    template = build_synthetic_template(tmp_path / "synthetic.pptx")
    extracted = extract_tokens(template, name="Extracted Corp")

    xml = build_theme_xml(extracted.tokens)

    assert extracted.tokens.palette.accent1.upper() in xml
    assert f'<a:latin typeface="{extracted.tokens.typography.major}"/>' in xml


def test_extraction_always_reports_its_gaps(tmp_path: Path) -> None:
    """A caller cannot get an `ExtractedTheme` without also seeing what it could not read.

    This is the mechanism, not just the docstring, for "do not describe mode (a) as done":
    the gaps travel with the result.
    """
    template = build_synthetic_template(tmp_path / "synthetic.pptx")
    extracted = extract_tokens(template, name="Extracted Corp")

    assert extracted.gaps == EXTRACTION_GAPS
    assert any("clrMap" in gap for gap in extracted.gaps)
    assert any("type scale" in gap for gap in extracted.gaps)


def test_extraction_fails_loudly_on_a_file_with_no_theme_part(tmp_path: Path) -> None:
    not_a_template = tmp_path / "empty.pptx"
    with zipfile.ZipFile(not_a_template, "w") as package:
        package.writestr("hello.txt", "not a template")

    with pytest.raises(TemplateExtractionError, match=r"theme1\.xml"):
        extract_theme_xml(not_a_template)
    with pytest.raises(TemplateExtractionError, match=r"theme1\.xml"):
        extract_tokens(not_a_template, name="x")


def test_extraction_fails_loudly_on_something_that_is_not_a_zip(tmp_path: Path) -> None:
    garbage = tmp_path / "garbage.pptx"
    garbage.write_bytes(b"this is not a zip file at all")

    with pytest.raises(TemplateExtractionError, match="not a valid"):
        extract_theme_xml(garbage)


def test_extraction_fails_loudly_on_an_incomplete_colour_scheme(tmp_path: Path) -> None:
    """An incomplete `<a:clrScheme>` is a malformed template, not something to guess at —
    exactly the "malformed, decade-old template" case B31 flags as the interesting one."""
    a_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    broken_theme = (
        f'<a:theme xmlns:a="{a_ns}" name="Broken">'
        "<a:themeElements>"
        '<a:clrScheme name="Broken">'
        '<a:dk1><a:srgbClr val="000000"/></a:dk1>'
        '<a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>'
        "</a:clrScheme>"
        '<a:fontScheme name="Broken">'
        '<a:majorFont><a:latin typeface="Inter Display"/></a:majorFont>'
        '<a:minorFont><a:latin typeface="Inter"/></a:minorFont>'
        "</a:fontScheme>"
        "</a:themeElements>"
        "</a:theme>"
    )
    broken = tmp_path / "broken.pptx"
    with zipfile.ZipFile(broken, "w") as package:
        package.writestr("ppt/theme/theme1.xml", broken_theme)

    with pytest.raises(TemplateExtractionError, match="missing slot"):
        extract_tokens(broken, name="x")


def test_the_synthetic_templates_module_docstring_disclaims_it() -> None:
    """Locks in the one non-negotiable line from the spec: nobody reading `extract.py` may
    come away thinking a synthetic template proves anything about a real one."""
    from autodeck.design.theme import extract

    assert extract.__doc__ is not None
    assert "proves nothing about the" in extract.__doc__
    assert "malformed, decade-old templates" in extract.__doc__
