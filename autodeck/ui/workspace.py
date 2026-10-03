"""Workspace read models: knowledge (projects/clients), provider keys.

Owns knowledge_view(roots) and keys_view(env).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from autodeck.ingest.document_store import DocumentStore
from autodeck.ui.api import Roots


def knowledge_view(roots: Roots) -> dict[str, Any]:
    """Knowledge base inventory: projects, papers, claims, clients, templates.

    Returns:
        {projects: [{name, papers: [{doc_id, file, pages, ingested}],
                    claims_md, curated_claims, ingested}],
         clients: [{name, summary, positioning, has_template, theme,
                   past_decks, engagement_notes}]}

    Raises:
        UIError: only for errors a person can act on (rare; mostly logs silently).
    """
    from autodeck.knowledge.loader import KnowledgeLoader

    loader = KnowledgeLoader(roots.knowledge)

    projects = []
    for project_name in loader.project_names():
        try:
            proj = loader.load_project(project_name)
            papers = []
            for paper_path in proj.papers:
                doc_id = paper_path.stem
                ingested = _doc_ingested(roots, project_name, doc_id)
                pages = _get_page_count(roots, project_name, doc_id) if ingested else None
                papers.append(
                    {
                        "doc_id": doc_id,
                        "file": paper_path.name,
                        "pages": pages,
                        "ingested": ingested,
                    }
                )
            curated = len(proj.claims)
            proj_ingested = bool(papers) and all(p["ingested"] for p in papers)
            projects.append(
                {
                    "name": project_name,
                    "papers": papers,
                    "claims_md": proj.root / "claims.md" in proj.root.glob("claims.md"),
                    "curated_claims": curated,
                    "ingested": proj_ingested,
                }
            )
        except Exception:
            continue

    clients = []
    for client_name in loader.client_names():
        try:
            client = loader.load_client(client_name)
            summary = _extract_summary(client.client_md, 280)
            positioning = _extract_summary(client.value_prop_md, 280)
            clients.append(
                {
                    "name": client_name,
                    "summary": summary,
                    "positioning": positioning,
                    "has_template": client.template_path is not None,
                    "theme": _theme_name(client.root),
                    "past_decks": len(client.decks),
                    "engagement_notes": len(client.engagements),
                }
            )
        except Exception:
            continue

    return {"projects": projects, "clients": clients}


def keys_view(env: str) -> dict[str, Any]:
    """Provider API keys: which are set, where they are needed.

    Returns:
        {keys: [{var, provider, set: bool, needed_by: [env]}]}

    Never returns any part of a value.
    """
    import yaml

    from autodeck.providers.registry import DEFAULT_CONFIG_PATH, PROVIDERS, api_key_env

    # Get all provider env vars
    all_keys = {}
    for provider in PROVIDERS:
        var = api_key_env(provider)
        all_keys[var] = provider

    # Determine needed_by by checking all environments in config
    needed_by_map: dict[str, set[str]] = {var: set() for var in all_keys}
    try:
        raw = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        environments = raw.get("environments") or {}
        for env_name, env_config in environments.items():
            if isinstance(env_config, dict):
                for role_config in env_config.values():
                    if isinstance(role_config, dict):
                        provider = role_config.get("provider")
                        if provider:
                            var = api_key_env(provider)
                            needed_by_map[var].add(env_name)
    except Exception:
        pass

    keys = []
    for var, provider in sorted(all_keys.items()):
        keys.append(
            {
                "var": var,
                "provider": provider,
                "set": bool(os.environ.get(var)),
                "needed_by": sorted(needed_by_map.get(var, set())),
            }
        )

    return {"keys": keys}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_summary(text: str, max_chars: int) -> str:
    """Extract first non-empty paragraph from markdown, stripped and trimmed to max_chars.

    Removes markdown heading markers (# symbols) and leading/trailing whitespace.
    """
    # The first paragraph of body text: consecutive lines up to a blank line, skipping
    # headings and blockquotes (a client file opens with a "Fictional" note in one).
    paragraph: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.startswith(("#", ">")):
            if paragraph:
                break
            continue
        paragraph.append(stripped)
    summary = " ".join(paragraph)

    # Remove any remaining markdown formatting
    summary = re.sub(r"^#+\s+", "", summary)  # Remove heading markers
    summary = summary.strip()

    # Trim to max_chars if needed
    if len(summary) > max_chars:
        summary = summary[: max_chars - 3] + "..."

    return summary


def _doc_ingested(roots: Roots, project: str, doc_id: str) -> bool:
    """Check if a document is in the document store."""
    try:
        store = DocumentStore(roots.corpus / project)
        return doc_id in store.doc_ids()
    except Exception:
        return False


def _get_page_count(roots: Roots, project: str, doc_id: str) -> int | None:
    """Get the page count from the document store, or None if not available."""
    try:
        store = DocumentStore(roots.corpus / project)
        doc = store.get(doc_id)
        return doc.page_count if doc.page_count > 0 else None
    except Exception:
        return None


def _theme_name(client_root: Path) -> str | None:
    """Get the theme name from client's theme folder, or None if absent."""
    theme_dir = client_root / "theme"
    if theme_dir.is_dir() and (
        (theme_dir / "tokens.json").exists() or (theme_dir / "template.pptx").exists()
    ):
        return "custom"
    return None
