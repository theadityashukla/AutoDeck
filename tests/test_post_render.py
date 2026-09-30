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
    DiagramAxis,
    DiagramSpec,
    LabelFraming,
    QuadrantItem,
    Slide,
    SlideStyle,
    TwoByTwoSpec,
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
        [_framing_block("label", "Takeaway"), _claim_block("takeaway", TAKEAWAY)],
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


# ---------------------------------------------------------------------------
# A2's caption exemption is exact, not a prefix
# ---------------------------------------------------------------------------

SOURCE_CLAIM = "Source: internal figures show a 40% improvement."


def _source_claim_deck() -> Deck:
    return _deck(
        _slide(
            "s1",
            "callout_takeaway",
            [_framing_block("label", "Takeaway"), _claim_block("takeaway", SOURCE_CLAIM)],
        )
    )


def test_a_clean_render_of_a_claim_beginning_with_source_passes(tmp_path: Path) -> None:
    deck = _source_claim_deck()
    report = post_render_audit(deck, _render(deck, tmp_path))
    assert report.passes


def test_a_claim_beginning_with_source_is_still_caught_by_a2(tmp_path: Path) -> None:
    """A claim whose own text begins "Source: " and whose number changes after render is
    still caught. A prefix match on "Source: " would have removed this whole line from the
    numeric linter's input; only the slide's real computed caption is exempt."""
    deck = _source_claim_deck()
    pptx = _render(deck, tmp_path)
    _tamper_part(pptx, "ppt/slides/slide1.xml", "40%", "45%")

    report = post_render_audit(deck, pptx)

    assert not report.numeric.passes
    assert any("45" in finding.detail for finding in report.numeric.blocking)


def test_the_old_prefix_strip_would_have_let_that_tamper_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Swap the exact-match strip for the prefix match it replaced; the same tamper then
    passes A2. Proves the catch above comes from the exact match."""
    deck = _source_claim_deck()
    pptx = _render(deck, tmp_path)
    _tamper_part(pptx, "ppt/slides/slide1.xml", "40%", "45%")

    def prefix_strip(_slide: Slide, text: str) -> str:
        return "\n".join(line for line in text.split("\n") if not line.startswith("Source: "))

    monkeypatch.setattr(post_render, "_strip_caption_lines", prefix_strip)

    assert post_render_audit(deck, pptx).numeric.passes


# ---------------------------------------------------------------------------
# A diagram node survives in two parts: its label on the face, its claim in the notes
# ---------------------------------------------------------------------------

NODE_CLAIM = "Enterprise accounts renewed at 92% across the last four quarters measured."


def _node_claim_deck() -> Deck:
    citation = _citation(NODE_CLAIM, doc_id="q3-segmentation-report", page=6)
    diagram = DiagramSpec(
        relationship="classification",
        kind="two_by_two",
        two_by_two=TwoByTwoSpec(
            x_axis=DiagramAxis(name="Cost to serve", low="Low", high="High"),
            y_axis=DiagramAxis(name="Adoption speed", low="Slow", high="Fast"),
            items=[
                QuadrantItem(
                    id="self_serve",
                    label="Self-serve",
                    x=0.15,
                    y=0.85,
                    framing=LabelFraming(reason="category_name"),
                ),
                QuadrantItem(
                    id="enterprise",
                    label="Enterprise",
                    x=0.85,
                    y=0.25,
                    claim=Claim(text=NODE_CLAIM, citations=[citation], verdict="supported"),
                ),
            ],
        ),
    )
    return _deck(
        _slide(
            "s1",
            "framework_diagram",
            [
                _framing_block("headline", "Deals justify the higher cost to serve"),
                _payload_block("diagram", "diagram", diagram=diagram),
            ],
        )
    )


def test_a_clean_render_of_a_diagram_node_claim_has_no_findings(tmp_path: Path) -> None:
    """The case that failed on every clean render before: label != claim text. Now the label
    is checked on the face and the claim in the notes, and the slide's real caption
    ("Source: q3-segmentation-report p.6") is exempt from A2 as chrome."""
    deck = _node_claim_deck()
    report = post_render_audit(deck, _render(deck, tmp_path))

    assert report.findings == ()
    assert report.numeric.passes


def test_a_diagram_node_claim_changed_in_the_notes_is_caught(tmp_path: Path) -> None:
    deck = _node_claim_deck()
    pptx = _render(deck, tmp_path)
    _tamper_part(pptx, "ppt/notesSlides/notesSlide1.xml", "renewed", "churned")

    report = post_render_audit(deck, pptx)

    matching = [f for f in report.findings if f.check == "claim altered in render"]
    assert len(matching) == 1
    assert NODE_CLAIM in matching[0].detail
    assert "notes" in matching[0].detail


def test_a_diagram_node_label_changed_on_the_face_is_caught(tmp_path: Path) -> None:
    deck = _node_claim_deck()
    pptx = _render(deck, tmp_path)
    _tamper_part(pptx, "ppt/slides/slide1.xml", "<a:t>Enterprise</a:t>", "<a:t>Corporate</a:t>")

    report = post_render_audit(deck, pptx)

    matching = [f for f in report.findings if f.check == "claim altered in render"]
    assert len(matching) == 1
    assert "'Enterprise'" in matching[0].detail
    assert "face" in matching[0].detail


# ---------------------------------------------------------------------------
# An agenda's numbers are list formatting, so a clean agenda render passes outright
# ---------------------------------------------------------------------------


def _agenda_deck() -> Deck:
    return _deck(
        _slide(
            "s1",
            "agenda",
            [
                _framing_block("headline", "Three sessions outline the full analysis"),
                _framing_block("items", "Where the original architecture left headroom."),
                _framing_block("items", "The rewrite: what changed, and what stayed."),
                _framing_block("items", "The impact by the numbers."),
            ],
        )
    )


def test_a_clean_agenda_render_passes_the_whole_audit(tmp_path: Path) -> None:
    """Before the numbers became native list formatting, this failed A2 on "1", "2", "3":
    digits the renderer had composed into the text and no IR block held."""
    deck = _agenda_deck()
    report = post_render_audit(deck, _render(deck, tmp_path))

    assert report.numeric.passes
    assert report.numeric.blocking == []
    assert report.findings == ()
    assert report.passes


def test_typed_digits_added_to_an_agenda_item_after_render_are_still_caught(
    tmp_path: Path,
) -> None:
    """Native numbering is not a blind spot for real digits: a number typed into the text is
    text, and A2 sees it."""
    deck = _agenda_deck()
    pptx = _render(deck, tmp_path)
    _tamper_part(
        pptx,
        "ppt/slides/slide1.xml",
        "The impact by the numbers.",
        "The impact by the numbers: 73%.",
    )

    report = post_render_audit(deck, pptx)

    assert not report.numeric.passes
