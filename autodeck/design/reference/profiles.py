"""The four profiles derived from a reference deck (Phase 4, task 4.2).

Everything here is deterministic code over a `ReferenceDeck` — no model call, no clock, no
randomness — so re-ingesting the same deck yields byte-identical JSON. Each heuristic is
deliberately simple and documented where it lives; a slide's inferred role records the rule
that set it so a wrong guess is explainable.

**A1:** profiles carry deck-derived text only under fields named for what it is
(`titles`, `exemplar_headers`, `terms`). Nothing here builds a `Document`, a
`RetrievedSpan` or a `CachedClaim`, and no profile key is one a `DocumentStore` would accept.

* `StorylineProfile` — slide roles (`title`, `agenda`, `divider`, `content`, `appendix`,
  `closing`), sections, density, the arc as ordered titles.
* `HeaderDerivation` — a mapping `HeaderStyleProfile.from_mapping` loads, plus the shares and
  exemplars that cannot live in that (extra-forbidding) shape. It never overwrites
  `style/headers.yaml`; proposing a change to it is task 4.7's job.
* `VoiceProfile` — sentence length, person, bullet share, top terms, acronyms. `avoided`
  stays empty: one deck cannot tell what a client avoids.
* `DesignProfile` — per slide, the nearest catalog component and a 0-1 confidence, margins,
  fonts and colours by frequency.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from autodeck.design.headers.profile import HeaderStyleProfile
from autodeck.ingest.deck_ingest import ReferenceDeck, RefShape, RefSlide

SlideRole = Literal["title", "agenda", "divider", "content", "appendix", "closing"]

EXEMPLAR_CAP = 8
TERM_CAP = 25
LOW_CONFIDENCE = 0.5

# ---------------------------------------------------------------------------
# Storyline
# ---------------------------------------------------------------------------

_AGENDA = re.compile(r"\b(agenda|contents|outline|today'?s? (discussion|topics))\b", re.I)
_APPENDIX = re.compile(r"\b(appendix|appendices|backup|back-up|supplementary)\b", re.I)
_CLOSING = re.compile(
    r"\b(thank you|thanks|next steps?|questions\??|contact|q\s*&\s*a|get in touch)\b", re.I
)
_DIVIDER_LAYOUT = re.compile(r"section|divider|break|chapter", re.I)
_TITLE_LAYOUT = re.compile(r"\btitle slide\b|^title$|cover|title only$", re.I)
_CLOSING_LAYOUT = re.compile(r"closing|end|thank", re.I)


class SlideRoleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide: int
    role: SlideRole
    rule: str
    words: int
    shapes: int


class StorylineProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_count: int
    roles: list[SlideRoleRecord]
    role_counts: dict[str, int]
    sections: list[dict[str, int]]
    """Section boundaries: each divider (or the first slide) starts one; `{start, slides}`."""
    titles: list[str]
    """The arc: every slide's title in order. Style input only (A1)."""
    mean_words_per_slide: float
    mean_shapes_per_slide: float


def _body_words(slide: RefSlide) -> int:
    return sum(s.words for s in slide.shapes if s.kind == "text")


def _total_words(slide: RefSlide) -> int:
    return len(slide.title.split()) + _body_words(slide)


