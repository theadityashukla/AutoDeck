"""Decoding a recording to the 16 kHz mono float samples the models expect.

ffmpeg does the container/codec work (m4a, mp3, mov, ...). The intermediate WAV lives in a
TemporaryDirectory so it is deleted even on failure — an uncompressed copy of a client
meeting must not be left lying around. Error messages name the file, never its path.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from autodeck.meeting.errors import MeetingDepsError, MeetingError

if TYPE_CHECKING:
    import numpy as np

SAMPLE_RATE = 16000

ALLOWED_SUFFIXES = {
    ".m4a",
    ".mp3",
    ".wav",
    ".mp4",
    ".aiff",
    ".aif",
    ".flac",
    ".ogg",
    ".webm",
    ".mov",
}


def ffmpeg_exe() -> str:
    """The bundled ffmpeg (imageio-ffmpeg) if present, else one on PATH."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise MeetingDepsError("ffmpeg is not available")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode(path: Path) -> np.ndarray:
    """Float32 mono 16 kHz samples of any supported recording."""
    path = Path(path)
    try:
        import numpy as np  # noqa: F401
        import soundfile as sf
    except ImportError as exc:
        raise MeetingDepsError(f"audio decoding needs {exc.name}") from None
    if not path.is_file():
        raise MeetingError(f"audio file not found: {path.name}")
    exe = ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix="autodeck-meeting-") as tmp:
        wav = Path(tmp) / "audio.wav"
        proc = subprocess.run(
            [
                *[exe, "-nostdin", "-v", "error", "-y", "-i", str(path)],
                *["-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(wav)],
            ],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0 or not wav.is_file():
            raise MeetingError(f"ffmpeg could not decode {path.name} (exit {proc.returncode})")
        samples, rate = sf.read(str(wav), dtype="float32", always_2d=False)
    if rate != SAMPLE_RATE:
        raise MeetingError(f"unexpected sample rate {rate} decoding {path.name}")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    return samples.astype("float32", copy=False)
