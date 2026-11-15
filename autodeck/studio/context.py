"""A thread's opening context, built from state and never from a transcript (plan §5.1, P2).

A new thread is given, and only given:

1. the engagement context: the client and project knowledge markdown (through v2's
   `assemble_context`, so v2's loader and namespace guard apply) and both memory files
   (through v2's `MemoryStore`, read only);
2. for each artifact: a compact view of its current state (`views.deck_outline`);
3. the recent change log of each artifact, including undone entries (what was rejected);
4. the proposals that were dismissed, accepted, or are still open;
5. what is provisional, stale or still open.

Nothing in this module reads a thread's files. That is the mechanism behind "the second
thread picks up with no transcript": whatever an earlier thread said is either in the
state above (a change it made, with the owner's instruction recorded on the entry; a
proposal it offered) or it is gone. A test pins it: deleting every `messages.jsonl` leaves
`build_context` unchanged.

The builder is split for exact testing. `gather_inputs` does the reading and returns a
plain `ContextInputs`; `render_context` is a pure function of those inputs whose output is
specified to the byte below.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autodeck.knowledge.context_assembler import assemble_context
from autodeck.knowledge.memory import MemoryScope, MemoryStore
from autodeck.studio.conversation import ProposalRecord
from autodeck.studio.design import DesignSystem
from autodeck.studio.diff import describe
from autodeck.studio.engagement import Engagement
from autodeck.studio.models import ChangeLog, DeckArtifact, Slide
from autodeck.studio.proposals import ProposalStore
from autodeck.studio.views import change_line, deck_outline, design_system_text, flat

RECENT_CHANGES = 15
"""How many change-log entries per artifact the context lists (newest first)."""

DIFF_LINES_PER_CHANGE = 3
"""How many `diff.describe` lines are shown under each listed entry."""

MemorySections = tuple[tuple[str, tuple[str, ...]], ...]
"""A memory file as `((section, (item, ...)), ...)`, in the file's fixed section order."""


@dataclass(frozen=True)
class Knowledge:
    """The curated knowledge, as v2's `AssembledContext` holds it."""

    project_md: str
    client_md: str
    value_prop_md: str
    engagement_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactState:
    """One artifact's current state and its whole change log."""

    deck: DeckArtifact
    log: ChangeLog
    system: DesignSystem | None = None
    """Phase 2-3: the stored design-system version the deck refers to, or None when the deck
    has no reference (it is in the provisional default system)."""


@dataclass(frozen=True)
class ContextInputs:
    """Everything the context is built from. Plain data, so `render_context` is pure."""

    client: str
    project: str
    title: str
    knowledge: Knowledge
    engagement_memory: MemorySections
    owner_memory: MemorySections
    artifacts: tuple[ArtifactState, ...]
    """In artifact id order."""
    proposals: tuple[ProposalRecord, ...]
    """In proposal id order."""


def gather_inputs(engagement: Engagement, *, owner_memory_path: Path) -> ContextInputs:
    """Read everything `render_context` needs, through the engagement's guards.

    * knowledge: `autodeck.knowledge.context_assembler.assemble_context(
      engagement.knowledge_root, client=..., project=...)`: its `project_md`, `client_md`,
      `value_prop_md` and `engagements` (as `engagement_notes`);
    * memory: `MemoryStore(engagement.knowledge_root, client=..., project=...,
      run_id="studio", owner_path=owner_memory_path)`; for each scope, `load(scope)` and
      take `sections` as `((name, tuple(items)), ...)` in the doc's section order. Nothing
      is written (no `add`, no audit line);
    * artifacts: for each id in `engagement.artifact_ids()`, `store = engagement.
      artifact_store(id)`, `ArtifactState(store.load(), store.changelog(), system)` where
      `system` is `load_deck_system(engagement, deck)` when the deck has a design-system
      reference, else None (Phase 2-3);
    * proposals: `ProposalStore(engagement).list()`;
    * title: `engagement.record.title`.

    Raises whatever those raise (v2's `KnowledgeError` / `ClientIsolationError`, the
    store's integrity errors): a context that cannot be built honestly is not built.
    """
    assembled = assemble_context(
        engagement.knowledge_root, client=engagement.client, project=engagement.project
    )
    knowledge = Knowledge(
        project_md=assembled.project_md,
        client_md=assembled.client_md,
        value_prop_md=assembled.value_prop_md,
        engagement_notes=tuple(assembled.engagements),
    )
    memory = MemoryStore(
        engagement.knowledge_root,
        client=engagement.client,
        project=engagement.project,
        run_id="studio",
        owner_path=owner_memory_path,
    )

    def sections(scope: MemoryScope) -> MemorySections:
        doc = memory.load(scope)
        return tuple((name, tuple(items)) for name, items in doc.sections.items())

    artifacts: list[ArtifactState] = []
    for artifact_id in engagement.artifact_ids():
        store = engagement.artifact_store(artifact_id)
        deck = store.load()
        system = load_deck_system(engagement, deck) if deck.design_system is not None else None
        artifacts.append(ArtifactState(deck, store.changelog(), system))
    return ContextInputs(
        client=engagement.client,
        project=engagement.project,
        title=engagement.record.title,
        knowledge=knowledge,
        engagement_memory=sections("engagement"),
        owner_memory=sections("owner"),
        artifacts=tuple(artifacts),
        proposals=tuple(ProposalStore(engagement).list()),
    )


