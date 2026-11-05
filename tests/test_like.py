"""`--like DECK` (Phase 4, task 4.3): build a deck like one of the client's past decks.

The reference deck teaches shape and voice, never truth (A1): its text reaches the writer as
its own prompt section, and never an evidence pack, a seed, a store or a citable set. The
deck is resolved inside the client's own `decks/` folder (A4) and snapshotted into the run
(A6), so a later change to the folder cannot change the run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import autodeck.agents.compose as compose_module
import autodeck.providers.registry as registry_module
from autodeck.agents.content import (
    ProposedBlock,
    ProposedCitation,
    ProposedClaim,
    resolve_blocks,
)
from autodeck.audit.framing_linter import lint_header
from autodeck.cli import run_source_hashes
from autodeck.design.reference import ingest_client_decks
from autodeck.design.reference.like import like_description, like_summary, load_like
from autodeck.ingest.document_store import Document, DocumentStore
from autodeck.ir.models import Block, Citation, Claim, Slide
from autodeck.ir.store import IRStore
from autodeck.knowledge.context_assembler import ClientNamespace
from tests.test_cli_draft import (
    CLARIFIED,
    COMPOSED,
    AgentComposer,
    Counting,
    World,
    agent_script,
)
from tests.test_cli_gate2 import CLIENT, DOC_ID, PROJECT, QUOTE, element
from tests.test_reference_decks import TITLES, build_deck

DECK = "Margin Review.pptx"
REFERENCE_TEXT = [*TITLES.values(), "Retail margin review", "Where we are today"]


class LikeWorld(World):
    """The draft-first world, plus an ingested reference deck in `acme`'s `decks/`."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *answers) -> None:  # type: ignore[no-untyped-def]
        super().__init__(tmp_path, monkeypatch, *answers)
        for client in ("acme", "globex"):
            (self.knowledge / "clients" / client / "decks" / "past.pptx").unlink()
        decks = self.knowledge / "clients" / CLIENT / "decks"
        build_deck(decks / DECK)
        build_deck(decks / "Not Ingested.pptx")
        build_deck(self.knowledge / "clients" / "globex" / "decks" / "Globex Only.pptx")
        ingest_client_decks(
            ClientNamespace(client=CLIENT, knowledge_root=self.knowledge), [DECK]
        )
        other = ClientNamespace(client="globex", knowledge_root=self.knowledge)
        ingest_client_decks(other, ["Globex Only.pptx"])

    def clarify_like(self, name: str = "margin-review", run: str = "r1"):  # type: ignore[no-untyped-def]
        return self.run(
            "clarify", run, "--client", CLIENT, "--project", PROJECT,
            "--prompt", "Show that the kernel rewrite raised training throughput.",
            "--like", name, *self.data_roots,
        )  # fmt: skip


def test_clarify_like_snapshots_the_profile_into_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = LikeWorld(tmp_path, monkeypatch, CLARIFIED, COMPOSED)

    result = w.clarify_like()
    assert result.exit_code == 0, result.output

    like = load_like(w.runs / "r1")
    assert like is not None and like["deck"] == "margin-review"
    assert set(like) == {"deck", "storyline", "header", "voice", "density"}
    assert like["storyline"]["slide_count"] == 10
    assert like["storyline"]["arc"][3] == {
        "n": 4,
        "role": "content",
        "title": TITLES["content1"],
    }
    assert like["density"]["median_words_per_content_slide"] == 18
    # The clarify call sees one line, so its questions do not re-ask the length.
    assert "build it like margin-review: 10 slides, 2 sections" in w.composer.prompts[0]
    assert TITLES["content1"] not in w.composer.prompts[0]
    # A6: the run's manifest sources cover the snapshot.
    assert "like" in run_source_hashes(w.runs / "r1")


