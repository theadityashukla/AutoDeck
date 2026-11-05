"""What the review UI shows and does, as plain functions over the repository (B40).

Every function here reads the same files the CLI reads, or calls the same code it calls.
None of them approves a gate: signing the brief goes through `PlannerSession.sign_off`
(in `server.py`), and the other three approvals go through `approvals.approve_gate`, which
calls the method `autodeck approve` calls (A7, B39, B42).

Kept free of HTTP so the tests can call it directly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autodeck.pipeline.orchestrator import (
    DEFAULT_RUNS_ROOT,
    ApprovalState,
    Gate,
    Orchestrator,
    UnknownRunError,
)

DEFAULT_KNOWLEDGE_ROOT = Path("knowledge")
DEFAULT_CORPUS_ROOT = Path("corpus")
DEFAULT_TOKENS = Path("config/tokens/dev.json")

#: The file the UI keeps beside a run to remember which client and project it was started
#: for. `state.json` does not record them, and the run list is unreadable without them.
#: Derived and local, like the rest of `runs/`; nothing in the pipeline reads it.
UI_META = "ui.json"

CLIENT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")

ENV_LABELS = {
    "dev-mistral": (
        "Draft models (Mistral)",
        "Small paid Mistral models on the included monthly allowance; a few cents a draft. "
        "A draft, never a client deliverable; accuracy here is a smoke test (B51).",
    ),
    "sit": (
        "Verification models",
        "The models production uses, for checking accuracy before a real deck.",
    ),
    "prod": ("Production models", "For real client deliverables."),
}

GATE_LABELS = {
    Gate.BRIEF: "Brief",
    Gate.OUTLINE: "Outline",
    Gate.CLAIMS: "Claims",
    Gate.FINAL_RENDER: "Final render",
}
GATE_KEYS = {
    Gate.BRIEF: "brief",
    Gate.OUTLINE: "outline",
    Gate.CLAIMS: "claims",
    Gate.FINAL_RENDER: "final",
}


class UIError(Exception):
    """A request the UI refuses, with a message a person can act on."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Roots:
    """Where the repository's folders are. Defaults match the CLI's."""

    knowledge: Path = DEFAULT_KNOWLEDGE_ROOT
    corpus: Path = DEFAULT_CORPUS_ROOT
    runs: Path = DEFAULT_RUNS_ROOT
    tokens: Path = DEFAULT_TOKENS
    env: str = field(default_factory=lambda: _default_env())
    profile: Path = field(default_factory=lambda: _default_profile())


def _default_profile() -> Path:
    from autodeck.ui.profile import DEFAULT_PROFILE

    return DEFAULT_PROFILE


def _default_env() -> str:
    from autodeck.providers.registry import ModelRegistry

    try:
        return ModelRegistry.load().env
    except Exception:
        return "dev-mistral"


# ---------------------------------------------------------------------------
# Knowledge
# ---------------------------------------------------------------------------


def _loader(roots: Roots):  # type: ignore[no-untyped-def]
    from autodeck.knowledge.loader import KnowledgeLoader

    return KnowledgeLoader(roots.knowledge)


def list_clients(roots: Roots) -> list[str]:
    try:
        return _loader(roots).client_names()
    except Exception:
        return []


def list_projects(roots: Roots) -> list[str]:
    try:
        return _loader(roots).project_names()
    except Exception:
        return []


