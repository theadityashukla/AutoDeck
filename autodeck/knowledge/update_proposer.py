"""Post-engagement knowledge updates, proposed as a diff and never written (task 4.7).

After a run finishes, some of what it established is worth keeping: a claim that was checked
against a corpus document, the headlines the person kept, the terms and people the engagement
memory learned. This module reads **one finished run and its own client's knowledge** (A4) and
writes **a unified diff against `knowledge/`**. It never touches the knowledge folder. A person
reads the diff and, if they agree, runs `autodeck knowledge apply FILE --yes-i-reviewed-this`
(A7: there is no path that writes knowledge without a human applying a file they have read).

## What is proposed

1. **Project `claims.md` additions.** Claims in the run's latest IR with verdict `supported`,
   a single citation, and that citation in a *corpus* document. Citations to `conversation--`,
   `transcript--` and `client-deck--` documents are the client's or the run's own, so they never
   enter the project tier, which is shared across clients (D8, A4). A claim that names a client
   folder is skipped for the same reason. Already-present claims (same `doc_id` and quote) are
   not proposed twice. The text is the exact `claims.md` format the loader parses.
2. **A client engagement note**, `clients/<c>/engagements/<date>-<run>.md`: deterministic text
   from the brief, the final headlines and the meeting notes' decisions. No model call.
3. **Approved headers** as `exemplar_headers` in `clients/<c>/style/headers.proposed.yaml`.
   `HeaderStyleProfile` forbids unknown fields, so adding the list to `headers.yaml` would stop
   that file loading; the proposal goes to a sibling file the profile loader does not read.
4. **Engagement memory consolidation**: this run's Terms and People lines from
   `clients/<c>/memory/<project>.md`, under a `## Learned` section of `client.md`. Never a
   figure (the owner-memory figure rule), and never Decisions or Open actions, which are about
   one engagement's moment rather than the client.

Every proposed addition carries its provenance (run, slide, block, verdict) in a comment in the
text it adds, so the diff body itself says where each line came from.

## The patch format

Git-style (`diff --git a/knowledge/<path> b/knowledge/<path>`) so `git apply` also works from
the repository root. A `#` preamble names the run, client and project. `apply_patch` reads the
preamble and refuses any path other than the allow-list for exactly that client and project,
so a patch edited to reach another client's folder, or anything outside `knowledge/`, fails.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from autodeck.design.headers.flow import header_slot_name
from autodeck.design.headers.profile import HeaderProfileError, HeaderStyleProfile
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import (
    CLIENT_DECK_DOC_PREFIX,
    CONVERSATION_DOC_PREFIX,
    TRANSCRIPT_DOC_PREFIX,
    Block,
    Deck,
    Slide,
)
from autodeck.ir.store import IRStore, IRStoreError
from autodeck.knowledge.context_assembler import ClientNamespace
from autodeck.knowledge.loader import (
    CLIENTS_DIR,
    PROJECTS_DIR,
    KnowledgeError,
    KnowledgeLoader,
    parse_claims_markdown,
)
from autodeck.knowledge.memory import SMALL_COUNT, MemoryDoc, _bare

KNOWLEDGE_DIR = "knowledge"
"""The directory name every path in a patch starts with (after `a/` or `b/`)."""

CLIENT_ONLY_PREFIXES = (CONVERSATION_DOC_PREFIX, TRANSCRIPT_DOC_PREFIX, CLIENT_DECK_DOC_PREFIX)
"""Documents that belong to one client or one run; never evidence for the shared tier."""

LEARNED_SECTIONS = ("Terms", "People")
LEARNED_HEADING = "## Learned"
HEADERS_PROPOSED = "headers.proposed.yaml"

_FIGURE = re.compile(r"\d+(?:[.,]\d+)*\s*%?")
_CURRENCY = re.compile(r"[$€£¥]")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class UpdateProposalError(KnowledgeError):
    """A proposal could not be made, or a patch was refused."""


@dataclass
class FileChange:
    """One file's before and after. `old` is None for a file the patch creates."""

    path: str
    """Relative to the knowledge root, forward slashes."""
    old: str | None
    new: str
    notes: list[str] = field(default_factory=list)


