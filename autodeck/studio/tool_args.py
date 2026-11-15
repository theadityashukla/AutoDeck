"""The lead's tool vocabulary: one pydantic argument model per tool (Phase 1).

The closed-vocabulary pattern of v2's `ToolBox`: every tool has an argument model, the
model's call is validated against it, and bad arguments come back to the model as an error
*result* it can read and correct, never as an exception (`agents/tools/registry.py`).

The descriptions on these fields are part of the tool schema the model sees, so they are
written for the model: short, imperative, and in the product's terms. Every deck tool takes
an optional `artifact_id`; omitted, it means the engagement's only deck
(`tools.resolve_artifact`).

Phase 1 was one model writing every layer, so `write_slide` took the whole slide. Phase 2-3
splits it (plan §6.2): the lead writes a slide's brief (`SetSlideBriefArgs`) and asks the
designer to compose it (`ComposeSlidesArgs`); only the designer's own tool
(`DesignedSlideInput`) carries blocks and a layout. `WriteSlideArgs` and
`SetDesignConceptArgs` remain defined for old thread logs and the bench, but no toolbox
offers them any more. The system layer's tool (`SetPaletteArgs`), the mechanic's handoff
(`HandToLeadArgs`) and the router's answer (`RouteArgs`) are here too.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autodeck.ir.models import ColorToken, FreeLayout
from autodeck.studio.conversation import MAX_LABEL_CHARS, MAX_SUMMARY_CHARS
from autodeck.studio.design import DesignDirection, TextPair
from autodeck.studio.models import (
    MAX_HEADER_CHARS,
    PROPOSAL_ID_PATTERN,
    SEGMENT_PATTERN,
    Block,
    DesignPalette,
    Marker,
    OptionId,
    Slide,
    SlideBrief,
)

ARTIFACT_ID_HELP = "The deck's id. Omit it when the engagement has one deck."
MARKER_HELP = (
    "decided only when the owner chose or accepted this; provisional when you filled it in "
    "so the work could continue."
)

SLIDE_FIELDS_HELP = (
    "The whole slide. Its only fields are: id, intent, blocks, speaker_notes, layout, marker "
    "and serves. There is no field for a rationale or any other commentary: say why in your "
    "reply, or put what the slide must do in intent."
)

MARK_TARGET_PATTERN = r"^(brief|storyline|design_concept|slide:[^\s]+)$"
"""`set_marker` targets: a deck-level part, or `slide:<slide id>`."""


class ToolArgs(BaseModel):
    """Base of every argument model: an invented argument fails validation."""

    model_config = ConfigDict(extra="forbid")


class DeckToolArgs(ToolArgs):
    artifact_id: str | None = Field(default=None, description=ARTIFACT_ID_HELP)


# -- reading state ---------------------------------------------------------------------


class ViewDeckArgs(DeckToolArgs):
    """`view_deck`: the deck in compact form (brief, storyline, concept, slide list)."""


class ViewSlideArgs(DeckToolArgs):
    """`view_slide`: one slide in full (blocks, layout, notes) and its layout check."""

    slide_id: str = Field(min_length=1)


# -- reading sources --------------------------------------------------------------------


class ListSourcesArgs(ToolArgs):
    """`list_sources`: what this engagement can read."""


class ReadSourceArgs(ToolArgs):
    """`read_source`: a knowledge file (a window of it) or a document (its outline, or one
    page)."""

    source_id: str = Field(
        min_length=1, description="An id from list_sources, e.g. 'knowledge:client/client.md'."
    )
    page: int | None = Field(
        default=None,
        ge=1,
        description="Documents only: the page to read. Omit for the outline.",
    )
    offset: int = Field(
        default=0, ge=0, description="Knowledge files only: the character to start from."
    )


class SearchSourcesArgs(ToolArgs):
    """`search_sources`: passages that match a query, from knowledge files and documents."""

    query: str = Field(min_length=1, description="What to look for, in the sources' words.")
    limit: int = Field(default=6, ge=1, le=12, description="Passages to return, 1 to 12.")


# -- editing the deck ---------------------------------------------------------------------


class CreateDeckArgs(ToolArgs):
    """`create_deck`: start the engagement's deck. Only when it has none."""

    artifact_id: str = Field(
        pattern=SEGMENT_PATTERN,
        description="A short id for the deck: lower-case words joined by hyphens.",
    )
    title: str = Field(default="", description="The deck's working title.")