def lint_framing(text: str) -> list[dict[str, str]]:
    """A5's fence, line by line, for the positioning field as it is typed."""
    from autodeck.audit.framing_linter import lint_framing_text

    findings: list[dict[str, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        for finding in lint_framing_text(line, location=f"line {number}"):
            findings.append(
                {
                    "reason": finding.check,
                    "severity": finding.severity,
                    "excerpt": f"{finding.location}: {finding.fragment or line.strip()}",
                    "detail": finding.detail,
                }
            )
    return findings


def create_client(roots: Roots, *, name: str, client_md: str, value_prop_md: str) -> Path:
    """Write `knowledge/clients/<name>/` with its two required files.

    Refuses a name that exists, and text that names another client (A4: the same check the
    context assembler runs at build time, run here so the mistake is caught while typing).
    A5 findings in the positioning text are reported, not refused: the build demotes such
    lines to claims, and the person may want to keep a line and cite it.
    """
    name = name.strip()
    if not CLIENT_NAME.fullmatch(name):
        raise UIError("Use lower case letters, numbers and dashes for the client name.")
    if not client_md.strip() or not value_prop_md.strip():
        raise UIError("Both 'Who they are' and 'Positioning language' are required.")

    folder = roots.knowledge / "clients" / name
    if folder.exists():
        raise UIError(f"A client called {name!r} already exists.", status=409)

    others = [c for c in list_clients(roots) if c != name]
    named = sorted(c for c in others if c in client_md or c in value_prop_md)
    if named:
        raise UIError(
            f"The text mentions another client ({', '.join(named)}). A client's folder must "
            "not name another client (A4)."
        )

    title = name.replace("-", " ").title()
    folder.mkdir(parents=True)
    (folder / "client.md").write_text(f"# {title}\n\n{client_md.strip()}\n", encoding="utf-8")
    (folder / "value_prop.md").write_text(
        f"# {title} — positioning\n\n{value_prop_md.strip()}\n", encoding="utf-8"
    )
    return folder


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def _check(name: str, ok: bool, note: str, fix: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "note": note, "fix": fix}


def readiness(roots: Roots) -> list[dict[str, Any]]:
    """The owner guide's 'Before you start' list, checked rather than described."""
    checks = [_keys_check(roots.env), _fonts_check(roots.tokens), _soffice_check()]
    projects = list_projects(roots)
    checks.extend(_corpus_check(roots, p) for p in projects)
    if not projects:
        checks.append(
            _check(
                "Projects", False, f"No project folders under {roots.knowledge / 'projects'}"
            )
        )
    return checks


def _keys_check(env: str) -> dict[str, Any]:
    from autodeck.providers.registry import ModelRegistry

    try:
        missing = ModelRegistry.load(env).missing_credentials()
    except Exception as exc:
        return _check("API keys", False, str(exc))
    if missing:
        return _check(
            "API keys",
            False,
            f"Not set: {', '.join(missing)}",
            fix="; ".join(f"export {var}=…" for var in missing) + "  (then restart AutoDeck)",
        )
    return _check("API keys", True, f"Every model in {env} has its key")


def _fonts_check(tokens: Path) -> dict[str, Any]:
    from autodeck.design.fonts import FontNotFoundError, resolve_face
    from autodeck.design.theme.tokens import DesignTokens

    try:
        families = sorted(DesignTokens.load(tokens).typography.families())
    except Exception as exc:
        return _check("Fonts", False, f"Could not read {tokens}: {exc}")
    missing = []
    for family in families:
        for bold, italic in ((False, False), (True, False), (False, True)):
            try:
                resolve_face(family, bold=bold, italic=italic)
            except FontNotFoundError:
                missing.append(family)
                break
    if missing:
        return _check(
            "Fonts",
            False,
            f"Missing: {', '.join(missing)}. Text is measured against the real font.",
            fix="./scripts/setup-dev-env.sh",
        )
    return _check("Fonts", True, ", ".join(families))


def _soffice_check() -> dict[str, Any]:
    from autodeck.render.qa.libreoffice import RenderError, soffice_path

    try:
        path = soffice_path()
    except RenderError:
        return _check(
            "LibreOffice",
            False,
            "Needed to render previews and the final deck",
            fix="Install LibreOffice, or run ./scripts/setup-dev-env.sh",
        )
    return _check("LibreOffice", True, path)


def _corpus_check(roots: Roots, project: str) -> dict[str, Any]:
    from autodeck.ingest.document_store import DocumentStore

    try:
        count = sum(1 for _ in DocumentStore(roots.corpus / project).documents())
    except Exception:
        count = 0
    if not count:
        return _check(
            f"Papers: {project}",
            False,
            "Not ingested yet; planning needs them",
            fix=f"uv run autodeck knowledge ingest {project}",
        )
    return _check(f"Papers: {project}", True, f"{count} document(s) ingested")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def settings(roots: Roots) -> dict[str, Any]:
    import yaml

    from autodeck.providers.registry import DEFAULT_CONFIG_PATH

    try:
        raw = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        names = list((raw.get("environments") or {}).keys())
    except Exception:
        names = []
    names = names or [roots.env]
    from autodeck.ui.profile import read_profile
    from autodeck.ui.workspace import keys_view

    envs = []
    for name in names:
        full = env_info(name)
        envs.append(
            {
                **env_info(name, brief=True),
                "roles": full.get("roles", []),
                "missing_credentials": full.get("missing_credentials", []),
            }
        )
    return {
        "env": env_info(roots.env),
        "envs": envs,
        "profile": read_profile(roots.profile),
        "keys": keys_view(roots.env)["keys"],
        "rendering": [_fonts_check(roots.tokens), _soffice_check()],
    }


def project_settings_view(roots: Roots, project: str) -> dict[str, Any]:
    """A project's provenance mode and glossary of numeric names (B55, B58)."""
    from autodeck.knowledge.loader import KnowledgeError, load_project_settings

    if project not in list_projects(roots):
        raise UIError(f"Unknown project {project!r}.", status=404)
    try:
        loaded = load_project_settings(roots.knowledge, project)
    except KnowledgeError as exc:
        raise UIError(str(exc), status=409) from None
    return {
        "project": project,
        "provenance": loaded.provenance,
        "named_terms": list(loaded.named_terms),
    }


def save_project_settings_view(
    roots: Roots, project: str, *, provenance: Any, named_terms: Any
) -> dict[str, Any]:
    """Write a project's settings. Runs already started keep their own snapshot (B55)."""
    from autodeck.knowledge.loader import (
        KnowledgeError,
        ProjectSettings,
        load_project_settings,
        save_project_settings,
    )

    current = project_settings_view(roots, project)
    if named_terms is not None and not isinstance(named_terms, list):
        raise UIError("named_terms must be a list of strings.")
    try:
        updated = ProjectSettings.model_validate(
            {
                **load_project_settings(roots.knowledge, project).model_dump(),
                "provenance": provenance if provenance is not None else current["provenance"],
                **(
                    {"named_terms": [str(t).strip() for t in named_terms if str(t).strip()]}
                    if named_terms is not None
                    else {}
                ),
            }
        )
        save_project_settings(roots.knowledge, project, updated)
    except (KnowledgeError, ValueError) as exc:
        raise UIError(f"Those settings are not valid: {exc}") from None
    return project_settings_view(roots, project)


def run_provenance(roots: Roots, run_id: str) -> str:
    """The run's fixed provenance mode ("strict" when it has none)."""
    from autodeck.pipeline.provenance import ProvenanceModeError, load_mode

    try:
        return load_mode(roots.runs / run_id)
    except ProvenanceModeError:
        return "strict"


def run_design_mode(roots: Roots, run_id: str) -> str:
    """The run's fixed design mode ("structured" when it has none)."""
    from autodeck.pipeline.design_mode import DesignModeError, load_design_mode

    try:
        return load_design_mode(roots.runs / run_id)
    except DesignModeError:
        return "structured"


def snapshot_run_design_mode(roots: Roots, run_id: str, override: str | None) -> str:
    """Fix a new run's design mode: `override`, else the environment's default (B69)."""
    from autodeck.pipeline.design_mode import DesignModeError, resolve_design_mode
    from autodeck.providers.registry import ModelRegistry

    try:
        default = ModelRegistry.load(roots.env).design_mode
        return resolve_design_mode(roots.runs / run_id, default, override)  # type: ignore[arg-type]
    except Exception as exc:
        if isinstance(exc, DesignModeError):
            raise UIError(str(exc)) from None
        raise UIError(f"Could not read the model settings: {exc}") from None


def env_info(env: str, *, brief: bool = False) -> dict[str, Any]:
    label, note = ENV_LABELS.get(env, (env, ""))
    info: dict[str, Any] = {
        "name": env,
        "label": f"{label} ({env})" if not brief else label,
        "note": note,
    }
    if brief:
        return info
    from autodeck.providers.registry import ModelRegistry

    try:
        registry = ModelRegistry.load(env)
        info["roles"] = [
            {"role": role, "provider": b.provider, "model": b.model}
            for role, b in sorted(registry.bindings().items())
        ]
        info["missing_credentials"] = registry.missing_credentials()
        info["design_mode"] = registry.design_mode
    except Exception as exc:
        info["roles"] = []
        info["missing_credentials"] = []
        info["design_mode"] = "structured"
        info["note"] = f"{note} (config error: {exc})"
    return info


#: The person's choice of models, kept beside their profile so it survives a restart.
SETTINGS_FILENAME = "settings.json"


def _settings_path(roots: Roots) -> Path:
    return roots.profile.parent / SETTINGS_FILENAME


def set_env(roots: Roots, env: str) -> None:
    """Switch the models every later step runs on, and remember the choice."""
    known = {e["name"] for e in settings(roots)["envs"]}
    if env not in known:
        raise UIError(f"Unknown environment {env!r}.")
    roots.env = env
    path = _settings_path(roots)
    try:
        saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        saved = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**saved, "env": env}, indent=2), encoding="utf-8")


