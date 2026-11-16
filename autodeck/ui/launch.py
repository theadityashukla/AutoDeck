"""Open the review UI: a native window if pywebview is installed, else the browser (B40).

pywebview uses the web view the OS already ships (WebView2 on Windows, WKWebView on
macOS), so the window costs no download beyond the `ui` extra. Anything that stops it —
the package missing, no GUI backend (most Linux servers) — falls back to the default
browser on the same local address, which is the fallback the owner asked for.
"""

from __future__ import annotations

import threading
import webbrowser
from collections.abc import Callable

from autodeck.ui.api import Roots
from autodeck.ui.server import make_server


def serve(
    roots: Roots,
    *,
    port: int = 0,
    window: bool = True,
    say: Callable[[str], None] = print,
) -> None:
    """Run until the window closes (native) or Ctrl-C (browser)."""
    server = make_server(roots, port=port)
    host, bound = server.server_address[:2]
    url = f"http://{host}:{bound}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        if window and _run_window(url, say):
            return
        say(f"AutoDeck is running at {url}  (Ctrl-C to stop)")
        webbrowser.open(url)
        thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


def _run_window(url: str, say: Callable[[str], None]) -> bool:
    """Show the native window and block until it closes. False if it cannot be shown."""
    try:
        import webview  # type: ignore[import-not-found]
    except ImportError:
        say("Native window unavailable (install with `uv sync --extra ui`); using the browser.")
        return False
    try:
        webview.create_window(
            "AutoDeck", url, width=1320, height=860, min_size=(900, 620), text_select=True
        )
        webview.start()
    except Exception as exc:  # no GUI backend, WebView2 runtime missing, etc.
        say(f"Native window failed ({type(exc).__name__}: {exc}); using the browser.")
        return False
    return True