class SetBriefArgs(DeckToolArgs):
    """`set_brief`: who the deck is for and what it must achieve. Fields left out keep
    their current value; at least one of title, audience, goal and notes is given."""

    title: str | None = Field(default=None, description="The deck's title.")
    audience: str | None = None
    goal: str | None = None
    notes: str | None = Field(default=None, description="Anything else about the job.")
    marker: Marker = Field(default="provisional", description=MARKER_HELP)

    @model_validator(mode="after")
    def _something_to_set(self) -> SetBriefArgs:
        if all(v is None for v in (self.title, self.audience, self.goal, self.notes)):
            raise ValueError("give at least one of title, audience, goal, notes")
        return self


class StorylinePointInput(ToolArgs):
    id: str | None = Field(
        default=None,
        description="Keep an existing point's id when rewording it; omit for a new point.",
    )
    text: str = Field(min_length=1, description="One step of the argument, as a sentence.")


class SetStorylineArgs(DeckToolArgs):
    """`set_storyline`: the whole argument, in order. Replaces the current storyline."""

    points: list[StorylinePointInput] = Field(min_length=1)
    marker: Marker = Field(default="provisional", description=MARKER_HELP)


class SetDesignConceptArgs(DeckToolArgs):
    """`set_design_concept`: the deck's visual idea in one or two sentences, no tokens."""

    text: str = Field(min_length=1)
    marker: Marker = Field(default="provisional", description=MARKER_HELP)


class WriteSlideArgs(DeckToolArgs):
    """`write_slide`: one whole slide. An id already in the deck replaces that slide."""

    slide: Slide = Field(description=SLIDE_FIELDS_HELP)
    position: int | None = Field(
        default=None,
        ge=1,
        description="1-based place in the deck. Omit to keep a replaced slide where it is, "
        "or to add a new one at the end.",
    )


class SetBlockTextArgs(DeckToolArgs):
    """`set_block_text`: new text for one text block."""

    slide_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class RemoveSlideArgs(DeckToolArgs):
    """`remove_slide`: take a slide out of the deck."""

    slide_id: str = Field(min_length=1)


class MoveSlideArgs(DeckToolArgs):
    """`move_slide`: put a slide at a new 1-based position."""

    slide_id: str = Field(min_length=1)
    position: int = Field(ge=1)


class SetMarkerArgs(DeckToolArgs):
    """`set_marker`: mark a part decided or provisional (for example when the owner says
    they like a slide)."""

    target: str = Field(
        pattern=MARK_TARGET_PATTERN,
        description="brief, storyline, design_concept, or slide:<slide id>.",
    )
    marker: Marker


# -- proposing ----------------------------------------------------------------------------


class CandidateSlideInput(ToolArgs):
    """One candidate slide and what applying it does. Give exactly one of `replaces` and
    `insert_at`."""

    slide: Slide = Field(
        description="The whole candidate slide. Rendered for the owner, not in the deck "
        "until the option is applied."
    )
    replaces: str | None = Field(
        default=None,
        min_length=1,
        description="The id of an existing slide this candidate replaces. When applied it "
        "takes that slide's place and keeps that slide's id (and its storyline links, if "
        "the candidate names none). Must exist in the deck now.",
    )
    insert_at: int | None = Field(
        default=None,
        ge=1,
        description="Instead of replaces: the 1-based position the candidate is inserted "
        "at, as a new slide whose id is not yet in the deck.",
    )

    @model_validator(mode="after")
    def _replace_or_insert(self) -> CandidateSlideInput:
        if (self.replaces is None) == (self.insert_at is None):
            raise ValueError(
                "say what applying this candidate does: give exactly one of `replaces` "
                "(the id of the slide it replaces) or `insert_at` (the position it is "
                "inserted at)"
            )
        return self


class ProposeOptionInput(ToolArgs):
    label: str = Field(
        min_length=1, max_length=MAX_LABEL_CHARS, description="A few words naming the option."
    )
    text: str = Field(min_length=1, description="What the option is, in two or three lines.")
    slides: list[CandidateSlideInput] = Field(
        default_factory=list,
        description="Candidate slides to show it. Each must say whether it replaces an "
        "existing slide (`replaces`) or is inserted at a position (`insert_at`).",
    )


