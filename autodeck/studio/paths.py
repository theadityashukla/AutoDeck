"""The workspace layout, in one place (P1, A4 by path).

Working state lives under a workspace root that is not the knowledge tree and is
git-ignored (`/workspace/` at the repo root by default):

```
<workspace>/
  engagements/<client>/<project>/
    engagement.json                 EngagementRecord
    artifacts/<artifact-id>/
      current.json                  the artifact's current state (canonical serialisation)
      changelog.json                ChangeLog
      versions/initial.json         the state the artifact was created with
      versions/<entry-id>.json      the state after each change-log entry
      renders/<digest12>/           derived: one render per deck state; safe to delete
    threads/<thread-id>/            Phase 1
      thread.json                   ThreadRecord
      context.md                    the opening context the thread was given
      messages.jsonl                ThreadLine records, append-only, one per line
    proposals/<proposal-id>/        Phase 1
      proposal.json                 ProposalRecord
      renders/<option-id>/          derived: candidate-slide previews
```

The client name is a path segment directly under `engagements/`, so "does this path belong
to another client" is a question about path prefixes, answered by `EngagementPaths.guard`.
Nothing outside this module builds these paths by string concatenation, the rule v2's
`RunPaths` set for `runs/`.

Every function here is pure path arithmetic: nothing touches the filesystem except
`ensure` methods, which only create directories.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from autodeck.knowledge.loader import ClientIsolationError
from autodeck.studio.errors import InvalidSegmentError, WorkspaceLocationError
from autodeck.studio.models import (
    ENTRY_ID_PATTERN,
    OPTION_IDS,
    PROPOSAL_ID_PATTERN,
    RENDER_DIGEST_PATTERN,
    SEGMENT_PATTERN,
    THREAD_ID_PATTERN,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
"""The repository root (the directory holding `pyproject.toml`)."""

DEFAULT_WORKSPACE_DIRNAME = "workspace"

ENGAGEMENTS_DIR = "engagements"
ARTIFACTS_DIR = "artifacts"
THREADS_DIR = "threads"
VERSIONS_DIR = "versions"
RENDERS_DIR = "renders"
ENGAGEMENT_FILE = "engagement.json"
CURRENT_FILE = "current.json"
CHANGELOG_FILE = "changelog.json"
INITIAL_VERSION_FILE = "initial.json"
PROPOSALS_DIR = "proposals"
THREAD_FILE = "thread.json"
MESSAGES_FILE = "messages.jsonl"
CONTEXT_FILE = "context.md"
PROPOSAL_FILE = "proposal.json"
DESIGN_SYSTEMS_DIR = "design_systems"
"""Phase 2-3: `<engagement>/design_systems/<system id>/v0001.json`, one file per version."""

_SEGMENT = re.compile(SEGMENT_PATTERN)
_ENTRY_ID = re.compile(ENTRY_ID_PATTERN)
_THREAD_ID = re.compile(THREAD_ID_PATTERN)
_PROPOSAL_ID = re.compile(PROPOSAL_ID_PATTERN)
_RENDER_DIGEST = re.compile(RENDER_DIGEST_PATTERN)


def _check(pattern: re.Pattern[str], value: str, label: str, example: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise InvalidSegmentError(f"invalid {label}: {value!r} (expected {example})")
    return value


def _matching_dirs(directory: Path, pattern: re.Pattern[str]) -> list[str]:
    """Names of the subdirectories of `directory` matching `pattern`, sorted; [] if none."""
    try:
        children = list(directory.iterdir())
    except (FileNotFoundError, NotADirectoryError):
        return []
    return sorted(c.name for c in children if pattern.fullmatch(c.name) and c.is_dir())


def default_workspace_root() -> Path:
    """`REPO_ROOT / "workspace"`. No environment variable overrides it: callers that want
    another root pass one explicitly (tests always do, with a temporary directory)."""
    return REPO_ROOT / DEFAULT_WORKSPACE_DIRNAME


def check_segment(name: str, *, label: str) -> str:
    """Return `name` unchanged if it matches `models.SEGMENT_PATTERN`, else raise.

    `label` names what the value is ("client", "project", "artifact id") and appears in the
    error message together with the rejected value, e.g.
    `InvalidSegmentError("invalid artifact id: '../x' ...")`.

    Raises:
        InvalidSegmentError: empty, starts with a dot, or contains anything outside
            `[A-Za-z0-9._-]` (so `/`, `\\`, spaces and `..` are all rejected).
    """
    # fullmatch, not match: `$` in SEGMENT_PATTERN also matches before a trailing newline.
    if not isinstance(name, str) or _SEGMENT.fullmatch(name) is None:
        raise InvalidSegmentError(
            f"invalid {label}: {name!r} (use letters, digits, '.', '_' or '-')"
        )
    return name


def check_workspace_location(workspace_root: Path, knowledge_root: Path) -> None:
    """Refuse a workspace root that overlaps the knowledge tree.

    Both paths are resolved (`Path.resolve()`, following symlinks; neither need exist yet)
    before comparison. Overlap means: equal, the workspace inside the knowledge root, or the
    knowledge root inside the workspace.

    Raises:
        WorkspaceLocationError: the two overlap; the message names both resolved paths.
    """
    ws = workspace_root.resolve()
    kn = knowledge_root.resolve()
    if ws == kn or ws.is_relative_to(kn) or kn.is_relative_to(ws):
        raise WorkspaceLocationError(f"workspace root {ws} overlaps the knowledge tree {kn}")


@dataclass(frozen=True)
class ArtifactPaths:
    """Paths of one artifact. `root` is `<engagement>/artifacts/<artifact-id>`."""

    root: Path

    @property
    def artifact_id(self) -> str:
        return self.root.name

    @property
    def current(self) -> Path:
        """`<root>/current.json`."""
        return self.root / CURRENT_FILE

    @property
    def changelog(self) -> Path:
        """`<root>/changelog.json`."""
        return self.root / CHANGELOG_FILE

    @property
    def versions(self) -> Path:
        """`<root>/versions`."""
        return self.root / VERSIONS_DIR

    @property
    def initial_version(self) -> Path:
        """`<root>/versions/initial.json`."""
        return self.versions / INITIAL_VERSION_FILE

    @property
    def renders(self) -> Path:
        """`<root>/renders`: derived output, never read back as state."""
        return self.root / RENDERS_DIR

    def render_dir(self, digest12: str) -> Path:
        """`<root>/renders/<digest12>`: the render of one deck state (Phase 1).

        Raises:
            InvalidSegmentError: `digest12` is not 12 lower-case hex characters.
        """
        _check(_RENDER_DIGEST, digest12, "render digest", "12 lower-case hex characters")
        return self.renders / digest12

    def version(self, entry_id: str) -> Path:
        """`<root>/versions/<entry_id>.json`, the state after that entry.

        Raises:
            InvalidSegmentError: `entry_id` does not match `models.ENTRY_ID_PATTERN`
                (so `initial`, `../x` and `c1` are all rejected).
        """
        if _ENTRY_ID.fullmatch(entry_id) is None:
            raise InvalidSegmentError(
                f"invalid entry id: {entry_id!r} (expected c0001, c0002, ...)"
            )
        return self.versions / f"{entry_id}.json"

    def ensure(self) -> ArtifactPaths:
        """Create `root` and `versions` (parents included; existing is fine). Returns self."""
        self.versions.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class ThreadPaths:
    """Paths of one thread (Phase 1). `root` is `<engagement>/threads/<thread-id>`."""

    root: Path

    @property
    def thread_id(self) -> str:
        return self.root.name

    @property
    def record(self) -> Path:
        """`<root>/thread.json`."""
        return self.root / THREAD_FILE

    @property
    def messages(self) -> Path:
        """`<root>/messages.jsonl`: the thread's own log, for display and for this thread's
        model context only. No other thread ever reads it."""
        return self.root / MESSAGES_FILE

    @property
    def context(self) -> Path:
        """`<root>/context.md`: the opening context built from state when the thread began."""
        return self.root / CONTEXT_FILE

    def ensure(self) -> ThreadPaths:
        """Create `root` (parents included; existing is fine). Returns self."""
        self.root.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class ProposalPaths:
    """Paths of one proposal (Phase 1). `root` is `<engagement>/proposals/<proposal-id>`."""

    root: Path

    @property
    def proposal_id(self) -> str:
        return self.root.name

    @property
    def record(self) -> Path:
        """`<root>/proposal.json`."""
        return self.root / PROPOSAL_FILE

    @property
    def renders(self) -> Path:
        """`<root>/renders`: derived previews of the candidate slides."""
        return self.root / RENDERS_DIR

    def option_renders(self, option_id: str) -> Path:
        """`<root>/renders/<option_id>`.

        Raises:
            InvalidSegmentError: `option_id` is not one of `models.OPTION_IDS`.
        """
        if option_id not in OPTION_IDS:
            raise InvalidSegmentError(f"invalid option id: {option_id!r} (expected A to D)")
        return self.renders / option_id

    def ensure(self) -> ProposalPaths:
        """Create `root` (parents included; existing is fine). Returns self."""
        self.root.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class EngagementPaths:
    """Paths of one engagement. `root` is `<workspace>/engagements/<client>/<project>`.

    Construct through `WorkspacePaths.engagement`, which validates the segments.
    """

    workspace_root: Path
    client: str
    project: str

    @property
    def root(self) -> Path:
        """`<workspace_root>/engagements/<client>/<project>`."""
        return self.workspace_root / ENGAGEMENTS_DIR / self.client / self.project

    @property
    def record(self) -> Path:
        """`<root>/engagement.json`."""
        return self.root / ENGAGEMENT_FILE

    @property
    def artifacts(self) -> Path:
        """`<root>/artifacts`."""
        return self.root / ARTIFACTS_DIR

    @property
    def threads(self) -> Path:
        """`<root>/threads`."""
        return self.root / THREADS_DIR

    @property
    def proposals(self) -> Path:
        """`<root>/proposals`."""
        return self.root / PROPOSALS_DIR

    def thread(self, thread_id: str) -> ThreadPaths:
        """`ThreadPaths(<root>/threads/<thread_id>)`.

        Raises:
            InvalidSegmentError: `thread_id` does not match `models.THREAD_ID_PATTERN`.
        """
        _check(_THREAD_ID, thread_id, "thread id", "t0001, t0002, ...")
        return ThreadPaths(self.threads / thread_id)

    def thread_ids(self) -> list[str]:
        """Directories under `threads/` whose name is a thread id, sorted; [] if none."""
        return _matching_dirs(self.threads, _THREAD_ID)

    def proposal(self, proposal_id: str) -> ProposalPaths:
        """`ProposalPaths(<root>/proposals/<proposal_id>)`.

        Raises:
            InvalidSegmentError: `proposal_id` does not match `models.PROPOSAL_ID_PATTERN`.
        """
        _check(_PROPOSAL_ID, proposal_id, "proposal id", "p0001, p0002, ...")
        return ProposalPaths(self.proposals / proposal_id)

    def proposal_ids(self) -> list[str]:
        """Directories under `proposals/` whose name is a proposal id, sorted; [] if none."""
        return _matching_dirs(self.proposals, _PROPOSAL_ID)

    @property
    def design_systems(self) -> Path:
        """Phase 2-3: `<root>/design_systems`."""
        return self.root / DESIGN_SYSTEMS_DIR

    def design_system_dir(self, system_id: str) -> Path:
        """Phase 2-3: `<root>/design_systems/<system_id>`.

        Raises:
            InvalidSegmentError: `system_id` is not a safe segment (`check_segment`).
        """
        return self.design_systems / check_segment(system_id, label="design system id")

    def design_system_version(self, system_id: str, version: int) -> Path:
        """Phase 2-3: `<root>/design_systems/<system_id>/v<version, 4 digits>.json`
        (`v0001.json`). Raises `InvalidSegmentError` for a bad id or a version below 1."""
        if version < 1:
            raise InvalidSegmentError(f"design system version {version} is below 1")
        return self.design_system_dir(system_id) / f"v{version:04d}.json"

    def artifact(self, artifact_id: str) -> ArtifactPaths:
        """`ArtifactPaths(<root>/artifacts/<artifact_id>)`.

        Raises:
            InvalidSegmentError: `artifact_id` is not a safe segment (`check_segment`).
        """
        return ArtifactPaths(self.artifacts / check_segment(artifact_id, label="artifact id"))

    def artifact_ids(self) -> list[str]:
        """Names of the directories under `artifacts/`, sorted; `[]` if it does not exist.

        Only directories whose name is a valid segment are returned; stray files and
        hidden directories are ignored.
        """
        try:
            children = list(self.artifacts.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            return []
        return sorted(
            c.name for c in children if _SEGMENT.fullmatch(c.name) is not None and c.is_dir()
        )

    def foreign_client(self, path: Path) -> str | None:
        """The other client a path belongs to inside this workspace, or None.

        Resolve `path` and `<workspace_root>/engagements`. If the path is not under the
        engagements directory, return None (not a workspace path; other guards cover it).
        Otherwise the first path component below `engagements/` is the owning client: return
        it if it differs from `self.client`, else None. The engagements directory itself
        (no client component) returns None. A path under this client's directory but in a
        different *project* returns None: projects are not isolated from each other, only
        clients are (D8).
        """
        engagements = (self.workspace_root / ENGAGEMENTS_DIR).resolve()
        resolved = path.resolve()
        if not resolved.is_relative_to(engagements):
            return None
        parts = resolved.relative_to(engagements).parts
        if not parts or parts[0] == self.client:
            return None
        return parts[0]

    def guard(self, path: Path) -> Path:
        """Return `path` unchanged if `foreign_client(path)` is None.

        Raises:
            ClientIsolationError: (v2's, from `autodeck.knowledge.loader`) the path belongs
                to another client's engagements; the message names both clients and the path.
        """
        owner = self.foreign_client(path)
        if owner is not None:
            raise ClientIsolationError(
                f"client {self.client!r} may not reach client {owner!r}'s engagements: {path}"
            )
        return path

    def ensure(self) -> EngagementPaths:
        """Create `root` and `artifacts` (parents included; existing is fine). Not `threads`.
        Returns self."""
        self.artifacts.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class WorkspacePaths:
    """The workspace root and what hangs off it."""

    root: Path

    @property
    def engagements(self) -> Path:
        """`<root>/engagements`."""
        return self.root / ENGAGEMENTS_DIR

    def engagement(self, client: str, project: str) -> EngagementPaths:
        """`EngagementPaths(self.root, client, project)` after `check_segment` on both.

        Raises:
            InvalidSegmentError: either name is not a safe segment.
        """
        check_segment(client, label="client")
        check_segment(project, label="project")
        return EngagementPaths(self.root, client, project)

    def engagement_keys(self) -> list[tuple[str, str]]:
        """Every `(client, project)` with an `engagement.json`, sorted.

        Walks `engagements/<client>/<project>/engagement.json`; directories without the
        record, and names that are not valid segments, are skipped. `[]` when the
        engagements directory does not exist.
        """
        keys: list[tuple[str, str]] = []
        try:
            clients = list(self.engagements.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            return []
        for client_dir in clients:
            if _SEGMENT.fullmatch(client_dir.name) is None or not client_dir.is_dir():
                continue
            for project_dir in client_dir.iterdir():
                if _SEGMENT.fullmatch(project_dir.name) is None:
                    continue
                if (project_dir / ENGAGEMENT_FILE).is_file():
                    keys.append((client_dir.name, project_dir.name))
        return sorted(keys)


def workspace_paths(workspace_root: Path | None = None) -> WorkspacePaths:
    """`WorkspacePaths` for `workspace_root`, or for `default_workspace_root()` when None.
    The path is used as given (not resolved) and nothing is created."""
    return WorkspacePaths(
        default_workspace_root() if workspace_root is None else workspace_root
    )
