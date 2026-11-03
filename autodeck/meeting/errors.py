"""Errors for the meeting package.

Two classes so the CLI can give different exit codes: a missing optional dependency is an
environment problem the owner fixes once (exit 2); anything else is a problem with this
recording or these models (exit 1).
"""

from __future__ import annotations


class MeetingError(RuntimeError):
    """A meeting transcription step failed."""


class MeetingDepsError(MeetingError):
    """An optional dependency (sherpa-onnx, soundfile, numpy, ffmpeg) is not available."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"{detail} — install with: uv sync --extra meeting")
