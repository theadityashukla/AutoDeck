"""Palette presets (B69): twenty schemes for decks with no client master, all readable."""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.design.free_layout import contrast_ratio
from autodeck.design.theme.palettes import (
    UnknownPaletteError,
    available_palettes,
    load_palette,
    with_palette,
)
from autodeck.design.theme.tokens import DesignTokens

TOKENS = DesignTokens.load(Path("config/tokens/dev.json"))
NAMES = [c.name for c in available_palettes()]


def test_there_are_twenty_presets_including_the_dark_ones() -> None:
    assert len(NAMES) == 20
    assert {"keynote", "midnight", "neon"} <= {c.name for c in available_palettes() if c.dark}


@pytest.mark.parametrize("name", NAMES)
def test_every_preset_keeps_text_and_focal_marks_readable(name: str) -> None:
    p = load_palette(name).palette
    assert contrast_ratio(p.dk1, p.lt1) >= 7.0, "body text on the background"
    assert contrast_ratio(p.dk2, p.lt1) >= 4.5, "secondary text on the background"
    assert contrast_ratio(p.dk1, p.lt2) >= 4.5, "text on a soft panel"
    assert contrast_ratio(p.accent1, p.lt1) >= 3.0, "the focal colour as a chart mark"


def test_a_preset_replaces_only_the_palette() -> None:
    themed = with_palette(TOKENS, "forest")
    assert themed.palette == load_palette("forest").palette
    assert themed.typography == TOKENS.typography and themed.spacing == TOKENS.spacing
    assert themed.name.endswith("forest")


def test_an_unknown_preset_names_the_available_ones() -> None:
    with pytest.raises(UnknownPaletteError, match="cobalt"):
        load_palette("vaporwave")
