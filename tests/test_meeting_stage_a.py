"""Meeting Stage A: local transcription. Unit tests run everywhere; `meeting` needs models."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from autodeck.cli import app
from autodeck.meeting import audio as audio_mod
from autodeck.meeting import model_files
from autodeck.meeting.diarize import assign_speakers
from autodeck.meeting.errors import MeetingDepsError, MeetingError
from autodeck.meeting.schema import AudioInfo, Segment, Transcript, TranscriptModels

FIXTURES = Path(__file__).parent / "fixtures"
CLIP = FIXTURES / "meeting_clip.m4a"
runner = CliRunner()


def _transcript(segments: list[Segment], duration: float = 60.0) -> Transcript:
    return Transcript(
        audio=AudioInfo(name="a.m4a", sha256="0" * 64, duration_s=duration),
        models=TranscriptModels(asr="asr", vad="vad", diarization=None, sherpa_onnx="1"),
        segments=segments,
        speakers_labelled=any(s.speaker for s in segments),
        timings={"total": 1.0},
    )


def test_roundtrip_and_text(tmp_path: Path) -> None:
    t = _transcript(
        [
            Segment(start=0, end=2, text="hello", speaker="S1"),
            Segment(start=65.4, end=70, text="hi"),
        ]
    )
    json_path, text_path = t.save(tmp_path / "out")
    assert Transcript.load(json_path) == t
    assert text_path.read_text() == "[00:00] S1: hello\n[01:05] hi\n"


def test_text_without_speakers_and_hours() -> None:
    t = _transcript([Segment(start=3725, end=3730, text="late")], duration=4000)
    assert t.to_text() == "[01:02:05] late\n"
    short = _transcript([Segment(start=5, end=6, text="x")])
    assert short.to_text() == "[00:05] x\n"


def test_schema_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        Segment.model_validate({"start": 0, "end": 1, "text": "x", "oops": 1})


def test_deps_error_message() -> None:
    assert "uv sync --extra meeting" in str(MeetingDepsError("x"))
    assert isinstance(MeetingDepsError("x"), MeetingError)


def test_assign_speakers_overlap_and_relabel() -> None:
    segs = [
        Segment(start=0, end=4, text="a"),
        Segment(start=4, end=8, text="b"),
        Segment(start=8, end=12, text="c"),
        Segment(start=40, end=41, text="d"),
    ]
    turns = [(0, 3.5, 7), (3.5, 8.5, 2), (8.5, 12, 7)]
    out, warning = assign_speakers(segs, turns)
    assert warning is None
    assert [s.speaker for s in out] == ["S1", "S2", "S1", None]


def test_assign_speakers_too_many_clusters() -> None:
    segs = [Segment(start=i, end=i + 1, text="x") for i in range(14)]
    turns = [(i, i + 1, i) for i in range(14)]
    out, warning = assign_speakers(segs, turns)
    assert warning and "14" in warning
    assert all(s.speaker is None for s in out)


def test_models_dir_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(model_files, "_settings_file", lambda: settings)
    monkeypatch.delenv("AUTODECK_MODELS_DIR", raising=False)
    assert model_files.models_dir() == Path.home() / ".autodeck" / "models"
    monkeypatch.setenv("AUTODECK_MODELS_DIR", str(tmp_path / "env"))
    assert model_files.models_dir() == tmp_path / "env"
    settings.write_text(json.dumps({"models_dir": str(tmp_path / "set")}))
    assert model_files.models_dir() == tmp_path / "set"


def _fake_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: bytes, sha: str):
    monkeypatch.setenv("AUTODECK_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setattr(model_files, "_settings_file", lambda: tmp_path / "none.json")
    fake = model_files.ModelFile(
        key="vad",
        url="https://example.invalid/silero_vad.onnx",
        sha256=sha,
        archive=False,
        path_in_dir="silero_vad.onnx",
        approx_mb=1,
    )
    monkeypatch.setitem(model_files.MODELS, "vad", fake)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=payload))

    @contextlib.contextmanager
    def stream(method, url, **kw):  # type: ignore[no-untyped-def]
        kw.pop("timeout", None)
        with httpx.Client(transport=transport) as client, client.stream(method, url, **kw) as r:
            yield r

    monkeypatch.setattr(model_files.httpx, "stream", stream)


def test_ensure_downloads_and_verifies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"tiny model"
    _fake_model(monkeypatch, tmp_path, payload, hashlib.sha256(payload).hexdigest())
    lines: list[str] = []
    model_files.ensure(["vad"], progress=lines.append)
    assert model_files.paths()["vad"].read_bytes() == payload
    assert dict((k, p) for k, p, _ in model_files.status())["vad"] is True
    model_files.ensure(["vad"])  # present: no second download (would also pass; no .part left)
    assert not list((tmp_path / "models" / "vad").glob("*.part"))


def test_ensure_refuses_checksum_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_model(monkeypatch, tmp_path, b"tampered", "0" * 64)
    with pytest.raises(MeetingError, match="checksum mismatch"):
        model_files.ensure(["vad"])
    assert not model_files.paths()["vad"].exists()
    assert not list((tmp_path / "models" / "vad").glob("*.part"))


def _knowledge(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    (root / "clients" / "acme").mkdir(parents=True)
    (root / "projects" / "proj").mkdir(parents=True)
    return root


def _args(tmp_path: Path, audio: Path, **over: str) -> list[str]:
    client = over.get("client", "acme")
    return [
        "meeting", "transcribe", "r1", "--audio", str(audio), "--client", client,
        "--project", "proj", "--knowledge-root", str(_knowledge(tmp_path)),
        "--runs-root", str(tmp_path / "runs"),
    ]  # fmt: skip


def test_cli_refuses_unknown_suffix(tmp_path: Path) -> None:
    bad = tmp_path / "notes.txt"
    bad.write_text("x")
    result = runner.invoke(app, _args(tmp_path, bad))
    assert result.exit_code == 1
    assert not (tmp_path / "runs").exists()


def test_cli_refuses_unknown_client(tmp_path: Path) -> None:
    audio = tmp_path / "m.m4a"
    audio.write_bytes(b"x")
    result = runner.invoke(app, _args(tmp_path, audio, client="nobody"))
    assert result.exit_code == 1
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "knowledge" / "clients" / "nobody").exists()


def test_cli_with_fake_recognizer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import numpy as np

    from autodeck.meeting import asr, transcribe

    audio = tmp_path / "Board call.m4a"
    audio.write_bytes(b"not really audio")
    models = tmp_path / "models"
    monkeypatch.setenv("AUTODECK_MODELS_DIR", str(models))
    monkeypatch.setattr(
        model_files, "status", lambda: [(k, True, models / k) for k in model_files.MODELS]
    )
    monkeypatch.setattr(audio_mod, "decode", lambda p: np.zeros(16000 * 10, dtype="float32"))

    class Result:
        text = "zanzibar quokka"

    class Stream:
        result = Result()

        def accept_waveform(self, rate, samples):  # type: ignore[no-untyped-def]
            pass

    class Fake:
        def create_stream(self):  # type: ignore[no-untyped-def]
            return Stream()

        def decode_stream(self, stream):  # type: ignore[no-untyped-def]
            pass

    monkeypatch.setattr(transcribe, "load_recognizer", lambda d, t: Fake())
    monkeypatch.setattr(
        asr, "vad_segments", lambda a, m: iter([(1.0, np.zeros(16000)), (5.0, np.zeros(8000))])
    )
    result = runner.invoke(app, _args(tmp_path, audio))
    assert result.exit_code == 0, result.output
    assert "zanzibar" not in result.output
    run = tmp_path / "runs" / "r1"
    meeting = run / "meeting"
    assert "zanzibar" in (meeting / "transcript.txt").read_text()
    data = json.loads((meeting / "transcript.json").read_text())
    assert data["audio"]["name"] == "Board call.m4a" and len(data["segments"]) == 2
    assert str(tmp_path) not in json.dumps(data)
    cfg = json.loads((meeting / "settings.json").read_text())
    assert cfg["client"] == "acme" and cfg["speakers"] is False
    assert cfg["audio_sha256"] == hashlib.sha256(audio.read_bytes()).hexdigest()
    assert json.loads((run / "ui.json").read_text())["project"] == "proj"
    assert not (run / "meeting" / "Board call.m4a").exists()


# ---------------------------------------------------------------------------
# Real models
# ---------------------------------------------------------------------------


def _need(keys: list[str]) -> None:
    pytest.importorskip("sherpa_onnx")
    present = {k: ok for k, ok, _ in model_files.status()}
    if not all(present.get(k) for k in keys):
        pytest.skip("speech models not installed (autodeck meeting models --download)")


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()


def _wer(ref: list[str], hyp: list[str]) -> float:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[-1] / len(ref)


@pytest.mark.meeting
def test_clip_end_to_end(tmp_path: Path) -> None:
    from autodeck.meeting.transcribe import transcribe_file

    _need(["asr", "vad"])
    result = transcribe_file(CLIP, tmp_path)
    script = " ".join(
        line.split(":", 1)[1]
        for line in (FIXTURES / "meeting_clip.txt").read_text().splitlines()
    )
    hyp = " ".join(s.text for s in result.segments)
    wer = _wer(_words(script), _words(hyp))
    print(f"WER={wer:.3f} timings={result.timings}")
    assert wer <= 0.25
    assert "first week of february" in " ".join(_words(hyp))
    assert (tmp_path / "transcript.json").is_file() and not result.speakers_labelled


@pytest.mark.meeting
def test_clip_two_speakers(tmp_path: Path) -> None:
    from autodeck.meeting.transcribe import transcribe_file

    _need(["asr", "vad", "diar_seg", "diar_emb"])
    result = transcribe_file(CLIP, tmp_path, speakers=True, num_speakers=2)
    print(f"timings={result.timings}")
    assert {s.speaker for s in result.segments if s.speaker} == {"S1", "S2"}
