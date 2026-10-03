"""Draft previews (3c.8, B43): renderable without approval, unable to write `deck.pptx`.

The core tests stub the drawing step (`_build_pptx`) with a plain python-pptx file, so they
need neither fonts nor LibreOffice; the one real-render test carries the `render` marker.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation
from typer.testing import CliRunner

from autodeck.cli import app
from autodeck.design.fonts import is_available
from autodeck.ir.models import Deck
from autodeck.pipeline.orchestrator import Orchestrator
from autodeck.render import draft
from autodeck.render.draft import (
    DRAFT_MARKER_NAME,
    DRAFT_MARKER_TEXT,
    render_draft,
    slide_flags,
)
from autodeck.render.qa.libreoffice import RenderError
from tests.test_cli_gate2 import _validated_run
from tests.test_renderer import _claim_block, _deck, _slide, tokens_for


def _one(slide_id: str, verdict: str) -> object:
    return _slide(
        slide_id, "bullets_supporting", [_claim_block("headline", "Text.", verdict=verdict)]
    )  # type: ignore[arg-type]


def _deck_with(*verdicts: str) -> Deck:
    return _deck(*[_one(f"s{i}", v) for i, v in enumerate(verdicts, 1)])  # type: ignore[arg-type]


@pytest.fixture
def stub_build(monkeypatch: pytest.MonkeyPatch) -> None:
    def build(deck: Deck, tokens: object, out_path: Path) -> dict[str, str]:
        presentation = Presentation()
        for _ in deck.slides:
            presentation.slides.add_slide(presentation.slide_layouts[6])
        presentation.save(str(out_path))
        return {}

    monkeypatch.setattr(draft, "_build_pptx", build)


def test_flags_come_from_verdicts() -> None:
    deck = _deck_with(
        "supported", "partially_supported", "unsupported", "contradicted", "unverified"
    )
    assert slide_flags(deck) == {
        "s1": "",
        "s2": "partial",
        "s3": "blocking",
        "s4": "blocking",
        "s5": "blocking",
    }


def test_draft_renders_blocked_deck_without_approval_and_never_writes_deck_pptx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_build: None
) -> None:
    monkeypatch.setattr(
        draft, "render_pptx", lambda *a, **k: (_ for _ in ()).throw(RenderError("x"))
    )
    run_root = tmp_path / "run"
    out_dir = run_root / "previews" / "draft"
    result = render_draft(
        _deck_with("unsupported", "supported"), out_dir=out_dir, tokens=tokens_for()
    )

    assert result.pptx == out_dir.resolve() / "draft.pptx" and result.pptx.exists()
    assert result.flags == {"s1": "blocking", "s2": ""}
    assert not (run_root / "deck.pptx").exists()
    assert {p.name for p in run_root.rglob("*.pptx")} == {"draft.pptx"}


def test_a_run_root_is_refused_as_out_dir(tmp_path: Path, stub_build: None) -> None:
    (tmp_path / "state.json").write_text("{}")
    with pytest.raises(ValueError, match="run root"):
        render_draft(_deck_with("supported"), out_dir=tmp_path, tokens=tokens_for())
    assert not (tmp_path / "draft.pptx").exists()


def test_every_slide_carries_the_draft_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_build: None
) -> None:
    monkeypatch.setattr(
        draft, "render_pptx", lambda *a, **k: (_ for _ in ()).throw(RenderError("x"))
    )
    result = render_draft(
        _deck_with("supported", "supported", "supported"),
        out_dir=tmp_path / "d",
        tokens=tokens_for(),
    )
    slides = list(Presentation(str(result.pptx)).slides)
    assert len(slides) == 3
    for slide in slides:
        markers = [s for s in slide.shapes if s.name == DRAFT_MARKER_NAME]
        assert len(markers) == 1 and markers[0].text_frame.text == DRAFT_MARKER_TEXT


def test_missing_libreoffice_still_writes_the_pptx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_build: None
) -> None:
    monkeypatch.setattr("autodeck.render.qa.libreoffice.shutil.which", lambda _name: None)
    result = render_draft(_deck_with("supported"), out_dir=tmp_path / "d", tokens=tokens_for())
    assert result.rendered is False and result.images == []
    assert result.pptx.exists() and "LibreOffice" in result.note


def test_stale_pngs_are_cleared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_build: None
) -> None:
    out_dir = tmp_path / "d"
    out_dir.mkdir()
    (out_dir / "draft-9.png").write_bytes(b"old")
    (out_dir / "keep.txt").write_text("x")
    monkeypatch.setattr(
        draft, "render_pptx", lambda *a, **k: (_ for _ in ()).throw(RenderError("x"))
    )
    render_draft(_deck_with("supported"), out_dir=out_dir, tokens=tokens_for())
    assert not (out_dir / "draft-9.png").exists() and (out_dir / "keep.txt").exists()


def test_preview_command_records_a_stage_and_approves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_build: None
) -> None:
    runs_root = _validated_run(tmp_path, monkeypatch, "unsupported")
    monkeypatch.setattr(
        draft, "render_pptx", lambda *a, **k: (_ for _ in ()).throw(RenderError("no lo"))
    )
    tokens = tokens_for()
    monkeypatch.setattr("autodeck.cli.DesignTokens.load", lambda _p: tokens)

    before = dict(Orchestrator("r1", runs_root=runs_root).state.approvals)
    result = CliRunner().invoke(app, ["preview", "r1", "--runs-root", str(runs_root)])

    assert result.exit_code == 0, result.output
    orch = Orchestrator("r1", runs_root=runs_root)
    assert orch.state.is_complete("preview")
    assert (orch.paths.previews / "draft" / "draft.pptx").exists()
    assert not orch.paths.deck_pptx.exists()
    assert orch.state.approvals == before
    assert "blocking" in result.output


@pytest.mark.render
@pytest.mark.skipif(not is_available("Liberation Sans"), reason="needs Liberation Sans")
def test_real_draft_render(tmp_path: Path) -> None:
    result = render_draft(
        _deck_with("unsupported"), out_dir=tmp_path / "d", tokens=tokens_for()
    )
    assert result.pptx.exists()
    if result.rendered:
        assert len(result.images) == 1
