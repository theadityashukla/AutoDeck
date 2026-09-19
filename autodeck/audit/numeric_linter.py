"""The numeric linter (A2): every number is copied from a span or computed in the open.

A2 is the invariant a reader can check without leaving the room. They point at a figure
and ask where it came from, and the only two acceptable answers are *"it is in this
sentence of this paper"* and *"it is this arithmetic over those two sentences"*. Anything
else — a remembered number, a rounded one, a plausible one — is the failure this module
exists to make impossible to ship.

## Why the module is shaped this way

**Extraction and judgement are separated, and the separation is the design.** `extract_numerals`
is graded on recall alone: it pulls the digits out of `A100`, `int8`, `GPT-4`, `2-4x`,
`3.2M`, `2023-11-14` and `29ms` without any opinion about whether they are claim-bearing.
Deciding what needs a source is `match_numerals`' job. Conflating the two is how a linter
quietly stops catching things: the day someone teaches the extractor that "model numbers
are fine", `A100` stops being seen and so does the fabricated `A100` that was never
measured.

**The normalisation table is an artifact, not a regex.** INVARIANTS names it as the place
this invariant leaks, so `SCALE_TABLE`, `UNIT_TABLE`, `DATE_TABLE` and `SEPARATOR_RULES`
are declarative, carry their own justification, self-check for collisions at import, and
are tested directly rather than only through a lint run. A regex that happens to pass is
untestable in exactly the cases that matter.

**Matching has a floor, and the floor is the `(value, unit)` key.** A numeral matches a
citation when the numeral and the cited span share a normalised key, and nothing else
counts. That sentence exists because the three defects found in this module by an
adversarial review were all in *fallback* paths, and every one had been added to prevent a
false block: a verbatim substring search that let `40%` match `140%`, an unbounded rounding
match that let `0.51` be printed as `1x`, and an input match that threw the unit away so a
millisecond figure could be printed as a percentage. Each fallback was looser than the
thing it backed up, and the ladder had no floor.

So the floor is stated as a rule with a hole in it, because a rule with no hole gets
quietly ignored the first time it causes a false block: **a fallback may be wider than the
key intersection only if every match it makes is reported as a finding.** The
minority-reading branch already obeyed it. The three defects did not, and that — not the
individual rules — is what made them dangerous, because A2's green is the one result a
GATE 2 reviewer is invited to treat as settled. Every `NumeralMatch` records the
`matched_on` key it was made on, and `tests/test_numeric_linter.py` walks them, so the next
fallback either names a key its source carries or shows up in the report.

**A derivation is checked from both ends.** Re-executing the formula proves the
arithmetic; `check_derivation_inputs` proves the inputs were copied rather than invented.
Only the pair closes the loop — a derivation with real spans, correct arithmetic and made-up
input values passes every other check in the system, because its result traces to itself.

**A formula is model-generated text, not code.** `Derivation.formula` arrives from a
provider. `eval()` on it would hand a content agent arbitrary Python execution inside the
build, so `evaluate_formula` parses with `ast` and walks the tree, admitting numeric
literals, the declared input names, `+ - * / **` and unary minus, and nothing else. Every
other node — a call, an attribute, a name that was not declared — raises rather than runs.
Division by zero, overflow and NaN are findings too: a linter that dies on bad arithmetic
stops being a linter at the moment it is needed.

**The seam takes either input.** The linter runs twice in the finished system — here on IR
text, and again in Phase 3b on text extracted from the rendered deck. So the core is
`lint_scope`, which knows only about text plus the citations and derivations in force over
it, and there are two thin adapters: `lint_deck` over a `Deck`, and `lint_rendered_slides`
over rendered text keyed by slide id.

## What it does not do

**It does not fix.** Rounding a stated result to agree with its formula would destroy the
evidence that the writer's arithmetic was wrong. Findings go to the orchestrator, which
blocks; the same posture as `gate1.py`.

**It does not decide a numeral is obviously fine.** There is no "years look like citation
chrome" heuristic. `ALLOWLIST` is empty, and anything ever added to it must be an exact
surface form with a written justification — see the comment there.

**It reports where A2 is genuinely ambiguous rather than picking.** `1,234` is 1234 in one
locale and 1.234 in another; a numeral can match numerals in two different cited spans.
Both are advisory findings naming the ambiguity, because a linter that silently picks a
reading is a linter whose green result means nothing.

Owning phase: 2b (task 2b.5). Opus tier — `autodeck/audit/` is a path guardrail.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Literal

from autodeck.ingest.provenance import normalise_text
from autodeck.ir.models import Citation, Deck, Derivation, DerivationInput, DiagramSpec

# ---------------------------------------------------------------------------
# Findings and reports — the gate1.py shape
# ---------------------------------------------------------------------------

Severity = Literal["blocking", "advisory"]

#: A2's pass condition is "zero unmatched numerals", so an uncited numeral and a derivation
#: whose arithmetic does not reproduce are `blocking`. `advisory` is for the cases where the
#: linter has an answer but not a confident one — a locale-ambiguous separator, a numeral
#: that traces to more than one span, a stated result that is its formula's output rounded.
#: A reviewer has to see those; none of them is a failure on its own.


@dataclass(frozen=True)
class NumericFinding:
    """One thing A2 has to say about one numeral or one derivation.

    Mirrors `gate1.Finding` deliberately: same three fields, same meaning of `severity`,
    plus a `location` because this linter runs over many blocks at once and "a number does
    not trace" is useless without saying which number on which slide.
    """

    check: str
    severity: Severity
    detail: str
    location: str = ""

    def __str__(self) -> str:
        marker = "BLOCKING" if self.severity == "blocking" else "advisory"
        where = f" · {self.location}" if self.location else ""
        return f"[{marker}] {self.check}{where}: {self.detail}"


MatchSource = Literal["citation", "derivation_result", "derivation_input"]


@dataclass(frozen=True)
class NumeralMatch:
    """A numeral and the thing it traces to.

    Kept even on a clean run. A6's audit report has to *show the working* for every derived
    figure, and reconstructing which span a number came from after the fact means running
    the match again — so the match records itself the first time.
    """

    numeral: Numeral
    source: MatchSource
    detail: str
    location: str = ""
    via_rounding: bool = False
    """True when the text figure is the derivation's computed result rounded. Legitimate for
    a derivation, never for a citation — see `_match_against_derivations`."""
    via_ambiguous_form: bool = False
    """True when the match needed the minority reading of a locale-ambiguous separator."""
    other_sources: tuple[str, ...] = ()
    """Further citations carrying the same numeral. A2 ambiguity, surfaced not resolved."""
    via_unqualified_form: bool = False
    """True when the text carried a bare number and the cited span qualifies it with a unit.

    The one place matching is allowed to be *wider* than the key intersection, and it pays
    for that by being reported — see `_match_against_citations`.
    """
    matched_on: NormalKey | None = None
    """The normalised `(value, unit)` key this match was made on, from the numeral's side.

    Recorded so **the floor rule can be checked rather than merely written down**. A match
    against a citation has to name a key the cited span itself carries; a match against a
    derivation has to name a key whose unit is the derivation's declared unit. The test
    `test_every_match_names_a_key_its_source_actually_carries` walks every match a lint run
    produces and confirms exactly that, so a future fallback matching on something looser
    than a shared key has nothing truthful to put here and the suite goes red.
    """


@dataclass
class NumericReport:
    """What A2 found, for a human and for the orchestrator's block decision."""

    findings: list[NumericFinding] = field(default_factory=list)
    matches: list[NumeralMatch] = field(default_factory=list)
    numerals_checked: int = 0
    derivations_checked: int = 0

    @property
    def blocking(self) -> list[NumericFinding]:
        return [f for f in self.findings if f.severity == "blocking"]

    @property
    def advisory(self) -> list[NumericFinding]:
        return [f for f in self.findings if f.severity == "advisory"]

    @property
    def passes(self) -> bool:
        """Whether A2 holds: zero unmatched numerals and every derivation re-executes.

        Unlike `gate1.Gate1Report.mechanical_checks_pass`, this one is allowed the plain
        name. GATE 1 asks a question no check can answer, so a boolean called `passed`
        there would misrepresent the gate. A2 is arithmetic end to end, and its own wording
        is a mechanical threshold — *"zero unmatched numerals to pass"*. Saying so is
        honest here and would not be there.

        It is still not a decision to render. This module reports; the orchestrator blocks.
        """
        return not self.blocking

    def extend(self, other: NumericReport) -> None:
        self.findings.extend(other.findings)
        self.matches.extend(other.matches)
        self.numerals_checked += other.numerals_checked
        self.derivations_checked += other.derivations_checked

    def render(self) -> str:
        lines = [
            "A2 — numeric lint",
            f"{self.numerals_checked} numeral(s) · {self.derivations_checked} derivation(s)",
            "",
        ]
        if not self.findings:
            lines.append("Every numeral traces to a cited span or a re-executed derivation.")
        else:
            lines.extend(str(f) for f in self.blocking + self.advisory)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# The normalisation table
# ---------------------------------------------------------------------------
#
# INVARIANTS, on A2: "the normalisation table is where this invariant leaks — locale
# decimal separators, % vs percent, scale suffixes. Test it directly, not only end to end."
# So it is a table. Each rule carries the leak it closes, `tests/test_numeric_linter.py`
# walks these tuples rather than hard-coding a sample of them, and `_check_table_collisions`
# below refuses to import if two rules claim the same surface form.


