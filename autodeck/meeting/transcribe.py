"""One call from a recording to a saved transcript.

Models are never fetched here: a surprise multi-hundred-MB download in the middle of a
client task is worse than a clear instruction. Timings and the real-time factor are
recorded (they are the only performance data worth keeping); transcript text is never
logged or passed to `progress`.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

from autodeck.meeting import audio as audio_mod
from autodeck.meeting import diarize as diarize_mod
from autodeck.meeting import model_files
from autodeck.meeting.asr import load_recognizer, transcribe_audio
from autodeck.meeting.errors import MeetingError
from autodeck.meeting.schema import AudioInfo, Transcript, TranscriptModels


def _sherpa_version() -> str:
    try:
        import sherpa_onnx

        return str(getattr(sherpa_onnx, "__version__", "unknown"))
    except ImportError:
        return "unavailable"


def transcribe_file(
    path: Path,
    out_dir: Path,
    *,
    speakers: bool = False,
    num_speakers: int | None = None,
    threads: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> Transcript:
    path = Path(path)
    threads = threads or min(8, os.cpu_count() or 1)
    keys = ["asr", "vad", *(["diar_seg", "diar_emb"] if speakers else [])]
    missing = [key for key, present, _ in model_files.status() if key in keys and not present]
    if missing:
        flag = " --speakers" if speakers else ""
        raise MeetingError(
            f"speech models missing ({', '.join(missing)}): run "
            f"`autodeck meeting models --download{flag}` first"
        )
    model_paths = model_files.paths()

    def say(message: str) -> None:
        if progress is not None:
            progress(message)

    t0 = time.perf_counter()
    sha = audio_mod.file_sha256(path)
    say("decoding audio")
    samples = audio_mod.decode(path)
    duration = len(samples) / audio_mod.SAMPLE_RATE
    t_decode = time.perf_counter()

    recognizer = load_recognizer(model_paths["asr"], threads)
    segments = transcribe_audio(
        samples,
        recognizer=recognizer,
        vad_model=model_paths["vad"],
        progress=progress,
    )
    t_asr = time.perf_counter()

    labelled = False
    t_diar = t_asr
    if speakers:
        say("identifying speakers")
        turns = diarize_mod.diarize(
            samples,
            seg_model=model_paths["diar_seg"],
            emb_model=model_paths["diar_emb"],
            threads=threads,
            num_speakers=num_speakers,
        )
        segments, warning = diarize_mod.assign_speakers(segments, turns)
        labelled = warning is None
        if warning:
            say(f"warning: {warning}")
        t_diar = time.perf_counter()

    total = t_diar - t0
    timings = {
        "decode": round(t_decode - t0, 2),
        "asr": round(t_asr - t_decode, 2),
        "diarize": round(t_diar - t_asr, 2),
        "total": round(total, 2),
        "rtf": round(total / duration, 3) if duration else 0.0,
    }
    transcript = Transcript(
        audio=AudioInfo(name=path.name, sha256=sha, duration_s=round(duration, 2)),
        models=TranscriptModels(
            asr=model_files.MODELS["asr"].path_in_dir,
            vad=model_files.MODELS["vad"].filename,
            diarization=(
                f"{model_files.MODELS['diar_seg'].path_in_dir} + "
                f"{model_files.MODELS['diar_emb'].filename}"
                if speakers
                else None
            ),
            sherpa_onnx=_sherpa_version(),
        ),
        segments=segments,
        speakers_labelled=labelled,
        timings=timings,
    )
    transcript.save(out_dir)
    return transcript