@dataclass
class Proposal:
    run_id: str
    client: str
    project: str
    changes: list[FileChange] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    """Things considered and left out, each with the reason. Shown, never silent."""

    def render(self) -> str:
        return render_patch(self)


# ---------------------------------------------------------------------------
# Proposing
# ---------------------------------------------------------------------------


def propose_updates(
    runs_root: Path,
    run_id: str,
    knowledge_root: Path,
    *,
    today: date | None = None,
) -> Proposal:
    """Read one finished run and propose updates to its own client's knowledge.

    Reads `knowledge_root` and the run; writes nothing.

    Raises:
        UpdateProposalError: the run has no IR, or its client or project has no folder.
    """
    knowledge_root = Path(knowledge_root)
    store = IRStore(runs_root, run_id)
    try:
        deck = store.load()
    except IRStoreError as exc:
        raise UpdateProposalError(str(exc)) from exc
    loader = KnowledgeLoader(knowledge_root)
    if deck.client not in loader.client_names():
        raise UpdateProposalError(
            f"run {run_id!r} is for client {deck.client!r}, which has no folder under "
            f"{knowledge_root / CLIENTS_DIR}"
        )
    if deck.project not in loader.project_names():
        raise UpdateProposalError(
            f"run {run_id!r} is for project {deck.project!r}, which has no folder under "
            f"{knowledge_root / PROJECTS_DIR}"
        )
    proposal = Proposal(run_id=run_id, client=deck.client, project=deck.project)
    namespace = ClientNamespace(deck.client, knowledge_root)
    run_root = store.paths.root
    day = (today or date.today()).isoformat()

    for change in (
        _claims_change(deck, knowledge_root, loader, proposal),
        _engagement_change(deck, run_root, knowledge_root, namespace, day, proposal),
        _headers_change(deck, knowledge_root, namespace, proposal),
        _learned_change(deck, knowledge_root, namespace, proposal),
    ):
        if change is not None and change.old != change.new:
            proposal.changes.append(change)
    return proposal


def _rel(*parts: str) -> str:
    return "/".join(parts)


def _read(knowledge_root: Path, rel: str) -> str | None:
    path = knowledge_root / rel
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


# -- 1. claims.md -----------------------------------------------------------------


def _claims_change(
    deck: Deck, knowledge_root: Path, loader: KnowledgeLoader, proposal: Proposal
) -> FileChange | None:
    rel = _rel(PROJECTS_DIR, deck.project, "claims.md")
    old = _read(knowledge_root, rel)
    try:
        existing = parse_claims_markdown(old or "", source=rel)
    except KnowledgeError as exc:
        proposal.skipped.append(f"claims: {rel} does not parse ({exc}); no claims proposed")
        return None
    have = {(c.doc_id, _norm(c.quote)) for c in existing}
    client_names = [name.casefold() for name in loader.client_names()]
    blocks: list[str] = []
    for site in deck.claim_sites():
        claim = site.claim
        where = f"slide {site.slide_id} block {site.block_id}"
        if claim.verdict != "supported":
            if claim.verdict != "unverified" or claim.citations:
                proposal.skipped.append(f"claim at {where}: verdict is {claim.verdict}")
            continue
        if claim.derivation is not None or len(claim.citations) != 1:
            proposal.skipped.append(
                f"claim at {where}: not a single-citation claim (a derived or multi-source "
                "claim is not a pre-verified quote)"
            )
            continue
        citation = claim.citations[0]
        if citation.doc_id.startswith(CLIENT_ONLY_PREFIXES):
            proposal.skipped.append(
                f"claim at {where}: cites {citation.doc_id}, which is client- or run-specific "
                "and may not enter the shared project tier (D8, A4)"
            )
            continue
        lowered = claim.text.casefold()
        named = [n for n in client_names if re.search(rf"\b{re.escape(n)}\b", lowered)]
        if named:
            proposal.skipped.append(
                f"claim at {where}: names a client ({', '.join(named)}); the project tier is "
                "shared"
            )
            continue
        key = (citation.doc_id, _norm(citation.quote))
        if key in have:
            continue
        have.add(key)
        entry = {
            "claim": claim.text,
            "doc_id": citation.doc_id,
            "page": citation.page,
            "quote": citation.quote,
        }
        body = yaml.safe_dump(
            entry, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10_000
        ).rstrip("\n")
        blocks.append(
            f"<!-- proposed from run {proposal.run_id}, slide {site.slide_id}, block "
            f"{site.block_id}, verdict {claim.verdict} -->"
            f"\n\n```yaml\n{body}\n```"
        )
    if not blocks:
        return None
    base = old if old is not None else f"# Claims: {deck.project}\n"
    new = base.rstrip("\n") + "\n\n" + "\n\n".join(blocks) + "\n"
    parse_claims_markdown(new, source=rel)  # a proposal that does not parse is a bug here
    return FileChange(rel, old, new)


