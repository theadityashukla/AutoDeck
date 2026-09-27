"""The post-render audit (task 3b.8) and rendered-text extraction.

Most tests render a clean deck, then tamper with the saved PPTX's XML directly — simulating a
pipeline stage that rewrote content — and assert the audit catches it. Tampering after render
is the honest test: it does not depend on a renderer bug existing.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest

from autodeck.audit import post_render
from autodeck.audit.post_render import post_render_audit
from autodeck.design.components import catalog
from autodeck.ir.models import (
    Block,
    ChartSeries,
    ChartSpec,
    Citation,
    Claim,
    Deck,
    Slide,
    SlideStyle,
    Verdict,
)
from autodeck.render.extract import ExtractionError
from autodeck.render.renderer import render_deck
from tests.test_renderer import tokens_for

# ---------------------------------------------------------------------------
# Fixture builders — deliberately independent of `test_renderer.py`'s (only
# `tokens_for` is shared) so this module's fixtures stand on their own.
# ---------------------------------------------------------------------------


def _citation(quote: str, **kw: Any) -> Citation:
    kw.setdefault("doc_id", "vendor-report")
    kw.setdefault("page", 4)
    kw.setdefault("bbox", (10.0, 20.0, 300.0, 44.0))
    kw.setdefault("retrieved_by", "validator")
    return Citation.for_quote(quote=quote, **kw)


def _claim(
    text: str, *, verdict: Verdict = "supported", citations: list[Citation] | None = None
) -> Claim:
    return Claim(text=text, citations=citations or [_citation(text)], verdict=verdict)


_ids = iter(f"b{n}" for n in range(1, 10_000))


def _claim_block(slot: str, text: str, **kw: Any) -> Block:
    return Block(id=next(_ids), kind="claim", slot=slot, claim=_claim(text, **kw))


def _framing_block(slot: str, text: str) -> Block:
    return Block(id=next(_ids), kind="framing", slot=slot, text=text)


def _payload_block(slot: str, kind: str, **payload: Any) -> Block:
    return Block(id=next(_ids), kind=kind, slot=slot, **payload)  # type: ignore[arg-type]


def _slide(
    slide_id: str,
    component: str,
    blocks: list[Block],
    *,
    speaker_notes: list[Block] | None = None,
    style: SlideStyle | None = None,
) -> Slide:
    return Slide(
        id=slide_id,
        narrative_role="test",
        component=component,
        blocks=blocks,
        speaker_notes=speaker_notes or [],
        style=style or SlideStyle(),
    )


def _deck(*slides: Slide) -> Deck:
    return Deck(
        run_id="r1",
        project="p",
        client="c",
        audience="a",
        version=1,
        theme_ref="t",
        component_lib_version=catalog.COMPONENT_LIB_VERSION,
        slides=list(slides),
    )


HEADLINE = "The rewrite reduces cost per token by 40%."
TAKEAWAY = "The kernel rewrite pays for itself in six weeks."
NOTES = "Internally, throughput improved 62.9% on the same benchmark."


def _sample_deck() -> Deck:
    """Two slides, a face claim with a numeral, a notes claim with a numeral."""
    slide1 = _slide(
        "s1",
        "bullets_supporting",
        [_claim_block("headline", HEADLINE), _framing_block("points", "A supporting point.")],
    )
    slide2 = _slide(
        "s2",
        "callout_takeaway",
        [_claim_block("takeaway", TAKEAWAY)],
        speaker_notes=[_claim_block("note", NOTES)],
    )
    return _deck(slide1, slide2)


def _render(deck: Deck, tmp_path: Path, name: str = "deck.pptx") -> Path:
    out_path = tmp_path / name
    render_deck(deck, tokens=tokens_for(), out_path=out_path)
    return out_path


def _chart_deck() -> Deck:
    citation = _citation("Cost per token fell to $0.42 in Q4.", doc_id="finance", page=2)
    chart = ChartSpec(
        chart_type="bar",
        categories=["Q4"],
        series=[ChartSeries(name="Cost per token ($)", values=[0.42])],
        source_citations=[citation],
    )
    slide = _slide(
        "s1",
        "chart_focus",
        [
            _framing_block("headline", "Cost per token fell every quarter"),
            _payload_block("chart", "chart", chart=chart),
        ],
    )
    return _deck(slide)


# ---------------------------------------------------------------------------
# Zip tampering — simulating a pipeline stage rewriting the saved PPTX
# ---------------------------------------------------------------------------


def _read_part(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name).decode("utf-8")


def _replace_part(path: Path, name: str, new_text: str) -> None:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        contents = {info.filename: archive.read(info.filename) for info in infos}
    contents[name] = new_text.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for info in infos:
            archive.writestr(info, contents[info.filename])


def _add_part(path: Path, name: str, data: bytes) -> None:
    with zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, data)


def _tamper_text(xml: str, old: str, new: str) -> str:
    count = xml.count(old)
    assert count == 1, f"expected exactly one occurrence of {old!r}, found {count}"
    return xml.replace(old, new, 1)


def _tamper_part(path: Path, name: str, old: str, new: str) -> None:
    xml = _read_part(path, name)
    _replace_part(path, name, _tamper_text(xml, old, new))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_a_clean_render_passes(tmp_path: Path) -> None:
    """`post_render_audit(deck, rendered)` passes with no findings and a passing A2 report."""
    deck = _sample_deck()
    pptx = _render(deck, tmp_path)

    report = post_render_audit(deck, pptx)

    assert report.numeric.passes
    assert report.findings == ()
    assert report.passes


def test_a_number_changed_after_render_is_caught_by_a2(tmp_path: Path) -> None:
    """Edit the slide XML so "40%" reads "45%". The numeric report blocks."""
    deck = _sample_deck()
    pptx = _render(deck, tmp_path)
    _tamper_part(pptx, "ppt/slides/slide1.xml", "40%", "45%")

    report = post_render_audit(deck, pptx)

    assert not report.numeric.passes
    assert any("45" in finding.detail for finding in report.numeric.blocking)


def test_a_word_changed_after_render_is_caught_with_no_number_involved(tmp_path: Path) -> None:
    """Edit "reduces" to "eliminates" in a claim. A2 passes (no numeral changed); the report
    has a "claim altered in render" finding naming both sentences — the check A2 cannot do."""
    deck = _sample_deck()
    pptx = _render(deck, tmp_path)
    _tamper_part(pptx, "ppt/slides/slide1.xml", "reduces", "eliminates")

    report = post_render_audit(deck, pptx)

    assert report.numeric.passes
    matching = [
        f
        for f in report.findings
        if f.check == "claim altered in render" and f.slide_id == "s1"
    ]
    assert len(matching) == 1
    assert HEADLINE in matching[0].detail
    assert not report.passes


def test_a_chart_value_changed_in_the_chart_xml_is_caught(tmp_path: Path) -> None:
    """Edit one `c:v` in the chart part's numCache. Extraction reads it and A2 blocks."""
    deck = _chart_deck()
    pptx = _render(deck, tmp_path)
    _tamper_part(pptx, "ppt/charts/chart1.xml", "<c:v>0.42</c:v>", "<c:v>0.99</c:v>")

    report = post_render_audit(deck, pptx)

    assert not report.numeric.passes
    assert any("0.99" in finding.detail for finding in report.numeric.blocking)


