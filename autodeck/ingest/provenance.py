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
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Any

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


#: Snapping (B52): the share of the model's quote that must be found, in order, in one
#: passage; how much longer than the quote that passage may run; the shortest quote worth
#: snapping (a short quote is too ambiguous to place); and the shortest run of agreeing
#: characters that counts, so scattered common letters cannot add up to a match.
SNAP_MIN_COVERAGE = 0.85
SNAP_MAX_STRETCH = 1.5
SNAP_MIN_QUOTE_CHARS = 20
NORMAL_SNAP_MIN_COVERAGE = 0.6
"""B86: in a `normal` deck (and in meeting notes) the writer points at a passage rather than
copying it character for character: a quote that shares at least this much of its text with
one shown passage is resolved to that passage's exact words. The stored citation is always
the source's verbatim text (A1); only the burden of copying is lighter."""
_SNAP_MIN_RUN = 4


def snap_span(
    haystack: str, needle: str, *, min_coverage: float = SNAP_MIN_COVERAGE
) -> tuple[tuple[int, int], float] | None:
    """Locate the passage of `haystack` that `needle` is a slightly-off copy of (B52).

    For when `find_span` fails because a model copied a quote imperfectly: a period added
    where it cut a sentence short, reference markers like "[50, 51]" left out, a stray
    extraction space ("( p = 0.76)") tidied away. Whether the passage *supports* the
    sentence is not decided here — that is the validator's job (A3). This only decides
    whether the model was pointing at this passage, and returns the passage's **verbatim**
    offsets, so the citation built from it carries the document's words, never the model's.

    Returns `((start, end), coverage)`, or None when no single passage accounts for at
    least `min_coverage` (default `SNAP_MIN_COVERAGE`) of the quote within `SNAP_MAX_STRETCH`
    of its length. A `normal` deck passes `NORMAL_SNAP_MIN_COVERAGE` (B86).
    """
    target = normalise_for_match(needle)
    if len(target) < SNAP_MIN_QUOTE_CHARS:
        return None
    normalised, offsets = _normalise_with_offsets(haystack)
    if not normalised:
        return None

    matcher = SequenceMatcher(None, normalised, target, autojunk=False)
    runs = [b for b in matcher.get_matching_blocks() if b.size >= _SNAP_MIN_RUN]
    if not runs:
        return None
    coverage = sum(run.size for run in runs) / len(target)
    start_n, end_n = runs[0].a, runs[-1].a + runs[-1].size
    if coverage < min_coverage or end_n - start_n > SNAP_MAX_STRETCH * len(target):
        return None

    start, end = offsets[start_n], offsets[end_n - 1] + 1
    # Never cut a word in half: widen to the enclosing word boundaries.
    while start > 0 and haystack[start - 1].isalnum():
        start -= 1
    while end < len(haystack) and haystack[end].isalnum():
        end += 1
    return (start, end), coverage


def _covered_runs(passage: str, target: str) -> list[tuple[int, int]]:
    """Spans of `target` (normalised) that `passage` accounts for, as (start, end) in target."""
    normalised, _offsets = _normalise_with_offsets(passage)
    if not normalised or not target:
        return []
    matcher = SequenceMatcher(None, normalised, target, autojunk=False)
    return [
        (b.b, b.b + b.size) for b in matcher.get_matching_blocks() if b.size >= _SNAP_MIN_RUN
    ]


def diagnose_quote(quote: str, passages: Sequence[str]) -> dict[str, Any]:
    """Say whether a quote that matched nowhere is two passages joined together.

    A model sometimes stitches the end of one sentence onto the start of another ("A ... B")
    and the result is in no passage. No single passage snaps (`snap_span` is None for each),
    but two passages (or two disjoint regions of one) each cover a substantial contiguous
    part of the quote and together nearly all of it.

    Returns `{"splice": bool, "best_coverage": float, "parts": [...]}`. `best_coverage` is the
    best single-passage coverage of the quote; `parts` lists, for a splice, the two covering
    pieces as `{"passage": index, "start": .., "end": .., "coverage": ..}` (offsets into the
    normalised quote). A quote some passage already snaps is never a splice.
    """
    target = normalise_for_match(quote)
    result: dict[str, Any] = {"splice": False, "best_coverage": 0.0, "parts": []}
    if len(target) < SNAP_MIN_QUOTE_CHARS:
        return result

    per_passage: list[list[tuple[int, int]]] = []
    best = 0.0
    for text in passages:
        runs = _covered_runs(text, target)
        per_passage.append(runs)
        best = max(best, sum(e - s for s, e in runs) / len(target))
        if snap_span(text, quote) is not None:
            result["best_coverage"] = best
            return result
    result["best_coverage"] = best

    # Candidate regions: each passage's matching runs, grouped into one contiguous region of
    # the quote (runs closer than a gap tolerance belong together).
    regions: list[dict[str, Any]] = []
    for index, runs in enumerate(per_passage):
        group: list[tuple[int, int]] = []
        for run in runs:
            if group and run[0] - group[-1][1] > max(8, len(target) // 20):
                regions.append(_region(index, group, len(target)))
                group = []
            group.append(run)
        if group:
            regions.append(_region(index, group, len(target)))

    best_pair: tuple[float, dict[str, Any], dict[str, Any]] | None = None
    for i, first in enumerate(regions):
        for second in regions[i + 1 :]:
            left, right = sorted((first, second), key=lambda r: r["start"])
            if left["coverage"] < 0.3 or right["coverage"] < 0.3:
                continue
            if right["start"] < left["end"] - len(target) * 0.05:
                continue  # overlapping parts are one region seen twice, not a join
            if first["passage"] == second["passage"] and first["span"] == second["span"]:
                continue
            combined = left["coverage"] + right["coverage"]
            if combined >= SNAP_MIN_COVERAGE and (best_pair is None or combined > best_pair[0]):
                best_pair = (combined, left, right)
    if best_pair is not None:
        _combined, left, right = best_pair
        result["splice"] = True
        result["parts"] = [
            {k: left[k] for k in ("passage", "start", "end", "coverage")},
            {k: right[k] for k in ("passage", "start", "end", "coverage")},
        ]
    return result


def _region(passage: int, runs: list[tuple[int, int]], length: int) -> dict[str, Any]:
    start, end = runs[0][0], runs[-1][1]
    matched = sum(e - s for s, e in runs)
    return {
        "passage": passage,
        "start": start,
        "end": end,
        "coverage": matched / length,
        "span": (start, end),
    }


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