class ProposeArgs(DeckToolArgs):
    """`propose`: offer the owner two to four options without changing the deck. One option
    is allowed for a single described change with a preview. Every candidate slide says
    whether it replaces an existing slide or is inserted at a position."""

    summary: str = Field(
        min_length=1,
        max_length=MAX_SUMMARY_CHARS,
        description="What is being decided, in one line.",
    )
    options: list[ProposeOptionInput] = Field(min_length=1, max_length=4)


class ApplyOptionArgs(ToolArgs):
    """`apply_option`: do what the chosen option's candidate slides were proposed to do
    (replace the named slides, insert at the stated positions), once the owner has chosen
    it."""

    proposal_id: str = Field(pattern=PROPOSAL_ID_PATTERN)
    option_id: OptionId


# -- undo, redo, skills --------------------------------------------------------------------


class UndoArgs(DeckToolArgs):
    """`undo`: reverse the most recent change to the deck that is still live."""


class RedoArgs(DeckToolArgs):
    """`redo`: re-apply the most recently undone change, if nothing was changed since."""


class LoadSkillArgs(ToolArgs):
    """`load_skill`: read one deck-craft skill."""

    name: str = Field(min_length=1, description="A skill name from the list in your prompt.")


# ---------------------------------------------------------------------------
# Phase 2-3: briefs, composition, design, small edits, handoff, routing
# ---------------------------------------------------------------------------

SLIDE_ID_HELP = (
    "A short slide id: lower-case letters, digits and hyphens, e.g. 's1' or 'the-ask'. An id "
    "already in the deck updates that slide."
)
SLIDE_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


class SetSlideBriefArgs(DeckToolArgs):
    """`set_slide_brief`: create a slide from a brief, or update a slide's brief. Words only:
    the designer decides what the slide looks like (call compose_slides)."""

    slide_id: str = Field(pattern=SLIDE_ID_PATTERN, max_length=40, description=SLIDE_ID_HELP)
    brief: SlideBrief = Field(
        description="header: the talking headline, one line, shown word for word. intent: "
        "what the audience must conclude. content: points (short lines), figures (value and "
        "label), optional chart (kind bar|column|line, categories, series, emphasis). notes: "
        "what matters most, for the designer; not shown."
    )
    position: int | None = Field(
        default=None,
        ge=1,
        description="1-based place in the deck. Omit to keep an existing slide where it is, "
        "or to add a new one at the end.",
    )
    serves: list[str] | None = Field(
        default=None, description="Storyline point ids this slide serves. Omit to keep."
    )


class ComposeSlidesArgs(DeckToolArgs):
    """`compose_slides`: ask the designer to design or redesign slides from their briefs in
    the deck's design system."""

    slide_ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=30,
        description="Slides to design or redesign. Omit for every slide that is stale or "
        "not designed yet.",
    )


class ProposeDesignArgs(DeckToolArgs):
    """`propose_design`: offer two or three design directions, each rendered on real slides
    of this deck, without changing anything."""

    summary: str = Field(
        min_length=1, max_length=MAX_SUMMARY_CHARS, description="What is being decided."
    )
    directions: list[DesignDirection] = Field(
        min_length=2,
        max_length=3,
        description="Two or three clearly different directions: name, concept, 3-5 rules. "
        "Words only; the system layer picks the colours.",
    )
    sample_slide_ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=3,
        description="Up to three slides (with briefs) to render each direction on. Omit for "
        "the first three slides that have briefs.",
    )


class ApplyDesignArgs(DeckToolArgs):
    """`apply_design`: adopt a design as the deck's decided design system. Give either a
    proposal and option the owner chose, or a direction described in words."""

    proposal_id: str | None = Field(default=None, pattern=PROPOSAL_ID_PATTERN)
    option_id: OptionId | None = None
    direction: DesignDirection | None = Field(
        default=None, description="Instead of a proposal option: a direction in words."
    )

    @model_validator(mode="after")
    def _one_form(self) -> ApplyDesignArgs:
        by_option = self.proposal_id is not None and self.option_id is not None
        partial = (self.proposal_id is None) != (self.option_id is None)
        if partial or by_option == (self.direction is not None):
            raise ValueError(
                "give either proposal_id and option_id together, or a direction, not both"
            )
        return self


class RetitleSlideArgs(DeckToolArgs):
    """`retitle_slide`: give a slide a new header, keeping its design."""

    slide_id: str = Field(min_length=1)
    header: str = Field(min_length=1, max_length=MAX_HEADER_CHARS, description="One line.")

    @model_validator(mode="after")
    def _one_line(self) -> RetitleSlideArgs:
        if "\n" in self.header or not self.header.strip():
            raise ValueError("a header is one non-blank line")
        return self