@dataclass(frozen=True)
class ScaleRule:
    """A suffix that multiplies the numeral rather than qualifying it."""

    name: str
    surfaces: tuple[str, ...]
    multiplier: Decimal
    why: str


@dataclass(frozen=True)
class UnitRule:
    """Surface forms that mean the same unit. `canonical` is what matching compares."""

    canonical: str
    surfaces: tuple[str, ...]
    why: str


SCALE_TABLE: tuple[ScaleRule, ...] = (
    ScaleRule(
        "thousand",
        ("k", "thousand", "thousands"),
        Decimal(10) ** 3,
        "A source writing '12,000' and a slide writing '12k' are the same figure; without "
        "expansion the slide numeral matches nothing and A2 blocks a correct deck.",
    ),
    ScaleRule(
        "million",
        ("m", "mn", "million", "millions"),
        Decimal(10) ** 6,
        "The spec's own worked example: '3.2M' in the text against '3,200,000' in the "
        "quote. Expansion is what makes those one numeral.",
    ),
    ScaleRule(
        "billion",
        ("b", "bn", "billion", "billions"),
        Decimal(10) ** 9,
        "Model sizes in this corpus are written '13B' and '175B parameters'. A bare 13 "
        "would match any other 13 on the slide, which is worse than not matching at all.",
    ),
    ScaleRule(
        "trillion",
        ("t", "tn", "trillion", "trillions"),
        Decimal(10) ** 12,
        "Token counts and market figures; included for symmetry so 'T' is never read as a "
        "unit by accident.",
    ),
)

UNIT_TABLE: tuple[UnitRule, ...] = (
    UnitRule(
        "percent",
        ("%", "percent", "percents", "per cent", "pct"),
        "The named leak in INVARIANTS. '40%' and '40 percent' are one numeral; keeping them "
        "apart is the single most likely way a correct deck gets blocked.",
    ),
    UnitRule(
        "pp",
        ("pp", "ppt", "percentage point", "percentage points"),
        "Deliberately NOT folded into `percent`. A rise of 5 percentage points and a rise "
        "of 5 percent are different numbers, and a table that equated them would let a "
        "writer swap one for the other silently — the exact substitution A2 exists to stop.",
    ),
    UnitRule(
        "x",
        ("x", "×", "times", "fold", "-fold"),
        "'2-4x' and '2-4×' are the same measured range. The multiplication sign is what "
        "the papers use and the ASCII 'x' is what slides use.",
    ),
    UnitRule(
        "usd",
        ("$", "us$", "usd", "dollar", "dollars"),
        "Currency is a unit: 3.2 million dollars must not match 3.2 million requests.",
    ),
    UnitRule("eur", ("€", "eur", "euro", "euros"), "As `usd`."),
    UnitRule("gbp", ("£", "gbp", "pound", "pounds"), "As `usd`."),
    UnitRule(
        "ms",
        ("ms", "msec", "msecs", "millisecond", "milliseconds"),
        "The spec's '29ms' vs '29 ms' case. Latency figures are the ones most often "
        "re-typed with the space closed up.",
    ),
    UnitRule("s", ("sec", "secs", "second", "seconds"), "As `ms`."),
    UnitRule("min", ("min", "mins", "minute", "minutes"), "As `ms`."),
    UnitRule("h", ("h", "hr", "hrs", "hour", "hours"), "As `ms`."),
    UnitRule(
        "tok/s",
        ("tok/s", "tokens/s", "tokens/sec", "tps", "tok/sec"),
        "Throughput, the headline unit of this corpus; written five ways across the papers.",
    ),
    UnitRule("kb", ("kb", "kilobyte", "kilobytes"), "Memory figures; see `gb`."),
    UnitRule("mb", ("mb", "megabyte", "megabytes"), "Memory figures; see `gb`."),
    UnitRule(
        "gb",
        ("gb", "gigabyte", "gigabytes"),
        "Listed before the single-letter scale suffixes are consulted, so '8GB' is eight "
        "gigabytes and not eight billion. Longest-surface-first is what makes that work.",
    ),
    UnitRule("tb", ("tb", "terabyte", "terabytes"), "Memory figures; see `gb`."),
)

#: Ordinal endings, recognised only when written directly against the digits.
ORDINAL_SUFFIXES: tuple[str, ...] = ("st", "nd", "rd", "th")

#: Currency written before the digits rather than after.
CURRENCY_PREFIXES: tuple[str, ...] = ("$", "us$", "£", "€", "usd", "eur", "gbp")

#: Separators that are *only ever* grouping — never a decimal point in any locale. Stripped
#: before the ambiguous `,` / `.` reading is worked out.
GROUPING_ONLY_SEPARATORS: str = "    '’"


@dataclass(frozen=True)
class SeparatorRule:
    """One reading of `,` and `.` inside a digit run.

    Held as data because this is where locale ambiguity lives and because the rules have to
    be readable next to each other to be argued with. `alternative` is non-empty only for
    the genuinely undecidable shape, and a match that needs the alternative is reported.
    """

    name: str
    condition: str
    reading: str
    why: str


SEPARATOR_RULES: tuple[SeparatorRule, ...] = (
    SeparatorRule(
        "both separators present",
        "the run contains both ',' and '.'",
        "the last one to appear is the decimal separator; the other is grouping",
        "'1.234,5' and '1,234.5' are both unambiguous once you know only one separator can "
        "come last. No locale puts grouping after the decimal point.",
    ),
    SeparatorRule(
        "repeated separator",
        "one separator appears more than once",
        "grouping",
        "'3.200.000' cannot be a decimal — there is only ever one decimal point.",
    ),
    SeparatorRule(
        "single separator, tail not three digits",
        "one separator, and the digits after it do not number exactly three",
        "decimal",
        "'1,5' and '1.25' are decimals in every locale that writes them. This is the "
        "'1.5 vs 1,5' case the spec names.",
    ),
    SeparatorRule(
        "single separator, three-digit tail",
        "one separator, exactly three digits after it",
        "AMBIGUOUS: comma leads with 1234 and offers 1.234; full stop leads with 1.234 and "
        "offers 1234",
        "'1,234' is one thousand two hundred and thirty-four in English and one point two "
        "three four in German, and nothing in the string says which. Both readings are "
        "kept; a match that needs the minority one raises an advisory finding rather than "
        "being silently accepted, because picking a locale here is how a wrong number "
        "passes A2 looking clean.",
    ),
)


def _check_table_collisions() -> None:
    """Refuse to import if two rules claim the same surface form.

    A collision would make matching depend on table order, which is exactly the kind of
    silent, position-dependent behaviour a declarative table exists to avoid. Cheaper to
    fail at import than to debug a numeral that normalises differently after a reorder.
    """
    seen: dict[str, str] = {}
    for rule in SCALE_TABLE:
        for surface in rule.surfaces:
            owner = f"scale:{rule.name}"
            if surface in seen:
                raise RuntimeError(
                    f"normalisation surface {surface!r}: {seen[surface]} vs {owner}"
                )
            seen[surface] = owner
    for unit in UNIT_TABLE:
        for surface in unit.surfaces:
            owner = f"unit:{unit.canonical}"
            if surface in seen:
                raise RuntimeError(
                    f"normalisation surface {surface!r}: {seen[surface]} vs {owner}"
                )
            seen[surface] = owner


_check_table_collisions()

_SCALE_BY_SURFACE: dict[str, ScaleRule] = {s: r for r in SCALE_TABLE for s in r.surfaces}
_UNIT_BY_SURFACE: dict[str, UnitRule] = {s: r for r in UNIT_TABLE for s in r.surfaces}

#: Every suffix surface, longest first. Order is the whole reason '8GB' is not 8 billion.
_SUFFIX_SURFACES: tuple[str, ...] = tuple(
    sorted({*_SCALE_BY_SURFACE, *_UNIT_BY_SURFACE, *ORDINAL_SUFFIXES}, key=len, reverse=True)
)
_PREFIX_SURFACES: tuple[str, ...] = tuple(sorted(CURRENCY_PREFIXES, key=len, reverse=True))


def suffix_allows_a_space(surface: str) -> bool:
    """Whether `surface` may be separated from its digits by a space.

    A single alphabetic character may not: `5 m` is five metres, five minutes or a five in
    a sentence beginning "m…" at least as often as it is five million, and reading it as a
    scale suffix would inflate a numeral by a million on a guess. Written closed up, `5m`
    is unambiguously the scale suffix. Everything else — `%`, `×`, and every word —
    survives a space.
    """
    return not (len(surface) == 1 and surface.isalpha())


# ---------------------------------------------------------------------------
# Extraction — graded on recall only
# ---------------------------------------------------------------------------

NormalKey = tuple[Decimal, str]
"""A numeral reduced to (value, canonical unit). Matching is set intersection over these."""

#: A digit run, with or without grouping. The grouped alternative is tried first and each
#: group is guarded with `(?!\d)` so '1.2345' is one decimal rather than '1.234' plus a
#: stray '5' — a mis-tokenisation that would invent a numeral out of nothing.
_NUMBER_TOKEN = re.compile(
    r"\d{1,3}(?:[,.    '’]\d{3}(?!\d))+(?:[.,]\d+)?"
    r"|\d+(?:[.,]\d+)?"
)

_MONTHS: dict[str, int] = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}

_MONTH_ALTERNATION = "|".join(sorted(_MONTHS, key=len, reverse=True))


