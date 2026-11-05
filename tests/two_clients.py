"""A two-client world for the A4 regression (`test_multi_client_regression.py`), offline.

One shared project, two clients, and **one canary token per client-scoped surface**, so a
failure names the surface that leaked and the client it leaked into. Every model role the
builds use is wrapped in a recorder that keeps the full text of every request; every file a
build writes can be read back and scanned.

`CLIENT_SURFACES` is the extension point: 4.1 (onboarding, reference-profile files) and 4.2
(reference decks) add a `Surface` here and every regression test iterates it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pptx import Presentation
from typer.testing import CliRunner

import autodeck.providers.registry as registry_module
from autodeck.agents.compose import ComposedSlide
from autodeck.agents.content import ProposedBlock, ProposedCitation, ProposedClaim
from autodeck.agents.validation import ClaimJudgement, ValidationDraft
from autodeck.agents.workspace import DeckBriefDraft
from autodeck.audit.verdicts import VerdictJudgement
from autodeck.cli import app
from autodeck.ingest.document_store import Document, DocumentStore
from autodeck.ingest.transcript_source import transcript_doc_id
from autodeck.render import draft as draft_module
from autodeck.render.qa.libreoffice import RenderError
from tests.test_cli_draft import (
    CLARIFIED,
    COMPOSED,
    AgentComposer,
    Counting,
    Judge,
    agent_brief,
    agent_turn,
    quote_slide,
)
from tests.test_cli_gate2 import DOC_ID, QUOTE, element
from tests.test_knowledge import CLAIMS_MD
from tests.test_meeting_cli_wiring import QUOTE as MEETING_QUOTE
from tests.test_meeting_notes_cli import notes_script
from tests.test_transcript_source import make_transcript

runner = CliRunner()

PROJECT = "p-shared"
ALPHA = "alpha-co"
BETA = "beta-co"
CLIENTS = (ALPHA, BETA)
TAGS = {ALPHA: "ALPHA", BETA: "BETA"}
OWNER_CANARY = "OWNER-STYLE-55aa"
SHARED_CANARY = "SHARED-PROJECT-aa01"
THEME_HEX = {ALPHA: "A11CE0", BETA: "BEE7A0"}  # bare RRGGBB: valid palette values

READ_COLD = {
    "question": "Read cold.",
    "slide_ids": ["all"],
    "headlines_only": True,
    "include_notes": False,
    "skills": [],
    "pages": [],
}


def other(client: str) -> str:
    return BETA if client == ALPHA else ALPHA


def canary(client: str, key: str) -> str:
    """`ALPHA-VALUEPROP-3c1f`: the client's tag, the surface, four hex digits of a hash."""
    tag = TAGS[client]
    return f"{tag}-{key}-{hashlib.sha1(f'{tag}{key}'.encode()).hexdigest()[:4]}"


# -- the surfaces ----------------------------------------------------------------------


@dataclass(frozen=True)
class Surface:
    """One client-scoped file the loader or a build reads (or will read).

    `keys` are the canaries `render` writes into it. `consumed_by` names the builds whose
    model requests must carry it today (`B1` one-shot, `B2` agent, `B3` meeting); an empty set
    means no build reads it yet, so the regression pins its isolation at the loader and
    assembler instead and the lead moves it when a task wires it in.
    """

    name: str
    path: str
    keys: tuple[str, ...]
    render: Callable[[str], str | bytes]
    consumed_by: frozenset[str] = frozenset()
    note: str = ""
    key_builds: dict[str, frozenset[str]] = field(default_factory=dict)
    """Per-key override of `consumed_by`, for a surface whose parts travel differently."""

    def builds_for(self, key: str) -> frozenset[str]:
        return self.key_builds.get(key, self.consumed_by)


def _md(*keys: str, prose: str) -> Callable[[str], str]:
    def render(client: str) -> str:
        return f"# {client}\n\n{prose} " + " ".join(canary(client, k) for k in keys) + "\n"

    return render


def _headers(client: str) -> str:
    return (
        "style: assertion\nmax_words: 12\nhedges:\n  - as measured\navoid:\n"
        f"  - {canary(client, 'HEADER')}\n"
    )


def _tokens(client: str) -> str:
    """A loadable `DesignTokens`: the canary is its name, the client's colour its accent."""
    return json.dumps(
        {
            "name": canary(client, "THEME"),
            "palette": {"accent1": THEME_HEX[client], "hyperlink": THEME_HEX[client]},
            "typography": {"major": "Carlito", "minor": "Carlito"},
        },
        indent=2,
    )


