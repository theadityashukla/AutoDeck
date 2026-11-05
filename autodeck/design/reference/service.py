"""Ingest a client's reference decks: read, derive, write profiles, aggregate, gaps (4.2, 4.8).

Every read and write goes through `ReferenceStore` (the client's `ClientNamespace` guard).
Writes land only in the client's `decks/` folder.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autodeck.design.reference.gaps import analyse_gaps
from autodeck.design.reference.profiles import (
    DeckProfile,
    aggregate_profiles,
    derive_profiles,
)
from autodeck.ingest.deck_ingest import ReferenceStore, deck_slug
from autodeck.knowledge.context_assembler import ClientNamespace


@dataclass(frozen=True)
class IngestResult:
    decks: list[DeckProfile]
    aggregate: dict[str, Any]
    gaps: dict[str, Any]
    written: list[Path]


def load_deck_profiles(store: ReferenceStore) -> list[DeckProfile]:
    """The saved per-deck profiles whose `.pptx` is still in `decks/`."""
    present = {deck_slug(p.name) for p in store.deck_paths()}
    profiles: list[DeckProfile] = []
    for path in (
        sorted(store.decks_dir.glob("*.profile.json")) if store.decks_dir.is_dir() else []
    ):
        profile = DeckProfile.model_validate(store.read_json(path))
        if profile.slug in present:
            profiles.append(profile)
    return profiles


def ingest_client_decks(
    namespace: ClientNamespace, decks: Sequence[str | Path] | None = None
) -> IngestResult:
    """Derive and store profiles for `decks` (default: every `.pptx` in the client's
    `decks/`), then rebuild the aggregate and the gap list over all the client's decks.

    Raises:
        ClientIsolationError: a deck belongs to another client.
        ReferenceDeckError: a deck is outside `decks/`, missing, or unreadable.
    """
    store = ReferenceStore(namespace)
    paths = [store.resolve_deck(d) for d in decks] if decks else store.deck_paths()
    written: list[Path] = []
    for path in paths:
        slug = deck_slug(path.name)
        profile = derive_profiles(store.read_deck(path), slug=slug)
        written.append(
            store.write_json(store.profile_path(slug), profile.model_dump(mode="json"))
        )
    profiles = load_deck_profiles(store)
    aggregate = aggregate_profiles(namespace.client, profiles)
    gaps = analyse_gaps(profiles)
    written.append(store.write_json(store.aggregate_path, aggregate))
    written.append(store.write_json(store.gaps_path, gaps))
    return IngestResult(decks=profiles, aggregate=aggregate, gaps=gaps, written=written)
