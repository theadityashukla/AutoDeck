"""Deck-craft skills: versioned prompt files loaded into the writers' system prompts.

A skill is `prompts/skills/<name>.md`: YAML front matter (`name`, `summary`, `use_when`)
followed by a body. Like every prompt it is a file, so its hash reaches the build manifest
(A6) through `hash_prompts`, which walks `prompts/` recursively.

Each writer role loads a fixed, ordered set (`SKILL_SETS`). The set is static on purpose:
which skills a role sees must not depend on the request, or two builds of the same input
could be written under different instructions. `visual-review` is deliberately not in any
writer set — it is for a later agent that looks at rendered slides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SKILLS_DIR = Path("prompts/skills")

#: The same literal as `compose.PROMPT_SEPARATOR`. Defined here rather than imported because
#: `compose` imports this module.
SEPARATOR = "\n\n---\n\n"

_CORE: tuple[str, ...] = (
    "deck-thinking",
    "storyline",
    "headlines",
    "from-source-to-slide",
    "slide-bodies",
    "fidelity",
    "writing-style",
    "charts-and-diagrams",
    "citations",
)
"""What every role that writes a whole deck or whole slides needs."""

#: Per role, in load order. Narrowed after run XLP3 (2026-10-13): every role used to get every
#: skill, about 26k tokens, and a small composer followed little of it. Each role now gets
#: what its call does. Redesign guidance is only for redesigns. A repair fixes listed
#: blocks, so it needs the mechanics and the fit rules, not the storyline or the exemplars.
SKILL_SETS: dict[str, tuple[str, ...]] = {
    "compose": (*_CORE, "exemplars", "self-review"),
    "revise": (*_CORE, "self-review"),
    "redesign": (*_CORE, "reworking-decks", "self-review"),
    "repair": ("deck-thinking", "from-source-to-slide", "slide-bodies", "fidelity", "citations"),
    "content": (*_CORE, "exemplars", "self-review"),
}

#: B69 creative mode: the writer places each slide itself, so each whole-deck role also
#: gets `slide-design`. Loaded right after the core so it sits beside `slide-bodies`.
CREATIVE_SUFFIX = "-creative"
for _role in ("compose", "revise", "redesign"):
    _base = SKILL_SETS[_role]
    _at = _base.index("citations") + 1
    SKILL_SETS[_role + CREATIVE_SUFFIX] = (*_base[:_at], "slide-design", *_base[_at:])
del _role, _base, _at

_REQUIRED_FIELDS = ("name", "summary", "use_when")


class SkillError(ValueError):
    """A skill file is missing or malformed, or a name/role is unknown."""


@dataclass(frozen=True)
class Skill:
    name: str
    summary: str
    use_when: str
    body: str


def available_skills(skills_dir: Path = SKILLS_DIR) -> list[str]:
    """Sorted skill names (file stems) in `skills_dir`."""
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        return []
    return sorted(p.stem for p in skills_dir.glob("*.md"))


def load_skill(name: str, *, skills_dir: Path = SKILLS_DIR) -> Skill:
    """Parse one skill file.

    Raises:
        SkillError: unknown name (the message lists the available ones), unreadable file,
            missing or unterminated front matter, a missing or empty field, or a `name`
            that is not the file stem.
    """
    skills_dir = Path(skills_dir)
    path = skills_dir / f"{name}.md"
    if not path.is_file():
        raise SkillError(
            f"unknown skill {name!r}; available: {', '.join(available_skills(skills_dir)) or '(none)'}"
        )
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError(f"{path}: missing YAML front matter (the file must start with '---')")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise SkillError(f"{path}: unterminated YAML front matter (no closing '---')")
    try:
        meta = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise SkillError(f"{path}: front matter is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise SkillError(f"{path}: front matter must be a mapping with {', '.join(_REQUIRED_FIELDS)}")
    values: dict[str, str] = {}
    for key in _REQUIRED_FIELDS:
        value = meta.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SkillError(f"{path}: front matter field {key!r} is missing or empty")
        values[key] = value.strip()
    if values["name"] != path.stem:
        raise SkillError(f"{path}: name {values['name']!r} does not match the file stem {path.stem!r}")
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return Skill(values["name"], values["summary"], values["use_when"], body)


def skill_index(skills_dir: Path = SKILLS_DIR) -> str:
    """A markdown list of every skill, for an agent that chooses which to read."""
    skills = [load_skill(n, skills_dir=skills_dir) for n in available_skills(skills_dir)]
    return "\n".join(f"- `{s.name}` — {s.summary} (use when: {s.use_when})" for s in skills)


_PROJECT_BLOCK = re.compile(
    r"<!-- project: (?P<project>[\w.-]+) -->\n(?P<body>.*?)<!-- end project -->\n?", re.S
)


def _without_project(body: str, project: str | None) -> str:
    """Drop sections tagged for `project`; keep the rest, with the tags removed.

    The `exemplars` skill tags each gold deck with its project. A draft on that same project
    must not see it: run XLP4 copied the semaglutide gold deck's figure label word for word,
    and a draft scored against a gold deck it was shown proves nothing (B65).
    """
    def keep(match: re.Match[str]) -> str:
        return "" if project and match["project"] == project else match["body"]

    return _PROJECT_BLOCK.sub(keep, body)


def skills_text(
    role: str, *, skills_dir: Path = SKILLS_DIR, project: str | None = None
) -> str:
    """The skills a writer role loads, in `SKILL_SETS` order, as one prompt section.

    With `project`, any section a skill tags for that project is withheld (B65).
    """
    if role not in SKILL_SETS:
        raise SkillError(f"unknown role {role!r}; roles with skills: {', '.join(sorted(SKILL_SETS))}")
    header = (
        "# Skills\n\nThe skills below are how to build a deck. "
        "Each is referred to by its name in backticks."
    )
    parts = [header]
    for name in SKILL_SETS[role]:
        skill = load_skill(name, skills_dir=skills_dir)
        parts.append(f"## Skill: `{skill.name}`\n\n{_without_project(skill.body, project)}")
    return SEPARATOR.join(parts)