# -- 2. engagement note -----------------------------------------------------------


def _text_of(block: Block) -> str:
    if block.claim is not None:
        return block.claim.text
    return block.text or ""


def _headline(slide: Slide, tokens: DesignTokens | None) -> Block | None:
    """The block a reader takes as the slide's header, or None."""
    name = header_slot_name(slide.component, tokens) if tokens is not None else None
    if name is not None:
        found = next((b for b in slide.blocks if b.slot == name), None)
        if found is not None:
            return found
    return next(
        (b for b in slide.blocks if b.slot in ("headline", "title", "takeaway")),
        None,
    )


def _tokens(deck: Deck) -> DesignTokens | None:
    try:
        return DesignTokens.load(Path(deck.theme_ref))
    except Exception:
        return None


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _brief_facts(run_root: Path, run_id: str) -> tuple[str, str, list[str]]:
    """`(objective, audience, key message texts)` from the run's brief, or blanks."""
    store = IRStore(run_root.parent, run_id)
    try:
        brief = store.load_brief()
        return brief.objective, brief.audience, [m.text for m in brief.key_messages]
    except Exception:
        pass
    data = _load_json(run_root / "draft_brief.json")
    if isinstance(data, dict):
        messages = [
            str(m.get("text", "")) for m in data.get("key_messages", []) if isinstance(m, dict)
        ]
        return str(data.get("objective", "")), str(data.get("audience", "")), messages
    return "", "", []


def _decisions(run_root: Path) -> list[str]:
    data = _load_json(run_root / "meeting" / "notes.json")
    if not isinstance(data, dict):
        return []
    items = (data.get("sections") or {}).get("Decisions") or []
    return [
        str(i.get("text", "")).strip() for i in items if isinstance(i, dict) and i.get("text")
    ]


def _engagement_change(
    deck: Deck,
    run_root: Path,
    knowledge_root: Path,
    namespace: ClientNamespace,
    day: str,
    proposal: Proposal,
) -> FileChange | None:
    rel = _rel(CLIENTS_DIR, deck.client, "engagements", f"{day}-{deck.run_id}.md")
    namespace.guard(knowledge_root / rel)
    old = _read(knowledge_root, rel)
    if old is not None:
        proposal.skipped.append(f"engagement note: {rel} already exists; left as it is")
        return None
    objective, audience, messages = _brief_facts(run_root, deck.run_id)
    tokens = _tokens(deck)
    lines = [
        f"# Engagement: {deck.run_id} ({day})",
        "",
        f"<!-- proposed from run {deck.run_id}, IR v{deck.version}; deterministic summary, "
        "no model call -->",
        "",
        f"- Client: {deck.client}",
        f"- Project: {deck.project}",
        f"- Audience: {audience or deck.audience}",
    ]
    if objective:
        lines.append(f"- Deck objective: {objective}")
    if messages:
        lines += ["", "## Key messages", "", *[f"- {m}" for m in messages]]
    heads = []
    for slide in deck.slides:
        block = _headline(slide, tokens)
        text = _text_of(block).strip() if block is not None else ""
        if text:
            heads.append(f"- {slide.id}: {text}")
    if heads:
        lines += ["", "## Slide headlines (final draft)", "", *heads]
    decided = _decisions(run_root)
    if decided:
        lines += ["", "## Decided in the meeting", "", *[f"- {d}" for d in decided]]
    return FileChange(rel, None, "\n".join(lines) + "\n")


