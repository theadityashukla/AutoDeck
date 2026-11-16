"""IR store: golden-file round-trip, version immutability, and gate-review diffing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodeck.ir.models import Block, Citation, Claim, Deck, Slide
from autodeck.ir.store import IRStore, IRStoreError, diff_decks

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ir.json"


def load_sample() -> Deck:
    return Deck.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Golden-file round trip
# ---------------------------------------------------------------------------


def test_sample_ir_round_trips_byte_for_byte() -> None:
    """The golden file is the contract: parse -> model -> serialise must be identity.

    A drifting field order or a changed default would break A6's byte-comparability
    guarantee long before anyone renders anything, so it is checked on bytes.
    """
    original = FIXTURE.read_text(encoding="utf-8")
    deck = Deck.model_validate_json(original)
    reserialised = json.dumps(deck.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    assert reserialised == original


def test_sample_ir_is_structurally_sane() -> None:
    deck = load_sample()
    assert len(deck.slides) == 2
    assert len(deck.all_blocks()) == 7
    assert deck.blocking_blocks() == []
    # Every claim in the sample, notes included, carries evidence (A1).
    claims = [b.claim for b in deck.all_blocks() if b.claim is not None]
    assert claims and all(c.citations for c in claims)


def test_sample_ir_citation_hashes_verify() -> None:
    """Re-validating the fixture re-runs every hash check; a hand edit to a quote fails."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["slides"][0]["blocks"][0]["claim"]["citations"][0]["quote"] += " (edited)"
    with pytest.raises(Exception, match="does not match quote"):
        Deck.model_validate(payload)


# ---------------------------------------------------------------------------
# Store behaviour
# ---------------------------------------------------------------------------


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    deck = load_sample()
    store = IRStore(tmp_path, deck.run_id)
    path = store.save(deck)
    assert path == tmp_path / deck.run_id / "ir" / "v1.json"
    assert store.load() == deck
    assert store.load(1) == deck


def test_versions_and_next_version(tmp_path: Path) -> None:
    deck = load_sample()
    store = IRStore(tmp_path, deck.run_id)
    assert store.versions() == []
    assert store.next_version() == 1
    assert store.latest_version() is None

    store.save(deck)
    store.save(deck.model_copy(update={"version": 2}))
    assert store.versions() == [1, 2]
    assert store.latest_version() == 2
    assert store.next_version() == 3
    assert store.load().version == 2


def test_saved_versions_are_immutable(tmp_path: Path) -> None:
    """A gate approves bytes. Rewriting a version would invalidate that approval silently."""
    deck = load_sample()
    store = IRStore(tmp_path, deck.run_id)
    store.save(deck)
    with pytest.raises(IRStoreError, match="immutable"):
        store.save(deck)
    store.save(deck, overwrite=True)  # explicit override still available


def test_run_id_mismatch_is_refused(tmp_path: Path) -> None:
    deck = load_sample()
    store = IRStore(tmp_path, "some-other-run")
    with pytest.raises(IRStoreError, match="does not match store run"):
        store.save(deck)


def test_loading_a_missing_version_raises(tmp_path: Path) -> None:
    store = IRStore(tmp_path, "empty-run")
    with pytest.raises(IRStoreError, match="no IR versions"):
        store.load()
    with pytest.raises(IRStoreError, match="not found"):
        store.load(7)


@pytest.mark.parametrize("run_id", ["", "..", "a/b"])
def test_invalid_run_ids_are_refused(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(IRStoreError, match="invalid run_id"):
        IRStore(tmp_path, run_id)


# ---------------------------------------------------------------------------
# Diff — the gate-review surface
# ---------------------------------------------------------------------------


def _citation() -> Citation:
    return Citation.for_quote(
        doc_id="doc-1",
        page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
        quote="A verbatim source span.",
        retrieved_by="writer",
    )


def _slide(slide_id: str, text: str = "framing text") -> Slide:
    return Slide(
        id=slide_id,
        narrative_role="evidence",
        component="quote",
        blocks=[Block(id=f"{slide_id}-b1", kind="framing", slot="body", text=text)],
    )


def _deck(*slides: Slide, version: int = 1) -> Deck:
    return Deck(
        run_id="r1",
        project="p",
        client="c",
        audience="a",
        version=version,
        theme_ref="t",
        component_lib_version="0.1.0",
        slides=list(slides),
    )


def test_identical_decks_have_no_diff() -> None:
    assert diff_decks(load_sample(), load_sample()) == []


def test_diff_reports_a_changed_scalar() -> None:
    before = _deck(_slide("s1", "old text"))
    after = _deck(_slide("s1", "new text"))
    changes = diff_decks(before, after)
    assert [(c.path, c.kind) for c in changes] == [("slides[s1].blocks[s1-b1].text", "changed")]
    assert changes[0].before == "old text"
    assert changes[0].after == "new text"


def test_inserting_a_slide_is_one_addition_not_a_cascade() -> None:
    """Positional diffing would report every later slide as changed and train reviewers
    to skim — which is an accuracy problem at a gate, not a cosmetic one."""
    before = _deck(_slide("s1"), _slide("s2"), _slide("s3"))
    after = _deck(_slide("s1"), _slide("s_new"), _slide("s2"), _slide("s3"))
    changes = diff_decks(before, after)
    assert [(c.path, c.kind) for c in changes] == [("slides[s_new]", "added")]


def test_removing_a_slide_is_one_removal() -> None:
    before = _deck(_slide("s1"), _slide("s2"))
    after = _deck(_slide("s1"))
    assert [(c.path, c.kind) for c in diff_decks(before, after)] == [("slides[s2]", "removed")]


def test_reordering_slides_is_reported() -> None:
    """Invisible to an id-keyed comparison unless order is checked explicitly, and slide
    order *is* the argument (the horizontal-story test)."""
    before = _deck(_slide("s1"), _slide("s2"))
    after = _deck(_slide("s2"), _slide("s1"))
    changes = diff_decks(before, after)
    assert [(c.path, c.kind) for c in changes] == [("slides[order]", "changed")]
    assert changes[0].before == ["s1", "s2"]
    assert changes[0].after == ["s2", "s1"]


def test_diff_surfaces_a_verdict_change() -> None:
    """The shape of a GATE 2 review: what did validation change since I last looked?"""
    claim = Claim(text="A cited assertion.", citations=[_citation()])
    slide = Slide(
        id="s1",
        narrative_role="evidence",
        component="big_number",
        blocks=[Block(id="b1", kind="claim", slot="body", claim=claim)],
    )
    after_slide = slide.model_copy(deep=True)
    after_slide.blocks[0].claim = claim.model_copy(update={"verdict": "contradicted"})

    changes = diff_decks(_deck(slide), _deck(after_slide))
    assert [(c.path, c.kind, c.before, c.after) for c in changes] == [
        ("slides[s1].blocks[b1].claim.verdict", "changed", "unverified", "contradicted")
    ]


def test_change_renders_readably() -> None:
    before = _deck(_slide("s1", "old"))
    after = _deck(_slide("s1", "new"))
    assert str(diff_decks(before, after)[0]).startswith("~ slides[s1].blocks[s1-b1].text:")
