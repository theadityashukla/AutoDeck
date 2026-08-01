"""Context assembly, and the enforcement point for A4 client isolation.

A4: *a build loads exactly one client namespace; any cross-client reference in context
assembly is a build **error**, not a warning.* The consequence of getting this wrong is a
confidentiality breach — one client's material in another client's deck — so this module
is written so that the safe path is the only path.

**How isolation is enforced.** A `ClientNamespace` is bound at construction and every read
goes through `ClientNamespace.read()`, which resolves the path and checks it is not under
any other client's directory. There is no second way to read a file: the assembler holds
no `open()` calls of its own. That matters because the Phase 1 brief is explicit that the
non-obvious paths must be covered too —

- **cached retrieval indices.** An index built while assembling client A can be handed to a
  client B build and leak through search results, without any file ever being opened. So an
  index carries the client it was built for, and the assembler refuses a foreign one.
- **`clients/<c>/decks/`.** Reference decks are the most likely leak in practice: they are
  read for *style*, feel like neutral design assets, and are full of another client's
  facts. They go through the same namespace guard as everything else.

**What is shared and what is not.** The project tier is deliberately shared — the whole
point of the two-tier structure (D8) is that one project's evidence serves several
clients. Only the client tier is isolated.

Owning phase: 1 (task 1.6). Opus tier — invariant-critical per the phase brief.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from autodeck.knowledge.loader import (
    CLIENTS_DIR,
    ClientIsolationError,
    ClientKnowledge,
    KnowledgeLoader,
)


@dataclass(frozen=True)
class ClientNamespace:
    """The one client a build is allowed to read from.

    Every path the assembler touches passes through `guard`. Anything under a *different*
    client's directory raises, whether it arrived as a deck path, a theme asset, a cached
    index, or a hand-assembled string.
    """

    client: str
    knowledge_root: Path

    @property
    def clients_root(self) -> Path:
        return (self.knowledge_root / CLIENTS_DIR).resolve()

    @property
    def own_root(self) -> Path:
        return (self.clients_root / self.client).resolve()

    def owns(self, path: Path) -> bool:
        """Whether `path` belongs to this client's namespace."""
        return self.own_root == path or self.own_root in path.parents

    def foreign_client(self, path: Path) -> str | None:
        """The name of another client owning `path`, or None.

        Returns None for project-tier and non-knowledge paths — those are shared by design
        and blocking them would break the two-tier structure D8 exists to provide.
        """
        resolved = path.resolve()
        if not (self.clients_root == resolved or self.clients_root in resolved.parents):
            return None
        if self.owns(resolved):
            return None
        try:
            return resolved.relative_to(self.clients_root).parts[0]
        except (ValueError, IndexError):  # pragma: no cover — unreachable given the check
            return None

    def guard(self, path: Path) -> Path:
        """Return `path` if it is readable by this build, else raise.

        Raises:
            ClientIsolationError: the path belongs to a different client.
        """
        intruder = self.foreign_client(Path(path))
        if intruder is not None:
            raise ClientIsolationError(
                f"build for client {self.client!r} tried to read {path}, which belongs to "
                f"client {intruder!r}. A4 makes any cross-client reference a build error: "
                "one client's material must never enter another client's deck."
            )
        return Path(path)

    def read(self, path: Path) -> str:
        """Read a text file through the isolation guard.

        The assembler's only file-reading method. Adding an `open()` elsewhere in this
        module would create a route around A4, which is why there isn't one.
        """
        return self.guard(path).read_text(encoding="utf-8")


@dataclass(frozen=True)
class RetrievalIndex:
    """A search index, tagged with the client it was built for.

    Indices are cached and expensive, which makes them exactly the thing someone reuses
    across builds. A leak here produces no file access at all — the other client's text
    simply appears in search results — so the client is recorded and checked rather than
    inferred from where the index happens to live.
    """

    client: str | None
    project: str
    payload: object = None
    """Opaque to this module; `autodeck.retrieval` owns the shape."""


@dataclass(frozen=True)
class AssembledContext:
    """Everything assembled for one build, ready to become prompt context.

    Carries `client` so that anything downstream — a prompt builder, a cache key, an audit
    record — can assert which namespace produced it rather than trusting provenance by
    convention.
    """

    client: str
    project: str
    project_md: str
    client_md: str
    value_prop_md: str
    engagements: list[str] = field(default_factory=list)
    header_profile: dict[str, object] | None = None
    sources: list[Path] = field(default_factory=list)
    """Every file read, in order. The audit trail for what entered the prompt."""

    def to_prompt_context(self) -> str:
        """Render the curated knowledge as one block, loaded fully (D8, OKF principle)."""
        sections = [
            f"# Project: {self.project}\n\n{self.project_md}",
            f"# Client: {self.client}\n\n{self.client_md}",
            f"# Client value proposition (framing — A5 applies)\n\n{self.value_prop_md}",
        ]
        sections.extend(
            f"# Engagement note {index}\n\n{text}"
            for index, text in enumerate(self.engagements, start=1)
        )
        return "\n\n---\n\n".join(sections)