@dataclass(frozen=True)
class DateRule:
    """A date shape lifted out before the plain digit scan sees it.

    Without these, '2023-11-14' is three numerals, and a source writing '14 November 2023'
    supplies only two of them — so a correctly cited date fails A2. Dates are matched as one
    thing, on their resolved value, which is the only reading that survives reformatting.
    """

    name: str
    pattern: re.Pattern[str]
    why: str


DATE_TABLE: tuple[DateRule, ...] = (
    DateRule(
        "iso",
        re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
        "Unambiguous by construction; the only date form that never needs a locale.",
    ),
    DateRule(
        "slashed",
        re.compile(r"\b(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y>\d{4})\b"),
        "'03/04/2024' is 3 April in Britain and 4 March in America. Both readings are "
        "emitted and the numeral is flagged ambiguous rather than guessed.",
    ),
    DateRule(
        "month first",
        re.compile(
            rf"\b(?P<mon>{_MONTH_ALTERNATION})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})\b",
            re.I,
        ),
        "The form the slide writes when the source wrote ISO.",
    ),
    DateRule(
        "day first",
        re.compile(
            rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<mon>{_MONTH_ALTERNATION})\.?,?\s+(?P<y>\d{{4}})\b",
            re.I,
        ),
        "The same date, written the other way round; British prose default.",
    ),
    DateRule(
        "month and year",
        re.compile(rf"\b(?P<mon>{_MONTH_ALTERNATION})\.?\s+(?P<y>\d{{4}})\b", re.I),
        "'March 2023' — a real date with no day, and two numerals if left to the digit scan.",
    ),
    DateRule(
        "decade",
        re.compile(r"\b(?P<y>1\d{3}|20\d{2})s\b"),
        "'the 1980s'. Lifted out because the plain scan would read the trailing 's' as the "
        "seconds unit and report 1980 seconds.",
    ),
)


@dataclass(frozen=True)
class Numeral:
    """One numeral as it appears, with everything needed to normalise and report it.

    `forms` is the set of `(value, unit)` keys this numeral could be; matching is a set
    intersection, which is what lets one surface form carry several legitimate readings
    (a scale suffix, a range endpoint inheriting its neighbour's unit) without the caller
    knowing about any of them.
    """

    text: str
    """The surface form, prefix and suffix included — what a finding quotes back."""
    context: str
    """The whole word the digits sit in: 'A100', 'int8', 'GPT-4'. Reporting only."""
    forms: frozenset[NormalKey]
    ambiguous_forms: frozenset[NormalKey]
    """Subset of `forms` that exists only because a separator or a date order is
    undecidable. A match that needs one of these is reported, never silently taken."""
    start: int
    end: int
    """Offsets into the *normalised* text `extract_numerals` was given, not the original."""
    kind: Literal["number", "date"] = "number"

    def describe(self) -> str:
        if self.context and self.context != self.text:
            return f"{self.text!r} (in {self.context!r})"
        return repr(self.text)


def extract_numerals(text: str) -> list[Numeral]:
    """Every numeral in `text`, in order. Recall is the only goal.

    Dates are lifted out first so a reformatted date is one numeral rather than three, then
    every remaining digit run is taken with whatever currency prefix and unit or scale
    suffix sits against it. Nothing here decides whether a numeral needs a citation — a
    slide number, a model name and a fabricated market size all come back the same way, and
    `match_numerals` is where they stop being the same.

    `text` is passed through `provenance.normalise_text` first, the same normalisation the
    citation resolver uses, so a ligature or a line-broken hyphen cannot make a numeral
    findable in the block and unfindable in the quote.
    """
    normalised = normalise_text(text)
    numerals: list[Numeral] = []
    consumed: list[tuple[int, int]] = []

    for rule in DATE_TABLE:
        for match in rule.pattern.finditer(normalised):
            if _overlaps(match.start(), match.end(), consumed):
                continue
            numeral = _date_numeral(rule, match)
            if numeral is None:
                continue
            consumed.append((match.start(), match.end()))
            numerals.append(numeral)

    for match in _NUMBER_TOKEN.finditer(normalised):
        if _overlaps(match.start(), match.end(), consumed):
            continue
        numerals.append(_plain_numeral(normalised, match))

    numerals.sort(key=lambda n: n.start)
    return _apply_range_inheritance(normalised, numerals)


