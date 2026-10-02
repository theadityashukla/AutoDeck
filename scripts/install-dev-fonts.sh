#!/usr/bin/env bash
# Install the OFL dev font set (Inter) into fonts/ and the user font directory.
#
# `fonts/README.md` says work in a container or CI uses the OFL token set
# (`config/tokens/dev.json`) "so that previews are true renders of a font that is genuinely
# installed". Nothing installed it. In a fresh container neither Aptos *nor* Inter is
# present, so `autodeck fonts check` fails against both token sets and the D5 preview loop
# cannot run at all — which is the correct behaviour (B11: a missing font is a loud error,
# never a substitution) applied to an environment nobody had set up.
#
# Inter is SIL Open Font License 1.1, so unlike Aptos it can be fetched. It is still not
# committed: `.gitignore` excludes `fonts/*.ttf`, and that stays true.
#
# Both destinations matter and for different readers:
#   fonts/                     -> autodeck.design.fonts.resolve_family(), for glyph metrics
#   ~/.local/share/fonts/      -> fontconfig, so headless LibreOffice renders the same face
# Installing only the first gives budgets computed from Inter and previews rendered in
# whatever LibreOffice substitutes, which is the silent-mismatch failure B11 exists to stop.
#
# Aptos is unaffected: it cannot be legally fetched and remains the deliverable default.
# See fonts/README.md.

set -euo pipefail

INTER_VERSION="${INTER_VERSION:-4.1}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FONT_DIR="${REPO_ROOT}/fonts"
USER_FONT_DIR="${HOME}/.local/share/fonts"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# The faces the dev token set actually asks for: Inter (minor) and Inter Display (major),
# in the weights and styles a deck uses. Not the whole family — the release is 33 MB.
FACES=(
  Inter-Regular Inter-Bold Inter-Italic Inter-BoldItalic Inter-SemiBold
  InterDisplay-Regular InterDisplay-Bold InterDisplay-Italic InterDisplay-SemiBold
)

echo "Fetching Inter ${INTER_VERSION}..."
curl -sSLf -o "${WORK}/inter.zip" \
  "https://github.com/rsms/inter/releases/download/v${INTER_VERSION}/Inter-${INTER_VERSION}.zip"

unzip -q -o "${WORK}/inter.zip" -d "${WORK}" "extras/ttf/*" "LICENSE.txt"

mkdir -p "${FONT_DIR}" "${USER_FONT_DIR}"
for face in "${FACES[@]}"; do
  src="${WORK}/extras/ttf/${face}.ttf"
  if [[ ! -f "${src}" ]]; then
    echo "  MISSING in release: ${face}.ttf" >&2
    exit 1
  fi
  cp "${src}" "${FONT_DIR}/"
  cp "${src}" "${USER_FONT_DIR}/"
done
cp "${WORK}/LICENSE.txt" "${FONT_DIR}/Inter-LICENSE.txt"

if command -v fc-cache >/dev/null 2>&1; then
  fc-cache -f >/dev/null
else
  echo "  fc-cache not found — LibreOffice may not see the new fonts until it is run." >&2
fi

echo "Installed ${#FACES[@]} faces into fonts/ and ${USER_FONT_DIR}."
echo
uv run autodeck fonts check --tokens config/tokens/dev.json
