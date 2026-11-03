"""The storyline check (B70): the headers read in order, as one argument a presenter can say."""

from __future__ import annotations

from typing import Any

from autodeck.agents.validation import (
    StorylineDraft,
    StorylineFindingDraft,
    check_storyline,
    story_line_of,
)
from autodeck.ir.models import Block, Deck, Slide

SYSTEM = "validator system prompt"


def _slide(slide_id: str, role: str, slot: str, text: str) -> Slide:
    return Slide(
        id=slide_id,
        narrative_role=role,
        component="title" if slot == "title" else "bullets_supporting",
        blocks=[Block(id="h1", kind="section_header", slot=slot, text=text)],
    )


def _deck(*slides: Slide) -> Deck:
    return Deck(
        run_id="r1", project="p", client="c", audience="CTO", version=1,
        slides=list(slides), theme_ref="dev", component_lib_version="1",
    )


def _story() -> Deck:
    return _deck(
        _slide("s1", "title", "title", "Should our next sequence models be Transformers?"),
        _slide("s2", "evidence", "headline", "Both Transformer sizes beat every earlier model, ensembles included"),
        _slide("s3", "mechanism", "headline", "Attention scores each query against every key"),
    )


class Scripted:
    def __init__(self, draft: StorylineDraft | None = None) -> None:
        self.draft = draft
        self.prompts: list[str] = []

    def complete_structured(self, prompt: str, response_model: type, *, system: str | None = None) -> Any:
        assert response_model is StorylineDraft
        assert system == SYSTEM
        self.prompts.append(prompt)
        if self.draft is None:
            raise RuntimeError("provider down")
        return self.draft


def _draft(*findings: StorylineFindingDraft, tells: bool = False) -> StorylineDraft:
    return StorylineDraft(tells_story=tells, summary="  A list of facts, not an argument.  ", findings=list(findings))


def test_headers_are_read_in_order_and_findings_are_recorded() -> None:
    deck = _story()
    model = Scripted(_draft(
        StorylineFindingDraft(slide_id="s2", issue="unspeakable", notes="Say: even the small model beat everything before it"),
        StorylineFindingDraft(slide_id="s3", issue="breaks_chain", notes="No header says what was wrong with recurrence"),
    ))
    assert check_storyline(deck, model=model, system=SYSTEM) == 1

    prompt = model.prompts[0]
    assert prompt.index("Should our next") < prompt.index("Both Transformer") < prompt.index("Attention scores")
    assert "Audience: CTO" in prompt
    check = deck.storyline_check
    assert check is not None and not check.tells_story
    assert check.summary == "A list of facts, not an argument."
    assert [(f.slide_id, f.issue) for f in check.findings] == [("s2", "unspeakable"), ("s3", "breaks_chain")]
    assert check.headlines == [story_line_of(s) for s in deck.slides]


def test_a_finding_for_an_unknown_slide_or_with_no_notes_is_dropped() -> None:
    deck = _story()
    model = Scripted(_draft(
        StorylineFindingDraft(slide_id="s99", issue="repeats", notes="invented slide"),
        StorylineFindingDraft(slide_id="s2", issue="repeats", notes="   "),
    ))
    check_storyline(deck, model=model, system=SYSTEM)
    assert deck.storyline_check is not None and deck.storyline_check.findings == []


def test_a_title_and_a_callout_takeaway_count_as_lines() -> None:
    slide = _slide("s1", "recommendation", "takeaway", "Pilot it before migrating")
    assert story_line_of(slide) == "Pilot it before migrating"
    assert story_line_of(_slide("s0", "title", "title", "A question")) == "A question"


def test_fewer_than_two_lines_is_not_judged() -> None:
    deck = _deck(_slide("s1", "title", "title", "Only a title"))
    model = Scripted(_draft())
    assert check_storyline(deck, model=model, system=SYSTEM) == 0
    assert model.prompts == [] and deck.storyline_check is None


def test_an_unchanged_storyline_is_reused_and_a_changed_one_is_judged_again() -> None:
    first = _story()
    check_storyline(first, model=Scripted(_draft(tells=True)), system=SYSTEM)

    unchanged = _story()
    idle = Scripted(_draft())
    assert check_storyline(unchanged, model=idle, system=SYSTEM, previous=first) == 0
    assert idle.prompts == [] and unchanged.storyline_check == first.storyline_check

    changed = _story()
    changed.slides[1].blocks[0].text = "Even the small Transformer beat every model before it"
    again = Scripted(_draft(tells=True))
    assert check_storyline(changed, model=again, system=SYSTEM, previous=first) == 1
    assert len(again.prompts) == 1


def test_a_failed_call_leaves_the_storyline_unjudged() -> None:
    deck = _story()
    assert check_storyline(deck, model=Scripted(None), system=SYSTEM) == 1
    assert deck.storyline_check is None


def test_a_broken_storyline_never_blocks_the_render() -> None:
    """Advisory by design: a weak story is a craft failure, not a false statement."""
    from autodeck.pipeline.orchestrator import assess_render_safety

    deck = _story()
    check_storyline(deck, model=Scripted(_draft(
        StorylineFindingDraft(slide_id="s3", issue="breaks_chain", notes="missing problem"),
    )), system=SYSTEM)
    assert deck.storyline_check is not None
    assert not any("storyline" in r or "s3" in r for r in assess_render_safety(deck).reasons)


def test_the_audit_report_shows_the_storyline_beside_the_summary() -> None:
    from autodeck.audit.report import build_audit_report, render

    deck = _story()
    check_storyline(deck, model=Scripted(_draft(
        StorylineFindingDraft(slide_id="s3", issue="breaks_chain", notes="No header says what was wrong with recurrence"),
    )), system=SYSTEM)
    text = render(build_audit_report(deck, brief=None))
    assert "## Storyline (advisory)" in text
    assert "does not yet tell one story" in text
    assert "`s3` · breaks chain: No header says what was wrong with recurrence" in text
