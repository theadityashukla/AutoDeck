"""`render` starts from the IR version `validate` recorded (DECISIONS B38).

Without it, a second `render` art-directed the first render's output, so identical model
replies gave a different deck and voided a `final_render` approval.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from autodeck.audit.manifest import canonical_pptx_digest
from autodeck.ir.actions import SetAccent
from autodeck.ir.models import Block
from autodeck.ir.store import IRStore
from autodeck.pipeline.orchestrator import ApprovalState, Gate, Orchestrator
from tests.test_aesthetic import FakeCritic, reply
from tests.test_art_direction import FakeArtModel
from tests.test_gate3 import _gate3, _invoke, art_plan, make_gate3_run, patch_roles


def _icon_count(blocks: Sequence[Block]) -> int:
    return sum(1 for block in blocks if block.kind == "icon")


def _scripted_twice(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeArtModel, FakeCritic]:
    """Identical replies for two renders: the same art plan, and a critic that restyles slide
    1 on the first look and is content on the second, each time."""
    art = FakeArtModel(art_plan(), art_plan())
    critic = FakeCritic(
        reply(5.0, SetAccent(slide_id="s1", accent="accent2"), rationale="Second accent."),
        reply(9.0, rationale="good"),
        reply(5.0, SetAccent(slide_id="s1", accent="accent2"), rationale="Second accent."),
        reply(9.0, rationale="good"),
    )
    patch_roles(monkeypatch, outline=art, aesthetic=critic)
    return art, critic


@pytest.mark.render
def test_a_second_render_with_identical_replies_gives_the_same_deck_and_keeps_the_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root, knowledge = make_gate3_run(tmp_path)
    _scripted_twice(monkeypatch)
    deck_path = runs_root / "r1" / "deck.pptx"

    assert _invoke(runs_root, "render", "r1").exit_code == 0
    assert _gate3(runs_root, knowledge).exit_code == 0
    approved = _invoke(runs_root, "approve", "r1", "final_render")
    assert approved.exit_code == 0, approved.output
    first_digest = canonical_pptx_digest(deck_path)
    orchestrator = Orchestrator("r1", runs_root=runs_root)
    assert orchestrator.approval_state(Gate.FINAL_RENDER) == (ApprovalState.CURRENT, "approved")

    again = _invoke(runs_root, "render", "r1")

    assert again.exit_code == 0, again.output
    assert canonical_pptx_digest(deck_path) == first_digest
    reopened = Orchestrator("r1", runs_root=runs_root)
    assert reopened.approval_state(Gate.FINAL_RENDER) == (ApprovalState.CURRENT, "approved")
    assert reopened.approval_state(Gate.CLAIMS) == (ApprovalState.CURRENT, "approved")
    # Each render wrote its own two versions on top of the validated v1.
    assert IRStore(runs_root, "r1").versions() == [1, 2, 3, 4, 5]


@pytest.mark.render
def test_the_second_render_art_directs_the_validated_ir_not_the_first_renders_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root, _knowledge = make_gate3_run(tmp_path)
    art, critic = _scripted_twice(monkeypatch)
    store = IRStore(runs_root, "r1")
    validated = store.load(1)
    assert _icon_count(validated.slides[2].blocks) == 0

    assert _invoke(runs_root, "render", "r1").exit_code == 0
    assert _icon_count(store.load(2).slides[2].blocks) == 3
    assert store.load(3).slides[0].style.accent == "accent2"

    again = _invoke(runs_root, "render", "r1")

    assert again.exit_code == 0, again.output
    # The art director was shown the same deck twice: no icons yet, no second accent yet.
    assert art.calls == 2 and art.prompts[0] == art.prompts[1]
    # So the plan assigned the icons afresh instead of being rejected for finding them there.
    assert "applied  assign_icons" in again.output
    assert "1 action(s) applied, 0 rejected" in again.output
    # The critic saw slide 1 in its validated style both times.
    assert critic.calls == 4
    assert store.load(4).slides[0].style.accent != "accent2"
    assert _icon_count(store.load(4).slides[2].blocks) == 3
    assert store.load(5).slides[0].style.accent == "accent2"
    # Same presentation, different version numbers.
    assert store.load(4).model_dump(exclude={"version"}) == store.load(2).model_dump(
        exclude={"version"}
    )
    assert store.load(5).model_dump(exclude={"version"}) == store.load(3).model_dump(
        exclude={"version"}
    )


def test_render_without_a_recorded_validate_version_says_to_run_validate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Normally the claims gate stops this first; `render` still refuses on its own."""
    runs_root, _knowledge = make_gate3_run(tmp_path)
    patch_roles(monkeypatch, outline=FakeArtModel(), aesthetic=FakeCritic())
    monkeypatch.setattr(Orchestrator, "require_gate", lambda self, gate: None)
    state_file = runs_root / "r1" / "state.json"
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    payload["stages"]["validate"]["ir_version"] = None
    state_file.write_text(json.dumps(payload), encoding="utf-8")

    result = _invoke(runs_root, "render", "r1")

    assert result.exit_code == 3, result.output
    assert "autodeck validate r1" in result.output
    assert "Traceback" not in result.output
    assert not (runs_root / "r1" / "deck.pptx").exists()
    assert IRStore(runs_root, "r1").versions() == [1]


def test_render_with_an_unreadable_validated_ir_says_to_run_validate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root, _knowledge = make_gate3_run(tmp_path)
    patch_roles(monkeypatch, outline=FakeArtModel(), aesthetic=FakeCritic())
    monkeypatch.setattr(Orchestrator, "require_gate", lambda self, gate: None)

    store = IRStore(runs_root, "r1")
    store.version_path(1).unlink()
    gone = _invoke(runs_root, "render", "r1")
    assert gone.exit_code == 1, gone.output
    assert "IR v1 not found" in gone.output
    assert "autodeck validate r1" in gone.output

    store.version_path(1).write_text("{not json", encoding="utf-8")
    broken = _invoke(runs_root, "render", "r1")
    assert broken.exit_code == 1, broken.output
    assert "autodeck validate r1" in broken.output
    assert "Traceback" not in broken.output
