"""`HeaderStyleProfile` — the learned or selected header voice for one deck (D12, §6.11.1).

## What a profile is, and is not

`knowledge/clients/northwind-retail/style/headers.yaml` is the seed shape this module
loads: a `style` name, a word budget, casing and punctuation rules, a numbers policy, a
hedge vocabulary and a client-specific `avoid` list, plus the body-copy limits that travel
alongside a header's voice. Every one of those fields is about **phrasing** — how a
supported sentence is said, not what earns the right to be said at all.

**A profile can only make a claim punchier. It can never make an unsupported sentence
sayable.** `numbers_in_headers: allowed` does not mean a bare number is exempt from A1 —
Northwind's own `headers.yaml` says so in a comment, and this module holds the same line in
code: the profile text this module renders for the writer always ends with the reminder
that a fact-bearing header is a `claim` block, never a decoration with a smaller font. See
`autodeck/design/headers/flow.py`'s module docstring and this phase's report for how that
invariant is actually enforced (`autodeck/audit/framing_linter.py`, a guardrail path this
module does not touch).

## Loading is lenient, resolution is not

`from_mapping` accepts whatever a client's `headers.yaml` parsed to (see
`autodeck.knowledge.loader.ClientKnowledge.header_profile` — a loose `dict | None`, by
design, since the loader's job is only to catch malformed YAML, not to know the profile
shape). This module is what gives that dict a shape, with every field defaulted so a client
with no opinion on, say, `hedges` still gets a usable profile rather than a `KeyError`
three modules downstream.

## The one-flag switch

`HeaderStyleProfile.with_style` is what makes `--header-style question_led` a genuine
one-flag switch rather than "edit `headers.yaml`, then remember to also update the brief,
then remember to also tell the writer": it swaps only the `style` field — the voice — and
keeps every rule the client's profile already set (word budget, avoid list, hedges, body
limits). A deck can therefore try a different header voice for one build without touching
`knowledge/`, without a second profile file per style, and without the brief's other fields
moving at all. See `resolve_profile` for where a per-deck override and a client's on-disk
profile are combined.

Owning phase: Phase 3a (task 3a.8). See docs/AUTODECK_V2_PLAN.md §6.11.1.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

NumbersPolicy = Literal["allowed", "discouraged", "forbidden"]
"""How this client's audience takes a number in a header. Never a citation exemption —
see the module docstring — only a note on whether this audience reads a number there as
confident or as marketing."""


class HeaderProfileError(RuntimeError):
    """A header style profile (usually a client's `headers.yaml`) does not fit the shape
    `HeaderStyleProfile` supports.

    Raised at load time, in the loader's own "fail loudly" tradition (see
    `autodeck/knowledge/loader.py`'s module docstring) — a malformed profile that loaded as
    defaults would ship a deck in the wrong voice with nothing in the build log to explain
    why.
    """


class HeaderBodyStyle(BaseModel):
    """The body-copy limits `headers.yaml` carries alongside the header voice itself.

    These are a client's own preference on top of the component budgets
    `autodeck.design.components.catalog` already computes from real font metrics — this is
    never a substitute for `check_overflow`, which remains the hard, measured gate (3a.6:
    nothing here estimates when it could measure).
    """

    model_config = ConfigDict(extra="forbid")

    bullets_max: int = Field(default=5, ge=1)
    words_per_bullet_max: int = Field(default=18, ge=1)


class HeaderStyleProfile(BaseModel):
    """One client's (or one deck's) header voice.

    Every field defaults to a neutral, low-commitment choice so a build with no client
    profile and no `--header-style` override still gets sensible guidance rather than an
    empty section in the prompt.
    """

    model_config = ConfigDict(extra="forbid")

    style: str = Field(default="topic_led", min_length=1)
    """A name, not an enum. `headers.yaml` seeds included `assertion`; this task adds
    `question_led` and the `topic_led` default. A client or a future style is free to name
    its own — `guidance_for` falls back to a generic description for a name it does not
    recognise rather than rejecting it, because an unrecognised style name is a reason to
    add guidance, not a reason to fail the build."""

    max_words: int = Field(default=14, ge=1)
    sentence_case: bool = True
    terminal_punctuation: bool = False
    numbers_in_headers: NumbersPolicy = "allowed"
    hedges: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    body: HeaderBodyStyle = Field(default_factory=HeaderBodyStyle)

    @classmethod
    def from_mapping(
        cls, data: dict[str, object] | None, *, source: str = "headers.yaml"
    ) -> HeaderStyleProfile:
        """Build a profile from the raw dict `KnowledgeLoader` parsed, or the defaults.

        `data` is `None` for a client with no `style/headers.yaml` at all — the loader
        already treats that as legitimate rather than an error (the field is optional),
        and this is the same posture: no profile is not malformed, it is "use the neutral
        default and say so nowhere in particular", which is what every field default here
        already provides.

        Raises:
            HeaderProfileError: `data` parsed to YAML but not to this shape — an unknown
                field, a wrong type, or a `body` mapping that failed its own validation.
        """
        if not data:
            return cls()
        payload = dict(data)
        body = payload.get("body")
        if isinstance(body, dict):
            try:
                payload["body"] = HeaderBodyStyle.model_validate(body)
            except ValidationError as exc:
                raise HeaderProfileError(f"{source}: invalid 'body': {exc}") from exc
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise HeaderProfileError(
                f"{source}: does not match HeaderStyleProfile: {exc}"
            ) from exc

    def with_style(self, style: str | None) -> HeaderStyleProfile:
        """The one-flag switch: swap the voice, keep every other rule as-is.

        `None` and the current style are both no-ops, so a caller can pass
        `brief.header_style` (which is `None` on most decks) straight through without a
        branch at every call site.
        """
        if not style or style == self.style:
            return self
        return self.model_copy(update={"style": style})


#: Built-in guidance for the style names this task ships. A client's `headers.yaml` may
#: still name any style it likes (see `HeaderStyleProfile.style`'s docstring); a name not
#: listed here gets `_FALLBACK_GUIDANCE` instead of a build failure.
STYLE_GUIDANCE: dict[str, str] = {
    "assertion": (
        'State the finding, not the topic — "KV-cache waste is the binding constraint", '
        'never "KV cache". The header is the argument; the slide body is the evidence '
        "for it."
    ),
    "question_led": (
        'Phrase the header as the question this slide actually answers — "Where does the '
        'serving budget go?" — and let the body answer it. Only a question the slide '
        "resolves belongs here; a rhetorical question with no answer on the slide is a "
        "topic label wearing a question mark."
    ),
    "topic_led": (
        'Name the subject plainly — "KV cache and serving cost". Lower-commitment than '
        "`assertion` on purpose: use it where the audience wants to be told what a slide "
        "is about before being told what to conclude from it."
    ),
}

_FALLBACK_GUIDANCE = (
    "no built-in guidance for this style name — follow the rules below (word budget, "
    "casing, punctuation, hedges, avoid list) and the client's own comments in "
    "`headers.yaml`."
)


def guidance_for(style: str) -> str:
    """The prose description of what `style` asks the writer to do."""
    return STYLE_GUIDANCE.get(style, _FALLBACK_GUIDANCE)