def infer_roles(deck: ReferenceDeck) -> list[SlideRoleRecord]:
    """Role per slide by the first matching rule, in this order:

    1. `first-slide`: slide 1 with at most 30 body words, or a title-like layout name.
    2. `appendix-title` / `after-appendix`: title or layout says appendix/backup; every slide
       after the first appendix slide stays appendix.
    3. `agenda-title`: title says agenda/contents/outline.
    4. `closing-title`: title says thank you / next steps / questions / contact (on the last
       three slides only, so "Next steps" mid-deck stays content), or `last-slide-layout`: the
       last slide on a closing-like layout with at most 25 body words.
    5. `divider-layout`: layout name says section/divider/break; or `sparse-slide`: no body
       text, no picture/chart/table, a title of at most 8 words, not first or last.
    6. otherwise `content`.
    """
    total = len(deck.slides)
    records: list[SlideRoleRecord] = []
    in_appendix = False
    for slide in deck.slides:
        body = _body_words(slide)
        visual = slide.count("picture") + slide.count("chart") + slide.count("table")
        role: SlideRole
        if slide.index == 1 and (body <= 30 or _TITLE_LAYOUT.search(slide.layout_name)):
            role, rule = "title", "first-slide"
        elif in_appendix:
            role, rule = "appendix", "after-appendix"
        elif _APPENDIX.search(slide.title) or _APPENDIX.search(slide.layout_name):
            role, rule = "appendix", "appendix-title"
            in_appendix = True
        elif _AGENDA.search(slide.title) or _AGENDA.search(slide.layout_name):
            role, rule = "agenda", "agenda-title"
        elif slide.index > total - 3 and _CLOSING.search(slide.title):
            role, rule = "closing", "closing-title"
        elif (
            slide.index == total
            and total > 1
            and _CLOSING_LAYOUT.search(slide.layout_name)
            and body <= 25
        ):
            role, rule = "closing", "last-slide-layout"
        elif _DIVIDER_LAYOUT.search(slide.layout_name) and visual == 0:
            role, rule = "divider", "divider-layout"
        elif (
            body == 0
            and visual == 0
            and slide.title
            and len(slide.title.split()) <= 8
            and 1 < slide.index < total
        ):
            role, rule = "divider", "sparse-slide"
        else:
            role, rule = "content", "default"
        if role == "appendix" and rule == "appendix-title":
            pass
        records.append(
            SlideRoleRecord(
                slide=slide.index,
                role=role,
                rule=rule,
                words=_total_words(slide),
                shapes=len(slide.shapes),
            )
        )
    return records


def derive_storyline(deck: ReferenceDeck) -> StorylineProfile:
    records = infer_roles(deck)
    starts = [r.slide for r in records if r.role == "divider"]
    if records and (not starts or starts[0] != 1):
        starts.insert(0, 1)
    sections = [
        {
            "start": start,
            "slides": (starts[i + 1] if i + 1 < len(starts) else len(records) + 1) - start,
        }
        for i, start in enumerate(starts)
    ]
    count = len(records)
    return StorylineProfile(
        slide_count=count,
        roles=records,
        role_counts=dict(sorted(Counter(r.role for r in records).items())),
        sections=sections,
        titles=[s.title for s in deck.slides],
        mean_words_per_slide=round(sum(r.words for r in records) / count, 1) if count else 0.0,
        mean_shapes_per_slide=round(sum(r.shapes for r in records) / count, 1)
        if count
        else 0.0,
    )


def _content_slides(deck: ReferenceDeck, storyline: StorylineProfile) -> list[RefSlide]:
    roles = {r.slide: r.role for r in storyline.roles}
    return [s for s in deck.slides if roles.get(s.index) == "content"]


# ---------------------------------------------------------------------------
# Header style
# ---------------------------------------------------------------------------

#: Finite-verb cues: a title with one of these (and at least 5 words) reads as an assertion.
VERB_CUES = frozenset(
    [
        "is",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "will",
        "can",
        "could",
        "should",
        "must",
        "drives",
        "drive",
        "reduces",
        "reduce",
        "increases",
        "increase",
        "cuts",
        "cut",
        "grows",
        "grow",
        "raises",
        "raise",
        "lowers",
        "lower",
        "improves",
        "improve",
        "enables",
        "enable",
        "requires",
        "require",
        "remains",
        "remain",
        "needs",
        "need",
        "shows",
        "show",
        "means",
        "mean",
        "delivers",
        "deliver",
        "saves",
        "save",
        "falls",
        "fall",
        "rises",
        "rise",
        "doubles",
        "halves",
        "exceeds",
        "exceed",
        "outperforms",
        "accounts",
        "depends",
        "makes",
        "make",
        "gives",
        "give",
        "wins",
        "creates",
        "create",
        "becomes",
        "become",
        "matters",
        "limits",
        "limit",
        "drops",
        "drop",
        "hits",
        "hit",
        "pays",
        "pay",
        "costs",
        "cost",
        "lifts",
        "lift",
        "beats",
        "beat",
        "leads",
        "lead",
    ]
)

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'%$.,/-]*")


def _words(text: str) -> list[str]:
    return text.split()