def test_the_snapshot_is_what_a_later_draft_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproducible (A6): removing the deck after clarify changes nothing for the draft."""
    w = LikeWorld(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    assert w.clarify_like().exit_code == 0
    assert w.run("answer", "r1", "--accept-all", *w.roots).exit_code == 0
    decks = w.knowledge / "clients" / CLIENT / "decks"
    for path in decks.glob("margin-review*"):
        path.unlink()
    (decks / DECK).unlink()

    result = w.run("draft", "r1", *w.data_roots)
    assert result.exit_code == 0, result.output
    prompt = w.composer.prompts[1]
    assert "# A deck to build like" in prompt  # prompts/reference_like.md
    assert "2. [agenda] Agenda" in prompt
    assert f"4. [content] {TITLES['content1']}" in prompt
    assert "Median words per content slide: 18" in prompt
    assert "Slide count: 10" in prompt
    assert "style: assertion" in prompt and "at most 9 words" in prompt
    assert "median sentence length: 3 words" in prompt


def test_reference_text_never_enters_the_evidence_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = LikeWorld(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    assert w.clarify_like().exit_code == 0
    assert w.run("answer", "r1", "--accept-all", *w.roots).exit_code == 0
    assert w.run("draft", "r1", *w.data_roots).exit_code == 0

    prompt = w.composer.prompts[1]
    like_part, _, pack_part = prompt.partition("# Evidence pack")
    assert pack_part, "the prompt has an evidence pack section"
    assert TITLES["content1"] in like_part
    for text in REFERENCE_TEXT:
        assert text not in pack_part
    # Nothing written to the run's source folder (the store a citation resolves against)
    # carries it either.
    for path in (w.runs / "r1" / "source").glob("*"):
        for text in REFERENCE_TEXT:
            assert text not in path.read_text(encoding="utf-8")


def test_the_agent_is_told_the_arc_and_its_spans_hold_no_reference_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = LikeWorld(tmp_path, monkeypatch, CLARIFIED)
    w.composer = AgentComposer(CLARIFIED)
    roles = {"composer": w.composer, "validation": w.judge, "advisor": Counting()}
    monkeypatch.setattr(
        registry_module.ModelRegistry, "provider_for", lambda self, role, **kw: roles[role]
    )
    shown: list[str] = []
    from autodeck.agents import deck_agent

    real = deck_agent.seed_pack

    def spy(*args, **kwargs):  # type: ignore[no-untyped-def]
        pack = real(*args, **kwargs)
        shown.extend(span.text for span in pack.spans)
        shown.append(pack.text)
        return pack

    monkeypatch.setattr(deck_agent, "seed_pack", spy)
    assert w.clarify_like().exit_code == 0
    assert w.run("answer", "r1", "--accept-all", *w.roots).exit_code == 0
    w.composer.turns = agent_script(length_target=2)

    result = w.run("draft", "r1", "--agent", *w.data_roots)
    assert result.exit_code == 0, result.output

    opening = (w.runs / "r1" / "session" / "transcript.jsonl").read_text()
    assert "# A deck to build like" in opening and TITLES["content1"] in opening
    assert shown, "the spy saw the seed"
    for text in REFERENCE_TEXT:
        assert not any(text in piece for piece in shown)


def test_a_claim_quoting_a_reference_title_fails_resolution(tmp_path: Path) -> None:
    store = DocumentStore(tmp_path / "corpus")
    store.add(
        Document(
            doc_id=DOC_ID,
            source_path=f"{DOC_ID}.pdf",
            page_count=6,
            elements=[element(DOC_ID, QUOTE)],
        )
    )
    rejections: list[str] = []
    blocks = resolve_blocks(
        [
            ProposedBlock(
                id="b1",
                kind="claim",
                slot="headline",
                claim=ProposedClaim(
                    text="Automated counts cut stock errors by 31 percent.",
                    citations=[ProposedCitation(doc_id=DOC_ID, quote=TITLES["content2"])],
                ),
            )
        ],
        store=store,
        claims=[],
        spans=[],
        location="slide s1",
        rejections=rejections,
    )
    assert blocks == [] and rejections


def test_a_header_number_only_the_reference_had_is_blocked() -> None:
    claim = Claim(
        text="Training throughput rose from 412 to 671 sequences per second.",
        citations=[
            Citation.for_quote(
                doc_id=DOC_ID, page=4, bbox=(0, 0, 1, 1), quote=QUOTE, retrieved_by="writer"
            )
        ],
    )
    slide = Slide(
        id="s1",
        narrative_role="evidence",
        component="bullets_supporting",
        blocks=[
            Block(
                id="h",
                kind="section_header",
                slot="headline",
                text="Automated counts cut stock errors by 31%",
            ),
            Block(id="b1", kind="claim", slot="points", claim=claim),
        ],
    )
    demotion = lint_header(slide.blocks[0], slide)
    assert demotion is not None and {r.fragment for r in demotion.reasons} == {"31%"}


def test_a_deck_without_a_profile_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = LikeWorld(tmp_path, monkeypatch, CLARIFIED)
    result = w.clarify_like("Not Ingested.pptx")
    assert result.exit_code == 1
    assert "autodeck reference ingest" in result.output
    assert len(w.composer.prompts) == 0 and not (w.runs / "r1" / "like.json").exists()


@pytest.mark.parametrize(
    "name", ["Globex Only.pptx", "globex-only", "../globex/decks/Globex Only.pptx"]
)
def test_a_deck_outside_the_clients_namespace_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """A4: a `--like` build for acme never reads globex's deck, by name or by path."""
    w = LikeWorld(tmp_path, monkeypatch, CLARIFIED)
    result = w.clarify_like(name)
    assert result.exit_code == 1, result.output
    assert len(w.composer.prompts) == 0
    assert not (w.runs / "r1" / "like.json").exists()


