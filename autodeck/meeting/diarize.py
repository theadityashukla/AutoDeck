"""Who spoke when, and attaching that to the recognised segments.

Diarization is a separate pass over the audio (pyannote segmentation + a speaker embedding
model + clustering). The prototype showed it can fail badly — 60 clusters for 6 people with
a mismatched embedding model — and a transcript with 60 "speakers" is worse than none, so
`assign_speakers` refuses to label past a sanity cap and says why. sherpa_onnx is imported
only inside `diarize`; `assign_speakers` is pure.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from autodeck.meeting.asr import _sherpa
from autodeck.meeting.schema import Segment

if TYPE_CHECKING:
    import numpy as np

Turn = tuple[float, float, int]


def diarize(
    audio: np.ndarray,
    *,
    seg_model: Path,
    emb_model: Path,
    threads: int,
    num_speakers: int | None = None,
    threshold: float = 0.85,
) -> list[Turn]:
    sherpa = _sherpa()
    config = sherpa.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg_model)),
            num_threads=threads,
        ),
        embedding=sherpa.SpeakerEmbeddingExtractorConfig(
            model=str(emb_model), num_threads=threads
        ),
        clustering=sherpa.FastClusteringConfig(
            num_clusters=num_speakers if num_speakers else -1, threshold=threshold
        ),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    engine = sherpa.OfflineSpeakerDiarization(config)
    result = engine.process(audio).sort_by_start_time()
    return [(float(r.start), float(r.end), int(r.speaker)) for r in result]


def assign_speakers(
    segments: list[Segment], turns: Sequence[Turn], *, max_speakers: int = 12
) -> tuple[list[Segment], str | None]:
    """Label each segment with the turn it overlaps most; number speakers by first speech.

    Returns the segments and a warning when labelling was abandoned (too many clusters).
    """
    clusters = {speaker for _, _, speaker in turns}
    if len(clusters) > max_speakers:
        return [s.model_copy(update={"speaker": None}) for s in segments], (
            f"diarization found {len(clusters)} speakers (more than {max_speakers}); "
            "speaker labels left off"
        )
    raw: list[int | None] = []
    for seg in segments:
        overlap: dict[int, float] = {}
        for start, end, speaker in turns:
            shared = min(seg.end, end) - max(seg.start, start)
            if shared > 0:
                overlap[speaker] = overlap.get(speaker, 0.0) + shared
        raw.append(max(overlap, key=lambda k: overlap[k]) if overlap else None)
    names: dict[int, str] = {}
    out: list[Segment] = []
    for seg, speaker in zip(segments, raw, strict=True):
        label = None
        if speaker is not None:
            label = names.setdefault(speaker, f"S{len(names) + 1}")
        out.append(seg.model_copy(update={"speaker": label}))
    return out, None
