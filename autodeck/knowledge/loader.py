"""Two-tier knowledge folders: project base + client overlay (D8).

Curated markdown loaded *fully* into context beats blind chunk search for stable knowledge
— that is the OKF principle behind D8, and retrieval (§6.5) is reserved for the paper
long tail. So this module's job is to find, validate and load folders, and to fail loudly
when one is malformed rather than quietly assembling a half-empty context.

"Loudly" is the operative word. A missing `client.md` that produces an empty string gives
a build with no client context that still runs to completion and produces a plausible,
generic deck. Naming the missing file in the error is the difference between a five-second
fix and an afternoon.

Owning phase: 1 (tasks 1.5 and 1.7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from autodeck.ir.models import Citation, RetrievedBy

PROJECTS_DIR = "projects"
CLIENTS_DIR = "clients"

#: Files a project folder must contain. `claims.md` is required even when empty — its
#: absence usually means someone forgot it, and an empty file says so deliberately.
REQUIRED_PROJECT_FILES = ("project.md", "claims.md")

#: Files a client folder must contain. `value_prop.md` is required because A5 types its
#: contents as `framing`; without it, positioning language has nowhere to live and tends to
#: get smuggled into claims instead.
REQUIRED_CLIENT_FILES = ("client.md", "value_prop.md")


class KnowledgeError(RuntimeError):
    """A knowledge folder is missing, malformed, or incomplete."""


class ClientIsolationError(KnowledgeError):
    """A build touched more than one client namespace (A4).

    A build error, never a warning. Plan §3 A4: client folder contents never enter prompts
    for another client's build, and the consequence of getting it wrong is a
    confidentiality breach rather than a bad slide.
    """


# ---------------------------------------------------------------------------
# Cached claims (task 1.7)
# ---------------------------------------------------------------------------


class CachedClaim(BaseModel):
    """A pre-verified claim from `claims.md`.

    **The cache is a head start, not a bypass.** A3 requires an independent verdict for
    every claim in a deck, and a claim loaded from here arrives `unverified` like any
    other. What it saves is the *retrieval* — the writer starts from a known-good citation
    instead of searching — not the validation.
    """

    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    bbox: tuple[float, float, float, float] | None = None
    tags: list[str] = Field(default_factory=list)
    note: str | None = None

    def to_citation(
        self, *, store: object = None, retrieved_by: RetrievedBy = "writer"
    ) -> Citation:
        """Resolve this cached claim's quote into a verified `Citation`.

        Always goes through the document store rather than trusting the cached page and
        bbox: `claims.md` is hand-maintained, and a corpus re-ingest can move a span. The
        store is the authority on where text actually is.

        Args:
            store: a `DocumentStore`. Required — the signature accepts `None` only so the
                dependency stays injected rather than imported at module scope.

        Raises:
            KnowledgeError: no store was supplied.
            QuoteNotFoundError: the cached quote is no longer in the document — which
                means the cache is stale and must be corrected, not worked around.
        """
        if store is None:
            raise KnowledgeError(
                "a DocumentStore is required to resolve a cached claim: the cache records "
                "what was true at curation time, and only the store knows where the text "
                "is now"
            )
        return store.resolve_quote(  # type: ignore[attr-defined]
            self.doc_id, self.quote, retrieved_by=retrieved_by
        )


_YAML_BLOCK = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.DOTALL)


def parse_claims_markdown(text: str, *, source: str = "claims.md") -> list[CachedClaim]:
    """Parse the fenced YAML blocks out of a `claims.md`.

    The format is markdown prose interleaved with ```yaml blocks — readable and reviewable
    as a document, unambiguous to parse, and it renders on GitHub. Prose outside the blocks
    is commentary for humans and is ignored.

    Raises:
        KnowledgeError: a block is not valid YAML or not a valid claim.
    """
    claims: list[CachedClaim] = []
    for index, match in enumerate(_YAML_BLOCK.finditer(text), start=1):
        try:
            payload = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            raise KnowledgeError(f"{source}: block {index} is not valid YAML: {exc}") from exc
        if payload is None:
            continue
        if not isinstance(payload, dict):
            raise KnowledgeError(
                f"{source}: block {index} must be a mapping, got {type(payload).__name__}"
            )
        try:
            claims.append(CachedClaim.model_validate(payload))
        except Exception as exc:
            raise KnowledgeError(
                f"{source}: block {index} is not a valid claim: {exc}"
            ) from exc
    return claims


# ---------------------------------------------------------------------------
# Folder models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectKnowledge:
    """One project's curated knowledge and paper corpus."""

    name: str
    root: Path
    project_md: str
    claims: list[CachedClaim]
    papers: list[Path] = field(default_factory=list)
    assets: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class ClientKnowledge:
    """One client's context, framing and brand.

    Everything here is confined to a single client namespace. `ContextAssembler` will not
    load two of these in one build (A4).
    """

    name: str
    root: Path
    client_md: str
    value_prop_md: str
    header_profile: dict[str, object] | None = None
    tokens_path: Path | None = None
    template_path: Path | None = None
    icons_dir: Path | None = None
    decks: list[Path] = field(default_factory=list)
    engagements: list[Path] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class KnowledgeLoader:
    """Finds and validates knowledge folders beneath a root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -- discovery ---------------------------------------------------------

    def project_names(self) -> list[str]:
        return _subdirectories(self.root / PROJECTS_DIR)

    def client_names(self) -> list[str]:
        return _subdirectories(self.root / CLIENTS_DIR)

    def project_root(self, name: str) -> Path:
        return self.root / PROJECTS_DIR / _safe_name(name)

    def client_root(self, name: str) -> Path:
        return self.root / CLIENTS_DIR / _safe_name(name)

    # -- loading -----------------------------------------------------------

    def load_project(self, name: str) -> ProjectKnowledge:
        """Load and validate a project folder.

        Raises:
            KnowledgeError: the folder is missing or a required file is absent.
        """
        root = self.project_root(name)
        _require_directory(root, f"project {name!r}", self.project_names())
        _require_files(root, REQUIRED_PROJECT_FILES, f"project {name!r}")

        claims_path = root / "claims.md"
        return ProjectKnowledge(
            name=name,
            root=root,
            project_md=(root / "project.md").read_text(encoding="utf-8"),
            claims=parse_claims_markdown(
                claims_path.read_text(encoding="utf-8"), source=str(claims_path)
            ),
            papers=_pdfs(root / "papers"),
            assets=_files(root / "assets"),
        )

    def load_client(self, name: str) -> ClientKnowledge:
        """Load and validate a client folder.

        Raises:
            KnowledgeError: the folder is missing or a required file is absent.
        """
        root = self.client_root(name)
        _require_directory(root, f"client {name!r}", self.client_names())
        _require_files(root, REQUIRED_CLIENT_FILES, f"client {name!r}")

        headers_path = root / "style" / "headers.yaml"
        header_profile: dict[str, object] | None = None
        if headers_path.exists():
            try:
                loaded = yaml.safe_load(headers_path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise KnowledgeError(f"{headers_path}: not valid YAML: {exc}") from exc
            if loaded is not None and not isinstance(loaded, dict):
                raise KnowledgeError(f"{headers_path}: must be a mapping")
            header_profile = loaded

        return ClientKnowledge(
            name=name,
            root=root,
            client_md=(root / "client.md").read_text(encoding="utf-8"),
            value_prop_md=(root / "value_prop.md").read_text(encoding="utf-8"),
            header_profile=header_profile,
            tokens_path=_optional(root / "theme" / "tokens.json"),
            template_path=_optional(root / "theme" / "template.pptx"),
            icons_dir=_optional(root / "theme" / "icons"),
            decks=sorted((root / "decks").glob("*.pptx")) if (root / "decks").is_dir() else [],
            engagements=sorted((root / "engagements").glob("*.md"))
            if (root / "engagements").is_dir()
            else [],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_name(name: str) -> str:
    if not name or "/" in name or name in (".", ".."):
        raise KnowledgeError(f"invalid knowledge folder name: {name!r}")
    return name


def _subdirectories(path: Path) -> list[str]:
    if not path.is_dir():
        return []
    return sorted(child.name for child in path.iterdir() if child.is_dir())


def _require_directory(path: Path, label: str, available: list[str]) -> None:
    if not path.is_dir():
        known = ", ".join(available) or "none"
        raise KnowledgeError(f"{label} not found at {path}. Available: {known}")


def _require_files(root: Path, required: tuple[str, ...], label: str) -> None:
    """Fail naming every missing file at once.

    Reporting them one per run turns folder setup into a guessing game.
    """
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise KnowledgeError(
            f"{label} is missing required file(s): {', '.join(missing)} (expected in {root}). "
            "An absent file would otherwise load as empty context and produce a plausible, "
            "generic deck."
        )


def _optional(path: Path) -> Path | None:
    return path if path.exists() else None


def _pdfs(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.pdf")) if directory.is_dir() else []


def _files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.iterdir() if p.is_file()) if directory.is_dir() else []
