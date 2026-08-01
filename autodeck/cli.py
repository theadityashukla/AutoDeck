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
from typing import Annotated

import typer

from autodeck.audit.manifest import build_manifest
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import Block, Citation, Claim, Deck, Slide
from autodeck.ir.store import IRStore, diff_decks
from autodeck.pipeline.orchestrator import (
    DEFAULT_RUNS_ROOT,
    STAGE_SEQUENCE,
    Gate,
    GateBlocked,
    Orchestrator,
)
from autodeck.providers.registry import ModelRegistry

app = typer.Typer(
    name="autodeck",
    help="Accuracy-first consulting decks as native, editable PPTX.",
    no_args_is_help=True,
    add_completion=False,
)

ir_app = typer.Typer(help="Inspect and diff Deck IR versions.", no_args_is_help=True)
spike_app = typer.Typer(help="GATE 0 spike artifacts.", no_args_is_help=True)
fonts_app = typer.Typer(help="Font availability checks.", no_args_is_help=True)
knowledge_app = typer.Typer(
    help="Knowledge folders and the document corpus.", no_args_is_help=True
)
app.add_typer(ir_app, name="ir")
app.add_typer(spike_app, name="spike")
app.add_typer(fonts_app, name="fonts")
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
        component_lib_version="0.1.0",
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
    """
    from autodeck.design.fonts import FontNotFoundError, resolve_family

    families = [family] if family else sorted(DesignTokens.load(tokens).typography.families())
    missing = False
    for name in families:
        try:
            typer.secho(
                f"  OK      {name} -> {resolve_family(name).path}", fg=typer.colors.GREEN
            )
        except FontNotFoundError as exc:
            missing = True
            typer.secho(f"  MISSING {name}", fg=typer.colors.RED)
            typer.echo(f"          {exc}")
    if missing:
        raise typer.Exit(code=1)


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
            ContextAssembler(knowledge_root, client=client, project=project).use_index(index)
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