def _is_sentence_case(title: str) -> bool:
    """First letter capital or non-letter, and no later word that is Capitalised (an
    all-caps acronym, or a word with a digit, is not counted)."""
    words = _words(title)
    for word in words[1:]:
        letters = re.sub(r"[^A-Za-z]", "", word)
        if len(letters) < 2 or any(c.isdigit() for c in word) or letters.isupper():
            continue
        if word[0].isalpha() and word[0].isupper():
            return False
    return True


def _percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def _share(flags: list[bool]) -> float:
    return round(sum(flags) / len(flags), 3) if flags else 0.0


class HeaderDerivation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: dict[str, Any]
    """A mapping `HeaderStyleProfile.from_mapping` loads (same shape as `headers.yaml`)."""
    titles_considered: int
    question_share: float
    sentence_case_share: float
    number_share: float
    assertion_share: float
    exemplar_headers: list[str]
    """Up to 8 content titles in deck order. Style input only (A1)."""


def derive_headers(deck: ReferenceDeck, storyline: StorylineProfile) -> HeaderDerivation:
    """Rules, over the content slides' titles (all titled slides when there are none):

    * `max_words`: 90th percentile (nearest rank) of title word counts.
    * `sentence_case`: true when at least 60% of titles are sentence case.
    * `terminal_punctuation`: true when at least half end in `.` or `!` (a `?` is a question,
      counted separately).
    * `numbers_in_headers`: `allowed` when at least 20% carry a digit, else `discouraged`
      (the `avoid` the plan names does not exist in `NumbersPolicy`).
    * `style`: `assertion` when most titles have at least 5 words and a `VERB_CUES` word,
      else `topic_led` (the name `STYLE_GUIDANCE` already knows for a topic style).
    """
    slides = _content_slides(deck, storyline)
    titles = [s.title for s in slides if s.title]
    if not titles:
        titles = [s.title for s in deck.slides if s.title]
    mapping: dict[str, Any] = {"style": "topic_led"}
    if not titles:
        HeaderStyleProfile.from_mapping(mapping)
        return HeaderDerivation(
            profile=mapping,
            titles_considered=0,
            question_share=0.0,
            sentence_case_share=0.0,
            number_share=0.0,
            assertion_share=0.0,
            exemplar_headers=[],
        )
    counts = [len(_words(t)) for t in titles]
    sentence = [_is_sentence_case(t) for t in titles]
    terminal = [t.rstrip()[-1:] in (".", "!") for t in titles]
    numbers = [any(c.isdigit() for c in t) for t in titles]
    questions = [t.rstrip().endswith("?") for t in titles]
    assertion = [
        len(_words(t)) >= 5 and any(w.lower().strip(".,;:!?") in VERB_CUES for w in _words(t))
        for t in titles
    ]
    mapping = {
        "style": "assertion" if _share(assertion) > 0.5 else "topic_led",
        "max_words": max(1, _percentile(counts, 0.9)),
        "sentence_case": _share(sentence) >= 0.6,
        "terminal_punctuation": _share(terminal) >= 0.5,
        "numbers_in_headers": "allowed" if _share(numbers) >= 0.2 else "discouraged",
    }
    HeaderStyleProfile.from_mapping(
        mapping
    )  # fail here, not in a consumer, if the shape drifts
    return HeaderDerivation(
        profile=mapping,
        titles_considered=len(titles),
        question_share=_share(questions),
        sentence_case_share=_share(sentence),
        number_share=_share(numbers),
        assertion_share=_share(assertion),
        exemplar_headers=titles[:EXEMPLAR_CAP],
    )


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------

STOPWORDS = frozenset(
    [
        "about",
        "above",
        "after",
        "again",
        "against",
        "also",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "could",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "from",
        "further",
        "have",
        "having",
        "here",
        "into",
        "itself",
        "just",
        "more",
        "most",
        "only",
        "other",
        "over",
        "same",
        "should",
        "some",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "under",
        "until",
        "very",
        "what",
        "when",
        "where",
        "which",
        "while",
        "will",
        "with",
        "would",
        "your",
        "yours",
        "were",
        "was",
        "our",
        "ours",
        "its",
        "and",
        "the",
        "for",
        "are",
        "not",
        "but",
        "you",
        "can",
        "has",
        "had",
        "how",
        "why",
        "who",
    ]
)
_FIRST = frozenset({"we", "our", "ours", "us", "we're", "we'll", "we've"})
_SECOND = frozenset({"you", "your", "yours", "you're", "you'll", "you've"})
_THIRD = frozenset({"they", "their", "theirs", "them", "they're", "they'll", "they've"})
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_TERM = re.compile(r"[A-Za-z][A-Za-z'-]{3,}")
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,5}\b")


