"""The advisor (B73): a fresh-context second reader the deck agent can consult.

A writer who has read forty passages cannot read its own headlines cold. The advisor can: it
gets `prompts/advisor.md`, the question, and only the material the agent attached — some
slides, the agent's notes, a skill, a page of a source — and returns plain text. It cannot
edit the workspace and its answer is never evidence; a session tool result is the only way
its words reach the agent.

It runs on the `advisor` role, which the registry refuses to bind to the validation model
(B44): the validator stays the blind, independent check on whatever the writer and its
advisor produced. Each question is one text completion, cached like any other call, so a
replayed session gets the same advice back.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from autodeck.agents.compose import PROMPT_SEPARATOR, ComposedSlide, read_prompt

ADVISOR_PROMPT = Path("prompts/advisor.md")

MAX_ADVICE_CHARS = 4_000
"""An answer longer than this is cut: the prompt asks for under 250 words."""


class AdvisorModel(Protocol):
    def complete(self, prompt: str, *, system: str | None = None) -> str: ...


def _block_line(block: object) -> str:
    kind = getattr(block, "kind", "")
    slot = getattr(block, "slot", "")
    head = f"  [{getattr(block, 'id', '')}] {kind} · {slot}: "
    claim = getattr(block, "claim", None)
    if claim is not None:
        quotes = "; ".join(f"{c.doc_id}: {c.quote!r}" for c in claim.citations)
        return f"{head}{claim.text}\n      cites {quotes}"
    chart = getattr(block, "chart", None)
    if chart is not None:
        series = "; ".join(f"{s.name} {s.values}" for s in chart.series)
        return f"{head}chart {chart.chart_type} '{chart.title}' {chart.categories} {series}"
    diagram = getattr(block, "diagram", None)
    if diagram is not None:
        return f"{head}diagram: " + " → ".join(s.label for s in diagram.steps)
    return f"{head}{getattr(block, 'text', '')}"


def slide_text(slide: ComposedSlide) -> str:
    """One slide as the advisor reads it: role, intent, every block, the notes."""
    lines = [
        f"slide {slide.id} · {slide.component} · {slide.narrative_role}",
        f"  intent: {slide.intent}",
    ]
    lines.extend(_block_line(b) for b in slide.blocks)
    if slide.speaker_notes:
        lines.append("  speaker notes:")
        lines.extend(_block_line(b) for b in slide.speaker_notes)
    return "\n".join(lines)


def advisor_prompt(question: str, attachments: Sequence[tuple[str, str]]) -> str:
    """The user message: the question, then each attachment under its own heading."""
    parts = [f"# The question\n\n{question.strip()}"]
    parts.extend(f"# {title}\n\n{body}" for title, body in attachments if body.strip())
    if len(parts) == 1:
        parts.append("# Attachments\n\n(none)")
    return PROMPT_SEPARATOR.join(parts)


def ask(
    model: AdvisorModel,
    question: str,
    attachments: Sequence[tuple[str, str]],
    *,
    prompt_path: Path = ADVISOR_PROMPT,
) -> str:
    """One fresh-context completion. Returns the advice, trimmed to `MAX_ADVICE_CHARS`."""
    prompt = advisor_prompt(question, attachments)
    answer = model.complete(prompt, system=read_prompt(prompt_path))
    answer = answer.strip()
    if len(answer) > MAX_ADVICE_CHARS:
        answer = answer[:MAX_ADVICE_CHARS].rsplit(" ", 1)[0] + " …"
    return answer
