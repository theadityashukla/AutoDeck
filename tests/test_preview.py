"""The golden-preview loop (task 3a.4): `EXAMPLES` coverage and the real render.

Two different things are tested here, and it is worth being clear which is which:

- **`EXAMPLES` coverage** — fast, no font or LibreOffice needed. This is the guard that
  catches "registered a component, forgot to give it example content" the moment it
  happens, rather than three layers away when someone runs the loop and gets a `KeyError`.
- **The real render** — needs headless LibreOffice and an installed font, so it carries the
  `render` marker per B10 and runs locally (this container has both; see B11 / the fonts
  install script).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autodeck.design.components import catalog, preview
from autodeck.design.fonts import is_available
from autodeck.design.theme.tokens import DesignTokens

TOKENS_DIR = Path(__file__).resolve().parents[1] / "config" / "tokens"
DEV_TOKENS = TOKENS_DIR / "dev.json"

requires_test_font = pytest.mark.skipif(not is_available("Inter"), reason="Inter not installed")


# ---------------------------------------------------------------------------
# EXAMPLES coverage — no font, no LibreOffice, always runs
# ---------------------------------------------------------------------------


def test_every_registered_component_has_example_content() -> None:
    """The invariant `render_previews` relies on: a name missing here fails loudly there,
    but it should never get the chance to — this test catches it first."""
    assert set(preview.EXAMPLES) == set(catalog.known_components())


def test_each_example_is_an_instance_of_its_own_content_type() -> None:
    for name, content in preview.EXAMPLES.items():
        expected = catalog.registration(name).content_type
        assert isinstance(content, expected), (
            f"EXAMPLES[{name!r}] is a {type(content).__name__}, not {expected.__name__}"
        )


def _blocks_for(name: str, content: Any) -> dict[str, str | list[str]]:
    """Flatten one example's dataclass into the slot-name -> value mapping `check_overflow`
    expects. `two_column_compare` needs its own case: its real content model nests a
    `ComparisonColumn` per side, and the slot names (`left_title`, `left_points`, ...) live
    one level below the dataclass's own fields, not on it directly."""
    if name == "two_column_compare":
        return {
            "headline": content.headline,  # type: ignore[attr-defined]
            "left_title": content.left.title,  # type: ignore[attr-defined]
            "right_title": content.right.title,  # type: ignore[attr-defined]
            "left_points": content.left.points,  # type: ignore[attr-defined]
            "right_points": content.right.points,  # type: ignore[attr-defined]
            "source": content.source,  # type: ignore[attr-defined]
        }
    from dataclasses import asdict

    return {k: v for k, v in asdict(content).items() if isinstance(v, str | list)}


@requires_test_font
def test_every_example_passes_its_own_components_overflow_check() -> None:
    """A preview gallery whose own example content overflows would be self-defeating — the
    golden PNG is supposed to demonstrate the component fitting, not the opposite."""
    tokens = DesignTokens.load(DEV_TOKENS)
    for name, content in preview.EXAMPLES.items():
        findings = catalog.check_overflow(_blocks_for(name, content), name, tokens)
        assert findings == [], f"{name}: {findings}"


# ---------------------------------------------------------------------------
# The real render
# ---------------------------------------------------------------------------


@pytest.mark.render
def test_render_previews_writes_a_png_named_after_the_component(tmp_path: Path) -> None:
    tokens = DesignTokens.load(DEV_TOKENS)
    name = catalog.known_components()[0]
    results = preview.render_previews(tokens, only=(name,), out_dir=tmp_path)

    assert len(results) == 1
    result = results[0]
    assert result.name == name
    assert result.png == tmp_path / f"{name}.png"
    assert result.png.exists()
    assert result.png.stat().st_size > 0
    # No scratch pptx left behind alongside the committed artifact.
    assert not any(tmp_path.glob("*.pptx"))


@pytest.mark.render
def test_render_previews_regenerates_every_registered_component_by_default(
    tmp_path: Path,
) -> None:
    tokens = DesignTokens.load(DEV_TOKENS)
    results = preview.render_previews(tokens, out_dir=tmp_path)
    assert {r.name for r in results} == set(catalog.known_components())
    for result in results:
        assert result.png.exists()


@pytest.mark.render
def test_an_unknown_component_in_only_is_refused(tmp_path: Path) -> None:
    tokens = DesignTokens.load(DEV_TOKENS)
    with pytest.raises(catalog.UnknownComponentError):
        preview.render_previews(tokens, only=("not_a_real_component",), out_dir=tmp_path)


@pytest.mark.render
def test_write_provenance_records_the_rendered_family(tmp_path: Path) -> None:
    tokens = DesignTokens.load(DEV_TOKENS)
    name = catalog.known_components()[0]
    results = preview.render_previews(tokens, only=(name,), out_dir=tmp_path)
    path = preview.write_provenance(results, tmp_path / "provenance.json")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["components"][name]["font_major"] == tokens.typography.major
    assert payload["components"][name]["font_minor"] == tokens.typography.minor


@pytest.mark.render
def test_write_provenance_merges_rather_than_overwrites(tmp_path: Path) -> None:
    """A `--only` run must not erase the rest of the gallery's recorded provenance."""
    tokens = DesignTokens.load(DEV_TOKENS)
    path = tmp_path / "provenance.json"
    first_name, second_name, *_ = catalog.known_components()

    first = preview.render_previews(tokens, only=(first_name,), out_dir=tmp_path)
    preview.write_provenance(first, path)

    second = preview.render_previews(tokens, only=(second_name,), out_dir=tmp_path)
    preview.write_provenance(second, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload["components"]) == {first_name, second_name}
