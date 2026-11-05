"""Catalog gap analysis (Phase 4, task 4.8).

Reference-deck layouts the component catalog cannot express. From each deck's
`DesignProfile`, take the slides whose best catalog match has confidence below
`LOW_CONFIDENCE` (0.5), cluster them by their coarse layout signature (text-box, column,
picture, chart and table counts), and rank the clusters by how many slides, then how many
decks, show them. The result is a list of candidate components, not a decision: a person
decides which gaps deserve a catalog entry.

Deterministic and text-free: a gap names a signature and slide numbers, never deck text.
"""

from __future__ import annotations

from typing import Any

from autodeck.design.reference.profiles import LOW_CONFIDENCE, DeckProfile

EXAMPLE_CAP = 5


def analyse_gaps(profiles: list[DeckProfile]) -> dict[str, Any]:
    clusters: dict[str, dict[str, Any]] = {}
    for profile in sorted(profiles, key=lambda p: p.slug):
        for slide in profile.design.slides:
            if slide.confidence >= LOW_CONFIDENCE:
                continue
            cluster = clusters.setdefault(
                slide.signature,
                {
                    "signature": slide.signature,
                    "count": 0,
                    "decks": [],
                    "examples": [],
                    "best_match": slide.component,
                    "confidence": slide.confidence,
                },
            )
            cluster["count"] += 1
            if profile.slug not in cluster["decks"]:
                cluster["decks"].append(profile.slug)
            if len(cluster["examples"]) < EXAMPLE_CAP:
                cluster["examples"].append({"deck": profile.slug, "slide": slide.slide})
            if slide.confidence > cluster["confidence"]:
                cluster["best_match"] = slide.component
                cluster["confidence"] = slide.confidence
    ranked = sorted(
        clusters.values(), key=lambda c: (-c["count"], -len(c["decks"]), c["signature"])
    )
    for rank, cluster in enumerate(ranked, start=1):
        cluster["rank"] = rank
    return {"threshold": LOW_CONFIDENCE, "gaps": ranked}
