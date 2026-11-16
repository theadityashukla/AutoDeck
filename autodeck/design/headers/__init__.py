"""HeaderStyleProfile: learn, apply, and switch header voice (§6.11.1, D12).

`profile.py` defines the profile and its built-in style guidance; `prompt.py` resolves one
for a build and renders it for the content prompt (`autodeck.agents.content._content_prompt`
is where it actually reaches the writer); `flow.py` is the horizontal-flow QA pass that
reads a deck's headers back out in slide order once content has been written.

Owning phase: Phase 3a (task 3a.8). See docs/AUTODECK_V2_PLAN.md §6.11.1.
"""

from __future__ import annotations

from autodeck.design.headers.flow import FlowFinding, HeaderFlowReport, HeaderLine, flow_report
from autodeck.design.headers.profile import (
    HeaderBodyStyle,
    HeaderProfileError,
    HeaderStyleProfile,
    NumbersPolicy,
    guidance_for,
)
from autodeck.design.headers.prompt import render_for_prompt, resolve_profile

__all__ = [
    "FlowFinding",
    "HeaderBodyStyle",
    "HeaderFlowReport",
    "HeaderLine",
    "HeaderProfileError",
    "HeaderStyleProfile",
    "NumbersPolicy",
    "flow_report",
    "guidance_for",
    "render_for_prompt",
    "resolve_profile",
]
