"""Advisory subjectless-point check and the cold-read gate on `finish` (B76)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodeck.agents.draft_checks import run_draft_checks
from autodeck.agents.tools.advisor import advisor_tools
from autodeck.agents.tools.deck import deck_tools
from autodeck.agents.tools.registry import ToolBox
from autodeck.agents.workspace import DeckWorkspace
from autodeck.ir.models import Block, Claim, Deck, Slide
from autodeck.providers.base import ToolCall
from autodeck.agents.content import ProposedBlock
from tests.test_agent_tools import brief_args, call, make_env
from tests.test_compose import QUOTE, claim_block, slide

# -- subjectless points ---------------------------------------------------------------


def _claim_block(block_id: str, slot: str, text: str) -> Block:
    return Block(
        id=block_id, kind="claim", slot=slot, claim=Claim(text=text, basis="unsourced")
    )


def _compare(*points: tuple[str, str], component: str = "two_column_compare") -> Slide:
    blocks = [
        Block(id="h", kind="framing", slot="headline", text="Two routes differ"),
        Block(id="lt", kind="framing", slot="left_title", text="Oral Semaglutide"),
        Block(id="rt", kind="framing", slot="right_title", text="Subcutaneous Semaglutide"),
    ]
    blocks += [_claim_block(f"p{i}", slot, text) for i, (slot, text) in enumerate(points)]
    return Slide(
        id="s1",
        narrative_role="argument",
        component=component,  # type: ignore[arg-type]
        intent="Compare the routes.",
        message_ids=["km1"],
        blocks=blocks,
    )


def _check(slide_: Slide):  # type: ignore[no-untyped-def]
    deck = Deck(
        run_id="r1",
        project="p",
        client="c",
        audience="CTO",
        version=1,
        slides=[slide_],
        theme_ref="config/tokens/dev.json",
        component_lib_version="test",
        provenance="normal",
    )
    return run_draft_checks(deck)


def _subjectless(result) -> list:  # type: ignore[no-untyped-def]
    return [a for a in result.advisories if a.kind == "subjectless_point"]


def test_a_point_that_never_names_its_side_gets_one_advisory() -> None:
    result = _check(_compare(("right_points", "No fasting requirement.")))
    found = _subjectless(result)
    assert len(found) == 1 and found[0].block_id == "p0"
    assert all(f.kind != "subjectless_point" for f in result.failures)


def test_a_short_label_and_colon_names_the_side() -> None:
    result = _check(_compare(("right_points", "s.c.: no fasting rule")))
    assert _subjectless(result) == []


def test_a_word_distinctive_to_the_column_names_the_side() -> None:
    result = _check(_compare(("right_points", "Subcutaneous: weekly injection")))
    assert _subjectless(result) == []
    result = _check(_compare(("left_points", "Oral dose needs fasting.")))
    assert _subjectless(result) == []


def test_only_the_shared_word_is_not_enough() -> None:
    result = _check(_compare(("right_points", "Semaglutide has no fasting requirement.")))
    assert len(_subjectless(result)) == 1


def test_a_non_compare_slide_gets_no_advisory() -> None:
    # The check keys off the compare slots, not the component name, so a bullets slide is
    # modelled by its own slots (no column titles).
    slide_ = Slide(
        id="s1",
        narrative_role="argument",
        component="bullets_supporting",
        intent="List.",
        message_ids=["km1"],
        blocks=[
            Block(id="h", kind="framing", slot="headline", text="Two routes differ"),
            _claim_block("p0", "points", "No fasting requirement."),
        ],
    )
    assert _subjectless(_check(slide_)) == []


# -- the cold-read gate ---------------------------------------------------------------


class Advisor:
    def complete(self, prompt: str, *, system: str | None = None) -> str:
        return "Looks fine."


def slide_args(sid: str = "s1") -> dict[str, Any]:
    """A `quote` slide that passes every draft check."""
    s = slide(
        sid,
        ["km1"],
        claim_block(f"{sid}b1", "Quantisation halves memory.", QUOTE),
        claim_block(f"{sid}b2", "Quantisation halves memory.", QUOTE, slot="quote"),
        ProposedBlock(id=f"{sid}b3", kind="framing", slot="attribution", text="Paper One"),
    )
    return {"slide": s.model_dump(mode="json")}


def _gated(tmp_path: Path, *, require: bool = True):  # type: ignore[no-untyped-def]
    ws, index, docs = make_env(tmp_path)
    tools = [*deck_tools(ws, require_cold_read=require)]
    tools += advisor_tools(ws, model=Advisor(), index=index, project=None)
    b = ToolBox(tools, state_key=lambda: ws.revision)
    call(b, "set_brief", **brief_args())
    # Show the passage so the slide passes its checks, then write it.
    from autodeck.agents.tools.corpus import corpus_tools
    from autodeck.agents.corpus_map import build_corpus_map
    from tests.test_agent_tools import CLAIMS

    cb = ToolBox(
        corpus_tools(ws, index=index, claims=CLAIMS, corpus_map=build_corpus_map(docs, CLAIMS)),
        state_key=lambda: ws.revision,
    )
    call(cb, "read_passage", doc_id="paper-1", page=4)
    assert not call(b, "write_slide", **slide_args()).error
    return ws, b


def _ask_all(b: ToolBox) -> Any:
    return call(
        b,
        "ask_advisor",
        question="Read cold.",
        slide_ids=["all"],
        headlines_only=True,
        include_notes=False,
        skills=[],
        pages=[],
    )


FIN: dict[str, Any] = {"coverage": [], "notes": "n"}


def test_finish_is_held_back_until_the_cold_read(tmp_path: Path) -> None:
    ws, b = _gated(tmp_path)
    held = call(b, "finish", **FIN)
    assert not held.finished and not held.error and "s1" in held.text
    assert "Not yet read" in held.text
    _ask_all(b)
    assert ws.cold_read == ["s1"]
    done = call(b, "finish", **FIN)
    assert done.finished


def test_a_slide_added_after_the_cold_read_holds_finish_again(tmp_path: Path) -> None:
    ws, b = _gated(tmp_path)
    _ask_all(b)
    assert not call(b, "write_slide", **slide_args("s2")).error
    held = call(b, "finish", **FIN)
    assert not held.finished
    assert "Not yet read: s2." in held.text and "s1" not in held.text.split("Not yet read:")[1]


def test_no_cold_read_needed_without_the_requirement(tmp_path: Path) -> None:
    _ws, b = _gated(tmp_path, require=False)
    assert call(b, "finish", **FIN).finished


def test_a_partial_read_does_not_count(tmp_path: Path) -> None:
    ws, b = _gated(tmp_path)
    call(
        b,
        "ask_advisor",
        question="q",
        slide_ids=["s1"],
        headlines_only=False,
        include_notes=False,
        skills=[],
        pages=[],
    )
    # s1 is every current slide, so naming it explicitly is a full read too.
    assert ws.cold_read == ["s1"]
    call(b, "write_slide", **slide_args("s2"))
    call(
        b,
        "ask_advisor",
        question="q",
        slide_ids=["s2"],
        headlines_only=False,
        include_notes=False,
        skills=[],
        pages=[],
    )
    assert ws.cold_read == ["s1"]  # unchanged: the s2-only ask is not a whole-deck read


def test_cold_read_round_trips(tmp_path: Path) -> None:
    ws, b = _gated(tmp_path)
    _ask_all(b)
    again = DeckWorkspace.from_json(ws.to_json(), ws.settings)
    assert again.cold_read == ["s1"] and again.cold_read_missing() == []
