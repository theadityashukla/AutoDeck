"""What the agent remembers between runs (B77): one engagement's memory, and the owner's.

A run's session (B74) remembers that run. This module remembers across runs, at two scopes:

- `engagement`: `knowledge/clients/<client>/memory/<project>.md`. Terms, people, open
  actions, decisions and deck preferences for this client's project.
- `owner`: `~/.autodeck/memory/owner.md`. How the person likes notes and decks; **never a
  client fact**.

**Why the engagement file lives under the client, not the project.** The project tier is
shared across clients by design (D8, `context_assembler`). People, action items and a
client's deck preferences written there would reach the next client's build. Under
`clients/<client>/` every read and write goes through `ClientNamespace.guard`, so A4 holds
by construction: a store bound to one client cannot open another's memory.

**Why the owner file is checked on every write.** It is read into every build for every
client, so it is the one place a client fact could cross namespaces. A write to it is
refused when it names any client or project in the knowledge root, uses a term or person
from the current engagement's memory, copies eight or more consecutive words from a passage
shown in this session, or states a number other than a small count. That is a backstop
under the instruction not to put client facts there, not a proof; every write is also logged.

**Memory is context, never evidence.** It is not a `Document`, so nothing in it can become
a `Citation` (A1): a fact the agent remembers still has to be found in a source to reach a
slide. The files are markdown with fixed `##` sections, one bullet per item, so the person
can read and edit them; each bullet the agent writes ends with `(run <id>)`.

**Size is bounded.** Past the cap a write is refused with "consolidate first", and the agent
rewrites the file shorter (`revise_memory`). A memory that only grows stops being read.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from autodeck.knowledge.context_assembler import ClientNamespace
from autodeck.knowledge.loader import (
    CLIENTS_DIR,
    ClientIsolationError,
    KnowledgeError,
    KnowledgeLoader,
)

MemoryScope = Literal["engagement", "owner"]

ENGAGEMENT_SECTIONS: tuple[str, ...] = (
    "Terms",
    "People",
    "Open actions",
    "Decisions",
    "Deck preferences",
)
"""Terms: canonical spellings and what they were heard or mistyped as. People: names and
roles. Open actions: owner, task, due, as stated. Decisions: what was agreed. Deck
preferences: what this client wants decks to look and sound like."""

OWNER_SECTIONS: tuple[str, ...] = ("Note style", "Deck habits")

SECTIONS: dict[MemoryScope, tuple[str, ...]] = {
    "engagement": ENGAGEMENT_SECTIONS,
    "owner": OWNER_SECTIONS,
}

CAPS: dict[MemoryScope, int] = {"engagement": 8_000, "owner": 3_000}
"""Characters per file. About 2k and 750 tokens: small enough to send with every build."""

MAX_ITEM_CHARS = 300

COPY_RUN_WORDS = 8
"""An owner note sharing this many consecutive words with a shown passage was copied."""

SMALL_COUNT = 12
"""The largest bare number an owner note may state ("at most 6 bullets", "10 slides")."""

DEFAULT_OWNER_PATH = Path.home() / ".autodeck" / "memory" / "owner.md"

_FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
"""A client or project folder name. No separators and no leading dot, so a name can never
climb out of its own folder: `ClientNamespace` derives its root from the client name, so a
client called `../other` would otherwise be "its own" namespace inside another client's."""

_RUN_TAG = re.compile(r"\s*\(run [^)]+\)\s*$")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*\s*%?")


class MemoryWriteError(KnowledgeError):
    """A memory write was refused: unknown section, over the cap, or (owner scope) a client
    fact."""


@dataclass
class MemoryDoc:
    """One memory file: a title line and fixed sections of bullets."""

    title: str
    sections: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def parse(cls, text: str, sections: Iterable[str], title: str) -> MemoryDoc:
        """Read the file's bullets into its fixed sections. Text under an unknown heading,
        or outside any heading, is kept in the nearest known section rather than lost."""
        names = list(sections)
        doc = cls(title=title, sections={name: [] for name in names})
        current: str | None = None
        for raw in text.splitlines():
            line = raw.rstrip()
            if line.startswith("# "):
                doc.title = line[2:].strip() or title
                continue
            if line.startswith("## "):
                heading = line[3:].strip()
                match = next((n for n in names if n.lower() == heading.lower()), None)
                current = match or current
                continue
            item = line.lstrip()
            if not item.startswith(("- ", "* ")):
                continue
            target = current or names[0]
            doc.sections[target].append(item[2:].strip())
        return doc

    def render(self) -> str:
        lines = [f"# {self.title}", ""]
        for name, items in self.sections.items():
            lines.append(f"## {name}")
            lines.extend(f"- {item}" for item in items)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def items(self) -> list[str]:
        return [item for items in self.sections.values() for item in items]


