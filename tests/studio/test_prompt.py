"""The lead's system prompt (a versioned file) and the base's allowed skills."""

from __future__ import annotations

from autodeck.agents.skills import available_skills
from autodeck.studio.prompt import (
    ALLOWED_SKILLS,
    LEAD_PROMPT_PATH,
    RECAP_REQUEST,
    SKILLS_DIR,
    choice_text,
    skill_index,
    system_prompt,
)

STRICT_ONLY = {"citations", "fidelity", "from-source-to-slide", "headlines", "exemplars"}


def test_the_prompt_is_a_file_under_prompts_studio() -> None:
    assert LEAD_PROMPT_PATH.parts[-3:] == ("prompts", "studio", "lead.md")
    assert LEAD_PROMPT_PATH.is_file()


def test_the_system_prompt_ends_with_the_allowed_skill_index_only() -> None:
    text = system_prompt()
    body = LEAD_PROMPT_PATH.read_text(encoding="utf-8").rstrip()
    assert text == f"{body}\n\n## Skills you can load\n\n{skill_index()}\n"
    for name in ALLOWED_SKILLS:
        assert f"- `{name}`:" in text
    for name in set(available_skills(SKILLS_DIR)) - set(ALLOWED_SKILLS):
        assert f"- `{name}`:" not in text


def test_allowed_skills_exist_and_exclude_the_strict_ones() -> None:
    assert set(ALLOWED_SKILLS) <= set(available_skills(SKILLS_DIR))
    assert not set(ALLOWED_SKILLS) & STRICT_ONLY


def test_the_prompt_states_the_conversation_rules() -> None:
    raw = LEAD_PROMPT_PATH.read_text(encoding="utf-8")
    text = " ".join(raw.split())
    for phrase in (
        "Show, do not ask",
        "Ask only what changes the deck",
        "At most three questions",
        "suggested answer",
        "No order is imposed",
        "can be undone",
        "no citation",
        "built from the current state",
        "You do **not** remember earlier conversations",
    ):
        assert phrase in text, phrase
    tools_section = raw.split("## Tools")[1].split("\n## ")[0]
    assert "`finish`" not in tools_section


def test_choice_text_and_recap_request() -> None:
    assert choice_text("p0003", "B", "Lead with the number") == (
        "I pick option B of p0003: Lead with the number."
    )
    assert choice_text("p0003", "A", "Keep it.") == "I pick option A of p0003: Keep it."
    assert "recap" in RECAP_REQUEST and "change nothing" in RECAP_REQUEST


def test_the_recap_and_the_prompt_use_the_contexts_proposal_terms() -> None:
    from autodeck.studio.context import PROPOSAL_TERMS

    assert "accepted" in RECAP_REQUEST and "dismissed" in RECAP_REQUEST
    assert "which option was chosen" in RECAP_REQUEST
    text = " ".join(LEAD_PROMPT_PATH.read_text(encoding="utf-8").split())
    for phrase in (
        "Never call an accepted proposal dismissed",
        "the other options were not chosen, which is not a dismissal",
        "`replaces`",
        "`insert_at`",
        "A slide has only these fields",
    ):
        assert phrase in text, phrase
    assert "- accepted: the owner picked one option and it was applied." in PROPOSAL_TERMS
