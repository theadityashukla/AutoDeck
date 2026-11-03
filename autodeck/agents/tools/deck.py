"""The deck tools: edit the workspace, and see what the checks say about the edit.

Every writing tool answers with the findings `compose.build_draft` produces for the slide it
just changed — the same resolver, budgets and draft checks a one-shot draft goes through — so
the agent corrects a quote that does not resolve while it still has the page in mind. No tool
here decides what a slide says, and none can mark a slide good: `finish` only ends the
session, and whatever still fails then is dropped by the caller (B56).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from autodeck.agents import content
from autodeck.agents.compose import (
    Built,
    ComposedSlide,
    ComposeError,
    CoverageNote,
    CreativeComposedSlide,
)
from autodeck.agents.tools.registry import Tool, ToolError, ToolResult
from autodeck.agents.workspace import (
    DeckBriefDraft,
    DeckWorkspace,
    message_findings,
    slide_findings,
)
from autodeck.audit.numeric_linter import FormulaError, evaluate_formula

PASSED = "all checks passed"


class WriteSlideArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide: ComposedSlide = Field(
        description="The whole slide. An id already in the deck replaces that slide."
    )
    position: int | None = Field(
        default=None, ge=1, description="1-based place in the deck; omit to keep or append."
    )


class CreativeWriteSlideArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide: CreativeComposedSlide = Field(
        description="The whole slide, with its layout. An id already in the deck replaces it."
    )
    position: int | None = Field(
        default=None, ge=1, description="1-based place in the deck; omit to keep or append."
    )


class RemoveSlideArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(description="The id of the slide to remove.")


class ReorderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: list[str] = Field(description="Every slide id, exactly once, in the new order.")


class SetNotesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="Your scratch notes: governing thought, decisions, glossary.")


class CheckSlideArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str


class CheckDeckArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComponentBudgetsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: str = Field(description="A catalog component name.")


class ComputeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    formula: str = Field(description="Arithmetic only, e.g. '(a - b) / b * 100'.")
    inputs: dict[str, float] = Field(description="Value of each name used in the formula.")


class FinishArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coverage: list[CoverageNote] = Field(
        description="What the deck did with each thing the person asked for."
    )
    notes: str = Field(description="Anything the person should know first; '' for none.")


def _short(text: str, limit: int = 100) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _built(ws: DeckWorkspace) -> Built:
    return ws.build()


def _slide_report(built: Built, slide_id: str) -> tuple[str, int]:
    lines = slide_findings(built, slide_id)
    return ("\n".join(lines) if lines else PASSED), len(lines)


def _deck_report(ws: DeckWorkspace, built: Built) -> tuple[str, int]:
    out: list[str] = []
    problems = 0
    for slide in ws.slides:
        lines = slide_findings(built, slide.id)
        if lines:
            problems += 1
            out.append(f"{slide.id}:")
            out.extend(f"  {line}" for line in lines)
        else:
            out.append(f"{slide.id}: ok")
    messages = message_findings(built)
    if messages:
        out.append("key messages:")
        out.extend(f"  {line}" for line in messages)
    out.append(
        f"{len(ws.slides)} slides, {problems} with findings, "
        f"{len(built.failures)} failures, {len(built.advisories)} advisories."
    )
    return "\n".join(out), problems


class _Finish:
    """First-finish state, kept off the workspace: a resumed session starts fresh."""

    def __init__(self) -> None:
        self.warned = False


def deck_tools(ws: DeckWorkspace, *, require_cold_read: bool = False) -> list[Tool]:
    """The deck tools. With `require_cold_read` (the session has an advisor, B76), `finish`
    refuses until the advisor has read every current slide cold through `ask_advisor`."""
    finish_state = _Finish()

    def set_brief(args: DeckBriefDraft) -> ToolResult:
        ws.set_brief(args)
        ids = ", ".join(m.id for m in args.key_messages)
        if ws.slides:
            built = _built(ws)
            lines = message_findings(built)
            return ToolResult(
                "brief set.\n" + "\n".join(lines), f"set_brief: {len(lines)} message lines"
            )
        return ToolResult(
            f"brief set; key messages are graded once slides exist. Messages: {ids}.",
            f"set_brief: {len(args.key_messages)} messages",
        )

    def write_slide(args: Any) -> ToolResult:
        if ws.brief is None:
            raise ToolError("call set_brief first.")
        outcome = ws.write_slide(args.slide, args.position)
        sid = args.slide.id
        try:
            built = _built(ws)
        except ComposeError as exc:
            return ToolResult(
                f"ERROR: slide {sid} is kept in the workspace, but the deck cannot be "
                f"built: {exc}",
                f"write_slide {sid}: build failed",
                error=True,
            )
        at = ws.slide_ids().index(sid) + 1
        report, count = _slide_report(built, sid)
        verb = "added" if outcome == "added" else "replaced"
        return ToolResult(
            f"{verb} slide {sid} at position {at} of {len(ws.slides)}.\n{report}",
            f"{verb} {sid} at {at}/{len(ws.slides)}: "
            + (f"{count} findings" if count else PASSED),
        )

    def remove_slide(args: RemoveSlideArgs) -> ToolResult:
        ws.remove_slide(args.slide_id)
        return ToolResult(
            f"removed slide {args.slide_id}. The deck now has {ws._ids_text()}.",
            f"removed {args.slide_id}",
        )

    def reorder(args: ReorderArgs) -> ToolResult:
        ws.reorder(args.order)
        return ToolResult(f"order is now {', '.join(args.order)}.", "reordered slides")

    def set_notes(args: SetNotesArgs) -> ToolResult:
        ws.set_deck_notes(args.text)
        return ToolResult("notes saved.", f"notes saved ({len(args.text)} chars)")

    def check_slide(args: CheckSlideArgs) -> ToolResult:
        if args.slide_id not in ws.slide_ids():
            raise ToolError(f"no slide {args.slide_id!r}; the deck has {ws._ids_text()}.")
        built = _built(ws)
        report, count = _slide_report(built, args.slide_id)
        return ToolResult(
            f"{args.slide_id}: {report}",
            f"check {args.slide_id}: " + (f"{count} findings" if count else PASSED),
        )

    def check_deck(_: CheckDeckArgs) -> ToolResult:
        built = _built(ws)
        report, problems = _deck_report(ws, built)
        return ToolResult(
            report, f"check_deck: {len(ws.slides)} slides, {problems} with findings"
        )

    def component_budgets(args: ComponentBudgetsArgs) -> ToolResult:
        text = content.slide_budgets(args.component, ws.settings.tokens)
        return ToolResult(text, f"budgets for {args.component}")

    def compute(args: ComputeArgs) -> ToolResult:
        try:
            value = evaluate_formula(args.formula, args.inputs)
        except FormulaError as exc:
            return ToolResult(f"ERROR: {exc}", "compute: formula error", error=True)
        return ToolResult(f"result = {value}", f"compute: {_short(args.formula, 60)} = {value}")

    def finish(args: FinishArgs) -> ToolResult:
        if ws.brief is None or not ws.slides:
            raise ToolError("there is nothing to finish: set a brief and write slides first.")
        ws.coverage = list(args.coverage)
        ws.notes = args.notes
        ws.revision += 1
        unread = ws.cold_read_missing() if require_cold_read else []
        if unread:
            return ToolResult(
                "Not finished yet: the deck has not been read cold. Call ask_advisor with "
                "slide_ids ['all'] and headlines_only true, asking what argument the headlines "
                "make and where it jumps; then ask_advisor again with the slides you are least "
                "sure of, asking whether any claim says more than its cited passage or fails "
                "to name its subject. Fix what it finds, then call finish. "
                f"Not yet read: {', '.join(unread)}.",
                f"finish held back: cold read missing for {len(unread)} slide(s)",
            )
        built = _built(ws)
        failures = len(built.failures)
        if failures and not finish_state.warned:
            finish_state.warned = True
            report, _ = _deck_report(ws, built)
            return ToolResult(
                f"{report}\n\nThe deck still has {failures} failures. Anything still failing "
                "will be dropped if you call finish again. Fix what you can, or call finish "
                "again to accept the drop.",
                f"finish held back: {failures} failures",
            )
        claims = sum(len(s.blocks) for s in ws.slides)
        return ToolResult(
            f"finished: {len(ws.slides)} slides, {claims} blocks, "
            f"{failures} failures to be dropped.",
            f"finished: {len(ws.slides)} slides, {failures} failures dropped",
            finished=True,
        )

    write_args: type[BaseModel] = CreativeWriteSlideArgs if ws.creative else WriteSlideArgs
    tools = [
        Tool(
            "set_brief",
            "Set the deck brief: objective, audience, length, key messages (with the "
            "citations that support each), must-include and must-avoid. Call it first; "
            "call it again to change the brief.",
            DeckBriefDraft,
            set_brief,
        ),
        Tool(
            "write_slide",
            "Add a slide, or replace the slide with the same id. The result lists what the "
            "checks found: quotes that did not resolve, budgets exceeded, advice.",
            write_args,
            write_slide,
        ),
        Tool("remove_slide", "Remove one slide.", RemoveSlideArgs, remove_slide),
        Tool("reorder", "Reorder the slides; list every id once.", ReorderArgs, reorder),
        Tool(
            "set_notes",
            "Save your scratch notes (governing thought, decisions). Replaces the old notes.",
            SetNotesArgs,
            set_notes,
        ),
        Tool(
            "check_slide",
            "Re-run the checks and show findings for one slide.",
            CheckSlideArgs,
            check_slide,
        ),
        Tool(
            "check_deck",
            "Re-run the checks over the whole deck: one line per slide, then key messages.",
            CheckDeckArgs,
            check_deck,
        ),
    ]
    if not ws.creative:
        tools.append(
            Tool(
                "component_budgets",
                "The slots and word/character budgets of one catalog component.",
                ComponentBudgetsArgs,
                component_budgets,
            )
        )
    tools += [
        Tool(
            "compute",
            "Dry-run arithmetic: evaluates a formula over inputs. It only checks the "
            "arithmetic; the derivation still goes in the claim (its derivation field) of "
            "write_slide, with each input cited.",
            ComputeArgs,
            compute,
        ),
        Tool(
            "finish",
            "End the session once the deck is done. If failures remain you are shown them "
            "first; calling finish again accepts that they are dropped.",
            FinishArgs,
            finish,
        ),
    ]
    return tools
