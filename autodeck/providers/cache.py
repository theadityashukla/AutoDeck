"""On-disk response cache — the resumability half of task 0.3.

Free-tier development (B8) means a long run will be interrupted by a rate limit, usually
partway through something expensive like `ingest_vlm` over a corpus. Without a cache the
only options are to re-pay for every completed call or to build resumability later, under
the rate limit that is already blocking you. Plan §7 asks for it in Phase 0 for exactly
that reason.

The cache is keyed by the full request — provider, model, temperature, system, prompt, and
schema digest — so it is safe by construction: a changed prompt or a changed schema is a
different key, and a resumed run cannot silently reuse a response produced under a contract
that has since changed.

Owning phase: 0 (task 0.3).
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class ResponseCache:
    """Content-addressed store of raw provider replies under `runs/<run_id>/llm_cache/`.

    Deliberately dumb: no expiry, no size cap, no eviction. A run directory is the unit of
    cleanup, and a cache entry that outlives its usefulness costs a few kilobytes, whereas
    an entry evicted mid-run costs an API call at the exact moment the quota is exhausted.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    @staticmethod
    def make_key(material: str) -> str:
        """Hash the full request description into a cache key."""
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def path_for(self, key: str) -> Path:
        # Two-character shard keeps directory listings usable over a long run.
        return self.directory / key[:2] / f"{key}.txt"

    def get(self, key: str) -> str | None:
        path = self.path_for(key)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def put(self, key: str, value: str) -> None:
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: an interrupted write must not leave a truncated response that
        # a later resume would treat as a valid cache hit.
        temporary = path.with_suffix(".tmp")
        temporary.write_text(value, encoding="utf-8")
        temporary.replace(path)

    def __len__(self) -> int:
        if not self.directory.exists():
            return 0
        return sum(1 for _ in self.directory.rglob("*.txt"))
