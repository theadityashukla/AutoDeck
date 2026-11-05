"""Which `tokens.json` a build uses (task 4.1).

An explicit `--tokens` wins. Otherwise a client's own `theme/tokens.json` (written by
`autodeck onboard`) is the theme; a client without one falls back to the dev default. The
client's file is reached through its `ClientNamespace`, so a symlink or path into another
client's folder is a build error (A4) rather than a quiet cross-client read.
"""

from __future__ import annotations

from pathlib import Path

from autodeck.knowledge.context_assembler import ClientNamespace
from autodeck.knowledge.loader import CLIENTS_DIR, KnowledgeError

DEFAULT_TOKENS = Path("config/tokens/dev.json")


def client_tokens_path(knowledge_root: Path, client: str) -> Path | None:
    """The client's `theme/tokens.json` if it exists (guarded), else None."""
    namespace = ClientNamespace(client=client, knowledge_root=Path(knowledge_root))
    path = Path(knowledge_root) / CLIENTS_DIR / client / "theme" / "tokens.json"
    if not path.is_file():
        return None
    resolved = path.resolve()
    # The guard raises if the file (or a symlink it follows) belongs to another client.
    namespace.guard(resolved)
    if not namespace.owns(resolved):
        namespace.guard(path)  # foreign -> raises; non-client path -> refuse below
        raise KnowledgeError(f"{path} resolves to {resolved}, outside client {client!r}")
    return path


def resolve_tokens_path(
    explicit: Path | None,
    *,
    knowledge_root: Path,
    client: str | None,
    default: Path = DEFAULT_TOKENS,
) -> Path:
    """`explicit`, else the client's own tokens, else `default`."""
    if explicit is not None:
        return Path(explicit)
    if client:
        own = client_tokens_path(knowledge_root, client)
        if own is not None:
            return own
    return default
