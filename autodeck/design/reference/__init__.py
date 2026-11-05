"""Reference-deck profiles and catalog gap analysis (Phase 4, tasks 4.2 and 4.8).

Style and structure derived from a client's past decks. Nothing here produces a `Document`
or anything a citation can resolve against (A1) — see `autodeck.ingest.deck_ingest`.
"""

from __future__ import annotations

from autodeck.design.reference.gaps import analyse_gaps
from autodeck.design.reference.profiles import (
    DeckProfile,
    aggregate_profiles,
    derive_profiles,
)
from autodeck.design.reference.service import ingest_client_decks

__all__ = [
    "DeckProfile",
    "aggregate_profiles",
    "analyse_gaps",
    "derive_profiles",
    "ingest_client_decks",
]
