"""`autodeck` command line — the headless entry point (D7).

v1's Streamlit state machine was a documented cost (`legacy/v1/LEGACY.md`), so v2 is
CLI-first with the review UI deferred. Every command that touches models takes `--env`,
defaulting to `dev`, and every artifact lands under `runs/<run_id>/` where it can be
inspected, diffed and resumed.

Owning phase: 0 (task 0.7); the real `plan` and `build` commands land in Phases 2a and 4.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from autodeck.audit.manifest import build_manifest
from autodeck.design.components.catalog import COMPONENT_LIB_VERSION
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import Block, Citation, Claim, Deck, DeckBrief, Slide
from autodeck.ir.store import IRStore, diff_decks
from autodeck.pipeline.orchestrator import (
    DEFAULT_RUNS_ROOT,
    STAGE_SEQUENCE,
    Gate,
    GateBlocked,
    Orchestrator,
)
from autodeck.providers.registry import ModelRegistry

if TYPE_CHECKING:
    from autodeck.audit.report import AuditReport
    from autodeck.pipeline.orchestrator import RenderSafety

app = typer.Typer(
    name="autodeck",
    help="Accuracy-first consulting decks as native, editable PPTX.",
    no_args_is_help=True,
    add_completion=False,
)

ir_app = typer.Typer(help="Inspect and diff Deck IR versions.", no_args_is_help=True)
spike_app = typer.Typer(help="GATE 0 spike artifacts.", no_args_is_help=True)
fonts_app = typer.Typer(help="Font availability checks.", no_args_is_help=True)
components_app = typer.Typer(help="Component catalog: golden previews.", no_args_is_help=True)
knowledge_app = typer.Typer(
    help="Knowledge folders and the document corpus.", no_args_is_help=True
)
app.add_typer(ir_app, name="ir")
app.add_typer(spike_app, name="spike")
app.add_typer(fonts_app, name="fonts")
app.add_typer(components_app, name="components")
app.add_typer(knowledge_app, name="knowledge")

EnvOption = Annotated[
    str, typer.Option("--env", help="Provider environment: dev, sit or prod.")
]
RunsRoot = Annotated[Path, typer.Option("--runs-root", help="Where run directories live.")]
TokensOption = Annotated[Path, typer.Option("--tokens", help="Path to a tokens.json.")]
KnowledgeRoot = Annotated[
    Path, typer.Option("--knowledge-root", help="Root of the knowledge folders.")
]
CorpusRoot = Annotated[
    Path,
    typer.Option(
        "--corpus-root",
        help="Where ingested documents are stored. Derived data — not committed.",
    ),
]

DEFAULT_KNOWLEDGE_ROOT = Path("knowledge")
DEFAULT_CORPUS_ROOT = Path("corpus")


def _echo_error(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


@app.command()
def models(env: EnvOption = "dev") -> None:
    """Show the resolved provider bindings for an environment."""
    registry = ModelRegistry.load(env)
    typer.secho(f"environment: {registry.env}", bold=True)
    for role, binding in sorted(registry.bindings().items()):
        typer.echo(f"  {role:<12} {binding.provider:<8} {binding.model}")

    missing = registry.missing_credentials()
    if missing:
        typer.secho(f"\nmissing credentials: {', '.join(missing)}", fg=typer.colors.YELLOW)

    if registry.env == "dev":
        typer.secho(
            "\nNote: A3 and A8 are model-sensitive (B8). A dev-environment accuracy result "
            "is a smoke test, not a verification — measure headline metrics on sit.",
            fg=typer.colors.YELLOW,
        )


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@app.command()
def run(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    env: EnvOption = "dev",
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
    stub: Annotated[
        bool, typer.Option("--stub", help="Run the Phase 0 stub pipeline.")
    ] = False,
) -> None:
    """Run the pipeline for `run_id`, resuming from wherever it stopped.

    The Phase 0 stub produces a versioned IR and a blank manifest, then **blocks** at the
    first human gate — which is the phase milestone.
    """
    if not stub:
        _echo_error("Only `--stub` is implemented in Phase 0. Real stages land in Phase 2a.")
        raise typer.Exit(code=2)

    orchestrator = Orchestrator(run_id, runs_root=runs_root, env=env)
    registry = ModelRegistry.load(env)

    def write_stub_ir() -> str:
        deck = _stub_deck(run_id)
        path = orchestrator.ir.save(deck, overwrite=True)
        return f"wrote {path}"

    def write_manifest() -> str:
        latest = orchestrator.ir.version_path(orchestrator.ir.latest_version() or 1)
        manifest = build_manifest(
            run_id=run_id,
            env=registry.env,
            models=registry.manifest_entry(),
            prompts_dir=Path("prompts"),
            ir_path=latest,
        )
        manifest.save(orchestrator.paths.manifest_file)
        return f"wrote {orchestrator.paths.manifest_file}"

    for stage, work in (("outline", write_stub_ir), ("audit", write_manifest)):
        ran = orchestrator.run_stage(stage, work)
        typer.echo(f"  {stage:<12} {'ran' if ran else 'skipped (already complete)'}")

    typer.echo("")
    try:
        orchestrator.require_gate(Gate.BRIEF)
    except GateBlocked as blocked:
        typer.secho(str(blocked), fg=typer.colors.YELLOW)
        raise typer.Exit(code=3) from None

    typer.secho("all gates approved", fg=typer.colors.GREEN)


def _stub_deck(run_id: str) -> Deck:
    """A minimal valid deck. Even the stub carries a citation — A1 has no exemptions."""
    citation = Citation.for_quote(
        doc_id="stub-doc",
        page=1,
        bbox=(0.0, 0.0, 100.0, 20.0),
        quote="A verbatim span from a stub source document.",
        retrieved_by="writer",
    )
    return Deck(
        run_id=run_id,
        project="stub-project",
        client="stub-client",
        audience="stub audience",
        version=1,
        theme_ref="config/tokens/dev.json",
        component_lib_version=COMPONENT_LIB_VERSION,
        slides=[
            Slide(
                id="s1",
                narrative_role="evidence",
                component="big_number",
                blocks=[
                    Block(
                        id="s1-b1",
                        kind="claim",
                        slot="figure",
                        claim=Claim(text="A cited stub assertion.", citations=[citation]),
                    )
                ],
            )
        ],
    )


@app.command()
def approve(
    run_id: Annotated[str, typer.Argument()],
    gate: Annotated[Gate, typer.Argument(help="Which A7 gate to approve.")],
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
    approver: Annotated[str, typer.Option("--by")] = "owner",
) -> None:
    """Record a human approval for one of the four A7 gates.

    Separate from `run` on purpose: there is no flag on `run` that approves a gate, and
    there must never be one.
    """
    orchestrator = Orchestrator(run_id, runs_root=runs_root)
    orchestrator.approve(gate, approver=approver)
    typer.secho(f"approved {gate.value} for {run_id}", fg=typer.colors.GREEN)

    remaining = orchestrator.pending_gates()
    if remaining:
        typer.echo(f"still pending: {', '.join(g.value for g in remaining)}")


@app.command()
def status(
    run_id: Annotated[str, typer.Argument()], runs_root: RunsRoot = DEFAULT_RUNS_ROOT
) -> None:
    """Show stage completion and gate approvals for a run."""
    orchestrator = Orchestrator(run_id, runs_root=runs_root)
    state = orchestrator.state

    typer.secho(f"run {run_id} (env={state.env})", bold=True)
    typer.echo("stages:")
    for name in STAGE_SEQUENCE:
        record = state.stages.get(name)
        typer.echo(f"  {name:<14} {record.status.value if record else 'not-started'}")

    typer.echo("gates:")
    for gate in Gate:
        approval = state.approvals.get(gate.value)
        typer.echo(f"  {gate.value:<14} {approval or 'PENDING'}")


# ---------------------------------------------------------------------------
# ir
# ---------------------------------------------------------------------------


@ir_app.command("versions")
def ir_versions(
    run_id: Annotated[str, typer.Argument()], runs_root: RunsRoot = DEFAULT_RUNS_ROOT
) -> None:
    """List the IR versions saved for a run."""
    versions = IRStore(runs_root, run_id).versions()
    typer.echo(" ".join(f"v{v}" for v in versions) if versions else "no IR versions")


@ir_app.command("diff")
def ir_diff(
    run_id: Annotated[str, typer.Argument()],
    before: Annotated[int, typer.Argument()],
    after: Annotated[int, typer.Argument()],
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
) -> None:
    """Diff two IR versions — the gate-review surface."""
    store = IRStore(runs_root, run_id)
    changes = diff_decks(store.load(before), store.load(after))
    if not changes:
        typer.echo("no changes")
        return
    for change in changes:
        typer.echo(str(change))
    typer.echo(f"\n{len(changes)} change(s)")


@ir_app.command("schema")
def ir_schema(
    flavor: Annotated[
        str, typer.Option("--flavor", help="standard, strict or gemini.")
    ] = "standard",
) -> None:
    """Print the Deck IR JSON schema in a provider dialect."""
    from autodeck.ir.schema import SchemaFlavor, export_schema

    if flavor not in ("standard", "strict", "gemini"):
        _echo_error(f"unknown flavor {flavor!r}")
        raise typer.Exit(code=2)
    schema: SchemaFlavor = flavor  # type: ignore[assignment]
    typer.echo(json.dumps(export_schema(Deck, schema), indent=2))


# ---------------------------------------------------------------------------
# fonts
# ---------------------------------------------------------------------------


@fonts_app.command("check")
def fonts_check(
    tokens: TokensOption = Path("config/tokens/aptos.json"),
    family: Annotated[
        str | None, typer.Option("--family", help="Check one family instead.")
    ] = None,
) -> None:
    """Confirm the fonts a token set declares are installed.

    Worth running before any design work: a missing family means budgets would be computed
    against a substituted face, which is the failure B11 exists to prevent.

    Reports per **face**, not per family. The component library draws bold headlines and
    italic pull-quotes, so a family present in regular alone is a family half the budgets
    cannot be computed for — and a check that only looked for the regular file is what let
    every bold budget be measured against the wrong face until 3a.6.
    """
    from autodeck.design.fonts import FontNotFoundError, resolve_face

    families = [family] if family else sorted(DesignTokens.load(tokens).typography.families())
    missing = False
    for name in families:
        for bold, italic in ((False, False), (True, False), (False, True)):
            try:
                resolved = resolve_face(name, bold=bold, italic=italic)
            except FontNotFoundError as exc:
                missing = True
                label = _face_label(bold, italic)
                typer.secho(f"  MISSING {name} ({label})", fg=typer.colors.RED)
                typer.echo(f"          {exc}")
                continue
            typer.secho(
                f"  OK      {name} ({resolved.face}) -> {resolved.path}",
                fg=typer.colors.GREEN,
            )
    if missing:
        raise typer.Exit(code=1)


def _face_label(bold: bool, italic: bool) -> str:
    return "bold" if bold else ("italic" if italic else "regular")


# ---------------------------------------------------------------------------
# components
# ---------------------------------------------------------------------------


@components_app.command("preview")
def components_preview(
    tokens: TokensOption = Path("config/tokens/dev.json"),
    only: Annotated[
        list[str] | None,
        typer.Option("--only", help="Render just these components (repeatable). Default: all."),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Where to write PNGs. Default: the committed preview dir."),
    ] = None,
) -> None:
    """Render every registered component to its committed golden preview PNG (D5, 3a.4).

    Regenerates unconditionally, every registered component by default, so a `layout_kit`
    change that shifts every component's geometry is visible as one diff across every PNG
    rather than a stale subset of them. The PNGs this writes ARE the design artifact of
    record — commit them.
    """
    from autodeck.design.components import preview as preview_loop
    from autodeck.design.components.catalog import PREVIEW_DIR, UnknownComponentError
    from autodeck.render.qa.libreoffice import FontSubstitutionRisk, RenderError

    design_tokens = DesignTokens.load(tokens)
    out_dir = out or PREVIEW_DIR
    try:
        results = preview_loop.render_previews(
            design_tokens, only=tuple(only) if only else None, out_dir=out_dir
        )
    except (FontSubstitutionRisk, RenderError, UnknownComponentError, KeyError) as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    for result in results:
        typer.echo(f"  {result.name:<20} {result.png}")

    preview_loop.write_provenance(results, out_dir / "provenance.json")

    typer.secho(
        f"\n{len(results)} preview(s) rendered in {design_tokens.typography.major} / "
        f"{design_tokens.typography.minor}. A visual judgement is only valid for that "
        "family — Aptos is the deliverable target (B11).",
        fg=typer.colors.YELLOW,
    )


# ---------------------------------------------------------------------------
# knowledge
# ---------------------------------------------------------------------------


@knowledge_app.command("validate")
def knowledge_validate(knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT) -> None:
    """Load every project and client folder, failing on the first malformed one.

    Worth running before a build rather than during one: the loader's errors name the
    missing file, and finding out here costs seconds instead of finding out mid-pipeline.
    """
    from autodeck.knowledge.loader import KnowledgeError, KnowledgeLoader

    loader = KnowledgeLoader(knowledge_root)
    projects, clients = loader.project_names(), loader.client_names()
    if not projects and not clients:
        _echo_error(f"no knowledge folders under {knowledge_root}")
        raise typer.Exit(code=2)

    try:
        for name in projects:
            project = loader.load_project(name)
            typer.secho(
                f"  project  {name:<28} {len(project.claims)} claim(s), "
                f"{len(project.papers)} paper(s)",
                fg=typer.colors.GREEN,
            )
        for name in clients:
            client = loader.load_client(name)
            extras = [
                label
                for label, present in (
                    ("headers", client.header_profile is not None),
                    ("tokens", client.tokens_path is not None),
                    ("template", client.template_path is not None),
                    ("icons", client.icons_dir is not None),
                    (f"{len(client.decks)} deck(s)", bool(client.decks)),
                    (f"{len(client.engagements)} engagement(s)", bool(client.engagements)),
                )
                if present
            ]
            typer.secho(
                f"  client   {name:<28} {', '.join(extras) or 'required files only'}",
                fg=typer.colors.GREEN,
            )
    except KnowledgeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None


@knowledge_app.command("ingest")
def knowledge_ingest(
    project: Annotated[str, typer.Argument(help="Project whose papers/ to ingest.")],
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    force: Annotated[
        bool, typer.Option("--force", help="Re-ingest papers already in the store.")
    ] = False,
) -> None:
    """Ingest a project's papers into its document store.

    Slow and model-dependent — Docling downloads weights on first use and runs a layout
    model per page. Already-ingested papers are skipped unless `--force`, so an interrupted
    run resumes instead of starting over.

    The `doc_id` is the PDF's filename stem. That is what appears in every citation, which
    is why `SOURCES.md` asks for readable slugs rather than bare identifiers.
    """
    from autodeck.ingest.docling_runner import ingest_pdf
    from autodeck.ingest.document_store import DocumentStore, IngestError
    from autodeck.knowledge.loader import KnowledgeError, KnowledgeLoader

    try:
        knowledge = KnowledgeLoader(knowledge_root).load_project(project)
    except KnowledgeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    if not knowledge.papers:
        _echo_error(f"project {project!r} has no PDFs under {knowledge.root / 'papers'}")
        raise typer.Exit(code=2)

    store = DocumentStore(corpus_root / project)
    flagged: list[str] = []

    for pdf in knowledge.papers:
        doc_id = pdf.stem
        if not force and store.path_for(doc_id).exists():
            typer.echo(f"  skipped   {doc_id} (already ingested)")
            continue
        try:
            document = ingest_pdf(pdf, doc_id=doc_id)
        except IngestError as exc:
            _echo_error(f"{doc_id}: {exc}")
            raise typer.Exit(code=1) from None
        store.add(document)

        coverage = document.provenance_coverage()
        line = (
            f"  ingested  {doc_id:<52} {document.page_count:>3}p "
            f"{len(document.elements):>4} elements  coverage {coverage:.0%}"
        )
        if document.low_provenance:
            flagged.append(doc_id)
            typer.secho(line + "  LOW PROVENANCE", fg=typer.colors.YELLOW)
        else:
            typer.echo(line)

    if flagged:
        typer.secho(
            f"\n{len(flagged)} document(s) flagged low-provenance: {', '.join(flagged)}.\n"
            "Plan §9: these need human review and their content cannot back a claim. They "
            "are excluded from the retrieval index rather than cited approximately.",
            fg=typer.colors.YELLOW,
        )


@knowledge_app.command("ask")
def knowledge_ask(
    project: Annotated[str, typer.Argument(help="Project to search.")],
    question: Annotated[str, typer.Argument(help="What to look for.")],
    client: Annotated[
        str | None, typer.Option("--client", help="Bind the search to one client (A4).")
    ] = None,
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    limit: Annotated[int, typer.Option("--limit")] = 5,
) -> None:
    """Search the corpus and print each hit with a hash-verified citation.

    The Phase 1 milestone in one command: ask a factual question, get answers with page and
    bbox citations that verify against stored text. Uncitable hits — figures, page furniture
    — are shown as such rather than hidden, because a searcher needs to know the difference.
    """
    from autodeck.ingest.document_store import DocumentStore, IngestError
    from autodeck.knowledge.context_assembler import ContextAssembler
    from autodeck.knowledge.loader import KnowledgeError
    from autodeck.retrieval.hybrid import build_index, search

    store = DocumentStore(corpus_root / project)
    documents = list(store.documents())
    if not documents:
        _echo_error(
            f"no ingested documents under {corpus_root / project}. "
            f"Run `autodeck knowledge ingest {project}` first."
        )
        raise typer.Exit(code=2)

    index = build_index(documents, project=project)
    if client is not None:
        try:
            assembler = ContextAssembler(knowledge_root, client=client, project=project)
            # Load the client before binding the index. `use_index` checks the index's
            # namespace, not the client's existence, so a typo'd `--client` would otherwise
            # pass silently — and a search that looks namespace-bound but is not is worse
            # than one that never claimed to be.
            assembler.loader.load_client(client)
            assembler.use_index(index)
        except KnowledgeError as exc:
            _echo_error(str(exc))
            raise typer.Exit(code=1) from None

    hits = search(index, question, limit=limit)
    if not hits:
        typer.echo("no matches")
        return

    for hit in hits:
        typer.secho(f"\n{hit.doc_id}  p.{hit.page}  (score {hit.score:.4f})", bold=True)
        typer.echo(f"  {_shorten(hit.text)}")
        if not hit.citable:
            typer.secho(
                "  NOT CITABLE — retrievable metadata (figure or page furniture). A1 "
                "forbids it backing a claim; cite the caption or the prose instead.",
                fg=typer.colors.YELLOW,
            )
            continue
        try:
            citation = hit.to_citation(store)
        except IngestError as exc:  # pragma: no cover — defensive
            typer.secho(f"  citation failed: {exc}", fg=typer.colors.RED)
            continue
        verified = store.verify_citation(citation)
        typer.secho(
            f"  bbox {tuple(round(v, 1) for v in citation.bbox)}  "
            f"sha256 {citation.quote_sha256[:12]}…  "
            f"{'VERIFIED' if verified else 'FAILED'}",
            fg=typer.colors.GREEN if verified else typer.colors.RED,
        )


def _shorten(text: str, width: int = 300) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= width else collapsed[: width - 1] + "…"


@knowledge_app.command("spotcheck")
def knowledge_spotcheck(
    project: Annotated[str, typer.Argument(help="Project to spot-check.")],
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    output: Annotated[Path, typer.Option("--out")] = Path("spikes/gate1a"),
    count: Annotated[int, typer.Option("--count", help="How many citations to render.")] = 10,
) -> None:
    """Render citations onto their source pages for the GATE 1a review.

    Produces a folder of page images with each citation's bbox drawn on it, plus an
    `index.md` worksheet with an unticked checkbox per citation. **Nothing here decides
    whether the gate passes** — it makes the owner's judgement cheap to form (A7).

    Citations come from `claims.md` first, since those are the curated library and the ones
    most worth being sure about; the remainder are drawn from retrieval so the long-tail
    path is checked too, not just the hand-written entries.
    """
    from autodeck.audit.spotcheck import SpotCheckError, build_spot_checks, write_index
    from autodeck.ingest.document_store import DocumentStore, IngestError
    from autodeck.knowledge.loader import KnowledgeError, KnowledgeLoader
    from autodeck.retrieval.hybrid import build_index, search

    try:
        knowledge = KnowledgeLoader(knowledge_root).load_project(project)
    except KnowledgeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    store = DocumentStore(corpus_root / project)
    documents = list(store.documents())
    if not documents:
        _echo_error(
            f"no ingested documents under {corpus_root / project}. "
            f"Run `autodeck knowledge ingest {project}` first."
        )
        raise typer.Exit(code=2)

    selected: list[tuple[Citation, str]] = []
    seen: set[str] = set()

    for claim in knowledge.claims:
        if len(selected) >= count:
            break
        try:
            citation = claim.to_citation(store=store)
        except IngestError as exc:
            # A stale cached claim is a real finding, not a reason to skip quietly: it
            # means claims.md and the corpus have drifted apart.
            typer.secho(f"  stale claim ({claim.doc_id}): {exc}", fg=typer.colors.YELLOW)
            continue
        selected.append((citation, claim.claim.strip()))
        seen.add(citation.quote_sha256)

    if len(selected) < count:
        index = build_index(documents, project=project)
        for probe in _spotcheck_probes(knowledge.project_md):
            for hit in search(index, probe, limit=3, citable_only=True):
                if len(selected) >= count:
                    break
                try:
                    citation = hit.to_citation(store)
                except IngestError:
                    continue
                if citation.quote_sha256 in seen:
                    continue
                seen.add(citation.quote_sha256)
                selected.append((citation, f"(retrieved for “{probe}”)"))
            if len(selected) >= count:
                break

    if not selected:
        _echo_error("no citations could be resolved; nothing to spot-check")
        raise typer.Exit(code=1)

    papers = {pdf.stem: pdf for pdf in knowledge.papers}
    try:
        checks = build_spot_checks(selected, store, papers, output)
    except SpotCheckError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    index_path = write_index(checks, output / "index.md")
    unrenderable = [check for check in checks if check.source_pdf is None]

    for check in checks:
        typer.echo(
            f"  {check.citation.doc_id:<52} p.{check.citation.page:<3} "
            f"{'hash ok' if check.hash_verified else 'HASH FAILED'}"
        )
    typer.secho(f"\nwrote {index_path}", fg=typer.colors.GREEN)
    if unrenderable:
        typer.secho(
            f"{len(unrenderable)} citation(s) had no source PDF and could not be rendered.",
            fg=typer.colors.YELLOW,
        )
    if len(checks) < count:
        typer.secho(
            f"only {len(checks)} of the {count} requested citations resolved. GATE 1a asks "
            "for ten; a short sheet is a smaller sample, not a passed gate.",
            fg=typer.colors.YELLOW,
        )
    typer.secho(
        "\nGATE 1a is the owner's call. Open index.md, judge each image, tick the boxes. "
        "Nothing in this repository ticks them (A7).",
        fg=typer.colors.YELLOW,
    )


def _spotcheck_probes(project_md: str) -> list[str]:
    """Queries to pull retrieval citations from, when claims.md is short.

    Drawn from the project's own headings so the probes track whatever corpus the project
    holds, rather than a hardcoded list that silently stops matching when the seed changes.
    """
    headings = [
        line.lstrip("#").strip()
        for line in project_md.splitlines()
        if line.startswith("#") and len(line.lstrip("#").strip()) > 3
    ]
    return headings or ["method", "results", "evaluation"]


# ---------------------------------------------------------------------------
# plan / outline (Phase 2a)
# ---------------------------------------------------------------------------


@app.command()
def plan(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    client: Annotated[str, typer.Option("--client", help="Client namespace (A4).")],
    project: Annotated[str, typer.Option("--project", help="Project whose corpus to probe.")],
    env: EnvOption = "dev",
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
) -> None:
    """Run the planning conversation and sign off a brief (A7 approval 1 of 4).

    Conversational, per D7. Type to talk; the planner probes each key message against the
    corpus as it goes. The session ends **only** when you type `/sign <your name>` — there
    is no flag that approves a brief and the planner cannot approve its own.

    Commands during a session: `/brief` shows the draft, `/sign <name>` signs it off,
    `/quit` leaves without signing (the transcript is kept and the draft is not).
    """
    from autodeck.agents.evidence_gap import CLASSIFIER_ROLE, EvidenceProbe
    from autodeck.agents.planner import (
        BriefIncomplete,
        PlannerError,
        PlannerSession,
        render_draft,
    )
    from autodeck.ingest.document_store import DocumentStore
    from autodeck.knowledge.context_assembler import ContextAssembler
    from autodeck.knowledge.loader import KnowledgeError, KnowledgeLoader
    from autodeck.pipeline.orchestrator import Orchestrator
    from autodeck.providers.registry import ModelRegistry
    from autodeck.retrieval.hybrid import build_index

    try:
        assembler = ContextAssembler(knowledge_root, client=client, project=project)
        context = assembler.assemble()
        knowledge = KnowledgeLoader(knowledge_root).load_project(project)
    except KnowledgeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    store = DocumentStore(corpus_root / project)
    documents = list(store.documents())
    if not documents:
        _echo_error(
            f"no ingested documents under {corpus_root / project}. The evidence-gap check "
            f"is the point of this session — run `autodeck knowledge ingest {project}` first."
        )
        raise typer.Exit(code=2)

    registry = ModelRegistry.load(env)
    index = assembler.use_index(build_index(documents, project=project))
    session = PlannerSession(
        Orchestrator(run_id, runs_root=runs_root, env=env),
        model=registry.provider_for("planner"),  # type: ignore[arg-type]
        probe=EvidenceProbe(
            index=index,  # type: ignore[arg-type]
            store=store,
            claims=knowledge.claims,
            classifier=registry.provider_for(CLASSIFIER_ROLE),  # type: ignore[arg-type]
        ),
        context=context,
    )

    typer.secho(f"Planning {run_id} for {client} / {project} (env={env})", bold=True)
    typer.echo(
        "Type to talk. /brief to see the draft, /sign <name> to approve, /quit to leave.\n"
    )

    while True:
        try:
            said = typer.prompt("you", prompt_suffix=" > ").strip()
        except (EOFError, KeyboardInterrupt):
            typer.echo("\nleft without signing; transcript kept")
            raise typer.Exit(code=1) from None

        if said in ("/quit", "/exit"):
            typer.secho("left without signing; transcript kept", fg=typer.colors.YELLOW)
            raise typer.Exit(code=1)

        if said == "/brief":
            typer.echo(render_draft(session.draft))
            continue

        if said.startswith("/sign"):
            approver = said[len("/sign") :].strip()
            try:
                brief = session.sign_off(approver=approver)
            except BriefIncomplete as exc:
                typer.secho(str(exc), fg=typer.colors.RED)
                typer.secho(
                    "\nCarrying a weak message is allowed — it needs a recorded risk with "
                    "someone's name on it. Ask the planner to add one (A8).",
                    fg=typer.colors.YELLOW,
                )
                continue
            except PlannerError as exc:
                typer.secho(str(exc), fg=typer.colors.RED)
                continue
            typer.secho(
                f"\nbrief v{brief.version} signed off by {brief.approved_by}",
                fg=typer.colors.GREEN,
            )
            unprobed = brief.unprobed_messages()
            if unprobed:
                typer.secho(
                    f"note: {', '.join(m.id for m in unprobed)} were never probed against "
                    "the corpus. Not a failure — but nobody looked.",
                    fg=typer.colors.YELLOW,
                )
            typer.echo(
                f"\nNext: autodeck outline {run_id} --client {client} --project {project}"
            )
            return

        if not said:
            continue

        try:
            reply = session.turn(said)
        except PlannerError as exc:
            _echo_error(str(exc))
            raise typer.Exit(code=1) from None

        typer.secho(f"\nplanner > {reply.text}\n", fg=typer.colors.CYAN)
        for probe in reply.probes:
            colour = {
                "supported": typer.colors.GREEN,
                "thin": typer.colors.YELLOW,
                "unsupported": typer.colors.RED,
            }.get(probe.status, typer.colors.WHITE)
            typer.secho(
                f"  evidence · {probe.message_id}: {probe.status.upper()}"
                + (" (capped)" if probe.capped else ""),
                fg=colour,
            )
            if probe.reasoning:
                typer.echo(f"      {_shorten(probe.reasoning, 200)}")
        if reply.probes:
            typer.echo("")


@app.command()
def outline(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    client: Annotated[str, typer.Option("--client")],
    project: Annotated[str, typer.Option("--project")],
    env: EnvOption = "dev",
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
    tokens: TokensOption = Path("config/tokens/dev.json"),
) -> None:
    """Build the outline skeleton from the signed brief, then review it against that brief.

    Blocks unless the brief gate is approved (A7). The GATE 1 report that follows checks
    only what a machine can check — whether the outline *makes the argument* is yours.
    """
    from autodeck.agents.outline import OutlineError, build_outline
    from autodeck.audit.gate1 import review_outline
    from autodeck.ir.store import IRStoreError
    from autodeck.knowledge.context_assembler import ContextAssembler
    from autodeck.knowledge.loader import KnowledgeError
    from autodeck.pipeline.orchestrator import Gate, GateBlocked, Orchestrator
    from autodeck.providers.registry import ModelRegistry

    orchestrator = Orchestrator(run_id, runs_root=runs_root, env=env)
    try:
        orchestrator.require_gate(Gate.BRIEF)
    except GateBlocked as blocked:
        _echo_error(str(blocked))
        raise typer.Exit(code=3) from None

    try:
        brief_doc = orchestrator.ir.load_brief()
        context = ContextAssembler(knowledge_root, client=client, project=project).assemble()
    except (IRStoreError, KnowledgeError) as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    try:
        result = build_outline(
            brief_doc,
            ModelRegistry.load(env).provider_for("outline"),  # type: ignore[arg-type]
            client=client,
            project=project,
            theme_ref=str(tokens),
            component_lib_version=COMPONENT_LIB_VERSION,
            context=context.to_prompt_context(),
        )
    except OutlineError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    path = orchestrator.ir.save(result.deck, overwrite=True)
    typer.secho(f"wrote {path}", fg=typer.colors.GREEN)

    for slide in result.deck.slides:
        served = ", ".join(slide.message_ids) or "-"
        typer.echo(
            f"  {slide.id:<8} {slide.narrative_role:<14} {slide.component:<20} [{served}]"
        )
        typer.echo(f"           {_shorten(slide.intent or '', 90)}")

    if result.notes:
        typer.secho(f"\noutline notes: {result.notes}", fg=typer.colors.YELLOW)
    for correction in result.corrections:
        typer.secho(f"corrected: {correction}", fg=typer.colors.YELLOW)

    typer.echo("")
    report = review_outline(result.deck, brief_doc)
    typer.echo(report.render())
    if not report.mechanical_checks_pass:
        raise typer.Exit(code=4)


# ---------------------------------------------------------------------------
# content / validate / GATE 2 (Phase 2b, task 2b.11)
# ---------------------------------------------------------------------------
#
# Three commands and a fourth that is the actual point of this section. `content` and
# `validate` are plumbing — they call agents that already exist and are already tested
# (`autodeck/agents/content.py`, `autodeck/agents/validation.py`) and write the result as
# the next IR version, exactly as `outline` does for its own stage. `gate2` is the review
# surface `gate1.py` already models: it reports the checkable criteria and never approves.
#
# `send-back` is the part nothing in the system could express before this task. GATE 2's
# exit criterion is "approves, or sends specific claims back", and a send-back that a
# writer could regenerate verbatim would make the gate decorative — see
# `autodeck/pipeline/send_back.py`'s module docstring for the full design and its own
# stated limits.


def _iso_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


@app.command()
def content(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    env: EnvOption = "dev",
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
    header_style: Annotated[
        str | None,
        typer.Option(
            "--header-style",
            help=(
                "Override this deck's header voice for this run (e.g. question_led, "
                "assertion). Reshapes phrasing only, on top of whatever the client's own "
                "headers.yaml sets — it never relaxes what needs a citation (D12)."
            ),
        ),
    ] = None,
) -> None:
    """Write every slide's blocks from the approved outline, then lint the result (A2, A5).

    Blocked unless the outline gate is approved (A7): there is no content without an
    outline the owner has signed off. Any claim `autodeck send-back` rejected in an earlier
    round is read from the run directory and shown to the writer; a new claim identical to
    one already rejected is dropped rather than written again — see
    `autodeck/pipeline/send_back.py` for what that check does and does not catch.

    `--header-style` is the one-flag per-deck switch task 3a.8 asks for: it does not touch
    the approved brief on disk, the client's `headers.yaml`, or any prompt file — see
    `autodeck.design.headers.prompt.resolve_profile`.
    """
    import dataclasses

    from autodeck.agents.content import ContentError, write_slide
    from autodeck.audit.framing_linter import lint_framing
    from autodeck.audit.numeric_linter import lint_deck
    from autodeck.design.theme.tokens import DesignTokens
    from autodeck.ingest.document_store import DocumentStore
    from autodeck.ingest.provenance import normalise_for_match
    from autodeck.ir.store import IRStoreError
    from autodeck.knowledge.context_assembler import ContextAssembler
    from autodeck.knowledge.loader import KnowledgeError, KnowledgeLoader
    from autodeck.pipeline.orchestrator import Gate, GateBlocked, Orchestrator
    from autodeck.pipeline.send_back import SendBackRecord, load_send_backs
    from autodeck.providers.registry import ModelRegistry
    from autodeck.retrieval.hybrid import build_index

    orchestrator = Orchestrator(run_id, runs_root=runs_root, env=env)
    try:
        orchestrator.require_gate(Gate.OUTLINE)
    except GateBlocked as blocked:
        _echo_error(str(blocked))
        raise typer.Exit(code=3) from None

    try:
        deck = orchestrator.ir.load()
        brief_doc = orchestrator.ir.load_brief()
    except IRStoreError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    if header_style is not None:
        # The one-flag switch: overrides only this run's effective voice, never the
        # approved brief saved on disk (A7 concerns itself with approvals, not this — but
        # the brief file itself stays exactly what the owner signed off).
        brief_doc = brief_doc.model_copy(update={"header_style": header_style})

    try:
        context = ContextAssembler(
            knowledge_root, client=deck.client, project=deck.project
        ).assemble()
        knowledge = KnowledgeLoader(knowledge_root).load_project(deck.project)
    except KnowledgeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    store = DocumentStore(corpus_root / deck.project)
    documents = list(store.documents())
    if not documents:
        _echo_error(
            f"no ingested documents under {corpus_root / deck.project}. Run "
            f"`autodeck knowledge ingest {deck.project}` first."
        )
        raise typer.Exit(code=2)
    index = build_index(documents, project=deck.project)

    design_tokens = DesignTokens.load(Path(deck.theme_ref))
    model = ModelRegistry.load(env).provider_for("content")

    send_backs = load_send_backs(orchestrator.paths.root)
    if send_backs:
        context = dataclasses.replace(
            context, send_backs=tuple(record.prompt_line() for record in send_backs)
        )

    def matches_a_send_back(record: SendBackRecord, claim: Claim) -> bool:
        return normalise_for_match(claim.text) == normalise_for_match(record.claim_text)

    def drop_repeats(blocks: list[Block], location: str) -> tuple[list[Block], list[str]]:
        kept: list[Block] = []
        dropped: list[str] = []
        for block in blocks:
            claim = block.claim
            hit = next(
                (r for r in send_backs if claim is not None and matches_a_send_back(r, claim)),
                None,
            )
            if hit is None:
                kept.append(block)
                continue
            dropped.append(
                f"{location} block {block.id!r} dropped: identical to the claim sent back "
                f"as {hit.claim_id!r} against IR v{hit.ir_version} by {hit.by} — {hit.reason}"
            )
        return kept, dropped

    new_slides: list[Slide] = []
    rejections: list[str] = []
    send_back_drops: list[str] = []
    new_deck: Deck | None = None

    def do_content() -> str:
        nonlocal new_deck
        for slide in deck.slides:
            result = write_slide(
                slide,
                brief_doc,
                context,
                store=store,
                index=index,
                claims=knowledge.claims,
                tokens=design_tokens,
                model=model,
            )
            kept_blocks, block_drops = drop_repeats(result.blocks, f"slide {slide.id} face")
            kept_notes, note_drops = drop_repeats(
                result.speaker_notes, f"slide {slide.id} notes"
            )
            send_back_drops.extend(block_drops + note_drops)
            rejections.extend(f"slide {slide.id}: {reason}" for reason in result.rejections)

            new_slides.append(
                slide.model_copy(update={"blocks": kept_blocks, "speaker_notes": kept_notes})
            )
            typer.echo(
                f"  {slide.id:<8} {len(kept_blocks)} block(s), {len(kept_notes)} note(s)"
                + ("" if result.budgets_checked else "  (budgets not checked — no catalog)")
            )

        new_deck = deck.model_copy(
            update={"version": orchestrator.ir.next_version(), "slides": new_slides}
        )
        path = orchestrator.ir.save(new_deck)
        return f"wrote {path}"

    try:
        orchestrator.run_stage("content", do_content, force=True)
    except ContentError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    assert new_deck is not None
    typer.secho(f"\nwrote IR v{new_deck.version}", fg=typer.colors.GREEN)

    if rejections:
        typer.secho(
            f"\n{len(rejections)} block(s) dropped during citation/budget resolution:",
            fg=typer.colors.YELLOW,
        )
        for reason in rejections:
            typer.echo(f"  {reason}")

    if send_back_drops:
        typer.secho(
            f"\n{len(send_back_drops)} block(s) dropped as a verbatim repeat of a GATE 2 "
            "send-back:",
            fg=typer.colors.YELLOW,
        )
        for reason in send_back_drops:
            typer.echo(f"  {reason}")
    elif send_backs:
        typer.echo(
            f"\n{len(send_backs)} earlier send-back(s) were shown to the writer; none of "
            "the new claims repeat one verbatim."
        )

    typer.echo("")
    numeric = lint_deck(new_deck)
    framing = lint_framing(new_deck)
    typer.echo(numeric.render())
    typer.echo("")
    typer.echo(framing.render())
    typer.echo(f"\nNext: autodeck validate {run_id}")


@app.command()
def validate(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    env: EnvOption = "dev",
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
) -> None:
    """Validate every claim in the latest IR (A3) and write the verdicts as a new version.

    Blocked unless `autodeck content` has run — there is nothing to independently verify
    before it has. Prints the claims table `verdicts.VerdictReport.render()` produces;
    `autodeck gate2` is the surface that turns this into a reviewable report.
    """
    from autodeck.agents.validation import ValidationAgentError, ValidationResult, validate_deck
    from autodeck.ingest.document_store import DocumentStore
    from autodeck.ir.store import IRStoreError
    from autodeck.pipeline.orchestrator import Orchestrator
    from autodeck.providers.registry import ModelRegistry
    from autodeck.retrieval.hybrid import build_index

    orchestrator = Orchestrator(run_id, runs_root=runs_root, env=env)
    if not orchestrator.state.is_complete("content"):
        _echo_error(
            f"run {run_id!r} has no content yet. Run `autodeck content {run_id}` first."
        )
        raise typer.Exit(code=3)

    try:
        deck = orchestrator.ir.load()
    except IRStoreError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    store = DocumentStore(corpus_root / deck.project)
    documents = list(store.documents())
    if not documents:
        _echo_error(
            f"no ingested documents under {corpus_root / deck.project}. Run "
            f"`autodeck knowledge ingest {deck.project}` first."
        )
        raise typer.Exit(code=2)
    index = build_index(documents, project=deck.project)
    model = ModelRegistry.load(env).provider_for("validation")

    next_version = orchestrator.ir.next_version()
    result: ValidationResult | None = None

    def do_validate() -> str:
        nonlocal result
        deck_to_validate = deck.model_copy(update={"version": next_version})
        result = validate_deck(deck_to_validate, index=index, store=store, model=model)
        path = orchestrator.ir.save(result.deck)
        return f"wrote {path} · {result.provider_calls} provider call(s)"

    try:
        orchestrator.run_stage("validate", do_validate, force=True)
    except ValidationAgentError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    assert result is not None
    typer.secho(f"wrote v{next_version}", fg=typer.colors.GREEN)
    typer.echo("")
    typer.echo(result.report.render())
    typer.echo(f"\nNext: autodeck gate2 {run_id}")


@app.command()
def gate2(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
) -> None:
    """The GATE 2 review surface: the audit report, a stable id per claim, and the phase
    brief's checkable criteria.

    Blocked unless `autodeck validate` has run. Exits non-zero when a checkable criterion
    fails — but as with `gate1.py`, this reports and never decides. A clean run here is not
    the gate: the owner reading the claims table is. Approve with `autodeck approve
    <run> claims`, or reject named claims with `autodeck send-back`.
    """
    from autodeck.audit.report import build_audit_report, render
    from autodeck.ir.store import IRStoreError
    from autodeck.pipeline.orchestrator import Orchestrator, assess_render_safety
    from autodeck.pipeline.send_back import load_send_backs

    orchestrator = Orchestrator(run_id, runs_root=runs_root)
    if not orchestrator.state.is_complete("validate"):
        _echo_error(
            f"run {run_id!r} has not been validated yet. Run `autodeck validate {run_id}` "
            "first."
        )
        raise typer.Exit(code=3)

    try:
        deck = orchestrator.ir.load()
    except IRStoreError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    brief_doc: DeckBrief | None
    try:
        brief_doc = orchestrator.ir.load_brief()
    except IRStoreError:
        brief_doc = None

    # One assessment, feeding both the report and the criteria. The render guard computes
    # exactly this from exactly this deck, so GATE 2 cannot show a green criterion for a
    # deck the render stage will refuse — and neither can be handed another deck's reports.
    safety = assess_render_safety(deck)
    report = build_audit_report(
        deck, brief=brief_doc, numeric=safety.numeric, framing=safety.framing
    )

    typer.echo(render(report))
    typer.echo("=" * 78)
    typer.secho(
        "GATE 2 checkable criteria (docs/phases/PHASE-2B.md)", bold=True, fg=typer.colors.CYAN
    )
    all_pass = True
    for label, passed, detail in _gate2_checks(brief_doc, safety, report):
        all_pass = all_pass and passed
        typer.secho(
            f"  [{'PASS' if passed else 'FAIL'}] {label}",
            fg=typer.colors.GREEN if passed else typer.colors.RED,
        )
        if detail:
            typer.echo(f"         {detail}")

    typer.echo("\nStable claim ids, for `autodeck send-back --claim`:")
    for row in report.claim_rows():
        typer.echo(
            f"  {row.slide_id}:{row.block_id}  [{row.verdict}]  {_shorten(row.claim_text, 80)}"
        )

    send_backs = load_send_backs(orchestrator.paths.root)
    if send_backs:
        typer.secho(
            f"\n{len(send_backs)} claim(s) already sent back in an earlier round:",
            fg=typer.colors.YELLOW,
        )
        for record in send_backs:
            typer.echo(
                f"  {record.claim_id} (v{record.ir_version}, by {record.by}): {record.reason}"
            )

    typer.secho(
        f"\nA clean run above is not the gate — {run_id} is ready for the owner to read the "
        "claims table, not to ship. Approve with `autodeck approve "
        f"{run_id} claims`, or send specific claims back with `autodeck send-back {run_id} "
        '--claim <id> --reason "..."`.',
        fg=typer.colors.YELLOW,
    )

    if not all_pass:
        raise typer.Exit(code=4)


def _gate2_checks(
    brief_doc: DeckBrief | None,
    safety: RenderSafety,
    report: AuditReport,
) -> list[tuple[str, bool, str]]:
    """The six checkable criteria `docs/phases/PHASE-2B.md` names for GATE 2.

    Every check reads an existing report field — nothing here re-derives a verdict, a
    numeral match or a demotion, and **this function is not given the deck**, so it cannot
    start. The first three criteria are `assess_render_safety`'s own four conditions,
    printed one per line: this used to call `blocking_blocks`, `unverified_claims` and read
    two reports of its own, which is three of the render guard's four conditions
    re-implemented at a second call site. The guard's docstring warns that three checks at
    three call sites is how one gets forgotten; it had already happened, and both copies
    shared the diagram blind spot. Phase 3b's render stage inherits one answer.

    The one deliberate broadening over "unsupported/contradicted": criterion 1 also fails
    on an `unverified` claim. A validation pass that never reached a claim leaves
    `blocking_blocks()` empty, which would otherwise let an unvalidated deck read as passing
    every GATE 2 criterion — the same trap `assess_render_safety` names.
    """
    checks: list[tuple[str, bool, str]] = []

    blocking, unverified = safety.blocking, safety.unverified
    checks.append(
        (
            "zero blocks verdict unsupported/contradicted (and none left unverified)",
            not blocking and not unverified,
            (
                f"{len(blocking)} blocking block(s), {len(unverified)} unverified claim(s)"
                if blocking or unverified
                else ""
            ),
        )
    )

    numeric = safety.numeric
    checks.append(
        (
            "numeric linter: zero unmatched numerals, every derivation re-executes",
            numeric.passes,
            "" if numeric.passes else f"{len(numeric.blocking)} blocking A2 finding(s)",
        )
    )

    framing = safety.framing
    checks.append(
        (
            "framing linter clean, no unresolved demotions",
            not framing.blocks_build,
            (
                f"{len(framing.demotions)} block(s) demoted to claim"
                if framing.blocks_build
                else ""
            ),
        )
    )

    rows = report.claim_rows()
    fully_cited = all(
        row.citations
        and all(c.quote.strip() and c.page >= 1 and c.doc_id for c in row.citations)
        for row in rows
    )
    checks.append(
        (
            "every claim shows doc, page and a verbatim quote",
            fully_cited,
            "" if fully_cited else "a claim row is missing a citation with doc/page/quote",
        )
    )

    conflicts_ok = all(
        bool(row.contradicting_spans) for row in rows if row.verdict == "contradicted"
    )
    checks.append(
        (
            "conflicts section present where sources disagree (A8)",
            conflicts_ok,
            "" if conflicts_ok else "a contradicted claim has no contradicting span recorded",
        )
    )

    if brief_doc is None:
        checks.append(
            (
                "open_risks from the brief appear in the report",
                False,
                "no brief could be loaded for this run — risks cannot be resurfaced",
            )
        )
    else:
        risk_ids = {risk.message_id for risk in brief_doc.open_risks}
        reported_ids = {row.risk.message_id for row in report.risks}
        missing_ids = sorted(risk_ids - reported_ids)
        checks.append(
            (
                "open_risks from the brief appear in the report",
                risk_ids == reported_ids,
                "" if risk_ids == reported_ids else f"missing: {missing_ids}",
            )
        )

    return checks


@app.command("send-back")
def send_back(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    claim: Annotated[
        list[str],
        typer.Option(
            "--claim",
            help="Stable claim id from `autodeck gate2` (e.g. s3:b2). Repeatable.",
        ),
    ],
    reason: Annotated[
        list[str],
        typer.Option(
            "--reason",
            help="Why this claim is rejected. Repeatable, paired by position with --claim.",
        ),
    ],
    by: Annotated[str, typer.Option("--by", help="Who is sending it back.")] = "owner",
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
) -> None:
    """Reject named claims from the latest IR, recorded so the next content pass sees them.

    This command cannot approve anything — `autodeck approve` is the only command that can,
    and there is no flag here that does what it does. A send-back is a rejection: it is
    recorded beside the IR (`runs/<run>/send_backs.json`), not in it, and read back by
    `autodeck content` on its next run. See `autodeck/pipeline/send_back.py` for the full
    design and what it does not guarantee.
    """
    from autodeck.audit.report import build_audit_report
    from autodeck.ir.store import IRStoreError
    from autodeck.pipeline.orchestrator import Orchestrator
    from autodeck.pipeline.send_back import SendBackRecord, append_send_backs

    if len(claim) != len(reason):
        _echo_error(
            f"{len(claim)} --claim option(s) but {len(reason)} --reason option(s); pass "
            "exactly one --reason for each --claim, in the same order."
        )
        raise typer.Exit(code=2)
    if not claim:
        _echo_error("at least one --claim is required.")
        raise typer.Exit(code=2)

    orchestrator = Orchestrator(run_id, runs_root=runs_root)
    try:
        deck = orchestrator.ir.load()
    except IRStoreError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    report = build_audit_report(deck, brief=None)
    by_claim_id = {f"{row.slide_id}:{row.block_id}": row for row in report.claim_rows()}

    records: list[SendBackRecord] = []
    unknown: list[str] = []
    for claim_id, why in zip(claim, reason, strict=True):
        if not why.strip():
            _echo_error(
                f"empty --reason for claim {claim_id!r}. A send-back with no reason teaches "
                "the writer nothing."
            )
            raise typer.Exit(code=2)
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
                at=_iso_now(),
            )
        )

    if unknown:
        _echo_error(
            f"unknown claim id(s): {', '.join(unknown)}. Run `autodeck gate2 {run_id}` to "
            "see the current claim ids — they change across content passes."
        )
        raise typer.Exit(code=1)

    path = append_send_backs(orchestrator.paths.root, records)
    for record in records:
        typer.secho(
            f"sent back {record.claim_id} (v{record.ir_version}) — {record.reason}",
            fg=typer.colors.YELLOW,
        )
    typer.secho(f"\nwrote {path}", fg=typer.colors.GREEN)
    typer.echo(
        "\nThis is a rejection, not an approval — GATE 2 still needs `autodeck approve "
        f"{run_id} claims` once every claim is addressed. Re-run `autodeck content {run_id}` "
        "so the writer sees this."
    )


# ---------------------------------------------------------------------------
# spike
# ---------------------------------------------------------------------------


@spike_app.command("build")
def spike_build(
    tokens: TokensOption = Path("config/tokens/dev.json"),
    output: Annotated[Path, typer.Option("--out")] = Path("spikes/gate0"),
    preview: Annotated[bool, typer.Option("--preview/--no-preview")] = True,
) -> None:
    """Build the three GATE 0 spike artifacts, and optionally render previews.

    The PPTX files are the deliverable — GATE 0 is closed by opening them in PowerPoint,
    not by reading the PNGs.
    """
    from autodeck.design import spikes

    design_tokens = DesignTokens.load(tokens)
    artifacts = [
        spikes.build_theme_spike(design_tokens, output / "theme.pptx"),
        spikes.build_component_spike(design_tokens, output / "components.pptx"),
        spikes.build_icon_spike(design_tokens, output / "icon.pptx"),
    ]
    spikes.write_provenance(artifacts, output / "provenance.json")

    for artifact in artifacts:
        typer.echo(f"  {artifact.name:<11} {artifact.pptx}  ({artifact.build_seconds:.2f}s)")

    if not preview:
        return

    from autodeck.render.qa.libreoffice import RenderError, render_pptx

    try:
        for artifact in artifacts:
            result = render_pptx(artifact.pptx, output / "previews", design_tokens)
            typer.echo(f"  {artifact.name:<11} {result.page_count} preview(s)")
    except RenderError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    typer.secho(
        f"\nPreviews rendered in {design_tokens.typography.major} / "
        f"{design_tokens.typography.minor}. A visual judgement is only valid for that "
        "family — Aptos is the deliverable target (B11).",
        fg=typer.colors.YELLOW,
    )


if __name__ == "__main__":  # pragma: no cover
    app()
