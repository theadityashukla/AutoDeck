"""Give a gate the artifact it covers.

An approval is bound to an artifact (A7), so a test that wants a gate approved has to make
the artifact first. One helper, used by every test that needs an approved gate, so the
"what does this gate cover" knowledge lives in a single place — the same one
`Orchestrator.current_fingerprint` reads.
"""

from __future__ import annotations

import zipfile

from autodeck.ir.models import Deck, DeckBrief, KeyMessage
from autodeck.pipeline.orchestrator import Gate, Orchestrator


def seed_artifact(orchestrator: Orchestrator, gate: Gate, *, marker: str = "") -> None:
    """Write whatever `gate` covers. `marker` makes two seeds of the same gate differ."""
    run_id = orchestrator.run_id
    if gate is Gate.BRIEF:
        orchestrator.ir.save_brief(
            DeckBrief(
                run_id=run_id,
                objective=f"Decide something. {marker}",
                audience="CTO",
                key_messages=[
                    KeyMessage(id="km1", text="A message.", evidence_status="supported")
                ],
                approved_by="tester",
                version=orchestrator.ir.next_brief_version(),
            )
        )
    elif gate is Gate.FINAL_RENDER:
        with zipfile.ZipFile(orchestrator.paths.deck_pptx, "w") as archive:
            archive.writestr("ppt/presentation.xml", f"<p>{marker}</p>")
    else:
        stage = "outline" if gate is Gate.OUTLINE else "validate"
        deck = Deck(
            run_id=run_id,
            project="p",
            client="c",
            audience=f"CTO {marker}",
            version=orchestrator.ir.next_version(),
            slides=[],
            theme_ref="config/tokens/dev.json",
            component_lib_version="test",
        )
        orchestrator.run_stage(stage, lambda: f"wrote {orchestrator.save_ir(deck)}", force=True)
