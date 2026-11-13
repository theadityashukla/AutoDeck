"""`python -m autodeck.studio`: start the studio's local server (Phase 1).

v2's `cli.py` is not touched; the studio has its own entry point.

    python -m autodeck.studio [--env ENV] [--port 8765] [--script PATH]
                              [--workspace DIR] [--knowledge DIR] [--corpus DIR]
                              [--owner-memory FILE] [--no-render]

* `--script PATH` (or the `AUTODECK_STUDIO_SCRIPT` environment variable, when `--script` is
  not given) runs the scripted stand-in model instead of a provider: no API key needed.
  Example: `--script tests/studio/fixtures/scripts/two_threads.json`.
* Otherwise the lead is bound from `config/studio.yaml` for `--env` (default: its
  `default_env`), with a response cache under `<workspace>/llm_cache/`. A missing API key
  is reported as one line naming the variable, exit status 2.
* `--no-render` uses a renderer that never calls LibreOffice (every render is
  `rendered=False`, "previews disabled"), for machines without it.

Defaults: workspace `paths.default_workspace_root()`, knowledge `<repo>/knowledge`, corpus
`<repo>/corpus`, owner memory v2's `memory.DEFAULT_OWNER_PATH`, port 8765. The server binds
127.0.0.1 only and prints exactly one line, `AutoDeck studio: http://127.0.0.1:<port>/`,
then serves until interrupted (Ctrl-C exits 0 after `Studio.shutdown()`).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from autodeck.studio.api import StudioApp
from autodeck.studio.session import Studio

DEFAULT_PORT = 8765


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """The options above, with their defaults. `--port` is an int; paths are `Path`s or
    None (None = the default described above)."""
    raise NotImplementedError


def build(args: argparse.Namespace) -> tuple[StudioApp, Studio]:
    """Construct, without serving: tokens (`bindings.tokens_path(config)` →
    `DesignTokens.load`), the lead (`scripted.ScriptedModel.from_file` +
    `scripted_binding`, or `bindings.bind_model`), `EventBus()`, `PreviewService(bus=...,
    renderer=render_with_libreoffice(tokens) or the no-render renderer)`, `Studio`, and
    `StudioApp(studio, env=lead.env, scripted=...)`. Returns `(app, studio)`."""
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, build, `server.make_server(app, port=args.port)`, print the URL line,
    `serve_forever()`; on KeyboardInterrupt shut down cleanly and return 0. A
    `ProviderAuthError` or `StudioConfigError` while building prints one line to stderr
    and returns 2."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