# -- 3. approved headers ------------------------------------------------------------


def _header_problem(text: str, profile: HeaderStyleProfile) -> str | None:
    words = text.split()
    if not words:
        return "empty"
    if len(words) > profile.max_words:
        return f"{len(words)} words, over the {profile.max_words}-word budget"
    if not profile.terminal_punctuation and text.rstrip().endswith((".", "!")):
        return "ends in punctuation the style disallows"
    hit = [w for w in profile.avoid if w.lower() in text.lower()]
    if hit:
        return f"uses avoided wording {hit}"
    if profile.numbers_in_headers == "forbidden" and any(c.isdigit() for c in text):
        return "contains a number and the style forbids numbers in headers"
    if (
        profile.sentence_case
        and len(words) > 3
        and all(w[:1].isupper() for w in words if w[:1].isalpha())
    ):
        return "is in Title Case and the style is sentence case"
    return None


def _headers_change(
    deck: Deck, knowledge_root: Path, namespace: ClientNamespace, proposal: Proposal
) -> FileChange | None:
    style_dir = _rel(CLIENTS_DIR, deck.client, "style")
    namespace.guard(knowledge_root / style_dir)
    raw = _read(knowledge_root, _rel(style_dir, "headers.yaml"))
    try:
        loaded = yaml.safe_load(raw) if raw else None
        profile = HeaderStyleProfile.from_mapping(
            loaded if isinstance(loaded, dict) else None, source="headers.yaml"
        )
    except (HeaderProfileError, yaml.YAMLError) as exc:
        proposal.skipped.append(f"headers: the client's headers.yaml does not load ({exc})")
        return None
    rel = _rel(style_dir, HEADERS_PROPOSED)
    old = _read(knowledge_root, rel)
    taken: set[str] = set()
    if old:
        try:
            existing = yaml.safe_load(old)
        except yaml.YAMLError as exc:
            proposal.skipped.append(f"headers: {rel} does not parse ({exc})")
            return None
        if not isinstance(existing, dict) or set(existing) - {"exemplar_headers"}:
            proposal.skipped.append(
                f"headers: {rel} has content other than exemplar_headers; not extended"
            )
            return None
        taken = {_norm(str(h)) for h in existing.get("exemplar_headers") or []}
    tokens = _tokens(deck)
    additions: list[str] = []
    for slide in deck.slides:
        block = _headline(slide, tokens)
        if block is None:
            continue
        text = _text_of(block).strip()
        if not text:
            continue
        if slide.headline_check is not None and slide.headline_check.verdict == "overstates":
            proposal.skipped.append(
                f"header of slide {slide.id}: judged to overstate its claims"
            )
            continue
        verdict = "n/a"
        if block.claim is not None:
            verdict = block.claim.verdict
            if verdict != "supported":
                proposal.skipped.append(
                    f"header of slide {slide.id}: claim verdict is {verdict}"
                )
                continue
        problem = _header_problem(text, profile)
        if problem:
            proposal.skipped.append(f"header of slide {slide.id}: {problem}")
            continue
        if _norm(text) in taken:
            continue
        taken.add(_norm(text))
        additions.append(
            f"  # run {proposal.run_id}, slide {slide.id}, verdict {verdict}\n"
            f"  - {json.dumps(text, ensure_ascii=False)}"
        )
    if not additions:
        return None
    if old:
        new = old.rstrip("\n") + "\n" + "\n".join(additions) + "\n"
    else:
        new = (
            "# Headlines the person kept. Proposed here, not in headers.yaml, because "
            "HeaderStyleProfile\n# forbids unknown fields; move them if the profile gains "
            "an exemplar field.\nexemplar_headers:\n" + "\n".join(additions) + "\n"
        )
    return FileChange(rel, old, new)