def _overlaps(start: int, end: int, spans: Sequence[tuple[int, int]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def _date_numeral(rule: DateRule, match: re.Match[str]) -> Numeral | None:
    """Turn one date match into a single numeral keyed on its resolved value."""
    groups = match.groupdict()
    year = int(groups["y"])
    forms: set[NormalKey] = set()
    ambiguous: set[NormalKey] = set()

    if rule.name == "decade":
        forms.add((Decimal(year), "decade"))
        forms.add((Decimal(year), ""))
    elif rule.name == "month and year":
        month = _MONTHS[groups["mon"].casefold()]
        forms.add((Decimal(year * 100 + month), "yearmonth"))
    elif rule.name == "slashed":
        a, b = int(groups["a"]), int(groups["b"])
        # Both readings, because nothing in '03/04/2024' says which is the month.
        forms.add((Decimal(_as_date_key(year, b, a)), "date"))
        ambiguous.add((Decimal(_as_date_key(year, a, b)), "date"))
        if a == b:
            ambiguous.clear()
    else:
        month = int(groups["m"]) if "m" in groups else _MONTHS[groups["mon"].casefold()]
        day = int(groups["d"])
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        forms.add((Decimal(_as_date_key(year, month, day)), "date"))

    return Numeral(
        text=match.group(0),
        context=match.group(0),
        forms=frozenset(forms),
        ambiguous_forms=frozenset(ambiguous),
        start=match.start(),
        end=match.end(),
        kind="date",
    )


def _as_date_key(year: int, month: int, day: int) -> int:
    return year * 10_000 + month * 100 + day


def _plain_numeral(text: str, match: re.Match[str]) -> Numeral:
    digits = match.group(0).rstrip(GROUPING_ONLY_SEPARATORS + ",.")
    end = match.start() + len(digits)
    prefix = _scan_prefix(text, match.start())
    suffixes = _scan_suffix(text, end)
    suffix_width = sum(len(surface) for surface in suffixes)
    primary, alternative = _value_candidates(digits)

    forms = _forms_for(primary, prefix, suffixes)
    ambiguous = _forms_for(alternative, prefix, suffixes) - forms
    surface = text[match.start() - len(prefix) : end + suffix_width]

    return Numeral(
        text=surface.strip(),
        context=_word_around(text, match.start(), end),
        forms=frozenset(forms),
        ambiguous_forms=frozenset(ambiguous),
        start=match.start() - len(prefix),
        end=end + suffix_width,
    )


def _forms_for(
    values: Iterable[Decimal], prefix: str, suffixes: Sequence[str]
) -> set[NormalKey]:
    """Apply the tables: scale multiplies, unit qualifies, a currency prefix is the unit."""
    currency = prefix.strip().casefold()
    trimmed = [surface.strip().casefold() for surface in suffixes if surface.strip()]
    unit = ""
    multiplier = Decimal(1)

    if currency:
        currency_rule = _UNIT_BY_SURFACE.get(currency)
        unit = currency_rule.canonical if currency_rule else ""

    if any(surface in ORDINAL_SUFFIXES for surface in trimmed):
        # An ordinal and its cardinal are the same numeral in different grammar: a source
        # may write "the 3rd generation" where the slide writes "generation 3".
        return {key for value in values for key in ((value, "ordinal"), (value, unit))}

    for surface in trimmed:
        scale = _SCALE_BY_SURFACE.get(surface)
        if scale is not None:
            multiplier *= scale.multiplier
            continue
        unit_rule = _UNIT_BY_SURFACE.get(surface)
        if unit_rule is not None and not currency:
            unit = unit_rule.canonical

    return {(value * multiplier, unit) for value in values}


def _scan_prefix(text: str, start: int) -> str:
    """The currency symbol or code immediately before the digits, if any."""
    head = text[max(0, start - 8) : start]
    for surface in _PREFIX_SURFACES:
        for candidate in (surface, surface + " "):
            if head.casefold().endswith(candidate):
                before = head[: len(head) - len(candidate)]
                if before and before[-1].isalnum():
                    continue
                return head[len(head) - len(candidate) :]
    return ""


def _scan_suffix(text: str, end: int) -> list[str]:
    """The scale and/or unit written against the digits, longest surface first.

    Returns up to two surfaces because a scale and a unit can both be present: `3.2 million
    dollars` is the same numeral as `$3.2M`, and reading only the first of them would leave
    one of those two forms uncomparable to the other.
    """
    found: list[str] = []
    cursor = end
    while len(found) < 2:
        surface = _scan_one_suffix(text, cursor)
        if surface is None:
            break
        found.append(surface)
        cursor += len(surface)
        if surface.strip().casefold() not in _SCALE_BY_SURFACE:
            break
    return found


def _scan_one_suffix(text: str, end: int) -> str | None:
    tail = text[end : end + 20]
    folded = tail.casefold()
    for surface in _SUFFIX_SURFACES:
        for candidate in (surface, " " + surface):
            if candidate.startswith(" ") and not suffix_allows_a_space(surface):
                continue
            if not folded.startswith(candidate):
                continue
            after = tail[len(candidate) : len(candidate) + 1]
            if after.isalnum() or after in ("/", "-"):
                # 'ms' inside 'msgs', 'k' inside 'kg', 'x' inside 'x-axis': not this unit.
                continue
            return tail[: len(candidate)]
    return None


def _word_around(text: str, start: int, end: int) -> str:
    """The alphanumeric token the digits sit inside — 'A100' around the '100'."""
    left = start
    while left > 0 and (text[left - 1].isalnum() or text[left - 1] in "-_."):
        left -= 1
    right = end
    while right < len(text) and (text[right].isalnum() or text[right] in "-_."):
        right += 1
    return text[left:right].strip(".-_")


def _value_candidates(digits: str) -> tuple[list[Decimal], list[Decimal]]:
    """Read a digit run as `(leading values, alternative values)` per `SEPARATOR_RULES`.

    The alternative list is non-empty only for a single separator with exactly three digits
    after it — the shape where English and continental readings genuinely disagree. Callers
    treat a match that needs the alternative as a finding, not as a pass.
    """
    cleaned = digits
    for character in GROUPING_ONLY_SEPARATORS:
        cleaned = cleaned.replace(character, "")
    if not cleaned or not cleaned[0].isdigit():
        return [], []

    commas, dots = cleaned.count(","), cleaned.count(".")

    if commas and dots:
        separator = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        return _decimal_list(_read_as_decimal(cleaned, separator)), []

    if commas > 1 or dots > 1:
        separator = "," if commas else "."
        return _decimal_list(cleaned.replace(separator, "")), []

    if commas == 1 or dots == 1:
        separator = "," if commas else "."
        tail = cleaned.split(separator)[1]
        as_decimal = _read_as_decimal(cleaned, separator)
        as_grouped = cleaned.replace(separator, "")
        if len(tail) != 3:
            return _decimal_list(as_decimal), []
        if separator == ",":
            return _decimal_list(as_grouped), _decimal_list(as_decimal)
        return _decimal_list(as_decimal), _decimal_list(as_grouped)

    return _decimal_list(cleaned), []


def _read_as_decimal(cleaned: str, separator: str) -> str:
    other = "." if separator == "," else ","
    return cleaned.replace(other, "").replace(separator, ".")


def _decimal_list(raw: str) -> list[Decimal]:
    try:
        return [Decimal(raw)]
    except InvalidOperation:  # pragma: no cover — the tokeniser cannot produce this
        return []


#: Characters that make two adjacent numerals a range rather than two separate figures.
RANGE_SEPARATORS: tuple[str, ...] = ("-", "–", "—", "to", "–to", "..")


def _apply_range_inheritance(text: str, numerals: list[Numeral]) -> list[Numeral]:
    """Let a range's affixes reach both of its endpoints.

    '2-4x' writes the unit once and means it twice, and a source writing '2x to 4x' would
    otherwise fail to supply the left endpoint. Inheritance goes both ways: the left
    endpoint takes the right's suffix, the right takes the left's currency prefix, so
    '$2-4M' is two to four million dollars at both ends.

    The unqualified readings are kept as well, because sources really do write ranges both
    ways and dropping them would block a correct deck.
    """
    if len(numerals) < 2:
        return numerals

    result = list(numerals)
    for index in range(len(result) - 1):
        left, right = result[index], result[index + 1]
        if left.kind == "date" or right.kind == "date":
            continue
        between = text[left.end : right.start].strip().casefold()
        if between not in RANGE_SEPARATORS:
            continue

        head = _scan_prefix(text, _digits_start(text, left))
        tail = _scan_suffix(text, _digits_end(text, right))
        if not head and not tail:
            continue

        for position, numeral in ((index, left), (index + 1, right)):
            primary, alternative = _value_candidates(_digits_of(text, numeral))
            result[position] = _with_extra_forms(
                result[position],
                _forms_for(primary, head, tail),
                _forms_for(alternative, head, tail),
            )
    return result


def _with_extra_forms(
    numeral: Numeral, extra: set[NormalKey], extra_ambiguous: set[NormalKey]
) -> Numeral:
    forms = numeral.forms | extra
    ambiguous = (numeral.ambiguous_forms | extra_ambiguous) - forms
    return Numeral(
        text=numeral.text,
        context=numeral.context,
        forms=frozenset(forms),
        ambiguous_forms=frozenset(ambiguous),
        start=numeral.start,
        end=numeral.end,
        kind=numeral.kind,
    )


def _digits_of(text: str, numeral: Numeral) -> str:
    match = _NUMBER_TOKEN.search(text, numeral.start, numeral.end)
    return match.group(0) if match else numeral.text


def _digits_start(text: str, numeral: Numeral) -> int:
    match = _NUMBER_TOKEN.search(text, numeral.start, numeral.end)
    return match.start() if match else numeral.start


def _digits_end(text: str, numeral: Numeral) -> int:
    match = _NUMBER_TOKEN.search(text, numeral.start, numeral.end)
    return match.end() if match else numeral.end


# ---------------------------------------------------------------------------
# Formula evaluation — arithmetic only, never execution
# ---------------------------------------------------------------------------


class FormulaError(ValueError):
    """A formula could not be re-executed. Always becomes a finding, never an exception.

    Covers three different failures on purpose: the formula is not arithmetic (a call, an
    attribute, an undeclared name), the arithmetic is impossible (division by zero,
    overflow), or the result is not a number (NaN). They are one type because they have one
    consequence — the derivation's stated result is unverifiable, so A2 blocks — and
    because a caller that had to distinguish them would eventually forget one.
    """


#: Exactly the arithmetic the spec permits. Modulo, floor division and bitwise operators are
#: absent deliberately: none of them appears in a legitimate derivation, and each one added
#: is a further shape the walker has to be right about.
ALLOWED_BINARY_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}

ALLOWED_UNARY_OPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

#: Bounds on the expression itself. A derivation is `(a - b) / b * 100`; nothing legitimate
#: comes near these. They exist because `9 ** 9 ** 9` is a denial of service written in four
#: tokens, and because the formula is attacker-influenced text.
MAX_FORMULA_CHARS = 200
MAX_FORMULA_NODES = 100


def evaluate_formula(formula: str, inputs: Mapping[str, float]) -> float:
    """Re-execute `formula` over `inputs` without executing anything.

    The expression is parsed with `ast` and walked. Numeric literals, the names declared in
    `inputs`, `+ - * / **`, parentheses and unary minus are evaluated; every other node
    raises. There is no `eval`, no `__builtins__` dictionary to forget to empty, and no
    name resolution that reaches outside `inputs` — a formula naming `open` fails because
    `open` is not an input, not because a denylist happened to include it.

    Every literal is coerced to `float` before any operator sees it. That is a security
    measure as much as a numeric one: Python integers are arbitrary precision, so `9**9**9`
    on ints allocates until the process dies, while on floats it raises `OverflowError` in
    microseconds.

    Raises:
        FormulaError: the formula is not arithmetic, names something undeclared, divides by
            zero, overflows, or produces NaN.
    """
    if len(formula) > MAX_FORMULA_CHARS:
        raise FormulaError(
            f"formula is {len(formula)} characters, over the {MAX_FORMULA_CHARS} limit; "
            "a derivation is arithmetic over a handful of named inputs"
        )
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"formula is not a parseable expression: {exc.msg}") from exc

    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > MAX_FORMULA_NODES:
        raise FormulaError(
            f"formula has {node_count} nodes, over the {MAX_FORMULA_NODES} limit"
        )

    value = _evaluate_node(tree.body, inputs)
    if math.isnan(value):
        raise FormulaError("formula produced NaN; the stated result cannot be confirmed")
    if math.isinf(value):
        raise FormulaError("formula overflowed to infinity")
    return value


def _evaluate_node(node: ast.expr, inputs: Mapping[str, float]) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaError(
                f"formula contains the non-numeric literal {node.value!r}; "
                "a derivation is arithmetic over numbers"
            )
        return float(node.value)

    if isinstance(node, ast.Name):
        if node.id not in inputs:
            raise FormulaError(
                f"formula references {node.id!r}, which is not a declared input "
                f"({', '.join(sorted(inputs)) or 'none declared'}). Names are resolved "
                "only against the derivation's own inputs — nothing else is in scope."
            )
        return float(inputs[node.id])

    if isinstance(node, ast.UnaryOp):
        handler = ALLOWED_UNARY_OPS.get(type(node.op))
        if handler is None:
            raise FormulaError(f"unary operator {type(node.op).__name__} is not arithmetic")
        return handler(_evaluate_node(node.operand, inputs))

    if isinstance(node, ast.BinOp):
        binary = ALLOWED_BINARY_OPS.get(type(node.op))
        if binary is None:
            raise FormulaError(
                f"operator {type(node.op).__name__} is not permitted in a formula"
            )
        left = _evaluate_node(node.left, inputs)
        right = _evaluate_node(node.right, inputs)
        try:
            return binary(left, right)
        except ZeroDivisionError as exc:
            raise FormulaError(f"formula divides by zero: {left} / {right}") from exc
        except OverflowError as exc:
            raise FormulaError(f"formula overflowed: {exc}") from exc
        except (ValueError, TypeError) as exc:
            raise FormulaError(f"formula could not be evaluated: {exc}") from exc

    raise FormulaError(
        f"formula contains {type(node).__name__}, which is not arithmetic. A formula is "
        "model-generated text from a provider; only numbers, the declared input names and "
        "+ - * / ** are evaluated, and everything else is reported rather than run."
    )


