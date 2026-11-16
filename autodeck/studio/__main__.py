"""`python -m autodeck.studio`: start the studio's local server (Phase 1).

v2's `cli.py` is not touched; the studio has its own entry point.

    python -m autodeck.studio [--env ENV] [--port 8765] [--script PATH]
                              [--workspace DIR] [--knowledge DIR] [--corpus DIR]
                              [--owner-memory FILE] [--no-render]

* `--script PATH` (or the `AUTODECK_STUDIO_SCRIPT` environment variable, when `--script` is
  not given) runs the scripted stand-in model instead of a provider: no API key needed.
  Example: `--script tests/studio/fixtures/scripts/design_flow.json`. Every role is played
  by the script (`scripted.scripted_bindings`).
* Otherwise every role is bound from `config/studio.yaml` for `--env` (default: its
  `default_env`) with `bindings.bind_all`, with a response cache under
  `<workspace>/llm_cache/`. A missing API key
  is reported as one line naming the variable, exit status 2.
* `--no-render` uses a renderer that never calls LibreOffice (every render is
  `rendered=False`, "previews disabled"), for machines without it. Otherwise previews are
  rendered in each deck's design system (`design_render.render_with_design(tokens)`).
* Phase 2-3: `--prices FILE` names the assumed price file (default
  `config/studio_prices.yaml`, `usage.load_prices`).

Defaults: workspace `paths.default_workspace_root()`, knowledge `<repo>/knowledge`, corpus
`<repo>/corpus`, owner memory v2's `memory.DEFAULT_OWNER_PATH`, port 8765. The server binds
127.0.0.1 only and prints exactly one line, `AutoDeck studio: http://127.0.0.1:<port>/`,
then serves until interrupted (Ctrl-C exits 0 after `Studio.shutdown()`).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from autodeck.providers.base import ProviderAuthError
from autodeck.studio import server
from autodeck.studio.api import StudioApp
from autodeck.studio.conversation import RenderManifest
from autodeck.studio.errors import StudioConfigError
from autodeck.studio.models import DeckArtifact
from autodeck.studio.session import Studio

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
    parser.add_argument("--prices", type=Path, default=None, help="assumed price file")
    return parser.parse_args(argv)


def _no_render(deck: DeckArtifact, out_dir: Path, digest: str) -> RenderManifest:
    return RenderManifest(
        digest=digest, slide_ids=deck.slide_ids(), rendered=False, note="previews disabled"
    )


def build(args: argparse.Namespace) -> tuple[StudioApp, Studio]:
    """Construct, without serving (Phase 2-3):

    tokens (`bindings.tokens_path(config)` → `DesignTokens.load`); the bindings
    (`scripted.scripted_bindings(ScriptedModel.from_file(script))` with a script, else
    `bindings.bind_all(config, env=args.env, cache_dir=workspace / "llm_cache")`);
    `EventBus()`; `PreviewService(bus=..., renderer=_no_render if args.no_render else
    design_render.render_with_design(tokens))`; `StudioSettings(..., tokens=tokens,
    prices=usage.load_prices(args.prices or usage.DEFAULT_PRICES_PATH))`;
    `Studio(settings, bindings=..., bus=..., previews=...)`; and `StudioApp(studio,
    env=<the lead binding's env>, scripted=<a script was used>)`. Returns `(app, studio)`.
    """
    import os

    from autodeck.design.theme.tokens import DesignTokens
    from autodeck.knowledge.memory import DEFAULT_OWNER_PATH
    from autodeck.studio import bindings, design_render, scripted, usage
    from autodeck.studio.events import EventBus
    from autodeck.studio.paths import REPO_ROOT, default_workspace_root
    from autodeck.studio.previews import PreviewService
    from autodeck.studio.session import StudioSettings

    config = bindings.load_studio_config()
    tokens = DesignTokens.load(bindings.tokens_path(config))
    workspace: Path = args.workspace or default_workspace_root()
    script: Path | None = args.script
    if script is None and os.environ.get(scripted.SCRIPT_ENV_VAR):
        script = Path(os.environ[scripted.SCRIPT_ENV_VAR])
    if script is not None:
        all_roles = scripted.scripted_bindings(scripted.ScriptedModel.from_file(script))
    else:
        all_roles = bindings.bind_all(config, env=args.env, cache_dir=workspace / "llm_cache")
    bus = EventBus()
    renderer = _no_render if args.no_render else design_render.render_with_design(tokens)
    previews = PreviewService(bus=bus, renderer=renderer)  # type: ignore[arg-type]
    settings = StudioSettings(
        knowledge_root=args.knowledge or REPO_ROOT / "knowledge",
        workspace_root=workspace,
        corpus_root=args.corpus or REPO_ROOT / "corpus",
        owner_memory_path=args.owner_memory or DEFAULT_OWNER_PATH,
        tokens=tokens,
        prices=usage.load_prices(args.prices or usage.DEFAULT_PRICES_PATH),
    )
    studio = Studio(settings, bindings=all_roles, bus=bus, previews=previews)
    return StudioApp(studio, env=all_roles.lead.env, scripted=script is not None), studio


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
