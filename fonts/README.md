# Fonts

Font binaries are **not committed**. `.gitignore` excludes `fonts/*.ttf` and `fonts/*.otf`.
This directory holds the setup instructions and nothing else.

## Why a missing font is an error, not a fallback

`autodeck/design/budgets.py` computes text budgets from **real glyph metrics**. If the
declared family is absent and the measurement library silently substitutes another face,
every computed budget is wrong — and wrong in the direction that produces overflow, which
is precisely the failure that stalled v1 (`legacy/v1/LEGACY.md`). Decision B11 therefore
requires a **loud error**.

`autodeck.design.fonts.resolve_family()` raises `FontNotFoundError` when a family cannot
be located. Nothing in the codebase catches it and carries on.

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

Required faces: `Aptos.ttf`, `Aptos-Bold.ttf`, `Aptos-Italic.ttf`, `Aptos-Display.ttf`.

**Headless LibreOffice needs them too.** The preview loop (D5) renders through LibreOffice,
so if Aptos is missing there, the PNGs come back in a substituted face and the design loop
is judging something that is not the deliverable. Install into `~/.local/share/fonts/` and
run `fc-cache -f` before trusting a preview.

Verify with:

```bash
uv run autodeck fonts check --family "Aptos"
```

## The container / CI situation

Neither this repository's CI (B10 — no render path) nor an ephemeral dev container can
have Aptos: it cannot be legally fetched. Work in those environments uses the OFL token set
(`tokens/dev.json`) so that previews are **true renders of a font that is genuinely
installed**, never a substituted Aptos. Preview output records which family it rendered in.

Aptos remains the deliverable default and the target for any visual sign-off.