class SwapSlidesArgs(DeckToolArgs):
    """`swap_slides`: exchange the positions of two slides."""

    first: str = Field(min_length=1, description="A slide id.")
    second: str = Field(min_length=1, description="Another slide id.")

    @model_validator(mode="after")
    def _distinct(self) -> SwapSlidesArgs:
        if self.first == self.second:
            raise ValueError("name two different slides")
        return self


class HandToLeadArgs(ToolArgs):
    """`hand_to_lead`: this request is bigger than a small edit; give the turn to the lead."""

    reason: str = Field(
        min_length=1, max_length=MAX_SUMMARY_CHARS, description="Why, in one line."
    )


class CandidateBriefInput(ToolArgs):
    """One candidate slide of a `propose` option, as a brief: the designer composes it
    before the proposal is recorded, so the owner sees it rendered. Give exactly one of
    `replaces` and `insert_at`."""

    slide_id: str = Field(pattern=SLIDE_ID_PATTERN, max_length=40, description=SLIDE_ID_HELP)
    brief: SlideBrief
    replaces: str | None = Field(
        default=None, min_length=1, description="The id of the existing slide it replaces."
    )
    insert_at: int | None = Field(
        default=None, ge=1, description="Instead: the 1-based position it is inserted at."
    )

    @model_validator(mode="after")
    def _replace_or_insert(self) -> CandidateBriefInput:
        if (self.replaces is None) == (self.insert_at is None):
            raise ValueError("give exactly one of `replaces` or `insert_at`")
        return self


class ProposeBriefOptionInput(ToolArgs):
    label: str = Field(
        min_length=1, max_length=MAX_LABEL_CHARS, description="A few words naming the option."
    )
    text: str = Field(min_length=1, description="What the option is, in two or three lines.")
    slides: list[CandidateBriefInput] = Field(
        default_factory=list,
        max_length=3,
        description="Candidate slides as briefs; the designer renders each before the "
        "owner sees the proposal.",
    )


class ProposeBriefsArgs(DeckToolArgs):
    """`propose` (Phase 2-3): offer the owner options without changing the deck. Candidate
    slides are briefs the designer composes; the lead never writes a layout."""

    summary: str = Field(
        min_length=1, max_length=MAX_SUMMARY_CHARS, description="What is being decided."
    )
    options: list[ProposeBriefOptionInput] = Field(min_length=1, max_length=4)


# -- the designer's tool ------------------------------------------------------------------


class DesignedSlideInput(ToolArgs):
    """The slide the designer returns: its blocks (the words, chart or icons) and a free
    layout placing every block once, plus any shapes. `intent` and `speaker_notes` are
    accepted and ignored (the brief owns the intent; notes are not the designer's)."""

    id: str = Field(min_length=1, description="The slide id from the brief.")
    blocks: list[Block] = Field(min_length=1)
    layout: FreeLayout
    intent: str | None = Field(default=None, description="Ignored.")
    speaker_notes: str = Field(default="", description="Ignored; leave empty.")


class DesignerWriteArgs(ToolArgs):
    """`write_slide` (the designer's only tool): the whole designed slide."""

    slide: DesignedSlideInput


# -- the system layer's tool --------------------------------------------------------------


class SetPaletteArgs(ToolArgs):
    """`set_palette` (the system layer's only tool): the direction made concrete."""

    palette: DesignPalette = Field(
        description="One hex colour per slot: dk1, lt1, dk2, lt2, accent1..accent6."
    )
    roles: dict[ColorToken, str] = Field(
        description="What each of the ten slots is for, in words, including which grounds "
        "it is safe as text on."
    )
    background: ColorToken = Field(description="The slot every slide's background uses.")
    text_pairs: list[TextPair] = Field(
        min_length=1,
        description="Every text colour the roles allow, on every ground they allow it on. "
        "Each is checked for contrast; large_only pairs need 3:1 and are for 24pt and above.",
    )


# -- the router's tool --------------------------------------------------------------------


class RouteArgs(ToolArgs):
    """`route` (the router's only tool): where the owner's message goes."""

    to: Literal["lead", "mechanic"] = Field(
        description="mechanic only for a small local edit; lead for anything else or when "
        "unsure."
    )
    reason: str = Field(default="", max_length=MAX_SUMMARY_CHARS)
