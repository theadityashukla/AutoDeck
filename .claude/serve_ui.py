"""Serve the review UI on a fixed port without opening a browser (for the in-app preview)."""
import os
from pathlib import Path

from autodeck.ui.api import Roots, restore_env
from autodeck.ui.server import make_server

roots = Roots(knowledge=Path("knowledge"), corpus=Path("corpus"), runs=Path("runs"))
restore_env(roots)
server = make_server(roots, port=int(os.environ.get("PORT", "8765")))
print("serving", server.server_address, flush=True)
server.serve_forever()
