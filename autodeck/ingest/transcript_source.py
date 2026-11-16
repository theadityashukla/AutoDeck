"""What was said in a meeting, as a source document (B78, plan step 9).

A transcribed meeting (`autodeck meeting transcribe`) enters the same `Document` model a PDF,
a client deck or the person's own conversation uses, so the A1 resolver, the validator and the
audit report need no new path. A citation into it is recognised by its `transcript--` doc id
(`Citation.source_class == "transcript"`) and the audit labels it "from the meeting". It
proves the deck is faithful to *what was said*, not that it is true.

Layout: page N is the Nth non-empty transcript segment (a "turn", 1-based); each page holds
exactly one citable `text` element `t{N}-e1` whose box is the whole page (speech has no
geometry). Segments are whatever the voice-activity detector cut, so one turn is a stretch of
speech, not necessarily a sentence.

**Nothing but the words enters the Document** (A6): no start or end time, no speaker label,
no audio name or hash. The same words therefore always give a byte-identical Document, and a
re-transcription that moves a timestamp does not change a quote hash. Speaker labels are not
prefixed into the text either: diarisation is unreliable (B78), and a label inside the quoted
text would be quoted back as if it were speech. Times and labels live in the sidecar
`runs/<run>/meeting/segments.json`, keyed by the same page numbers, which the audit report
reads to say "from the meeting, 12:04".

A4: the document is built from, and written into, one run's own folder
(`runs/<run>/source/`); nothing here reads another run or the project corpus. Importing this
module needs no speech toolkit (`autodeck.meeting.schema` is plain pydantic).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from autodeck.ingest.document_store import Document, DocumentElement, DocumentStore, IngestError
from autodeck.ir.models import TRANSCRIPT_DOC_PREFIX, BBox
from autodeck.meeting.schema import Transcript

#: A turn has no geometry; every element's box is this 16:9 "page".
PAGE_BOX: BBox = (0.0, 0.0, 960.0, 540.0)

TITLE = "What was said in the meeting"

TRANSCRIPT_FILE = "transcript.json"
SEGMENTS_FILE = "segments.json"
MEETING_SETTINGS_FILE = "meeting/settings.json"


def transcript_doc_id(run_id: str) -> str:
    """`transcript--<slug>` for a run id."""
    slug = re.sub(r"[^a-z0-9]+", "-", run_id.casefold()).strip("-")
    if not slug:
        raise IngestError(f"cannot derive a transcript id from run id {run_id!r}")
    return f"{TRANSCRIPT_DOC_PREFIX}{slug}"


def _kept(transcript: Transcript) -> list:
    """The segments that carry words, in order. Page N is the Nth of these."""
    return [seg for seg in transcript.segments if seg.text.strip()]


def transcript_document(transcript: Transcript, run_id: str) -> Document:
    """The transcript as a `Document` (no disk writes). Page N is the Nth non-empty segment."""
    doc_id = transcript_doc_id(run_id)
    elements: list[DocumentElement] = []
    for page, segment in enumerate(_kept(transcript), start=1):
        elements.append(
            DocumentElement(
                element_id=f"t{page}-e1",
                doc_id=doc_id,
                kind="text",
                page=page,
                bbox=PAGE_BOX,
                reading_order=len(elements),
                text=" ".join(segment.text.split()),
            )
        )
    return Document(
        doc_id=doc_id,
        source_path="meeting",
        title=TITLE,
        page_count=len(elements),
        elements=elements,
    )


def segments_sidecar(transcript: Transcript, run_id: str) -> dict[str, Any]:
    """`{doc_id, pages: {"N": {start, end, speaker}}}`, keyed like the Document's pages."""
    pages = {
        str(page): {"start": seg.start, "end": seg.end, "speaker": seg.speaker}
        for page, seg in enumerate(_kept(transcript), start=1)
    }
    return {"doc_id": transcript_doc_id(run_id), "pages": pages}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def ingest_transcript(run_root: Path, run_id: str) -> str | None:
    """Write the run's transcript into `runs/<run>/source/` (and the times sidecar); its doc
    id, or `None` when nothing in it is citable.

    Raises:
        IngestError: there is no readable `meeting/transcript.json`. The message never
            carries transcript text.
    """
    run_root = Path(run_root)
    path = run_root / "meeting" / TRANSCRIPT_FILE
    try:
        transcript = Transcript.load(path)
    except FileNotFoundError:
        raise IngestError(
            f"no transcript at {path}; run `autodeck meeting transcribe`."
        ) from None
    except (OSError, ValueError) as exc:
        raise IngestError(
            f"the transcript at {path} cannot be read ({type(exc).__name__})."
        ) from None
    document = transcript_document(transcript, run_id)
    if not document.elements:
        return None
    DocumentStore(run_root / "source").add(document)
    _write_json(run_root / "meeting" / SEGMENTS_FILE, segments_sidecar(transcript, run_id))
    return document.doc_id


def meeting_times(run_root: Path) -> dict[str, dict[int, float]]:
    """`{transcript doc id: {page: start seconds}}` from the sidecar; `{}` when absent."""
    path = Path(run_root) / "meeting" / SEGMENTS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        doc_id = str(data["doc_id"])
        pages = {int(page): float(item["start"]) for page, item in data["pages"].items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
    return {doc_id: pages}


# -- the meeting run's settings ---------------------------------------------------------


class MeetingSettingsError(RuntimeError):
    pass


def settings_path(run_root: Path) -> Path:
    return Path(run_root) / MEETING_SETTINGS_FILE


def normalise(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validated settings; raises `MeetingSettingsError` on a value that is not allowed.

    `check_papers` defaults to off (B49): a meeting run is checked against the meeting only
    unless the person turns the paper check on."""
    doc_id = str(raw.get("doc_id", "")).strip()
    if not doc_id.startswith(TRANSCRIPT_DOC_PREFIX):
        raise MeetingSettingsError(
            f"meeting settings need a doc_id starting with {TRANSCRIPT_DOC_PREFIX!r}; run "
            "`autodeck meeting source <run>` to make the transcript the run's source."
        )
    num = raw.get("num_speakers")
    if num is not None and (isinstance(num, bool) or not isinstance(num, int)):
        raise MeetingSettingsError("num_speakers must be a whole number or null.")
    return {
        "audio_name": str(raw.get("audio_name", "")),
        "audio_sha256": str(raw.get("audio_sha256", "")),
        "speakers": bool(raw.get("speakers", False)),
        "num_speakers": num,
        "client": str(raw.get("client", "")),
        "project": str(raw.get("project", "")),
        "doc_id": doc_id,
        "check_papers": bool(raw.get("check_papers", False)),
    }


def save_meeting_settings(run_root: Path, settings: Mapping[str, Any]) -> Path:
    path = settings_path(run_root)
    _write_json(path, normalise(settings))
    return path


def load_meeting_settings(run_root: Path) -> dict[str, Any] | None:
    """The settings, or None when this is not a meeting run."""
    path = settings_path(run_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return normalise(data)
    except (OSError, ValueError, MeetingSettingsError) as exc:
        raise MeetingSettingsError(f"{path} cannot be read: {exc}") from exc
