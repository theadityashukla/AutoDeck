"""Design tokens — the single source of every colour, size and space in a deck.

Renderers draw exclusively from these (§6.6). No component may hardcode a colour or a
point size, because the theme is what makes a deck feel like the client's own and a
hardcoded value is invisible until someone opens the file and sees the one shape that
did not change.

The font family is a **parameter**, not a constant. Aptos is the deliverable default
(B11), but it cannot be installed in CI or a Linux container, and rendering previews in a
silently substituted face would make the "true render" untrue — the exact failure the
Phase 0 brief flags as most likely to be skipped and most damaging to skip. Parameterising
the family lets a container render honestly in a font it actually has, while Aptos stays
the target for any visual sign-off.

Owning phase: 0 (task 0.4); productionised in Phase 3a.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

HexColor = Annotated[str, Field(pattern=r"^[0-9A-Fa-f]{6}$")]
"""Bare RRGGBB, the form OOXML uses. No leading '#'."""

EMU_PER_INCH = 914400
EMU_PER_POINT = 12700

#: 16:9 at the size PowerPoint itself defaults to.
SLIDE_WIDTH_EMU = 12192000
SLIDE_HEIGHT_EMU = 6858000


class TokenModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Palette(TokenModel):
    """The twelve OOXML theme colour slots.

    These are the slots, in PowerPoint's own vocabulary, so that the generated theme
    populates the Design → Variants colour UI natively (D1). `dk1`/`lt1` are the text and
    background pair; `accent1`-`accent6` are the swatches a user sees when they recolour a
    shape.
    """

    dk1: HexColor = "1A1A1A"
    lt1: HexColor = "FFFFFF"
    dk2: HexColor = "2F3B4C"
    lt2: HexColor = "F2F4F7"
    accent1: HexColor = "1F4E79"
    accent2: HexColor = "2E9B8F"
    accent3: HexColor = "E8A33D"
    accent4: HexColor = "C0504D"
    accent5: HexColor = "6B5B95"
    accent6: HexColor = "7F8C8D"
    hyperlink: HexColor = "1F4E79"
    followed_hyperlink: HexColor = "6B5B95"

    def as_scheme(self) -> dict[str, str]:
        """Slot name -> hex, in the order `a:clrScheme` requires."""
        return {
            "dk1": self.dk1,
            "lt1": self.lt1,
            "dk2": self.dk2,
            "lt2": self.lt2,
            "accent1": self.accent1,
            "accent2": self.accent2,
            "accent3": self.accent3,
            "accent4": self.accent4,
            "accent5": self.accent5,
            "accent6": self.accent6,
            "hlink": self.hyperlink,
            "folHlink": self.followed_hyperlink,
        }


class Typography(TokenModel):
    """Font families and the type scale, in points.

    `major` is the heading family and `minor` the body family — the same split OOXML's
    `a:fontScheme` uses, so these land directly in the theme rather than being translated.
    """

    major: str = "Aptos Display"
    minor: str = "Aptos"

    display: float = Field(default=54.0, gt=0)
    title: float = Field(default=32.0, gt=0)
    heading: float = Field(default=22.0, gt=0)
    body: float = Field(default=16.0, gt=0)
    caption: float = Field(default=12.0, gt=0)
    #: §6.9's deterministic QA refuses anything smaller; below this a deck stops being
    #: readable in a room, whatever it looks like on a laptop.
    minimum: float = Field(default=10.0, gt=0)

    line_height: float = Field(default=1.25, gt=0)

    def families(self) -> set[str]:
        return {self.major, self.minor}


class Spacing(TokenModel):
    """Layout rhythm, in points. Everything in `layout_kit` derives from these."""

    baseline: float = Field(default=6.0, gt=0)
    gutter: float = Field(default=24.0, gt=0)
    margin_x: float = Field(default=54.0, gt=0)
    margin_y: float = Field(default=42.0, gt=0)
    #: §6.9 safe area: nothing renders closer to the slide edge than this.
    safe_area: float = Field(default=24.0, gt=0)


class DesignTokens(TokenModel):
    """A complete visual identity: palette, type, spacing, corner radii.

    One `tokens.json` per client (§6.4). Phase 4's onboarding extracts these from brand
    assets; Phase 0 hand-authors two, `aptos` and an OFL set for container work.
    """

    name: str = Field(min_length=1)
    palette: Palette = Field(default_factory=Palette)
    typography: Typography = Field(default_factory=Typography)
    spacing: Spacing = Field(default_factory=Spacing)
    corner_radius: float = Field(default=0.0, ge=0)

    slide_width_emu: int = SLIDE_WIDTH_EMU
    slide_height_emu: int = SLIDE_HEIGHT_EMU

    @classmethod
    def load(cls, path: Path) -> DesignTokens:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.model_dump(mode="json"), indent=2) + "\n"
        path.write_text(payload, encoding="utf-8")
        return path

    def require_fonts(self) -> None:
        """Fail now if a declared family is missing a face the design system draws with.

        Called before anything measures text or renders a preview. Failing at the start of
        a build is the whole value: the alternative is a deck that renders in a substituted
        face and looks *almost* right.

        Checks **regular, bold and italic** per family, not just regular. Every headline in
        the component library is bold and every pull-quote is italic, so a family shipping
        only a regular face cannot be budgeted honestly (`fonts.resolve_face` refuses to
        estimate one it cannot measure) — and finding that out here, once, beats finding it
        out from the first component that happens to use it.

        Bold-italic is deliberately *not* checked: nothing in the component library draws
        it today, and Inter Display — the dev token set's major family — ships no such
        face. Requiring it up front would fail every build in this container to guard
        against a combination no renderer asks for. The moment one does, `resolve_face`
        raises at measurement time with the face named, which is loud and specific; what it
        loses is only the up-front timing, and adding the fourth face here is a one-word
        change if a component ever needs it.

        Raises:
            FontNotFoundError: a declared family is not installed, or is missing its bold
                or italic face.
        """
        from autodeck.design.fonts import resolve_face

        for family in sorted(self.typography.families()):
            for bold, italic in ((False, False), (True, False), (False, True)):
                resolve_face(family, bold=bold, italic=italic)


def points_to_emu(points: float) -> int:
    return round(points * EMU_PER_POINT)


def emu_to_points(emu: int) -> float:
    return emu / EMU_PER_POINT
