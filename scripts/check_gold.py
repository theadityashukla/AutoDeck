"""Check a gold exemplar deck against the same machinery a model's draft meets.

A gold deck is a hand-written `ComposeDraft` (the writer's own output schema) kept at
`knowledge/projects/<project>/gold/<name>.json`. It is the bar AutoDeck's drafts are measured
against, so it must clear every check a draft faces: each quote resolves verbatim (no B52
snapping), each block fits its slot in the real font, and the A2/A5/header draft checks pass.

The evidence it may cite is the whole project corpus, not a retrieved pack: a gold deck is
written by someone who read the paper.

Usage:
    .venv/bin/python scripts/check_gold.py <project> <gold.json> [--tokens config/tokens/dev.json]

Exit 0 when the deck is clean, 1 when anything failed, was dropped or had to be snapped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autodeck.agents import compose  # noqa: E402
from autodeck.agents.compose import ComposeDraft  # noqa: E402
from autodeck.agents.content import render_evidence  # noqa: E402
from autodeck.agents.evidence_pack import EvidencePack  # noqa: E402
from autodeck.audit.numeric_linter import lint_deck  # noqa: E402
from autodeck.design.components.catalog import COMPONENT_LIB_VERSION  # noqa: E402
from autodeck.design.theme.tokens import DesignTokens  # noqa: E402
from autodeck.ingest.document_store import DocumentStore  # noqa: E402
from autodeck.knowledge.loader import KnowledgeLoader  # noqa: E402
from autodeck.retrieval.hybrid import RetrievedSpan, build_index  # noqa: E402


def whole_corpus_pack(store: DocumentStore, project: str) -> EvidencePack:
    """Every citable element of every document, as one evidence pack."""
    index = build_index(list(store.documents()), project=project)
    spans = tuple(
        RetrievedSpan(
            doc_id=e.doc_id,
            element_id=e.element_id,
            page=e.page,
            text=e.retrieval_text(),
            score=0.0,
            citable=e.is_citable,
        )
        for e in index.elements.values()
        if e.is_citable
    )
    text = render_evidence((), spans)
    return EvidencePack(
        claims=(), spans=spans, text=text, queries=(), dropped=0, approx_tokens=len(text) // 4
    )


def body_words(slide) -> int:  # type: ignore[no-untyped-def]
    words = 0
    for block in slide.blocks:
        if block.slot in {"headline", "title"}:
            continue
        text = block.claim.text if block.claim is not None else (block.text or "")
        words += len(text.split())
    return words


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project")
    parser.add_argument("gold", type=Path)
    parser.add_argument("--tokens", type=Path, default=ROOT / "config/tokens/dev.json")
    args = parser.parse_args()

    knowledge = KnowledgeLoader(ROOT / "knowledge").load_project(args.project)
    store = DocumentStore(ROOT / "corpus" / args.project)
    pack = whole_corpus_pack(store, args.project)
    draft = ComposeDraft.model_validate_json(args.gold.read_text(encoding="utf-8"))
    provenance = knowledge.settings.provenance

    built = compose._build(
        draft,
        chat_brief=None,
        pack=pack,
        store=store,
        tokens=DesignTokens.load(args.tokens),
        allow_unsourced=provenance == "normal",
        keep_words=False,
        dividers_requested=False,
        deck_fields={
            "run_id": f"gold-{args.gold.stem}",
            "project": args.project,
            "client": "gold",
            "theme_ref": str(args.tokens),
            "component_lib_version": COMPONENT_LIB_VERSION,
            "provenance": provenance,
            "named_terms": list(knowledge.settings.named_terms),
        },
    )

    proposed = {s.id: s for s in draft.slides}
    problems = 0
    print(f"{args.gold.name}: {len(built.slides)} slides\n")
    for slide in built.slides:
        before = proposed[slide.id]
        lost = len(before.blocks) + len(before.speaker_notes) - len(slide.blocks) - len(
            slide.speaker_notes
        )
        headline = next((b.text for b in slide.blocks if b.slot in {"headline", "title"}), "")
        print(
            f"  {slide.id:4} {slide.component:20} body {body_words(slide):3} words"
            f"{'  LOST ' + str(lost) + ' block(s)' if lost else ''}  | {headline}"
        )
        problems += lost
    for label, items in (
        ("failures", [f.message for f in built.failures]),
        ("snapped quotes (a gold deck must quote exactly)", built.corrections),
        ("incomplete slots", built.incomplete),
        ("advisories", [a.message for a in built.advisories]),
    ):
        if items:
            print(f"\n{label}:")
            for item in items:
                print(f"  - {item}")
            if label != "advisories":
                problems += len(items)
    numeric = lint_deck(built.deck)
    if not numeric.passes:
        print("\nA2 findings:")
        for finding in numeric.blocking:
            print(f"  - {finding}")
        problems += len(numeric.blocking)
    keys = {m.id: m.evidence_status for m in built.brief.key_messages}
    print(f"\nkey messages: {json.dumps(keys)}")
    print("\nCLEAN" if not problems else f"\n{problems} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
