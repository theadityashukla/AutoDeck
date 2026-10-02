"""`autodeck` command line — the headless entry point (D7).

v1's Streamlit state machine was a documented cost (`legacy/v1/LEGACY.md`), so v2 is
CLI-first with the review UI deferred. Every command that touches models takes `--env`,
defaulting to `dev`, and every artifact lands under `runs/<run_id>/` where it can be
inspected, diffed and resumed.

Owning phase: 0 (task 0.7); the real `plan` and `build` commands land in Phases 2a and 4.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NoReturn

import typer
from pydantic import BaseModel

from autodeck.audit.manifest import build_manifest
from autodeck.design.components.catalog import COMPONENT_LIB_VERSION
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import Block, Citation, Claim, Deck, DeckBrief, Slide
from autodeck.ir.store import IRStore, diff_decks
from autodeck.pipeline.orchestrator import (
    DEFAULT_RUNS_ROOT,
    STAGE_SEQUENCE,
    ApprovalRefused,
    ApprovalState,
    ArtifactMissing,
    Gate,
    GateBlocked,
    Orchestrator,
    UnknownRunError,
)
from autodeck.providers.cache import ResponseCache
from autodeck.providers.guard import ProviderFailureRecord, ProviderGuard
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


#: Exit code for a provider failure that ends a command: a spent quota or a missing or
#: rejected API key. Distinct from 1 (something is wrong with the input) and 3 (a gate)
#: because the remedy is different — wait, or set a key, then run the same command again.
EXIT_PROVIDER_FAILURE = 5


def _cache_note(orchestrator: Orchestrator) -> str:
    """How much of this run's provider work is saved, for the end-of-failure message.

    Counts what is in the response cache, which is all it can know: a provider that does not
    write to it (a stand-in model in a test) leaves it empty after making calls, so the empty
    case must not claim that no call was made.
    """
    cache = ResponseCache(orchestrator.paths.llm_cache)
    saved = len(cache)
    return (
        f"{saved} completed provider call(s) are saved under {cache.directory}; a re-run "
        "replays them at no cost and only pays for what did not finish."
        if saved
        else "The run's response cache is empty, so a re-run repeats every model call."
    )


def _undrawn_deck_note(deck: Deck, run_id: str, render_error: str) -> str:
    """Why no deck was drawn after a model call failed, in plain words.

    When the slides that could not be drawn are icon slides with no icons, say so: the
    art-direction call that would have chosen the icons is the one that failed. Any other
    render error is shown as it is.
    """
    iconless = [
        slide.id
        for slide in deck.slides
        if slide.component == "icon_pillars"
        and not any(block.slot == "pillar_icon" for block in slide.blocks)
    ]
    if not iconless:
        return f"\n  No deck was drawn yet: {render_error}"
    return (
        f"\n  No deck was drawn: the icon slide ({', '.join(iconless)}) could not get its "
        "icons because the art-direction call above failed. Re-run "
        f"`autodeck render {run_id}` later."
    )


def _provider_failure_message(
    failure: ProviderFailureRecord, *, command: str, saved: str
) -> str:
    who = f"role '{failure.role}' ({failure.provider}, model {failure.model})"
    if failure.kind == "rate_limit":
        # Free tiers limit differently: Gemini per model per day, Groq per minute
        # (config/models.yaml). Saying "daily" about Groq would send the owner away for a
        # day over a limit that clears in a minute.
        if failure.provider == "groq":
            meaning = (
                "Groq's free tier is limited per minute (tokens), so waiting a minute or "
                "two is usually enough."
            )
        else:
            meaning = (
                "On a free tier this is almost always that model's daily quota: it resets "
                "daily, so running the command again sooner will not help."
            )
        what = (
            f"STOPPED: {who} was rate limited.\n"
            "  The provider refused the call (HTTP 429) and waiting inside the command did "
            f"not clear it.\n  {meaning}"
        )
    elif failure.kind == "missing_key":
        what = (
            f"STOPPED: {who} has no API key.\n"
            f"  The environment variable {failure.env_var} is not set. Set it in this "
            "shell, then run the command again."
        )
    else:
        what = (
            f"STOPPED: {who} was refused: the provider rejected the credentials.\n"
            f"  Check that {failure.env_var} holds a valid key for {failure.provider}, then "
            "run the command again."
        )
    return f"{what}\n  Saved: {saved}\n  Then run `autodeck {command}` again."


@contextmanager
def _ends_on_provider_failure(
    guard: ProviderGuard, *, command: str, saved: Callable[[], str]
) -> Iterator[None]:
    """End the command with a short message and exit code 5 if a provider failure caused it.

    Looks through the exception's cause chain, because the agents wrap provider errors in
    their own (`ContentError`, `OutlineError`) and the role is gone by the time they surface.
    Anything else propagates untouched.
    """
    try:
        yield
    except Exception as exc:
        failure = guard.failure_behind(exc)
        if failure is None:
            raise
        _echo_error(_provider_failure_message(failure, command=command, saved=saved()))
        raise typer.Exit(code=EXIT_PROVIDER_FAILURE) from None


def _open_run(run_id: str, runs_root: Path, env: str = "dev") -> Orchestrator:
    """Open a run that must already exist.

    Every command except `plan` (and the Phase 0 stub, which starts a run by design) goes
    through here, so a mistyped run id ends in an error instead of a new empty run that
    `status` then reports as not started and `approve` would once have accepted.
    """
    try:
        return Orchestrator(run_id, runs_root=runs_root, env=env, create=False)
    except UnknownRunError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None


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

    # The one command besides `plan` that starts a run: the Phase 0 milestone is a fresh id
    # running to the first gate.
    orchestrator = Orchestrator(run_id, runs_root=runs_root, env=env)
    registry = ModelRegistry.load(env)

    def write_stub_ir() -> str:
        deck = _stub_deck(run_id)
        path = orchestrator.save_ir(deck, overwrite=True)
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
    there must never be one. The approval is bound to the artifact as it is now (its
    sha256 is stored beside your name), and it is refused when that artifact does not exist
    yet.
    """
    orchestrator = _open_run(run_id, runs_root)
    try:
        orchestrator.approve(gate, approver=approver)
    except (ArtifactMissing, ApprovalRefused) as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    typer.secho(f"approved {gate.value} for {run_id}", fg=typer.colors.GREEN)
    typer.echo(f"  covers sha256 {orchestrator.state.fingerprints[gate.value][:16]}...")

    remaining = orchestrator.pending_gates()
    if remaining:
        typer.echo(f"still pending: {', '.join(g.value for g in remaining)}")


@app.command()
def status(
    run_id: Annotated[str, typer.Argument()], runs_root: RunsRoot = DEFAULT_RUNS_ROOT
) -> None:
    """Show stage completion and gate approvals for a run."""
    orchestrator = _open_run(run_id, runs_root)
    state = orchestrator.state

    typer.secho(f"run {run_id} (env={state.env})", bold=True)
    typer.echo("stages:")
    for name in STAGE_SEQUENCE:
        record = state.stages.get(name)
        typer.echo(f"  {name:<14} {record.status.value if record else 'not-started'}")

    if orchestrator.paths.draft_brief.exists() and not state.is_complete("plan"):
        typer.echo(
            f"  (an unsigned draft brief is saved at {orchestrator.paths.draft_brief}; "
            "`autodeck plan` resumes it)"
        )

    typer.echo("gates:")
    for gate in Gate:
        approval_state, detail = orchestrator.approval_state(gate)
        if approval_state is ApprovalState.PENDING:
            typer.echo(f"  {gate.value:<14} PENDING")
        elif approval_state is ApprovalState.CURRENT:
            typer.echo(f"  {gate.value:<14} {state.approvals[gate.value]}")
        else:
            typer.secho(
                f"  {gate.value:<14} NOT CURRENT ({state.approvals[gate.value]}) — {detail}",
                fg=typer.colors.YELLOW,
            )


# ---------------------------------------------------------------------------
# ir
# ---------------------------------------------------------------------------


@ir_app.command("versions")
def ir_versions(
    run_id: Annotated[str, typer.Argument()], runs_root: RunsRoot = DEFAULT_RUNS_ROOT
) -> None:
    """List the IR versions saved for a run."""
    _open_run(run_id, runs_root)
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
    _open_run(run_id, runs_root)
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
    `/quit` (or `/exit`, Ctrl-C, Ctrl-D) leaves without signing. The transcript **and the
    draft** are kept: run `plan` again with the same run id and it picks the draft up. A
    provider failure (spent quota, missing key) also ends the session with the draft kept.
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
    orchestrator = Orchestrator(run_id, runs_root=runs_root, env=env)
    guard = ProviderGuard(registry, cache=ResponseCache(orchestrator.paths.llm_cache))
    resume_command = f"plan {run_id} --client {client} --project {project}"

    def draft_note() -> str:
        if orchestrator.paths.draft_brief.exists():
            return (
                f"your draft brief is kept at {orchestrator.paths.draft_brief}; "
                "running the same command again resumes it. Nothing is approved."
            )
        return "no draft had been started. Nothing is approved."

    with _ends_on_provider_failure(guard, command=resume_command, saved=draft_note):
        session = PlannerSession(
            orchestrator,
            model=guard.provider("planner"),
            probe=EvidenceProbe(
                index=index,  # type: ignore[arg-type]
                store=store,
                claims=knowledge.claims,
                classifier=guard.provider(CLASSIFIER_ROLE),
            ),
            context=context,
        )

    typer.secho(f"Planning {run_id} for {client} / {project} (env={env})", bold=True)
    if session.resumed:
        typer.secho(
            f"Resumed the unsigned draft from an earlier session "
            f"({len(session.draft.key_messages)} key message(s)); /brief shows it. "
            "Nothing is approved until you /sign.",
            fg=typer.colors.YELLOW,
        )
    typer.echo(
        "Type to talk. /brief to see the draft, /sign <name> to approve, /quit to leave.\n"
    )

    def leave_unsigned() -> NoReturn:
        kept = session.save_draft()
        typer.secho(
            "\nleft without signing; transcript kept"
            + (
                f", draft kept at {kept} (run `autodeck {resume_command}` to resume it)"
                if kept
                else " (there was no draft to keep)"
            ),
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)

    while True:
        try:
            said = typer.prompt("you", prompt_suffix=" > ").strip()
        except (EOFError, KeyboardInterrupt, typer.Abort):
            # click turns Ctrl-C and Ctrl-D at a prompt into `Abort`; the other two are
            # kept for a caller that supplies its own input.
            leave_unsigned()

        if said in ("/quit", "/exit"):
            leave_unsigned()

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
            with _ends_on_provider_failure(guard, command=resume_command, saved=draft_note):
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
    from autodeck.agents.outline import OutlineError, OutlineResult, build_outline
    from autodeck.audit.gate1 import review_outline
    from autodeck.ir.store import IRStoreError
    from autodeck.knowledge.context_assembler import ContextAssembler
    from autodeck.knowledge.loader import KnowledgeError
    from autodeck.pipeline.orchestrator import Gate, GateBlocked
    from autodeck.providers.registry import ModelRegistry

    orchestrator = _open_run(run_id, runs_root, env)
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

    guard = ProviderGuard(
        ModelRegistry.load(env), cache=ResponseCache(orchestrator.paths.llm_cache)
    )
    built: list[OutlineResult] = []

    def do_outline() -> str:
        result = build_outline(
            brief_doc,
            guard.provider("outline"),
            client=client,
            project=project,
            theme_ref=str(tokens),
            component_lib_version=COMPONENT_LIB_VERSION,
            context=context.to_prompt_context(),
        )
        built.append(result)
        # Re-running replaces v1, and the bytes change with it: that is what invalidates
        # an outline approval given to the previous run (the gate compares fingerprints).
        path = orchestrator.save_ir(result.deck, overwrite=True)
        return f"wrote {path}"

    try:
        with _ends_on_provider_failure(
            guard,
            command=f"outline {run_id} --client {client} --project {project}",
            saved=lambda: (
                "the previous outline, if any, is unchanged. " + _cache_note(orchestrator)
            ),
        ):
            orchestrator.run_stage("outline", do_outline, force=True)
    except OutlineError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    [result] = built
    path = orchestrator.ir.version_path(result.deck.version)
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
    from autodeck.design.headers.flow import flow_report
    from autodeck.design.headers.prompt import resolve_profile
    from autodeck.design.theme.tokens import DesignTokens
    from autodeck.ingest.document_store import DocumentStore
    from autodeck.ingest.provenance import normalise_for_match
    from autodeck.ir.store import IRStoreError
    from autodeck.knowledge.context_assembler import ContextAssembler
    from autodeck.knowledge.loader import KnowledgeError, KnowledgeLoader
    from autodeck.pipeline.orchestrator import Gate, GateBlocked
    from autodeck.pipeline.send_back import SendBackRecord, load_send_backs
    from autodeck.providers.registry import ModelRegistry
    from autodeck.retrieval.hybrid import build_index

    orchestrator = _open_run(run_id, runs_root, env)
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
    guard = ProviderGuard(
        ModelRegistry.load(env), cache=ResponseCache(orchestrator.paths.llm_cache)
    )
    content_command = f"content {run_id}"

    def content_saved() -> str:
        latest = orchestrator.ir.latest_version()
        return f"no IR version was written (the latest is still v{latest}). " + _cache_note(
            orchestrator
        )

    with _ends_on_provider_failure(guard, command=content_command, saved=content_saved):
        model = guard.provider("content")

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
    incomplete: list[str] = []
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
            incomplete.extend(
                f"slide {slide.id}: {finding}" for finding in result.incomplete_slots
            )

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
        path = orchestrator.save_ir(new_deck)
        return f"wrote {path}"

    try:
        with _ends_on_provider_failure(guard, command=content_command, saved=content_saved):
            orchestrator.run_stage("content", do_content, force=True)
    except ContentError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    assert new_deck is not None
    typer.secho(f"\nwrote IR v{new_deck.version}", fg=typer.colors.GREEN)

    if rejections:
        typer.secho(
            f"\n{len(rejections)} block(s) dropped during citation/budget resolution "
            "(one line each; a dropped block is gone from the deck, not shortened):",
            fg=typer.colors.YELLOW,
        )
        for reason in rejections:
            typer.echo(f"  {reason}")

    if incomplete:
        typer.secho(
            f"\n{len(incomplete)} required slot(s) have no block — nothing was written for "
            "them, so nothing was dropped, but a render cannot proceed with them empty:",
            fg=typer.colors.YELLOW,
        )
        for finding in incomplete:
            typer.echo(f"  {finding}")

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

    typer.echo("")
    header_profile = resolve_profile(context.header_profile, brief_doc.header_style)
    typer.echo(flow_report(new_deck, design_tokens, header_profile, brief=brief_doc).render())

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
    from autodeck.providers.registry import ModelRegistry
    from autodeck.retrieval.hybrid import build_index

    orchestrator = _open_run(run_id, runs_root, env)
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
    guard = ProviderGuard(
        ModelRegistry.load(env), cache=ResponseCache(orchestrator.paths.llm_cache)
    )
    validate_command = f"validate {run_id}"

    def validate_saved() -> str:
        return (
            "the validate stage is marked failed, so `gate2` and `approve ... claims` stay "
            f"closed until it completes. {_cache_note(orchestrator)}"
        )

    with _ends_on_provider_failure(guard, command=validate_command, saved=validate_saved):
        model = guard.provider("validation")

    next_version = orchestrator.ir.next_version()
    result: ValidationResult | None = None

    def do_validate() -> str:
        nonlocal result
        deck_to_validate = deck.model_copy(update={"version": next_version})
        result = validate_deck(deck_to_validate, index=index, store=store, model=model)
        path = orchestrator.save_ir(result.deck)
        if guard.failures:
            # The validation pass swallows a provider failure on purpose (an unjudged claim
            # is reported unjudged), so the pass "succeeds" with claims nobody judged. That
            # must not read as a finished validation: fail the stage, so the claims gate
            # cannot be approved over it, and let the re-run replay what did complete.
            raise guard.failures[0].exception
        return f"wrote {path} · {result.provider_calls} provider call(s)"

    try:
        with _ends_on_provider_failure(guard, command=validate_command, saved=validate_saved):
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
    from autodeck.pipeline.orchestrator import assess_render_safety
    from autodeck.pipeline.send_back import load_send_backs

    orchestrator = _open_run(run_id, runs_root)
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

    rendered_report = render(report)
    # A6: every deck ships an audit report. Written every time `gate2` runs, so the file on
    # disk is always the report for the latest IR — not whatever somebody remembered to save.
    orchestrator.paths.audit_report.write_text(rendered_report + "\n", encoding="utf-8")

    typer.echo(rendered_report)
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
        f"\nAudit report written to {orchestrator.paths.audit_report}",
        fg=typer.colors.GREEN,
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


def _describe_action(action: BaseModel) -> str:
    """`set_accent slide_id=s2 accent=accent3` — an action as one readable line."""
    fields = action.model_dump(mode="json", exclude_none=True)
    kind = fields.pop("kind", type(action).__name__)
    return " ".join([str(kind), *(f"{name}={value}" for name, value in fields.items())])


@app.command()
def render(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
    env: EnvOption = "dev",
) -> None:
    """Art-direct, render and critique the approved deck into `runs/<run>/deck.pptx` (3b.10).

    Blocked unless the claims gate is approved for the deck as it is now (A7). Always runs
    every stage, in order: art direction (communication modes by rule, taste by model), then
    the aesthetic loop on true renders, then the final `deck.pptx` and its PNGs under
    `runs/<run>/previews/final`. Each presentation pass writes its result as a new IR version
    that changes no fact, so the claims approval stays current; a pass that changed a claim
    would void it (and `apply_action` refuses to). There is deliberately no option that
    skips a stage. Approves nothing: GATE 3 is `autodeck gate3`, then `autodeck approve`.
    """
    import shutil

    from autodeck.agents.art_direction import ArtDirectionResult, run_art_direction
    from autodeck.design.fonts import FontNotFoundError
    from autodeck.ir.store import IRStoreError
    from autodeck.pipeline.orchestrator import RenderBlocked
    from autodeck.render.qa.aesthetic import (
        AestheticLoopError,
        AestheticResult,
        run_aesthetic_loop,
    )
    from autodeck.render.qa.libreoffice import RenderError, render_pptx
    from autodeck.render.renderer import render_deck

    orchestrator = _open_run(run_id, runs_root, env)
    try:
        orchestrator.require_gate(Gate.CLAIMS)
    except GateBlocked as blocked:
        _echo_error(str(blocked))
        raise typer.Exit(code=3) from None

    try:
        deck = orchestrator.ir.load()
        brief_doc = orchestrator.ir.load_brief()
    except IRStoreError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    paths = orchestrator.paths
    design_tokens = DesignTokens.load(Path(deck.theme_ref))
    guard = ProviderGuard(
        ModelRegistry.load(env), cache=ResponseCache(orchestrator.paths.llm_cache)
    )
    render_command = f"render {run_id}"
    start_version = orchestrator.ir.latest_version()

    def render_saved() -> str:
        latest = orchestrator.ir.latest_version()
        wrote = (
            "no IR version was written"
            if latest == start_version
            else f"IR versions up to v{latest} were written"
        )
        deck_note = (
            f"; {paths.deck_pptx} exists but was not (fully) critiqued"
            if paths.deck_pptx.exists()
            else ""
        )
        return f"{wrote}{deck_note}. {_cache_note(orchestrator)}"

    # Both providers are built before anything is written, so a missing key stops the
    # command with nothing half-done.
    with _ends_on_provider_failure(guard, command=render_command, saved=render_saved):
        art_model = guard.provider("outline")
        aesthetic_model = guard.provider("aesthetic")

    # -- art direction -----------------------------------------------------------------

    art_result: ArtDirectionResult | None = None
    directed: Deck = deck

    def do_art_direction() -> str:
        nonlocal art_result, directed
        shutil.rmtree(paths.previews / "art_direction", ignore_errors=True)
        art_result = run_art_direction(
            deck,
            brief=brief_doc,
            tokens=design_tokens,
            model=art_model,
            work_dir=paths.previews / "art_direction",
        )
        directed = art_result.deck.model_copy(
            update={"version": orchestrator.ir.next_version()}
        )
        return f"wrote {orchestrator.save_ir(directed)}"

    try:
        with _ends_on_provider_failure(guard, command=render_command, saved=render_saved):
            orchestrator.run_stage("art_direction", do_art_direction, force=True)
    except FileNotFoundError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    except (RenderError, FontNotFoundError) as exc:
        _echo_error(f"art direction could not render a trial: {exc}")
        raise typer.Exit(code=1) from None
    except RenderBlocked as blocked:
        _echo_error(str(blocked))
        raise typer.Exit(code=4) from None

    assert art_result is not None
    typer.secho("Art direction", bold=True, fg=typer.colors.CYAN)
    for slide in directed.slides:
        decision = art_result.modes.get(slide.id)
        if decision is not None:
            note = f" - {decision.note}" if decision.note else ""
            typer.echo(
                f"  {slide.id:<10} {decision.mode:<14} ({decision.source}) "
                f"{slide.component}{note}"
            )
    typer.echo(
        f"  {len(art_result.applied)} action(s) applied, {len(art_result.rejected)} rejected"
    )
    for applied in art_result.applied:
        typer.echo(f"    applied  {_describe_action(applied)}")
    for rejected in art_result.rejected:
        typer.echo(f"    rejected {_describe_action(rejected.action)}: {rejected.reason}")
    if art_result.rationale:
        typer.echo(f"  Rationale: {art_result.rationale}")
    if art_result.stopped == "model_error":
        typer.secho(
            f"  The art-direction model did not answer ({art_result.detail}); modes were "
            "assigned by rule only.",
            fg=typer.colors.YELLOW,
        )
    if art_result.grammar:
        typer.echo(f"  {len(art_result.grammar)} grammar finding(s) on the directed deck:")
        for finding in art_result.grammar:
            typer.echo(f"    {finding}")
    typer.secho(f"wrote IR v{directed.version}", fg=typer.colors.GREEN)

    if art_result.render_error:
        if guard.failures:
            # The model that was meant to supply what this deck lacks (icons) never answered:
            # that is a quota or a key to fix, not a defect in the slide.
            _echo_error(
                "\n"
                + _provider_failure_message(
                    guard.failures[0], command=render_command, saved=render_saved()
                )
                + _undrawn_deck_note(directed, run_id, art_result.render_error)
            )
            raise typer.Exit(code=EXIT_PROVIDER_FAILURE)
        _echo_error(
            f"\nThe art-directed deck does not render: {art_result.render_error}\n"
            f"IR v{directed.version} is saved. Nothing was rendered; fix the slide it names "
            "and run `autodeck render` again."
        )
        raise typer.Exit(code=4)

    # -- aesthetic loop and final render -----------------------------------------------

    loop_result: AestheticResult | None = None
    final_deck: Deck = directed
    final_images: list[Path] = []

    def do_render() -> str:
        nonlocal loop_result, final_deck, final_images
        shutil.rmtree(paths.previews / "aesthetic", ignore_errors=True)
        shutil.rmtree(paths.previews / "final", ignore_errors=True)
        loop_result = run_aesthetic_loop(
            directed,
            tokens=design_tokens,
            model=aesthetic_model,
            work_dir=paths.previews / "aesthetic",
            pins=brief_doc.layout_pins,
        )
        final_deck = loop_result.deck
        if final_deck.model_dump(mode="json") != directed.model_dump(mode="json"):
            final_deck = final_deck.model_copy(
                update={"version": orchestrator.ir.next_version()}
            )
            orchestrator.save_ir(final_deck)
        render_deck(final_deck, tokens=design_tokens, out_path=paths.deck_pptx)
        final_images = render_pptx(
            paths.deck_pptx, paths.previews / "final", design_tokens
        ).images
        return f"wrote {paths.deck_pptx}"

    try:
        with _ends_on_provider_failure(guard, command=render_command, saved=render_saved):
            orchestrator.run_stage("render", do_render, force=True)
    except AestheticLoopError as exc:
        _echo_error(f"\n{exc}\nIR v{directed.version} is saved; no deck was written.")
        raise typer.Exit(code=4) from None
    except (RenderError, FontNotFoundError) as exc:
        _echo_error(
            f"\nThe deck could not be rendered: {exc}\nIR v{directed.version} is saved "
            "(art direction); no final deck was written."
        )
        raise typer.Exit(code=1) from None
    except RenderBlocked as blocked:
        _echo_error(str(blocked))
        raise typer.Exit(code=4) from None

    assert loop_result is not None
    typer.secho("\nAesthetic loop", bold=True, fg=typer.colors.CYAN)
    score = "none" if loop_result.best_score is None else f"{loop_result.best_score:g}/10"
    detail = f" ({loop_result.detail})" if loop_result.detail else ""
    typer.echo(f"  Stopped: {loop_result.stopped}{detail}. Best score: {score}.")
    for iteration in loop_result.iterations:
        typer.echo(
            f"  iteration {iteration.index}: score {iteration.score:g}, "
            f"{iteration.qa_findings} QA finding(s), {len(iteration.applied)} applied, "
            f"{len(iteration.rejected)} rejected"
        )
        for applied in iteration.applied:
            typer.echo(f"    applied  {_describe_action(applied)}")
        for rejected in iteration.rejected:
            typer.echo(f"    rejected {_describe_action(rejected.action)}: {rejected.reason}")
    if final_deck.version != directed.version:
        typer.secho(f"wrote IR v{final_deck.version}", fg=typer.colors.GREEN)

    typer.secho(f"\nWrote {paths.deck_pptx}", fg=typer.colors.GREEN)
    typer.echo(f"Rendered {len(final_images)} slide(s) to PNG in {paths.previews / 'final'}")
    typer.echo(f"What the critic saw, per iteration: {paths.previews / 'aesthetic'}")

    if guard.failures:
        # The art-direction and critique passes swallow a provider failure on purpose (the
        # rule and the best deck so far stand in), so the command "succeeds" with a deck
        # that was not critiqued. Say so as loudly as any other provider failure.
        _echo_error(
            "\n"
            + _provider_failure_message(
                guard.failures[0], command=render_command, saved=render_saved()
            )
        )
        raise typer.Exit(code=EXIT_PROVIDER_FAILURE)

    if loop_result.stopped == "model_error" or art_result.stopped == "model_error":
        typer.secho(
            "\nThe deck was not (fully) critiqued: a model call failed (details above). The "
            f"deck is rendered and safe to review; run `autodeck {render_command}` again to "
            "retry the critique (completed provider calls replay from the cache).",
            fg=typer.colors.YELLOW,
        )

    typer.echo(f"\nNext: autodeck gate3 {run_id}")


@app.command()
def gate3(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
    env: EnvOption = "dev",
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
) -> None:
    """The GATE 3 review surface: deck, final audit and manifest, together (3b.10, A7).

    Recomputes everything from the files on disk - the latest IR and `runs/<run>/deck.pptx` -
    so the report describes the exact deck `autodeck approve <run> final_render` will
    fingerprint. Writes `final_audit_report.md` and `build_manifest.json`, then prints their
    paths with the deck's first, the report, and the five PowerPoint checks only a person can
    do. Exits non-zero when a checkable criterion fails. As with `gate2`, this reports and
    never decides: a clean run here is not the gate.

    Requires a current claims approval (exit 3 otherwise): a final audit over claims that are
    no longer the approved ones would print PASS lines about a deck nobody may ship. It
    records what it concluded (`Orchestrator.record_final_assessment`) so `approve ...
    final_render` can refuse a deck this audit did not describe or did not pass. The terminal
    shows the three paths, the four criteria, the findings, the header flow and the human
    checklist; the full claim-level audit (a repeat of GATE 2) goes only to the report file.
    """
    from autodeck.audit.gate3 import assess_final, render_final_report
    from autodeck.audit.report import build_audit_report
    from autodeck.audit.report import render as render_audit
    from autodeck.design.headers.prompt import resolve_profile
    from autodeck.ir.store import IRStoreError
    from autodeck.knowledge.context_assembler import ContextAssembler
    from autodeck.knowledge.loader import KnowledgeError
    from autodeck.pipeline.orchestrator import assess_render_safety

    orchestrator = _open_run(run_id, runs_root, env)
    try:
        orchestrator.require_gate(Gate.CLAIMS)
    except GateBlocked as blocked:
        _echo_error(str(blocked))
        raise typer.Exit(code=3) from None
    paths = orchestrator.paths
    if not orchestrator.state.is_complete("render") or not paths.deck_pptx.exists():
        _echo_error(
            f"run {run_id!r} has no rendered deck. Run `autodeck render {run_id}` first."
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

    try:
        context = ContextAssembler(
            knowledge_root, client=deck.client, project=deck.project
        ).assemble()
    except KnowledgeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    profile = resolve_profile(
        context.header_profile, brief_doc.header_style if brief_doc is not None else None
    )

    design_tokens = DesignTokens.load(Path(deck.theme_ref))
    assessment = assess_final(
        deck, paths.deck_pptx, tokens=design_tokens, brief=brief_doc, profile=profile
    )
    safety = assess_render_safety(deck)
    audit_report = build_audit_report(
        deck, brief=brief_doc, numeric=safety.numeric, framing=safety.framing
    )
    report_text = render_final_report(assessment, audit_report=render_audit(audit_report))
    paths.final_audit_report.write_text(report_text, encoding="utf-8")
    shown_text = render_final_report(
        assessment,
        audit_report=(
            f"The claim-level audit is in `{paths.final_audit_report}` (it repeats the GATE 2 "
            "table you have already reviewed)."
        ),
    )
    orchestrator.record_final_assessment(assessment.deck_digest, assessment.passes)

    registry = ModelRegistry.load(env)
    latest = orchestrator.ir.latest_version()
    assert latest is not None

    def write_manifest() -> str:
        manifest = build_manifest(
            run_id=run_id,
            env=registry.env,
            models=registry.manifest_entry(),
            prompts_dir=Path("prompts"),
            knowledge_dir=knowledge_root,
            ir_path=orchestrator.ir.version_path(latest),
        )
        manifest.save(paths.manifest_file)
        return f"wrote {paths.manifest_file}"

    orchestrator.run_stage("audit", write_manifest, force=True)

    # The task's definition of done: the owner gets all three together, so all three first.
    typer.secho("GATE 3 - the owner gets these together", bold=True, fg=typer.colors.CYAN)
    typer.echo(f"  Deck:               {paths.deck_pptx}")
    typer.echo(f"  Final audit report: {paths.final_audit_report}")
    typer.echo(f"  Build manifest:     {paths.manifest_file}")
    typer.echo("")
    typer.echo(shown_text)
    typer.echo("=" * 78)
    for label, passed, detail in assessment.checkable():
        typer.secho(
            f"  [{'PASS' if passed else 'FAIL'}] {label}",
            fg=typer.colors.GREEN if passed else typer.colors.RED,
        )
        typer.echo(f"         {detail}")
    typer.secho(
        f"\nApprove with `autodeck approve {run_id} final_render` after doing the five "
        "PowerPoint checks above; the approval records the deck digest shown "
        f"({assessment.deck_digest[:16]}...). A clean run above is not the gate.",
        fg=typer.colors.YELLOW,
    )

    if not assessment.passes:
        raise typer.Exit(code=4)


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

    orchestrator = _open_run(run_id, runs_root)
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
