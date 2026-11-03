#!/usr/bin/env bash
# Regenerates meeting_clip.m4a from meeting_clip.txt with macOS `say`.
# Voices: speaker A = Daniel (en_GB), speaker B = Samantha (en_US).
# Output: mono 16 kHz AAC, ~0.5 s of silence between utterances. Uses the ffmpeg bundled
# with imageio-ffmpeg (uv sync --extra meeting). No audio of a real meeting is involved.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
ffmpeg="$(cd "$repo" && uv run python -c 'import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())')"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
list="$work/list.txt"; i=0
"$ffmpeg" -v error -f lavfi -i anullsrc=r=16000:cl=mono -t 0.5 "$work/gap.wav"
while IFS= read -r line; do
  i=$((i + 1))
  case "${line%%:*}" in A) voice=Daniel ;; B) voice=Samantha ;; *) continue ;; esac
  say -v "$voice" -o "$work/u$i.aiff" "${line#*: }"
  "$ffmpeg" -v error -y -i "$work/u$i.aiff" -ac 1 -ar 16000 "$work/u$i.wav"
  printf "file '%s'\nfile '%s'\n" "$work/u$i.wav" "$work/gap.wav" >> "$list"
done < "$here/meeting_clip.txt"
"$ffmpeg" -v error -y -f concat -safe 0 -i "$list" -ac 1 -ar 16000 -c:a aac -b:a 32k "$here/meeting_clip.m4a"
