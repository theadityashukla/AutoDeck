"""HeaderStyleProfile: learn, apply, and switch header voice (§6.11.1, D12).

`profile.py` defines the profile and its built-in style guidance; `prompt.py` resolves one
for a build and renders it for the content prompt
(`autodeck.agents.content._content_prompt` is where it actually reaches the writer). A
later task in this phase adds `flow.py`, the horizontal-flow QA pass over a written deck's
headers.

Owning phase: Phase 3a (task 3a.8). See docs/AUTODECK_V2_PLAN.md §6.11.1.
"""

from __future__ import annotations

from autodeck.design.headers.profile import (
    HeaderBodyStyle,
    HeaderProfileError,
    HeaderStyleProfile,
    NumbersPolicy,
    guidance_for,
)
from autodeck.design.headers.prompt import render_for_prompt, resolve_profile

__all__ = [
    "HeaderBodyStyle",
    "HeaderProfileError",
    "HeaderStyleProfile",
    "NumbersPolicy",
    "guidance_for",
    "render_for_prompt",
    "resolve_profile",
]
