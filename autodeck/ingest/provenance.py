"""Provenance primitives — the link between a source PDF and a citation.

A1 requires every factual assertion to carry a citation resolving to
`(doc_id, page, bbox, verbatim_quote, quote_sha256)`. That chain has exactly two weak
points, and both are here:

1. **The quote must be verbatim.** Not paraphrased, not re-flowed, not normalised. The
   hash in `Citation` is computed over the exact characters, so anything that "helpfully"
   tidies text before hashing breaks verification for every citation downstream.
2. **Matching a quote to a span is a search over messy text.** PDFs break words across
   lines, use ligatures, and vary their quotation marks. A search that is too strict finds
   nothing and blocks real citations; one that is too loose matches the wrong span and
   produces a citation that looks perfect and points at the wrong place.

The resolution is a **normalised index with verbatim payload**: matching happens on a
normalised form, but the citation always carries the original characters from the store.
Normalisation is a lookup key, never a substitute for the source text.

Owning phase: 1 (task 1.2).
"""

from __future__ import annotations

import re
import unicodedata

from autodeck.ir.models import BBox

#: Characters PDF extraction commonly substitutes, mapped back to their ASCII form for
#: *matching only*. The stored text keeps whatever the document actually contained.
_LOOKALIKES = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "–": "-",
    "—": "-",
    "−": "-",
    "­": "",  # soft hyphen
    " ": " ",
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}

_WHITESPACE = re.compile(r"\s+")

#: A hyphen at a line break, e.g. "through-\nput" -> "throughput". Only joined when the
#: break is followed by a lowercase letter; "state-\nof-the-art" must keep its hyphen.
_LINE_BREAK_HYPHEN = re.compile(r"(\w)-\s*\n\s*([a-z])")


def normalise_text(text: str) -> str:
    """Return the matching form of `text`.

    Unicode NFKC, lookalike substitution, line-break hyphen joining, and whitespace
    collapse. **Never** store the result as if it were source text: it is a lookup key, and
    a citation built from it would fail its own hash check.
    """
    text = _LINE_BREAK_HYPHEN.sub(r"\1\2", text)
    text = unicodedata.normalize("NFKC", text)
    for source, replacement in _LOOKALIKES.items():
        text = text.replace(source, replacement)
    return _WHITESPACE.sub(" ", text).strip()


def normalise_for_match(text: str) -> str:
    """Normalised and case-folded — for locating a quote within a span."""
    return normalise_text(text).casefold()


def find_span(haystack: str, needle: str) -> tuple[int, int] | None:
    """Locate `needle` inside `haystack`, returning **verbatim** character offsets.

    Searching happens on the normalised forms, but the offsets returned index the original
    string, so the caller can slice out the exact characters the document contains. That is
    what keeps `quote_sha256` verifiable — a citation carrying normalised text would hash
    to something the source never said.

    Returns None when the quote is not present.
    """
    if not needle.strip():
        return None

    # Fast path: the quote appears exactly as written.
    exact = haystack.find(needle)
    if exact != -1:
        return exact, exact + len(needle)

    # Slow path: build a map from normalised positions back to verbatim ones.
    normalised, offsets = _normalise_with_offsets(haystack)
    target = normalise_for_match(needle)
    if not target:
        return None

    position = normalised.find(target)
    if position == -1:
        return None

    start = offsets[position]
    end_index = position + len(target) - 1
    end = offsets[end_index] + 1 if end_index < len(offsets) else len(haystack)
    return start, end


#: A hyphen ending a line, seen from that hyphen's position: whitespace including a
#: newline, then a lowercase letter. Mirrors `_LINE_BREAK_HYPHEN` for the offset-preserving
#: walker, which cannot use a bulk substitution.
_HYPHEN_AT_LINE_END = re.compile(r"-\s*\n\s*(?=[a-z])")


def _normalise_with_offsets(text: str) -> tuple[str, list[int]]:
    """Normalise `text` while recording, for each output character, its source index.

    Done character by character rather than with the regex pipeline above, because a
    citation needs to point back into the original string and a bulk `re.sub` throws that
    correspondence away. The two paths must agree: anything `normalise_text` collapses,
    this must collapse identically, or a quote will match one and not the other.
    """
    output: list[str] = []
    offsets: list[int] = []
    previous_was_space = False
    index = 0

    while index < len(text):
        # Word broken across a line: drop the hyphen and the break entirely, so
        # "through-\nput" matches "throughput".
        if text[index] == "-" and output and output[-1].isalnum():
            joined = _HYPHEN_AT_LINE_END.match(text, index)
            if joined:
                index = joined.end()
                previous_was_space = False
                continue

        char = text[index]
        replacement = _LOOKALIKES.get(char)
        if replacement is None:
            replacement = unicodedata.normalize("NFKC", char)

        if replacement == "":
            index += 1
            continue

        if replacement.isspace():
            if not previous_was_space and output:
                output.append(" ")
                offsets.append(index)
                previous_was_space = True
            index += 1
            continue

        previous_was_space = False
        for expanded in replacement:
            output.append(expanded.casefold())
            offsets.append(index)
        index += 1

    while output and output[-1] == " ":
        output.pop()
        offsets.pop()

    return "".join(output), offsets


def merge_bboxes(boxes: list[BBox]) -> BBox:
    """The bounding box enclosing all of `boxes`.

    Used when a quote spans several elements — the citation points at the whole region
    rather than at whichever fragment happened to match first.
    """
    if not boxes:
        raise ValueError("cannot merge an empty list of bounding boxes")
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def bbox_is_sane(bbox: BBox) -> bool:
    """Whether a bounding box has positive area and non-negative coordinates.

    Plan §9 names Docling provenance gaps on messy PDFs as a live risk, and the failure is
    a degenerate or missing box rather than an exception. A citation with a zero-area box
    cannot be spot-checked against the source, which is exactly what GATE 1a does — so it
    is treated as absent provenance rather than as a cosmetic flaw.
    """
    left, top, right, bottom = bbox
    return right > left and bottom > top and left >= 0 and top >= 0
