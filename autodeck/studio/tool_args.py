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

    slide: Slide = Field(description="The whole slide: intent, blocks, notes and layout.")
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


class ProposeOptionInput(ToolArgs):
    label: str = Field(
        min_length=1, max_length=MAX_LABEL_CHARS, description="A few words naming the option."
    )
    text: str = Field(min_length=1, description="What the option is, in two or three lines.")
    slides: list[Slide] = Field(
        default_factory=list,
        description="Candidate slides to show it. Rendered for the owner, not added to the "
        "deck until the option is applied. An id already in the deck would replace it.",
    )
    insert_at: int | None = Field(
        default=None,
        ge=1,
        description="1-based place for new candidate slides; omit for the end.",
    )


class ProposeArgs(DeckToolArgs):
    """`propose`: offer the owner two to four options without changing the deck. One option
    is allowed for a single described change with a preview."""

    summary: str = Field(
        min_length=1,
        max_length=MAX_SUMMARY_CHARS,
        description="What is being decided, in one line.",
    )
    options: list[ProposeOptionInput] = Field(min_length=1, max_length=4)


class ApplyOptionArgs(ToolArgs):
    """`apply_option`: put an option's candidate slides into the deck, once the owner has
    chosen it."""

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
