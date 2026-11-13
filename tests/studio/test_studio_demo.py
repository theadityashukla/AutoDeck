"""The Phase 0 demo script (`scripts/studio_demo.py`)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.studio.helpers import DEV_TOKENS, REPO_ROOT


def _demo() -> ModuleType:
    path = REPO_ROOT / "scripts" / "studio_demo.py"
    spec = importlib.util.spec_from_file_location("studio_demo", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


def test_defaults() -> None:
    demo = _demo()
    args = demo.parse_args([])
    assert args.tokens == DEV_TOKENS
    assert args.knowledge_root == REPO_ROOT / "knowledge"
    assert args.keep is False
    args = demo.parse_args(["--keep", "--tokens", "x.json"])
    assert args.keep is True and args.tokens == Path("x.json")


@pytest.mark.render
def test_the_demo_runs_and_undo_is_exact(tmp_path: Path) -> None:
    demo = _demo()
    result = demo.run_demo(
        tokens_path=DEV_TOKENS,
        knowledge_root=REPO_ROOT / "knowledge",
        workspace_root=tmp_path / "ws",
    )
    assert result.undo_exact
    text = "\n".join(result.lines)
    assert "pptx build:" in text and "previews:" in text and "c0001" in text
    assert result.workspace_root == tmp_path / "ws"


@pytest.mark.render
def test_main_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert _demo().main([]) == 0
    out = capsys.readouterr().out
    assert "byte-identical to before: yes" in out