def test_a_notes_claim_changed_after_render_is_caught(tmp_path: Path) -> None:
    """Edit a notes-page claim; a "claim altered in render" finding for that slide."""
    deck = _sample_deck()
    pptx = _render(deck, tmp_path)
    _tamper_part(pptx, "ppt/notesSlides/notesSlide1.xml", "improved", "skyrocketed")

    report = post_render_audit(deck, pptx)

    matching = [
        f
        for f in report.findings
        if f.check == "claim altered in render" and f.slide_id == "s2"
    ]
    assert len(matching) == 1
    assert NOTES in matching[0].detail


@pytest.mark.parametrize("tamper", ["delete a slide", "duplicate a slide"])
def test_slide_set_changes_are_caught(tamper: str, tmp_path: Path) -> None:
    """A deleted slide gives "slide missing from render"; a duplicated slide's repeated tag
    raises `ExtractionError` — text that cannot be attributed cannot be audited."""
    deck = _sample_deck()
    pptx = _render(deck, tmp_path)

    if tamper == "delete a slide":
        presentation_xml = _read_part(pptx, "ppt/presentation.xml")
        assert '<p:sldId id="257" r:id="rId8"/>' in presentation_xml
        _replace_part(
            pptx,
            "ppt/presentation.xml",
            presentation_xml.replace('<p:sldId id="257" r:id="rId8"/>', ""),
        )

        report = post_render_audit(deck, pptx)

        assert any(
            f.check == "slide missing from render" and f.slide_id == "s2"
            for f in report.findings
        )
    else:
        _tamper_part(pptx, "ppt/slides/slide2.xml", 'name="autodeck:s2"', 'name="autodeck:s1"')

        with pytest.raises(ExtractionError):
            post_render_audit(deck, pptx)


def test_an_untagged_slide_cannot_be_audited(tmp_path: Path) -> None:
    """Clear one slide's `cSld/@name`: `post_render_audit` raises `ExtractionError`."""
    deck = _sample_deck()
    pptx = _render(deck, tmp_path)
    _tamper_part(pptx, "ppt/slides/slide1.xml", 'name="autodeck:s1"', 'name=""')

    with pytest.raises(ExtractionError):
        post_render_audit(deck, pptx)


def test_an_image_part_in_a_deck_without_figures_is_flagged(tmp_path: Path) -> None:
    """Add a `ppt/media/image1.png` part: an "image part without a figure" finding."""
    deck = _sample_deck()
    pptx = _render(deck, tmp_path)
    _add_part(pptx, "ppt/media/image1.png", b"not really a png, just bytes")

    report = post_render_audit(deck, pptx)

    assert any(f.check == "image part without a figure" for f in report.findings)


def test_disabling_claim_survival_lets_the_word_change_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Monkeypatch the survival comparison to always match; the "reduces" → "eliminates"
    tamper then passes. Proves the green above comes from the check."""
    deck = _sample_deck()
    pptx = _render(deck, tmp_path)
    _tamper_part(pptx, "ppt/slides/slide1.xml", "reduces", "eliminates")

    monkeypatch.setattr(post_render, "_claim_survives", lambda *_a, **_kw: True)

    report = post_render_audit(deck, pptx)

    assert report.passes