# ---------------------------------------------------------------------------
# Derivation re-execution
# ---------------------------------------------------------------------------

#: Agreement this tight means the writer's stated result *is* the formula's output.
DERIVATION_REL_TOL = 1e-9

#: A stated result may legitimately be the computed one rounded for a slide — 62.9 for
#: 62.8640776. That is reported (A6 wants the working shown) but not blocked.
#: Beyond this relative distance it is not rounding, it is a different number.
ROUNDING_REL_LIMIT = 0.05


def re_execute_derivation(
    derivation: Derivation, *, location: str = ""
) -> list[NumericFinding]:
    """Check that a derivation's stated result is what its formula actually computes.

    This is the load-bearing half of A2 and the half that is invisible without it: a
    derivation with real citations, real input values and a wrong result looks exactly like
    a correct one to every other check in the system, because every number in it is cited.
    Only re-running the arithmetic finds it.

    Returns findings; raises nothing. A formula that cannot be evaluated is a blocking
    finding with the reason, because a derivation nobody can reproduce is indistinguishable
    from an invented number.
    """
    values = {name: item.value for name, item in derivation.inputs.items()}
    try:
        computed = evaluate_formula(derivation.formula, values)
    except FormulaError as exc:
        return [
            NumericFinding(
                check="derivation formula",
                severity="blocking",
                detail=f"{derivation.formula!r} could not be re-executed: {exc}",
                location=location,
            )
        ]

    stated = derivation.result
    if math.isclose(computed, stated, rel_tol=DERIVATION_REL_TOL, abs_tol=1e-12):
        return []

    places = _decimal_places(stated)
    rounds_to_stated = math.isclose(
        round(computed, places), stated, rel_tol=DERIVATION_REL_TOL, abs_tol=1e-12
    )
    if rounds_to_stated and _relative_difference(computed, stated) <= ROUNDING_REL_LIMIT:
        return [
            NumericFinding(
                check="derivation rounding",
                severity="advisory",
                detail=(
                    f"{derivation.formula!r} computes {computed!r}; the stated result "
                    f"{stated!r} is that rounded to {places} decimal place(s). The audit "
                    "report shows the unrounded working (A6)."
                ),
                location=location,
            )
        ]

    return [
        NumericFinding(
            check="derivation arithmetic",
            severity="blocking",
            detail=(
                f"{derivation.formula!r} over "
                f"{{{', '.join(f'{k}={v!r}' for k, v in sorted(values.items()))}}} computes "
                f"{computed!r}, but the derivation states {stated!r}. A2 re-executes every "
                "formula precisely because a wrong result with correct citations passes "
                "every other check."
            ),
            location=location,
        )
    ]


@lru_cache(maxsize=2048)
def _keys_for_value(quote: str, value: float) -> frozenset[NormalKey]:
    """Every `(value, unit)` key the numerals in `quote` give to `value`.

    Cached on the pair rather than on the `DerivationInput`, which is a pydantic model and
    not hashable, and because a rendered-slide pass asks the same short quote about the
    same input once per numeral on the slide.
    """
    wanted = Decimal(str(value))
    return frozenset(
        key
        for numeral in extract_numerals(quote)
        for key in numeral.forms | numeral.ambiguous_forms
        if key[0] == wanted
    )


def input_keys(item: DerivationInput) -> frozenset[NormalKey]:
    """The normalised keys the cited span attaches to this input's value.

    `DerivationInput` carries a value and a citation and no unit (B13), so the unit half of
    the key has to come from somewhere. It comes from the span: the numeral in the quote
    that *is* this value, read through the same tables as everything else. An input cited
    to *"generates at 40 ms per token"* is 40 milliseconds and nothing else, so a slide
    printing `40%` matches no input of that derivation.

    Empty when the value does not appear in its span at all — which is already a blocking
    `derivation input` finding, and which correctly matches nothing here rather than
    matching everything.
    """
    return _keys_for_value(item.citation.quote, item.value)


def derivation_input_is_traceable(item: DerivationInput) -> bool:
    """Whether this input's value really appears as a numeral in the span it cites.

    One definition, two readers. `check_derivation_inputs` turns a False into a blocking A2
    finding; `audit/report.py` prints the answer per input, because A6 asks the report to
    *show the working* and an input whose value is not in its own span is asserted rather
    than cited. Restating the test in the report would let the two drift apart, and a
    disagreement would read as a clean report on a build the linter had blocked.

    The comparison is over every normalised reading the extractor found, ambiguous ones
    included, so `3.2M` in a quote matches an input of `3200000`. A value that matches only
    through an ambiguous reading still counts here: the locale advisory belongs to
    `match_numerals`, and refusing the match would make this report "input not found" for a
    number that is plainly in the sentence.
    """
    return bool(input_keys(item))


def check_derivation_inputs(
    derivation: Derivation, *, location: str = ""
) -> list[NumericFinding]:
    """Check that each input's value is actually present in the span it cites.

    The gap this closes is the one the derivation machinery would otherwise open. B13 made
    `DerivationInput` carry a value *and* a citation so re-execution would not have to guess
    which numeral in a quote was meant — but nothing then required the value to be one of
    them. `Claim._derivation_inputs_are_cited` checks the citation is among the claim's
    citations; the formula re-execution checks the arithmetic. Between the two, a derivation
    with real spans, correct arithmetic and invented input values passes everything: the
    result is unmatched by any source and yet traces, because it traces to itself.

    A silent unit conversion trips this too — an input of 65 cited to a span reading `0.65`.
    That is deliberate and it is not a false positive: converting a ratio to a percentage is
    arithmetic, and A2's answer to arithmetic is to declare it as a derivation rather than
    to do it in the gap between a quote and a value.
    """
    findings: list[NumericFinding] = []
    for name, item in sorted(derivation.inputs.items()):
        if derivation_input_is_traceable(item):
            continue
        findings.append(
            NumericFinding(
                check="derivation input",
                severity="blocking",
                detail=(
                    f"input {name!r} is {item.value!r}, which does not appear in the span it "
                    f"cites ({_citation_label(item.citation)}: {item.citation.quote!r}). A "
                    "derivation input is a number copied from a source; if it was computed, "
                    "the computation is itself a derivation and A2 wants the working."
                ),
                location=location,
            )
        )
    return findings


#: Below this relative distance two figures are the same measurement written twice, not a
#: disagreement — deliberately the same number as `ROUNDING_REL_LIMIT`, because this module
#: already calls that distance "one figure rounded" and it would be incoherent for two
#: values to be a rounding of each other at one call site and a conflict at another.
CONFLICT_REL_LIMIT = ROUNDING_REL_LIMIT


def check_derivation_reconciles_sources(
    derivation: Derivation, *, location: str = ""
) -> list[NumericFinding]:
    """Refuse a derivation that averages away a disagreement between two sources (A8).

    `prompts/content.md`: *"Show both, never the average… Do not average them"*, and
    *"Never round to hedge, never average to reconcile"*. A8 says the same and is enforced
    by *"`prompts/content.md` behaviour + a conflicts section in the audit report"* — that
    is, by asking the model nicely. The derivation machinery then supplied the mechanism
    that makes breaking the promise look audited: two corpus sources reporting 412 and 671
    tokens per second for one workload, reconciled with `(a + b) / 2`, both inputs cited,
    both present in their spans, the arithmetic exact. `A2 passes: True`, zero findings,
    `require_safe_to_render` PASSED, the conflicts section reading *"no contradicting span"*
    — and the averaged figure printed under **"Working (A2 — derived figure)"** with a green
    tick against each source. A 63% disagreement between two papers, presented to a GATE 2
    reviewer as verified arithmetic.

    This is `PHASE-2B.md` §6.3's shape one level up. §6.3 closed *"the inputs trace to
    nothing"*; this is *"the inputs trace perfectly and the operation over them is the thing
    A8 forbids"*.

    ## Where the line is

    **Combining two sources is not the offence.** A rate built from one paper's numerator
    and another's denominator is honest arithmetic, and so is a percentage delta between a
    figure in one paper and a figure in another. Blocking those would push writers away from
    declaring their working at all, which is a worse outcome than the hole. **The offence is
    reconciling a disagreement about the same quantity into a single figure nobody
    measured.**

    So the blocking case is the narrow, certain one, and it is three conditions at once:

    1. the formula, re-executed over the real inputs, returns **exactly their arithmetic
       mean** — which is what `(a + b) / 2`, `a/2 + b/2`, `(a + b) * 0.5` and the midpoint
       `a + (b - a) / 2` all are, without this function having to pattern-match on formula
       text that a writer can spell a dozen ways;
    2. two of the inputs cite **different `doc_id`s** — one paper averaging two of its own
       measurements is a different argument, and not one A8 makes;
    3. those two values differ by more than `CONFLICT_REL_LIMIT`, so there is a
       disagreement to reconcile rather than one figure written twice.

    A percentage delta survives all of this — `(b - a) / b * 100` over 412 and 671 computes
    38.6, nowhere near their mean of 541.5 — and so does a cross-source rate, and that is
    the test of the boundary rather than an argument about it.

    **The residue is reported, not blocked.** A weighted average, or any other formula
    landing strictly between two materially different figures from two documents, is the
    same manoeuvre with a thumb on the scale, and so is a mean drawn from one document.
    Neither is certain enough to block on, so each raises an advisory naming the two
    figures. Better a reviewer reads one line about honest arithmetic than a writer learns
    that declaring a derivation is how a deck gets stopped.
    """
    values = {name: item.value for name, item in derivation.inputs.items()}
    if len(values) < 2:
        return []
    try:
        computed = evaluate_formula(derivation.formula, values)
    except FormulaError:
        return []  # already a blocking finding from `re_execute_derivation`
    if not math.isfinite(computed):
        return []

    mean = sum(values.values()) / len(values)
    is_mean = math.isclose(computed, mean, rel_tol=DERIVATION_REL_TOL, abs_tol=1e-12)
    low, high = min(values.values()), max(values.values())
    between = low < computed < high

    if not is_mean and not between:
        return []

    pair = _widest_disagreeing_pair(derivation)
    if pair is None:
        # Nothing here disagrees with anything, or it all came from one document.
        same_document = _widest_disagreeing_pair(derivation, across_documents=False)
        if is_mean and same_document is not None:
            return [_reconciliation_finding(derivation, same_document, computed, location)]
        return []

    if is_mean:
        return [_reconciliation_finding(derivation, pair, computed, location, blocking=True)]
    return [_reconciliation_finding(derivation, pair, computed, location)]