def load_deck_system(engagement: Engagement, deck: DeckArtifact) -> DesignSystem:
    """Phase 2-3: the stored design-system version `deck.design_system` names:
    `design.DesignSystemStore(engagement).load(ref.id, ref.version)` (no base tokens: a
    reference always names a stored version). Its errors propagate
    (`DesignSystemNotFoundError` for a dangling reference: a context that cannot be built
    honestly is not built)."""
    raise NotImplementedError


def slide_composition_item(
    artifact_id: str, index: int, slide: Slide, deck: DeckArtifact
) -> str | None:
    """Phase 2-3: the open item for a slide that has a brief, or None when it is designed
    and fresh. By `models.composition_status(slide, models.effective_system(deck))`:
    undesigned → `"<a>: slide <i> (<id>) is not designed yet"`; stale → `"<a>: slide <i>
    (<id>) is stale: <reasons joined by "; ">"`; failed → `"<a>: slide <i> (<id>) failed to
    compose: <views.clip(first finding, 120), or "no findings">"`; fresh → None."""
    raise NotImplementedError


def design_system_item(artifact_id: str, deck: DeckArtifact) -> str | None:
    """Phase 2-3: the deck-level design item, listed only for a deck with at least one
    slide that has a brief (decks made before Phase 2-3 are unchanged): no reference →
    `"<a>: the design system is the provisional default (no concept decided)"`; a reference
    whose marker is not `decided` → `"<a>: the design system is <marker>"`; else None."""
    raise NotImplementedError


def is_returning(inputs: ContextInputs) -> bool:
    """True when there is state to recap: at least one artifact or one proposal."""
    return bool(inputs.artifacts or inputs.proposals)


def open_items(inputs: ContextInputs) -> list[str]:
    """The "Provisional, stale and open" list, in this order.

    For each artifact (id order), with `a` its id and `m` a marker:

    * `"<a>: no brief yet"` when the brief is None, else `"<a>: the brief is <m>"` when
      its marker is not `decided`;
    * `"<a>: no storyline yet"` when it has no points, else `"<a>: the storyline is <m>"`
      when its marker is not `decided`;
    * `"<a>: no design concept yet"`, or `"<a>: the design concept is <m>"` likewise;
    * Phase 2-3: `design_system_item(a, deck)` when not None (only for decks with a
      briefed slide);
    * `"<a>: no slides yet"` when there are none; otherwise for each slide i (1-based):
      `"<a>: slide <i> (<id>) is <m>"` when its marker is not `decided`, then, for a slide
      with a brief, `slide_composition_item(...)` when not None, and for a slide without
      one `"<a>: slide <i> (<id>) has no layout yet"` when its layout is None;
    * for each storyline point (in order) that no slide serves:
      `"<a>: storyline point <point id> is not served by any slide"`.

    Then each open proposal (id order): `"proposal <id> is open: <summary>"`.
    """
    items: list[str] = []
    for state in inputs.artifacts:
        deck = state.deck
        a = deck.id
        if deck.brief is None:
            items.append(f"{a}: no brief yet")
        elif deck.brief.marker != "decided":
            items.append(f"{a}: the brief is {deck.brief.marker}")
        if not deck.storyline.points:
            items.append(f"{a}: no storyline yet")
        elif deck.storyline.marker != "decided":
            items.append(f"{a}: the storyline is {deck.storyline.marker}")
        if deck.design_concept is None:
            items.append(f"{a}: no design concept yet")
        elif deck.design_concept.marker != "decided":
            items.append(f"{a}: the design concept is {deck.design_concept.marker}")
        if any(slide.brief is not None for slide in deck.slides):
            design_item = design_system_item(a, deck)
            if design_item is not None:
                items.append(design_item)
        if not deck.slides:
            items.append(f"{a}: no slides yet")
        for i, slide in enumerate(deck.slides, start=1):
            if slide.marker != "decided":
                items.append(f"{a}: slide {i} ({slide.id}) is {slide.marker}")
            if slide.brief is not None:
                composition = slide_composition_item(a, i, slide, deck)
                if composition is not None:
                    items.append(composition)
            elif slide.layout is None:
                items.append(f"{a}: slide {i} ({slide.id}) has no layout yet")
        served = {point for slide in deck.slides for point in slide.serves}
        for point in deck.storyline.points:
            if point.id not in served:
                items.append(f"{a}: storyline point {point.id} is not served by any slide")
    for proposal in inputs.proposals:
        if proposal.status == "open":
            items.append(f"proposal {proposal.id} is open: {proposal.summary}")
    return items