def _memory(client: str) -> str:
    return (
        f"# Memory: {client} / {PROJECT}\n\n"
        f"## Terms\n- {canary(client, 'MEMTERM')} - a coined term (run old)\n\n"
        f"## People\n- {canary(client, 'MEMPERSON')} - the sponsor (run old)\n\n"
        f"## Open actions\n\n"
        f"## Decisions\n- {canary(client, 'MEMDECISION')}: keep the deck short (run old)\n\n"
        "## Deck preferences\n"
    )


def _deck(client: str) -> bytes:
    import io

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = canary(client, "DECK")
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


ALL_BUILDS = frozenset({"B1", "B2", "B3"})
AGENT_BUILDS = frozenset({"B2", "B3"})

CLIENT_SURFACES: list[Surface] = [
    Surface(
        "client.md",
        "client.md",
        ("CLIENTMD",),
        _md("CLIENTMD", prose="Who the client is."),
        ALL_BUILDS,
    ),
    Surface(
        "value_prop.md",
        "value_prop.md",
        ("VALUEPROP",),
        _md("VALUEPROP", prose="How this client likes to be positioned."),
        ALL_BUILDS,
    ),
    Surface(
        "engagements/2026-q1.md",
        "engagements/2026-q1.md",
        ("ENGAGEMENT",),
        _md("ENGAGEMENT", prose="Q1 notes."),
        ALL_BUILDS,
    ),
    Surface("style/headers.yaml", "style/headers.yaml", ("HEADER",), _headers, ALL_BUILDS),
    Surface(
        "memory/p-shared.md",
        f"memory/{PROJECT}.md",
        ("MEMTERM", "MEMPERSON", "MEMDECISION"),
        _memory,
        AGENT_BUILDS,
        note="Terms also reach the validator in every build (validation-terms).",
        key_builds={"MEMTERM": ALL_BUILDS},
    ),
    Surface(
        "theme/tokens.json",
        "theme/tokens.json",
        ("THEME",),
        _tokens,
        note="Read by every build that draws (4.1): with no `--tokens`, a build loads its "
        "client's own tokens. Asserted in tests/test_onboard.py (the tokens path in each "
        "deck's `theme_ref`, never the other client's); not a prompt surface, so no `req`.",
    ),
    Surface(
        "decks/past.pptx",
        "decks/past.pptx",
        ("DECK",),
        _deck,
        note="Not read by any build yet (4.2). Pinned at `reference_decks` until then.",
    ),
]
"""**Extension point.** Add a `Surface` per new client-scoped file; the fixture writes it for
both clients and the regression tests iterate it."""


def surface_canaries(client: str) -> list[str]:
    return [canary(client, key) for surface in CLIENT_SURFACES for key in surface.keys]


RUN_LOCAL_KEYS = ("TRANSCRIPT", "PROMPT")


def client_canaries(client: str) -> list[str]:
    """Everything that must never be seen by the *other* client's build."""
    return [
        *surface_canaries(client),
        *(canary(client, key) for key in RUN_LOCAL_KEYS),
        canary(client, "NEWTERM"),
        THEME_HEX[client],
    ]


def build_two_client_root(root: Path) -> Path:
    """`knowledge/` with one shared project and two canary-bearing clients."""
    knowledge = root / "knowledge"
    project = knowledge / "projects" / PROJECT
    (project / "papers").mkdir(parents=True)
    (project / "project.md").write_text(
        f"Efficiency of attention kernels. {SHARED_CANARY}\n", encoding="utf-8"
    )
    (project / "claims.md").write_text(CLAIMS_MD, encoding="utf-8")
    (project / "papers" / "kaplan2024.pdf").write_bytes(b"%PDF-1.5 stub")
    for client in CLIENTS:
        base = knowledge / "clients" / client
        for surface in CLIENT_SURFACES:
            path = base / surface.path
            path.parent.mkdir(parents=True, exist_ok=True)
            content = surface.render(client)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
    return knowledge


# -- recording -------------------------------------------------------------------------


@dataclass
class Request:
    run: str
    role: str
    kind: str
    text: str


