"""`autodeck/design/headers/` — profile loading, prompt application, and flow QA (3a.8).

The property worth protecting throughout: a `HeaderStyleProfile` can only change how a
supported header is *phrased*. Nothing here ever lowers what needs a citation — every
later test in this file that renders a profile or reads a flow report restates that.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.design.headers.flow import flow_report
from autodeck.design.headers.profile import (
    HeaderProfileError,
    HeaderStyleProfile,
    guidance_for,
)
from autodeck.design.headers.prompt import render_for_prompt, resolve_profile
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import Block, Citation, Claim, Deck, Slide

TOKENS = DesignTokens.load(Path("config/tokens/dev.json"))

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


# ---------------------------------------------------------------------------
# Horizontal-flow QA
# ---------------------------------------------------------------------------


def citation() -> Citation:
    return Citation.for_quote(
        doc_id="paper-1",
        page=1,
        bbox=(0.0, 0.0, 1.0, 1.0),
        quote="a quoted span",
        retrieved_by="writer",
    )


def header_block(text: str, *, kind: str = "section_header", slot: str = "headline") -> Block:
    if kind == "claim":
        return Block(
            id="h1",
            kind="claim",
            slot=slot,
            claim=Claim(text=text, citations=[citation()]),
        )
    return Block(id="h1", kind=kind, slot=slot, text=text)  # type: ignore[arg-type]


def deck_with_slides(*slides: Slide) -> Deck:
    return Deck(
        run_id="r1",
        project="p",
        client="c",
        audience="CTO",
        version=1,
        slides=list(slides),
        theme_ref="config/tokens/dev.json",
        component_lib_version="test",
    )


class TestFlowReport:
    def test_a_section_header_is_read_in_order(self) -> None:
        deck = deck_with_slides(
            Slide(
                id="s1",
                narrative_role="framing",
                component="big_number",
                blocks=[header_block("Where the money actually goes")],
            )
        )
        report = flow_report(deck, TOKENS, HeaderStyleProfile())
        [line] = report.lines
        assert line.slide_id == "s1"
        assert line.kind == "section_header"
        assert line.text == "Where the money actually goes"
        assert "top to bottom" in report.render()

    def test_a_claim_header_is_read_correctly_by_flow(self) -> None:
        """D12: a fact-bearing header written as `kind='claim'` is read as one, not as a
        blank slot — `Block` forbids a `claim` block from also carrying `text`, so this is
        the one place a naive `block.text` read would silently under-report."""
        deck = deck_with_slides(
            Slide(
                id="s1",
                narrative_role="evidence",
                component="big_number",
                blocks=[header_block("KV-cache waste is the binding constraint", kind="claim")],
            )
        )
        report = flow_report(deck, TOKENS, HeaderStyleProfile())
        [line] = report.lines
        assert line.kind == "claim"
        assert line.text == "KV-cache waste is the binding constraint"
        assert not report.findings

    def test_avoid_and_max_words_are_advisory_only(self) -> None:
        """The mechanical checks flag, they never block — that is A5's job, on the IR,
        regardless of what this report says."""
        profile = HeaderStyleProfile.from_mapping(
            {"max_words": 3, "avoid": ["revolutionary"], "terminal_punctuation": False}
        )
        deck = deck_with_slides(
            Slide(
                id="s1",
                narrative_role="framing",
                component="big_number",
                blocks=[header_block("A revolutionary way to think about serving cost.")],
            )
        )
        report = flow_report(deck, TOKENS, profile)
        details = " ".join(f.detail for f in report.findings)
        assert "word(s) over" in details
        assert "revolutionary" in details
        assert "punctuation" in details
        # Advisory only: the report itself carries no blocking flag or exception.
        assert isinstance(report.render(), str)

    def test_a_verbatim_repeat_is_flagged(self) -> None:
        deck = deck_with_slides(
            Slide(
                id="s1",
                narrative_role="framing",
                component="big_number",
                blocks=[header_block("Serve better before buying more")],
            ),
            Slide(
                id="s2",
                narrative_role="evidence",
                component="big_number",
                blocks=[header_block("Serve better before buying more")],
            ),
        )
        report = flow_report(deck, TOKENS, HeaderStyleProfile())
        assert any("repeats slide s1" in f.detail for f in report.findings)

    def test_a_component_with_no_registered_header_slot_is_skipped_not_failed(self) -> None:
        deck = deck_with_slides(
            Slide(id="s1", narrative_role="framing", component="not_a_real_component")
        )
        report = flow_report(deck, TOKENS, HeaderStyleProfile())
        [line] = report.lines
        assert line.kind == "(no header slot)"
        assert not report.findings

    def test_render_reports_an_empty_header_slot(self) -> None:
        deck = deck_with_slides(
            Slide(id="s1", narrative_role="framing", component="big_number")
        )
        report = flow_report(deck, TOKENS, HeaderStyleProfile())
        assert any("no block fills" in f.detail for f in report.findings)