InputPair = tuple[tuple[str, DerivationInput], tuple[str, DerivationInput]]


def _widest_disagreeing_pair(
    derivation: Derivation, *, across_documents: bool = True
) -> InputPair | None:
    """The two inputs furthest apart that are far enough apart to be a disagreement.

    Widest rather than first, so the finding quotes the two figures a reader would argue
    about. Deterministic on ties by input name, because a finding whose text changed between
    runs is one nobody trusts.
    """
    items = sorted(derivation.inputs.items())
    best: InputPair | None = None
    best_distance = CONFLICT_REL_LIMIT
    for index, left in enumerate(items):
        for right in items[index + 1 :]:
            if across_documents and left[1].citation.doc_id == right[1].citation.doc_id:
                continue
            if not across_documents and left[1].citation.doc_id != right[1].citation.doc_id:
                continue
            distance = _relative_difference(left[1].value, right[1].value)
            if distance > best_distance:
                best, best_distance = (left, right), distance
    return best


def _reconciliation_finding(
    derivation: Derivation,
    pair: InputPair,
    computed: float,
    location: str,
    *,
    blocking: bool = False,
) -> NumericFinding:
    """One finding naming both figures, both sources, and where the disagreement belongs."""
    (left_name, left), (right_name, right) = pair
    distance = _relative_difference(left.value, right.value)
    verb = "averages" if blocking else "reconciles"
    consequence = (
        "The average is a figure neither source measured and no reader can check, and "
        "declaring it as a derivation is what makes it look audited: the report prints it "
        "under 'Working (A2 — derived figure)' with a green tick against each source."
        if blocking
        else "It may be honest arithmetic — a rate or a delta across two papers is fine — "
        "but a formula landing between two figures that disagree is how an average gets "
        "spelled when it is not spelled '/ 2'."
    )
    return NumericFinding(
        check="derivation reconciles disagreeing sources",
        severity="blocking" if blocking else "advisory",
        detail=(
            f"{derivation.formula!r} {verb} {left_name}={left.value!r} "
            f"({_citation_label(left.citation)}: {left.citation.quote!r}) and "
            f"{right_name}={right.value!r} "
            f"({_citation_label(right.citation)}: {right.citation.quote!r}) to "
            f"{computed!r}. Those figures differ by {distance:.0%}. {consequence} A8: show "
            "both, each with its source and its workload, and put the disagreement in the "
            "audit report's conflicts section — never average to reconcile."
        ),
        location=location,
    )


def _decimal_places(value: float) -> int:
    """How many decimal places `value` is written to, as a rounding target.

    An integral float is zero places. Without that, `result: 63` arrives as `63.0`, whose
    repr suggests one decimal place, and a formula computing 62.864 would be blocked for
    failing to equal 62.9 — a number nobody wrote.
    """
    if not math.isfinite(value) or value == int(value):
        return 0
    text = repr(float(value))
    if "e" in text or "E" in text:
        return 0
    return len(text.partition(".")[2])


def _relative_difference(computed: float, stated: float) -> float:
    scale = max(abs(computed), abs(stated))
    if scale == 0:
        return 0.0
    return abs(computed - stated) / scale


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AllowedNumeral:
    """One numeral A2 does not require to trace anywhere, by exact surface form."""

    surface: str
    why: str


#: Numerals exempt from A2. **Deliberately empty.**
#:
#: On IR text nothing qualifies: every numeral in a block is content, and an exemption here
#: would be an exemption for the fabricated numeral that happens to share its surface form.
#: Phase 3b's post-render run will meet slide numbers and footer chrome, and the right fix
#: there is for the text extractor to hand over body text rather than for this linter to
#: guess which '7' was a page number — a guess it cannot make and a heuristic the brief
#: forbids. The mechanism exists so that, if an entry is ever genuinely needed, it is an
#: exact surface form with a written justification and a test, passed in by the caller.
ALLOWLIST: tuple[AllowedNumeral, ...] = ()


@dataclass(frozen=True)
class LintScope:
    """Some text and the evidence in force over it.

    The whole seam. The linter never asks what produced the text, so the same core serves
    IR blocks now and rendered slide text in Phase 3b without either adapter teaching it
    anything about the other.
    """

    location: str
    text: str
    citations: tuple[Citation, ...] = ()
    derivations: tuple[Derivation, ...] = ()


def match_numerals(
    numerals: Sequence[Numeral],
    *,
    citations: Sequence[Citation] = (),
    derivations: Sequence[Derivation] = (),
    allow: Sequence[AllowedNumeral] = ALLOWLIST,
    location: str = "",
) -> tuple[list[NumeralMatch], list[Numeral]]:
    """Trace each numeral to a cited span, a derivation result, or a derivation input.

    Returns `(matches, unmatched)`. It does **not** re-execute derivations — matching a
    numeral to a stated result only proves the writer wrote the number down twice.
    `re_execute_derivation` is what proves the number is right, and keeping the two apart is
    what makes "disable the defence and confirm red" a test rather than a thought
    experiment.
    """
    allowed = {entry.surface for entry in allow}
    citation_forms = _citation_forms(citations)
    matches: list[NumeralMatch] = []
    unmatched: list[Numeral] = []

    for numeral in numerals:
        if numeral.text in allowed:
            continue
        match = _match_against_citations(numeral, citation_forms, location)
        if match is None:
            match = _match_against_derivations(numeral, derivations, location)
        if match is None:
            unmatched.append(numeral)
        else:
            matches.append(match)
    return matches, unmatched


#: A citation's numerals as `(leading keys, minority-reading keys)`. The two are kept apart
#: so that a slide numeral matching a quote only because *the quote* is locale-ambiguous is
#: reported, exactly as one matching because the slide is. Merging them would hide half the
#: ambiguity — and it is the same ambiguity either way.
CitationForms = tuple[Citation, frozenset[NormalKey], frozenset[NormalKey]]


def _citation_forms(citations: Sequence[Citation]) -> list[CitationForms]:
    """Every numeral in every cited quote, reduced to normal keys. Computed once per scope."""
    resolved: list[CitationForms] = []
    for citation in citations:
        numerals = extract_numerals(citation.quote)
        strict = frozenset(key for numeral in numerals for key in numeral.forms)
        loose = (
            frozenset(key for numeral in numerals for key in numeral.ambiguous_forms) - strict
        )
        resolved.append((citation, strict, loose))
    return resolved


