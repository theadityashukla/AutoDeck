"""Build manifest (A6) — what produced this deck, and what "the same output" means.

A6 requires every deck to ship a manifest recording model IDs and versions, prompt file
hashes, the knowledge folder's git commit, and the component library version, such that the
same manifest plus the same IR re-renders comparable output.

Phase 0 produced a *blank but valid* manifest: the schema was fixed then so later phases
fill fields rather than invent structure, and the `env` plus resolved model IDs were
recorded from the first run. That last part matters immediately — B8 makes `dev` and `prod`
results non-transferable, so a deck that does not state which bindings produced it cannot be
interpreted at all.

## Phase 2b fills the three gaps the brief names

**The knowledge commit, and whether the tree was dirty.** The knowledge folder is an input
to every build; a deck reproducible against "whatever `claims.md` said that day" is not
reproducible. HEAD alone is not enough, because uncommitted edits are invisible in it — so
`knowledge_dirty` is recorded alongside, and a dirty-tree build says so rather than
implying a reproducibility it does not have.

**The component library version, from one definition.** `catalog.COMPONENT_LIB_VERSION` is
read both here and where the `Deck` is built. Two literals would be two answers to one
question, and the stale one would be the manifest's.

## Byte-comparable is not achievable for PPTX, and this module does not pretend otherwise

INVARIANTS' "watch for" on A6 is right and its headline sentence is optimistic. A PPTX is a
zip, and a zip of identical parts is **not** identical bytes:

- every entry carries the wall-clock time it was written;
- entry order follows the writer's iteration order, not the document;
- the DEFLATE stream depends on the zlib build, so the same bytes in give different bytes
  out on a different machine;
- `docProps/core.xml` carries `dcterms:modified` and a revision counter that move when the
  file is saved at all.

None of that is fixable by being careful. So the honest claim is **normalised-comparable**,
and the function is named for what it does: `canonical_pptx_digest` hashes a canonical
serialisation — entries sorted, decompressed, with a named list of volatile `docProps`
fields blanked — and `PPTX_NORMALISATION_RULES` records, per rule, why the thing is volatile
*and why dropping it cannot hide a real difference in the deck*. The manifest stores which
normalisation was applied, so a comparison run next year knows what was excluded rather
than guessing. **A6's own wording needs correcting to match; that is the owner's call and
not a silent redefinition, so nothing here is named `bytes_match`.**

Owning phase: 0 (skeleton) / Phase 2b (populated, task 2b.10). Opus tier —
`autodeck/audit/` is a path guardrail in docs/MODEL_ROUTING.md.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from autodeck.design.components.catalog import COMPONENT_LIB_VERSION

MANIFEST_VERSION = 1


class Manifest(BaseModel):
    """The reproducibility record shipped with every deck."""

    model_config = ConfigDict(extra="forbid")

    manifest_version: int = MANIFEST_VERSION
    run_id: str = Field(min_length=1)
    env: str = Field(min_length=1, description="Which provider bindings produced this (B8).")
    created_at: str

    models: dict[str, Any] = Field(default_factory=dict)
    """Resolved provider and model per role, from `ModelRegistry.manifest_entry()`."""

    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    """Prompt file path -> SHA-256. Plan §0.5 versions prompts; A6 pins which version ran."""

    knowledge_commit: str | None = None
    """Git commit of the knowledge folder, when one is in use (Phase 1).

    None means the folder is not in a git working tree at all — which is a real answer and
    a bad one, since it says the build's knowledge inputs are unversioned.
    """

    knowledge_dirty: bool | None = None
    """Whether the knowledge folder had uncommitted or untracked changes at build time.

    Recorded because `knowledge_commit` alone would imply a reproducibility the build does
    not have: a commit hash says nothing about the edits sitting on top of it, and a deck
    built from a dirty tree cannot be rebuilt from anything this manifest names. True is not
    an error — it is the ordinary state of a working session — but it has to be visible,
    for the same reason `capped` is surfaced in `verdicts.py` rather than swallowed.

    None means there was no git tree to ask, and is deliberately distinct from False.
    """

    component_lib_version: str = COMPONENT_LIB_VERSION
    """Which slot geometry laid this deck out, from `catalog.COMPONENT_LIB_VERSION`.

    The same constant `Deck.component_lib_version` is built from. A deck rendered against
    different slot boxes is a different deck from the same IR, so this is part of what "the
    same build" means.
    """

    render_normalisation: str | None = None
    """Which normalisation a comparison of two renders must apply, e.g. `pptx-canonical-v1`.

    Recorded rather than assumed. A comparison run a year from now needs to know what was
    excluded from "the same output", and a normalisation that lives only in whichever
    version of this file happened to be checked out is not a record of anything.
    """

    render_normalisation_excludes: list[str] = Field(default_factory=list)
    """The ids of the rules `render_normalisation` applied — what the digest does not see."""

    ir_sha256: str | None = None
    autodeck_version: str = "2.0.0.dev0"

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.model_dump(mode="json"), indent=2) + "\n"
        path.write_text(payload, encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> Manifest:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def reproducibility_key(self) -> dict[str, Any]:
        """The fields that must match for two builds to be considered the same build.

        `created_at` is excluded on purpose — A6 compares builds *excluding timestamps*, and
        comparing a build against itself an hour later must succeed.

        `knowledge_dirty` is **not** excluded. Two builds from the same commit, one of them
        with uncommitted edits on top, are not the same build, and the whole reason to
        record the flag is that nothing else in here would show the difference.
        """
        return self.model_dump(mode="json", exclude={"created_at"})

    def matches(self, other: Manifest) -> bool:
        """Whether `other` describes the same build, ignoring timestamps."""
        return self.reproducibility_key() == other.reproducibility_key()

    def reproducible(self) -> bool:
        """Whether this build could be reproduced from what the manifest names.

        False when the knowledge tree was dirty, unversioned, or simply not recorded: in all
        three cases this manifest does not name the knowledge inputs, so a rebuild would be
        a rebuild from something else. Deliberately not named `valid` — the manifest is
        perfectly valid, it is the build that is not repeatable, and nothing here refuses a
        build over it.
        """
        return self.knowledge_commit is not None and self.knowledge_dirty is False


def file_sha256(path: Path) -> str:
    """SHA-256 of a file's contents."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


