"""`autodeck/design/headers/` — profile loading, prompt application, and flow QA (3a.8).

The property worth protecting throughout: a `HeaderStyleProfile` can only change how a
supported header is *phrased*. Nothing here ever lowers what needs a citation — every
later test in this file that renders a profile or reads a flow report restates that.
"""

from __future__ import annotations

import pytest

from autodeck.design.headers.profile import (
    HeaderProfileError,
    HeaderStyleProfile,
    guidance_for,
)
from autodeck.design.headers.prompt import render_for_prompt, resolve_profile

NORTHWIND_YAML: dict[str, object] = {
    "style": "assertion",
    "max_words": 12,
    "sentence_case": True,
    "terminal_punctuation": False,
    "numbers_in_headers": "allowed",
    "hedges": ["on the reported setup"],
    "avoid": ["revolutionary", "10x"],
    "body": {"bullets_max": 5, "words_per_bullet_max": 18},
}


# ---------------------------------------------------------------------------
# HeaderStyleProfile — loading
# ---------------------------------------------------------------------------


class TestProfileLoading:
    def test_no_profile_is_the_neutral_default(self) -> None:
        profile = HeaderStyleProfile.from_mapping(None)
        assert profile.style == "topic_led"
        assert profile.numbers_in_headers == "allowed"
        assert profile.avoid == []

    def test_the_seed_headers_yaml_shape_loads(self) -> None:
        profile = HeaderStyleProfile.from_mapping(NORTHWIND_YAML)
        assert profile.style == "assertion"
        assert profile.max_words == 12
        assert profile.hedges == ["on the reported setup"]
        assert profile.avoid == ["revolutionary", "10x"]
        assert profile.body.bullets_max == 5
        assert profile.body.words_per_bullet_max == 18

    def test_an_unknown_field_is_reported_loudly_not_ignored(self) -> None:
        with pytest.raises(HeaderProfileError, match="headers\\.yaml"):
            HeaderStyleProfile.from_mapping({"style": "assertion", "not_a_real_field": 1})

    def test_a_malformed_body_is_reported(self) -> None:
        with pytest.raises(HeaderProfileError):
            HeaderStyleProfile.from_mapping({"body": {"bullets_max": "five"}})

    def test_with_style_is_the_one_flag_switch(self) -> None:
        """Swapping the voice keeps every other rule the client's profile set."""
        base = HeaderStyleProfile.from_mapping(NORTHWIND_YAML)
        switched = base.with_style("question_led")
        assert switched.style == "question_led"
        assert switched.max_words == base.max_words
        assert switched.avoid == base.avoid
        assert switched.hedges == base.hedges

    def test_with_style_none_or_same_is_a_no_op(self) -> None:
        base = HeaderStyleProfile.from_mapping(NORTHWIND_YAML)
        assert base.with_style(None) is base
        assert base.with_style("assertion") is base

    def test_guidance_falls_back_for_an_unknown_style_name(self) -> None:
        assert "no built-in guidance" in guidance_for("a-client-invented-name")
        assert "question" in guidance_for("question_led").lower()


# ---------------------------------------------------------------------------
# resolve_profile / render_for_prompt — reaching the writer
# ---------------------------------------------------------------------------


class TestApplication:
    def test_resolve_profile_combines_client_profile_and_deck_override(self) -> None:
        profile = resolve_profile(NORTHWIND_YAML, "question_led")
        assert profile.style == "question_led"
        assert profile.max_words == 12  # kept from the client profile

    def test_resolve_profile_with_no_client_profile_and_no_override(self) -> None:
        profile = resolve_profile(None, None)
        assert profile.style == "topic_led"

    def test_rendered_prompt_never_waives_the_citation_requirement(self) -> None:
        rendered = render_for_prompt(resolve_profile(NORTHWIND_YAML, None))
        assert "claim" in rendered
        assert "never lowers what needs support" in rendered
        assert "revolutionary" in rendered
        assert "12" in rendered

    def test_rendered_prompt_names_the_chosen_style_and_its_guidance(self) -> None:
        rendered = render_for_prompt(resolve_profile(None, "question_led"))
        assert "question_led" in rendered
        assert "question" in rendered.lower()