class VoiceProfile(BaseModel):
    """`avoided` stays empty by design: a single deck cannot say what a client avoids, only
    what it used. Curating that list is a person's job (`headers.yaml` `avoid`)."""

    model_config = ConfigDict(extra="forbid")

    sentences: int
    mean_sentence_words: float
    median_sentence_words: float
    person: dict[str, float]
    bullet_share: float
    terms: list[tuple[str, int]]
    acronyms: list[str]
    avoided: list[str] = Field(default_factory=list)


def derive_voice(deck: ReferenceDeck) -> VoiceProfile:
    paragraphs = [p for s in deck.slides for p in s.body_paragraphs]
    sentence_lengths: list[int] = []
    for paragraph in paragraphs:
        for sentence in _SENTENCE_SPLIT.split(paragraph.text):
            n = len(sentence.split())
            if n:
                sentence_lengths.append(n)
    tokens = [
        w.lower() for p in paragraphs for w in re.findall(r"[A-Za-z][A-Za-z'\u2019]*", p.text)
    ]
    first = sum(t in _FIRST for t in tokens)
    second = sum(t in _SECOND for t in tokens)
    third = sum(t in _THIRD for t in tokens)
    pronouns = first + second + third
    person = {
        "we": round(first / pronouns, 3) if pronouns else 0.0,
        "you": round(second / pronouns, 3) if pronouns else 0.0,
        "they": round(third / pronouns, 3) if pronouns else 0.0,
    }
    term_counts = Counter(
        w.lower()
        for p in paragraphs
        for w in _TERM.findall(p.text)
        if w.lower() not in STOPWORDS
    )
    terms = sorted(
        ((t, n) for t, n in term_counts.items() if n >= 2), key=lambda item: (-item[1], item[0])
    )[:TERM_CAP]
    acronyms = sorted(
        {
            a
            for s in deck.slides
            for text in [s.title, *(p.text for p in s.body_paragraphs)]
            for a in _ACRONYM.findall(text)
        }
    )
    return VoiceProfile(
        sentences=len(sentence_lengths),
        mean_sentence_words=round(statistics.fmean(sentence_lengths), 1)
        if sentence_lengths
        else 0.0,
        median_sentence_words=float(statistics.median(sentence_lengths))
        if sentence_lengths
        else 0.0,
        person=person,
        bullet_share=_share([p.bullet for p in paragraphs]),
        terms=terms,
        acronyms=acronyms,
    )


# ---------------------------------------------------------------------------
# Design
# ---------------------------------------------------------------------------

_BIG_NUMBER = re.compile(r"^[\s$€£~≈+-]*\d[\d.,]*\s*[%xX\u00d7kKmMbBpt]*\+?$")
_QUOTE_MARKS = ('"', "\u201c", "\u2018", "'")


class SlideDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide: int
    layout_name: str
    component: str
    confidence: float
    rule: str
    signature: str
    text_boxes: int
    columns: int
    pictures: int
    charts: int
    tables: int
    margin_min: float | None


class DesignProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slides: list[SlideDesign]
    component_counts: dict[str, int]
    low_confidence_slides: list[int]
    margin_pt: float | None
    fonts: list[tuple[str, int]]
    colours: list[tuple[str, int]]


def _body_boxes(slide: RefSlide) -> list[RefShape]:
    return [s for s in slide.shapes if s.kind == "text" and not s.covers_slide]


def _columns(boxes: list[RefShape], slide_width: float) -> int:
    """Distinct left edges (within 5% of the slide width) among body text boxes that are
    narrower than 70% of the slide: a full-width box is one column, however it is placed."""
    lefts = sorted(b.box[0] for b in boxes if (b.box[2] - b.box[0]) < 0.7 * slide_width)
    clusters = 0
    last: float | None = None
    for left in lefts:
        if last is None or left - last > 0.05 * slide_width:
            clusters += 1
            last = left
    return clusters


