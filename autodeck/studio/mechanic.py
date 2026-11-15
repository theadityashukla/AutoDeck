"""The mechanic's view of a turn (Phase 2-3, L5 Mechanics; plan §6.4).

The mechanic handles small local edits the router sent it, with a handful of tools
(`tools.MECHANIC_TOOL_NAMES`). It is stateless per turn: it is not given the thread's
history, only the deck's current state and the owner's one message, which keeps every
call small. What it did is recorded on the thread like any turn (its lines carry
`role="mechanic"`), and the lead sees it folded into one line in later turns
(`loop.fold_mechanic_lines`).
"""

from __future__ import annotations

from autodeck.providers.base import Message
from autodeck.studio.engagement import Engagement
from autodeck.studio.views import deck_outline


def mechanic_request_text(engagement: Engagement, text: str) -> str:
    """The mechanic's one user message, exactly:

    `"# The deck\\n\\n" + <the decks> + "\\n\\n# The owner's message\\n\\n" + text`

    where `<the decks>` is `views.deck_outline(deck)` for each artifact of the engagement in
    id order (loaded through `engagement.artifact_store(id).load()`), joined by `"\\n\\n"`,
    or `(no deck yet)` when there is none."""
    outlines = [
        deck_outline(engagement.artifact_store(artifact_id).load())
        for artifact_id in engagement.artifact_ids()
    ]
    decks = "\n\n".join(outlines) if outlines else "(no deck yet)"
    return f"# The deck\n\n{decks}\n\n# The owner's message\n\n{text}"


def mechanic_messages(engagement: Engagement, text: str) -> list[Message]:
    """`[Message("user", mechanic_request_text(engagement, text))]`."""
    return [Message("user", mechanic_request_text(engagement, text))]
