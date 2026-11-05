"""`autodeck knowledge propose` / `apply` (task 4.7): updates are a diff a person reads (A7).

Built offline: a finished run is an IR on disk, with no model call anywhere.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autodeck.cli import app
from autodeck.ir.models import (
    Block,
    Citation,
    Claim,
    Deck,
    HeadlineCheck,
    Slide,
)
from autodeck.ir.store import IRStore
from autodeck.knowledge.loader import KnowledgeLoader, parse_claims_markdown
from autodeck.knowledge.update_proposer import (
    UpdateProposalError,
    apply_patch,
    propose_updates,
)
from tests.test_knowledge import build_knowledge

runner = CliRunner()
CLIENT = "acme"
OTHER = "globex"
PROJECT = "attention-efficiency"
RUN = "r1"
TODAY = date(2026, 5, 1)


def cite(doc_id: str, quote: str, page: int = 2) -> Citation:
    return Citation.for_quote(
        doc_id=doc_id, page=page, bbox=(0, 0, 1, 1), quote=quote, retrieved_by="writer"
    )


def claim_block(bid: str, slot: str, text: str, doc_id: str, quote: str, verdict: str) -> Block:
    return Block(
        id=bid,
        kind="claim",
        slot=slot,
        claim=Claim(text=text, citations=[cite(doc_id, quote)], verdict=verdict),  # type: ignore[arg-type]
    )


def make_deck(
    client: str = CLIENT, run_id: str = RUN, slides: list[Slide] | None = None
) -> Deck:
    return Deck(
        run_id=run_id,
        project=PROJECT,
        client=client,
        audience="CTO",
        version=1,
        slides=slides if slides is not None else default_slides(),
        theme_ref="no-such-tokens.json",
        component_lib_version="1",
        provenance="normal",
    )


def slide(sid: str, blocks: list[Block], **extra: object) -> Slide:
    return Slide(id=sid, narrative_role="evidence", component="quote", blocks=blocks, **extra)  # type: ignore[arg-type]


def default_slides() -> list[Slide]:
    return [
        slide(
            "s1",
            [
                claim_block(
                    "b1",
                    "headline",
                    "Rewrite lifted throughput",
                    "kaplan2024",
                    "Throughput rose a lot in the new run.",
                    "supported",
                ),
                claim_block(
                    "b2",
                    "quote",
                    "Paged cache cut memory use",
                    "kaplan2024",
                    "Memory use fell with paging.",
                    "supported",
                ),
            ],
        ),
        slide(
            "s2",
            [
                claim_block(
                    "b3",
                    "headline",
                    "Unchecked claim here",
                    "kaplan2024",
                    "Never verified.",
                    "unsupported",
                ),
                claim_block(
                    "b4",
                    "quote",
                    "The CTO said the budget is fixed",
                    "conversation--r1",
                    "the budget is fixed",
                    "supported",
                ),
                claim_block(
                    "b5",
                    "x",
                    "Transcript fact",
                    "transcript--m1",
                    "we agreed on Friday",
                    "supported",
                ),
                claim_block(
                    "b6",
                    "y",
                    "Client deck fact",
                    "client-deck--old",
                    "old deck says so",
                    "supported",
                ),
            ],
        ),
    ]


def file_section(patch: str, rel: str) -> str:
    """The part of a patch that changes `rel`."""
    head = f"diff --git a/knowledge/{rel} "
    return patch.split(head)[1].split("diff --git")[0]


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


class World:
    def __init__(self, tmp_path: Path, deck: Deck | None = None) -> None:
        self.knowledge = build_knowledge(tmp_path)
        self.runs = tmp_path / "runs"
        self.tmp = tmp_path
        deck = deck or make_deck()
        IRStore(self.runs, deck.run_id).save(deck)
        self.deck = deck

    @property
    def client_root(self) -> Path:
        return self.knowledge / "clients" / self.deck.client

    def propose(self, run_id: str = RUN) -> str:
        return propose_updates(self.runs, run_id, self.knowledge, today=TODAY).render()


def test_only_supported_corpus_claims_are_proposed(tmp_path: Path) -> None:
    patch = World(tmp_path).propose()
    assert "Rewrite lifted throughput" in patch
    assert "Paged cache cut memory use" in patch
    assert "Unchecked claim here" not in file_section(
        patch, "projects/attention-efficiency/claims.md"
    )


@pytest.mark.parametrize(
    "fact", ["the budget is fixed", "we agreed on Friday", "old deck says so"]
)
def test_client_and_run_citations_never_enter_the_project_tier(
    tmp_path: Path, fact: str
) -> None:
    patch = World(tmp_path).propose()
    claims_part = patch.split("diff --git")[1]
    assert "claims.md" in claims_part.splitlines()[0]
    assert fact not in claims_part
    assert "conversation--" not in claims_part and "transcript--" not in claims_part
    assert "client-deck--" not in claims_part


def test_proposed_claims_md_parses_with_the_loader_and_has_provenance(tmp_path: Path) -> None:
    w = World(tmp_path)
    patch = w.propose()
    claims_file = w.knowledge / "projects" / PROJECT / "claims.md"
    apply_patch(patch, w.knowledge)
    parsed = parse_claims_markdown(claims_file.read_text(encoding="utf-8"))
    assert len(parsed) == 4  # two seeded, two proposed
    assert {c.doc_id for c in parsed} == {"kaplan2024"}
    loaded = KnowledgeLoader(w.knowledge).load_project(PROJECT)
    assert len(loaded.claims) == 4
    assert "+<!-- proposed from run r1, slide s1, block b1, verdict supported -->" in patch


def test_no_duplicates_in_a_proposal_or_against_existing_claims(tmp_path: Path) -> None:
    w = World(tmp_path)
    claims_file = w.knowledge / "projects" / PROJECT / "claims.md"
    existing = claims_file.read_text(encoding="utf-8")
    twice = make_deck(
        slides=[
            slide(
                "s1",
                [
                    claim_block(
                        "b1", "headline", "Same one", "kaplan2024", "Fresh quote.", "supported"
                    ),
                    claim_block(
                        "b2",
                        "quote",
                        "Same one again",
                        "kaplan2024",
                        "Fresh  quote.",
                        "supported",
                    ),
                    claim_block(
                        "b3",
                        "x",
                        "Already known",
                        "kaplan2024",
                        "Training throughput rose from 412 to 671 sequences per second.",
                        "supported",
                    ),
                ],
            )
        ]
    )
    IRStore(w.runs, RUN).save(twice.model_copy(update={"version": 2}))
    patch = w.propose()
    assert patch.count("quote: Fresh") == 1
    assert "Already known" not in patch
    apply_patch(patch, w.knowledge)
    assert (
        len(parse_claims_markdown(claims_file.read_text(encoding="utf-8")))
        == len(parse_claims_markdown(existing)) + 1
    )


def test_a_claim_naming_a_client_is_not_proposed_into_the_shared_tier(tmp_path: Path) -> None:
    deck = make_deck(
        slides=[
            slide(
                "s1",
                [
                    claim_block(
                        "b1", "headline", "acme saw gains", "kaplan2024", "Gains.", "supported"
                    )
                ],
            )
        ]
    )
    patch = World(tmp_path, deck).propose()
    assert "projects/" not in patch
    assert "names a client" in patch


def test_engagement_note_is_deterministic_and_from_the_run(tmp_path: Path) -> None:
    w = World(tmp_path)
    run_root = w.runs / RUN
    (run_root / "meeting").mkdir()
    (run_root / "meeting" / "notes.json").write_text(
        json.dumps({"sections": {"Decisions": [{"id": "d1", "text": "Ship in June."}]}}),
        encoding="utf-8",
    )
    (run_root / "draft_brief.json").write_text(
        json.dumps(
            {
                "objective": "Decide on the rewrite.",
                "audience": "CTO",
                "key_messages": [{"id": "km1", "text": "It is faster."}],
            }
        ),
        encoding="utf-8",
    )
    first = w.propose()
    assert first == w.propose()
    assert "engagements/2026-05-01-r1.md" in first
    for line in (
        "+- Deck objective: Decide on the rewrite.",
        "+- It is faster.",
        "+- s1: Rewrite lifted throughput",
        "+- Ship in June.",
    ):
        assert line in first


def test_header_exemplars_follow_the_clients_rules(tmp_path: Path) -> None:
    w = World(tmp_path)
    (w.client_root / "style" / "headers.yaml").write_text(
        "style: assertion\nmax_words: 4\navoid: [leverage]\n", encoding="utf-8"
    )
    slides = [
        slide(
            "s1",
            [
                claim_block(
                    "b1",
                    "headline",
                    "Rewrite lifted throughput",
                    "kaplan2024",
                    "q1.",
                    "supported",
                )
            ],
        ),
        slide(
            "s2",
            [
                claim_block(
                    "b2",
                    "headline",
                    "This one is far too long to keep",
                    "kaplan2024",
                    "q2.",
                    "supported",
                )
            ],
        ),
        slide(
            "s3",
            [
                claim_block(
                    "b3", "headline", "We leverage speed", "kaplan2024", "q3.", "supported"
                )
            ],
        ),
        slide(
            "s4",
            [
                claim_block(
                    "b4", "headline", "Unsupported header", "kaplan2024", "q4.", "unsupported"
                )
            ],
        ),
        slide(
            "s5",
            [claim_block("b5", "headline", "Ends with dot.", "kaplan2024", "q5.", "supported")],
        ),
        slide(
            "s6",
            [
                claim_block(
                    "b6", "headline", "Overstated line", "kaplan2024", "q6.", "supported"
                )
            ],
            headline_check=HeadlineCheck(verdict="overstates", headline="Overstated line"),
        ),
    ]
    IRStore(w.runs, RUN).save(make_deck(slides=slides).model_copy(update={"version": 2}))
    patch = w.propose()
    section = file_section(patch, "clients/acme/style/headers.proposed.yaml")
    assert '+  - "Rewrite lifted throughput"' in section
    assert "run r1, slide s1, verdict supported" in section
    for rejected in (
        "far too long",
        "leverage",
        "Unsupported header",
        "Ends with dot",
        "Overstated",
    ):
        assert rejected not in section
    assert "headers.yaml\n" not in patch.replace("headers.proposed.yaml", "")
    # The profile still loads: nothing was added to headers.yaml itself.
    apply_patch(patch, w.knowledge)
    loaded = KnowledgeLoader(w.knowledge).load_client(CLIENT)
    assert loaded.header_profile == {
        "style": "assertion",
        "max_words": 4,
        "avoid": ["leverage"],
    }


def test_memory_terms_and_people_become_learned_without_figures(tmp_path: Path) -> None:
    w = World(tmp_path)
    memory = w.client_root / "memory"
    memory.mkdir()
    (memory / f"{PROJECT}.md").write_text(
        "# Memory\n\n## Terms\n"
        "- Sparkle — the product line (run r1)\n"
        "- Margin target is 42% (run r1)\n"
        "- Older term (run r0)\n\n"
        "## People\n"
        "- Dana Reyes — CFO (run r1)\n"
        "- Budget owner with $5 (run r1)\n\n"
        "## Decisions\n- Ship in June (run r1)\n",
        encoding="utf-8",
    )
    patch = w.propose()
    section = file_section(patch, "clients/acme/client.md")
    assert "+## Learned" in section
    assert "+- Sparkle — the product line <!-- run r1, memory Terms -->" in section
    assert "+- Dana Reyes — CFO <!-- run r1, memory People -->" in section
    for left_out in ("42%", "Older term", "$5", "Ship in June"):
        assert left_out not in section
    apply_patch(patch, w.knowledge)
    text = (w.client_root / "client.md").read_text(encoding="utf-8")
    assert text.count("## Learned") == 1
    # a second proposal after applying finds nothing new
    again = w.propose()
    assert "+- Sparkle" not in again and "+- Dana" not in again


def test_propose_leaves_knowledge_byte_identical(tmp_path: Path) -> None:
    w = World(tmp_path)
    before = tree_hash(w.knowledge)
    result = runner.invoke(
        app,
        [
            "knowledge",
            "propose",
            RUN,
            "--runs-root",
            str(w.runs),
            "--knowledge-root",
            str(w.knowledge),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "diff --git" in result.output
    out = tmp_path / "proposal.patch"
    result = runner.invoke(
        app,
        ["knowledge", "propose", RUN, "--out", str(out), "--runs-root", str(w.runs),
         "--knowledge-root", str(w.knowledge)],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert out.is_file()
    assert tree_hash(w.knowledge) == before


def test_propose_refuses_an_out_path_inside_knowledge(tmp_path: Path) -> None:
    w = World(tmp_path)
    before = tree_hash(w.knowledge)
    result = runner.invoke(
        app,
        ["knowledge", "propose", RUN, "--out", str(w.knowledge / "x.patch"),
         "--runs-root", str(w.runs), "--knowledge-root", str(w.knowledge)],
    )  # fmt: skip
    assert result.exit_code == 1
    assert tree_hash(w.knowledge) == before


def test_apply_refuses_without_the_flag_and_applies_with_it(tmp_path: Path) -> None:
    w = World(tmp_path)
    patch_file = tmp_path / "p.patch"
    patch_file.write_text(w.propose(), encoding="utf-8")
    before = tree_hash(w.knowledge)
    args = ["knowledge", "apply", str(patch_file), "--knowledge-root", str(w.knowledge)]
    refused = runner.invoke(app, args)
    assert refused.exit_code == 1
    assert "--yes-i-reviewed-this" in refused.output
    assert tree_hash(w.knowledge) == before
    done = runner.invoke(app, [*args, "--yes-i-reviewed-this"])
    assert done.exit_code == 0, done.output
    assert "projects/attention-efficiency/claims.md" in done.output
    assert (w.client_root / "engagements").is_dir()
    assert any(
        p.name.startswith("2026") or p.name.endswith("-r1.md")
        for p in (w.client_root / "engagements").iterdir()
    )
    assert tree_hash(w.knowledge) != before


def test_apply_fails_when_the_file_changed_since_the_proposal(tmp_path: Path) -> None:
    w = World(tmp_path)
    patch = w.propose()
    claims = w.knowledge / "projects" / PROJECT / "claims.md"
    claims.write_text("# Different now\n", encoding="utf-8")
    with pytest.raises(UpdateProposalError, match="propose again"):
        apply_patch(patch, w.knowledge)
    assert claims.read_text(encoding="utf-8") == "# Different now\n"


def retarget(patch: str, old: str, new: str) -> str:
    return patch.replace(old, new)


def test_apply_refuses_another_clients_folder(tmp_path: Path) -> None:
    w = World(tmp_path)
    patch = w.propose()
    forged = retarget(patch, "knowledge/clients/acme/", f"knowledge/clients/{OTHER}/")
    before = tree_hash(w.knowledge)
    with pytest.raises(UpdateProposalError, match="A4"):
        apply_patch(forged, w.knowledge)
    assert tree_hash(w.knowledge) == before


def test_apply_refuses_paths_outside_knowledge_and_unlisted_files(tmp_path: Path) -> None:
    w = World(tmp_path)
    patch = w.propose()
    before = tree_hash(w.knowledge)
    for target in (
        "etc/evil.md",
        "knowledge/../escape.md",
        "knowledge/clients/acme/theme/tokens.json",
    ):
        forged = retarget(
            patch,
            "knowledge/projects/attention-efficiency/claims.md",
            target,
        )
        with pytest.raises(UpdateProposalError):
            apply_patch(forged, w.knowledge)
    assert tree_hash(w.knowledge) == before
    assert not (tmp_path / "escape.md").exists()


def test_apply_refuses_a_patch_without_a_preamble(tmp_path: Path) -> None:
    w = World(tmp_path)
    body = w.propose()
    stripped = body[body.index("diff --git") :]
    with pytest.raises(UpdateProposalError, match="preamble"):
        apply_patch(stripped, w.knowledge)


def test_a_run_for_client_a_cannot_propose_into_client_b(tmp_path: Path) -> None:
    w = World(tmp_path)
    memory = w.knowledge / "clients" / OTHER / "memory"
    memory.mkdir()
    (memory / f"{PROJECT}.md").write_text(
        "# Memory\n\n## Terms\n- GlobexOnlyTerm (run r2)\n", encoding="utf-8"
    )
    (w.knowledge / "clients" / OTHER / "style" / "headers.yaml").write_text(
        "style: assertion\n", encoding="utf-8"
    )
    patch = w.propose()
    assert "GlobexOnlyTerm" not in patch
    assert "clients/globex" not in patch
    assert "# client: acme" in patch
    run_b = make_deck(client=OTHER, run_id="r2")
    IRStore(w.runs, "r2").save(run_b)
    patch_b = w.propose("r2")
    assert "GlobexOnlyTerm" in patch_b
    assert "clients/acme" not in patch_b


def test_a_missing_run_or_client_is_an_error(tmp_path: Path) -> None:
    w = World(tmp_path)
    with pytest.raises(UpdateProposalError):
        w.propose("nope")
    IRStore(w.runs, "r9").save(make_deck(client="nobody", run_id="r9"))
    with pytest.raises(UpdateProposalError, match="no folder"):
        w.propose("r9")
