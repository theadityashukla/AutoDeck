"""What the person typed in a run, as a source document (B55, `normal` mode only).

In `normal` provenance the person's own words are a legitimate source: "the architecture
slide says X because I told you X". They enter the same `Document` model a PDF or a client
deck uses, so the A1 resolver, the validator and the audit report need no new path, and a
citation into it is recognised by its `conversation--` doc id (`Citation.source_class ==
"conversation"`). It proves the deck is faithful to *what the person said*, not that it is
true; the audit labels it "from you".

**Only the person's own typing is citable.** Included: the clarify request prompt, answers
the person typed, corrections, the human turns of the planner chat, and revise
instructions. Excluded: the model's replies, assumptions and questions, and answers the
person merely accepted from the model's suggestions (`autodeck.pipeline.clarify_state`
records which is which).

Layout: page N is the Nth message (1-based); each non-empty paragraph is one citable `text`
element `m{N}-e{k}` whose box is the whole page (a message has no geometry). The message list
is ordered clarify (prompt, typed answers in typing order, corrections), then chat turns and
revise instructions merged by their recorded time (stable on ties). It is append-only in
practice — a new message becomes the last page — so earlier pages keep their text, element
ids and quote hashes. No timestamp enters the Document (A6): the same messages always yield
an identical Document.

A4: the document is built from, and written into, one run's own folder
(`runs/<run>/source/`); nothing here reads another run or the project corpus.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from autodeck.ingest.document_store import Document, DocumentElement, DocumentStore, IngestError
from autodeck.ir.models import CONVERSATION_DOC_PREFIX, BBox
from autodeck.pipeline.clarify_state import ClarifyStateError, load_clarify, typed_answers

#: A message has no geometry; every element's box is this 16:9 "page".
PAGE_BOX: BBox = (0.0, 0.0, 960.0, 540.0)

TITLE = "What you told us"


def conversation_doc_id(run_id: str) -> str:
    """`conversation--<slug>` for a run id."""
    slug = re.sub(r"[^a-z0-9]+", "-", run_id.casefold()).strip("-")
    if not slug:
        raise IngestError(f"cannot derive a conversation id from run id {run_id!r}")
    return f"{CONVERSATION_DOC_PREFIX}{slug}"


def _jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def person_messages(run_root: Path) -> list[str]:
    """Everything the person typed in this run, oldest first. Model wording is excluded."""
    run_root = Path(run_root)
    messages: list[str] = []

    try:
        clarify = load_clarify(run_root)
    except ClarifyStateError:
        clarify = None
    if clarify is not None:
        prompt = str(clarify.get("prompt") or "").strip()
        if prompt:
            messages.append(prompt)
        messages.extend(typed_answers(clarify))
        messages.extend(
            str(c).strip() for c in clarify.get("corrections", []) if str(c).strip()
        )

    later: list[tuple[str, str]] = []
    for item in _jsonl(run_root / "logs" / "planner.jsonl"):
        if item.get("role") == "human" and str(item.get("text") or "").strip():
            later.append((str(item.get("at") or ""), str(item["text"]).strip()))
    for item in _jsonl(run_root / "revisions.jsonl"):
        if str(item.get("instruction") or "").strip():
            later.append((str(item.get("at") or ""), str(item["instruction"]).strip()))
    later.sort(key=lambda pair: pair[0])  # stable: ties keep chat before revisions
    messages.extend(text for _, text in later)
    return messages


def conversation_document(run_root: Path, run_id: str) -> Document:
    """The conversation as a `Document` (no disk writes). Page N is the Nth message."""
    doc_id = conversation_doc_id(run_id)
    messages = person_messages(run_root)
    elements: list[DocumentElement] = []
    for page, message in enumerate(messages, start=1):
        number = 0
        for paragraph in message.splitlines():
            if not paragraph.strip():
                continue
            number += 1
            elements.append(
                DocumentElement(
                    element_id=f"m{page}-e{number}",
                    doc_id=doc_id,
                    kind="text",
                    page=page,
                    bbox=PAGE_BOX,
                    reading_order=len(elements),
                    text=paragraph.strip(),
                )
            )
    return Document(
        doc_id=doc_id,
        source_path="conversation",
        title=TITLE,
        page_count=len(messages),
        elements=elements,
    )


def ingest_conversation(run_root: Path, run_id: str) -> str | None:
    """Write (or refresh) the conversation into `runs/<run>/source/`; its doc id, or `None`
    when the person has typed nothing citable yet (any stale copy is left untouched)."""
    document = conversation_document(run_root, run_id)
    if not document.elements:
        return None
    DocumentStore(Path(run_root) / "source").add(document)
    return document.doc_id
