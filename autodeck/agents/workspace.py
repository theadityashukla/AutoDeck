"""The deck agent's workspace (B71): a draft under construction, edited one tool call at a time.

A one-shot compose asks for the whole deck in one reply. The agent session instead builds it
here, a brief and a slide at a time, and every change is checked by the very code a one-shot
draft goes through — `compose.build_draft` (citation resolution against what was shown, A1;
slot budgets; the B56 draft checks). Nothing in this module decides what a slide says.

**The citable set is what the session showed** (B75). A span becomes citable when a tool
put it in front of the agent — the seed it started with, a search, a page it read — exactly
as a one-shot writer may cite only its evidence pack. `pack()` hands those spans to the
resolver, so a quote from a passage the agent never saw fails with `doc_not_shown`, as it
would in a pack.

The workspace serialises to `session/workspace.json`, so a resumed session (revise, chat)
starts from the same draft, the same notes and the same citable set.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from autodeck.agents.compose import (
    Built,
    ComposedMessage,
    ComposeDraft,
    ComposedSlide,
    CoverageNote,
    CreativeComposeDraft,
    CreativeComposedSlide,
    build_draft,
)
from autodeck.agents.evidence_pack import EvidencePack
from autodeck.agents.planner import Draft
from autodeck.agents.rejections import Rejection
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ingest.document_store import DocumentStore
from autodeck.ir.models import DesignMode
from autodeck.knowledge.loader import CachedClaim
from autodeck.retrieval.hybrid import RetrievedSpan

WORKSPACE_VERSION = 1


class WorkspaceError(ValueError):
    """An edit the workspace cannot make (no brief yet, an unknown slide id)."""


class DeckBriefDraft(BaseModel):
    """The brief part of a `ComposeDraft`, set on its own by `set_brief`."""

    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, description="The decision the deck should produce.")
    audience: str = Field(min_length=1)
    length_target: int = Field(ge=1)
    key_messages: list[ComposedMessage] = Field(min_length=1)
    must_include: list[str]
    must_avoid: list[str]


@dataclass(frozen=True)
class BuildSettings:
    """Everything `build_draft` needs besides the draft and the pack. Fixed for a session."""

    store: DocumentStore
    tokens: DesignTokens
    deck_fields: Mapping[str, Any]
    chat_brief: Draft | None = None
    allow_unsourced: bool = False
    keep_words: bool = False
    dividers_requested: bool = False

    @property
    def design_mode(self) -> DesignMode:
        return self.deck_fields.get("design_mode", "structured")  # type: ignore[return-value]


def _span_key(span: RetrievedSpan) -> tuple[str, str, int, str]:
    return (span.doc_id, span.element_id, span.page, span.text)


def _claim_key(claim: CachedClaim) -> tuple[str, int, str]:
    return (claim.doc_id, claim.page, claim.quote)


@dataclass
class DeckWorkspace:
    """The draft as the agent has built it so far, plus what it may cite."""

    settings: BuildSettings
    brief: DeckBriefDraft | None = None
    slides: list[ComposedSlide] = field(default_factory=list)
    coverage: list[CoverageNote] = field(default_factory=list)
    notes: str = ""
    """The note to the person (`ComposeResult.notes`), set by `finish`."""
    deck_notes: str = ""
    """The agent's own scratch: governing thought, glossary, decisions. Survives into revise."""
    shown_spans: list[RetrievedSpan] = field(default_factory=list)
    shown_claims: list[CachedClaim] = field(default_factory=list)
    cold_read: list[str] = field(default_factory=list)
    """The slide ids the advisor last read cold as a whole deck (B76). `finish` requires it to
    cover every current slide when the session has an advisor."""
    revision: int = 0
    """Bumped on every edit. Part of the toolbox's repeat-call key, so the same check after a
    change is a new call, not a repeat."""

    # -- what may be cited ----------------------------------------------------------

    def show_spans(self, spans: Iterable[RetrievedSpan]) -> int:
        """Add spans to the citable set; returns how many were new."""
        seen = {_span_key(s) for s in self.shown_spans}
        added = 0
        for span in spans:
            key = _span_key(span)
            if key not in seen:
                seen.add(key)
                self.shown_spans.append(span)
                added += 1
        if added:
            self.revision += 1
        return added

    def show_claims(self, claims: Iterable[CachedClaim]) -> int:
        seen = {_claim_key(c) for c in self.shown_claims}
        added = 0
        for claim in claims:
            key = _claim_key(claim)
            if key not in seen:
                seen.add(key)
                self.shown_claims.append(claim)
                added += 1
        if added:
            self.revision += 1
        return added

    def pack(self) -> EvidencePack:
        """The shown spans and claims, as the resolver's evidence (A1)."""
        return EvidencePack(
            claims=tuple(self.shown_claims),
            spans=tuple(self.shown_spans),
            text="",
            queries=(),
            dropped=0,
            approx_tokens=0,
        )

    # -- edits ----------------------------------------------------------------------

    @property
    def creative(self) -> bool:
        return self.settings.design_mode == "creative"

    def set_brief(self, brief: DeckBriefDraft) -> None:
        self.brief = brief
        self.revision += 1

    def slide_ids(self) -> list[str]:
        return [s.id for s in self.slides]

    def write_slide(self, slide: ComposedSlide, position: int | None = None) -> str:
        """Add or replace a slide. Returns 'added' or 'replaced'.

        A slide with an id already in the deck replaces it in place, unless `position` moves
        it; a new slide goes at `position` (1-based) or at the end.
        """
        if self.creative and not isinstance(slide, CreativeComposedSlide):
            raise WorkspaceError("this deck is in creative mode: every slide needs a layout.")
        ids = self.slide_ids()
        outcome = "added"
        if slide.id in ids:
            at = ids.index(slide.id)
            self.slides.pop(at)
            outcome = "replaced"
        else:
            at = len(self.slides)
        if position is not None:
            at = max(0, min(position - 1, len(self.slides)))
        self.slides.insert(at, slide)
        self.revision += 1
        return outcome

    def remove_slide(self, slide_id: str) -> None:
        if slide_id not in self.slide_ids():
            raise WorkspaceError(f"no slide {slide_id!r}; the deck has {self._ids_text()}.")
        self.slides = [s for s in self.slides if s.id != slide_id]
        self.revision += 1

    def reorder(self, order: Sequence[str]) -> None:
        ids = self.slide_ids()
        if sorted(order) != sorted(ids) or len(set(order)) != len(order):
            raise WorkspaceError(
                "the order must list every slide exactly once; the deck has "
                f"{self._ids_text()}."
            )
        by_id = {s.id: s for s in self.slides}
        self.slides = [by_id[sid] for sid in order]
        self.revision += 1

    def record_cold_read(self, slide_ids: Sequence[str]) -> None:
        self.cold_read = list(slide_ids)
        self.revision += 1

    def cold_read_missing(self) -> list[str]:
        """Current slides the last whole-deck cold read did not include."""
        read = set(self.cold_read)
        return [sid for sid in self.slide_ids() if sid not in read]

    def set_deck_notes(self, text: str) -> None:
        self.deck_notes = text
        self.revision += 1

    def _ids_text(self) -> str:
        return ", ".join(self.slide_ids()) or "no slides yet"

    # -- building -------------------------------------------------------------------

    def as_draft(self) -> ComposeDraft:
        if self.brief is None:
            raise WorkspaceError("there is no brief yet: call set_brief first.")
        if not self.slides:
            raise WorkspaceError("there are no slides yet.")
        schema = CreativeComposeDraft if self.creative else ComposeDraft
        return schema(
            **self.brief.model_dump(),
            slides=list(self.slides),
            coverage=list(self.coverage),
            notes=self.notes,
        )

    def build(self) -> Built:
        """Resolve and check the whole draft (raises `ComposeError` if no slide is usable)."""
        s = self.settings
        return build_draft(
            self.as_draft(),
            chat_brief=s.chat_brief,
            pack=self.pack(),
            store=s.store,
            tokens=s.tokens,
            allow_unsourced=s.allow_unsourced,
            keep_words=s.keep_words,
            dividers_requested=s.dividers_requested,
            deck_fields=s.deck_fields,
        )

    # -- persistence ----------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "version": WORKSPACE_VERSION,
            "brief": self.brief.model_dump(mode="json") if self.brief else None,
            "slides": [s.model_dump(mode="json") for s in self.slides],
            "coverage": [c.model_dump(mode="json") for c in self.coverage],
            "notes": self.notes,
            "deck_notes": self.deck_notes,
            "shown_spans": [asdict(s) for s in self.shown_spans],
            "shown_claims": [c.model_dump(mode="json") for c in self.shown_claims],
            "cold_read": list(self.cold_read),
            "revision": self.revision,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.to_json(), indent=1) + "\n", encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def from_json(cls, data: Mapping[str, Any], settings: BuildSettings) -> DeckWorkspace:
        if data.get("version") != WORKSPACE_VERSION:
            raise WorkspaceError(
                f"workspace version {data.get('version')!r} is not {WORKSPACE_VERSION}"
            )
        creative = settings.design_mode == "creative"
        slide_model = CreativeComposedSlide if creative else ComposedSlide
        brief = data.get("brief")
        return cls(
            settings=settings,
            brief=DeckBriefDraft.model_validate(brief) if brief else None,
            slides=[slide_model.model_validate(s) for s in data.get("slides", [])],
            coverage=[CoverageNote.model_validate(c) for c in data.get("coverage", [])],
            notes=str(data.get("notes", "")),
            deck_notes=str(data.get("deck_notes", "")),
            shown_spans=[RetrievedSpan(**s) for s in data.get("shown_spans", [])],
            shown_claims=[CachedClaim.model_validate(c) for c in data.get("shown_claims", [])],
            cold_read=[str(sid) for sid in data.get("cold_read", [])],
            revision=int(data.get("revision", 0)),
        )

    @classmethod
    def load(cls, path: Path, settings: BuildSettings) -> DeckWorkspace:
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")), settings)