# -- 4. memory consolidation ----------------------------------------------------------


def _has_figure(text: str) -> bool:
    if _CURRENCY.search(text):
        return True
    for match in _FIGURE.finditer(text):
        token = match.group(0).strip()
        digits = token.rstrip("%").replace(",", "")
        if "%" in token or "." in digits or float(digits) > SMALL_COUNT:
            return True
    return False


def _learned_change(
    deck: Deck, knowledge_root: Path, namespace: ClientNamespace, proposal: Proposal
) -> FileChange | None:
    memory_rel = _rel(CLIENTS_DIR, deck.client, "memory", f"{deck.project}.md")
    namespace.guard(knowledge_root / memory_rel)
    memory_text = _read(knowledge_root, memory_rel)
    if not memory_text:
        return None
    doc = MemoryDoc.parse(
        memory_text,
        ("Terms", "People", "Open actions", "Decisions", "Deck preferences"),
        "memory",
    )
    tag = f"(run {deck.run_id})"
    rel = _rel(CLIENTS_DIR, deck.client, "client.md")
    old = _read(knowledge_root, rel)
    if old is None:
        proposal.skipped.append("memory: the client has no client.md to extend")
        return None
    present = {_norm(line.lstrip("- ").split("<!--")[0]) for line in old.splitlines()}
    bullets: list[str] = []
    for section in LEARNED_SECTIONS:
        for item in doc.sections.get(section, []):
            if not item.rstrip().endswith(tag):
                continue
            text = _bare(item)
            if _has_figure(text):
                proposal.skipped.append(f"memory {section}: {text!r} states a figure")
                continue
            if _norm(text) in present:
                continue
            present.add(_norm(text))
            bullets.append(f"- {text} <!-- run {deck.run_id}, memory {section} -->")
    if not bullets:
        return None
    lines = old.rstrip("\n").split("\n")
    heading = next(
        (i for i, line in enumerate(lines) if line.strip().lower() == LEARNED_HEADING.lower()),
        None,
    )
    if heading is None:
        new_lines = [*lines, "", LEARNED_HEADING, "", *bullets]
    else:
        end = next(
            (i for i in range(heading + 1, len(lines)) if lines[i].startswith("#")), len(lines)
        )
        while end > heading + 1 and not lines[end - 1].strip():
            end -= 1
        new_lines = [*lines[:end], *bullets, *lines[end:]]
    return FileChange(rel, old, "\n".join(new_lines) + "\n")


# ---------------------------------------------------------------------------
# The patch
# ---------------------------------------------------------------------------


def _file_diff(change: FileChange) -> str:
    path = f"{KNOWLEDGE_DIR}/{change.path}"
    old_lines = [] if change.old is None else change.old.rstrip("\n").split("\n")
    if change.old == "":
        old_lines = []
    new_lines = change.new.rstrip("\n").split("\n")
    body = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="/dev/null" if change.old is None else f"a/{path}",
            tofile=f"b/{path}",
            n=3,
            lineterm="",
        )
    )
    head = [f"diff --git a/{path} b/{path}"]
    if change.old is None:
        head.append("new file mode 100644")
    return "\n".join([*head, *body]) + "\n"