#: Documentation living under `prompts/` is not itself a prompt. Hashing it would make an
#: edit to the README change every build's reproducibility key, which would turn a real A6
#: signal into noise.
_NOT_A_PROMPT: frozenset[str] = frozenset({"README.md"})


def hash_prompts(prompts_dir: Path) -> dict[str, str]:
    """Hash every prompt file, keyed by path relative to `prompts_dir`.

    Sorted so the manifest is stable between runs — an unordered dict would make two
    identical builds produce different JSON and break the A6 comparison for no reason.
    """
    prompts_dir = Path(prompts_dir)
    if not prompts_dir.is_dir():
        return {}
    return {
        str(path.relative_to(prompts_dir)): file_sha256(path)
        for path in sorted(prompts_dir.rglob("*.md"))
        if path.name not in _NOT_A_PROMPT
    }


@dataclass(frozen=True)
class GitState:
    """A directory's git commit and whether it had uncommitted work on top.

    The pair, never just the commit. A hash on its own reads as "this is exactly what was
    used", and on a working session it very often is not.
    """

    commit: str | None
    dirty: bool | None
    """None when there is no git working tree to ask — distinct from False, which is a
    positive finding that the tree was clean."""

    @property
    def reproducible(self) -> bool:
        return self.commit is not None and self.dirty is False


def git_state(repo_dir: Path) -> GitState:
    """Resolve HEAD for the tree containing `repo_dir`, and whether `repo_dir` is dirty.

    Two deliberate choices:

    **HEAD is the whole repository's**, because that is the only thing a rebuild can be
    asked for — `git checkout <sha>` takes a repository, not a folder.

    **Dirtiness is scoped to `repo_dir`**, because the question the manifest is answering is
    whether *the knowledge inputs* were the ones at that commit. An uncommitted edit under
    `autodeck/` does not change what `claims.md` said, and a flag that went True for every
    build during development would be read as noise within a week and stop being read at
    all. Untracked files count: a new, uncommitted `claims.md` is precisely an input that
    HEAD does not describe.
    """
    commit = _git(repo_dir, "rev-parse", "HEAD")
    if commit is None:
        return GitState(commit=None, dirty=None)
    status = _git(repo_dir, "status", "--porcelain", "--", ".")
    return GitState(commit=commit, dirty=None if status is None else bool(status))