class ContextAssembler:
    """Assembles one build's context from exactly one client namespace.

    Construction binds the client. There is no method to switch clients, and no method
    takes a client argument — reusing an assembler for a second client is impossible rather
    than discouraged.
    """

    def __init__(self, knowledge_root: Path, *, client: str, project: str) -> None:
        self.loader = KnowledgeLoader(knowledge_root)
        self.project = project
        self.namespace = ClientNamespace(client=client, knowledge_root=Path(knowledge_root))

    @property
    def client(self) -> str:
        return self.namespace.client

    def assemble(self) -> AssembledContext:
        """Load the project and client tiers into a single context.

        Raises:
            KnowledgeError: a folder is missing or malformed.
            ClientIsolationError: something reached outside this client's namespace.
        """
        project = self.loader.load_project(self.project)
        client = self.loader.load_client(self.client)

        # A client folder that somehow resolves outside its own namespace — via a symlink,
        # or a name that escaped validation — must fail here rather than be trusted because
        # the loader returned it.
        self.namespace.guard(client.root)

        sources = [
            project.root / "project.md",
            client.root / "client.md",
            client.root / "value_prop.md",
        ]

        engagements: list[str] = []
        for path in client.engagements:
            engagements.append(self.namespace.read(path))
            sources.append(path)

        return AssembledContext(
            client=client.name,
            project=project.name,
            project_md=project.project_md,
            client_md=client.client_md,
            value_prop_md=client.value_prop_md,
            engagements=engagements,
            header_profile=client.header_profile,
            sources=sources,
        )

    # -- guarded accessors for the non-obvious leak paths -------------------

    def reference_decks(self, client: ClientKnowledge | None = None) -> list[Path]:
        """Past decks for style learning (§6.12), each checked against the namespace.

        The likeliest leak in practice: reference decks are read for *style*, feel like
        neutral design assets, and are full of another client's facts. They also teach
        style and structure only — any fact lifted from one still needs a corpus citation
        (§6.12's accuracy rule).
        """
        knowledge = client or self.loader.load_client(self.client)
        return [self.namespace.guard(path) for path in knowledge.decks]

    def theme_assets(self, client: ClientKnowledge | None = None) -> list[Path]:
        """Tokens, template and icon directory, checked against the namespace."""
        knowledge = client or self.loader.load_client(self.client)
        candidates = [knowledge.tokens_path, knowledge.template_path, knowledge.icons_dir]
        return [self.namespace.guard(path) for path in candidates if path is not None]

    def use_index(self, index: RetrievalIndex) -> RetrievalIndex:
        """Accept a retrieval index only if it was built for this build.

        A cached index is the leak that touches no files: another client's text arrives
        through search results. An index with `client=None` is project-tier and shared by
        design (D8).

        Raises:
            ClientIsolationError: the index belongs to another client, or another project.
        """
        if index.client is not None and index.client != self.client:
            raise ClientIsolationError(
                f"build for client {self.client!r} was given a retrieval index built for "
                f"client {index.client!r}. A cached index leaks through search results "
                "without opening a single file, so it is checked rather than trusted (A4)."
            )
        if index.project != self.project:
            raise ClientIsolationError(
                f"retrieval index is for project {index.project!r}, not {self.project!r}"
            )
        return index

    def check_text(self, text: str, *, label: str = "text") -> str:
        """Assert that assembled text names no other client.

        A backstop, not the mechanism — the path and index guards are. It catches the case
        where another client's *name* has been pasted into curated markdown, which no file
        check can see. Deliberately narrow: it looks only for the names of clients that
        actually exist in this knowledge root, so it cannot fire on ordinary prose.
        """
        others = [name for name in self.loader.client_names() if name != self.client]
        found = sorted(name for name in others if name in text)
        if found:
            raise ClientIsolationError(
                f"{label} for client {self.client!r} mentions other client(s): "
                f"{', '.join(found)}. Curated markdown must not name another client (A4)."
            )
        return text


def assemble_context(knowledge_root: Path, *, client: str, project: str) -> AssembledContext:
    """Convenience wrapper for a one-shot assembly."""
    return ContextAssembler(knowledge_root, client=client, project=project).assemble()