def _match_against_citations(
    numeral: Numeral,
    citation_forms: Sequence[CitationForms],
    location: str,
) -> NumeralMatch | None:
    """Match a numeral to a span that contains it — on normalised `(value, unit)` keys only.

    **One strategy, and that is the floor.** There used to be a verbatim branch ahead of
    this one: `provenance.find_span` looking for the numeral's surface form inside the
    quote, on the reasoning that a numeral literally present in the source matches for the
    same reason the quote itself does. `find_span` is a *quote* locator. Its needle is
    normally a whole sentence, where substring semantics are right; here the needle was one
    to four characters, where they are catastrophically wrong. It matched `40%` against a
    span reading `140%`, `12` against `3,120`, `29 ms` against `1029 ms` and `3x` against
    `13x` — every one of them A2-green with no finding of any severity, and the audit
    report then printed the `140%` sentence underneath the `40%` claim as its evidence.

    The branch was **dropped rather than fenced**. A digit fence — requiring a non-numeral
    character on both sides of the hit — closes the four cases above and leaves two more
    open, because the fence can only see the *digits*: a bare `100` on a slide still passes
    a fence against a span reading `$100 million`, and a bare `29` still passes one against
    `29 ms`. Both are the unit-and-scale blindness that `UNIT_TABLE` exists to prevent, so
    any honest repair of the branch converges on re-implementing the key intersection that
    is already here. Removing it changed no legitimate match anywhere in the suite or in the
    A2 negative controls, which is the evidence that it backed up nothing.

    There is **no rounding tolerance here**, unlike the derivation path. `prompts/content.md`
    is explicit: if the span says `29ms` and the slide says `about 30ms`, a numeral has been
    introduced that appears in no source. Allowing 30 to match 29 would make that
    instruction unenforceable.
    """
    strict = [
        (c, shared) for c, forms, _ in citation_forms if (shared := forms & numeral.forms)
    ]
    if strict:
        return NumeralMatch(
            numeral=numeral,
            source="citation",
            detail=f"normalises onto a numeral in {_citation_label(strict[0][0])}",
            location=location,
            other_sources=tuple(_citation_label(c) for c, _ in strict[1:]),
            matched_on=_preferred_key(strict[0][1]),
        )

    everything = numeral.forms | numeral.ambiguous_forms
    loose = [
        (c, shared)
        for c, forms, alt in citation_forms
        if (shared := (forms | alt) & everything)
    ]
    if loose:
        return NumeralMatch(
            numeral=numeral,
            source="citation",
            detail=f"matches {_citation_label(loose[0][0])} only under the minority reading",
            location=location,
            via_ambiguous_form=True,
            other_sources=tuple(_citation_label(c) for c, _ in loose[1:]),
            matched_on=_preferred_key(loose[0][1]),
        )

    # Last tier: the text wrote a bare number where the span qualifies it — a chart series
    # value of `4.0` against a span reading `4.0x`, a table cell of `29` against `29 ms`.
    # Prevents: blocking a correct deck whose units live in the axis label rather than in
    # the cell, which is how charts and tables are actually written and which the dropped
    # verbatim branch used to carry by accident.
    #
    # It runs **only from bare to qualified, never the other way and never between two
    # different units**: `40%` against a span saying `40 ms` stays blocked, because a slide
    # that supplies a unit the source does not is asserting something the source does not
    # say. And it is advisory-reported on every hit, which is the whole licence it has to
    # be wider than the key intersection at all.
    bare_values = {value for value, unit in numeral.forms if not unit}
    if bare_values:
        unqualified = [
            (c, shared)
            for c, forms, alt in citation_forms
            if (shared := {key for key in (forms | alt) if key[0] in bare_values})
        ]
        if unqualified:
            span_key = _preferred_key(unqualified[0][1])
            return NumeralMatch(
                numeral=numeral,
                source="citation",
                detail=(
                    f"matches {_citation_label(unqualified[0][0])} on value only — the span "
                    f"qualifies it as {span_key[1]!r} and the text does not"
                ),
                location=location,
                via_unqualified_form=True,
                other_sources=tuple(_citation_label(c) for c, _ in unqualified[1:]),
                matched_on=(span_key[0], ""),
            )
    return None


def _preferred_key(shared: frozenset[NormalKey] | set[NormalKey]) -> NormalKey:
    """One key out of an intersection, chosen deterministically.

    Which key is reported changes nothing about whether the match happened — the set is
    non-empty either way — but a match that reported a different key run to run would make
    the floor test flap, and a flapping invariant test is one somebody eventually deletes.
    """
    return min(shared, key=lambda key: (key[0], key[1]))


def _match_against_derivations(
    numeral: Numeral, derivations: Sequence[Derivation], location: str
) -> NumeralMatch | None:
    """Match a numeral to a derivation's stated result or to one of its input values.

    A result **may** be matched against its rounded form, and an input may not. The
    asymmetry is the point: a derived figure is computed here and rounding it for a slide is
    the writer's own arithmetic, shown in the audit report. An input was copied from a span,
    so a rounded input is a numeral that no source contains.

    The rounding tolerance is `ROUNDING_REL_LIMIT`, the same bound `re_execute_derivation`
    puts on the other rounding path in this module. It used to be unbounded here, which
    meant a derivation computing 0.51 could be printed as `1x` — a +96% drift — with
    `passes=True` and no finding of any severity, while the citation path next door
    correctly blocked `about 30ms` against a span reading `29ms`, a drift of 3.4%.

    A rounded match is also **reported**, as `printed figure is a rounding`. It was silent
    before, which hid a legitimate rounding from the one reader who needs it: the figure on
    the slide is not the figure the arithmetic produced.

    **An input match compares the unit**, as the two branches above it always did. It used
    to compare values alone, so a derivation `(b - a) / b * 100` with `a=40.0` cited to
    *"generates at 40 ms per token"* let a slide print `Latency improves by 40%.`,
    `A 40x improvement.` or `It costs $100 per month.` — each one A2-green with no finding.
    `UNIT_TABLE`'s own justification for the `usd` row reads *"Currency is a unit: 3.2
    million dollars must not match 3.2 million requests."* That branch did precisely that.

    `DerivationInput` records a value and a citation and **no unit** — see B13 — so there
    is no field to compare. The unit is not missing, though: it is in the span the input
    cites, which is the only place it was ever written down, and `input_keys` reads it back
    out. An input whose span writes the value bare therefore has the *empty* unit and is
    matched only by a bare numeral. "No unit declared" never becomes "matches any unit",
    which is this bug with an extra step.
    """
    for derivation in derivations:
        unit = _canonical_unit(derivation.unit)
        for key in sorted(numeral.forms, key=lambda k: (k[0], k[1])):
            if key == (Decimal(str(derivation.result)), unit):
                return NumeralMatch(
                    numeral=numeral,
                    source="derivation_result",
                    detail=f"the stated result of {derivation.formula!r}",
                    location=location,
                    matched_on=key,
                )
        for key in sorted(numeral.forms, key=lambda k: (k[0], k[1])):
            value, key_unit = key
            if key_unit != unit:
                continue
            places = _places_of(value)
            if Decimal(str(round(derivation.result, places))) != value:
                continue
            # Prevents: 0.51 printed as `1x`, a +96% drift, passing A2 in silence.
            # Rounding to zero decimal places is a very coarse operation and `round()`
            # alone says nothing about how far it moved — 1.49 and 1.51 both round to
            # something, and one of them is a third of the way to a different claim.
            # `ROUNDING_REL_LIMIT` already bounds the other rounding path in this module
            # (`re_execute_derivation`); two rounding paths answering differently is not a
            # tolerance, it is a route. Beyond this distance it is a different number.
            drift = _relative_difference(float(derivation.result), float(value))
            if drift > ROUNDING_REL_LIMIT:
                continue
            return NumeralMatch(
                numeral=numeral,
                source="derivation_result",
                detail=(
                    f"the result of {derivation.formula!r} ({derivation.result!r}) "
                    f"rounded to {places} decimal place(s) — {drift:.1%} from the "
                    "computed figure"
                ),
                location=location,
                via_rounding=True,
                matched_on=key,
            )
        for name, item in sorted(derivation.inputs.items()):
            # Prevents: a millisecond figure being reprinted as a percentage, a throughput,
            # a multiplier or a sum of money. This compared values only and discarded the
            # unit, unlike the citation branch and unlike the result branch directly above.
            shared = input_keys(item) & numeral.forms
            if shared:
                key = _preferred_key(shared)
                return NumeralMatch(
                    numeral=numeral,
                    source="derivation_input",
                    detail=(
                        f"input {name!r} of {derivation.formula!r}, which the span it "
                        f"cites writes as {key[1] or 'a bare number'}"
                    ),
                    location=location,
                    matched_on=key,
                )
    return None