def _memory_block(sections: MemorySections) -> str:
    groups = [
        "\n".join([f"{name}:", *(f"- {item}" for item in items)])
        for name, items in sections
        if items
    ]
    return "\n\n".join(groups) if groups else "(nothing yet)"


def _change_block(log: ChangeLog, recent_changes: int) -> str:
    if not log.entries:
        return "None."
    shown = log.entries[::-1][: max(recent_changes, 0)]
    lines: list[str] = []
    for entry in shown:
        lines.append(f"- {change_line(entry)}")
        described = describe(entry.diff)
        lines.extend(f"    {line}" for line in described[:DIFF_LINES_PER_CHANGE])
        if len(described) > DIFF_LINES_PER_CHANGE:
            lines.append(f"    (+{len(described) - DIFF_LINES_PER_CHANGE} more)")
    omitted = len(log.entries) - len(shown)
    if omitted > 0:
        lines.append(f"- ({omitted} earlier changes not shown)")
    return "\n".join(lines)


PROPOSAL_TERMS = (
    "Statuses:\n"
    "- accepted: the owner picked one option and it was applied.\n"
    "  The options they did not pick were not chosen; that is not a dismissal.\n"
    "- dismissed: the owner turned down every option; nothing was applied.\n"
    "- open: not yet decided."
)
"""The lines under `# Proposals` that fix what the three statuses mean."""


def _proposal_block(group: list[ProposalRecord]) -> str:
    lines: list[str] = []
    for p in group:
        where = p.artifact_id if p.artifact_id is not None else "no artifact"
        status = f"accepted: option {p.chosen}" if p.status == "accepted" else p.status
        lines.append(f"- {p.id} ({where}, thread {p.thread_id}) [{status}]: {p.summary}")
        if p.status == "accepted":
            chosen = next(o for o in p.options if o.id == p.chosen)
            lines.append(f"  - chosen: {chosen.id}. {chosen.label}")
            others = [f"{o.id}. {o.label}" for o in p.options if o.id != chosen.id]
            if others:
                lines.append(f"  - not chosen: {'; '.join(others)}")
            continue
        for o in p.options:
            line = f"  - {o.id}. {o.label}: {flat(o.text)}"
            if o.slides:
                n = len(o.slides)
                line += f" ({n} candidate {'slide' if n == 1 else 'slides'})"
            lines.append(line)
    return "\n".join(lines)