def test_a_later_like_on_draft_is_refused_once_the_run_has_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = LikeWorld(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    assert w.clarify_like().exit_code == 0
    assert w.run("answer", "r1", "--accept-all", *w.roots).exit_code == 0
    result = w.run("draft", "r1", "--like", "Not Ingested.pptx", *w.data_roots)
    assert result.exit_code == 1 and "keeps the deck it started with" in result.output
    assert len(w.composer.prompts) == 1  # no compose call was made
    assert load_like(w.runs / "r1")["deck"] == "margin-review"  # type: ignore[index]


def test_like_on_draft_starts_a_run_that_had_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = LikeWorld(tmp_path, monkeypatch, CLARIFIED, COMPOSED)
    assert w.clarify().exit_code == 0
    assert w.run("answer", "r1", "--accept-all", *w.roots).exit_code == 0
    result = w.run("draft", "r1", "--like", "margin-review", *w.data_roots)
    assert result.exit_code == 0, result.output
    assert "2. [agenda] Agenda" in w.composer.prompts[1]
    assert IRStore(w.runs, "r1").load().slides


def test_revise_keeps_the_arc_in_front_of_the_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_cli_draft import REVISED

    w = LikeWorld(tmp_path, monkeypatch, CLARIFIED, COMPOSED, REVISED)
    assert w.clarify_like().exit_code == 0
    assert w.run("answer", "r1", "--accept-all", *w.roots).exit_code == 0
    assert w.run("draft", "r1", *w.data_roots).exit_code == 0
    result = w.run("revise", "r1", "--instruction", "Soften slide two.", *w.data_roots)
    assert result.exit_code == 0, result.output
    assert "2. [agenda] Agenda" in w.composer.prompts[-1]


def test_the_description_has_the_arc_the_sections_and_the_rules() -> None:
    like = {
        "deck": "d",
        "storyline": {
            "slide_count": 3,
            "arc": [
                {"n": 1, "role": "title", "title": "A"},
                {"n": 2, "role": "content", "title": "B"},
                {"n": 3, "role": "closing", "title": "C"},
            ],
            "sections": [{"start": 1, "slides": 3}],
            "role_counts": {},
        },
        "header": {"style": "topic_led", "max_words": 6, "numbers_in_headers": "discouraged"},
        "voice": {"median_sentence_words": 7, "mean_sentence_words": 7, "person": {"we": 1.0}},
        "density": {"median_words_per_content_slide": 30, "mean_words_per_slide": 20},
    }
    text = like_description(like)
    assert "1. [title] A\n2. [content] B\n3. [closing] C" in text
    assert "numbers in headers: discouraged" in text and "we 100%" in text
    assert like_summary(like) == "build it like d: 3 slides, 1 sections"
    assert compose_module.like_prompt_section(like).startswith("# A deck to build like")
    assert json.dumps(like)