def restore_env(roots: Roots) -> None:
    """Use the models last chosen in the UI, if that environment still exists."""
    path = _settings_path(roots)
    try:
        env = json.loads(path.read_text(encoding="utf-8")).get("env")
    except (OSError, ValueError, AttributeError):
        return
    if isinstance(env, str) and env in {e["name"] for e in settings(roots)["envs"]}:
        roots.env = env


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def write_run_meta(
    roots: Roots,
    run_id: str,
    *,
    client: str,
    project: str,
    agent: bool | None = None,
    meeting: bool | None = None,
) -> None:
    """Remember the run's client and project; `agent` (Phase 4c) and `meeting` (step 12) are
    kept only when true.

    `None` leaves an earlier choice alone, so a later write (the CLI's own, for one) cannot
    lose it.
    """
    folder = roots.runs / run_id
    folder.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"client": client, "project": project}
    if agent or (agent is None and run_uses_agent(roots, run_id)):
        data["agent"] = True
    if meeting or (meeting is None and _meta_flag(roots, run_id, "meeting")):
        data["meeting"] = True
    (folder / UI_META).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _meta_flag(roots: Roots, run_id: str, key: str) -> bool:
    try:
        data = json.loads((roots.runs / run_id / UI_META).read_text(encoding="utf-8"))
        return bool(data.get(key))
    except (OSError, ValueError, AttributeError):
        return False


def run_uses_agent(roots: Roots, run_id: str) -> bool:
    """Whether the person chose the deck agent when starting this run."""
    return _meta_flag(roots, run_id, "agent")


def run_is_meeting(roots: Roots, run_id: str) -> bool:
    """Whether the run started from a meeting recording."""
    return (
        _meta_flag(roots, run_id, "meeting")
        or (roots.runs / run_id / "meeting" / "settings.json").is_file()
    )


