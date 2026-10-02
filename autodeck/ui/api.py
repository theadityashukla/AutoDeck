"""What the review UI shows and does, as plain functions over the repository (B40).

Every function here reads the same files the CLI reads, or calls the same code it calls.
None of them approves a gate: signing the brief goes through `PlannerSession.sign_off`
(in `server.py`), and the other three approvals stay with `autodeck approve` until the UI
grows its own path through that command (A7, B39).

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
    "dev": (
        "Draft models",
        "Free-tier models. Fine for trying the flow; a dev deck is a draft, never a client "
        "deliverable, and an accuracy result on dev is a smoke test (B8).",
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


def _default_env() -> str:
    from autodeck.providers.registry import ModelRegistry

    try:
        return ModelRegistry.load().env
    except Exception:
        return "dev"


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
    return {"env": env_info(roots.env), "envs": [env_info(n, brief=True) for n in names]}


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
    except Exception as exc:
        info["roles"] = []
        info["missing_credentials"] = []
        info["note"] = f"{note} (config error: {exc})"
    return info


def set_env(roots: Roots, env: str) -> None:
    known = {e["name"] for e in settings(roots)["envs"]}
    if env not in known:
        raise UIError(f"Unknown environment {env!r}.")
    roots.env = env


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def write_run_meta(roots: Roots, run_id: str, *, client: str, project: str) -> None:
    folder = roots.runs / run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / UI_META).write_text(
        json.dumps({"client": client, "project": project}, indent=2), encoding="utf-8"
    )


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


def run_summary(roots: Roots, run_id: str) -> dict[str, Any]:
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
    return {
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


def check_run_id(run_id: str) -> str:
    run_id = run_id.strip()
    if not RUN_ID.fullmatch(run_id):
        raise UIError("Run names use letters, numbers, dots, dashes and underscores.")
    return run_id


def home(roots: Roots) -> dict[str, Any]:
    return {
        "env": env_info(roots.env),
        "checks": readiness(roots),
        "clients": list_clients(roots),
        "projects": list_projects(roots),
        "runs": list_runs(roots),
    }
