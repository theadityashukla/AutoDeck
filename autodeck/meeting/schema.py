"""The transcript, as data.

The audio is identified by file *name* and sha256 only: a full path can carry a client's
name into logs and run folders, and the hash is what actually pins which recording a
transcript came from. Models are recorded so a transcript can be reproduced or questioned.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: float
    end: float
    text: str
    speaker: str | None = None


class AudioInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    sha256: str
    duration_s: float


class TranscriptModels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asr: str
    vad: str
    diarization: str | None
    sherpa_onnx: str


class Transcript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio: AudioInfo
    models: TranscriptModels
    segments: list[Segment]
    speakers_labelled: bool
    timings: dict[str, float]

    def to_text(self) -> str:
        """`[mm:ss] S1: text` per segment; `[hh:mm:ss]` once the recording passes an hour."""
        long = self.audio.duration_s >= 3600 or any(s.start >= 3600 for s in self.segments)
        lines = []
        for seg in self.segments:
            stamp = _stamp(seg.start, long)
            who = f"{seg.speaker}: " if seg.speaker else ""
            lines.append(f"[{stamp}] {who}{seg.text}")
        return "\n".join(lines) + ("\n" if lines else "")

    def save(self, directory: Path) -> tuple[Path, Path]:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / "transcript.json"
        text_path = directory / "transcript.txt"
        json_path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        text_path.write_text(self.to_text(), encoding="utf-8")
        return json_path, text_path

    @classmethod
    def load(cls, path: Path) -> Transcript:
        path = Path(path)
        if path.is_dir():
            path = path / "transcript.json"
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _stamp(seconds: float, long: bool) -> str:
    total = int(max(seconds, 0))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if long:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours * 60 + minutes:02d}:{secs:02d}"