def _rows(boxes: list[RefShape], slide_height: float) -> int:
    tops = sorted(b.box[1] for b in boxes)
    rows, last = 0, None
    for top in tops:
        if last is None or top - last > 0.08 * slide_height:
            rows += 1
            last = top
    return rows


def _has_big_number(boxes: list[RefShape]) -> bool:
    sizes = [b.max_font_pt for b in boxes if b.max_font_pt]
    typical = statistics.median(sizes) if sizes else 0
    for box in boxes:
        for paragraph in box.paragraphs:
            if _BIG_NUMBER.match(paragraph.text) and (
                (box.max_font_pt or 0) >= 40 or (box.max_font_pt or 0) >= 2 * typical > 0
            ):
                return True
    return False


def _has_quote(slide: RefSlide, boxes: list[RefShape]) -> bool:
    if "quote" in slide.layout_name.lower():
        return True
    return any(
        p.text.startswith(_QUOTE_MARKS)
        and p.text.rstrip().endswith(('"', "\u201d", "\u2019", "'"))
        and len(p.text.split()) >= 6
        for b in boxes
        for p in b.paragraphs
    )


def _signature(text_boxes: int, columns: int, pictures: int, charts: int, tables: int) -> str:
    cap = lambda n: f"{n}" if n < 6 else "6+"  # noqa: E731
    return (
        f"text{cap(text_boxes)}-cols{min(columns, 4) if columns < 5 else '5+'}"
        f"-pic{min(pictures, 3) if pictures < 4 else '3+'}"
        f"-chart{min(charts, 2)}-table{min(tables, 2)}"
    )


def nearest_component(
    slide: RefSlide, role: SlideRole, deck: ReferenceDeck
) -> tuple[str, float, str]:
    """The catalog component whose simple geometry/content rule fits best, with a 0-1
    confidence and the rule name. Confidence is the rule's fixed strength (what a match of
    that kind is worth), not a probability; anything below 0.5 is a gap candidate (4.8).

    Role rules: title 0.9, divider 0.9 (`section_divider`), agenda 0.85, closing 0.8
    (`closing_cta`). Content rules, strongest wins: quote 0.85; big number 0.8 (at most 3
    body boxes, no chart); chart-only `chart_focus` 0.85 / chart with text 0.6; picture
    with 1-3 text boxes `evidence_with_figure` 0.8; two columns `two_column_compare` 0.8
    (before/after titles `before_after` 0.75); 3-4 columns `icon_pillars` 0.75 with
    pictures else 0.6; a 2x2+ grid `data_card_grid` 0.65; a single row of 4+ boxes
    `timeline` 0.65; at most 2 body boxes `bullets_supporting` 0.8; one short unbulleted
    box `callout_takeaway` 0.6. A table fits nothing (best guess `data_card_grid`, 0.3), and
    anything else falls back to `bullets_supporting` at 0.3.
    """
    if role == "title":
        return "title", 0.9, "role-title"
    if role == "divider":
        return "section_divider", 0.9, "role-divider"
    if role == "agenda":
        return "agenda", 0.85, "role-agenda"
    if role == "closing":
        return "closing_cta", 0.8, "role-closing"

    boxes = _body_boxes(slide)
    n = len(boxes)
    pictures = sum(1 for s in slide.shapes if s.kind == "picture" and not s.covers_slide)
    charts, tables = slide.count("chart"), slide.count("table")
    cols = _columns(boxes, deck.slide_width)
    rows = _rows(boxes, deck.slide_height)
    candidates: list[tuple[float, str, str]] = []

    def add(confidence: float, component: str, rule: str) -> None:
        candidates.append((confidence, component, rule))

    if tables:
        add(0.3, "data_card_grid", "table-no-component")
    if _has_quote(slide, boxes) and not charts and not tables:
        add(0.85, "quote", "quote-text")
    if _has_big_number(boxes) and n <= 3 and not charts:
        add(0.8, "big_number", "big-number")
    if charts and not tables:
        if n <= 2 and not pictures:
            add(0.85, "chart_focus", "chart-only")
        else:
            add(0.6, "chart_focus", "chart-with-text")
    if pictures and 1 <= n <= 3 and not charts and not tables:
        add(0.8, "evidence_with_figure", "picture-with-text")
    if not pictures and not charts and not tables:
        low = slide.title.lower()
        if cols == 2 and 2 <= n <= 6:
            if "before" in low and "after" in low:
                add(0.75, "before_after", "before-after-title")
            add(0.8, "two_column_compare", "two-columns")
        if 3 <= cols <= 4 and n >= 3:
            add(0.6, "icon_pillars", "three-or-four-columns")
        if cols >= 2 and rows >= 2 and n >= 4:
            add(0.65, "data_card_grid", "card-grid")
        if rows == 1 and cols >= 4 and n >= 4:
            add(0.65, "timeline", "single-row")
        if n <= 2 and cols <= 1:
            add(0.8, "bullets_supporting", "body-text")
        if n == 1 and boxes and not boxes[0].paragraphs[0].bullet and boxes[0].words <= 25:
            add(0.6, "callout_takeaway", "single-callout")
    if pictures >= 3 and 3 <= cols <= 4 and not charts and not tables:
        add(0.75, "icon_pillars", "columns-with-pictures")
    add(0.3, "bullets_supporting", "fallback")
    confidence, component, rule = max(candidates, key=lambda c: (c[0], c[1]))
    return component, confidence, rule


