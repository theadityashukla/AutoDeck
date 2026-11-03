# Fonts

Font binaries are **not committed**. `.gitignore` excludes `fonts/*.ttf` and `fonts/*.otf`.
This directory holds the setup instructions and nothing else.

## Why a missing font is an error, not a fallback

`autodeck/design/budgets.py` computes text budgets from **real glyph metrics**. If the
declared family is absent and the measurement library silently substitutes another face,
every computed budget is wrong — and wrong in the direction that produces overflow, which
is precisely the failure that stalled v1 (`legacy/v1/LEGACY.md`). Decision B11 therefore
requires a **loud error**.

`autodeck.design.fonts.resolve_face()` raises `FontNotFoundError` when a face cannot be
located. Nothing in the codebase catches it and carries on.

## A family is not enough: each face must be installed

Budgets are measured per **face**, not per family, because the bold face is genuinely
wider than the regular one — measured at 32pt on the faces in this directory, +6.1% for
Inter Display and +2.8% for Inter. Every headline the component library draws is bold and
every pull-quote is italic, so:

**A declared family must supply its regular, bold and italic faces.** `resolve_face()`
refuses to fall back to regular and refuses to synthesise: a synthesised face has no file
to measure, and a budget this codebase cannot measure is one it will not issue. Until
3a.6 the resolver returned the regular file whatever was asked of it, which made every
bold budget under-predict by exactly the percentages above — in the overflow direction,
and invisibly, because every automated check compared the prediction against itself.

`DesignTokens.require_fonts()` and `autodeck fonts check` both report per face. Bold-italic
is the one combination not required up front, because nothing draws it yet and Inter
Display ships none; asking for it raises at measurement time, naming the face.

## Aptos — the deliverable default (B11)

Aptos Display (major/headings) + Aptos (minor/body) is the Office default font scheme, so
decks render as authored on essentially every corporate client machine without relying on
embedding.

**Aptos ships with Microsoft 365 and is not freely redistributable.** Copy the files from a
local Office installation into this directory, or point `AUTODECK_FONT_DIRS` at the system
font directory.

| Platform | Where Office installs Aptos |
|---|---|
| macOS | `~/Library/Fonts/`, or `/Library/Fonts/Microsoft/` |
| Windows | `C:\Windows\Fonts\`, or `%LOCALAPPDATA%\Microsoft\Windows\Fonts\` |
| Linux | not shipped — Aptos is unavailable unless copied from a licensed install |

Required faces: the regular, bold and italic of **both** declared families — so
`Aptos.ttf`, `Aptos-Bold.ttf`, `Aptos-Italic.ttf` for the minor family, and the matching
three for Aptos Display (the major family, which carries every bold headline). A regular
file alone is not enough; see the per-face section above.

**Headless LibreOffice needs them too.** The preview loop (D5) renders through LibreOffice,
so if Aptos is missing there, the PNGs come back in a substituted face and the design loop
is judging something that is not the deliverable. Install into `~/.local/share/fonts/` and
run `fc-cache -f` before trusting a preview. **On macOS** headless LibreOffice uses CoreText,
not fontconfig, so install into `~/Library/Fonts/` instead (or as well); `~/.local/share/fonts/`
is invisible to it and it will substitute silently. `render_pptx` checks both.

Verify with:

```bash
uv run autodeck fonts check --family "Aptos"
```

## The container / CI situation

Neither this repository's CI (B10 — no render path) nor an ephemeral dev container can
have Aptos: it cannot be legally fetched. Work in those environments uses the OFL token set
(`config/tokens/dev.json`) so that previews are **true renders of a font that is genuinely
installed**, never a substituted Aptos. Preview output records which family it rendered in.

**The dev token set uses Carlito, which ships with LibreOffice.** Carlito (SIL OFL 1.1,
metric-compatible with Calibri) is bundled in LibreOffice's own font directory, so headless
LibreOffice renders it with nothing installed, and `autodeck.design.fonts` finds the same
files for glyph metrics. Searched, after `AUTODECK_FONT_DIRS` and the usual system folders:

| Platform | LibreOffice bundled fonts |
|---|---|
| macOS | `/Applications/LibreOffice.app/Contents/Resources/fonts/truetype/` |
| Linux | `/usr/lib/libreoffice/share/fonts/truetype/`, `/opt/libreoffice*/share/fonts/truetype/` |

So no font install is needed for previews. Aptos remains the deliverable default and the
target for any visual sign-off.

### Inter (optional / legacy)

Earlier the dev token set used Inter / Inter Display. `./scripts/install-dev-fonts.sh`
still fetches Inter (SIL OFL 1.1) into `fonts/`, `~/.local/share/fonts/` and, on macOS,
`~/Library/Fonts/`; it is only needed for custom token sets or the Inter-based tests, which
skip when Inter is absent. The binaries stay uncommitted (`.gitignore` excludes
`fonts/*.ttf`). `./scripts/setup-dev-env.sh` still calls it as an optional step; the
LibreOffice and poppler packages it installs are what previews actually require.
