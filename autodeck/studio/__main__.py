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
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from autodeck.design.theme.tokens import DesignTokens
from autodeck.knowledge.memory import DEFAULT_OWNER_PATH
from autodeck.providers.base import ProviderAuthError
from autodeck.studio import bindings, server
from autodeck.studio.api import StudioApp
from autodeck.studio.conversation import RenderManifest
from autodeck.studio.errors import StudioConfigError
from autodeck.studio.events import EventBus
from autodeck.studio.models import DeckArtifact
from autodeck.studio.paths import REPO_ROOT, default_workspace_root
from autodeck.studio.previews import PreviewService, render_with_libreoffice
from autodeck.studio.scripted import SCRIPT_ENV_VAR, ScriptedModel, scripted_binding
from autodeck.studio.session import Studio, StudioSettings

DEFAULT_PORT = 8765


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """The options above, with their defaults. `--port` is an int; paths are `Path`s or
    None (None = the default described above)."""
    parser = argparse.ArgumentParser(
        prog="python -m autodeck.studio", description="AutoDeck studio local server."
    )
    parser.add_argument("--env", default=None, help="environment in config/studio.yaml")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--script", type=Path, default=None, help="scripted model (no API key)")
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--knowledge", type=Path, default=None)
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument("--owner-memory", type=Path, default=None)
    parser.add_argument("--no-render", action="store_true", help="never call LibreOffice")
    return parser.parse_args(argv)


def _no_render(deck: DeckArtifact, out_dir: Path, digest: str) -> RenderManifest:
    return RenderManifest(
        digest=digest, slide_ids=deck.slide_ids(), rendered=False, note="previews disabled"
    )


def build(args: argparse.Namespace) -> tuple[StudioApp, Studio]:
    """Construct, without serving: tokens (`bindings.tokens_path(config)` →
    `DesignTokens.load`), the lead (`scripted.ScriptedModel.from_file` +
    `scripted_binding`, or `bindings.bind_model`), `EventBus()`, `PreviewService(bus=...,
    renderer=render_with_libreoffice(tokens) or the no-render renderer)`, `Studio`, and
    `StudioApp(studio, env=lead.env, scripted=...)`. Returns `(app, studio)`."""
    config = bindings.load_studio_config()
    tokens = DesignTokens.load(bindings.tokens_path(config))
    workspace: Path = args.workspace or default_workspace_root()
    script: Path | None = args.script
    if script is None and os.environ.get(SCRIPT_ENV_VAR):
        script = Path(os.environ[SCRIPT_ENV_VAR])
    if script is not None:
        lead = scripted_binding(ScriptedModel.from_file(script))
    else:
        lead = bindings.bind_model(config, env=args.env, cache_dir=workspace / "llm_cache")
    bus = EventBus()
    previews = PreviewService(
        bus=bus, renderer=_no_render if args.no_render else render_with_libreoffice(tokens)
    )
    settings = StudioSettings(
        knowledge_root=args.knowledge or REPO_ROOT / "knowledge",
        workspace_root=workspace,
        corpus_root=args.corpus or REPO_ROOT / "corpus",
        owner_memory_path=args.owner_memory or DEFAULT_OWNER_PATH,
        tokens=tokens,
    )
    studio = Studio(settings, lead=lead, bus=bus, previews=previews)
    return StudioApp(studio, env=lead.env, scripted=script is not None), studio


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, build, `server.make_server(app, port=args.port)`, print the URL line,
    `serve_forever()`; on KeyboardInterrupt shut down cleanly and return 0. A
    `ProviderAuthError` or `StudioConfigError` while building prints one line to stderr
    and returns 2."""
    args = parse_args(argv)
    try:
        app, studio = build(args)
    except (ProviderAuthError, StudioConfigError) as exc:
        print(f"autodeck studio: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:  # unreadable script, tokens, workspace
        print(f"autodeck studio: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    try:
        httpd = server.make_server(app, port=args.port)
    except OSError as exc:
        studio.shutdown()
        print(f"autodeck studio: cannot listen on port {args.port}: {exc}", file=sys.stderr)
        return 2
    print(f"AutoDeck studio: http://127.0.0.1:{httpd.server_address[1]}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.stopping.set()  # type: ignore[attr-defined]
        httpd.server_close()
        studio.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
