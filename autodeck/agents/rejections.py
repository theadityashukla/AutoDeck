"""Structured rejections: why a proposed block, slide or key message was refused.

Every drop the draft-first compose makes used to be recorded as a plain sentence only. A
repair call has to send each failure back to the model with enough structure to say what to
fix (which block, which slot, which figure), so each drop is also recorded as a `Rejection`.
The sentence stays (`message`, and the legacy string lists) so nothing that reads strings
changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

RejectionKind = Literal[
    "quote_not_found",
    "quote_splice",
    "doc_not_shown",
    "uncitable",
    "no_payload",
    "ir_invalid",
    "overflow_item",
    "overflow_stack",
    "overflow_text",
    "unknown_slot",
    "computed_slot",
    "missing_slot",
    "framing_fence",
    "numeral_unmatched",
    "header_fact_unbacked",
    "mode_blocked",
    "reworded_keep_words",
    "overflow_frame",
    "layout_fit",
    "subjectless_point",
]


@dataclass(frozen=True)
class Rejection:
    """One refusal, structured. `proposed` is the model's own block, for a repair prompt."""

    kind: RejectionKind
    where: Literal["face", "notes", "message"]
    slide_id: str
    block_id: str
    slot: str
    message: str
    item_index: int | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)
    proposed: Any = None

    def to_dict(self) -> dict[str, Any]:
        """A JSON-safe dict (the proposed block through pydantic's JSON mode)."""
        proposed: Any = self.proposed
        if proposed is not None and hasattr(proposed, "model_dump"):
            proposed = proposed.model_dump(mode="json")
        return {
            "kind": self.kind,
            "where": self.where,
            "slide_id": self.slide_id,
            "block_id": self.block_id,
            "slot": self.slot,
            "message": self.message,
            "item_index": self.item_index,
            "detail": _jsonable(dict(self.detail)),
            "proposed": _jsonable(proposed),
        }


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    return str(value)
