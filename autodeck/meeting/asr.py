"""Speech recognition: Silero VAD cuts speech into short segments, a transducer reads each.

Streaming the VAD keeps memory flat for a three-hour recording: audio is fed in 512-sample
windows and segments are handed on as they close, instead of buffering the whole file's
worth of results. Segments are capped at 25 s because the recogniser degrades on long
inputs. sherpa_onnx is imported lazily so the package imports (and the pure tests run)
without the optional extra.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from autodeck.meeting.audio import SAMPLE_RATE
from autodeck.meeting.errors import MeetingDepsError
from autodeck.meeting.schema import Segment

if TYPE_CHECKING:
    import numpy as np

WINDOW = 512
MIN_SILENCE_S = 0.4
MAX_SPEECH_S = 25.0
VAD_BUFFER_S = 120.0
PROGRESS_STEP = 5


class Recognizer(Protocol):
    """The slice of sherpa_onnx.OfflineRecognizer used here (a seam for fakes in tests)."""

    def create_stream(self) -> Any: ...

    def decode_stream(self, stream: Any) -> None: ...


def _sherpa() -> Any:
    try:
        import sherpa_onnx
    except ImportError:
        raise MeetingDepsError("sherpa-onnx is not installed") from None
    return sherpa_onnx


def load_recognizer(asr_dir: Path, threads: int) -> Recognizer:
    sherpa = _sherpa()
    asr_dir = Path(asr_dir)
    return sherpa.OfflineRecognizer.from_transducer(
        encoder=str(asr_dir / "encoder.int8.onnx"),
        decoder=str(asr_dir / "decoder.int8.onnx"),
        joiner=str(asr_dir / "joiner.int8.onnx"),
        tokens=str(asr_dir / "tokens.txt"),
        model_type="nemo_transducer",
        num_threads=threads,
    )


def vad_segments(audio: np.ndarray, vad_model: Path) -> Iterator[tuple[float, np.ndarray]]:
    """Yield `(start_seconds, samples)` for each stretch of speech, as it closes."""
    sherpa = _sherpa()
    config = sherpa.VadModelConfig()
    config.silero_vad.model = str(vad_model)
    config.silero_vad.min_silence_duration = MIN_SILENCE_S
    config.silero_vad.max_speech_duration = MAX_SPEECH_S
    config.silero_vad.window_size = WINDOW
    config.sample_rate = SAMPLE_RATE
    vad = sherpa.VoiceActivityDetector(config, buffer_size_in_seconds=VAD_BUFFER_S)

    def drain() -> Iterator[tuple[float, np.ndarray]]:
        while not vad.empty():
            seg = vad.front
            yield seg.start / SAMPLE_RATE, seg.samples
            vad.pop()

    total = len(audio)
    for offset in range(0, total, WINDOW):
        chunk = audio[offset : offset + WINDOW]
        if len(chunk) < WINDOW:
            break  # the tail is flushed below; a short window is not valid VAD input
        vad.accept_waveform(chunk)
        yield from drain()
    vad.flush()
    yield from drain()


def transcribe_audio(
    audio: np.ndarray,
    *,
    recognizer: Recognizer,
    vad_model: Path,
    progress: Callable[[str], None] | None = None,
) -> list[Segment]:
    """Recognise all speech in `audio`; progress lines carry percentages only."""
    total = max(len(audio), 1)
    segments: list[Segment] = []
    last_reported = 0
    for start, samples in vad_segments(audio, vad_model):
        stream = recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        recognizer.decode_stream(stream)
        text = str(stream.result.text).strip()
        if text:
            segments.append(
                Segment(start=start, end=start + len(samples) / SAMPLE_RATE, text=text)
            )
        if progress is not None:
            consumed = int((start * SAMPLE_RATE + len(samples)) * 100 / total)
            step = min(consumed, 100) // PROGRESS_STEP * PROGRESS_STEP
            if step >= last_reported + PROGRESS_STEP:
                last_reported = step
                progress(f"transcribing {step}%")
    if progress is not None and last_reported < 100:
        progress("transcribing 100%")
    return segments
