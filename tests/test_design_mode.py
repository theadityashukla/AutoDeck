"""B69: a run's design mode — the snapshot, the per-environment default, CLI and UI wiring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import autodeck.agents.compose as compose_module
from autodeck.pipeline.design_mode import (
    DesignModeError,
    design_mode_path,
    load_design_mode,
    resolve_design_mode,
    snapshot_design_mode,
)
from autodeck.providers.registry import DEFAULT_CONFIG_PATH, ModelRegistry, RegistryError
from autodeck.ui import api
from autodeck.ui.api import Roots, UIError
from autodeck.ui.server import App
from tests.test_cli_draft import CLARIFIED, World, claim_slide
from tests.test_provenance_wiring import _composed, _drafted
from tests.test_ui import make_client
from tests.test_ui import roots as roots  # noqa: F401
from tests.test_ui_draft import StubJobs, seed_draft, stub_clarify

CONFIG = Path(__file__).resolve().parents[1] / DEFAULT_CONFIG_PATH

# -- the snapshot -----------------------------------------------------------------------------


def test_a_run_without_a_snapshot_is_structured(tmp_path: Path) -> None:
    assert load_design_mode(tmp_path) == "structured"


def test_resolve_uses_the_default_and_snapshots_it(tmp_path: Path) -> None:
    assert resolve_design_mode(tmp_path, "creative") == "creative"
    assert json.loads(design_mode_path(tmp_path).read_text()) == {"design_mode": "creative"}
    assert load_design_mode(tmp_path) == "creative"


def test_an_override_wins_before_the_snapshot(tmp_path: Path) -> None:
    assert resolve_design_mode(tmp_path, "structured", "creative") == "creative"


def test_the_snapshot_ignores_a_later_default(tmp_path: Path) -> None:
    resolve_design_mode(tmp_path, "structured")
    assert resolve_design_mode(tmp_path, "creative") == "structured"
    assert snapshot_design_mode(tmp_path, "creative") == "structured"


def test_a_differing_override_after_the_snapshot_is_an_error(tmp_path: Path) -> None:
    resolve_design_mode(tmp_path, "structured")
    assert resolve_design_mode(tmp_path, "creative", "structured") == "structured"
    with pytest.raises(DesignModeError, match="already fixed"):
        resolve_design_mode(tmp_path, "structured", "creative")


def test_an_unreadable_snapshot_is_an_error_not_a_silent_default(tmp_path: Path) -> None:
    design_mode_path(tmp_path).write_text("not json")
    with pytest.raises(DesignModeError, match="cannot be read"):
        load_design_mode(tmp_path)
    design_mode_path(tmp_path).write_text('{"design_mode": "wild"}')
    with pytest.raises(DesignModeError, match="must be one of"):
        load_design_mode(tmp_path)
    with pytest.raises(DesignModeError):
        snapshot_design_mode(tmp_path / "other", "wild")  # type: ignore[arg-type]


# -- the per-environment default --------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "expected"), [("dev-mistral", "structured"), ("sit", "creative"), ("prod", "creative")]
)
def test_the_shipped_default_per_environment(env: str, expected: str) -> None:
    assert ModelRegistry.load(env, CONFIG).design_mode == expected


def test_a_missing_key_means_structured_and_a_bad_one_is_refused(tmp_path: Path) -> None:
    roles = "".join(
        f"    {r}: {{provider: mistral, model: m}}\n"
        for r in ("planner", "outline", "content", "composer", "validation", "aesthetic", "ingest_vlm")
    ) + "    advisor: {provider: mistral, model: m-advisor}\n"
    path = tmp_path / "models.yaml"
    path.write_text(f"default_env: a\nenvironments:\n  a:\n{roles}")
    assert ModelRegistry.load("a", path).design_mode == "structured"
    path.write_text(f"default_env: a\nenvironments:\n  a:\n    design_mode: wild\n{roles}")
    with pytest.raises(RegistryError, match="design_mode"):
        ModelRegistry.load("a", path)


# -- CLI --------------------------------------------------------------------------------------


def _capture_compose(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    real = compose_module.compose_deck

    def spy(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(compose_module, "compose_deck", spy)
    return seen


def _clarify_with(world: World, *extra: str):  # type: ignore[no-untyped-def]
    return world.run(
        "clarify", "r1", "--client", "acme", "--project", "attention-efficiency",
        "--prompt", "Show that the kernel rewrite raised training throughput.",
        *extra, *world.data_roots,
    )  # fmt: skip


def test_the_cli_option_reaches_compose_deck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, _composed(claim_slide("s1", "Rose.", ["km1"])))
    seen = _capture_compose(monkeypatch)
    result = _clarify_with(w, "--design-mode", "creative")
    assert result.exit_code == 0, result.output
    assert "Design mode: creative" in result.output
    assert w.run("answer", "r1", "--accept-all", *w.roots).exit_code == 0
    assert w.run("draft", "r1", *w.data_roots).exit_code == 0
    assert seen[0]["design_mode"] == "creative"


def test_the_cli_defaults_to_the_environment_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, _composed(claim_slide("s1", "Rose.", ["km1"])))
    seen = _capture_compose(monkeypatch)
    _drafted(w)
    assert (w.runs / "r1" / "design_mode.json").exists()
    assert w.run("draft", "r1", *w.data_roots).exit_code == 0
    assert seen[0]["design_mode"] == ModelRegistry.load(None).design_mode == "structured"


def test_the_cli_refuses_a_change_after_the_mode_is_fixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED, CLARIFIED)
    assert _clarify_with(w, "--design-mode", "structured").exit_code == 0
    again = _clarify_with(w, "--design-mode", "creative")
    assert again.exit_code == 1 and "already fixed" in again.output
    bad = _clarify_with(w, "--design-mode", "wild")
    assert bad.exit_code == 1 and "structured" in bad.output


def test_models_command_shows_the_design_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch)
    result = w.run("models")
    assert result.exit_code == 0 and "design mode" in result.output


# -- UI ---------------------------------------------------------------------------------------


def test_draft_start_passes_the_design_mode_to_clarify(roots: Roots) -> None:  # noqa: F811
    make_client(roots)
    calls: list[list[str]] = []
    app = App(roots, StubJobs(), cli_runner=stub_clarify(roots, calls))  # type: ignore[arg-type]
    app.start_draft(
        {"run_id": "r1", "client": "acme", "project": "proj", "prompt": "x",
         "design_mode": "creative"}
    )  # fmt: skip
    assert calls[0][calls[0].index("--design-mode") + 1] == "creative"
    app.start_draft({"run_id": "r2", "client": "acme", "project": "proj", "prompt": "x"})
    assert "--design-mode" not in calls[1]
    with pytest.raises(UIError, match="design_mode"):
        app.start_draft(
            {"run_id": "r3", "client": "acme", "project": "proj", "prompt": "x",
             "design_mode": "wild"}
        )  # fmt: skip


def test_the_api_snapshots_for_a_chat_started_run(roots: Roots) -> None:  # noqa: F811
    assert api.snapshot_run_design_mode(roots, "p1", "creative") == "creative"
    assert api.run_design_mode(roots, "p1") == "creative"
    with pytest.raises(UIError, match="already fixed"):
        api.snapshot_run_design_mode(roots, "p1", "structured")
    assert api.snapshot_run_design_mode(roots, "p2", None) == api.env_info(roots.env)["design_mode"]


def test_the_draft_view_and_home_expose_the_design_mode(roots: Roots) -> None:  # noqa: F811
    seed_draft(roots)
    assert api.draft_view(roots, "r1")["design_mode"] == "structured"
    (roots.runs / "r1").mkdir(exist_ok=True)
    resolve_design_mode(roots.runs / "r1", "creative")
    assert api.draft_view(roots, "r1")["design_mode"] == "creative"
    assert api.home(roots)["env"]["design_mode"] in ("structured", "creative")
