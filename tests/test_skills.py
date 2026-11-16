"""Deck-craft skills (`autodeck/agents/skills.py`) and their wiring into writer prompts."""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.agents.compose import (
    COMPONENTS_PROMPT,
    COMPOSE_PROMPT,
    PROVENANCE_PROMPTS,
    _writer_system,
)
from autodeck.agents.skills import (
    SKILL_SETS,
    SKILLS_DIR,
    SkillError,
    available_skills,
    load_skill,
    skill_index,
    skills_text,
)
from autodeck.audit.manifest import hash_prompts

NAMES = available_skills()


def test_there_are_skills() -> None:
    assert len(NAMES) >= 12


@pytest.mark.parametrize("name", NAMES)
def test_every_skill_loads_and_its_name_matches_its_stem(name: str) -> None:
    skill = load_skill(name)
    assert skill.name == name
    assert skill.summary and skill.use_when and skill.body.strip()
    assert not skill.body.startswith("\n")
    assert not skill.body.startswith("---")


def test_skill_sets_reference_existing_skills_and_exclude_visual_review() -> None:
    assert set(SKILL_SETS) >= {"compose", "revise", "redesign", "repair", "content"}
    for role, names in SKILL_SETS.items():
        assert names[0] == "deck-thinking"
        # A repair fixes listed blocks: no storyline, exemplars or self-review (XLP3 trim).
        if role != "repair":
            assert names[-1] == "self-review"
        assert len(set(names)) == len(names)
        assert "visual-review" not in names
        for name in names:
            assert name in NAMES, (role, name)


@pytest.mark.parametrize("role", sorted(SKILL_SETS))
def test_skills_text_contains_every_skill_body_in_order(role: str) -> None:
    text = skills_text(role)
    assert text.startswith("# Skills\n\nThe skills below are how to build a deck.")
    last = -1
    for name in SKILL_SETS[role]:
        marker = f"## Skill: `{name}`"
        assert marker in text
        assert text.index(marker) > last
        last = text.index(marker)
        heading = next(l for l in load_skill(name).body.splitlines() if l.startswith("#"))
        assert heading in text
    assert "## Skill: `visual-review`" not in text


def test_unknown_skill_lists_the_available_names() -> None:
    with pytest.raises(SkillError, match="deck-thinking"):
        load_skill("no-such-skill")


def test_unknown_role_raises() -> None:
    with pytest.raises(SkillError):
        skills_text("painter")


def _write(tmp_path: Path, name: str, text: str) -> Path:
    (tmp_path / f"{name}.md").write_text(text, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "text",
    [
        "# no front matter\n",
        "---\nname: x\nsummary: s\nuse_when: u\n# never closed\n",
        "---\nsummary: s\nuse_when: u\n---\nbody\n",
        "---\nname: x\nsummary: ''\nuse_when: u\n---\nbody\n",
        "---\nname: x\nsummary: s\n---\nbody\n",
        "---\nname: other\nsummary: s\nuse_when: u\n---\nbody\n",
        "---\n- a\n- list\n---\nbody\n",
        "---\nname: [unclosed\n---\nbody\n",
    ],
)
def test_malformed_front_matter_raises(tmp_path: Path, text: str) -> None:
    _write(tmp_path, "x", text)
    with pytest.raises(SkillError):
        load_skill("x", skills_dir=tmp_path)


def test_a_wellformed_temp_skill_loads(tmp_path: Path) -> None:
    _write(tmp_path, "x", "---\nname: x\nsummary: a summary\nuse_when: always\n---\n\n\n# X\n\ntext\n")
    skill = load_skill("x", skills_dir=tmp_path)
    assert (skill.summary, skill.use_when) == ("a summary", "always")
    assert skill.body.startswith("# X")


def test_skill_index_lists_every_skill() -> None:
    index = skill_index()
    for name in NAMES:
        skill = load_skill(name)
        assert f"- `{name}` — {skill.summary} (use when: {skill.use_when})" in index


def test_the_manifest_hashes_every_skill() -> None:
    hashes = hash_prompts(Path("prompts"))
    for name in NAMES:
        assert f"skills/{name}.md" in hashes


@pytest.mark.parametrize("role", ["compose", "revise", "redesign", "repair"])
def test_the_writer_system_prompt_is_role_components_skills_provenance(role: str) -> None:
    system = _writer_system(COMPOSE_PROMPT, role=role, provenance="strict")

    assert COMPOSE_PROMPT.read_text(encoding="utf-8") in system
    assert COMPONENTS_PROMPT.read_text(encoding="utf-8") in system
    assert load_skill("deck-thinking").body in system
    assert PROVENANCE_PROMPTS["strict"].read_text(encoding="utf-8") in system
    first_line = Path("prompts/content.md").read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "# Content"
    assert f"\n{first_line}\n" not in system
    assert SKILLS_DIR.is_dir()


def test_the_content_system_prompt_carries_the_skills() -> None:
    from autodeck.agents import content

    assert content.PROMPT_PATH.read_text(encoding="utf-8")
    assert "## Skill: `charts-and-diagrams`" in skills_text("content")


def test_a_projects_own_gold_exemplar_is_withheld() -> None:
    """B65: run XLP4 copied the semaglutide gold deck's wording into a semaglutide draft."""
    everything = skills_text("compose")
    semaglutide = skills_text("compose", project="oral-semaglutide")
    assert "Exemplar 1: oral semaglutide" in everything
    assert "Exemplar 1: oral semaglutide" not in semaglutide
    assert "Exemplar 2: Attention Is All You Need" in semaglutide
    assert "<!-- project:" not in everything and "<!-- end project" not in everything


def test_the_compose_prompt_withholds_the_runs_own_exemplar() -> None:
    from autodeck.agents import compose

    system = compose._writer_system(
        compose.COMPOSE_PROMPT, role="compose", provenance="normal", project="lejepa-ssl"
    )
    assert "Exemplar 3: LeJEPA" not in system and "Exemplar 1: oral semaglutide" in system