def render_context(inputs: ContextInputs, *, recent_changes: int = RECENT_CHANGES) -> str:
    """The opening context as markdown. Pure. Exact format (blocks joined by one blank
    line, i.e. `"\\n\\n"`; the whole text ends with exactly one `"\\n"`; every markdown
    body below is `.strip()`ped first):

    ```
    # Engagement

    Client: <client> · Project: <project>            (` · <title>` appended when title
                                                       is not blank)

    ## Client and project knowledge

    ### Project: <project>

    <project_md>

    ### Client: <client>

    <client_md>

    ### Client value proposition

    <value_prop_md>

    ### Engagement note <i>                           (one block pair per note, i from 1)

    <note>

    ## Memory (read-only)

    ### This engagement

    <memory block of engagement_memory>

    ### How the owner works

    <memory block of owner_memory>

    # Artifacts

    <"None yet." when there is no artifact; otherwise, per artifact:>

    ## <artifact id>

    <views.deck_outline(deck)>

    ### Recent changes (newest first)

    <change block>

    ### Design system                                (Phase 2-3: only when the artifact
                                                      state has a stored system)
    <views.design_system_text(system)>

    # Proposals

    <"None." when there is no proposal; otherwise `PROPOSAL_TERMS`, then for each
     non-empty group in the order Dismissed, Accepted, Open:>

    ## <Dismissed | Accepted | Open>

    <proposal block>

    # Provisional, stale and open

    <"Nothing." when open_items is empty; else one "- <item>" line per item>
    ```

    A **memory block** is, for each section that has items, the line `<section>:` followed
    by one `- <item>` line per item, sections separated by one blank line; or
    `(nothing yet)` when no section has items.

    A **change block** lists the last `recent_changes` entries of the log by append order,
    newest first. Each is the line `- <views.change_line(entry)>` followed by up to
    `DIFF_LINES_PER_CHANGE` lines `    <line>` (four spaces) from `diff.describe(diff)`,
    and, when more describe lines exist, `    (+<k> more)`. Entries are separated by a
    newline only (no blank line). When older entries were left out, a last line
    `- (<k> earlier changes not shown)`. `None.` when the log is empty.

    A **proposal block** has, per proposal in the group (id order), a first line
    `- <id> (<artifact id, or "no artifact">, thread <thread id>) [<status>]: <summary>`
    where `<status>` is `dismissed`, `open` or `accepted: option <X>`, then:
    Dismissed and Open list every option as `  - <option id>. <label>: <flat(text)>`
    with ` (<k> candidate slide|slides)` appended when it has slides; Accepted has the
    line `  - chosen: <option id>. <label>` and, when there were other options, the line
    `  - not chosen: <id>. <label>; <id>. <label>` (they were passed over, not dismissed).
    Lines are separated by a newline only.
    """
    blocks: list[str] = ["# Engagement"]
    header = f"Client: {inputs.client} · Project: {inputs.project}"
    if inputs.title.strip():
        header += f" · {inputs.title}"
    blocks.append(header)

    knowledge = inputs.knowledge
    blocks.append("## Client and project knowledge")
    blocks.extend(
        [
            f"### Project: {inputs.project}",
            knowledge.project_md.strip(),
            f"### Client: {inputs.client}",
            knowledge.client_md.strip(),
            "### Client value proposition",
            knowledge.value_prop_md.strip(),
        ]
    )
    for i, note in enumerate(knowledge.engagement_notes, start=1):
        blocks.extend([f"### Engagement note {i}", note.strip()])

    blocks.extend(
        [
            "## Memory (read-only)",
            "### This engagement",
            _memory_block(inputs.engagement_memory),
            "### How the owner works",
            _memory_block(inputs.owner_memory),
            "# Artifacts",
        ]
    )
    if not inputs.artifacts:
        blocks.append("None yet.")
    for state in inputs.artifacts:
        blocks.extend(
            [
                f"## {state.deck.id}",
                deck_outline(state.deck),
                "### Recent changes (newest first)",
                _change_block(state.log, recent_changes),
            ]
        )
        if state.system is not None:
            blocks.extend(["### Design system", design_system_text(state.system)])

    blocks.append("# Proposals")
    if not inputs.proposals:
        blocks.append("None.")
    else:
        blocks.append(PROPOSAL_TERMS)
    for status, heading in (
        ("dismissed", "Dismissed"),
        ("accepted", "Accepted"),
        ("open", "Open"),
    ):
        group = [p for p in inputs.proposals if p.status == status]
        if group:
            blocks.extend([f"## {heading}", _proposal_block(group)])

    blocks.append("# Provisional, stale and open")
    items = open_items(inputs)
    blocks.append("\n".join(f"- {item}" for item in items) if items else "Nothing.")
    return "\n\n".join(blocks) + "\n"


def build_context(
    engagement: Engagement,
    *,
    owner_memory_path: Path,
    recent_changes: int = RECENT_CHANGES,
) -> str:
    """`render_context(gather_inputs(engagement, owner_memory_path=...),
    recent_changes=recent_changes)`."""
    return render_context(
        gather_inputs(engagement, owner_memory_path=owner_memory_path),
        recent_changes=recent_changes,
    )