# ---------------------------------------------------------------------------
# Reports: what a check tells the agent
# ---------------------------------------------------------------------------


def _mentions_slide(line: str, slide_id: str) -> bool:
    return f"slide {slide_id}:" in line or f"slide {slide_id!r}" in line


def slide_findings(built: Built, slide_id: str) -> list[str]:
    """Every failure, correction and advisory about one slide, one line each."""
    lines: list[str] = []
    for failure in built.failures:
        if failure.where != "message" and failure.slide_id == slide_id:
            lines.append(f"FAIL {failure.kind} [{failure.block_id or '-'}]: {failure.message}")
    for advisory in built.advisories:
        if advisory.slide_id == slide_id:
            lines.append(f"ADVICE {advisory.kind}: {advisory.message}")
    for correction in built.corrections:
        if _mentions_slide(correction, slide_id):
            lines.append(f"NOTE: {correction}")
    if slide_id not in {s.id for s in built.slides}:
        lines.append("DROPPED: this slide could not be built and is not in the deck.")
    return lines


def message_findings(built: Built) -> list[str]:
    """Key-message evidence, as code graded it, plus any message-citation failures."""
    lines = [
        f"{m.id}: {m.evidence_status} — {m.probe_notes or ''}".rstrip(" —")
        for m in built.graded
    ]
    lines.extend(
        f"FAIL {f.kind} [{f.block_id}]: {f.message}"
        for f in built.failures
        if f.where == "message"
    )
    return lines


def failing(built: Built) -> list[Rejection]:
    """The failures that would cost the deck a block (everything but advisories)."""
    return list(built.failures)
