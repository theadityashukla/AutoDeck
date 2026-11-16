"""`ask_advisor`: the deck agent asks a fresh-context second reader one question (B73)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from autodeck.agents.advisor import AdvisorModel, ask, slide_text
from autodeck.agents.content import render_evidence
from autodeck.agents.skills import SkillError, _without_project, load_skill
from autodeck.agents.tools.registry import Tool, ToolError, ToolResult
from autodeck.agents.workspace import DeckWorkspace
from autodeck.retrieval.hybrid import HybridIndex, RetrievedSpan

MAX_ATTACHED_PAGES = 4


class PageRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    page: int = Field(ge=1)


class AskAdvisorArgs(BaseModel):
    """What the advisor sees: the question and only what is attached. Nothing else."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        min_length=1,
        description=(
            "One specific question, e.g. 'Read these headlines cold: what is the argument, "
            "and where does it jump?' or 'Does s4 claim more than its cited passage says?'"
        ),
    )
    slide_ids: list[str] = Field(
        description="Slides to attach, or ['all'] for the whole deck; [] for none."
    )
    headlines_only: bool = Field(
        description="Attach only each slide's headline, in order, for a cold read of the story."
    )
    include_notes: bool = Field(description="Attach your working notes (set_notes).")
    skills: list[str] = Field(description="Skills to attach as the standard to judge by.")
    pages: list[PageRef] = Field(
        description=f"Source pages to attach, at most {MAX_ATTACHED_PAGES}; [] for none."
    )


def _headline(slide) -> str:  # type: ignore[no-untyped-def]
    for block in slide.blocks:
        if block.slot in ("headline", "title") and block.text:
            return block.text
    return slide.intent


def advisor_tools(
    ws: DeckWorkspace, *, model: AdvisorModel, index: HybridIndex, project: str | None
) -> list[Tool]:
    def run(args: AskAdvisorArgs) -> ToolResult:
        attachments: list[tuple[str, str]] = []
        wanted = ws.slide_ids() if args.slide_ids == ["all"] else args.slide_ids
        unknown = [sid for sid in wanted if sid not in ws.slide_ids()]
        if unknown:
            raise ToolError(f"no slide(s) {', '.join(unknown)}; the deck has {ws.slide_ids()}")
        chosen = [s for s in ws.slides if s.id in wanted]
        if chosen and args.headlines_only:
            attachments.append(
                (
                    "The headlines, in deck order",
                    "\n".join(f"{n}. {_headline(s)}" for n, s in enumerate(chosen, 1)),
                )
            )
        elif chosen:
            attachments.append(("Slides", "\n\n".join(slide_text(s) for s in chosen)))
        if args.include_notes and ws.deck_notes.strip():
            attachments.append(("The writer's notes", ws.deck_notes))
        for name in args.skills:
            try:
                skill = load_skill(name)
            except SkillError as exc:
                raise ToolError(str(exc)) from exc
            attachments.append((f"Skill: {name}", _without_project(skill.body, project)))
        if len(args.pages) > MAX_ATTACHED_PAGES:
            raise ToolError(f"attach at most {MAX_ATTACHED_PAGES} pages")
        for ref in args.pages:
            elements = sorted(
                (
                    e
                    for e in index.elements.values()
                    if e.doc_id == ref.doc_id and e.page == ref.page
                ),
                key=lambda e: e.reading_order,
            )
            if not elements:
                raise ToolError(f"{ref.doc_id} has no page {ref.page} in the corpus")
            spans = [
                RetrievedSpan(
                    doc_id=e.doc_id,
                    element_id=e.element_id,
                    page=e.page,
                    text=e.retrieval_text(),
                    score=0.0,
                    citable=e.is_citable,
                )
                for e in elements
            ]
            title = f"Source {ref.doc_id} p.{ref.page}"
            attachments.append((title, render_evidence((), spans)))
        advice = ask(model, args.question, attachments)
        if chosen and {s.id for s in chosen} == set(ws.slide_ids()):
            ws.record_cold_read([s.id for s in chosen])
        what = ", ".join(t for t, _ in attachments) or "no attachments"
        return ToolResult(
            text=f"Advisor (who saw only: {what}):\n\n{advice}",
            summary=f"ask_advisor: {args.question[:70]}",
        )

    return [
        Tool(
            name="ask_advisor",
            description=(
                "Ask a second reader one question. It sees ONLY what you attach, reads it cold "
                "the way the audience will, and answers in plain text. Use it to test the "
                "storyline (headlines_only), to ask whether a slide overclaims its source, or "
                "which component shows a point best. It cannot edit and its words are not "
                "evidence."
            ),
            args_model=AskAdvisorArgs,
            run=run,
        )
    ]
