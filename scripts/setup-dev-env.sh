#!/usr/bin/env bash
# Install the three environment dependencies a fresh container lacks (B34).
#
# Fresh containers lacked the Inter fonts, `libreoffice-impress` and `poppler-utils`.
# Without the fonts, budgets are refused (B11). Without the other two, 32 render tests —
# every prediction-vs-render check — fail. CI deselects render tests (B10), so CI stayed
# green while those checks could not run at all: a green local suite is meaningful only
# after this script has run.
#
# This script installs all three and does not stop at "apt-get exit 0" — it proves the
# render path actually works, end to end, by building a one-slide PPTX, converting it to
# PDF with LibreOffice, and rasterising it with poppler. See DECISIONS.md B34.
#
# Idempotent: on a machine that already has everything, the apt-get step is skipped and
# only the proof runs.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "== 1/3: libreoffice-impress + poppler-utils =="

can_convert_pptx() {
  command -v soffice >/dev/null 2>&1 && command -v pdftoppm >/dev/null 2>&1
}

if command -v apt-get >/dev/null 2>&1 && ! can_convert_pptx; then
  SUDO=""
  if [[ "$(id -u)" -ne 0 ]]; then
    SUDO="sudo"
  fi
  ${SUDO} apt-get update
  ${SUDO} apt-get install -y --no-install-recommends libreoffice-impress poppler-utils
else
  echo "  already present (or no apt-get) — nothing to install"
fi

if ! command -v soffice >/dev/null 2>&1; then
  echo "ERROR: soffice is still not on PATH after the install step." >&2
  exit 1
fi
if ! command -v pdftoppm >/dev/null 2>&1; then
  echo "ERROR: pdftoppm is still not on PATH after the install step." >&2
  exit 1
fi

echo "== 2/3: Inter dev fonts =="
"${REPO_ROOT}/scripts/install-dev-fonts.sh"

echo "== 3/3: prove the render path end to end =="

PPTX_PATH="${WORK}/probe.pptx"
PDF_PATH="${WORK}/probe.pdf"

uv run python - "${PPTX_PATH}" <<'PYEOF'
import sys

from pptx import Presentation
from pptx.util import Inches

path = sys.argv[1]
prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[0])
slide.shapes.title.text = "setup-dev-env.sh probe"
box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1))
box.text_frame.text = "rendered by scripts/setup-dev-env.sh"
prs.save(path)
PYEOF

if [[ ! -s "${PPTX_PATH}" ]]; then
  echo "ERROR: building the probe PPTX produced no output." >&2
  exit 1
fi

soffice --headless --convert-to pdf --outdir "${WORK}" "${PPTX_PATH}" >/dev/null

if [[ ! -s "${PDF_PATH}" ]]; then
  echo "ERROR: soffice --headless --convert-to pdf produced no output." >&2
  exit 1
fi

pdftoppm -png -r 72 "${PDF_PATH}" "${WORK}/probe" >/dev/null

if ! compgen -G "${WORK}/probe-*.png" > /dev/null; then
  echo "ERROR: pdftoppm produced no output." >&2
  exit 1
fi

echo
echo "Verified:"
echo "  - libreoffice-impress (soffice) and poppler-utils (pdftoppm) are on PATH"
echo "  - the Inter dev font set is installed (fonts/ and ~/.local/share/fonts/)"
echo "  - a one-slide PPTX was built, converted to PDF, and rasterised to PNG end to end"