def _places_of(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return max(0, -int(exponent)) if isinstance(exponent, int) else 0


def _canonical_unit(unit: str) -> str:
    """The derivation's declared unit, through the same table the text goes through."""
    folded = unit.strip().casefold()
    if not folded:
        return ""
    rule = _UNIT_BY_SURFACE.get(folded)
    return rule.canonical if rule else folded


def _citation_label(citation: Citation) -> str:
    return f"{citation.doc_id} p.{citation.page}"


# ---------------------------------------------------------------------------
# The core, and the two entry points
# ---------------------------------------------------------------------------


def lint_scope(
    scope: LintScope, *, allow: Sequence[AllowedNumeral] = ALLOWLIST
) -> NumericReport:
    """Run A2 over one piece of text and the evidence in force over it.

    Three passes, deliberately in this order: re-execute every derivation, extract every
    numeral, match what was extracted. Re-execution runs first because its findings stand
    whether or not the text mentions the result at all — a derivation the writer computed
    and then did not use is still wrong arithmetic in the IR, and it would reach the audit
    report.
    """
    report = NumericReport()

    for derivation in scope.derivations:
        report.derivations_checked += 1
        report.findings.extend(check_derivation_inputs(derivation, location=scope.location))
        report.findings.extend(
            check_derivation_reconciles_sources(derivation, location=scope.location)
        )
        report.findings.extend(re_execute_derivation(derivation, location=scope.location))

    numerals = extract_numerals(scope.text)
    report.numerals_checked = len(numerals)
    matches, unmatched = match_numerals(
        numerals,
        citations=scope.citations,
        derivations=scope.derivations,
        allow=allow,
        location=scope.location,
    )
    report.matches.extend(matches)

    report.findings.extend(
        NumericFinding(
            check="uncited numeral",
            severity="blocking",
            detail=(
                f"{numeral.describe()} appears in the text but in no cited span and in no "
                "declared derivation. A2 requires every number to be copied from a source "
                "or computed from cited inputs with the working shown."
            ),
            location=scope.location,
        )
        for numeral in unmatched
    )
    report.findings.extend(_ambiguity_findings(matches, scope.location))
    return report


def _ambiguity_findings(matches: Sequence[NumeralMatch], location: str) -> list[NumericFinding]:
    """Advisories for the four ways a match can be true without being decisive.

    Both are escalation triggers in the phase brief rather than failures, and both are
    aggregated into one finding each so that a long slide does not bury its blocking
    findings under per-numeral noise.
    """
    findings: list[NumericFinding] = []

    ambiguous = [m for m in matches if m.via_ambiguous_form]
    if ambiguous:
        findings.append(
            NumericFinding(
                check="locale-ambiguous numeral",
                severity="advisory",
                detail=(
                    f"{', '.join(m.numeral.describe() for m in ambiguous)} matched only under "
                    "the minority reading of a separator ('1,234' as 1.234, or a day/month "
                    "order). The figure may be right; nothing in the text says so."
                ),
                location=location,
            )
        )

    rounded = [m for m in matches if m.via_rounding]
    if rounded:
        findings.append(
            NumericFinding(
                check="printed figure is a rounding",
                severity="advisory",
                detail=(
                    "; ".join(f"{m.numeral.describe()} is {m.detail}" for m in rounded)
                    + ". Within ROUNDING_REL_LIMIT, so A2 holds — but the figure on the "
                    "slide is not the figure the arithmetic produced, and a reader who "
                    "cannot see that cannot check it. This is what A6's 'show the working' "
                    "section exists for."
                ),
                location=location,
            )
        )

    unqualified = [m for m in matches if m.via_unqualified_form]
    if unqualified:
        findings.append(
            NumericFinding(
                check="numeral matched without its unit",
                severity="advisory",
                detail=(
                    "; ".join(f"{m.numeral.describe()} → {m.detail}" for m in unqualified)
                    + ". The value is in the span, so A2 holds — but the unit came from the "
                    "source rather than from the text, and a bare figure on a slide is one "
                    "axis label away from meaning something else. The only match in this "
                    "module wider than a shared (value, unit) key, and it is reported every "
                    "time precisely because it is wider."
                ),
                location=location,
            )
        )

    several = [m for m in matches if m.other_sources]
    if several:
        findings.append(
            NumericFinding(
                check="numeral matches several spans",
                severity="advisory",
                detail=(
                    "; ".join(
                        f"{m.numeral.describe()} → {m.detail}, also "
                        f"{', '.join(m.other_sources)}"
                        for m in several
                    )
                    + ". A2 is satisfied either way — the number was copied — but which span "
                    "it was copied from is not determined, so the audit report cannot say. "
                    "Phase brief escalation trigger."
                ),
                location=location,
            )
        )
    return findings


def lint_scopes(
    scopes: Iterable[LintScope], *, allow: Sequence[AllowedNumeral] = ALLOWLIST
) -> NumericReport:
    """Run `lint_scope` over many scopes into one report."""
    report = NumericReport()
    for scope in scopes:
        report.extend(lint_scope(scope, allow=allow))
    return report


def lint_deck(deck: Deck, *, allow: Sequence[AllowedNumeral] = ALLOWLIST) -> NumericReport:
    """Entry point one: A2 over a deck's IR text.

    Uses `Slide.all_blocks()`, so **speaker notes are linted exactly like slide faces**.
    INVARIANTS says notes are the most common place for an uncited number to hide, and a
    linter that iterated `slide.blocks` would be blind to precisely that.
    """
    return lint_scopes(_deck_scopes(deck), allow=allow)


def _deck_scopes(deck: Deck) -> list[LintScope]:
    scopes: list[LintScope] = []
    for slide in deck.slides:
        face_ids = {block.id for block in slide.blocks}
        for block in slide.all_blocks():
            where = "notes" if block.id not in face_ids else "slide"
            location = f"slide {slide.id} / {where} block {block.id}"
            if block.claim is not None:
                scopes.append(
                    LintScope(
                        location=location,
                        text=block.claim.text,
                        citations=tuple(block.claim.citations),
                        derivations=(
                            (block.claim.derivation,) if block.claim.derivation else ()
                        ),
                    )
                )
            if block.text:
                scopes.append(LintScope(location=location, text=block.text))
            if block.chart is not None:
                scopes.append(
                    LintScope(
                        location=f"{location} / chart",
                        text=_chart_text(block.chart),
                        citations=tuple(block.chart.source_citations),
                    )
                )
            if block.figure is not None and block.figure.caption:
                scopes.append(
                    LintScope(
                        location=f"{location} / caption",
                        text=block.figure.caption,
                        citations=(block.figure.citation,),
                    )
                )
            if block.diagram is not None:
                scopes.extend(_diagram_scopes(block.diagram, location))
    return scopes


def _diagram_scopes(diagram: DiagramSpec, location: str) -> list[LintScope]:
    """One scope per diagram label, against that node's own claim if it has one.

    A diagram node is the other place A2 can be walked around: `DiagramNode.claim` is
    optional, so a label reading "95% of memory" with `claim=None` carries a number and no
    evidence, on a slide whose other blocks are all perfectly cited. The IR already says the
    diagram engine is not a loophole in A1; this is the same sentence about A2.

    Labels are scoped one at a time rather than joined, so a finding names the node.
    """
    scopes: list[LintScope] = []
    if diagram.title:
        scopes.append(LintScope(location=f"{location} / diagram title", text=diagram.title))
    for node in diagram.nodes:
        claim = node.claim
        scopes.append(
            LintScope(
                location=f"{location} / diagram node {node.id}",
                text=node.label,
                citations=tuple(claim.citations) if claim else (),
                derivations=(claim.derivation,) if claim and claim.derivation else (),
            )
        )
        if claim is not None and claim.text != node.label:
            scopes.append(
                LintScope(
                    location=f"{location} / diagram node {node.id} claim",
                    text=claim.text,
                    citations=tuple(claim.citations),
                    derivations=(claim.derivation,) if claim.derivation else (),
                )
            )
    scopes.extend(
        LintScope(
            location=f"{location} / diagram edge {edge.source}->{edge.target}",
            text=edge.label,
        )
        for edge in diagram.edges
        if edge.label
    )
    return scopes


def _chart_text(chart: object) -> str:
    """Chart labels and values as text, so a chart is not a hole in A2.

    D10 makes a chart a dense set of factual assertions. Its categories and series values
    are numerals like any other and its `source_citations` are the evidence in force over
    them, so it goes through the same scope as prose rather than through a special case.
    """
    parts: list[str] = []
    title = getattr(chart, "title", None)
    if title:
        parts.append(str(title))
    parts.extend(str(category) for category in getattr(chart, "categories", ()))
    parts.extend(
        str(label)
        for label in (
            getattr(chart, "x_axis_label", None),
            getattr(chart, "y_axis_label", None),
        )
        if label
    )
    for series in getattr(chart, "series", ()):
        parts.append(str(getattr(series, "name", "")))
        parts.extend(repr(value) for value in getattr(series, "values", ()))
    return " ".join(part for part in parts if part)


def lint_rendered_slides(
    deck: Deck,
    rendered_text: Mapping[str, str],
    *,
    allow: Sequence[AllowedNumeral] = ALLOWLIST,
) -> NumericReport:
    """Entry point two: A2 over text extracted from a rendered deck (Phase 3b).

    The evidence in force over a rendered slide is everything cited anywhere on that slide,
    faces and notes together — the render has flattened the block boundaries, so the linter
    cannot and must not pretend to know which citation covers which sentence. That makes
    this pass strictly weaker than `lint_deck` at attribution and exactly as strong at its
    real job, which is catching a numeral that reached the page without reaching the IR:
    a component that formatted a figure, a template with a number baked into it, a label
    the renderer invented.

    Raises:
        KeyError: `rendered_text` names a slide the deck does not contain. Linting rendered
            text against the wrong deck would produce a confident, meaningless report.
    """
    by_id = {slide.id: slide for slide in deck.slides}
    unknown = sorted(set(rendered_text) - set(by_id))
    if unknown:
        raise KeyError(
            f"rendered text names slide(s) {', '.join(unknown)}, which are not in deck "
            f"{deck.run_id!r} v{deck.version}"
        )

    scopes: list[LintScope] = []
    for slide_id, text in rendered_text.items():
        slide = by_id[slide_id]
        citations: list[Citation] = []
        derivations: list[Derivation] = []
        for block in slide.all_blocks():
            if block.claim is not None:
                citations.extend(block.claim.citations)
                if block.claim.derivation is not None:
                    derivations.append(block.claim.derivation)
            if block.chart is not None:
                citations.extend(block.chart.source_citations)
            if block.figure is not None:
                citations.append(block.figure.citation)
            if block.diagram is not None:
                for node in block.diagram.nodes:
                    if node.claim is not None:
                        citations.extend(node.claim.citations)
                        if node.claim.derivation is not None:
                            derivations.append(node.claim.derivation)
        scopes.append(
            LintScope(
                location=f"slide {slide_id} (rendered)",
                text=text,
                citations=tuple(citations),
                derivations=tuple(derivations),
            )
        )
    # Derivations were already re-executed by `lint_deck`; re-running them here would double
    # every arithmetic finding in a full build. The rendered pass exists to catch numerals,
    # so it carries derivations for *matching* only.
    report = NumericReport()
    for scope in scopes:
        numerals = extract_numerals(scope.text)
        report.numerals_checked += len(numerals)
        matches, unmatched = match_numerals(
            numerals,
            citations=scope.citations,
            derivations=scope.derivations,
            allow=allow,
            location=scope.location,
        )
        report.matches.extend(matches)
        report.findings.extend(
            NumericFinding(
                check="uncited numeral",
                severity="blocking",
                detail=(
                    f"{numeral.describe()} is on the rendered slide but traces to nothing in "
                    "the IR for that slide. A number that appears only after rendering was "
                    "never written by the content agent and was never validated."
                ),
                location=scope.location,
            )
            for numeral in unmatched
        )
        report.findings.extend(_ambiguity_findings(matches, scope.location))
    return report
