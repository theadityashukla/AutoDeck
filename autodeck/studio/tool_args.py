"""The lead's tool vocabulary: one pydantic argument model per tool (Phase 1).

The closed-vocabulary pattern of v2's `ToolBox`: every tool has an argument model, the
model's call is validated against it, and bad arguments come back to the model as an error
*result* it can read and correct, never as an exception (`agents/tools/registry.py`).

The descriptions on these fields are part of the tool schema the model sees, so they are
written for the model: short, imperative, and in the product's terms. Every deck tool takes
an optional `artifact_id`; omitted, it means the engagement's only deck
(`tools.resolve_artifact`).

Phase 1 is one model writing every layer (no routing yet), so `write_slide` takes the
whole slide, blocks and free layout together. Phase 2 splits it (plan §6.2) without
changing the IR.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autodeck.studio.conversation import MAX_LABEL_CHARS, MAX_SUMMARY_CHARS
from autodeck.studio.models import (
    PROPOSAL_ID_PATTERN,
    SEGMENT_PATTERN,
    Marker,
    OptionId,
    Slide,
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
