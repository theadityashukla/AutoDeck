"""Phase 0 of AutoDeck v3, shown end to end, with preview speed measured (plan §12, §13).

Loads the hand-written fixture deck (`tests/studio/fixtures/base_deck.json`) into an
engagement in a **temporary** workspace, over the repo's real knowledge folders (read
only), renders it to PPTX and PNG previews, applies one edit, lists the change log, undoes
the edit, and checks the artifact is byte-identical to before. It prints how long the PPTX
build and the preview rasterisation each took: the number the plan's first risk asks for.

Usage:
    uv run python scripts/studio_demo.py [--tokens config/tokens/dev.json]
        [--knowledge-root knowledge] [--keep]

`--keep` leaves the temporary workspace on disk and prints its path, so the PPTX and the
PNGs can be opened. Without it the workspace is deleted on exit.

Exit 0 when every step succeeded (previews not rendering because LibreOffice is absent is
reported but is not a failure), 1 when the undo was not exact or any step raised.

Expected output shape (numbers vary):

    engagement: northwind-retail / llm-inference-efficiency
    artifact:   inference-readout (4 slides)
    pptx build: 0.04s for 4 slides
    previews:   2.05s for 4 images
    edit:       c0001 slides[s2].blocks[heading].text
    log:        c0001 live composition human demo 2026-...  Tighten the slide two heading.
    undo:       c0001 undone; current.json byte-identical to before: yes
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autodeck.design.theme.tokens import DesignTokens  # noqa: E402
from autodeck.studio import (  # noqa: E402
    changelog,
    edits,
    engagement,
    models,
    render,
    serialise,
)

FIXTURE = ROOT / "tests" / "studio" / "fixtures" / "base_deck.json"
DEFAULT_TOKENS = ROOT / "config" / "tokens" / "dev.json"
DEFAULT_KNOWLEDGE_ROOT = ROOT / "knowledge"

EDIT_SLIDE = "s2"
EDIT_BLOCK = "heading"
EDIT_TEXT = "Cost per request fell 41% in six weeks"
EDIT_INSTRUCTION = "Tighten the slide two heading."
THREAD_ID = "demo"


@dataclass(frozen=True)
class DemoResult:
    """What `run_demo` observed; `main` prints it and derives the exit code."""

    lines: list[str]
    """The report lines, in the order of the docstring's expected output."""
    undo_exact: bool
    """`current.json` bytes after undo == bytes before the edit."""
    workspace_root: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """`--tokens PATH` (default `DEFAULT_TOKENS`), `--knowledge-root PATH` (default
    `DEFAULT_KNOWLEDGE_ROOT`), `--keep` (flag). Paths are returned as `Path`."""
    parser = argparse.ArgumentParser(description="Phase 0 of AutoDeck v3, end to end.")
    parser.add_argument("--tokens", type=Path, default=DEFAULT_TOKENS)
    parser.add_argument("--knowledge-root", type=Path, default=DEFAULT_KNOWLEDGE_ROOT)
    parser.add_argument("--keep", action="store_true")
    return parser.parse_args(argv)


def run_demo(*, tokens_path: Path, knowledge_root: Path, workspace_root: Path) -> DemoResult:
    """Run every step in `workspace_root` (which must not exist yet or be empty).

    1. Load the fixture with `serialise.load_artifact(FIXTURE.read_text("utf-8"))` and the
       tokens with `DesignTokens.load(tokens_path)`.
    2. `engagement.create_engagement(deck.client, deck.project, knowledge_root=...,
       workspace_root=...)`, then `create_artifact(deck)`.
    3. `render.render_artifact(store.load(), tokens=..., out_dir=store.paths.renders)`;
       add `report.timing_lines()` to the output. A `rendered=False` preview set is a line,
       not an exception.
    4. Read `store.paths.current` bytes; `edits.set_block_text(EDIT_SLIDE, EDIT_BLOCK,
       EDIT_TEXT)`; `store.apply(..., instruction=EDIT_INSTRUCTION, thread_id=THREAD_ID,
       layer="composition", model_id=models.HUMAN_MODEL_ID)`; add the entry id and its diff
       paths.
    5. Add `changelog.listing(store.changelog())`.
    6. `store.undo()`; compare `store.paths.current` bytes with step 4's; add the line.

    Exceptions from any step propagate (`main` turns them into exit 1).
    """
    deck = serialise.load_artifact(FIXTURE.read_text("utf-8"))
    tokens = DesignTokens.load(tokens_path)

    eng = engagement.create_engagement(
        deck.client,
        deck.project,
        knowledge_root=knowledge_root,
        workspace_root=workspace_root,
    )
    store = eng.create_artifact(deck)
    lines = [
        f"engagement: {eng.client} / {eng.project}",
        f"artifact:   {deck.id} ({len(deck.slides)} slides)",
    ]

    report = render.render_artifact(store.load(), tokens=tokens, out_dir=store.paths.renders)
    lines.extend(report.timing_lines())

    before = store.paths.current.read_bytes()
    edited = edits.set_block_text(
        store.load(), slide_id=EDIT_SLIDE, block_id=EDIT_BLOCK, text=EDIT_TEXT
    )
    entry = store.apply(
        edited,
        instruction=EDIT_INSTRUCTION,
        thread_id=THREAD_ID,
        layer="composition",
        model_id=models.HUMAN_MODEL_ID,
    )
    paths = ", ".join(item.path for item in entry.diff)
    lines.append(f"edit:       {entry.id} {paths}")

    lines.extend(f"log:        {line}" for line in changelog.listing(store.changelog()))

    undone = store.undo()
    exact = store.paths.current.read_bytes() == before
    verdict = "yes" if exact else "no"
    lines.append(
        f"undo:       {undone.id} undone; current.json byte-identical to before: {verdict}"
    )
    return DemoResult(lines=lines, undo_exact=exact, workspace_root=workspace_root)


def main(argv: list[str] | None = None) -> int:
    """Parse args, make a temporary workspace (`tempfile.mkdtemp(prefix="studio-demo-")`),
    `run_demo`, print each line, then print the workspace path if `--keep` or delete it.
    Return 0 if `undo_exact`, else 1; on an exception print `error: <exc>` to stderr and
    return 1 (the workspace is still deleted unless `--keep`)."""
    args = parse_args(argv)
    workspace = Path(tempfile.mkdtemp(prefix="studio-demo-"))
    try:
        try:
            result = run_demo(
                tokens_path=args.tokens,
                knowledge_root=args.knowledge_root,
                workspace_root=workspace,
            )
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        for line in result.lines:
            print(line)
        return 0 if result.undo_exact else 1
    finally:
        if args.keep:
            print(f"workspace:  {workspace}")
        else:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
