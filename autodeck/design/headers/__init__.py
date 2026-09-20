"""HeaderStyleProfile: learn, apply, and switch header voice (§6.11.1, D12).

`profile.py` defines the profile and its built-in style guidance. Later tasks in this
phase add `prompt.py` (resolving and rendering a profile for the content prompt) and
`flow.py` (horizontal-flow QA over a written deck's headers).

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

__all__ = [
    "HeaderBodyStyle",
    "HeaderProfileError",
    "HeaderStyleProfile",
    "NumbersPolicy",
    "guidance_for",
]
