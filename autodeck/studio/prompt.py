"""The lead's system prompt and the fixed model-facing texts of the conversation (Phase 1).

Prompts are product surface (prompts/README.md): the lead's instructions live in
`prompts/studio/lead.md`, a versioned file, never inlined here. This module only assembles
the system prompt from that file and the index of the skills the base allows, and holds
the two short fixed texts the conversation itself writes (the recap request and the text
a proposal pick sends).

**Which skills the base allows.** `prompts/skills/` was written for v2's strict pipeline.
Most skills there teach claim/framing typing, verbatim citation mechanics, the component
catalog or validator behaviour, which the plain base deck does not have (P3, V8); loading
them would teach the lead rules that do not apply and fields that do not exist. The base
allows only the skills whose substance is craft that holds for a plain deck:
`storyline` (the argument), `slide-design` (designing inside a master with a free layout)
and `writing-style` (plain slide prose). Their few strict-flavoured lines are neutralised
by the "About the skills" section of `lead.md`. The reasoning per skill is in
docs/phases/V3-PHASE-1.md.
"""

from __future__ import annotations

from pathlib import Path

from autodeck.agents.skills import load_skill
from autodeck.studio.paths import REPO_ROOT

LEAD_PROMPT_PATH = REPO_ROOT / "prompts" / "studio" / "lead.md"
SKILLS_DIR = REPO_ROOT / "prompts" / "skills"

ALLOWED_SKILLS: tuple[str, ...] = ("storyline", "slide-design", "writing-style")
"""The skills `load_skill` may load in the base, in the order the index lists them."""

RECAP_REQUEST = (
    "This is a returning thread. Before anything else, give the owner a short recap built "
    "only from the context above, as your instructions describe, and change nothing. "
    "Report each proposal's status in the context's own terms: accepted (say which option "
    "was chosen), dismissed, or open."
)
"""The user text of a returning thread's opening turn (`UserLine.origin == "recap"`)."""

CONTEXT_SEPARATOR = "\n\n---\n\n"
"""Joins merged user-role texts (the context and the first request, notes and a message)."""


def choice_text(proposal_id: str, option_id: str, label: str) -> str:
    """The user text sent when the owner picks an option with the button
    (`UserLine.origin == "choice"`): `I pick option B of p0003: <label>.` exactly, with
    the label's trailing full stop not doubled."""
    label = label.strip()
    end = "" if label.endswith((".", "!", "?")) else "."
    return f"I pick option {option_id} of {proposal_id}: {label}{end}"


def skill_index(skills_dir: Path = SKILLS_DIR) -> str:
    """One line per allowed skill, in `ALLOWED_SKILLS` order:
    ``- `<name>`: <summary> (use when: <use_when>)``.

    Raises:
        SkillError: (v2's) an allowed skill file is missing or malformed.
    """
    lines = []
    for name in ALLOWED_SKILLS:
        skill = load_skill(name, skills_dir=skills_dir)
        lines.append(f"- `{skill.name}`: {skill.summary} (use when: {skill.use_when})")
    return "\n".join(lines)


def system_prompt(
    *, prompt_path: Path = LEAD_PROMPT_PATH, skills_dir: Path = SKILLS_DIR
) -> str:
    """The lead's system prompt: `lead.md` (stripped of trailing whitespace), a blank
    line, `## Skills you can load`, a blank line, and `skill_index()`, ending with one
    newline. The same text for every thread and turn, so providers can cache it."""
    body = prompt_path.read_text(encoding="utf-8").rstrip()
    return f"{body}\n\n## Skills you can load\n\n{skill_index(skills_dir)}\n"