class Recorder:
    """A role's fake with every request's full text kept: system, prompt, every message,
    tool call arguments and tool results."""

    def __init__(self, role: str, inner: Any, world: TwoClientWorld) -> None:
        self.role, self.inner, self.world = role, inner, world

    def _note(self, kind: str, *parts: str | None) -> None:
        text = "\n".join(p for p in parts if p)
        self.world.requests.append(Request(self.world.label, self.role, kind, text))

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self._note("complete_structured", system, prompt)
        return self.inner.complete_structured(prompt, response_model, system=system)

    def complete(self, prompt, *, system=None):  # type: ignore[no-untyped-def]
        self._note("complete", system, prompt)
        return self.inner.complete(prompt, system=system)

    def converse(self, messages, tools, *, system=None):  # type: ignore[no-untyped-def]
        parts: list[str | None] = [system]
        parts += [f"[tool {t.name}] {t.description}" for t in tools]
        for message in messages:
            parts.append(message.content)
            parts += [json.dumps(c.arguments, default=str) for c in message.tool_calls]
        self._note("converse", *parts)
        return self.inner.converse(messages, tools, system=system)


class MeetingJudge:
    """Supports every claim named in the prompt, quoting the meeting."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        ids = [c for c in ("s1:b1", "s2:b1") if c in prompt]
        verdict = VerdictJudgement(
            verdict="supported", verdict_notes="said", supporting_quote=MEETING_QUOTE
        )
        return ValidationDraft(
            judgements=[ClaimJudgement(claim_id=i, judgement=verdict) for i in ids]
        )


def _meeting_slide(sid: str, doc: str, text: str) -> dict[str, Any]:
    cite = [ProposedCitation(doc_id=doc, quote=MEETING_QUOTE)]
    slide = ComposedSlide(
        id=sid,
        narrative_role="evidence",
        component="quote",
        intent=f"Land {sid}.",
        message_ids=["km1"],
        blocks=[
            ProposedBlock(
                id=bid, kind="claim", slot=slot, claim=ProposedClaim(text=text, citations=cite)
            )
            for bid, slot in (("b1", "headline"), ("b2", "quote"))
        ]
        + [ProposedBlock(id="b3", kind="framing", slot="attribution", text="The meeting")],
        speaker_notes=[],
    )
    return {"slide": slide.model_dump(mode="json")}


def _meeting_transcript(client: str):  # type: ignore[no-untyped-def]
    return make_transcript(
        (12.5, 20.0, "Good morning everyone.", "S1"),
        (31.0, 39.0, "The pilot goes live  in the first\nweek of February.", "S2"),
        (777.7, 790.0, "Shikha will run the walkthrough.", "S1"),
        (800.0, 810.0, f"We also noted {canary(client, 'TRANSCRIPT')} for the record.", "S1"),
    )


@dataclass
class Build:
    client: str
    kind: str
    run_id: str


@dataclass
class TwoClientWorld:
    """Knowledge, corpus, runs and owner memory in a tmp folder, with recording providers."""

    root: Path
    mp: pytest.MonkeyPatch
    requests: list[Request] = field(default_factory=list)
    outputs: list[tuple[str, str]] = field(default_factory=list)
    caches: list[tuple[str, str, Path]] = field(default_factory=list)
    builds: list[Build] = field(default_factory=list)
    label: str = ""
    roles: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.knowledge = build_two_client_root(self.root)
        self.corpus = self.root / "corpus"
        self.runs = self.root / "runs"
        self.owner_file = self.root / "owner" / "owner.md"
        self.owner_file.parent.mkdir(parents=True)
        self.owner_file.write_text(
            f"# Memory: how I like to work\n\n## Note style\n- {OWNER_CANARY}\n\n"
            "## Deck habits\n",
            encoding="utf-8",
        )
        self.mp.setenv("AUTODECK_OWNER_MEMORY", str(self.owner_file))
        DocumentStore(self.corpus / PROJECT).add(
            Document(
                doc_id=DOC_ID,
                source_path=f"{DOC_ID}.pdf",
                page_count=6,
                elements=[element(DOC_ID, QUOTE)],
            )
        )

        def provider_for(registry, role, **kw):  # type: ignore[no-untyped-def]
            self.caches.append((self.label, role, kw.get("cache")))  # type: ignore[arg-type]
            return Recorder(role, self.roles[role], self)

        self.mp.setattr(registry_module.ModelRegistry, "provider_for", provider_for)

        def build(deck, tokens, out_path):  # type: ignore[no-untyped-def]
            presentation = Presentation()
            for _ in deck.slides:
                presentation.slides.add_slide(presentation.slide_layouts[6])
            presentation.save(str(out_path))
            return {}

        self.mp.setattr(draft_module, "_build_pptx", build)
        self.mp.setattr(
            draft_module, "render_pptx", lambda *a, **k: (_ for _ in ()).throw(RenderError("x"))
        )

    # -- driving the CLI ---------------------------------------------------------------

    @property
    def roots(self) -> list[str]:
        return ["--runs-root", str(self.runs)]

    @property
    def data_roots(self) -> list[str]:
        return [
            *self.roots,
            "--knowledge-root",
            str(self.knowledge),
            "--corpus-root",
            str(self.corpus),
        ]

    def cli(self, *args: str, ok: bool = True):  # type: ignore[no-untyped-def]
        result = runner.invoke(app, list(args))
        self.outputs.append((f"{self.label}: {' '.join(args[:2])}", result.output))
        if ok:
            assert result.exit_code == 0, f"{args}: {result.output}"
        return result

    def begin(self, client: str, kind: str) -> Build:
        run_id = f"{kind.lower()}-{client}"
        self.label = run_id
        build = Build(client, kind, run_id)
        self.builds.append(build)
        return build

    def prompt(self, client: str) -> str:
        goal = "Show that the kernel rewrite raised training throughput."
        return f"{goal} {canary(client, 'PROMPT')}"

    # -- B1: draft-first one-shot ------------------------------------------------------

    def start_b1(self, client: str) -> Build:
        """clarify and answer, with fresh scripted providers for the compose that follows."""
        build = self.begin(client, "B1")
        self.roles = {
            "composer": Counting(CLARIFIED, COMPOSED),
            "validation": Judge(),
            "advisor": Counting(),
        }
        self.cli("clarify", build.run_id, "--client", client, "--project", PROJECT,
                 "--prompt", self.prompt(client), *self.data_roots)  # fmt: skip
        self.cli("answer", build.run_id, "--accept-all", *self.roots)
        return build

    def b1(self, client: str) -> Build:
        build = self.start_b1(client)
        self.cli("draft", build.run_id, *self.data_roots)
        self.cli("validate", build.run_id, "--corpus-root", str(self.corpus), *self.roots,
                 "--knowledge-root", str(self.knowledge))  # fmt: skip
        self.cli("preview", build.run_id, *self.roots)
        self.cli("gate2", build.run_id, *self.roots, ok=False)
        return build

    # -- B2: agent draft, reading and writing memory ------------------------------------

    def b2(self, client: str) -> Build:
        build = self.begin(client, "B2")
        composer = AgentComposer(CLARIFIED)
        self.roles = {
            "composer": composer,
            "validation": Judge(),
            "advisor": Counting(),
        }
        self.cli("clarify", build.run_id, "--client", client, "--project", PROJECT,
                 "--prompt", self.prompt(client), *self.data_roots)  # fmt: skip
        self.cli("answer", build.run_id, "--accept-all", *self.roots)
        composer.turns = [
            agent_turn("read_memory", 1, scope="engagement"),
            agent_turn(
                "remember",
                2,
                scope="engagement",
                section="Terms",
                text=f"{canary(client, 'NEWTERM')} - coined during this build",
                replaces="",
            ),
            agent_turn("set_brief", 3, **agent_brief(2)),
            agent_turn("read_passage", 4, doc_id=DOC_ID, page=4),
            agent_turn(
                "write_slide",
                5,
                **quote_slide("s1", "The rewrite raised throughput, per the paper."),
            ),
            agent_turn("ask_advisor", 6, **READ_COLD),
            agent_turn("finish", 7, coverage=[], notes="Drafted by the agent."),
        ]
        self.cli("draft", build.run_id, "--agent", *self.data_roots)
        self.cli("validate", build.run_id, "--corpus-root", str(self.corpus), *self.roots,
                 "--knowledge-root", str(self.knowledge))  # fmt: skip
        composer.turns = [
            agent_turn(
                "write_slide", 8, **quote_slide("s1", "The rewrite raised speed, per it.")
            ),
            agent_turn("finish", 9, coverage=[], notes="Reworded slide one."),
        ]
        self.cli(
            "revise", build.run_id, "--instruction", "Reword it.", "--agent", *self.data_roots
        )
        self.cli("preview", build.run_id, *self.roots)
        return build

    # -- B3: a meeting, to notes, to a deck -----------------------------------------------

    def start_b3(self, client: str) -> Build:
        """A meeting run with its transcript and sourced, ready for `meeting notes`."""
        build = self.begin(client, "B3")
        composer = AgentComposer(CLARIFIED)
        self.roles = {
            "composer": composer,
            "validation": MeetingJudge(),
            "advisor": Counting(),
        }
        meeting = self.runs / build.run_id / "meeting"
        _meeting_transcript(client).save(meeting)
        settings = {"audio_name": "board.m4a", "audio_sha256": "ab" * 32, "speakers": False,
                    "num_speakers": None, "client": client, "project": PROJECT}  # fmt: skip
        (meeting / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        self.cli("meeting", "source", build.run_id, *self.roots)
        return build

    def b3(self, client: str) -> Build:
        build = self.start_b3(client)
        composer: AgentComposer = self.roles["composer"]
        composer.turns = notes_script()
        self.cli("meeting", "notes", build.run_id, *self.data_roots)
        self.cli("clarify", build.run_id, "--client", client, "--project", PROJECT,
                 "--prompt", self.prompt(client), "--provenance", "strict",
                 *self.data_roots)  # fmt: skip
        self.cli("answer", build.run_id, "--accept-all", *self.roots)
        doc = transcript_doc_id(build.run_id)
        brief = DeckBriefDraft(
            objective="Report the meeting.",
            audience="The board",
            length_target=2,
            key_messages=_meeting_key_messages(doc),
            must_include=[],
            must_avoid=[],
        )
        composer.turns = [
            agent_turn("set_brief", 1, **brief.model_dump(mode="json")),
            agent_turn(
                "write_slide", 2, **_meeting_slide("s1", doc, "The rollout has a first date.")
            ),
            agent_turn("ask_advisor", 3, **READ_COLD),
            agent_turn("finish", 4, coverage=[], notes="Drafted from the meeting."),
        ]
        self.cli("draft", build.run_id, "--agent", *self.data_roots)
        self.cli("validate", build.run_id, "--corpus-root", str(self.corpus), *self.roots,
                 "--knowledge-root", str(self.knowledge))  # fmt: skip
        return build

    def all_builds(self) -> None:
        for client in CLIENTS:
            self.b1(client)
            self.b2(client)
            self.b3(client)

    # -- reading back ------------------------------------------------------------------

    def requests_for(self, client: str, kind: str | None = None) -> list[Request]:
        runs = {b.run_id for b in self.builds if b.client == client and kind in (None, b.kind)}
        return [r for r in self.requests if r.run in runs]

    def run_dirs(self, client: str) -> list[Path]:
        return [self.runs / b.run_id for b in self.builds if b.client == client]

    def written(self, client: str, kind: str | None = None) -> dict[str, str]:
        """Every text file a client's builds wrote, keyed by path, plus the text of any pptx
        (shapes and notes), the stdout of each of its commands, and its memory files."""
        out: dict[str, str] = {}
        runs = [b for b in self.builds if b.client == client and kind in (None, b.kind)]
        for run in (self.runs / b.run_id for b in runs):
            out.update(read_tree(run))
        out.update(read_tree(self.knowledge / "clients" / client / "memory"))
        for label, text in self.outputs:
            if any(label.startswith(b.run_id) for b in runs):
                out[f"stdout[{label}]"] = text
        return out


def _meeting_key_messages(doc: str):  # type: ignore[no-untyped-def]
    message = COMPOSED.key_messages[0].model_copy(deep=True)
    message.citations[0].doc_id = doc
    message.citations[0].quote = MEETING_QUOTE
    return [message]


TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".yaml", ".yml"}


def pptx_text(path: Path) -> str:
    """Shape text, tables and speaker notes of a deck, and its core properties."""
    presentation = Presentation(str(path))
    parts: list[str] = [
        str(presentation.core_properties.title or ""),
        str(presentation.core_properties.author or ""),
    ]
    for slide in presentation.slides:
        shapes = list(slide.shapes)
        if slide.has_notes_slide:
            shapes += list(slide.notes_slide.shapes)
        for shape in shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
            if getattr(shape, "has_table", False) and shape.has_table:
                parts += [c.text for row in shape.table.rows for c in row.cells]
    return "\n".join(parts)


def read_tree(root: Path) -> dict[str, str]:
    """Every text file (and the text of every pptx) beneath `root`, by path."""
    found: dict[str, str] = {}
    if not root.exists():
        return found
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix in TEXT_SUFFIXES:
            found[str(path)] = path.read_text(encoding="utf-8", errors="replace")
        elif path.suffix == ".pptx":
            found[str(path)] = pptx_text(path)
    return found


def hits(needles: Iterable[str], haystacks: dict[str, str]) -> list[tuple[str, str]]:
    """`(needle, where)` for every needle found, case-insensitively, in any haystack."""
    return [
        (needle, where)
        for where, text in haystacks.items()
        for needle in needles
        if needle.casefold() in text.casefold()
    ]


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file beneath `root`, by relative path, for an unchanged-tree assertion."""
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }
