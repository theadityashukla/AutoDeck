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
from typing import Annotated, NoReturn

import typer
from pydantic import BaseModel

from autodeck.audit.gate2 import gate2_checks
from autodeck.audit.manifest import build_manifest, session_record
from autodeck.design.components.catalog import COMPONENT_LIB_VERSION
from autodeck.design.theme.tokens import DesignTokens
from autodeck.dotenv import load_dotenv
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
from autodeck.pipeline.planning import MeetingPlanning, RedesignPlanning
from autodeck.providers.cache import ResponseCache
from autodeck.providers.guard import ProviderFailureRecord, ProviderGuard
from autodeck.providers.registry import ModelRegistry, default_env_name

app = typer.Typer(
    name="autodeck",
    help="Accuracy-first consulting decks as native, editable PPTX.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _load_local_env() -> None:
    """Fill provider keys missing from the environment from `./.env` (never overrides)."""
    load_dotenv()


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
memory_app = typer.Typer(
    help="What the agent remembers between runs (engagement and owner).", no_args_is_help=True
)
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(memory_app, name="memory")
meeting_app = typer.Typer(
    help="Local, offline transcription of meeting recordings.", no_args_is_help=True
)
app.add_typer(meeting_app, name="meeting")

#: The registry's `default_env` (config/models.yaml), not a hard-coded name.
DEFAULT_ENV = default_env_name()

EnvOption = Annotated[
    str,
    typer.Option(
        "--env", help="Provider environment from config/models.yaml (see `autodeck models`)."
    )
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
        # Limits differ by provider and plan: some are per minute, some per day.
        meaning = (
            "This is a request limit. A per-minute limit clears in a minute or two; a "
            "daily quota resets daily, so running the command again sooner will not help."
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


def _open_run(run_id: str, runs_root: Path, env: str = DEFAULT_ENV) -> Orchestrator:
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
def models(env: EnvOption = DEFAULT_ENV) -> None:
    """Show the resolved provider bindings for an environment."""
    registry = ModelRegistry.load(env)
    typer.secho(f"environment: {registry.env}", bold=True)
    typer.echo(f"  design mode  {registry.design_mode} (default for this environment)")
    for role, binding in sorted(registry.bindings().items()):
        typer.echo(f"  {role:<12} {binding.provider:<8} {binding.model}")

    missing = registry.missing_credentials()
    if missing:
        typer.secho(f"\nmissing credentials: {', '.join(missing)}", fg=typer.colors.YELLOW)

    if registry.env.startswith("dev"):
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
    env: EnvOption = DEFAULT_ENV,
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
            provenance_mode=orchestrator.ir.load().provenance,
            run_sources=run_source_hashes(orchestrator.paths.root),
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
    accept_risk: Annotated[
        list[str],
        typer.Option(
            "--accept-risk",
            help=(
                "Draft-first runs, brief only: carry a weak key message as a named risk, "
                "e.g. --accept-risk km2 or --accept-risk 'km2=one trial only'. Repeatable."
            ),
        ),
    ] = [],  # noqa: B006 — typer reads the default; it is never mutated
) -> None:
    """Record a human approval for one of the four A7 gates.

    Separate from `run` on purpose: there is no flag on `run` that approves a gate, and
    there must never be one. The approval is bound to the artifact as it is now (its
    sha256 is stored beside your name), and it is refused when that artifact does not exist
    yet.

    On a draft-first run (B43) approving the brief first records the draft's brief, with
    each weak key message carried only if you name it in `--accept-risk` (B48).
    """
    orchestrator = _open_run(run_id, runs_root)
    if gate is Gate.BRIEF and orchestrator.is_draft_first:
        from autodeck.pipeline.draft import DraftBriefError, finalise_draft_brief

        accepted = dict(
            [*item.split("=", 1), ""][:2] for item in (r.strip() for r in accept_risk) if item
        )
        try:
            finalise_draft_brief(orchestrator, approver=approver, accepted_risks=accepted)
        except DraftBriefError as exc:
            _echo_error(str(exc))
            raise typer.Exit(code=1) from None
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
        str, typer.Option("--flavor", help="standard or strict.")
    ] = "standard",
) -> None:
    """Print the Deck IR JSON schema in a provider dialect."""
    from autodeck.ir.schema import SchemaFlavor, export_schema

    if flavor not in ("standard", "strict"):
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


def _open_memory(knowledge_root: Path, client: str, project: str, run_id: str):  # type: ignore[no-untyped-def]
    """A `MemoryStore` for a client and project that exist in the knowledge root.

    The store's isolation guard resolves paths, so a crafted name such as `../globex` would
    pass it; the names are therefore checked against the folders that exist.
    """
    from autodeck.knowledge.loader import KnowledgeError, KnowledgeLoader
    from autodeck.knowledge.memory import MemoryStore
    from autodeck.ui.profile import owner_memory_path

    loader = KnowledgeLoader(knowledge_root)
    if client not in loader.client_names() or project not in loader.project_names():
        raise KnowledgeError(
            f"no client {client!r} with project {project!r} in {knowledge_root}"
        )
    return MemoryStore(
        knowledge_root,
        client=client,
        project=project,
        run_id=run_id,
        owner_path=owner_memory_path(),
    )


def _memory_store(knowledge_root: Path, client: str, project: str, run_id: str):  # type: ignore[no-untyped-def]
    """The agent's memory for this build (B77), or None (with a note) when it cannot open."""
    from autodeck.knowledge.loader import KnowledgeError

    try:
        return _open_memory(knowledge_root, client, project, run_id)
    except KnowledgeError as exc:
        typer.secho(f"agent memory is off for this build: {exc}", fg=typer.colors.YELLOW)
        return None


def _memory_cli_store(knowledge_root: Path, client: str, project: str):  # type: ignore[no-untyped-def]
    from autodeck.knowledge.loader import KnowledgeError

    try:
        return _open_memory(knowledge_root, client, project, "cli")
    except KnowledgeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None


@memory_app.command("show")
def memory_show(
    client: Annotated[str, typer.Option("--client", help="The client's folder name.")],
    project: Annotated[str, typer.Option("--project", help="The project's folder name.")],
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
) -> None:
    """Print the engagement memory for a client and project, and the owner memory."""
    from autodeck.knowledge.loader import KnowledgeError

    store = _memory_cli_store(knowledge_root, client, project)
    try:
        engagement = store.read("engagement")
    except KnowledgeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    typer.echo(f"Engagement memory ({store.engagement_path})\n")
    typer.echo(engagement)
    typer.echo(f"Owner memory ({store.owner_path})\n")
    typer.echo(store.read("owner"))


@memory_app.command("forget")
def memory_forget(
    client: Annotated[str, typer.Option("--client", help="The client's folder name.")],
    project: Annotated[str, typer.Option("--project", help="The project's folder name.")],
    scope: Annotated[str, typer.Option("--scope", help="engagement or owner.")],
    section: Annotated[str, typer.Option("--section", help="The section the item is under.")],
    item: Annotated[
        str, typer.Option("--item", help="The item's text (a unique part is enough).")
    ],
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
) -> None:
    """Drop one remembered item."""
    from autodeck.knowledge.loader import KnowledgeError

    if scope not in ("engagement", "owner"):
        _echo_error("--scope is engagement or owner")
        raise typer.Exit(code=1)
    store = _memory_cli_store(knowledge_root, client, project)
    try:
        typer.echo(store.remove(scope, section, item))  # type: ignore[arg-type]
    except KnowledgeError as exc:  # MemoryWriteError and ClientIsolationError
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None


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
    env: EnvOption = DEFAULT_ENV,
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
    from autodeck.agents.planner import BriefIncomplete, PlannerError, render_draft
    from autodeck.pipeline.planning import PlanningSetupError, prepare_planning

    try:
        planning = prepare_planning(
            run_id,
            client=client,
            project=project,
            env=env,
            knowledge_root=knowledge_root,
            corpus_root=corpus_root,
            runs_root=runs_root,
        )
    except PlanningSetupError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=exc.exit_code) from None

    orchestrator = planning.orchestrator
    guard = planning.guard
    resume_command = f"plan {run_id} --client {client} --project {project}"

    def draft_note() -> str:
        if orchestrator.paths.draft_brief.exists():
            return (
                f"your draft brief is kept at {orchestrator.paths.draft_brief}; "
                "running the same command again resumes it. Nothing is approved."
            )
        return "no draft had been started. Nothing is approved."

    with _ends_on_provider_failure(guard, command=resume_command, saved=draft_note):
        session = planning.open_session()

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
    env: EnvOption = DEFAULT_ENV,
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
    env: EnvOption = DEFAULT_ENV,
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


def _validation_terms(
    knowledge_root: Path, client: str, project: str, run_id: str, run_root: Path
) -> list[str]:
    """The engagement memory's Terms, to show the validator as context (B79).

    Snapshotted to `runs/<run>/validation-terms.json` (A6) when there are any; a stale file
    is removed when there are none. A project with no memory (or no such client) has none.
    """
    from autodeck.knowledge.loader import KnowledgeError

    terms: list[str] = []
    try:
        terms = _open_memory(knowledge_root, client, project, run_id).terms()
    except (KnowledgeError, OSError):
        typer.secho("no engagement terms for the validator (no memory).", dim=True)
    path = Path(run_root) / "validation-terms.json"
    if terms:
        _write_json(path, {"terms": terms})
    else:
        path.unlink(missing_ok=True)
    return terms


@app.command()
def validate(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    env: EnvOption = DEFAULT_ENV,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
) -> None:
    """Validate every claim in the latest IR (A3) and write the verdicts as a new version.

    Blocked unless `autodeck content` has run — there is nothing to independently verify
    before it has. Prints the claims table `verdicts.VerdictReport.render()` produces;
    `autodeck gate2` is the surface that turns this into a reviewable report. A redesign or
    meeting run is checked against its own source (plus the papers only if its paper check is
    on); the engagement's Terms are shown to the validator as context, never as evidence.
    """
    from autodeck.agents.validation import ValidationAgentError, ValidationResult, validate_deck
    from autodeck.ingest.document_store import DocumentStore
    from autodeck.ir.store import IRStoreError
    from autodeck.providers.registry import ModelRegistry
    from autodeck.retrieval.hybrid import build_index

    orchestrator = _open_run(run_id, runs_root, env)
    composed = orchestrator.state.is_complete("compose")
    if not (orchestrator.state.is_complete("content") or composed):
        _echo_error(
            f"run {run_id!r} has no content yet. Run `autodeck content {run_id}` first."
        )
        raise typer.Exit(code=3)

    try:
        deck = orchestrator.ir.load()
    except IRStoreError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    # Draft-first runs revalidate after revisions; claims unchanged since the last completed
    # validate keep their verdicts (B44). The gate-first path never passes `previous`.
    previous = None
    last_validated = orchestrator.state.stages.get("validate")
    if composed and last_validated is not None and last_validated.ir_version is not None:
        try:
            previous = orchestrator.ir.load(last_validated.ir_version)
        except IRStoreError:
            previous = None

    from autodeck.pipeline.planning import PlanningSetupError, run_source_store

    try:
        run_source = run_source_store(
            runs_root, run_id, corpus_root=corpus_root, project=deck.project, env=env
        )
    except PlanningSetupError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=exc.exit_code) from None
    if run_source is not None:
        # A redesign or a meeting is checked against what it was built from: the run-local
        # source, plus the papers only if the person turned that check on (B41, B49, B78).
        # The index is still built here, independently of the writer's pack (A3).
        store, documents = run_source
    else:
        store = DocumentStore(corpus_root / deck.project)
        documents = list(store.documents())
        if not documents:
            _echo_error(
                f"no ingested documents under {corpus_root / deck.project}. Run "
                f"`autodeck knowledge ingest {deck.project}` first."
            )
            raise typer.Exit(code=2)
        if deck.provenance == "normal":
            # B55: a claim that cites the person's own words is checked against them too. The
            # conversation is read from the run's own folder, never put into the index (A3).
            from autodeck.ingest.deck_source import run_source_root
            from autodeck.ingest.multi_store import MultiStore

            store = MultiStore(run_source_root(runs_root, run_id), corpus_root / deck.project)
    terms = _validation_terms(
        knowledge_root, deck.client, deck.project, run_id, orchestrator.paths.root
    )
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
        result = validate_deck(
            deck_to_validate,
            index=index,
            store=store,
            model=model,
            previous=previous,
            terms=terms,
        )
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
        deck,
        brief=brief_doc,
        numeric=safety.numeric,
        framing=safety.framing,
        meeting_times=_meeting_times(orchestrator.paths.root),
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
    for label, passed, detail in gate2_checks(brief_doc, safety, report):
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


_gate2_checks = gate2_checks  # kept for tests and callers that import the old name


# ---------------------------------------------------------------------------
# draft-first: clarify / answer / draft / revise (Phase 3c, B43 to B48)
# ---------------------------------------------------------------------------
#
# One prompt, one deterministic evidence pack, then three model calls before a draft can be
# read: `clarify` (what the draft will assume, and the few questions that would change it),
# `draft` (brief, outline and every slide, citations resolved in code) and `validate`.
# `revise` redoes only what an instruction touches. Nothing here approves anything: the four
# approvals are `autodeck approve`, given on the assembled draft (A7, B43), and no command
# in this section takes an option that approves.

EXIT_NEEDS_INPUT = 3

COMPOSE_MAX_OUTPUT_TOKENS = 32768


def _draft_setup(
    run_id: str,
    *,
    client: str | None,
    project: str | None,
    env: str,
    knowledge_root: Path,
    corpus_root: Path,
    runs_root: Path,
    clarify_data: dict | None,
):  # type: ignore[no-untyped-def]
    """Open an existing run and load what a compose-family call needs (A4 enforced).

    Client and project come from the options, else the clarify file, else the UI's run
    meta. Returns the planning context (orchestrator, guard, assembled context, index,
    store, claims) and the resolved client and project. A redesign or meeting run comes back
    as a `RedesignPlanning` or `MeetingPlanning` (`prepare_planning` looks at the run folder).
    """
    from autodeck.pipeline.planning import PlanningSetupError, prepare_planning
    from autodeck.ui.api import Roots, read_run_meta

    _open_run(run_id, runs_root, env)  # a mistyped id must not create a run
    meta = read_run_meta(Roots(runs=runs_root, env=env), run_id)
    data = clarify_data or {}
    client = client or data.get("client") or meta.get("client")
    project = project or data.get("project") or meta.get("project")
    if not client or not project:
        _echo_error(
            f"run {run_id!r} does not say which client and project it is for. Pass "
            "--client and --project."
        )
        raise typer.Exit(code=1)
    try:
        planning = prepare_planning(
            run_id,
            client=client,
            project=project,
            env=env,
            knowledge_root=knowledge_root,
            corpus_root=corpus_root,
            runs_root=runs_root,
        )
    except PlanningSetupError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=exc.exit_code) from None
    return planning, client, project


ProvenanceOption = Annotated[
    str | None,
    typer.Option(
        "--provenance",
        help=(
            "strict (MLR: document spans only) or normal (also what you typed, and checked "
            "general knowledge). Default: the project's setting. Only valid before the run's "
            "mode is fixed (B55)."
        ),
    ),
]


def _provenance_override(value: str | None):  # type: ignore[no-untyped-def]
    if value is None:
        return None
    if value not in ("strict", "normal"):
        _echo_error("--provenance must be 'strict' or 'normal'.")
        raise typer.Exit(code=1)
    return value


def _start_run_mode(  # type: ignore[no-untyped-def]
    run_root: Path, *, knowledge_root: Path, project: str, override: str | None = None
):
    """Fix (or read) the run's provenance mode when a draft-first run starts (B55).

    The project's setting is snapshotted into `runs/<run>/provenance.json`; an `override` is
    refused once a snapshot exists and differs. Failures are clean CLI errors (exit 1).
    """
    from autodeck.knowledge.loader import KnowledgeError, load_project_settings
    from autodeck.pipeline.provenance import ProvenanceModeError, resolve_mode

    try:
        return resolve_mode(
            run_root,
            load_project_settings(knowledge_root, project),
            _provenance_override(override),
        )
    except (KnowledgeError, ProvenanceModeError) as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None


DesignModeOption = Annotated[
    str | None,
    typer.Option(
        "--design-mode",
        help=(
            "structured (catalog layouts) or creative (the writer designs each slide). "
            "Default: the environment's setting in config/models.yaml. Only valid before the "
            "run's mode is fixed (B69)."
        ),
    ),
]


def _start_design_mode(  # type: ignore[no-untyped-def]
    run_root: Path, *, env: str, override: str | None = None
):
    """Fix (or read) the run's design mode when a run starts (B69), as a clean CLI error."""
    from autodeck.pipeline.design_mode import DesignModeError, resolve_design_mode

    if override is not None and override not in ("structured", "creative"):
        _echo_error("--design-mode must be 'structured' or 'creative'.")
        raise typer.Exit(code=1)
    try:
        return resolve_design_mode(run_root, ModelRegistry.load(env).design_mode, override)
    except DesignModeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None


def _design_mode(run_root: Path):  # type: ignore[no-untyped-def]
    """The run's fixed design mode (`structured` when it has none)."""
    from autodeck.pipeline.design_mode import DesignModeError, load_design_mode

    try:
        return load_design_mode(run_root)
    except DesignModeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None


def _project_named_terms(knowledge_root: Path, project: str) -> list[str]:
    """The project's glossary of names that contain digits (B58), as a clean CLI error."""
    from autodeck.knowledge.loader import KnowledgeError, load_project_settings

    try:
        return list(load_project_settings(knowledge_root, project).named_terms)
    except KnowledgeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None


def _run_mode(run_root: Path):  # type: ignore[no-untyped-def]
    """The run's fixed mode (`strict` when it has none), as a clean error on a bad file."""
    from autodeck.pipeline.provenance import ProvenanceModeError, load_mode

    try:
        return load_mode(run_root)
    except ProvenanceModeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None


def _with_conversation_source(  # type: ignore[no-untyped-def]
    planning, pack, *, run_id: str, runs_root: Path, corpus_root: Path, project: str, mode
):
    """`(pack, store)` for a compose-family call in `mode` (B55).

    `normal`: what the person typed is written to `runs/<run>/source/` and added to the pack,
    and the store reads that folder as well as the project's papers, so a `conversation--`
    quote resolves. A meeting run reads the papers only if its paper check is on (the corpus
    folder is not touched otherwise). `strict` and any redesign: unchanged.
    """
    if mode != "normal" or isinstance(planning, RedesignPlanning):
        return pack, planning.store
    from autodeck.agents.evidence_pack import with_conversation
    from autodeck.ingest.conversation_source import conversation_document, ingest_conversation
    from autodeck.ingest.deck_source import run_source_root
    from autodeck.ingest.multi_store import MultiStore

    run_root = planning.orchestrator.paths.root
    ingest_conversation(run_root, run_id)
    papers = corpus_root / project
    if isinstance(planning, MeetingPlanning) and not planning.settings["check_papers"]:
        papers = None
    store = MultiStore(run_source_root(runs_root, run_id), papers)
    return with_conversation(pack, conversation_document(run_root, run_id), mode), store


def _meeting_times(run_root: Path) -> dict[str, dict[int, float]]:
    """`{transcript doc id: {page: start seconds}}` for the audit labels; `{}` off a meeting."""
    from autodeck.ingest.transcript_source import meeting_times

    return meeting_times(run_root)


def run_source_hashes(run_root: Path) -> dict[str, str]:
    """`{name: sha256}` of what a run was built from, for the manifest (A6, B55, B78).

    `source/*.json` are keyed by doc id (the run-local documents: the conversation, a client
    deck, the meeting transcript). A meeting run's `meeting/*.json` (transcript, settings,
    times) are keyed `meeting/<file>`, and the engagement terms the validator was shown are
    keyed `validation-terms`.
    """
    from autodeck.audit.manifest import file_sha256

    root = Path(run_root)
    out: dict[str, str] = {}
    folder = root / "source"
    if folder.is_dir():
        out.update({path.stem: file_sha256(path) for path in sorted(folder.glob("*.json"))})
    meeting = root / "meeting"
    if meeting.is_dir():
        out.update(
            {
                f"meeting/{path.name}": file_sha256(path)
                for path in sorted(meeting.glob("*.json"))
            }
        )
    terms = root / "validation-terms.json"
    if terms.is_file():
        out["validation-terms"] = file_sha256(terms)
    return out


def _pack_for(planning, text: str, extra_queries: tuple[str, ...] = ()):  # type: ignore[no-untyped-def]
    from autodeck.agents.evidence_pack import (
        build_evidence_pack,
        build_redesign_pack,
        with_transcript,
    )

    if isinstance(planning, RedesignPlanning):
        return build_redesign_pack(
            planning.deck_document,
            check_papers=bool(planning.settings["check_papers"]),
            project_md=planning.assembled.project_md,
            claims=planning.claims,
            index=planning.index,
        )
    pack = build_evidence_pack(
        text,
        project_md=planning.assembled.project_md,
        claims=planning.claims,
        index=planning.index,
        extra_queries=extra_queries,
    )
    if isinstance(planning, MeetingPlanning):
        # A short meeting is read whole, never trimmed; a long one by retrieval alone (B78).
        pack = with_transcript(pack, planning.transcript_document)
    return pack


def _answer_queries(clarify_data: dict | None) -> tuple[str, ...]:
    """Each answered clarify question as one retrieval query: the question and its answer."""
    from autodeck.pipeline.clarify_state import answer_pairs

    out: list[str] = []
    for pair in answer_pairs(clarify_data or {}):
        out.append(pair if isinstance(pair, str) else f"{pair[0]} {pair[1]}")
    return tuple(out)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_coverage_file(orchestrator: Orchestrator) -> dict:
    try:
        data = json.loads((orchestrator.paths.root / "coverage.json").read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_coverage_file(orchestrator: Orchestrator, result, *, ir_version: int) -> None:  # type: ignore[no-untyped-def]
    # A redesign's layout notes survive a revision, which does not produce its own.
    changes = getattr(result, "changes", None) or _read_coverage_file(orchestrator).get(
        "changes"
    )
    _write_json(
        orchestrator.paths.root / "coverage.json",
        {
            **({"changes": changes} if changes else {}),
            "ir_version": ir_version,
            "coverage": result.coverage,
            "origins": result.origins,
            "rejections": result.rejections,
            "failures": [r.to_dict() for r in getattr(result, "failures", [])],
            "advisories": [r.to_dict() for r in getattr(result, "advisories", [])],
            "repairs": list(getattr(result, "repairs", [])),
            "repair_ran": bool(getattr(result, "repair_ran", False)),
            "provider_calls": getattr(result, "provider_calls", 1),
            "provenance": result.deck.provenance,
            "corrections": result.corrections,
            "incomplete_slots": result.incomplete_slots,
            "notes": result.notes if isinstance(result.notes, str) else "; ".join(result.notes),
        },
    )


def _print_draft_summary(result, deck: Deck) -> None:  # type: ignore[no-untyped-def]
    typer.echo(f"\n{len(deck.slides)} slide(s), {len(deck.claim_sites())} claim(s):")
    for slide in deck.slides:
        served = ", ".join(slide.message_ids) or "-"
        typer.echo(
            f"  {slide.id:<8} {slide.component:<22} {len(slide.blocks)} block(s)  [{served}]"
        )
    typer.echo("\nKey messages:")
    for message in result.draft_brief.key_messages:
        typer.echo(
            f"  {message.id:<6} {message.evidence_status.upper():<12} "
            f"{_shorten(message.text, 80)}"
        )
    if result.coverage:
        typer.echo("\nCoverage:")
        for entry in result.coverage:
            typer.echo(
                f"  {entry['status']:<9} {_shorten(entry['item'], 60)} — "
                f"{_shorten(entry['detail'], 100)}"
            )
    if result.rejections:
        typer.secho(f"\n{len(result.rejections)} block(s) dropped:", fg=typer.colors.YELLOW)
        for reason in result.rejections:
            typer.echo(f"  {reason}")
    if getattr(result, "repair_ran", False):
        repairs = list(getattr(result, "repairs", []))
        declined = sum(1 for line in repairs if "declin" in line.casefold())
        typer.secho(
            f"\nrepair call: {len(repairs) - declined} replaced, {declined} declined",
            fg=typer.colors.YELLOW,
        )
        for line in repairs:
            typer.echo(f"  {line}")
    for correction in result.corrections:
        typer.secho(f"corrected: {correction}", fg=typer.colors.YELLOW)
    for finding in result.incomplete_slots:
        typer.secho(f"incomplete: {finding}", fg=typer.colors.YELLOW)


@app.command()
def clarify(
    run_id: Annotated[str, typer.Argument(help="Run identifier (created if new).")],
    client: Annotated[str, typer.Option("--client", help="Client namespace (A4).")],
    project: Annotated[str, typer.Option("--project", help="Project whose corpus to use.")],
    prompt: Annotated[str, typer.Option("--prompt", help="What the deck is for.")],
    env: EnvOption = DEFAULT_ENV,
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
    provenance: ProvenanceOption = None,
    design_mode: DesignModeOption = None,
) -> None:
    """Show what the draft will assume and ask what would change it (B47, B48).

    One short model call over the request and the evidence pack. Writes
    `runs/<run>/clarify.json` (assumptions, questions, no answers yet). Answer with
    `autodeck answer`, then `autodeck draft`. Approves nothing.
    """
    from autodeck.pipeline.planning import PlanningSetupError, prepare_planning
    from autodeck.ui.api import Roots, write_run_meta

    if not prompt.strip():
        _echo_error("--prompt is empty: say what the deck is for.")
        raise typer.Exit(code=1)
    try:
        planning = prepare_planning(
            run_id,
            client=client,
            project=project,
            env=env,
            knowledge_root=knowledge_root,
            corpus_root=corpus_root,
            runs_root=runs_root,
        )
    except PlanningSetupError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=exc.exit_code) from None

    mode = _start_run_mode(
        planning.orchestrator.paths.root,
        knowledge_root=knowledge_root,
        project=project,
        override=provenance,
    )
    typer.echo(f"Provenance: {mode}")
    typer.echo(
        f"Design mode: {_start_design_mode(planning.orchestrator.paths.root, env=env, override=design_mode)}"
    )
    write_run_meta(Roots(runs=runs_root, env=env), run_id, client=client, project=project)
    _clarify_checkpoint(
        planning,
        run_id=run_id,
        client=client,
        project=project,
        prompt=prompt,
        command=f"clarify {run_id} --client {client} --project {project} --prompt ...",
    )


def _clarify_checkpoint(  # type: ignore[no-untyped-def]
    planning,
    *,
    run_id: str,
    client: str,
    project: str,
    prompt: str,
    command: str,
) -> None:
    """Run the clarify call, write `clarify.json`, and print the checkpoint.

    Shared by `clarify` and `redesign`: for a `RedesignPlanning` the pack is the client's
    deck and the call is told it is a redesign (and the person's settings).
    """
    from autodeck.agents.compose import ComposeError
    from autodeck.agents.compose import clarify as run_clarify
    from autodeck.pipeline.clarify_state import new_clarify, save_clarify

    orchestrator, guard = planning.orchestrator, planning.guard
    pack = _pack_for(planning, prompt)
    redesign = planning.settings if isinstance(planning, RedesignPlanning) else None
    payload: dict = {}

    def do_clarify() -> str:
        with _ends_on_provider_failure(
            guard,
            command=command,
            saved=lambda: "nothing was written. " + _cache_note(orchestrator),
        ):
            model = guard.provider("composer")
            result = run_clarify(
                prompt, pack=pack, context=planning.assembled, model=model, redesign=redesign
            )
        payload.update(
            new_clarify(
                prompt=prompt,
                client=client,
                project=project,
                assumptions=[a.model_dump(mode="json") for a in result.assumptions],
                questions=[q.model_dump(mode="json") for q in result.questions],
            )
        )
        path = save_clarify(orchestrator.paths.root, payload)
        return f"wrote {path}"

    try:
        orchestrator.run_stage("clarify", do_clarify, force=True)
    except ComposeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    typer.secho("The draft will assume:", bold=True)
    for assumption in payload["assumptions"]:
        typer.echo(f"  - [{assumption['topic']}] {assumption['statement']}")
    if payload["questions"]:
        typer.secho("\nQuestions:", bold=True)
        for question in payload["questions"]:
            typer.echo(f"  {question['id']}: {question['question']}")
            typer.echo(f"      why: {question['why']}")
            typer.echo(f"      suggested: {question['suggested_answer']}")
            if question["options"]:
                typer.echo(f"      options: {' | '.join(question['options'])}")
        typer.echo(
            f'\nNext: autodeck answer {run_id} --accept-all   (or --answer q1="..." for each)'
        )
    else:
        typer.echo("\nNo questions: nothing in the request needs asking.")
        typer.echo(f"Next: autodeck answer {run_id} --accept-all")


@app.command()
def redesign(
    run_id: Annotated[str, typer.Argument(help="Run identifier (created if new).")],
    client: Annotated[str, typer.Option("--client", help="Client namespace (A4).")],
    project: Annotated[str, typer.Option("--project", help="Project the deck belongs to.")],
    deck: Annotated[Path, typer.Option("--deck", help="The client's existing deck (.pptx).")],
    wording: Annotated[
        str,
        typer.Option(
            "--wording",
            help="keep: reuse the deck's sentences, trim only to fit; light: allow rewording.",
        ),
    ] = "keep",
    no_layouts: Annotated[
        bool, typer.Option("--no-layouts", help="Do not change any slide's layout.")
    ] = False,
    check_papers: Annotated[
        bool,
        typer.Option(
            "--check-papers",
            help="Also check the deck's figures against the project's papers (off by default).",
        ),
    ] = False,
    env: EnvOption = DEFAULT_ENV,
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
    provenance: ProvenanceOption = None,
    design_mode: DesignModeOption = None,
) -> None:
    """Start a redesign of a deck the client already has (B41, Phase 3d).

    Ingests the deck into the run's own source store (`runs/<run>/source/`, never the project
    corpus), writes `redesign.json` (the settings) and runs the clarify step over the whole
    deck, writing `clarify.json`. Then `answer`, `draft`, `validate` and `preview` follow as
    for any draft; `draft` sees `redesign.json` and rebuilds the deck, every statement citing
    the original slide. Approves nothing.
    """
    from autodeck.ingest.deck_source import ingest_deck, run_source_root
    from autodeck.ingest.document_store import IngestError
    from autodeck.ingest.redesign_settings import (
        RedesignSettingsError,
        save_redesign,
    )
    from autodeck.ui.api import Roots, write_run_meta

    settings = {
        "wording": wording,
        "layouts": not no_layouts,
        "check_papers": check_papers,
        "source_file": deck.name,
        "deck_doc_id": "pending",
    }
    if wording not in ("keep", "light"):
        _echo_error("--wording must be 'keep' or 'light'.")
        raise typer.Exit(code=1)
    from autodeck.ir.store import run_paths

    mode = _start_run_mode(
        run_paths(runs_root, run_id).root,
        knowledge_root=knowledge_root,
        project=project,
        override=provenance,
    )
    typer.echo(f"Provenance: {mode}")
    typer.echo(
        f"Design mode: {_start_design_mode(run_paths(runs_root, run_id).root, env=env, override=design_mode)}"
    )
    try:
        document = ingest_deck(deck, store_root=run_source_root(runs_root, run_id))
        settings["deck_doc_id"] = document.doc_id
        orchestrator = Orchestrator(run_id, runs_root=runs_root, env=env)
        save_redesign(orchestrator.paths.root, settings)
    except (IngestError, RedesignSettingsError) as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    write_run_meta(Roots(runs=runs_root, env=env), run_id, client=client, project=project)
    typer.echo(
        f"Ingested {deck.name}: {document.page_count} slide(s), "
        f"{len(document.citable_elements())} citable text element(s)."
    )

    from autodeck.pipeline.planning import PlanningSetupError, prepare_planning

    try:
        planning = prepare_planning(
            run_id,
            client=client,
            project=project,
            env=env,
            knowledge_root=knowledge_root,
            corpus_root=corpus_root,
            runs_root=runs_root,
        )
    except PlanningSetupError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=exc.exit_code) from None
    _clarify_checkpoint(
        planning,
        run_id=run_id,
        client=client,
        project=project,
        prompt=f"Redesign the client's existing deck ({deck.name}) in their brand.",
        command=f"redesign {run_id} --client {client} --project {project} --deck ...",
    )


@app.command()
def answer(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    answer: Annotated[
        list[str] | None,
        typer.Option("--answer", help='An answer, as q1="..." (repeat for each question).'),
    ] = None,
    accept_all: Annotated[
        bool, typer.Option("--accept-all", help="Take the suggested answer to every question.")
    ] = False,
    accept: Annotated[
        list[str] | None,
        typer.Option(
            "--accept",
            help="Take the suggested answer to one question, e.g. q2 (repeatable). Accepted "
            "answers are the model's wording, never citable as 'from you' (B55).",
        ),
    ] = None,
    correct: Annotated[
        list[str] | None,
        typer.Option("--correct", help="Correct one of the draft's assumptions (repeatable)."),
    ] = None,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
) -> None:
    """Record answers to the clarify questions, so the draft can start. No model call.

    Accepting the suggestions counts as answering (B48); leaving a question unanswered does
    not. Approves nothing: an answer is input to the draft, never an approval.
    """
    from autodeck.pipeline.clarify_state import (
        ClarifyStateError,
        load_clarify,
        record_answers,
        save_clarify,
    )

    orchestrator = _open_run(run_id, runs_root)
    parsed: dict[str, str] = {}
    for item in answer or []:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            _echo_error(f'--answer {item!r} must look like q1="your answer".')
            raise typer.Exit(code=1)
        parsed[key.strip()] = value
    try:
        data = load_clarify(orchestrator.paths.root)
        suggested = {q["id"]: str(q.get("suggested_answer", "")) for q in data["questions"]}
        accepted = {a.strip() for a in accept or [] if a.strip()}
        for qid in sorted(accepted):
            if qid in suggested:
                parsed.setdefault(qid, suggested[qid])
        record_answers(
            data,
            answers=parsed,
            corrections=correct or [],
            accept_all=accept_all,
            accepted=accepted & suggested.keys(),
        )
    except ClarifyStateError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    save_clarify(orchestrator.paths.root, data)
    for qid, text in (data["answers"] or {}).items():
        typer.echo(f"  {qid}: {text}")
    for correction in data["corrections"]:
        typer.echo(f"  correction: {correction}")
    typer.secho("Answers recorded.", fg=typer.colors.GREEN)
    typer.echo(f"Next: autodeck draft {run_id}")


@app.command()
def draft(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    env: EnvOption = DEFAULT_ENV,
    from_chat: Annotated[
        bool,
        typer.Option(
            "--from-chat",
            help="Draft to the brief the planning conversation left (chat mode, B47).",
        ),
    ] = False,
    client: Annotated[str | None, typer.Option("--client")] = None,
    project: Annotated[str | None, typer.Option("--project")] = None,
    agent: Annotated[
        bool,
        typer.Option(
            "--agent/--no-agent",
            help="Write the deck in an agent session that searches, reads and checks as it "
            "goes (B71) instead of one call. Falls back to one call if the session fails.",
        ),
    ] = False,
    agent_steps: Annotated[
        int, typer.Option("--agent-steps", min=1, help="Model turns the agent may take.")
    ] = 40,
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
    tokens: TokensOption = Path("config/tokens/dev.json"),
) -> None:
    """Write the brief, the outline and every slide in one call (B45), or with `--agent`.

    Refused (exit 3) until the clarify answers are recorded (`autodeck answer`) — or, with
    `--from-chat`, until the planning conversation left a draft brief, which compose then
    keeps verbatim. Citations are resolved in code, key-message evidence is computed from
    what resolved, and a coverage report says what the draft did with everything asked.
    Records a `compose` stage; approves nothing. Next: `validate`, then `preview`.
    """
    from autodeck.agents.compose import ComposeError, compose_deck
    from autodeck.pipeline.clarify_state import (
        ClarifyStateError,
        answer_pairs,
        is_answered,
        load_clarify,
        missing_answers,
    )
    from autodeck.pipeline.draft import DraftBriefError, load_draft_brief, save_draft_brief

    orchestrator = _open_run(run_id, runs_root, env)
    try:
        clarify_data = load_clarify(orchestrator.paths.root)
    except ClarifyStateError as exc:
        clarify_data = None
        clarify_error = str(exc)
    chat_brief = None
    if from_chat:
        try:
            chat_brief = load_draft_brief(orchestrator)
        except DraftBriefError as exc:
            _echo_error(str(exc))
            raise typer.Exit(code=EXIT_NEEDS_INPUT) from None
    elif clarify_data is None:
        _echo_error(f"{clarify_error}")
        raise typer.Exit(code=EXIT_NEEDS_INPUT)
    elif not is_answered(clarify_data):
        left = missing_answers(clarify_data)
        _echo_error(
            "the clarify questions have not been answered"
            + (f" ({', '.join(left)})" if left else "")
            + f". Run `autodeck answer {run_id} --accept-all` (or answer each) first (B47)."
        )
        raise typer.Exit(code=EXIT_NEEDS_INPUT)

    request = (clarify_data or {}).get(
        "prompt"
    ) or f"Write the deck for this brief: {chat_brief.objective if chat_brief else ''}"
    planning, client, project = _draft_setup(
        run_id,
        client=client,
        project=project,
        env=env,
        knowledge_root=knowledge_root,
        corpus_root=corpus_root,
        runs_root=runs_root,
        clarify_data=clarify_data,
    )
    guard = planning.guard
    run_root = orchestrator.paths.root
    if from_chat:
        # A chat-started run has no snapshot yet (the planner is gate-first): fix it now.
        mode = _start_run_mode(run_root, knowledge_root=knowledge_root, project=project)
        run_design_mode = _start_design_mode(run_root, env=env)
    else:
        mode = _run_mode(run_root)
        run_design_mode = _design_mode(run_root)
    named_terms = _project_named_terms(knowledge_root, project)
    pack, store = _with_conversation_source(
        planning,
        _pack_for(
            planning,
            request,
            # What the person answered steers retrieval too (run XLP2: "comparisons to
            # empagliflozin and sitagliptin" never reached the pack's queries).
            _answer_queries(clarify_data),
        ),
        run_id=run_id,
        runs_root=runs_root,
        corpus_root=corpus_root,
        project=project,
        mode=mode,
    )
    redesign_args = (
        {"mode": "redesign", "settings": planning.settings}
        if isinstance(planning, RedesignPlanning)
        else {}
    )
    use_agent = agent
    if agent and isinstance(planning, RedesignPlanning):
        typer.secho(
            "the agent does not do redesigns yet; drafting in one call", fg=typer.colors.YELLOW
        )
        use_agent = False
    design_tokens = DesignTokens.load(tokens)
    command = f"draft {run_id}"
    built: list = []

    def draft_saved() -> str:
        return "no IR version was written. " + _cache_note(orchestrator)

    advisor = None
    with _ends_on_provider_failure(guard, command=command, saved=draft_saved):
        model = guard.provider("composer", max_output_tokens=COMPOSE_MAX_OUTPUT_TOKENS)
        if use_agent:
            advisor = guard.provider("advisor")

    def one_shot():  # type: ignore[no-untyped-def]
        return compose_deck(
            request,
            answers=answer_pairs(clarify_data or {}),
            pack=pack,
            context=planning.assembled,
            store=store,
            tokens=design_tokens,
            model=model,
            run_id=run_id,
            client=client,
            project=project,
            theme_ref=str(tokens),
            component_lib_version=COMPONENT_LIB_VERSION,
            chat_brief=chat_brief,
            provenance=mode,
            named_terms=named_terms,
            design_mode=run_design_mode,
            **redesign_args,
        )

    def with_agent():  # type: ignore[no-untyped-def]
        """The agent's draft and the `session/meta.json` payload, or the one-shot draft
        (with the reason on its corrections) when the session cannot be used."""
        from autodeck.agents.deck_agent import compose_deck_agent
        from autodeck.agents.session import SessionLimits
        from autodeck.ingest.conversation_source import conversation_document

        session_dir = run_root / "session"
        meta: dict = {
            "stop_reason": "error",
            "steps": 0,
            "provider_calls": 0,
            "fell_back": False,
            "reason": None,
        }
        agent_args: dict = {
            "answers": answer_pairs(clarify_data or {}),
            "index": planning.index,
            "claims": planning.claims,
            "documents": list(store.documents()),
            "context": planning.assembled,
            "store": store,
            "tokens": design_tokens,
            "model": model,
            "advisor": advisor,
            "run_id": run_id,
            "client": client,
            "project": project,
            "theme_ref": str(tokens),
            "component_lib_version": COMPONENT_LIB_VERSION,
            "chat_brief": chat_brief,
            "provenance": mode,
            "named_terms": named_terms,
            "design_mode": run_design_mode,
            "conversation": (
                conversation_document(run_root, run_id) if mode == "normal" else None
            ),
            "session_dir": session_dir,
            "memory": _memory_store(knowledge_root, client, project, run_id),
            "limits": SessionLimits(max_steps=agent_steps),
            "on_step": _print_agent_step,
        }
        compose_agent = compose_deck_agent
        if isinstance(planning, MeetingPlanning):
            from autodeck.agents.meeting_deck import compose_meeting_deck_agent

            notes = _meeting_notes_workspace(run_root, planning, store)
            doc_id = planning.transcript_document.doc_id
            agent_args.update(
                transcript=planning.transcript_document,
                times=_meeting_times(run_root).get(doc_id, {}),
                notes=notes,
            )
            meta.update(kind="deck", from_meeting_session=notes is not None)
            compose_agent = compose_meeting_deck_agent
        reason = None
        try:
            ran = compose_agent(request, **agent_args)
        except ComposeError as exc:
            reason = str(exc)
        else:
            meta.update(
                stop_reason=ran.state.stop_reason,
                steps=ran.state.steps,
                provider_calls=ran.state.provider_calls,
            )
            wanted = -(-ran.result.draft_brief.length_target // 2)
            if len(ran.result.deck.slides) >= wanted:
                return ran.result, meta
            reason = (
                f"the agent wrote {len(ran.result.deck.slides)} slide(s) for a "
                f"{ran.result.draft_brief.length_target}-slide brief"
            )
        typer.secho(f"agent fell back to one-shot compose: {reason}", fg=typer.colors.YELLOW)
        result = one_shot()
        result.corrections.append(f"agent fell back to one-shot compose: {reason}")
        meta.update(fell_back=True, reason=reason)
        return result, meta

    def do_compose() -> str:
        if use_agent:
            result, meta = with_agent()
            _write_json(run_root / "session" / "meta.json", meta)
        else:
            result = one_shot()
        deck = result.deck.model_copy(update={"version": orchestrator.ir.next_version()})
        result.deck = deck
        save_draft_brief(orchestrator, result.draft_brief)
        path = orchestrator.save_ir(deck)
        _write_coverage_file(orchestrator, result, ir_version=deck.version)
        built.append(result)
        return f"wrote {path} · {result.provider_calls} provider call(s)"

    try:
        with _ends_on_provider_failure(guard, command=command, saved=draft_saved):
            orchestrator.run_stage("compose", do_compose, force=True)
    except ComposeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    [result] = built
    typer.secho(f"wrote IR v{result.deck.version}", fg=typer.colors.GREEN)
    if result.notes:
        typer.secho(f"\nread first: {result.notes}", fg=typer.colors.YELLOW)
    _print_draft_summary(result, result.deck)
    typer.echo(f"\nNext: autodeck validate {run_id}, then autodeck preview {run_id}")


def _meeting_notes_workspace(  # type: ignore[no-untyped-def]
    run_root: Path, planning: MeetingPlanning, store
):
    """The run's notes session as the deck agent's starting point (B82), or None when the
    run has none (or its notes no longer match the transcript: the deck is then written from
    the transcript alone)."""
    from autodeck.agents.notes_agent import migrate_notes_session
    from autodeck.agents.notes_workspace import NotesError, NotesWorkspace

    session = run_root / "session"
    migrate_notes_session(session)
    path = session / "notes_workspace.json"
    if not path.is_file():
        return None
    try:
        return NotesWorkspace.load(path, transcript=planning.transcript_document, store=store)
    except NotesError:
        typer.secho(
            "the saved notes no longer match the transcript; drafting from the transcript only",
            fg=typer.colors.YELLOW,
        )
        return None


def _print_agent_step(step: dict) -> None:
    """One line per transcript message, the stream the UI job log shows (B71)."""
    line = f"  · step {step['step']} {step['tool'] or step['role']}: {step['summary']}"
    if step.get("error"):
        typer.secho(line, fg=typer.colors.RED)
    else:
        typer.echo(line)


@app.command()
def revise(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    instruction: Annotated[str, typer.Option("--instruction", help="What to change.")],
    env: EnvOption = DEFAULT_ENV,
    client: Annotated[str | None, typer.Option("--client")] = None,
    project: Annotated[str | None, typer.Option("--project")] = None,
    agent: Annotated[
        bool | None,
        typer.Option(
            "--agent/--no-agent",
            help="Continue the run's agent session (the default when it has one) or make "
            "the change in one call.",
        ),
    ] = None,
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
) -> None:
    """Change the draft the way an instruction says, touching only what it names (3c.9).

    One call, or, when the run has an agent session (`draft --agent`), a continuation of
    that session. Slides the model does not return are kept exactly — same wording, citations
    and verdicts — so `validate` re-judges only what changed and approvals that covered the
    untouched parts stay current. Saved as a new `compose` version, with a line appended to
    `revisions.jsonl`. Approves nothing.
    """
    from autodeck.agents.compose import ComposeError, revise_deck
    from autodeck.ir.store import IRStoreError
    from autodeck.pipeline.clarify_state import ClarifyStateError, load_clarify
    from autodeck.pipeline.draft import DraftBriefError, load_draft_brief, save_draft_brief

    if not instruction.strip():
        _echo_error("--instruction is empty: say what to change.")
        raise typer.Exit(code=1)
    orchestrator = _open_run(run_id, runs_root, env)
    session_root = orchestrator.paths.root / "session"
    # A deck session: `workspace.json` is the deck agent's. A meeting run's notes session has
    # `notes_workspace.json` and does not count (B82).
    has_session = (session_root / "workspace.json").is_file()
    if agent and not has_session:
        if (session_root / "notes_workspace.json").is_file():
            _echo_error(
                "this run has a notes session but no deck session; draft with --agent first"
            )
        else:
            _echo_error("no agent session for this run; draft with --agent first")
        raise typer.Exit(code=1)
    if not orchestrator.is_draft_first:
        _echo_error(f"run {run_id!r} has no draft yet. Run `autodeck draft {run_id}` first.")
        raise typer.Exit(code=EXIT_NEEDS_INPUT)
    try:
        deck = orchestrator.ir.load()
        brief = load_draft_brief(orchestrator)
    except (IRStoreError, DraftBriefError) as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    try:
        clarify_data = load_clarify(orchestrator.paths.root)
    except ClarifyStateError:
        clarify_data = None

    planning, client, project = _draft_setup(
        run_id,
        client=client or deck.client,
        project=project or deck.project,
        env=env,
        knowledge_root=knowledge_root,
        corpus_root=corpus_root,
        runs_root=runs_root,
        clarify_data=clarify_data,
    )
    guard = planning.guard
    is_redesign = isinstance(planning, RedesignPlanning)
    if agent and is_redesign:
        _echo_error("the agent does not do redesigns yet; use --no-agent")
        raise typer.Exit(code=1)
    use_agent = has_session and not is_redesign if agent is None else bool(agent)
    base = (clarify_data or {}).get("prompt") or brief.objective
    run_root = orchestrator.paths.root
    mode = _run_mode(run_root)
    revisions_file = run_root / "revisions.jsonl"
    # In `normal` mode the instruction is part of what the person said, so it is on the log
    # before the conversation is ingested (it is dropped again if the revision fails).
    pending = mode == "normal" and not isinstance(planning, RedesignPlanning)
    if pending:
        _append_revision(
            revisions_file, {"instruction": instruction, "reply": "", "at": _iso_now()}
        )
    pack, store = _with_conversation_source(
        planning,
        _pack_for(planning, f"{base} {instruction}"),
        run_id=run_id,
        runs_root=runs_root,
        corpus_root=corpus_root,
        project=project,
        mode=mode,
    )
    design_tokens = DesignTokens.load(Path(deck.theme_ref))
    origins = _read_coverage_file(orchestrator).get("origins") or {}
    command = f"revise {run_id} --instruction ..."
    built: list = []

    def revise_saved() -> str:
        return f"the draft is unchanged (still v{deck.version}). " + _cache_note(orchestrator)

    advisor = None
    try:
        with _ends_on_provider_failure(guard, command=command, saved=revise_saved):
            model = guard.provider("composer", max_output_tokens=COMPOSE_MAX_OUTPUT_TOKENS)
            if use_agent:
                advisor = guard.provider("advisor")
    except BaseException:
        if pending:
            _drop_last_revision(revisions_file)
        raise

    def agent_revise():  # type: ignore[no-untyped-def]
        """The same session, one more instruction; shaped like a `ReviseResult`."""
        from autodeck.agents.compose import ReviseResult
        from autodeck.agents.deck_agent import build_settings, resume_deck_agent
        from autodeck.agents.session import SessionLimits
        from autodeck.pipeline.clarify_state import answer_pairs

        settings = build_settings(
            prompt=base,
            answers=answer_pairs(clarify_data or {}),
            chat_brief=None,
            store=store,
            tokens=design_tokens,
            provenance=deck.provenance,
            deck_fields={
                "run_id": deck.run_id,
                "project": deck.project,
                "client": deck.client,
                "theme_ref": deck.theme_ref,
                "component_lib_version": deck.component_lib_version,
                "provenance": deck.provenance,
                "named_terms": list(deck.named_terms),
                "design_mode": deck.design_mode,
            },
        )
        ran = resume_deck_agent(
            instruction,
            session_dir=run_root / "session",
            settings=settings,
            index=planning.index,
            claims=planning.claims,
            model=model,
            advisor=advisor,
            project=project,
            memory=_memory_store(knowledge_root, client, project, run_id),
            limits=SessionLimits(),
            on_step=_print_agent_step,
        )
        result = ran.result
        new_deck = result.deck.model_copy(update={"version": orchestrator.ir.next_version()})
        before = {s.id: s.model_dump() for s in deck.slides}
        changed = [s.id for s in new_deck.slides if before.get(s.id) != s.model_dump()]
        removed = [sid for sid in before if sid not in {s.id for s in new_deck.slides}]
        notes = [f"removed slide {sid}" for sid in removed]
        return ReviseResult(
            deck=new_deck,
            draft_brief=result.draft_brief,
            coverage=result.coverage,
            rejections=result.rejections,
            reply=result.notes or "Revised.",
            notes=notes,
            provider_calls=result.provider_calls,
            corrections=result.corrections,
            incomplete_slots=result.incomplete_slots,
            changed_slide_ids=changed,
            failures=result.failures,
            origins=result.origins,
        )

    def do_revise() -> str:
        if use_agent:
            result = agent_revise()
        else:
            result = revise_deck(
                instruction,
                deck=deck,
                draft_brief=brief,
                pack=pack,
                context=planning.assembled,
                store=store,
                tokens=design_tokens,
                model=model,
                origins=origins,
            )
        save_draft_brief(orchestrator, result.draft_brief)
        path = orchestrator.save_ir(result.deck)
        _write_coverage_file(orchestrator, result, ir_version=result.deck.version)
        record = {"instruction": instruction, "reply": result.reply, "at": _iso_now()}
        if use_agent:
            record["agent"] = True
        if pending:
            _replace_last_revision(revisions_file, record)
        else:
            _append_revision(revisions_file, record)
        built.append(result)
        return f"wrote {path} · {result.provider_calls} provider call(s)"

    try:
        with _ends_on_provider_failure(guard, command=command, saved=revise_saved):
            orchestrator.run_stage("compose", do_revise, force=True)
    except BaseException as exc:
        if pending and not built:
            _drop_last_revision(revisions_file)
        if isinstance(exc, ComposeError):
            _echo_error(str(exc))
            raise typer.Exit(code=1) from None
        raise

    [result] = built
    typer.secho(f"wrote IR v{result.deck.version}", fg=typer.colors.GREEN)
    typer.echo(f"\n{result.reply}")
    if result.changed_slide_ids:
        typer.echo(f"changed: {', '.join(result.changed_slide_ids)}")
    for note in result.notes:
        typer.secho(f"note: {note}", fg=typer.colors.YELLOW)
    _print_draft_summary(result, result.deck)
    typer.echo(f"\nNext: autodeck validate {run_id}, then autodeck preview {run_id}")


def _append_revision(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(record) + "\n")


def _revision_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _replace_last_revision(path: Path, record: dict) -> None:
    lines = _revision_lines(path)
    lines = [*lines[:-1], json.dumps(record)] if lines else [json.dumps(record)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _drop_last_revision(path: Path) -> None:
    lines = _revision_lines(path)
    if lines:
        path.write_text("".join(f"{line}\n" for line in lines[:-1]), encoding="utf-8")


def _describe_action(action: BaseModel) -> str:
    """`set_accent slide_id=s2 accent=accent3` — an action as one readable line."""
    fields = action.model_dump(mode="json", exclude_none=True)
    kind = fields.pop("kind", type(action).__name__)
    return " ".join([str(kind), *(f"{name}={value}" for name, value in fields.items())])


@app.command()
def preview(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
    env: EnvOption = DEFAULT_ENV,
) -> None:
    """Render a DRAFT preview of the latest IR into `runs/<run>/previews/draft` (3c.8, B43).

    Works on any deck - blocking verdicts, no approvals - because a draft is what an owner
    reads *before* approving. Every slide is stamped "DRAFT - not approved" and the file is
    `previews/draft/draft.pptx`; `deck.pptx` is never written (that is `autodeck render`,
    behind the gates). No art direction, no model calls. Records a `preview` stage and
    approves nothing; there is deliberately no option that does.
    """
    from autodeck.design.fonts import FontNotFoundError
    from autodeck.ir.store import IRStoreError
    from autodeck.render.draft import DraftPreview, render_draft

    orchestrator = _open_run(run_id, runs_root, env)
    try:
        deck = orchestrator.ir.load()
    except (IRStoreError, ValueError) as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None

    out_dir = orchestrator.paths.previews / "draft"
    tokens = DesignTokens.load(Path(deck.theme_ref))
    result: DraftPreview | None = None

    def do_preview() -> str:
        nonlocal result
        result = render_draft(deck, out_dir=out_dir, tokens=tokens)
        return f"wrote {result.pptx} ({len(result.images)} image(s))"

    try:
        orchestrator.run_stage("preview", do_preview, force=True)
    except (FileNotFoundError, FontNotFoundError, ValueError) as exc:
        _echo_error(f"the draft could not be drawn: {exc}")
        raise typer.Exit(code=1) from None

    assert result is not None
    typer.secho(f"Wrote {result.pptx}", fg=typer.colors.GREEN)
    if result.rendered:
        typer.echo(f"Rendered {len(result.images)} slide(s) to PNG in {out_dir}")
    else:
        typer.secho(f"No PNGs rendered: {result.note}", fg=typer.colors.YELLOW)
    for slide_id, flag in result.flags.items():
        typer.echo(f"  {slide_id:<12} {flag or 'ok'}")
    for slide_id, reason in result.placeholders.items():
        typer.secho(
            f"  {slide_id:<12} drawn as a placeholder: {reason}", fg=typer.colors.YELLOW
        )


@app.command()
def render(
    run_id: Annotated[str, typer.Argument(help="Run identifier.")],
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
    env: EnvOption = DEFAULT_ENV,
) -> None:
    """Art-direct, render and critique the approved deck into `runs/<run>/deck.pptx` (3b.10).

    Blocked unless the claims gate is approved for the deck as it is now (A7). Always runs
    every stage, in order: art direction (communication modes by rule, taste by model), then
    the aesthetic loop on true renders, then the final `deck.pptx` and its PNGs under
    `runs/<run>/previews/final`. Each presentation pass writes its result as a new IR version
    that changes no fact, so the claims approval stays current; a pass that changed a claim
    would void it (and `apply_action` refuses to). There is deliberately no option that
    skips a stage. Approves nothing: GATE 3 is `autodeck gate3`, then `autodeck approve`.

    Always starts from the IR version the `validate` stage recorded (DECISIONS B38) - the
    facts the claims approval covers - never from the latest version, which after a first
    render is that render's own art-directed and critiqued output. Starting from the latest
    would art-direct an already art-directed deck, so each run would differ from the last and
    a `final_render` approval would be voided by drift nobody asked for. This way a render is
    a function of the validated content and the model replies: with the response cache an
    identical re-run produces the same deck, and the approval survives it.
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
        # The final deck needs the three approvals before it current (A7 as amended by B43):
        # on a draft-first run they can be given in any order, so none is implied by another.
        for gate in (Gate.BRIEF, Gate.OUTLINE, Gate.CLAIMS):
            orchestrator.require_gate(gate)
    except GateBlocked as blocked:
        _echo_error(str(blocked))
        raise typer.Exit(code=3) from None

    validated = orchestrator.state.stages.get("validate")
    if validated is None or validated.ir_version is None:
        _echo_error(
            f"run {run_id!r} does not record which IR version `validate` wrote (a run from "
            f"before approvals were bound to artifacts), so there is nothing to start the "
            f"render from. Run `autodeck validate {run_id}` first."
        )
        raise typer.Exit(code=3)
    try:
        deck = orchestrator.ir.load(validated.ir_version)
        brief_doc = orchestrator.ir.load_brief()
    except (IRStoreError, ValueError) as exc:
        _echo_error(
            f"{exc} The IR version `validate` recorded (v{validated.ir_version}) cannot be "
            f"read. Run `autodeck validate {run_id}` again."
        )
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
    env: EnvOption = DEFAULT_ENV,
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
        deck,
        brief=brief_doc,
        numeric=safety.numeric,
        framing=safety.framing,
        meeting_times=_meeting_times(paths.root),
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
    orchestrator.record_final_assessment(
        assessment.deck_digest,
        assessment.passes,
        failed=[label for label, passed, _detail in assessment.checkable() if not passed],
    )

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
            provenance_mode=deck.provenance,
            run_sources=run_source_hashes(paths.root),
            session=session_record(paths.root / "session"),
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
    if assessment.passes:
        typer.secho(
            f"\nApprove with `autodeck approve {run_id} final_render` after doing the five "
            "PowerPoint checks above; the approval records the deck digest shown "
            f"({assessment.deck_digest[:16]}...). A clean run above is not the gate.",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.secho(
            f"\nNot approvable: `autodeck approve {run_id} final_render` will refuse this deck "
            "while a criterion above fails. Fix what it names, run `autodeck render "
            f"{run_id}` again, then `autodeck gate3 {run_id}`.",
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
    from autodeck.ir.store import IRStoreError
    from autodeck.pipeline.send_back import (
        EmptyReasonError,
        UnknownClaimError,
        append_send_backs,
        build_send_backs,
    )

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

    try:
        records = build_send_backs(
            deck, list(zip(claim, reason, strict=True)), by=by, at=_iso_now()
        )
    except EmptyReasonError as exc:
        _echo_error(
            f"empty --reason for claim {exc.claim_id!r}. A send-back with no reason teaches "
            "the writer nothing."
        )
        raise typer.Exit(code=2) from None
    except UnknownClaimError as exc:
        _echo_error(
            f"unknown claim id(s): {', '.join(exc.claim_ids)}. Run `autodeck gate2 {run_id}` "
            "to see the current claim ids — they change across content passes."
        )
        raise typer.Exit(code=1) from None

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


# ---------------------------------------------------------------------------
# ui
# ---------------------------------------------------------------------------


@app.command()
def ui(
    env: Annotated[
        str | None,
        typer.Option(
            "--env",
            help="Provider environment. Default: the one last chosen in the UI, else config.",
        ),
    ] = None,
    port: Annotated[int, typer.Option("--port", help="Local port; 0 picks a free one.")] = 0,
    browser: Annotated[
        bool, typer.Option("--browser", help="Open in the browser instead of a window.")
    ] = False,
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
) -> None:
    """Open the review UI (B40): a local window over the same pipeline these commands run.

    Uses a native window when the `ui` extra is installed (`uv sync --extra ui`), and the
    default browser otherwise. Serves on 127.0.0.1 only. Steps run as these same commands,
    and an approval is a person clicking Approve in it: the brief through the planner, as
    `/sign` is here, the other gates through the method `approve` calls (A7, B42).
    """
    from autodeck.ui.api import Roots, restore_env
    from autodeck.ui.launch import serve

    roots = Roots(knowledge=knowledge_root, corpus=corpus_root, runs=runs_root)
    if env:
        roots.env = env
    else:
        restore_env(roots)
    serve(roots, port=port, window=not browser, say=typer.echo)


# ---------------------------------------------------------------------------
# meeting — local speech-to-text (Stage A)
# ---------------------------------------------------------------------------


@meeting_app.command("models")
def meeting_models(
    download: Annotated[
        bool, typer.Option("--download", help="Fetch the models that are missing.")
    ] = False,
    speakers: Annotated[
        bool, typer.Option("--speakers", help="Include the speaker-labelling models.")
    ] = False,
) -> None:
    """List the speech models and whether they are installed; `--download` fetches them."""
    from autodeck.meeting import model_files
    from autodeck.meeting.errors import MeetingDepsError, MeetingError

    wanted = ["asr", "vad", *(["diar_seg", "diar_emb"] if speakers else [])]
    if download:
        try:
            model_files.ensure(wanted, progress=typer.echo)
        except MeetingDepsError as exc:
            _echo_error(str(exc))
            raise typer.Exit(code=2) from None
        except MeetingError as exc:
            _echo_error(str(exc))
            raise typer.Exit(code=1) from None
    typer.echo(f"Models folder: {model_files.models_dir()}")
    for key, present, path in model_files.status():
        size = model_files.MODELS[key].approx_mb
        typer.echo(f"  {key:<9} {'present' if present else 'missing':<8} ~{size} MB  {path}")


@meeting_app.command("transcribe")
def meeting_transcribe(
    run_id: Annotated[str, typer.Argument(help="Run identifier (created if new).")],
    audio: Annotated[Path, typer.Option("--audio", help="The meeting recording.")],
    client: Annotated[str, typer.Option("--client", help="Client namespace (A4).")],
    project: Annotated[str, typer.Option("--project", help="Project the meeting is for.")],
    speakers: Annotated[
        bool, typer.Option("--speakers", help="Label who is speaking (S1, S2, ...).")
    ] = False,
    num_speakers: Annotated[
        int | None, typer.Option("--num-speakers", help="Number of speakers, if known.")
    ] = None,
    threads: Annotated[int | None, typer.Option("--threads", help="CPU threads.")] = None,
    with_papers: Annotated[
        bool,
        typer.Option(
            "--with-papers/--no-papers",
            help="Also check the deck against the project's papers (off by default: a "
            "meeting deck is checked against the meeting only).",
        ),
    ] = False,
    env: EnvOption = DEFAULT_ENV,
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
) -> None:
    """Transcribe a recording on this machine into `runs/<run>/meeting/`.

    Nothing leaves the computer; the audio is read in place, not copied into the repo, and
    transcript text is written to files only, never printed. The transcript also becomes the
    run's source (`runs/<run>/source/`, citable as "from the meeting"); `clarify` and `draft`
    follow as for any run.
    """
    from autodeck.ingest.document_store import DocumentStore, IngestError
    from autodeck.ingest.transcript_source import (
        MeetingSettingsError,
        ingest_transcript,
        save_meeting_settings,
    )
    from autodeck.knowledge.loader import KnowledgeError, KnowledgeLoader
    from autodeck.meeting.audio import ALLOWED_SUFFIXES, file_sha256
    from autodeck.meeting.errors import MeetingDepsError, MeetingError
    from autodeck.meeting.transcribe import transcribe_file
    from autodeck.ui.api import Roots, write_run_meta

    if audio.suffix.lower() not in ALLOWED_SUFFIXES:
        _echo_error(
            f"unsupported audio type {audio.suffix or '(none)'!r}; "
            f"use one of {', '.join(sorted(ALLOWED_SUFFIXES))}"
        )
        raise typer.Exit(code=1)
    if not audio.is_file():
        _echo_error(f"audio file not found: {audio.name}")
        raise typer.Exit(code=1)
    loader = KnowledgeLoader(knowledge_root)
    try:
        known_clients, known_projects = loader.client_names(), loader.project_names()
    except KnowledgeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    if client not in known_clients:
        _echo_error(f"unknown client {client!r}; known: {', '.join(known_clients) or 'none'}")
        raise typer.Exit(code=1)
    if project not in known_projects:
        _echo_error(
            f"unknown project {project!r}; known: {', '.join(known_projects) or 'none'}"
        )
        raise typer.Exit(code=1)
    try:
        orchestrator = Orchestrator(run_id, runs_root=runs_root, env=env)
    except UnknownRunError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    write_run_meta(Roots(runs=runs_root, env=env), run_id, client=client, project=project)

    out_dir = orchestrator.paths.root / "meeting"
    try:
        sha = file_sha256(audio)
        result = transcribe_file(
            audio,
            out_dir,
            speakers=speakers,
            num_speakers=num_speakers,
            threads=threads,
            progress=typer.echo,
        )
    except MeetingDepsError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=2) from None
    except MeetingError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    try:
        doc_id = ingest_transcript(orchestrator.paths.root, run_id)
        if doc_id is None:
            _echo_error("no speech was transcribed; nothing to cite.")
            raise typer.Exit(code=1)
        save_meeting_settings(
            orchestrator.paths.root,
            {
                "audio_name": audio.name,
                "audio_sha256": sha,
                "speakers": speakers,
                "num_speakers": num_speakers,
                "client": client,
                "project": project,
                "doc_id": doc_id,
                "check_papers": with_papers,
            },
        )
    except (IngestError, MeetingSettingsError) as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    citable = len(DocumentStore(orchestrator.paths.root / "source").get(doc_id).elements)
    found = sorted({s.speaker for s in result.segments if s.speaker})
    timings = result.timings
    typer.echo(f"Duration: {result.audio.duration_s:.1f}s   Segments: {len(result.segments)}")
    if speakers:
        typer.echo(f"Speakers: {len(found)}" if found else "Speakers: not labelled")
    typer.echo(
        f"Timings: decode {timings['decode']}s, asr {timings['asr']}s, "
        f"diarize {timings['diarize']}s, total {timings['total']}s"
    )
    typer.echo(f"Real-time factor: {timings['rtf']}")
    typer.echo(f"Citable turns: {citable}")
    typer.echo(f"Wrote {out_dir}")
    typer.echo(
        f"Next: autodeck clarify {run_id} --client {client} --project {project} --prompt ..."
    )


@meeting_app.command("source")
def meeting_source(
    run_id: Annotated[str, typer.Argument(help="Run identifier (must have a transcript).")],
    with_papers: Annotated[
        bool,
        typer.Option(
            "--with-papers/--no-papers",
            help="Also check the deck against the project's papers (off by default).",
        ),
    ] = False,
    env: EnvOption = DEFAULT_ENV,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
) -> None:
    """Make an existing `meeting/transcript.json` the run's source, without transcribing again.

    For a transcript made before it became a source, or one corrected by hand. Rewrites
    `source/transcript--<run>.json`, `meeting/segments.json` and `meeting/settings.json`
    (the audio details already there are kept). Transcript text is never printed.
    """
    from autodeck.ingest.document_store import DocumentStore, IngestError
    from autodeck.ingest.transcript_source import (
        MeetingSettingsError,
        ingest_transcript,
        save_meeting_settings,
        settings_path,
    )

    orchestrator = _open_run(run_id, runs_root, env)
    root = orchestrator.paths.root
    try:
        previous = json.loads(settings_path(root).read_text(encoding="utf-8"))
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    try:
        doc_id = ingest_transcript(root, run_id)
        if doc_id is None:
            _echo_error("the transcript has no speech; nothing to cite.")
            raise typer.Exit(code=1)
        save_meeting_settings(root, {**previous, "doc_id": doc_id, "check_papers": with_papers})
    except (IngestError, MeetingSettingsError) as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    citable = len(DocumentStore(root / "source").get(doc_id).elements)
    typer.echo(f"Citable turns: {citable}")
    typer.echo(f"Paper check: {'on' if with_papers else 'off'}")
    typer.echo(f"Source: {doc_id}")


# ---------------------------------------------------------------------------
# meeting notes — an agent writes the notes (plan step 10, B80)
# ---------------------------------------------------------------------------


def _notes_setup(  # type: ignore[no-untyped-def]
    run_id: str,
    *,
    env: str,
    knowledge_root: Path,
    corpus_root: Path,
    runs_root: Path,
):
    """Open a meeting run for a notes command: the run's meeting settings, the confidential
    check (B81) and the planning context. Returns `(orchestrator, planning, client, project,
    times)`; exits 1 with a message when the run has no meeting or the environment is not
    `confidential_ok`."""
    from autodeck.ingest.transcript_source import (
        MeetingSettingsError,
        load_meeting_settings,
        meeting_times,
    )
    from autodeck.pipeline.planning import PlanningSetupError, require_confidential

    orchestrator = _open_run(run_id, runs_root, env)
    root = orchestrator.paths.root
    try:
        settings = load_meeting_settings(root)
    except MeetingSettingsError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    if settings is None:
        _echo_error(
            f"run {run_id} has no meeting; run `autodeck meeting transcribe {run_id}` first."
        )
        raise typer.Exit(code=1)
    try:
        require_confidential(env)
    except PlanningSetupError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=exc.exit_code) from None
    planning, client, project = _draft_setup(
        run_id,
        client=settings["client"] or None,
        project=settings["project"] or None,
        env=env,
        knowledge_root=knowledge_root,
        corpus_root=corpus_root,
        runs_root=runs_root,
        clarify_data=None,
    )
    assert isinstance(planning, MeetingPlanning)
    times = meeting_times(root).get(settings["doc_id"], {})
    return orchestrator, planning, client, project, times


def _finish_notes_command(orchestrator: Orchestrator, ran, times: dict) -> None:  # type: ignore[no-untyped-def]
    """Write the notes files and the session meta, and say what happened. Never prints a
    note or a transcript word: a meeting is client-confidential (B78)."""
    from autodeck.agents.notes_workspace import NOTES_SECTIONS, write_notes

    ws, state = ran.workspace, ran.state
    run_root = orchestrator.paths.root
    meeting_dir = run_root / "meeting"
    write_notes(ws, meeting_dir, times)
    note_path = meeting_dir / "agent-note.md"
    if ws.note_to_person.strip():
        note_path.write_text(ws.note_to_person.strip() + "\n", encoding="utf-8")
    elif note_path.exists():
        note_path.unlink()
    _write_json(
        run_root / "session" / "notes_meta.json",
        {
            "kind": "notes",
            "stop_reason": state.stop_reason,
            "steps": state.steps,
            "provider_calls": state.provider_calls,
            "input_tokens": state.input_tokens,
            "output_tokens": state.output_tokens,
        },
    )
    typer.echo(f"Stop reason: {state.stop_reason}")
    typer.echo(
        f"Steps: {state.steps}   Provider calls: {state.provider_calls}   "
        f"Tokens: {state.input_tokens} in, {state.output_tokens} out"
    )
    for name in NOTES_SECTIONS:
        typer.echo(f"  {name}: {len(ws.sections[name])}")
    typer.secho("Wrote meeting/notes.md", fg=typer.colors.GREEN)
    if ws.note_to_person.strip():
        typer.echo("The agent left you a note: meeting/agent-note.md")
    if state.stop_reason != "finished":
        typer.secho(
            f"The agent stopped ({state.stop_reason}) before finishing: the notes are what it "
            "had written by then.",
            fg=typer.colors.YELLOW,
        )


@meeting_app.command("notes")
def meeting_notes(
    run_id: Annotated[str, typer.Argument(help="Run identifier (must have a meeting).")],
    date: Annotated[
        str | None, typer.Option("--date", help="When the meeting was, as you would say it.")
    ] = None,
    attendees: Annotated[
        str | None,
        typer.Option(
            "--attendees", help='Who was there, e.g. "Shikha, Dev" (spellings, not evidence).'
        ),
    ] = None,
    steps: Annotated[
        int, typer.Option("--steps", min=1, help="Model turns the agent may take.")
    ] = 40,
    env: EnvOption = DEFAULT_ENV,
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
) -> None:
    """Write the meeting's notes in an agent session: `meeting/notes.md` and `notes.json`.

    Every note cites verbatim words from the transcript. The notes are sent to the
    environment's model providers, so the environment must be `confidential_ok`. Transcript
    and note text are never printed here. Edit `notes.md` by hand if you like, then
    `autodeck meeting revise-notes RUN --apply-edits`.
    """
    from autodeck.agents.compose import ComposeError
    from autodeck.agents.notes_agent import compose_notes_agent
    from autodeck.agents.session import SessionLimits

    orchestrator, planning, client, project, times = _notes_setup(
        run_id,
        env=env,
        knowledge_root=knowledge_root,
        corpus_root=corpus_root,
        runs_root=runs_root,
    )
    guard = planning.guard
    command = f"meeting notes {run_id}"

    def notes_saved() -> str:
        return "no notes were written. " + _cache_note(orchestrator)

    with _ends_on_provider_failure(guard, command=command, saved=notes_saved):
        model = guard.provider("composer", max_output_tokens=COMPOSE_MAX_OUTPUT_TOKENS)
        advisor = guard.provider("advisor")
    names = [a.strip() for a in (attendees or "").split(",") if a.strip()]
    built: list = []

    def do_notes() -> str:
        ran = compose_notes_agent(
            transcript=planning.transcript_document,
            store=planning.store,
            times=times,
            context=planning.assembled,
            model=model,
            advisor=advisor,
            project=project,
            meeting_date=(date or "").strip() or None,
            attendees=names,
            session_dir=orchestrator.paths.root / "session",
            limits=SessionLimits(max_steps=steps),
            on_step=_print_agent_step,
            memory=_memory_store(knowledge_root, client, project, run_id),
        )
        built.append(ran)
        return f"{ran.state.stop_reason} · {ran.state.provider_calls} provider call(s)"

    try:
        with _ends_on_provider_failure(guard, command=command, saved=notes_saved):
            orchestrator.run_stage("notes", do_notes, force=True)
    except ComposeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    _finish_notes_command(orchestrator, built[0], times)


def _notes_edit_diff(meeting_dir: Path) -> str:
    """The person's edits to `notes.md` as a unified diff against `notes.rendered.md`."""
    import difflib

    rendered, edited = meeting_dir / "notes.rendered.md", meeting_dir / "notes.md"
    try:
        before = rendered.read_text(encoding="utf-8").splitlines()
        after = edited.read_text(encoding="utf-8").splitlines()
    except OSError:
        _echo_error("there are no notes to compare; run `autodeck meeting notes` first.")
        raise typer.Exit(code=1) from None
    return "\n".join(
        difflib.unified_diff(before, after, "notes.rendered.md", "notes.md", n=1, lineterm="")
    )


@meeting_app.command("revise-notes")
def meeting_revise_notes(
    run_id: Annotated[str, typer.Argument(help="Run identifier (must have notes).")],
    say: Annotated[
        str | None, typer.Option("--say", help="What to change, in your own words.")
    ] = None,
    apply_edits: Annotated[
        bool,
        typer.Option("--apply-edits", help="Make the notes match your edits to notes.md."),
    ] = False,
    steps: Annotated[
        int, typer.Option("--steps", min=1, help="Model turns the agent may take.")
    ] = 40,
    env: EnvOption = DEFAULT_ENV,
    knowledge_root: KnowledgeRoot = DEFAULT_KNOWLEDGE_ROOT,
    corpus_root: CorpusRoot = DEFAULT_CORPUS_ROOT,
    runs_root: RunsRoot = DEFAULT_RUNS_ROOT,
) -> None:
    """Change the meeting's notes: with `--say` in words, or `--apply-edits` from your edits.

    Continues the run's notes session. Give exactly one of the two. `--apply-edits` compares
    `meeting/notes.md` with the copy as the agent wrote it (`notes.rendered.md`) and, when
    they differ, asks the agent to make the notes match, keeping every item cited.
    """
    from autodeck.agents.compose import ComposeError
    from autodeck.agents.notes_agent import resume_notes_agent
    from autodeck.agents.session import SessionLimits

    if (say is None) == (not apply_edits) or (say is not None and not say.strip()):
        _echo_error("give exactly one of --say TEXT or --apply-edits.")
        raise typer.Exit(code=1)
    orchestrator = _open_run(run_id, runs_root, env)
    run_root = orchestrator.paths.root
    meeting_dir = run_root / "meeting"
    if not (run_root / "session" / "notes_workspace.json").is_file():
        _echo_error(
            f"run {run_id} has no notes session; write the notes with "
            f"`autodeck meeting notes {run_id}` first."
        )
        raise typer.Exit(code=1)
    record: dict = {"target": "notes", "at": _iso_now()}
    if apply_edits:
        diff = _notes_edit_diff(meeting_dir)
        if not diff.strip():
            typer.echo("No edits to apply.")
            return
        instruction = (
            "The person edited the notes file. Lines starting '-' were removed and '+' added; "
            "the `<!-- nX -->` tag on a bullet names the item. Make the notes match their "
            "edits, keeping every item cited:\n\n" + diff
        )
        record["edits"] = diff
    else:
        instruction = (say or "").strip()
        record["instruction"] = instruction

    orchestrator, planning, client, project, times = _notes_setup(
        run_id,
        env=env,
        knowledge_root=knowledge_root,
        corpus_root=corpus_root,
        runs_root=runs_root,
    )
    guard = planning.guard
    command = f"meeting revise-notes {run_id}"

    def revise_saved() -> str:
        return "the notes are unchanged. " + _cache_note(orchestrator)

    with _ends_on_provider_failure(guard, command=command, saved=revise_saved):
        model = guard.provider("composer", max_output_tokens=COMPOSE_MAX_OUTPUT_TOKENS)
        advisor = guard.provider("advisor")
    built: list = []

    def do_revise() -> str:
        ran = resume_notes_agent(
            instruction,
            session_dir=run_root / "session",
            transcript=planning.transcript_document,
            store=planning.store,
            times=times,
            model=model,
            advisor=advisor,
            project=project,
            limits=SessionLimits(max_steps=steps),
            on_step=_print_agent_step,
            memory=_memory_store(knowledge_root, client, project, run_id),
        )
        built.append(ran)
        return f"{ran.state.stop_reason} · {ran.state.provider_calls} provider call(s)"

    try:
        with _ends_on_provider_failure(guard, command=command, saved=revise_saved):
            orchestrator.run_stage("notes", do_revise, force=True)
    except ComposeError as exc:
        _echo_error(str(exc))
        raise typer.Exit(code=1) from None
    ran = built[0]
    record["reply"] = ran.workspace.note_to_person.strip()
    _append_revision(run_root / "revisions.jsonl", record)
    _finish_notes_command(orchestrator, ran, times)


if __name__ == "__main__":  # pragma: no cover
    app()
