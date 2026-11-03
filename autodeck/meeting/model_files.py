"""The speech models: where they live, how they are fetched, how they are verified.

The weights are not in the repo (hundreds of MB) and are not downloaded implicitly: the
owner runs `autodeck meeting models --download` once. Each file's sha256 is pinned here so
a truncated download or a swapped upstream asset is refused rather than silently used — an
unverified model would make every later transcript unreproducible. If GitHub is blocked on
the network, the files can be copied in by hand to the paths `status()` reports.
"""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from autodeck.meeting.errors import MeetingError

_REL = "https://github.com/k2-fsa/sherpa-onnx/releases/download"

ASR_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")


@dataclass(frozen=True)
class ModelFile:
    key: str
    url: str
    sha256: str
    archive: bool
    #: Path of the usable artefact under `<models_dir>/<key>/` (a directory for `asr`).
    path_in_dir: str
    approx_mb: int
    #: Files that must exist (relative to `path_in_dir` when it is a directory).
    required: tuple[str, ...] = field(default=())

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]


MODELS: dict[str, ModelFile] = {
    "asr": ModelFile(
        key="asr",
        url=f"{_REL}/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2",
        sha256="157c157bc51155e03e37d2466522a3a737dd9c72bb25f36eb18912964161e1ad",
        archive=True,
        path_in_dir="sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
        approx_mb=430,
        required=ASR_FILES,
    ),
    "vad": ModelFile(
        key="vad",
        url=f"{_REL}/asr-models/silero_vad.onnx",
        sha256="9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6",
        archive=False,
        path_in_dir="silero_vad.onnx",
        approx_mb=1,
    ),
    "diar_seg": ModelFile(
        key="diar_seg",
        url=f"{_REL}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
        sha256="24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488",
        archive=True,
        path_in_dir="sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx",
        approx_mb=7,
    ),
    "diar_emb": ModelFile(
        key="diar_emb",
        # The release tag is misspelled upstream ("recongition"); it is the real URL.
        url=f"{_REL}/speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx",
        sha256="e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012",
        archive=False,
        path_in_dir="wespeaker_en_voxceleb_resnet34_LM.onnx",
        approx_mb=26,
    ),
}


def _settings_file() -> Path:
    return Path.home() / ".autodeck" / "settings.json"


def models_dir() -> Path:
    """settings.json `models_dir`, else `$AUTODECK_MODELS_DIR`, else `~/.autodeck/models`."""
    try:
        saved = json.loads(_settings_file().read_text(encoding="utf-8"))
        value = saved.get("models_dir") if isinstance(saved, dict) else None
    except (OSError, ValueError):
        value = None
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    env = os.environ.get("AUTODECK_MODELS_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".autodeck" / "models"


def _target(model: ModelFile) -> Path:
    return models_dir() / model.key / model.path_in_dir


def _present(model: ModelFile) -> bool:
    target = _target(model)
    if model.required:
        return all((target / name).is_file() for name in model.required)
    return target.is_file()


def status() -> list[tuple[str, bool, Path]]:
    return [(key, _present(model), _target(model)) for key, model in MODELS.items()]


def paths() -> dict[str, Path]:
    return {key: _target(model) for key, model in MODELS.items()}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(model: ModelFile, dest: Path, progress: Callable[[str], None] | None) -> None:
    last = -1
    with httpx.stream("GET", model.url, follow_redirects=True, timeout=60.0) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        got = 0
        with dest.open("wb") as handle:
            for chunk in response.iter_bytes(1 << 20):
                handle.write(chunk)
                got += len(chunk)
                if progress is not None and total:
                    pct = got * 100 // total // 5 * 5
                    if pct != last:
                        last = pct
                        progress(f"downloading {model.key} {pct}%")


def ensure(
    keys: list[str] | tuple[str, ...], *, progress: Callable[[str], None] | None = None
) -> None:
    """Make every model in `keys` present and verified; never re-downloads a present one."""
    for key in keys:
        model = MODELS.get(key)
        if model is None:
            raise MeetingError(f"unknown model key {key!r}")
        if _present(model):
            continue
        folder = models_dir() / model.key
        folder.mkdir(parents=True, exist_ok=True)
        part = folder / (model.filename + ".part")
        try:
            try:
                _download(model, part, progress)
            except httpx.HTTPError as exc:
                raise MeetingError(
                    f"could not download {model.key} ({type(exc).__name__}). If GitHub is "
                    f"blocked, copy the files in manually to {_target(model)}"
                ) from None
            actual = _sha256(part)
            if actual != model.sha256:
                raise MeetingError(
                    f"{model.key}: checksum mismatch (expected {model.sha256[:12]}…, got "
                    f"{actual[:12]}…). The download was deleted. If GitHub is blocked or "
                    f"serves a different file, copy the files in manually to "
                    f"{_target(model)}"
                )
            if model.archive:
                with tarfile.open(part, "r:bz2") as tar:
                    tar.extractall(folder, filter="data")
            else:
                part.replace(_target(model))
        finally:
            part.unlink(missing_ok=True)
        if not _present(model):
            raise MeetingError(
                f"{model.key}: expected files are missing after install under {_target(model)}"
            )
        if progress is not None:
            progress(f"{model.key} ready")
