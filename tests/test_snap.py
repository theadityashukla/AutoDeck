"""B52: a near-verbatim quote is cited in the source's own words instead of being dropped.

The model's copy of a quote decides only *which passage* it was pointing at. The citation
always carries the document's verbatim text and hash (A1), and whether that passage supports
the sentence stays the validator's call (A3). A paraphrase, or a sentence the evidence does
not contain, still resolves to nothing.

Also covers the draft preview's placeholder for a slide whose required slot was emptied by a
dropped block — the case the first live run of B52's predecessor crashed on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation

from autodeck.agents.content import resolve_blocks
from autodeck.design.fonts import is_available
from autodeck.ingest.provenance import snap_span
from autodeck.ir.models import quote_digest
from autodeck.render import draft
from autodeck.render.draft import PLACEHOLDER_NAME, render_draft
from autodeck.render.qa.libreoffice import RenderError
from autodeck.retrieval.hybrid import RetrievedSpan
from tests.test_content import QUOTE, claim_block, element, store_with
from tests.test_renderer import _claim_block, _deck, _slide, tokens_for
from tests.test_verdicts import citation

SOURCE = (
    "In PIONEER 1-5, all three doses of oral semaglutide were associated with greater "
    "reductions in body weight compared with sitagliptin [ETD - 0.6\u00a0kg ( p < 0.05)] at "
    "week 26 (table 3) [47-49, 53-55], and these effects were sustained."
)


# -- the matcher -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        # A period added where the model cut the sentence short.
        (
            "all three doses of oral semaglutide were associated with greater reductions in "
            "body weight compared with sitagliptin.",
            "all three doses of oral semaglutide were associated with greater reductions in "
            "body weight compared with sitagliptin",
        ),
        # A stray extraction space tidied away.
        (
            "compared with sitagliptin [ETD - 0.6 kg (p < 0.05)] at week 26",
            "compared with sitagliptin [ETD - 0.6\u00a0kg ( p < 0.05)] at week 26",
        ),
        # Reference markers left out.
        (
            "at week 26 (table 3), and these effects were sustained",
            "at week 26 (table 3) [47-49, 53-55], and these effects were sustained",
        ),
    ],
)
def test_a_near_verbatim_quote_snaps_to_the_sources_words(quote: str, expected: str) -> None:
    found = snap_span(SOURCE, quote)
    assert found is not None
    (start, end), coverage = found
    assert SOURCE[start:end] == expected
    assert coverage >= 0.85


@pytest.mark.parametrize(
    "quote",
    [
        "Oral semaglutide is well tolerated and patients prefer it to injections overall.",
        "Weight fell.",  # too short to place with confidence
    ],
)
def test_a_paraphrase_or_a_short_quote_does_not_snap(quote: str) -> None:
    assert snap_span(SOURCE, quote) is None


def test_a_snap_never_cuts_a_word_in_half() -> None:
    found = snap_span(SOURCE, "ll three doses of oral semaglutide were associated with greater")
    assert found is not None
    (start, end), _ = found
    assert SOURCE[start:end].startswith("all three doses")


# -- the writer's citations ----------------------------------------------------------------


def _resolve(tmp_path: Path, text: str, quote: str, snapped: list[str] | None = None):
    store = store_with(tmp_path, element("e1", text, page=3))
    span = RetrievedSpan(
        doc_id="paper-1", element_id="e1", page=3, text=text, score=1.0, citable=True
    )
    rejections: list[str] = []
    blocks = resolve_blocks(
        [claim_block(quote=quote)],
        store=store,
        claims=[],
        spans=[span],
        location="slide s1 face",
        rejections=rejections,
        snapped=snapped,
    )
    return blocks, rejections


def test_a_writer_quote_off_by_a_period_is_cited_verbatim_and_reported(tmp_path: Path) -> None:
    text = f"{QUOTE[:-1]} [12, 13], with no loss in accuracy."
    snapped: list[str] = []
    blocks, rejections = _resolve(tmp_path, text, QUOTE, snapped)

    assert not rejections
    [block] = blocks
    assert block.claim is not None
    [cited] = block.claim.citations
    assert cited.quote == QUOTE[:-1]
    assert cited.quote_sha256 == quote_digest(QUOTE[:-1])
    assert cited.page == 3
    [note] = snapped
    assert note.startswith("slide s1 face:") and "not verbatim" in note


def test_a_paraphrased_writer_quote_is_still_dropped(tmp_path: Path) -> None:
    blocks, rejections = _resolve(tmp_path, QUOTE, "LLM.int8() halves memory usage.")
    assert blocks == []
    assert len(rejections) == 1


# -- the validator's quotes ----------------------------------------------------------------


def test_the_validator_finds_a_span_from_a_near_verbatim_quote() -> None:
    from autodeck.audit.verdicts import ValidatorEvidence

    span = citation(SOURCE)
    evidence = ValidatorEvidence([span])
    near = (
        "all three doses of oral semaglutide were associated with greater reductions in "
        "body weight compared with sitagliptin."
    )
    assert evidence.find(near) == span
    assert evidence.find("Patients preferred the oral form to every injectable.") is None


# -- the draft preview ---------------------------------------------------------------------


@pytest.mark.skipif(not is_available("Liberation Sans"), reason="needs Liberation Sans")
def test_a_slide_missing_a_required_slot_is_drawn_as_a_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        draft, "render_pptx", lambda *a, **k: (_ for _ in ()).throw(RenderError("no lo"))
    )
    deck = _deck(
        _slide("s1", "chart_focus", [_claim_block("headline", "Weight fell on every dose.")])
    )

    result = render_draft(deck, out_dir=tmp_path / "d", tokens=tokens_for())

    assert set(result.placeholders) == {"s1"}
    assert "chart" in result.placeholders["s1"]
    [slide] = Presentation(str(result.pptx)).slides
    names = {shape.name for shape in slide.shapes}
    assert PLACEHOLDER_NAME in names
