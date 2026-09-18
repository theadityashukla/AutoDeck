"""The framing linter (A5): the exemption that pays for itself by being fenced.

A5 lets `framing` blocks carry no citation. That exemption is the only hole in A1, and it
exists for a good reason — *"serve better before you buy more"* is the argument of a deck
and there is no paper to cite for it. The whole question is what stops the hole widening.

The answer is that framing is **fenced rather than trusted**. A framing block may say
anything about the engagement and nothing about the world: no numerals, no named studies,
no comparative or superlative carrying factual content. A block that breaks the fence is
**demoted to `claim`**, and a claim with no citation cannot exist (A1), so the demotion
stops the build.

## Why demotion, rather than a warning

INVARIANTS is explicit: *"demotion must be a real state change that re-triggers A1/A3, not
a logged warning."* A warning has the wrong incentive attached — the writer who smuggled a
fact into framing gets their sentence onto the slide, and the warning is one line in a log
next to the forty lines that were fine.

**The IR cannot represent the demoted block, and that is the correct behaviour rather than
an obstacle.** `Block` requires a `Claim` for `kind="claim"`, and `Claim.citations` has
`min_length=1`, so a citation-free claim is unconstructible by design. A demoted framing
block is exactly that object. So the demotion is carried by a typed `Demotion` — which
names the new kind, keeps the text and the reasons, reports the A3 verdict the block would
carry, and whose `materialise()` raises the IR's own `ValidationError` on demand. Nothing
here relaxes the IR to make the state expressible; the inexpressibility *is* the A1 failure
the demotion is supposed to cause. `Demotion.a1_error` doubles as a tripwire: if
`Claim.citations` is ever loosened, it raises rather than returning, and this module's tests
fail before anything downstream notices.

The consequence for callers is the one thing to hold on to: a clean `Deck` is no longer
sufficient evidence that A1 holds. The render guard has to consult
`Deck.blocking_blocks()` **and** this report, because the blocks this report names are the
ones the deck could not be made to carry.

## Determinism

No model call, no retrieval, no judgement. A5 is in INVARIANTS' "transfers unchanged across
environments" group precisely because it is pattern-matching, and a model asked "does this
sentence assert a fact?" would give a different answer on `dev` than on `sit` — which is
the one thing a lint may never do.

The patterns are closed lists of *factual* language rather than grammatical detectors. That
distinction is the whole reason "the clearest way to think about this" passes and "the
fastest inference stack" does not: both are superlatives, and only one of them could be
falsified by a measurement. A `-est` detector would have to be argued down case by case
until it detected nothing.

## What it does not do

It does not rewrite the sentence, and it does not decide. `gate1.py`'s posture: findings go
to the orchestrator, and a human reads them. A demotion is not a rejection of the deck — it
is a statement that this sentence is a claim, and claims need sources.

Owning phase: 2b (task 2b.6). Opus tier — `autodeck/audit/` is a path guardrail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from autodeck.audit.numeric_linter import Numeral, extract_numerals
from autodeck.ir.models import Block, Claim, Deck, Verdict

Severity = Literal["blocking", "advisory"]


@dataclass(frozen=True)
class FramingFinding:
    """One reason a framing block is not framing.

    Same three fields as `gate1.Finding`, plus where it was found and the fragment that
    triggered it. The fragment matters more here than anywhere else in the audit subsystem:
    the fix is to rewrite one phrase, and a finding that does not quote the phrase sends the
    writer looking through a whole sentence for it.
    """

    check: str
    severity: Severity
    detail: str
    fragment: str = ""
    location: str = ""

    def __str__(self) -> str:
        marker = "BLOCKING" if self.severity == "blocking" else "advisory"
        where = f" · {self.location}" if self.location else ""
        return f"[{marker}] {self.check}{where}: {self.detail}"


# ---------------------------------------------------------------------------
# The pattern tables
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FramingPattern:
    """One kind of fabricated fact, with the reason it is one.

    Every entry carries `why` for the same reason the numeric linter's normalisation rules
    do: a pattern nobody can justify is a pattern nobody can argue with when it fires on a
    sentence that was fine, and the way that argument usually ends is with the check being
    removed.
    """

    name: str
    pattern: re.Pattern[str]
    why: str


NAMED_SOURCE_PATTERNS: tuple[FramingPattern, ...] = (
    FramingPattern(
        "author citation",
        re.compile(r"\b[A-Z][A-Za-z'\u2019-]+\s+et\s+al\.?"),
        "'Dettmers et al.' in a framing block is a citation with the citation taken out. "
        "The sentence borrows a paper's authority and gives the reader no way to check it.",
    ),
    FramingPattern(
        "attribution",
        re.compile(
            r"\b(?:according to|as reported by|as published in|published in|citing|cites)"
            r"\s+(?:the\s+)?[A-Z][A-Za-z]*"
        ),
        "'according to Nature' asserts that a named source says something. Whether it does "
        "is a fact about the world, and A1 wants the span. 'per' is deliberately not in "
        "this list: in this corpus it is distributive far more often than attributive, and "
        "'throughput per GPU' is the sentence A5 most needs to leave alone.",
    ),
    FramingPattern(
        "named study",
        re.compile(
            r"\b(?:the\s+)?(?:\d{4}\s+)?[A-Z][A-Za-z]+\s+"
            r"(?:study|studies|paper|report|trial|survey|benchmark|analysis|meta-analysis|"
            r"whitepaper)\b"
        ),
        "'the 2023 Stanford study' is INVARIANTS' own example. A named study is a source, "
        "and naming one without citing it is the most credible-sounding way to have no "
        "evidence at all.",
    ),
    FramingPattern(
        "research verb",
        re.compile(
            r"\b(?:research|studies|trials|the data|the evidence|a study|the literature)\s+"
            r"(?:show|shows|showed|suggest|suggests|demonstrate|demonstrates|prove|proves|"
            r"find|finds|confirm|confirms)\b",
            re.I,
        ),
        "'research shows' is a citation to an unnamed source: it claims a body of evidence "
        "exists without exposing any of it. Harder to check than a named study, not easier.",
    ),
    FramingPattern(
        "validation verb",
        re.compile(
            r"\b(?:clinically|scientifically|empirically|independently|externally)\s+"
            r"(?:shown|proven|proved|validated|verified|demonstrated|tested)\b",
            re.I,
        ),
        "'clinically shown' is the adversarial test from INVARIANTS. It asserts a process "
        "— a trial happened, somebody ran it — and that process is a fact with a source.",
    ),
    FramingPattern(
        "peer review",
        re.compile(r"\bpeer[-\s]reviewed\b", re.I),
        "Same shape as 'clinically shown': a claim about how the evidence was produced.",
    ),
    FramingPattern(
        "named venue or firm",
        re.compile(
            r"\b(?:Nature|Science|The Lancet|Lancet|NEJM|JAMA|arXiv|NeurIPS|ICML|ICLR|"
            r"McKinsey|Gartner|Forrester|IDC|Deloitte|Accenture|Bain|BCG|"
            r"MIT|Stanford|Harvard|Oxford|Cambridge|Berkeley)\b"
        ),
        "A journal, conference or analyst house named in framing is borrowed authority. "
        "Held as an explicit list rather than a capitalised-word heuristic, which would "
        "fire on the client's own name in every deck we write.",
    ),
)

FACTUAL_SUPERLATIVE_PATTERNS: tuple[FramingPattern, ...] = (
    FramingPattern(
        "measurable superlative",
        re.compile(
            r"\b(?:the\s+)?(?:fastest|cheapest|largest|biggest|smallest|highest|lowest|"
            r"strongest|safest|most\s+(?:accurate|efficient|advanced|effective|reliable|"
            r"scalable|performant)|best[-\s]performing)\b",
            re.I,
        ),
        "Each of these could be falsified by one measurement, which is what makes it a "
        "claim rather than a position. The list is closed on purpose: 'the clearest way to "
        "think about this' is also a superlative and nothing could measure it, so a "
        "grammatical '-est' detector would have to be argued down until it caught nothing.",
    ),
    FramingPattern(
        "market position",
        re.compile(
            r"\b(?:industry[-\s]leading|market[-\s]leading|category[-\s]leading|the leading|"
            r"best[-\s]in[-\s]class|world[-\s]class|industry standard|state[-\s]of[-\s]the"
            r"[-\s]art|number one|no\.\s?1|#1)\b",
            re.I,
        ),
        "`prompts/content.md` lists 'industry-leading' among the words that are not hedges. "
        "`value_prop.md` for Northwind names 'industry standard' as framing to avoid, in "
        "those words, because the audience will ask who says so.",
    ),
    FramingPattern(
        "unqualified proof",
        re.compile(r"\b(?:proven|guaranteed|unmatched|unrivall?ed|unbeatable)\b", re.I),
        "'proven to' is in content.md's A5 list. These assert that the question is settled, "
        "which is a claim about the evidence and therefore needs some.",
    ),
)

COMPARATIVE_PATTERNS: tuple[FramingPattern, ...] = (
    FramingPattern(
        "measured comparison",
        re.compile(
            r"\b(?:faster|cheaper|quicker|better|higher|lower|larger|smaller|stronger|"
            r"more\s+\w+|less\s+\w+|fewer\s+\w+)\s+(?:than|by)\b",
            re.I,
        ),
        "The complement is what makes the comparison factual. 'Serve better before you buy "
        "more' — the real Northwind framing — is a comparison with nothing to measure "
        "against, and it must pass untouched. 'better than their current stack' names the "
        "thing being beaten, and beating it is a measurable event.",
    ),
    FramingPattern(
        "multiplier",
        re.compile(
            r"\b(?:twice\s+(?:as|the)|three\s+times|ten\s+times|double\s+the|half\s+the|"
            r"twofold|threefold|tenfold|order of magnitude)\b",
            re.I,
        ),
        "The spec's own example is 'twice as efficient'. A multiplier is a numeral written "
        "in words, and A2 would catch it instantly if it were written in digits — so the "
        "spelling must not be what decides. Bare 'twice' is excluded: 'they have been "
        "pitched round multipliers twice' is about the engagement, not about the world.",
    ),
    FramingPattern(
        "outperformance",
        re.compile(r"\b(?:outperforms?|outperformed|superior to|beats|surpasses)\b", re.I),
        "Same shape as a measured comparison with the comparison folded into the verb.",
    ),
)

#: All three tables, in the order findings are reported. Numerals come first because a
#: numeral is the one violation A2 would also catch, and seeing both linters name the same
#: sentence is useful rather than redundant.
PATTERN_TABLES: tuple[tuple[str, tuple[FramingPattern, ...]], ...] = (
    ("named study or source", NAMED_SOURCE_PATTERNS),
    ("factual superlative", FACTUAL_SUPERLATIVE_PATTERNS),
    ("factual comparative", COMPARATIVE_PATTERNS),
)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def lint_framing_text(text: str, *, location: str = "") -> list[FramingFinding]:
    """Every way `text` fails the A5 fence. Deterministic; no model, no retrieval.

    Numerals are found with the numeric linter's own extractor rather than a second one.
    That is not only about duplication: two extractors drift, and the day they disagree is
    the day a number is *findable but uncitable* — caught by neither linter because each
    assumes the other saw it.
    """
    findings = [
        FramingFinding(
            check="numeral in framing",
            severity="blocking",
            detail=(
                f"{numeral.describe()} is a number, and framing carries no citation to "
                "trace it to. If the figure is real it belongs in a `claim` with its span; "
                "if it is illustrative it does not belong on a slide."
            ),
            fragment=numeral.text,
            location=location,
        )
        for numeral in _numerals_in(text)
    ]

    for check, table in PATTERN_TABLES:
        for entry in table:
            for match in entry.pattern.finditer(text):
                findings.append(
                    FramingFinding(
                        check=check,
                        severity="blocking",
                        detail=(
                            f"{match.group(0).strip()!r} ({entry.name}). {entry.why} "
                            "A5 fences framing rather than trusting it, so this sentence is "
                            "demoted to `claim` and needs a citation."
                        ),
                        fragment=match.group(0).strip(),
                        location=location,
                    )
                )
    return findings


def _numerals_in(text: str) -> list[Numeral]:
    """The shared extractor, unmodified.

    A5 says "no numerals" without qualification, so there is nothing to filter here — not a
    year, not a model number, not a count. A framing block has no citations at all, so every
    numeral in one is unsourced by construction; there is no case where a numeral in framing
    is fine and an exception would only be a way in.
    """
    return extract_numerals(text)


# ---------------------------------------------------------------------------
# Demotion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Demotion:
    """A framing block A5 has reclassified as a `claim`.

    **The state change the IR cannot hold.** `kind` here is `"claim"` — that is the block's
    new type, not a suggestion — but `Block` requires a `Claim` for that kind and
    `Claim.citations` has `min_length=1`, so the resulting object is unconstructible. This
    dataclass is the demoted block: it names the new kind, keeps the text and the reasons,
    and answers the two questions the render guard asks a `Block` (`blocks_render`, and the
    A3 verdict it carries).

    Calling `materialise()` performs the demotion against the real IR and raises the
    `ValidationError` A1 produces. That is the invariant firing, not an implementation
    accident, and `a1_error` captures the message so it reaches the audit report in the IR's
    own words rather than paraphrased here.
    """

    slide_id: str
    block_id: str
    slot: str
    text: str
    reasons: tuple[FramingFinding, ...]
    kind: Literal["claim"] = "claim"

    @property
    def verdict(self) -> Verdict:
        """The A3 verdict this block carries once demoted.

        A claim with no citation has nothing for the validator to re-retrieve against, so
        `unsupported` is the only verdict available — and `Claim.blocks_render` makes
        `unsupported` a bar on final render. Naming it here is what makes "demotion
        re-triggers A1/A3" a property of the object rather than a claim in a docstring.
        """
        return "unsupported"

    def blocks_render(self) -> bool:
        """True, always. Mirrors `Block.blocks_render` so a guard can treat the two alike."""
        return True

    def materialise(self) -> Block:
        """Build the demoted block against the real IR.

        Always raises. A `claim` block needs a `Claim`, and a `Claim` needs a citation this
        block does not have and — being framing — never had. The raise is the point: it is
        A1 refusing the object, in the IR's own validator, rather than this module asserting
        that A1 would have refused it.

        Raises:
            ValidationError: always, while A1 holds.
        """
        return Block(
            id=self.block_id,
            kind=self.kind,
            slot=self.slot,
            claim=Claim(text=self.text, citations=[]),
        )

    def a1_error(self) -> str:
        """The IR's own message for why the demoted block cannot exist.

        Doubles as a tripwire. If `Claim.citations` is ever relaxed, `materialise()` will
        succeed and this raises — loudly, in this module's tests — instead of the demotion
        quietly becoming a no-op that still reports itself as blocking. A1 failing silently
        is the failure mode INVARIANTS calls the worst available to this build.
        """
        try:
            self.materialise()
        except ValidationError as exc:
            return str(exc)
        raise RuntimeError(
            f"block {self.block_id!r} was demoted to 'claim' with no citation and the IR "
            "accepted it. A1 is enforced by Claim.citations' min_length=1 and something has "
            "relaxed it — every demotion in the system is now a no-op. See INVARIANTS A1."
        )

    def summary(self) -> str:
        fragments = ", ".join(sorted({r.fragment for r in self.reasons if r.fragment}))
        return (
            f"slide {self.slide_id} block {self.block_id}: framing demoted to claim "
            f"({fragments or 'see findings'})"
        )


@dataclass
class FramingReport:
    """What A5 found across a deck, and what it means for the build."""

    demotions: list[Demotion] = field(default_factory=list)
    framing_blocks_checked: int = 0

    @property
    def findings(self) -> list[FramingFinding]:
        return [reason for demotion in self.demotions for reason in demotion.reasons]

    @property
    def blocking(self) -> list[FramingFinding]:
        return [f for f in self.findings if f.severity == "blocking"]

    @property
    def advisory(self) -> list[FramingFinding]:
        return [f for f in self.findings if f.severity == "advisory"]

    @property
    def blocks_build(self) -> bool:
        """Whether any block was demoted — and therefore whether the deck can render.

        **This has to be consulted alongside `Deck.blocking_blocks()`, not instead of it.**
        A demoted block is one the IR cannot hold, so it is still sitting in the deck typed
        as `framing` and looking clean. The deck is not evidence about A5; this is.
        """
        return bool(self.demotions)

    def demotion_for(self, block_id: str) -> Demotion | None:
        return next((d for d in self.demotions if d.block_id == block_id), None)

    def render(self) -> str:
        lines = [
            "A5 — framing lint",
            f"{self.framing_blocks_checked} framing block(s) · {len(self.demotions)} demoted",
            "",
        ]
        if not self.demotions:
            lines.append("Every framing block stays on the right side of the fence.")
            return "\n".join(lines)

        for demotion in self.demotions:
            lines.append(demotion.summary())
            lines.extend(f"    {reason}" for reason in demotion.reasons)
            lines.append(f"    text: {demotion.text!r}")
        lines.extend(
            [
                "",
                "A demotion is a state change, not a warning: each block above is now a "
                "`claim` with no citation, which A1 forbids and A3 marks `unsupported`. The "
                "fix is to cite the sentence or to write it as framing — a sentence about "
                "the engagement rather than about the world.",
            ]
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def lint_block(block: Block, *, slide_id: str = "") -> Demotion | None:
    """Check one block. Returns the demotion it earned, or None.

    Non-`framing` blocks return None without being read. A5 is about the exemption, and
    running these patterns over a `claim` would demote every correctly cited sentence in the
    deck for saying 'faster than' with a span behind it.
    """
    if block.kind != "framing" or not block.text:
        return None
    location = f"slide {slide_id} block {block.id}" if slide_id else f"block {block.id}"
    reasons = lint_framing_text(block.text, location=location)
    if not reasons:
        return None
    return Demotion(
        slide_id=slide_id,
        block_id=block.id,
        slot=block.slot,
        text=block.text,
        reasons=tuple(reasons),
    )


def lint_framing(deck: Deck) -> FramingReport:
    """Run A5 over every framing block in a deck, faces and speaker notes alike.

    Uses `Slide.all_blocks()`. A framing block in the notes is exempt from A1 for the same
    reason a framing block on the face is, and it is fenced for the same reason — "nobody
    reads notes in the room" cuts both ways, and an unsourced superlative is worse in the
    place the presenter is reading from.
    """
    report = FramingReport()
    for slide in deck.slides:
        for block in slide.all_blocks():
            if block.kind != "framing":
                continue
            report.framing_blocks_checked += 1
            demotion = lint_block(block, slide_id=slide.id)
            if demotion is not None:
                report.demotions.append(demotion)
    return report