def render_patch(proposal: Proposal) -> str:
    """The proposal as one git-style patch, with a `#` preamble `apply_patch` reads."""
    out = [
        "# autodeck knowledge update proposal (task 4.7). Proposed, not applied.",
        f"# run: {proposal.run_id}",
        f"# client: {proposal.client}",
        f"# project: {proposal.project}",
        "# Read it, then: autodeck knowledge apply THIS-FILE --yes-i-reviewed-this",
    ]
    out += [f"# left out: {line}" for line in proposal.skipped]
    if not proposal.changes:
        out.append("# nothing to propose")
    return "\n".join(out) + "\n" + "".join(_file_diff(c) for c in proposal.changes)


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


@dataclass
class _FilePatch:
    path: str
    is_new: bool
    hunks: list[tuple[int, int, list[str]]]
    """`(old_start, old_count, lines)`; lines keep their one-character prefix."""


def _preamble(lines: list[str]) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in lines:
        if line.startswith("diff --git"):
            break
        match = re.match(r"^# (run|client|project): (.+)$", line)
        if match:
            meta[match.group(1)] = match.group(2).strip()
    return meta


def _parse_patch(text: str) -> tuple[dict[str, str], list[_FilePatch]]:
    lines = text.split("\n")
    meta = _preamble(lines)
    patches: list[_FilePatch] = []
    i = 0
    while i < len(lines) and not lines[i].startswith("diff --git"):
        i += 1
    while i < len(lines):
        header = lines[i]
        match = re.match(r"^diff --git a/(\S+) b/(\S+)$", header)
        if not match or match.group(1) != match.group(2):
            raise UpdateProposalError(f"unreadable patch header: {header!r}")
        path = match.group(2)
        i += 1
        is_new = False
        while i < len(lines) and not lines[i].startswith(("@@", "diff --git")):
            if lines[i].startswith("new file mode"):
                is_new = True
            elif lines[i].startswith(("deleted file", "rename ", "copy ")):
                raise UpdateProposalError(f"{path}: deletes and renames are not applied")
            i += 1
        hunks: list[tuple[int, int, list[str]]] = []
        while i < len(lines) and lines[i].startswith("@@"):
            hm = _HUNK.match(lines[i])
            if not hm:
                raise UpdateProposalError(f"{path}: unreadable hunk header {lines[i]!r}")
            old_start, old_count = int(hm.group(1)), int(hm.group(2) or 1)
            new_count = int(hm.group(4) or 1)
            i += 1
            body: list[str] = []
            seen_old = seen_new = 0
            while i < len(lines) and (seen_old < old_count or seen_new < new_count):
                line = lines[i]
                tag = line[:1] or " "
                if tag == "\\":
                    i += 1
                    continue
                if tag not in " +-":
                    raise UpdateProposalError(f"{path}: malformed hunk line {line!r}")
                body.append(tag + line[1:])
                seen_old += tag in " -"
                seen_new += tag in " +"
                i += 1
            if seen_old != old_count or seen_new != new_count:
                raise UpdateProposalError(f"{path}: a hunk is shorter than its header says")
            while i < len(lines) and lines[i].startswith("\\"):
                i += 1
            hunks.append((old_start, old_count, body))
        if not hunks:
            raise UpdateProposalError(f"{path}: no hunks")
        patches.append(_FilePatch(path, is_new, hunks))
        while i < len(lines) and not lines[i].startswith("diff --git"):
            if lines[i].strip():
                raise UpdateProposalError(f"unexpected text after {path}: {lines[i]!r}")
            i += 1
    if not patches:
        raise UpdateProposalError("the patch changes no files")
    return meta, patches


