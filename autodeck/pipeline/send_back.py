"""GATE 2 send-backs: named claims the owner rejected, kept for the next content pass.

The phase brief's exit criterion (`docs/phases/PHASE-2B.md`) is that the owner "approves,
or sends specific claims back", and nothing in the system before this module could express
the second half. A rejection has to *survive* — the writer's next pass has to see what was
rejected and why, or the gate is a rubber stamp with an extra step (task 2b.11's own framing
of the problem).

## Why this lives beside the IR rather than in it

The task is explicit: do not add a field to `autodeck/ir/` for this. A send-back is not
part of the deck — it is a fact about the *review*, and the IR's job is to describe the
deck as it stands, not its history of rejection. So a send-back is a small, inspectable
JSON file next to the IR under `runs/<run_id>/`, in the same spirit as `state.json` and
`build_manifest.json`: plain, diffable, and readable without this module.

## What is recorded, and why it is a snapshot rather than a live reference

A claim's stable id (`slide_id:block_id`, matching the audit report's own naming) can point
at a different sentence in the very next content pass — the writer is free to reuse a block
id, or the id may not even exist any more if the slide's blocks were rewritten from scratch.
So a `SendBackRecord` snapshots the rejected claim's own text and citations *as they stood
at the version being reviewed*, not just its id. That snapshot is what makes the record
mean something after the deck has moved on, and it is also what makes the mechanical check
in `autodeck content` possible: comparing the *next* draft's claim text against a
send-back's snapshotted text, not against a block id that may no longer exist.

## What this cannot do, and says so

A send-back is enforced by exact-text comparison (`normalise_for_match`, the same tolerant
matcher `verdicts.py` and the citation resolver use) between the previously rejected claim
and any claim `autodeck content` is about to write. That catches the literal case the task
names as the failure to avoid — the writer regenerating the same sentence verbatim — but it
is not, and cannot be, a check that the *substance* of a rejected claim never reappears
reworded. A model that rewrites a rejected assertion in different words produces a claim
this module cannot recognise as the same one. The send-back record is read into the
writer's own prompt context precisely because catching the reworded case needs the writer to
understand *why* the claim was rejected, not just that some other string was — the
mechanical check and the prompt context are two different, complementary defences, and
neither is complete on its own. `autodeck content`'s own output names any block it drops
this way, so a rewritten-but-still-rejected claim is at least visible for the next GATE 2
pass to catch, rather than silently shipping.

Owning phase: 2b (task 2b.11).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from autodeck.ir.models import Deck

SEND_BACKS_FILENAME = "send_backs.json"


class SendBackError(RuntimeError):
    """A send-back record could not be read or written."""


class EmptyReasonError(ValueError):
    """A send-back was given with a blank reason."""

    def __init__(self, claim_id: str) -> None:
        super().__init__(f"empty reason for claim {claim_id!r}")
        self.claim_id = claim_id


class UnknownClaimError(ValueError):
    """A send-back named claim ids the deck does not have."""

    def __init__(self, claim_ids: list[str]) -> None:
        super().__init__(f"unknown claim id(s): {', '.join(claim_ids)}")
        self.claim_ids = claim_ids


@dataclass(frozen=True)
class SendBackRecord:
    """One claim the owner rejected at GATE 2, with enough context to mean something later.

    `citations` is `(doc_id, page, quote)` tuples rather than `autodeck.ir.models.Citation`
    objects — a plain, JSON-native snapshot is enough to show the writer what was cited and
    needs no dependency on the IR's own (versioned, guardrailed) schema to read back.
    """

    claim_id: str
    """`slide_id:block_id`, exactly as `autodeck gate2` prints it and `--claim` takes it."""
    ir_version: int
    """Which IR version this claim was reviewed against, named in the record because the
    same `claim_id` can point at a different sentence once content is rewritten."""
    slide_id: str
    block_id: str
    claim_text: str
    verdict: str
    citations: tuple[tuple[str, int, str], ...]
    reason: str
    by: str
    at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "ir_version": self.ir_version,
            "slide_id": self.slide_id,
            "block_id": self.block_id,
            "claim_text": self.claim_text,
            "verdict": self.verdict,
            "citations": [list(item) for item in self.citations],
            "reason": self.reason,
            "by": self.by,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> SendBackRecord:
        try:
            citations = tuple(
                (str(doc_id), int(page), str(quote))
                for doc_id, page, quote in payload.get("citations") or []  # type: ignore[union-attr]
            )
            return cls(
                claim_id=str(payload["claim_id"]),
                ir_version=int(payload["ir_version"]),  # type: ignore[arg-type]
                slide_id=str(payload["slide_id"]),
                block_id=str(payload["block_id"]),
                claim_text=str(payload["claim_text"]),
                verdict=str(payload.get("verdict", "")),
                citations=citations,
                reason=str(payload["reason"]),
                by=str(payload["by"]),
                at=str(payload["at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SendBackError(f"malformed send-back record: {payload!r} ({exc})") from exc

    def prompt_line(self) -> str:
        """One line for `AssembledContext.send_backs` — what was rejected, and why.

        Natural-language, read by the model that writes the next pass. It is advisory, not
        an enforced constraint: see this module's docstring on what the mechanical
        text-match check in `autodeck content` does and does not catch.
        """
        where = ", ".join(f"{doc} p.{page}" for doc, page, _ in self.citations) or "no source"
        return (
            f'"{self.claim_text}" [{where}] — rejected by {self.by} at GATE 2 (was '
            f"{self.claim_id}, IR v{self.ir_version}). Reason: {self.reason}"
        )


def build_send_backs(
    deck: Deck, items: Sequence[tuple[str, str]], *, by: str, at: str
) -> list[SendBackRecord]:
    """Validate `(claim_id, reason)` pairs against `deck` and snapshot each claim.

    The one place a `SendBackRecord` is built, used by `autodeck send-back` and the review
    UI. Raises `EmptyReasonError` (checked first, per item, in order) for a blank reason and
    `UnknownClaimError` (naming every unknown id) for ids not in the deck. Writes nothing.
    """
    from autodeck.audit.report import build_audit_report

    report = build_audit_report(deck, brief=None)
    by_claim_id = {f"{row.slide_id}:{row.block_id}": row for row in report.claim_rows()}
    records: list[SendBackRecord] = []
    unknown: list[str] = []
    for claim_id, why in items:
        if not why.strip():
            raise EmptyReasonError(claim_id)
        row = by_claim_id.get(claim_id)
        if row is None:
            unknown.append(claim_id)
            continue
        records.append(
            SendBackRecord(
                claim_id=claim_id,
                ir_version=deck.version,
                slide_id=row.slide_id,
                block_id=row.block_id,
                claim_text=row.claim_text,
                verdict=row.verdict,
                citations=tuple((c.doc_id, c.page, c.quote) for c in row.citations),
                reason=why.strip(),
                by=by,
                at=at,
            )
        )
    if unknown:
        raise UnknownClaimError(unknown)
    return records


def send_backs_path(run_root: Path) -> Path:
    """Where a run's send-backs live, given its root (`Orchestrator.paths.root`)."""
    return Path(run_root) / SEND_BACKS_FILENAME


def load_send_backs(run_root: Path) -> list[SendBackRecord]:
    """Every send-back recorded for this run, oldest first. Empty if none has been."""
    path = send_backs_path(run_root)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SendBackError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise SendBackError(f"{path} must contain a JSON list, got {type(payload).__name__}")
    return [SendBackRecord.from_dict(item) for item in payload]


def append_send_backs(run_root: Path, records: list[SendBackRecord]) -> Path:
    """Add `records` to the run's send-back log, keeping every earlier one.

    Append-only on purpose: a send-back is a historical fact about a review, and a log a
    later run silently shortened would be indistinguishable from one where the rejection
    never happened.
    """
    path = send_backs_path(run_root)
    existing = load_send_backs(run_root)
    existing.extend(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([record.to_dict() for record in existing], indent=2) + "\n",
        encoding="utf-8",
    )
    return path


__all__ = [
    "SEND_BACKS_FILENAME",
    "EmptyReasonError",
    "SendBackError",
    "SendBackRecord",
    "UnknownClaimError",
    "append_send_backs",
    "build_send_backs",
    "load_send_backs",
    "send_backs_path",
]