def session_view(roots: Roots, run_id: str, *, active: bool) -> dict[str, Any]:
    """The agent's session for a run: the last 200 timeline rows and its meta.

    A deck session (`transcript.jsonl`) wins; a meeting run that has only a notes session
    (`notes_transcript.jsonl`, `notes_meta.json`) shows that, with `kind: "notes"`. When both
    exist the deck is shown and `notes_session` says the notes session is there too.
    """
    from autodeck.agents.session import timeline

    run_id = check_run_id(run_id)
    folder = roots.runs / run_id / "session"
    deck = folder / "transcript.jsonl"
    notes = folder / "notes_transcript.jsonl"
    if deck.is_file():
        kind, transcript, meta_name = "deck", deck, "meta.json"
    elif notes.is_file():
        kind, transcript, meta_name = "notes", notes, "notes_meta.json"
    else:
        return {"timeline": [], "meta": None, "active": False}
    try:
        rows = timeline(transcript)[-200:]
    except (OSError, ValueError, KeyError):
        rows = []
    try:
        meta = json.loads((folder / meta_name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = None
    out: dict[str, Any] = {"timeline": rows, "meta": meta, "active": active, "kind": kind}
    if kind == "deck" and notes.is_file():
        out["notes_session"] = True
    return out


def read_run_meta(roots: Roots, run_id: str) -> dict[str, str]:
    path = roots.runs / run_id / UI_META
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: str(v) for k, v in data.items() if k in ("client", "project")}
    except (OSError, ValueError):
        return {}


def list_runs(roots: Roots) -> list[dict[str, Any]]:
    """Every run under `runs/`, most recently touched first."""
    if not roots.runs.is_dir():
        return []
    folders = [p for p in roots.runs.iterdir() if p.is_dir() and RUN_ID.fullmatch(p.name)]
    folders.sort(key=_last_touched, reverse=True)
    summaries = []
    for folder in folders:
        try:
            summaries.append(run_summary(roots, folder.name))
        except UIError:
            continue
    return summaries


def _last_touched(folder: Path) -> float:
    try:
        return max(p.stat().st_mtime for p in [folder, *folder.iterdir()])
    except (OSError, ValueError):
        return 0.0


def _open(roots: Roots, run_id: str) -> Orchestrator:
    if not RUN_ID.fullmatch(run_id):
        raise UIError("Run names use letters, numbers, dots, dashes and underscores.")
    try:
        return Orchestrator(run_id, runs_root=roots.runs, create=False)
    except UnknownRunError:
        raise UIError(f"No run called {run_id!r}.", status=404) from None


def _open_or_none(roots: Roots, run_id: str) -> Orchestrator | None:
    """The run if it exists, else None (a draft may start a run that is not there yet)."""
    try:
        return _open(roots, run_id)
    except UIError:
        return None


def run_summary(roots: Roots, run_id: str, running_step: str = "") -> dict[str, Any]:
    """Where one run stands, worded for a person, from the same state `status` prints."""
    orch = _open(roots, run_id)
    state = orch.state
    meta = read_run_meta(roots, run_id)
    client, project = meta.get("client", ""), meta.get("project", "")

    gates = []
    current = {}
    for gate in Gate:
        approval, detail = orch.approval_state(gate)
        ok = approval is ApprovalState.CURRENT
        current[gate] = ok
        by, at = "", ""
        if gate.value in state.approvals:
            at, _, by = state.approvals[gate.value].partition(" by ")
        gates.append(
            {
                "gate": gate.value,
                "label": GATE_LABELS[gate],
                "approved": ok,
                "state": approval.value,
                "detail": "" if ok else detail,
                "by": by,
                "at": at[:16].replace("T", " "),
            }
        )

    stages: dict[str, str] = {}
    waiting_set = False
    for gate in Gate:
        key = GATE_KEYS[gate]
        if current[gate]:
            stages[key] = "done"
        elif not waiting_set:
            stages[key] = "now"
            waiting_set = True
        else:
            stages[key] = "todo"

    nxt, hint, resume = _next_step(orch, current, run_id, client, project)
    meeting_fields: dict[str, Any] = {}
    if run_is_meeting(roots, run_id):
        stage = meeting_stage(orch, running_step)
        meeting_fields = {"meeting": True, "meeting_stage": stage}
        if not is_draft_mode(orch):
            # A meeting run that is not yet a draft is not waiting on the gate-first steps.
            nxt, hint, resume = (
                stage,
                _meeting_hint(orch, run_id, client, project),
                (f"#/meeting/{run_id}"),
            )
    return {
        **meeting_fields,
        "stage_list": stage_list(orch, current, running_step),
        "id": run_id,
        "client": client,
        "project": project,
        "env": state.env,
        "stages": stages,
        "gates": gates,
        "next": nxt,
        "command_hint": hint,
        "resume": resume,
    }


#: The running job step, as the run list words it for a meeting run.
MEETING_RUNNING = {
    "transcribe": "Transcribing",
    "notes": "Writing the notes",
    "revise-notes": "Revising the notes",
    "clarify": "Drafting",
    "draft": "Drafting",
    "revise": "Drafting",
    "validate": "Drafting",
    "preview": "Drafting",
}


def meeting_stage(orch: Orchestrator, running_step: str = "") -> str:
    """Where a meeting run stands in one or two words: Transcribing, Notes ready, Draft..."""
    if running_step in MEETING_RUNNING:
        return MEETING_RUNNING[running_step]
    root = orch.paths.root
    if orch.state.is_complete("compose"):
        return "Draft"
    if (root / "clarify.json").exists():
        return "Drafting"
    if (root / "meeting" / "notes.md").is_file():
        return "Notes ready"
    if (root / "meeting" / "transcript.json").is_file():
        return "Transcribed"
    return "Transcribing"


def _meeting_hint(orch: Orchestrator, run_id: str, client: str, project: str) -> str:
    """The terminal command for a meeting run's next step."""
    root = orch.paths.root
    if (root / "meeting" / "notes.md").is_file():
        return (
            f"autodeck clarify {run_id} --client {client or '<client>'} "
            f"--project {project or '<project>'} --prompt ..."
        )
    if (root / "meeting" / "transcript.json").is_file():
        return f"autodeck meeting notes {run_id}"
    return ""


def _next_step(
    orch: Orchestrator, current: dict[Gate, bool], run_id: str, client: str, project: str
) -> tuple[str, str, str]:
    """(what the run waits for, the CLI command for it, a UI link to continue in)."""
    state = orch.state
    cp = (
        f" --client {client} --project {project}"
        if client and project
        else " --client <client> --project <project>"
    )
    if is_draft_mode(orch):
        link = f"#/draft/{run_id}"
        if not state.is_complete("compose"):
            if (orch.paths.root / "clarify.json").exists():
                return "Next: write the draft", f"autodeck draft {run_id}", link
            return "Next: clarify the request", f"autodeck clarify {run_id}{cp}", ""
        if not all(current[g] for g in (Gate.BRIEF, Gate.OUTLINE, Gate.CLAIMS)):
            return (
                "Waiting for you: review the draft and approve it",
                f"autodeck gate2 {run_id}",
                link,
            )
        if not current[Gate.FINAL_RENDER]:
            if state.final_assessment:
                return "Waiting for you: final approval", f"autodeck gate3 {run_id}", ""
            return "Next: render the final deck", f"autodeck render {run_id}", ""
        return "Done: all four approvals given", "", ""
    if not current[Gate.BRIEF]:
        plan_link = f"#/plan/{run_id}" if client and project else ""
        if orch.paths.draft_brief.exists():
            return "Brief draft saved, not signed", f"autodeck plan {run_id}{cp}", plan_link
        return "Planning not finished", f"autodeck plan {run_id}{cp}", plan_link
    if not current[Gate.OUTLINE]:
        if state.is_complete("outline"):
            return (
                "Waiting for you: outline approval",
                f"autodeck approve {run_id} outline --by <your name>",
                "",
            )
        return "Next: build the outline", f"autodeck outline {run_id}{cp}", ""
    if not current[Gate.CLAIMS]:
        if state.is_complete("validate"):
            return "Waiting for you: claims approval", f"autodeck gate2 {run_id}", ""
        if state.is_complete("content"):
            return "Next: validate the claims", f"autodeck validate {run_id}", ""
        return "Next: write the content", f"autodeck content {run_id}", ""
    if not current[Gate.FINAL_RENDER]:
        if state.final_assessment:
            return "Waiting for you: final approval", f"autodeck gate3 {run_id}", ""
        return "Next: render the deck", f"autodeck render {run_id}", ""
    return "Done: all four approvals given", "", ""


def stage_list(
    orch: Orchestrator, current: dict[Gate, bool], running_step: str = ""
) -> list[dict[str, Any]]:
    """The run screen's timeline: every pipeline step and approval, in order.

    `running_step` is the CLI step a UI job is running now (from `jobs.py`), if any.
    Statuses: done, running, failed, yours (waiting on a person), waiting (next for the
    pipeline), locked (an earlier step is not finished).
    """
    state = orch.state
    if is_draft_mode(orch):
        return draft_stage_list(orch, current, running_step)

    def record(name: str) -> Any:
        return state.stages.get(name)

    def step(key: str, label: str, stage: str, ready: bool, screen: str = "") -> dict[str, Any]:
        rec = record(stage)
        if running_step == stage:
            status, detail = "running", ""
        elif rec is not None and rec.status.value == "completed":
            status, detail = "done", _short_detail(rec.detail)
        elif rec is not None and rec.status.value == "failed":
            status, detail = "failed", _short_detail(rec.detail)
        else:
            status, detail = ("waiting" if ready else "locked"), ""
        finished = rec.finished_at if rec is not None and rec.finished_at else ""
        return {
            "key": key,
            "label": label,
            "status": status,
            "detail": detail,
            "finished_at": finished[:16].replace("T", " "),
            "screen": screen if status == "done" else "",
        }

    def gate_step(key: str, label: str, gate: Gate, ready: bool, screen: str) -> dict[str, Any]:
        by_at = state.approvals.get(gate.value, "")
        at, _, by = by_at.partition(" by ")
        if current[gate]:
            status, detail = "done", f"Approved by {by}"
        elif ready:
            status = "yours"
            detail = "Approval no longer current; review again" if by_at else "Waiting for you"
        else:
            status, detail = "locked", ""
        return {
            "key": key,
            "label": label,
            "status": status,
            "detail": detail,
            "finished_at": at[:16].replace("T", " ") if current[gate] else "",
            "screen": screen if status in ("done", "yours") else "",
        }

    brief_ok = current[Gate.BRIEF]
    planning = {
        "key": "planning",
        "label": "Plan the brief",
        "status": "done" if brief_ok else "yours",
        "detail": "Brief approved" if brief_ok else "Talk to the planner, then approve",
        "finished_at": "",
        "screen": "plan",
    }
    outline_done = state.is_complete("outline")
    validate_done = state.is_complete("validate")
    rendered = state.is_complete("render")
    audited = bool(state.final_assessment)
    final = {
        "key": "final_audit",
        "label": "Final audit",
        "status": "running"
        if running_step == "gate3"
        else ("done" if audited else ("waiting" if rendered else "locked")),
        "detail": (
            ("Passed" if state.final_assessment.get("passes") else "Did not pass")
            if audited
            else ""
        ),
        "finished_at": str(state.final_assessment.get("at", ""))[:16].replace("T", " "),
        "screen": "final" if audited else "",
    }
    return [
        planning,
        step("outline", "Build the outline", "outline", brief_ok),
        gate_step(
            "outline_approval", "Approve the outline", Gate.OUTLINE, outline_done, "outline"
        ),
        step("content", "Write the slides", "content", current[Gate.OUTLINE]),
        step("validate", "Check every claim", "validate", state.is_complete("content")),
        gate_step(
            "claims_approval", "Approve the claims", Gate.CLAIMS, validate_done, "claims"
        ),
        step("render", "Art direction and render", "render", current[Gate.CLAIMS]),
        final,
        gate_step(
            "final_approval",
            "Approve the final deck",
            Gate.FINAL_RENDER,
            audited and bool(state.final_assessment.get("passes")),
            "final",
        ),
    ]


def is_draft_mode(orch: Orchestrator | None) -> bool:
    """Whether the run is draft-first (B43): clarified or composed, rather than planned.

    A run counts from the moment its clarify step has run, so the timeline shows the draft
    being written, not the gate-first steps it will never take.
    """
    if orch is None:
        return False
    return (
        orch.is_draft_first
        or orch.state.stages.get("compose") is not None
        or (orch.paths.root / "clarify.json").exists()
    )


def draft_stage_list(
    orch: Orchestrator, current: dict[Gate, bool], running_step: str = ""
) -> list[dict[str, Any]]:
    """The timeline for a draft-first run: clarify, compose, checks, previews, approvals.

    Same statuses and shape as `stage_list`. The three approvals are given on the assembled
    draft, in the order brief, outline, claims; the final deck follows them (A7, B43).
    """
    state = orch.state

    def stage(
        key: str, label: str, name: str, ready: bool, running: str, screen: str = ""
    ) -> dict[str, Any]:
        rec = state.stages.get(name)
        if running_step == running:
            status, detail = "running", ""
        elif rec is not None and rec.status.value == "completed":
            status, detail = "done", _short_detail(rec.detail)
        elif rec is not None and rec.status.value == "failed":
            status, detail = "failed", _short_detail(rec.detail)
        else:
            status, detail = ("waiting" if ready else "locked"), ""
        finished = rec.finished_at if rec is not None and rec.finished_at else ""
        return {
            "key": key,
            "label": label,
            "status": status,
            "detail": detail,
            "finished_at": finished[:16].replace("T", " "),
            "screen": screen if status == "done" else "",
        }

    def approval(key: str, label: str, gate: Gate, ready: bool) -> dict[str, Any]:
        by_at = state.approvals.get(gate.value, "")
        at, _, by = by_at.partition(" by ")
        if current[gate]:
            status, detail = "done", f"Approved by {by}"
        elif ready:
            status = "yours"
            detail = "Approval no longer current; review again" if by_at else "Waiting for you"
        else:
            status, detail = "locked", ""
        return {
            "key": key,
            "label": label,
            "status": status,
            "detail": detail,
            "finished_at": at[:16].replace("T", " ") if current[gate] else "",
            "screen": "draft" if status in ("done", "yours") else "",
        }

    composed = state.is_complete("compose")
    validated = state.is_complete("validate")
    rendered = state.is_complete("render")
    audited = bool(state.final_assessment)
    final = {
        "key": "final_audit",
        "label": "Final audit",
        "status": "running"
        if running_step == "gate3"
        else ("done" if audited else ("waiting" if rendered else "locked")),
        "detail": (
            ("Passed" if state.final_assessment.get("passes") else "Did not pass")
            if audited
            else ""
        ),
        "finished_at": str(state.final_assessment.get("at", ""))[:16].replace("T", " "),
        "screen": "final" if audited else "",
    }
    return [
        stage("clarify", "Check what the draft needs", "clarify", True, "clarify"),
        stage(
            "compose",
            "Write brief, outline and slides",
            "compose",
            state.is_complete("clarify") or orch.paths.draft_brief.exists(),
            "draft" if running_step == "draft" else "revise",
            "draft",
        ),
        stage("validate", "Check every claim", "validate", composed, "validate", "draft"),
        stage("preview", "Draw the draft", "preview", composed, "preview", "draft"),
        approval("brief_approval", "Approve the brief", Gate.BRIEF, composed and validated),
        approval(
            "outline_approval", "Approve the outline", Gate.OUTLINE, composed and validated
        ),
        approval("claims_approval", "Approve the claims", Gate.CLAIMS, composed and validated),
        stage(
            "render",
            "Art direction and render",
            "render",
            current[Gate.BRIEF] and current[Gate.OUTLINE] and current[Gate.CLAIMS],
            "render",
        ),
        final,
        approval(
            "final_approval",
            "Approve the final deck",
            Gate.FINAL_RENDER,
            audited and bool(state.final_assessment.get("passes")),
        ),
    ]


def _short_detail(detail: str) -> str:
    """A stage's detail line with the written file cut to its name: `wrote v3.json`.

    Stages record `wrote <path>` (paths may hold spaces), optionally followed by ` · ...`.
    """
    return re.sub(
        r"\bwrote (.+?)(?= · |$)",
        lambda m: "wrote " + re.split(r"[\\/]", m.group(1).rstrip())[-1],
        detail or "",
    )


def check_run_id(run_id: str) -> str:
    run_id = run_id.strip()
    if not RUN_ID.fullmatch(run_id):
        raise UIError("Run names use letters, numbers, dots, dashes and underscores.")
    return run_id


def home(roots: Roots) -> dict[str, Any]:
    from autodeck.ui.profile import read_profile

    return {
        "profile": read_profile(roots.profile),
        "env": env_info(roots.env),
        "checks": readiness(roots),
        "clients": list_clients(roots),
        "projects": list_projects(roots),
        "runs": list_runs(roots),
    }


# ---------------------------------------------------------------------------
# Draft-first: the clarify checkpoint and the assembled draft (B43, B47, B48)
# ---------------------------------------------------------------------------

DRAFT_PREVIEW_DIR = ("previews", "draft")
_DRAFT_PNG = re.compile(r"^.+-(\d+)\.png$")


def clarify_view(roots: Roots, run_id: str) -> dict[str, Any]:
    """The checkpoint: what the draft will assume, its questions, and any answers so far."""
    from autodeck.pipeline.clarify_state import (
        ClarifyStateError,
        is_answered,
        load_clarify,
        missing_answers,
    )

    orch = _open(roots, run_id)
    try:
        data = load_clarify(orch.paths.root)
    except ClarifyStateError as exc:
        raise UIError(str(exc), status=404) from None
    redesign = (orch.paths.root / "redesign.json").exists()
    return {
        **data,
        "answered": is_answered(data),
        "missing": missing_answers(data),
        "mode": "redesign" if redesign else "draft",
    }


def _draft_images(orch: Orchestrator) -> dict[int, Path]:
    folder = orch.paths.root.joinpath(*DRAFT_PREVIEW_DIR)
    if not folder.is_dir():
        return {}
    found = {}
    for path in folder.glob("*.png"):
        match = _DRAFT_PNG.match(path.name)
        if match:
            found[int(match.group(1))] = path
    return found


def draft_preview_file(roots: Roots, run_id: str, n: int) -> tuple[bytes, str]:
    """One slide's DRAFT preview PNG from `previews/draft/`. Only an int picks the file."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise UIError("Slide number must be a whole number from 1.", status=404)
    path = _draft_images(_open(roots, run_id)).get(n)
    if path is None:
        raise UIError(f"No draft preview for slide {n}.", status=404)
    try:
        return path.read_bytes(), "image/png"
    except OSError:
        raise UIError(f"No draft preview for slide {n}.", status=404) from None


def _block_view(block: Any, times: dict[str, dict[int, float]] | None = None) -> dict[str, Any]:
    claim = block.claim
    return {
        "id": block.id,
        "kind": block.kind,
        "slot": block.slot,
        "text": claim.text if claim is not None else (block.text or ""),
        "verdict": claim.verdict if claim is not None else "",
        "verdict_notes": (claim.verdict_notes or "") if claim is not None else "",
        "basis": claim.basis if claim is not None else "",
        "citations": [
            _citation_view(c, times) for c in (claim.citations if claim is not None else [])
        ],
    }


def _citation_view(c: Any, times: dict[str, dict[int, float]] | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "doc_id": c.doc_id,
        "page": c.page,
        "quote": c.quote,
        "source_class": c.source_class,
    }
    if c.source_class == "transcript":
        # The meeting's time for the turn, for "from the meeting · mm:ss" (step 12). Local UI
        # only: the Document itself carries no times (B79, A6).
        from autodeck.audit.report import meeting_stamp

        seconds = (times or {}).get(c.doc_id, {}).get(c.page) if c.page is not None else None
        out["time"] = meeting_stamp(seconds) if seconds is not None else None
    return out


def draft_view(roots: Roots, run_id: str) -> dict[str, Any]:
    """The assembled draft as data: slides with citations and verdicts, the draft brief with
    its evidence, coverage, approval state and preview image links. Reads files only; the
    draft is built by the `draft` and `revise` jobs, and approving it is `approve_run`'s job.
    """
    from autodeck.agents.planner import Draft
    from autodeck.ir.store import IRStoreError
    from autodeck.render.draft import slide_flags
    from autodeck.ui.review import _approval

    orch = _open(roots, run_id)
    if not orch.state.is_complete("compose"):
        raise UIError("There is no draft for this run yet.", status=409)
    try:
        deck = orch.ir.load()
    except (IRStoreError, ValueError) as exc:
        raise UIError(f"The draft cannot be read: {exc}", status=409) from None

    extras: dict[str, Any] = {}
    try:
        loaded = json.loads((orch.paths.root / "coverage.json").read_text(encoding="utf-8"))
        extras = loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        pass
    origins = extras.get("origins") or {}
    flags = slide_flags(deck)
    images = _draft_images(orch)

    redesign = _redesign_info(roots, orch, run_id, extras, {s.id for s in deck.slides})
    from autodeck.ingest.transcript_source import meeting_times

    times = meeting_times(orch.paths.root)
    story = deck.storyline_check
    slides = []
    for number, slide in enumerate(deck.slides, start=1):
        slides.append(
            {
                **(
                    {
                        "original": _original_slides(
                            redesign["store"],
                            slide,
                            mapped=_mapped_originals(redesign, slide.id),
                        )
                    }
                    if redesign is not None
                    else {}
                ),
                "id": slide.id,
                "n": number,
                "role": slide.narrative_role,
                "component": slide.component,
                "intent": slide.intent or "",
                "message_ids": list(slide.message_ids),
                "flag": flags.get(slide.id, ""),
                "headline_check": (
                    slide.headline_check.model_dump(mode="json")
                    if slide.headline_check is not None
                    else None
                ),
                # B70: advisory only; never blocks anything.
                "storyline_findings": [
                    f.model_dump(mode="json")
                    for f in (story.findings if story is not None else [])
                    if f.slide_id == slide.id
                ],
                "blocks": [_block_view(b, times) for b in slide.blocks],
                "notes": [_block_view(b, times) for b in slide.speaker_notes],
                "preview": (
                    f"/api/runs/{run_id}/draft-preview/{number}" if number in images else None
                ),
            }
        )

    brief: dict[str, Any] = {}
    try:
        draft = Draft.from_dict(json.loads(orch.paths.draft_brief.read_text(encoding="utf-8")))
        brief = {
            "objective": draft.objective,
            "audience": draft.audience,
            "length_target": draft.length_target,
            "key_messages": [
                {
                    "id": m.id,
                    "text": m.text,
                    "origin": origins.get(m.id, ""),
                    "evidence": m.evidence_status,
                    "notes": m.probe_notes or "",
                    "leads": list(m.supporting_claims),
                    "slides": [s.id for s in deck.slides if m.id in s.message_ids],
                }
                for m in draft.key_messages
            ],
            "must_include": list(draft.must_include),
            "must_avoid": list(draft.must_avoid),
            "open_risks": [
                {
                    "message_id": r.message_id,
                    "description": r.description,
                    "accepted_by": r.accepted_by,
                }
                for r in draft.open_risks
            ],
        }
    except (OSError, ValueError, TypeError):
        pass

    approvals = {}
    for key, gate in (
        ("brief", Gate.BRIEF),
        ("outline", Gate.OUTLINE),
        ("claims", Gate.CLAIMS),
        ("final", Gate.FINAL_RENDER),
    ):
        approvals[key] = _approval(orch, gate)

    return {
        **(
            {"redesign": {"settings": redesign["settings"], "changes": redesign["changes"]}}
            if redesign is not None
            else {}
        ),
        "run_id": run_id,
        "meeting": run_is_meeting(roots, run_id),
        "version": deck.version,
        "validated": orch.state.is_complete("validate"),
        "previewed": orch.state.is_complete("preview"),
        "slides": slides,
        "storyline_check": story.model_dump(mode="json") if story is not None else None,
        "brief": brief,
        "coverage": extras.get("coverage", []),
        "rejections": extras.get("rejections", []),
        "provenance": run_provenance(roots, run_id),
        "design_mode": run_design_mode(roots, run_id),
        "failures": extras.get("failures", []),
        "advisories": extras.get("advisories", []),
        "repairs": extras.get("repairs", []),
        "repair_ran": bool(extras.get("repair_ran", False)),
        "corrections": extras.get("corrections", []),
        "incomplete_slots": extras.get("incomplete_slots", []),
        "notes": extras.get("notes", ""),
        "approvals": approvals,
        "flags": flags,
        "previews": [f"/api/runs/{run_id}/draft-preview/{n}" for n in sorted(images)],
        "revisions": _read_revisions(orch),
    }


def _redesign_info(
    roots: Roots, orch: Orchestrator, run_id: str, extras: dict[str, Any], slide_ids: set[str]
) -> dict[str, Any] | None:
    """A redesign run's settings, layout notes and run-local deck store; None otherwise."""
    from autodeck.ingest.deck_source import run_source_root
    from autodeck.ingest.document_store import DocumentStore
    from autodeck.ingest.redesign_settings import RedesignSettingsError, load_redesign

    try:
        settings = load_redesign(orch.paths.root)
    except RedesignSettingsError:
        return None
    if settings is None:
        return None
    changes = [
        c
        for c in extras.get("changes") or []
        if isinstance(c, dict) and c.get("slide_id") in slide_ids
    ]
    return {
        "settings": settings,
        "changes": changes,
        "store": DocumentStore(run_source_root(roots.runs, run_id)),
    }


def _mapped_originals(redesign: dict[str, Any], slide_id: str) -> list[int]:
    """Original slide numbers the composer said this slide was built from (`changes`)."""
    for change in redesign.get("changes") or []:
        if change.get("slide_id") == slide_id:
            return [int(n) for n in change.get("original_slides") or [] if str(n).isdigit()]
    return []


def _original_slides(
    store: Any, slide: Any, *, mapped: list[int] | None = None
) -> list[dict[str, Any]]:
    """The text of each original slide this slide came from, in slide order.

    The slides its blocks cite, plus the slides the redesign's `changes` map it to — so a
    title or framing-only slide, which cites nothing, still shows the slide it replaced. The
    text is read from the run-local store (never a model's say-so), so the review screen puts
    the client's own wording beside the proposal.
    """
    from autodeck.ingest.deck_source import DOC_ID_PREFIX
    from autodeck.ingest.document_store import IngestError

    cited: dict[tuple[str, int], None] = {}
    deck_ids = [d for d in store.doc_ids() if d.startswith(DOC_ID_PREFIX)]
    for page in mapped or []:
        for doc_id in deck_ids:
            cited[(doc_id, page)] = None
    for site in slide.claim_sites():
        for citation in site.claim.citations:
            if citation.doc_id.startswith(DOC_ID_PREFIX):
                cited[(citation.doc_id, citation.page)] = None
    out = []
    for doc_id, page in sorted(cited, key=lambda k: (k[1], k[0])):
        try:
            document = store.get(doc_id)
        except IngestError:
            continue
        texts = [
            e.text.strip()
            for e in sorted(document.elements, key=lambda e: e.reading_order)
            if e.page == page and e.text.strip()
        ]
        out.append({"slide": page, "text": "\n\n".join(texts)})
    return out


def _read_revisions(orch: Orchestrator) -> list[dict[str, str]]:
    """The conversation so far: each instruction and the composer's reply, oldest first."""
    path = orch.paths.root / "revisions.jsonl"
    out: list[dict[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append({k: str(item.get(k, "")) for k in ("instruction", "reply", "at")})
    return out


# ---------------------------------------------------------------------------
# Agent memory (B77)
# ---------------------------------------------------------------------------

MEMORY_AUDIT_LIMIT = 50


def _memory_store(roots: Roots, client: str, project: str):  # type: ignore[no-untyped-def]
    from autodeck.knowledge.loader import KnowledgeError
    from autodeck.knowledge.memory import MemoryStore
    from autodeck.ui.profile import owner_memory_path

    if not client or not project:
        raise UIError("Pick a client and a project.")
    if client not in list_clients(roots) or project not in list_projects(roots):
        raise UIError(f"No client {client!r} with project {project!r}.", status=404)
    try:
        return MemoryStore(
            roots.knowledge,
            client=client,
            project=project,
            run_id="ui",
            owner_path=owner_memory_path(),
        )
    except KnowledgeError as exc:
        raise UIError(str(exc)) from None


def memory_view(roots: Roots, client: str, project: str) -> dict[str, Any]:
    """Both memory files and the last changes to either, newest first."""
    from autodeck.knowledge.loader import KnowledgeError

    store = _memory_store(roots, client, project)
    try:
        engagement = store.read("engagement")
    except KnowledgeError as exc:
        raise UIError(str(exc)) from None
    records: list[dict[str, Any]] = []
    for scope in ("engagement", "owner"):
        log = store.path(scope).parent / "audit.jsonl"  # type: ignore[arg-type]
        if not log.is_file():
            continue
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append({**record, "scope": scope})
    records.sort(key=lambda r: str(r.get("at", "")), reverse=True)
    return {
        "engagement": engagement,
        "owner": store.read("owner"),
        "audit": records[:MEMORY_AUDIT_LIMIT],
    }


def save_memory(
    roots: Roots, client: str, project: str, scope: str, content: str
) -> dict[str, Any]:
    """Replace one memory file with the person's edit; the store's checks still apply."""
    from autodeck.knowledge.loader import KnowledgeError

    if scope not in ("engagement", "owner"):
        raise UIError("scope is engagement or owner.")
    store = _memory_store(roots, client, project)
    try:
        message = store.rewrite(scope, content)  # type: ignore[arg-type]
    except KnowledgeError as exc:  # MemoryWriteError and ClientIsolationError
        raise UIError(str(exc)) from None
    return {"scope": scope, "text": store.read(scope), "message": message}  # type: ignore[arg-type]
