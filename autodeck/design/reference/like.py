"""Build a deck *like* one of the client's past decks (Phase 4, task 4.3).

`clarify --like NAME` snapshots a slice of the named deck's saved profile into
`runs/<run>/like.json`. Every later model call for that run reads the snapshot, never the
client folder again, so the run is reproducible (A6) and `run_source_hashes` covers it.

**A1:** the snapshot and its prompt text are *style and structure*: slide roles, titles as an
arc, header rules, voice measures, density. Nothing here builds a `Document`, a
`RetrievedSpan` or a `CachedClaim`, and the text is added to a prompt as its own section,
never to an evidence pack, a `DocumentStore` or a seed, so it can satisfy no citation.

**A4:** the deck is resolved through the client's `ReferenceStore`, which refuses anything
outside that client's `decks/` folder.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from autodeck.design.reference.profiles import DeckProfile
from autodeck.ingest.deck_ingest import ReferenceDeckError, ReferenceStore, deck_slug
from autodeck.knowledge.context_assembler import ClientNamespace

LIKE_FILE = "like.json"
LIKE_PROMPT = Path("prompts/reference_like.md")


class LikeError(RuntimeError):
    """The deck cannot be used as a model: unknown, not ingested, or the run has another."""


def like_path(run_root: Path) -> Path:
    return Path(run_root) / LIKE_FILE


def load_like(run_root: Path) -> dict[str, Any] | None:
    """The run's snapshot, or `None` when it was not started with `--like`."""
    path = like_path(run_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LikeError(f"{path} cannot be read: {exc}") from exc
    if not isinstance(data, dict) or "storyline" not in data:
        raise LikeError(f"{path} is not a reference snapshot")
    return data


def _resolve(store: ReferenceStore, name: str) -> Path:
    """A deck by slug, file name or path, always inside the client's `decks/` (A4)."""
    candidate = name.strip()
    if not candidate:
        raise LikeError("--like needs the name of one of the client's decks")
    if len(Path(candidate).parts) == 1 and not candidate.casefold().endswith(".pptx"):
        try:
            wanted = deck_slug(candidate)
        except ReferenceDeckError as exc:
            raise LikeError(str(exc)) from exc
        for path in store.deck_paths():
            if deck_slug(path.name) == wanted:
                return path
    return store.resolve_deck(candidate)


def snapshot_of(profile: DeckProfile) -> dict[str, Any]:
    """The subset of a deck profile a build is shown: `{deck, storyline, header, voice,
    density}`. Deterministic: the same profile gives the same bytes."""
    storyline = profile.storyline
    roles = {r.slide: r for r in storyline.roles}
    content_words = [r.words for r in storyline.roles if r.role == "content"]
    return {
        "deck": profile.slug,
        "storyline": {
            "slide_count": storyline.slide_count,
            "arc": [
                {
                    "n": n,
                    "role": roles[n].role if n in roles else "content",
                    "title": title,
                }
                for n, title in enumerate(storyline.titles, start=1)
            ],
            "sections": list(storyline.sections),
            "role_counts": dict(storyline.role_counts),
        },
        "header": dict(profile.header.profile),
        "voice": {
            "median_sentence_words": profile.voice.median_sentence_words,
            "mean_sentence_words": profile.voice.mean_sentence_words,
            "person": dict(profile.voice.person),
        },
        "density": {
            "median_words_per_content_slide": (
                statistics.median(content_words) if content_words else 0
            ),
            "mean_words_per_slide": storyline.mean_words_per_slide,
        },
    }


def build_like_snapshot(namespace: ClientNamespace, name: str) -> dict[str, Any]:
    """The snapshot for `name`, read through the client's namespace.

    Raises:
        LikeError: no such deck, or it has no ingested profile.
        ClientIsolationError, ReferenceDeckError: the name points outside the client's
            `decks/` folder (both `KnowledgeError`s; the caller reports them).
    """
    store = ReferenceStore(namespace)
    path = _resolve(store, name)
    slug = deck_slug(path.name)
    profile_file = store.profile_path(slug)
    if not profile_file.is_file():
        raise LikeError(
            f"{path.name} has no ingested profile. Run `autodeck reference ingest "
            f"--client {namespace.client}` first."
        )
    return snapshot_of(DeckProfile.model_validate(store.read_json(profile_file)))


def write_like(run_root: Path, snapshot: Mapping[str, Any]) -> Path:
    """Write the run's snapshot. Refused when the run already has a different one."""
    existing = load_like(run_root)
    if existing is not None and existing != dict(snapshot):
        raise LikeError(
            f"this run was started like {existing.get('deck')!r}; a run keeps the deck it "
            "started with. Start a new run to build like another deck."
        )
    path = like_path(run_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _arc_lines(like: Mapping[str, Any]) -> list[str]:
    return [
        f"{slide['n']}. [{slide['role']}] {slide['title'] or '(untitled)'}"
        for slide in like["storyline"]["arc"]
    ]


def like_summary(like: Mapping[str, Any]) -> str:
    """One line for the clarify call, so its questions do not re-ask the length."""
    storyline = like["storyline"]
    return (
        f"build it like {like['deck']}: {storyline['slide_count']} slides, "
        f"{len(storyline['sections'])} sections"
    )


def like_description(like: Mapping[str, Any]) -> str:
    """The deck as code measured it: arc, sections, size, density, header rules, voice."""
    storyline, header, voice = like["storyline"], like["header"], like["voice"]
    lines = [
        f"The deck to build like: {like['deck']}",
        "",
        "Arc, one line per slide (`n. [role] title`):",
        *_arc_lines(like),
        "",
        "Section breaks (slide where each section starts, and its length): "
        + (
            ", ".join(f"{s['start']} ({s['slides']} slides)" for s in storyline["sections"])
            or "none"
        ),
        f"Slide count: {storyline['slide_count']}",
        "Median words per content slide: "
        f"{like['density']['median_words_per_content_slide']:g}",
        "",
        "Header rules:",
        f"- style: {header.get('style', 'topic_led')}",
        f"- at most {header.get('max_words', 'n/a')} words",
        "- case: " + ("sentence case" if header.get("sentence_case") else "not sentence case"),
        "- numbers in headers: " + str(header.get("numbers_in_headers", "n/a")),
        "- ends with a full stop: " + ("yes" if header.get("terminal_punctuation") else "no"),
        "",
        "Voice:",
        f"- median sentence length: {voice['median_sentence_words']:g} words",
        "- person: " + ", ".join(f"{k} {v:.0%}" for k, v in sorted(voice["person"].items())),
    ]
    return "\n".join(lines)


def like_section(like: Mapping[str, Any], prompt_text: str | None = None) -> str:
    """The prompt section: `prompts/reference_like.md`, then the description.

    `prompt_text` lets a caller that already read the prompt file (and owns the error for a
    missing one) pass it in.
    """
    if prompt_text is None:
        if not LIKE_PROMPT.is_file():
            raise LikeError(f"prompt not found at {LIKE_PROMPT}")
        prompt_text = LIKE_PROMPT.read_text(encoding="utf-8")
    return prompt_text.rstrip() + "\n\n" + like_description(like)