def _margin_min(slide: RefSlide, deck: ReferenceDeck) -> float | None:
    insets = [
        min(s.box[0], s.box[1], deck.slide_width - s.box[2], deck.slide_height - s.box[3])
        for s in slide.shapes
        if not s.covers_slide
    ]
    return round(min(insets), 1) if insets else None


def derive_design(deck: ReferenceDeck, storyline: StorylineProfile) -> DesignProfile:
    roles = {r.slide: r.role for r in storyline.roles}
    designs: list[SlideDesign] = []
    fonts: Counter[str] = Counter()
    colours: Counter[str] = Counter()
    for slide in deck.slides:
        boxes = _body_boxes(slide)
        pictures = sum(1 for s in slide.shapes if s.kind == "picture" and not s.covers_slide)
        charts, tables = slide.count("chart"), slide.count("table")
        columns = _columns(boxes, deck.slide_width)
        component, confidence, rule = nearest_component(slide, roles[slide.index], deck)
        designs.append(
            SlideDesign(
                slide=slide.index,
                layout_name=slide.layout_name,
                component=component,
                confidence=confidence,
                rule=rule,
                signature=_signature(len(boxes), columns, pictures, charts, tables),
                text_boxes=len(boxes),
                columns=columns,
                pictures=pictures,
                charts=charts,
                tables=tables,
                margin_min=_margin_min(slide, deck),
            )
        )
        for shape in slide.shapes:
            fonts.update(shape.font_names)
            if shape.fill:
                colours[shape.fill] += 1
    margins = [d.margin_min for d in designs if d.margin_min is not None]
    return DesignProfile(
        slides=designs,
        component_counts=dict(sorted(Counter(d.component for d in designs).items())),
        low_confidence_slides=[d.slide for d in designs if d.confidence < LOW_CONFIDENCE],
        margin_pt=round(statistics.median(margins), 1) if margins else None,
        fonts=_ranked(fonts),
        colours=_ranked(colours),
    )


def _ranked(counter: Counter[str]) -> list[tuple[str, int]]:
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))


# ---------------------------------------------------------------------------
# One deck, and a client's decks
# ---------------------------------------------------------------------------


class DeckProfile(BaseModel):
    """All four profiles for one deck: the content of `decks/<slug>.profile.json`."""

    model_config = ConfigDict(extra="forbid")

    deck: str
    slug: str
    storyline: StorylineProfile
    header: HeaderDerivation
    voice: VoiceProfile
    design: DesignProfile


def derive_profiles(deck: ReferenceDeck, *, slug: str) -> DeckProfile:
    storyline = derive_storyline(deck)
    return DeckProfile(
        deck=deck.name,
        slug=slug,
        storyline=storyline,
        header=derive_headers(deck, storyline),
        voice=derive_voice(deck),
        design=derive_design(deck, storyline),
    )


def _majority(flags: list[bool]) -> bool:
    return sum(flags) * 2 > len(flags)


def _sum_ranked(lists: list[list[tuple[str, int]]], cap: int | None = None) -> list[list[Any]]:
    total: Counter[str] = Counter()
    for items in lists:
        for key, n in items:
            total[key] += n
    ranked = _ranked(total)
    return [[k, n] for k, n in (ranked[:cap] if cap else ranked)]