def _bare(item: str) -> str:
    """An item without its `(run …)` tag, whitespace-collapsed, for matching."""
    return " ".join(_RUN_TAG.sub("", item).split())


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def _heads(items: Iterable[str]) -> set[str]:
    """The name or term each item is about: the text before its first ' — ', ':' or '('."""
    heads: set[str] = set()
    for item in items:
        head = re.split(r"\s[\u2014\u2013-]\s|:|\(", _bare(item), maxsplit=1)[0].strip()
        if len(head) >= 3:
            heads.add(head.casefold())
    return heads


class MemoryStore:
    """The engagement and owner memory for one build (one client, one project)."""

    def __init__(
        self,
        knowledge_root: Path,
        *,
        client: str,
        project: str,
        run_id: str,
        owner_path: Path = DEFAULT_OWNER_PATH,
        shown_texts: Callable[[], Iterable[str]] = lambda: (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        for label, name in (("client", client), ("project", project)):
            if not _FOLDER_NAME.match(name) or ".." in name:
                raise ClientIsolationError(
                    f"memory refused: {label} name {name!r} is not a plain folder name. A "
                    "name with a path in it could reach another client's memory (A4)."
                )
        self.knowledge_root = Path(knowledge_root)
        self.client = client
        self.project = project
        self.run_id = run_id
        self.namespace = ClientNamespace(client, self.knowledge_root)
        self.owner_path = Path(owner_path)
        self.shown_texts = shown_texts
        """The passages shown this session, for the owner-copy check. A session rebinds it to
        its workspace's citable set."""
        self._clock = clock
        loader = KnowledgeLoader(self.knowledge_root)
        self._names = [
            *loader.client_names(),
            *loader.project_names(),
        ]

    # -- paths ----------------------------------------------------------------------

    @property
    def engagement_path(self) -> Path:
        path = self.knowledge_root / CLIENTS_DIR / self.client / "memory" / f"{self.project}.md"
        return self.namespace.guard(path)

    def path(self, scope: MemoryScope) -> Path:
        return self.engagement_path if scope == "engagement" else self.owner_path

    def _audit_path(self, scope: MemoryScope) -> Path:
        return self.path(scope).parent / "audit.jsonl"

    # -- reading --------------------------------------------------------------------

    def _title(self, scope: MemoryScope) -> str:
        if scope == "engagement":
            return f"Memory: {self.client} / {self.project}"
        return "Memory: how I like to work"

    def load(self, scope: MemoryScope) -> MemoryDoc:
        path = self.path(scope)
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        return MemoryDoc.parse(text, SECTIONS[scope], self._title(scope))

    def read(self, scope: MemoryScope) -> str:
        return self.load(scope).render()

    def terms(self) -> list[str]:
        """The engagement's Terms items without their `(run …)` tags (B79), oldest first."""
        return [_bare(item) for item in self.load("engagement").sections.get("Terms", [])]

    def snapshot(self) -> dict[MemoryScope, str]:
        """Both files as they stand now. A session records this at its start (A6)."""
        return {"engagement": self.read("engagement"), "owner": self.read("owner")}

    def context_text(self, snapshot: Mapping[MemoryScope, str] | None = None) -> str:
        """The opening-context section built from a snapshot."""
        snap = snapshot or self.snapshot()
        return (
            "# Memory (context, not evidence; never cite it)\n\n"
            "What earlier runs learned. Use it to spell names and terms, to know who is who "
            "and what is still open, and to write the way this client and the person you work "
            "for prefer. A fact here still needs a source before it goes on a slide.\n\n"
            f"## This engagement ({self.client} / {self.project})\n\n"
            + _body(snap["engagement"])
            + "\n\n## The person you work for\n\n"
            + _body(snap["owner"])
        )

    # -- writing --------------------------------------------------------------------

    def add(self, scope: MemoryScope, section: str, text: str) -> str:
        item = self._item(scope, section, text)
        doc = self.load(scope)
        key = _bare(item).casefold()
        if any(_bare(existing).casefold() == key for existing in doc.items()):
            return f"already remembered under {section}: {_bare(item)}"
        doc.sections[section].append(item)
        self._save(scope, doc, op="add", section=section, text=text)
        return f"remembered under {section}: {_bare(item)}"

    def replace(self, scope: MemoryScope, section: str, old: str, new: str) -> str:
        doc = self.load(scope)
        self._check_section(scope, section)
        index = self._find(doc.sections[section], old, section)
        doc.sections[section][index] = self._item(scope, section, new)
        self._save(scope, doc, op="replace", section=section, text=new)
        return f"replaced under {section}: {_bare(new)}"

    def remove(self, scope: MemoryScope, section: str, old: str) -> str:
        doc = self.load(scope)
        self._check_section(scope, section)
        index = self._find(doc.sections[section], old, section)
        removed = doc.sections[section].pop(index)
        self._save(scope, doc, op="remove", section=section, text=removed)
        return f"forgot under {section}: {_bare(removed)}"

    def rewrite(self, scope: MemoryScope, content: str) -> str:
        """Replace the whole file (consolidation). Every item is checked as if added."""
        doc = MemoryDoc.parse(content, SECTIONS[scope], self._title(scope))
        for name, items in doc.sections.items():
            doc.sections[name] = [self._item(scope, name, item, tag=False) for item in items]
        size = len(doc.render())
        counts = ", ".join(f"{name} {len(items)}" for name, items in doc.sections.items())
        self._save(scope, doc, op="rewrite", section="", text=f"rewritten: {counts}")
        return f"{scope} memory rewritten: {len(doc.items())} items, {size} characters"

    # -- checks ---------------------------------------------------------------------

    def _check_section(self, scope: MemoryScope, section: str) -> None:
        if section not in SECTIONS[scope]:
            raise MemoryWriteError(
                f"{scope} memory has no section {section!r}; its sections are "
                + ", ".join(SECTIONS[scope])
            )

    def _item(self, scope: MemoryScope, section: str, text: str, *, tag: bool = True) -> str:
        self._check_section(scope, section)
        clean = " ".join(text.split())
        if not clean:
            raise MemoryWriteError("nothing to remember: the text is empty")
        if len(_bare(clean)) > MAX_ITEM_CHARS:
            raise MemoryWriteError(
                f"one memory item is at most {MAX_ITEM_CHARS} characters; say it shorter"
            )
        if scope == "owner":
            self._check_owner(_bare(clean))
        if tag and not _RUN_TAG.search(clean):
            clean = f"{clean} (run {self.run_id})"
        return clean

    def _check_owner(self, text: str) -> None:
        """Refuse an owner note that carries a client fact (see the module docstring)."""
        lowered = text.casefold()
        named = sorted(
            name
            for name in self._names
            if re.search(rf"\b{re.escape(name.casefold())}\b", lowered)
        )
        if named:
            raise MemoryWriteError(
                f"owner memory is shared by every client's builds and may not name a client or "
                f"project ({', '.join(named)}). Put this in engagement memory instead."
            )
        engagement = self.load("engagement")
        heads = _heads(
            engagement.sections["Terms"] + engagement.sections["People"]
        )
        used = sorted(h for h in heads if re.search(rf"\b{re.escape(h)}\b", lowered))
        if used:
            raise MemoryWriteError(
                "owner memory may not mention this engagement's terms or people "
                f"({', '.join(used)}). Put this in engagement memory instead."
            )
        words = _words(text)
        grams = {
            tuple(words[i : i + COPY_RUN_WORDS]) for i in range(len(words) - COPY_RUN_WORDS + 1)
        }
        if grams:
            for passage in self.shown_texts():
                source = _words(passage)
                for i in range(len(source) - COPY_RUN_WORDS + 1):
                    if tuple(source[i : i + COPY_RUN_WORDS]) in grams:
                        raise MemoryWriteError(
                            "owner memory may not copy a source passage: this note repeats "
                            f"{COPY_RUN_WORDS}+ words of something shown in this session."
                        )
        for match in _NUMBER.finditer(text):
            token = match.group(0).strip()
            digits = token.rstrip("%").replace(",", "")
            if "%" in token or "." in digits or float(digits) > SMALL_COUNT:
                raise MemoryWriteError(
                    f"owner memory may not state figures ({token!r}); only small counts like "
                    "'at most 6 bullets'. A figure is a fact about something; keep it in "
                    "engagement memory or in the sources."
                )

    @staticmethod
    def _find(items: list[str], old: str, section: str) -> int:
        wanted = _bare(old).casefold()
        exact = [i for i, item in enumerate(items) if _bare(item).casefold() == wanted]
        if exact:
            return exact[0]
        partial = [i for i, item in enumerate(items) if wanted and wanted in item.casefold()]
        if len(partial) == 1:
            return partial[0]
        if not partial:
            raise MemoryWriteError(f"no item under {section} matches {old!r}")
        raise MemoryWriteError(
            f"{len(partial)} items under {section} match {old!r}; quote one whole"
        )

    def _save(
        self, scope: MemoryScope, doc: MemoryDoc, *, op: str, section: str, text: str
    ) -> None:
        path = self.path(scope)
        before = path.read_text(encoding="utf-8") if path.is_file() else ""
        rendered = doc.render()
        if len(rendered) > CAPS[scope]:
            raise MemoryWriteError(
                f"{scope} memory would be {len(rendered)} characters, over its "
                f"{CAPS[scope]}-character cap. Consolidate first: read_memory, then "
                "revise_memory with a shorter version (merge, drop what is settled)."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)
        record = {
            "at": self._clock().isoformat(timespec="seconds"),
            "run": self.run_id,
            "scope": scope,
            "op": op,
            "section": section,
            "text": " ".join(text.split())[:MAX_ITEM_CHARS],
            "chars_before": len(before),
            "chars_after": len(rendered),
        }
        with self._audit_path(scope).open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")


def _body(rendered: str) -> str:
    """A rendered file without its title line; '(nothing yet)' when it has no items."""
    lines = rendered.splitlines()[1:]
    if not any(line.startswith("- ") for line in lines):
        return "(nothing yet)"
    kept = [f"#{line}" if line.startswith("## ") else line for line in lines if line.strip()]
    return "\n".join(kept)