def _git(repo_dir: Path, *args: str) -> str | None:
    """Run one git command in `repo_dir`; None on any failure, including "not a repo"."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


# ---------------------------------------------------------------------------
# Render comparison — normalised, and named for what it is
# ---------------------------------------------------------------------------

#: The id of the normalisation `canonical_pptx_digest` applies, stored in the manifest.
#: **Bump the version whenever `PPTX_NORMALISATION_RULES` changes.** A digest computed under
#: different rules is a different question, and two manifests that disagree about the rules
#: should fail to match rather than quietly compare digests that are not comparable.
PPTX_NORMALISATION = "pptx-canonical-v1"


@dataclass(frozen=True)
class NormalisationRule:
    """One thing the canonical digest ignores, with the argument for ignoring it.

    `safe_because` is the load-bearing field and the reason this is a table rather than four
    lines of code. Every exclusion is a hole in A6 unless it can be shown that the excluded
    thing cannot carry a real difference in the deck, and an exclusion nobody can justify is
    one nobody can argue with when a comparison passes that should have failed — the same
    reason the numeric linter's normalisation table carries `why`.
    """

    id: str
    what: str
    why: str
    safe_because: str


PPTX_NORMALISATION_RULES: tuple[NormalisationRule, ...] = (
    NormalisationRule(
        id="zip-entry-order",
        what="Archive entries are hashed in sorted name order.",
        why=(
            "A PPTX's entry order follows the writing library's iteration over its part "
            "collection, not the document. Two saves of one presentation can order the "
            "parts differently."
        ),
        safe_because=(
            "Nothing resolves a part by position. `[Content_Types].xml` and the "
            "relationship graph address every part by name, so order is not addressable "
            "and cannot encode content. Every name and every part's bytes are still "
            "hashed, so an added, removed or renamed part still changes the digest."
        ),
    ),
    NormalisationRule(
        id="zip-entry-metadata",
        what=(
            "Per-entry metadata — modification time, compression method and level, CRC, "
            "external attributes — is not hashed; each part's *decompressed* bytes are."
        ),
        why=(
            "`zipfile` stamps every entry with the wall-clock time of the save, so a "
            "second save is a different file. The DEFLATE stream also depends on the zlib "
            "build and level, so identical input bytes give different archive bytes on a "
            "different machine."
        ),
        safe_because=(
            "These describe how the bytes were stored, not what they are. The decompressed "
            "bytes are the document — anything a renderer, a reader or a reviewer can see "
            "survives decompression unchanged, and the CRC is a function of the bytes "
            "already hashed."
        ),
    ),
    NormalisationRule(
        id="docprops-volatile-fields",
        what=(
            "In `docProps/core.xml` only, the text of `dcterms:created`, "
            "`dcterms:modified`, `cp:lastPrinted`, `cp:revision` and `cp:lastModifiedBy` "
            "is blanked before hashing."
        ),
        why=(
            "PowerPoint and python-pptx write these on save. They move on every build even "
            "when the deck is identical, which is exactly INVARIANTS' 'embedded creation "
            "timestamps' warning."
        ),
        safe_because=(
            "None of the five is deck content: none appears on a slide, in a speaker note, "
            "or in any rendered output. They record when the file was written and by which "
            "process. The rest of `core.xml` — title, subject, keywords, category, "
            "description — is authored metadata and is hashed unchanged, and no other part "
            "is touched. In particular `docProps/app.xml` is hashed in full, because its "
            "`TitlesOfParts` carries the slide titles."
        ),
    ),
)

#: The `docProps/core.xml` element local names whose text is blanked. Matched by local name
#: so a namespace-prefix change (`cp:` vs `coreProperties:`) cannot slip a field past.
_VOLATILE_DOCPROPS: tuple[str, ...] = (
    "created",
    "modified",
    "lastPrinted",
    "revision",
    "lastModifiedBy",
)

_CORE_PROPERTIES_PART = "docProps/core.xml"

_VOLATILE_PATTERNS: tuple[re.Pattern[bytes], ...] = tuple(
    re.compile(
        rb"(<(?:[\w.-]+:)?" + field.encode("ascii") + rb"(?:\s[^>]*)?>)(.*?)"
        rb"(</(?:[\w.-]+:)?" + field.encode("ascii") + rb">)",
        re.DOTALL,
    )
    for field in _VOLATILE_DOCPROPS
)


def canonical_pptx_digest(path: Path) -> str:
    """SHA-256 of a PPTX's canonical form, under `PPTX_NORMALISATION`.

    **Not a digest of the file.** Two PPTX files with this digest in common are the same
    *document*; they are almost certainly not the same bytes, and A6's "byte-comparable"
    cannot be had for a zip container — see the module docstring. The name says which of the
    two this function answers.

    Raises:
        zipfile.BadZipFile: `path` is not a zip archive at all.
    """
    digest = hashlib.sha256()
    digest.update(PPTX_NORMALISATION.encode("utf-8"))
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            data = normalise_part(name, archive.read(name))
            # Name and length are framed into the hash so that the boundary between an
            # entry's name and its bytes cannot be moved: without it, ("a", b"bc") and
            # ("ab", b"c") would be one archive as far as the digest is concerned.
            digest.update(name.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
    return digest.hexdigest()


def normalise_part(name: str, data: bytes) -> bytes:
    """Apply the `docProps` rule to one archive member; everything else passes through.

    Exposed so a test can assert *which* bytes change, rather than only that two digests
    agree. A normalisation nobody can look at is one nobody can check the scope of.
    """
    if name != _CORE_PROPERTIES_PART:
        return data
    for pattern in _VOLATILE_PATTERNS:
        data = pattern.sub(rb"\1\3", data)
    return data


def pptx_differences(left: Path, right: Path) -> list[str]:
    """Which parts differ between two PPTX files under the canonical normalisation.

    Returned instead of a bare boolean because "these two renders are not the same" is the
    moment somebody needs to know *where*, and a 2 MB zip does not volunteer it. An empty
    list means the two are normalised-identical — the same thing `canonical_pptx_digest`
    agreeing means, said in more detail.
    """
    with zipfile.ZipFile(left) as a, zipfile.ZipFile(right) as b:
        left_names, right_names = set(a.namelist()), set(b.namelist())
        differences = [
            f"only in {Path(left).name}: {n}" for n in sorted(left_names - right_names)
        ]
        differences.extend(
            f"only in {Path(right).name}: {n}" for n in sorted(right_names - left_names)
        )
        differences.extend(
            f"differs: {name}"
            for name in sorted(left_names & right_names)
            if normalise_part(name, a.read(name)) != normalise_part(name, b.read(name))
        )
    return differences


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_manifest(
    *,
    run_id: str,
    env: str,
    models: dict[str, Any] | None = None,
    prompts_dir: Path | None = None,
    knowledge_dir: Path | None = None,
    component_lib_version: str = COMPONENT_LIB_VERSION,
    ir_path: Path | None = None,
    render_normalisation: str | None = PPTX_NORMALISATION,
) -> Manifest:
    """Assemble a manifest from the current build's inputs.

    `render_normalisation` defaults to the PPTX normalisation because every build this
    system performs ends in a PPTX. Pass None for a build that produced no render, so the
    manifest does not describe a comparison that was never available.
    """
    knowledge = git_state(knowledge_dir) if knowledge_dir else GitState(None, None)
    return Manifest(
        run_id=run_id,
        env=env,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        models=models or {},
        prompt_hashes=hash_prompts(prompts_dir) if prompts_dir else {},
        knowledge_commit=knowledge.commit,
        knowledge_dirty=knowledge.dirty,
        component_lib_version=component_lib_version,
        ir_sha256=file_sha256(ir_path) if ir_path else None,
        render_normalisation=render_normalisation,
        render_normalisation_excludes=(
            [rule.id for rule in PPTX_NORMALISATION_RULES]
            if render_normalisation == PPTX_NORMALISATION
            else []
        ),
    )
