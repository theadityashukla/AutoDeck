"""Palette presets: colour schemes for a deck that has no client master (B69).

A client deck takes its palette from the client's tokens, always. A deck with no client
master (a dev run, a personal deck) can pick one of the presets in `config/palettes/`
instead of the default. A preset replaces only the palette: fonts, type scale and spacing
stay those of the tokens it is applied to, so a preset can never take a deck off a font
the build can measure.

Each preset maps onto the twelve OOXML slots the renderers already use: `dk1` is the text
colour and `lt1` the background (a dark preset swaps their lightness, not their roles),
`accent1` is the focal colour ("look here"), `accent2` to `accent4` are support colours,
`accent5` is the alert colour and `accent6` the neutral for non-focal marks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import Field

from autodeck.design.theme.tokens import DesignTokens, Palette, TokenModel

PALETTES_DIR = Path("config/palettes")


class PalettePreset(TokenModel):
    """One preset file."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    dark: bool = False
    palette: Palette


class UnknownPaletteError(KeyError):
    """No preset by that name."""


@dataclass(frozen=True)
class PaletteChoice:
    name: str
    description: str
    dark: bool


def available_palettes(palettes_dir: Path = PALETTES_DIR) -> list[PaletteChoice]:
    """Every preset, sorted by name, without loading its colours into a deck."""
    out = []
    for path in sorted(Path(palettes_dir).glob("*.json")):
        preset = PalettePreset.model_validate_json(path.read_text(encoding="utf-8"))
        out.append(PaletteChoice(preset.name, preset.description, preset.dark))
    return out


def load_palette(name: str, palettes_dir: Path = PALETTES_DIR) -> PalettePreset:
    path = Path(palettes_dir) / f"{name}.json"
    if not path.exists():
        names = ", ".join(c.name for c in available_palettes(palettes_dir))
        raise UnknownPaletteError(f"no palette preset {name!r}; available: {names}")
    preset = PalettePreset.model_validate_json(path.read_text(encoding="utf-8"))
    if preset.name != name:
        raise UnknownPaletteError(f"{path} names itself {preset.name!r}, not {name!r}")
    return preset


def with_palette(tokens: DesignTokens, name: str, palettes_dir: Path = PALETTES_DIR) -> DesignTokens:
    """`tokens` with the preset's palette; everything else unchanged."""
    preset = load_palette(name, palettes_dir)
    return tokens.model_copy(update={"name": f"{tokens.name} · {preset.name}", "palette": preset.palette})


__all__ = [
    "PALETTES_DIR",
    "PaletteChoice",
    "PalettePreset",
    "UnknownPaletteError",
    "available_palettes",
    "load_palette",
    "with_palette",
]
