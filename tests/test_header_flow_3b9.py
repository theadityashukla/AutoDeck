"""Header horizontal flow, 3b.9 additions: repeated syntax and storyline order.

Both are advisory (`FlowFinding`), like everything in `flow.py` — they never block a build.
Build decks in the style of `tests/test_headers.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.design.components.catalog import COMPONENT_LIB_VERSION
from autodeck.design.headers.flow import FlowFinding, flow_report
from autodeck.design.headers.profile import HeaderStyleProfile
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import Block, Deck, DeckBrief, KeyMessage, Slide
from autodeck.ir.store import IRStore
from autodeck.pipeline.orchestrator import Gate, Orchestrator
from tests.test_cli_gate2 import (
    CLIENT,
    PROJECT,
    ScriptedContent,
    content_draft,
    make_run,
    patch_content_model,
    run_content,
)

TOKENS = DesignTokens.load(Path("config/tokens/dev.json"))


def header_slide(
    slide_id: str, text: str | None, *, message_ids: list[str] | None = None
) -> Slide:
    """A `big_number` slide whose `headline` (the title-role slot) holds `text`. `None`
    leaves the slide without blocks, as a title, agenda or divider slide would be."""
    blocks = (
        []
        if text is None
        else [Block(id=f"{slide_id}-h", kind="section_header", slot="headline", text=text)]
    )
    return Slide(
        id=slide_id,
        narrative_role="evidence",
        component="big_number",
        blocks=blocks,
        message_ids=message_ids or [],
    )


def deck_of(*slides: Slide) -> Deck:
    return Deck(
        run_id="r1",
        project="p",
        client="c",
        audience="CTO",
        version=1,
        slides=list(slides),
        theme_ref="config/tokens/dev.json",
        component_lib_version="test",
    )


def brief_of(*message_ids: str) -> DeckBrief:
    return DeckBrief(
        run_id="r1",
        objective="Decide whether to ship.",
        audience="CTO",
        key_messages=[KeyMessage(id=m, text=f"Message {m}.") for m in message_ids],
        approved_by="tester",
    )


def serving(*message_ids: str) -> Deck:
    """One slide per entry, each with a distinct header, serving the given message id."""
    return deck_of(
        *(
            header_slide(f"s{i}", f"Number{i} distinct header", message_ids=[m])
            for i, m in enumerate(message_ids, start=1)
        )
    )


def storyline(deck: Deck, brief: DeckBrief) -> list[FlowFinding]:
    """Only the findings the storyline check produced (headers here never trip the others)."""
    return flow_report(deck, TOKENS, HeaderStyleProfile(), brief=brief).findings


def test_three_headers_sharing_an_opening_are_flagged_once_two_are_not() -> None:
    """Two headers opening "Costs fall…" → nothing; add a third → exactly one finding, on the
    third slide, naming all three slide ids and the opening "costs fall" (first two words).
    Punctuation and case differences do not split a group."""
    # The stub's own example ("Costs fall...", "Costs rise...", "Costs stabilise...") shares
    # only ONE word, so under OPENING_WORDS = 2 it is not repeated syntax at all. Pinned here
    # so the constant, not the example, is what the behaviour answers to.
    one_shared_word = deck_of(
        header_slide("s1", "Costs fall sharply in year one"),
        header_slide("s2", "Costs rise again after that"),
        header_slide("s3", "Costs stabilise by year three"),
    )
    assert flow_report(one_shared_word, TOKENS, HeaderStyleProfile()).findings == []

    two = deck_of(
        header_slide("s1", "Costs fall sharply in year one"),
        header_slide("s2", "Costs fall again after that"),
    )
    assert flow_report(two, TOKENS, HeaderStyleProfile()).findings == []

    same_two_words = deck_of(
        header_slide("s1", "Costs fall sharply in year one"),
        header_slide("s2", "Costs fall again after that"),
        header_slide("s3", "Costs fall by year three"),
    )
    [finding] = flow_report(same_two_words, TOKENS, HeaderStyleProfile()).findings
    assert finding.slide_id == "s3"
    assert "'costs fall'" in finding.detail
    assert "template" in finding.detail

    # Case and punctuation do not split a group; the opening is the first two words.
    noisy = deck_of(
        header_slide("s1", "COSTS fall, sharply"),
        header_slide("s2", "“Costs” Fall: again"),
        header_slide("s3", "costs fall… by year three"),
        header_slide("s4", "Revenue grows quickly"),
    )
    [finding] = flow_report(noisy, TOKENS, HeaderStyleProfile()).findings
    assert finding.slide_id == "s3"
    assert "'costs fall'" in finding.detail
    assert "s4" not in finding.detail

    # Later members of an existing group are named but add no further finding.
    four = deck_of(
        header_slide("s1", "Costs fall sharply"),
        header_slide("s2", "Costs fall again"),
        header_slide("s3", "Costs fall further"),
        header_slide("s4", "Costs fall once more"),
    )
    [finding] = flow_report(four, TOKENS, HeaderStyleProfile()).findings
    assert finding.slide_id == "s3"
    assert "s4" in finding.detail


def test_one_word_and_empty_headers_are_not_counted_as_syntax() -> None:
    deck = deck_of(
        header_slide("s1", "Costs"),
        header_slide("s2", "Costs"),
        header_slide("s3", "Costs!"),
        header_slide("s4", "..."),
        header_slide("s5", None),
    )
    findings = flow_report(deck, TOKENS, HeaderStyleProfile()).findings
    assert not any("template" in finding.detail for finding in findings)

    # Exact repeats of a multi-word header are repeated syntax too, alongside the existing
    # verbatim finding, which says something different.
    repeats = deck_of(
        header_slide("s1", "Serve better first"),
        header_slide("s2", "Serve better first"),
        header_slide("s3", "Serve better first"),
    )
    details = [f.detail for f in flow_report(repeats, TOKENS, HeaderStyleProfile()).findings]
    assert sum("template" in detail for detail in details) == 1
    assert sum("verbatim" in detail for detail in details) == 2


def test_slides_visiting_key_messages_out_of_order_are_flagged() -> None:
    """Brief messages m1, m2, m3; slides serve m1, m3, m2 → one finding on the m2 slide,
    phrased as a question, naming m2 (position 2) and m3 (position 3). Order m1, m2, m3 →
    none. m1, m3, m1, m3 → one finding (the second m1)."""
    brief = brief_of("m1", "m2", "m3")

    assert storyline(serving("m1", "m2", "m3"), brief) == []

    [finding] = storyline(serving("m1", "m3", "m2"), brief)
    assert finding.slide_id == "s3"
    assert "'m2' (position 2)" in finding.detail
    assert "'m3' (position 3)" in finding.detail
    assert finding.detail.endswith("?")

    [finding] = storyline(serving("m1", "m3", "m1", "m3"), brief)
    assert finding.slide_id == "s3"
    assert "'m1' (position 1)" in finding.detail

    # `furthest` is not lowered by a backwards step: m3, m1, m2 flags both m1 and m2.
    flagged = storyline(serving("m3", "m1", "m2"), brief)
    assert [f.slide_id for f in flagged] == ["s2", "s3"]
    assert all("'m3' (position 3)" in f.detail for f in flagged)

    # A slide serving several messages ranks at its earliest one.
    multi = deck_of(
        header_slide("s1", "Alpha distinct header", message_ids=["m2"]),
        header_slide("s2", "Bravo distinct header", message_ids=["m3", "m1"]),
    )
    [finding] = storyline(multi, brief)
    assert finding.slide_id == "s2"
    assert "'m1' (position 1)" in finding.detail
    assert "'m2' (position 2)" in finding.detail


def test_slides_without_messages_neither_advance_nor_break_the_order() -> None:
    """A title, agenda and divider with no `message_ids` interleaved anywhere → no
    storyline finding attributable to them."""
    brief = brief_of("m1", "m2")
    deck = deck_of(
        header_slide("title", "Title distinct header"),
        header_slide("s1", "One distinct header", message_ids=["m1"]),
        header_slide("agenda", "Agenda distinct header"),
        header_slide("s2", "Two distinct header", message_ids=["m2"]),
        header_slide("divider", "Divider distinct header"),
    )
    assert storyline(deck, brief) == []

    # And they do not reset or raise the high-water mark: the break is still found, on the
    # message-bearing slide, not on the unmessaged ones around it.
    broken = deck_of(
        header_slide("title", "Title distinct header"),
        header_slide("s1", "One distinct header", message_ids=["m2"]),
        header_slide("divider", "Divider distinct header"),
        header_slide("s2", "Two distinct header", message_ids=["m1"]),
    )
    assert [f.slide_id for f in storyline(broken, brief)] == ["s2"]


def test_a_message_id_missing_from_the_brief_is_flagged() -> None:
    brief = brief_of("m1", "m2")
    deck = deck_of(
        header_slide("s1", "One distinct header", message_ids=["m1"]),
        header_slide("s2", "Two distinct header", message_ids=["ghost"]),
        header_slide("s3", "Three distinct header", message_ids=["m2"]),
    )
    [finding] = storyline(deck, brief)
    assert finding.slide_id == "s2"
    assert "'ghost'" in finding.detail

    # An unknown id does not take part in the ordering: a known one beside it still does.
    mixed = deck_of(
        header_slide("s1", "One distinct header", message_ids=["m2"]),
        header_slide("s2", "Two distinct header", message_ids=["ghost", "m1"]),
    )
    findings = storyline(mixed, brief)
    assert [f.slide_id for f in findings] == ["s2", "s2"]
    assert "'ghost'" in findings[0].detail
    assert "position 1" in findings[1].detail


def test_without_a_brief_no_storyline_findings_and_existing_behaviour_is_unchanged() -> None:
    """`flow_report(deck, tokens, profile)` with no brief → same lines and findings as before
    3b.9 apart from repeated-opening findings (compare against a deck with distinct
    openings, where the output must be identical to the pre-3b.9 report)."""
    deck = deck_of(
        header_slide("s1", "Costs fall sharply", message_ids=["m3"]),
        header_slide("s2", "Revenue grows quickly", message_ids=["m1"]),
        header_slide("s3", "Margins widen steadily", message_ids=["ghost"]),
        header_slide("s4", "Margins widen steadily"),
        header_slide("s5", "Serve better first!"),
    )
    profile = HeaderStyleProfile.from_mapping({"terminal_punctuation": False})

    without = flow_report(deck, TOKENS, profile)
    # Exactly the pre-3b.9 findings: one verbatim repeat, one punctuation, nothing about
    # openings (only two headers share one) or the storyline.
    assert [(f.slide_id, f.detail) for f in without.findings] == [
        ("s4", "repeats slide s3's header verbatim: 'Margins widen steadily'"),
        ("s5", "ends in punctuation the style disallows: 'Serve better first!'"),
    ]
    assert [line.text for line in without.lines] == [
        "Costs fall sharply",
        "Revenue grows quickly",
        "Margins widen steadily",
        "Margins widen steadily",
        "Serve better first!",
    ]

    with_brief = flow_report(deck, TOKENS, profile, brief=brief_of("m1", "m2", "m3"))
    assert with_brief.lines == without.lines
    assert with_brief.findings[: len(without.findings)] == without.findings
    assert len(with_brief.findings) > len(without.findings)


def test_the_content_command_passes_the_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`autodeck content`'s printed flow report includes a storyline finding for an
    out-of-order deck — i.e. cli.py passes `brief=brief_doc`. Drive it the way
    `tests/test_owner_run.py` drives the CLI."""
    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    orchestrator = Orchestrator("r1", runs_root=runs_root, env="dev")
    orchestrator.ir.save_brief(brief_of("km1", "km2", "km3"), overwrite=True)

    def outline_slide(slide_id: str, message_id: str) -> Slide:
        return Slide(
            id=slide_id,
            narrative_role="evidence",
            component="quote",
            intent="State that the kernel rewrite raised training throughput.",
            message_ids=[message_id],
        )

    deck = Deck(
        run_id="r1",
        project=PROJECT,
        client=CLIENT,
        audience="CTO",
        version=1,
        slides=[
            outline_slide("s1", "km1"),
            outline_slide("s2", "km3"),
            outline_slide("s3", "km2"),
        ],
        theme_ref="config/tokens/dev.json",
        component_lib_version=COMPONENT_LIB_VERSION,
    )
    orchestrator.run_stage(
        "outline", lambda: f"wrote {orchestrator.save_ir(deck, overwrite=True)}", force=True
    )
    orchestrator.approve(Gate.OUTLINE)
    patch_content_model(monkeypatch, ScriptedContent(content_draft()))

    result = run_content(runs_root, knowledge_root, corpus_root)

    assert result.exit_code == 0, result.output
    assert IRStore(runs_root, "r1").load().version == 2
    assert "Header flow" in result.output
    assert "a storyline break, or a deliberate recap?" in result.output
    [line] = [line for line in result.output.splitlines() if "a storyline break, or" in line]
    assert line.lstrip().startswith("s3: ")
    assert "'km2' (position 2)" in line
    assert "'km3' (position 3)" in line