def _check_target(path: str, meta: dict[str, str]) -> str:
    """The path relative to the knowledge root, once it is known to be allowed."""
    pure = Path(path)
    if pure.is_absolute() or ".." in pure.parts or "\\" in path or not pure.parts:
        raise UpdateProposalError(f"{path}: not a path inside {KNOWLEDGE_DIR}/")
    if pure.parts[0] != KNOWLEDGE_DIR:
        raise UpdateProposalError(
            f"{path}: outside {KNOWLEDGE_DIR}/. A knowledge patch changes knowledge only."
        )
    rel = pure.parts[1:]
    client, project = meta.get("client"), meta.get("project")
    if rel[:1] == (CLIENTS_DIR,) and len(rel) >= 2:
        if rel[1] != client:
            raise UpdateProposalError(
                f"{path}: belongs to client {rel[1]!r}, but this patch is for {client!r}. "
                "A patch may touch one client's folder only (A4)."
            )
        tail = rel[2:]
        allowed = (
            tail == ("client.md",)
            or (len(tail) == 2 and tail[0] == "engagements" and tail[1].endswith(".md"))
            or tail == ("style", HEADERS_PROPOSED)
        )
        if allowed:
            return "/".join(rel)
    elif rel[:1] == (PROJECTS_DIR,) and len(rel) == 3 and rel[2] == "claims.md":
        if rel[1] == project:
            return "/".join(rel)
        raise UpdateProposalError(
            f"{path}: belongs to project {rel[1]!r}, but this patch is for {project!r}"
        )
    raise UpdateProposalError(
        f"{path}: not a file a knowledge proposal may change (claims.md, client.md, "
        "engagements/*.md, style/headers.proposed.yaml)"
    )


def _apply_hunks(
    path: str, original: list[str], hunks: list[tuple[int, int, list[str]]]
) -> list[str]:
    lines = list(original)
    offset = 0
    for old_start, old_count, body in hunks:
        before = [line[1:] for line in body if line[0] in " -"]
        after = [line[1:] for line in body if line[0] in " +"]
        at = (old_start - 1 if old_count else old_start) + offset
        if lines[at : at + len(before)] != before:
            hits = [
                k
                for k in range(len(lines) - len(before) + 1)
                if lines[k : k + len(before)] == before
            ]
            if len(hits) != 1:
                raise UpdateProposalError(
                    f"{path}: a hunk at line {old_start} does not match the file as it stands "
                    "(it changed since the proposal was made); propose again"
                )
            at = hits[0]
        lines[at : at + len(before)] = after
        offset += len(after) - len(before)
    return lines


def apply_patch(text: str, knowledge_root: Path) -> list[str]:
    """Apply a reviewed proposal under `knowledge_root`. Returns the relative paths written.

    All-or-nothing: every file is checked and computed before the first is written.

    Raises:
        UpdateProposalError: no preamble naming a client and project, a path the proposal
            may not change (another client's folder, anything outside `knowledge/`), or a
            hunk that no longer matches.
    """
    knowledge_root = Path(knowledge_root)
    meta, patches = _parse_patch(text)
    if not meta.get("client") or not meta.get("project"):
        raise UpdateProposalError(
            "the patch has no '# client:' and '# project:' preamble; only a patch made by "
            "`autodeck knowledge propose` is applied"
        )
    root = knowledge_root.resolve()
    staged: list[tuple[Path, str, str]] = []
    seen: set[str] = set()
    for file_patch in patches:
        rel = _check_target(file_patch.path, meta)
        if rel in seen:
            raise UpdateProposalError(f"{file_patch.path}: appears twice in the patch")
        seen.add(rel)
        target = (knowledge_root / rel).resolve()
        if root not in target.parents:
            raise UpdateProposalError(f"{file_patch.path}: resolves outside {knowledge_root}")
        exists = target.is_file()
        if file_patch.is_new and exists:
            raise UpdateProposalError(f"{rel}: the patch creates it but it already exists")
        if not file_patch.is_new and not exists:
            raise UpdateProposalError(f"{rel}: the patch changes it but it does not exist")
        original = target.read_text(encoding="utf-8").rstrip("\n").split("\n") if exists else []
        if exists and not original[0] and len(original) == 1:
            original = []
        result = _apply_hunks(rel, original, file_patch.hunks)
        staged.append((target, rel, "\n".join(result) + "\n"))
    for target, _, content in staged:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)
    return [rel for _, rel, _ in staged]


__all__ = [
    "FileChange",
    "Proposal",
    "UpdateProposalError",
    "apply_patch",
    "propose_updates",
    "render_patch",
]
