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

from autodeck.studio.conversation import ProposalRecord
from autodeck.studio.engagement import Engagement
from autodeck.studio.models import ChangeLog, DeckArtifact

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
      artifact_store(id)`, `ArtifactState(store.load(), store.changelog())`;
    * proposals: `ProposalStore(engagement).list()`;
    * title: `engagement.record.title`.

    Raises whatever those raise (v2's `KnowledgeError` / `ClientIsolationError`, the
    store's integrity errors): a context that cannot be built honestly is not built.
    """
    raise NotImplementedError


def is_returning(inputs: ContextInputs) -> bool:
    """True when there is state to recap: at least one artifact or one proposal."""
    raise NotImplementedError


def open_items(inputs: ContextInputs) -> list[str]:
    """The "Provisional, stale and open" list, in this order.

    For each artifact (id order), with `a` its id and `m` a marker:

    * `"<a>: no brief yet"` when the brief is None, else `"<a>: the brief is <m>"` when
      its marker is not `decided`;
    * `"<a>: no storyline yet"` when it has no points, else `"<a>: the storyline is <m>"`
      when its marker is not `decided`;
    * `"<a>: no design concept yet"`, or `"<a>: the design concept is <m>"` likewise;
    * `"<a>: no slides yet"` when there are none; otherwise for each slide i (1-based):
      `"<a>: slide <i> (<id>) is <m>"` when its marker is not `decided`, then
      `"<a>: slide <i> (<id>) has no layout yet"` when its layout is None;
    * for each storyline point (in order) that no slide serves:
      `"<a>: storyline point <point id> is not served by any slide"`.

    Then each open proposal (id order): `"proposal <id> is open: <summary>"`.
    """
    raise NotImplementedError


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

    # Proposals

    <"None." when there is no proposal; otherwise, for each non-empty group in the order
     Dismissed, Accepted, Open:>

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
    `- <id> (<artifact id, or "no artifact">, thread <thread id>): <summary>`, then:
    Dismissed and Open list every option as `  - <option id>. <label>: <flat(text)>`
    with ` (<k> candidate slide|slides)` appended when it has slides; Accepted adds the
    one line `  - chose <option id>. <label>`. Lines are separated by a newline only.
    """
    raise NotImplementedError


def build_context(
    engagement: Engagement,
    *,
    owner_memory_path: Path,
    recent_changes: int = RECENT_CHANGES,
) -> str:
    """`render_context(gather_inputs(engagement, owner_memory_path=...),
    recent_changes=recent_changes)`."""
    raise NotImplementedError
