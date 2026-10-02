"""Getting a `HeaderStyleProfile` in front of the writer.

A profile that only exists as a loaded object is not "applied" — the brief in
`docs/phases/PHASE-3A.md` task 3a.8 is explicit that this has to *reach the writer*.
Concretely: `autodeck.knowledge.loader.KnowledgeLoader.load_client` already parses
`headers.yaml` into `ClientKnowledge.header_profile`, and
`autodeck.knowledge.context_assembler.AssembledContext` already carries it through to the
content stage — but nothing rendered it into the text the model actually reads. This
module is that render step, plus the one function (`resolve_profile`) that decides which
profile applies to a given build.

## Where this is called from

`autodeck.agents.content._content_prompt` calls `resolve_profile` and
`render_for_prompt` and puts the result in the per-slide prompt it assembles — the same
function that already builds the "budgets", "evidence" and "key messages" sections from
plain Python, not from `prompts/content.md`. `prompts/content.md` is a guardrail path this
task does not edit; see this task's report for the wording that module would need if it is
ever opened, and why the profile still reaches the writer without it.
"""

from __future__ import annotations

from autodeck.design.headers.profile import HeaderStyleProfile, guidance_for


def resolve_profile(
    header_profile: dict[str, object] | None,
    header_style: str | None = None,
    *,
    source: str = "headers.yaml",
) -> HeaderStyleProfile:
    """The profile one build actually writes headers under.

    `header_profile` is `AssembledContext.header_profile` — the client's on-disk
    `headers.yaml`, or `None` for a client without one. `header_style` is the per-deck
    override: `DeckBrief.header_style`, or a build-time `--header-style` flag, both of
    which name only the *voice* (`assertion`, `question_led`, ...), never a full profile.

    Precedence: the client's profile supplies every rule (word budget, casing, hedges,
    avoid list, body limits); `header_style`, when given, replaces only `style` on top of
    it (`HeaderStyleProfile.with_style`). A build with neither gets the neutral defaults.
    """
    profile = HeaderStyleProfile.from_mapping(header_profile, source=source)
    return profile.with_style(header_style)


def render_for_prompt(profile: HeaderStyleProfile) -> str:
    """The profile, as text ready to paste into a slide's content prompt.

    Every line here is guidance for *phrasing* a claim, never a relaxation of what needs a
    citation — the closing line says so explicitly because it is the line most likely to be
    skimmed past, and it is the one line in this section that is not the client's own
    preference.
    """
    lines = [
        f"style: {profile.style} — {guidance_for(profile.style)}",
        f"max words: {profile.max_words}",
        "case: sentence case, not Title Case" if profile.sentence_case else "case: Title Case",
        (
            "terminal punctuation: not allowed (a genuine question the slide answers may "
            "still end in '?')"
            if not profile.terminal_punctuation
            else "terminal punctuation: allowed"
        ),
        (
            f"numbers in headers: {profile.numbers_in_headers} — a number here needs the "
            "same citation as a number anywhere else (A1/A2); it does not become exempt by "
            "being in a title"
        ),
    ]
    if profile.hedges:
        lines.append("preferred hedge vocabulary: " + "; ".join(profile.hedges))
    if profile.avoid:
        lines.append("avoid: " + "; ".join(profile.avoid))
    lines.append(
        f"body copy for this client: at most {profile.body.bullets_max} bullet(s), "
        f"{profile.body.words_per_bullet_max} word(s) each"
    )
    lines.append(
        "A header that asserts something is a `claim` block with a citation, exactly like "
        "any other claim — never `section_header` text written to look decorative. The "
        "style above shapes how a supported header is phrased; it never lowers what needs "
        "support (D12)."
    )
    return "\n".join(f"- {line}" for line in lines)
