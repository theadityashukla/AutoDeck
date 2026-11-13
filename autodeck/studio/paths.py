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
      renders/                      derived: PPTX and previews; safe to delete
    threads/                        Phase 1
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

from autodeck.studio.models import ENTRY_ID_PATTERN, SEGMENT_PATTERN

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

_SEGMENT = re.compile(SEGMENT_PATTERN)
_ENTRY_ID = re.compile(ENTRY_ID_PATTERN)


def default_workspace_root() -> Path:
    """`REPO_ROOT / "workspace"`. No environment variable overrides it: callers that want
    another root pass one explicitly (tests always do, with a temporary directory)."""
    raise NotImplementedError


def check_segment(name: str, *, label: str) -> str:
    """Return `name` unchanged if it matches `models.SEGMENT_PATTERN`, else raise.

    `label` names what the value is ("client", "project", "artifact id") and appears in the
    error message together with the rejected value, e.g.
    `InvalidSegmentError("invalid artifact id: '../x' ...")`.

    Raises:
        InvalidSegmentError: empty, starts with a dot, or contains anything outside
            `[A-Za-z0-9._-]` (so `/`, `\\`, spaces and `..` are all rejected).
    """
    raise NotImplementedError


def check_workspace_location(workspace_root: Path, knowledge_root: Path) -> None:
    """Refuse a workspace root that overlaps the knowledge tree.

    Both paths are resolved (`Path.resolve()`, following symlinks; neither need exist yet)
    before comparison. Overlap means: equal, the workspace inside the knowledge root, or the
    knowledge root inside the workspace.

    Raises:
        WorkspaceLocationError: the two overlap; the message names both resolved paths.
    """
    raise NotImplementedError


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
        raise NotImplementedError

    @property
    def changelog(self) -> Path:
        """`<root>/changelog.json`."""
        raise NotImplementedError

    @property
    def versions(self) -> Path:
        """`<root>/versions`."""
        raise NotImplementedError

    @property
    def initial_version(self) -> Path:
        """`<root>/versions/initial.json`."""
        raise NotImplementedError

    @property
    def renders(self) -> Path:
        """`<root>/renders`: derived output, never read back as state."""
        raise NotImplementedError

    def version(self, entry_id: str) -> Path:
        """`<root>/versions/<entry_id>.json`, the state after that entry.

        Raises:
            InvalidSegmentError: `entry_id` does not match `models.ENTRY_ID_PATTERN`
                (so `initial`, `../x` and `c1` are all rejected).
        """
        raise NotImplementedError

    def ensure(self) -> ArtifactPaths:
        """Create `root` and `versions` (parents included; existing is fine). Returns self."""
        raise NotImplementedError


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
        raise NotImplementedError

    @property
    def record(self) -> Path:
        """`<root>/engagement.json`."""
        raise NotImplementedError

    @property
    def artifacts(self) -> Path:
        """`<root>/artifacts`."""
        raise NotImplementedError

    @property
    def threads(self) -> Path:
        """`<root>/threads` (unused until Phase 1)."""
        raise NotImplementedError

    def artifact(self, artifact_id: str) -> ArtifactPaths:
        """`ArtifactPaths(<root>/artifacts/<artifact_id>)`.

        Raises:
            InvalidSegmentError: `artifact_id` is not a safe segment (`check_segment`).
        """
        raise NotImplementedError

    def artifact_ids(self) -> list[str]:
        """Names of the directories under `artifacts/`, sorted; `[]` if it does not exist.

        Only directories whose name is a valid segment are returned; stray files and
        hidden directories are ignored.
        """
        raise NotImplementedError

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
        raise NotImplementedError

    def guard(self, path: Path) -> Path:
        """Return `path` unchanged if `foreign_client(path)` is None.

        Raises:
            ClientIsolationError: (v2's, from `autodeck.knowledge.loader`) the path belongs
                to another client's engagements; the message names both clients and the path.
        """
        raise NotImplementedError

    def ensure(self) -> EngagementPaths:
        """Create `root` and `artifacts` (parents included; existing is fine). Not `threads`.
        Returns self."""
        raise NotImplementedError


@dataclass(frozen=True)
class WorkspacePaths:
    """The workspace root and what hangs off it."""

    root: Path

    @property
    def engagements(self) -> Path:
        """`<root>/engagements`."""
        raise NotImplementedError

    def engagement(self, client: str, project: str) -> EngagementPaths:
        """`EngagementPaths(self.root, client, project)` after `check_segment` on both.

        Raises:
            InvalidSegmentError: either name is not a safe segment.
        """
        raise NotImplementedError

    def engagement_keys(self) -> list[tuple[str, str]]:
        """Every `(client, project)` with an `engagement.json`, sorted.

        Walks `engagements/<client>/<project>/engagement.json`; directories without the
        record, and names that are not valid segments, are skipped. `[]` when the
        engagements directory does not exist.
        """
        raise NotImplementedError


def workspace_paths(workspace_root: Path | None = None) -> WorkspacePaths:
    """`WorkspacePaths` for `workspace_root`, or for `default_workspace_root()` when None.
    The path is used as given (not resolved) and nothing is created."""
    raise NotImplementedError