def aggregate_profiles(client: str, profiles: list[DeckProfile]) -> dict[str, Any]:
    """The client aggregate (`decks/profile.json`): medians and majorities across decks,
    exemplars unioned in deck order (capped), plus the per-deck breakdown."""
    profiles = sorted(profiles, key=lambda p: p.slug)
    if not profiles:
        return {"client": client, "deck_count": 0, "decks": {}}
    headers = [p.header for p in profiles if p.header.titles_considered]
    header: dict[str, Any] = {"style": "topic_led"}
    exemplars: list[str] = []
    if headers:
        styles = Counter(h.profile["style"] for h in headers)
        header = {
            "style": sorted(styles.items(), key=lambda i: (-i[1], i[0]))[0][0],
            "max_words": round(statistics.median(h.profile["max_words"] for h in headers)),
            "sentence_case": _majority([h.profile["sentence_case"] for h in headers]),
            "terminal_punctuation": _majority(
                [h.profile["terminal_punctuation"] for h in headers]
            ),
            "numbers_in_headers": "allowed"
            if _majority([h.profile["numbers_in_headers"] == "allowed" for h in headers])
            else "discouraged",
        }
        for h in headers:
            for title in h.exemplar_headers:
                if title not in exemplars and len(exemplars) < EXEMPLAR_CAP:
                    exemplars.append(title)
    HeaderStyleProfile.from_mapping(header)
    voices = [p.voice for p in profiles if p.voice.sentences]
    role_counts: Counter[str] = Counter()
    for p in profiles:
        role_counts.update(p.storyline.role_counts)
    component_counts: Counter[str] = Counter()
    for p in profiles:
        component_counts.update(p.design.component_counts)
    margins = [p.design.margin_pt for p in profiles if p.design.margin_pt is not None]
    slide_total = sum(p.storyline.slide_count for p in profiles)
    return {
        "client": client,
        "deck_count": len(profiles),
        "slide_count": slide_total,
        "storyline": {
            "role_counts": dict(sorted(role_counts.items())),
            "mean_words_per_slide": round(
                sum(
                    p.storyline.mean_words_per_slide * p.storyline.slide_count for p in profiles
                )
                / slide_total,
                1,
            )
            if slide_total
            else 0.0,
        },
        "header": {
            "profile": header,
            "question_share": round(statistics.median(h.question_share for h in headers), 3)
            if headers
            else 0.0,
            "exemplar_headers": exemplars,
        },
        "voice": {
            "median_sentence_words": round(
                statistics.median(v.median_sentence_words for v in voices), 1
            )
            if voices
            else 0.0,
            "mean_sentence_words": round(
                statistics.median(v.mean_sentence_words for v in voices), 1
            )
            if voices
            else 0.0,
            "person": {
                key: round(statistics.median(v.person[key] for v in voices), 3)
                for key in ("we", "you", "they")
            }
            if voices
            else {"we": 0.0, "you": 0.0, "they": 0.0},
            "bullet_share": round(statistics.median(v.bullet_share for v in voices), 3)
            if voices
            else 0.0,
            "terms": _sum_ranked([v.terms for v in voices], TERM_CAP),
            "acronyms": sorted({a for v in voices for a in v.acronyms}),
            "avoided": [],
        },
        "design": {
            "component_counts": dict(sorted(component_counts.items())),
            "low_confidence_slides": sum(len(p.design.low_confidence_slides) for p in profiles),
            "margin_pt": round(statistics.median(margins), 1) if margins else None,
            "fonts": _sum_ranked([p.design.fonts for p in profiles]),
            "colours": _sum_ranked([p.design.colours for p in profiles]),
        },
        "decks": {
            p.slug: {
                "deck": p.deck,
                "slides": p.storyline.slide_count,
                "role_counts": p.storyline.role_counts,
                "header_style": p.header.profile["style"],
                "max_words": p.header.profile.get("max_words"),
                "median_sentence_words": p.voice.median_sentence_words,
                "component_counts": p.design.component_counts,
                "low_confidence_slides": len(p.design.low_confidence_slides),
            }
            for p in profiles
        },
    }
