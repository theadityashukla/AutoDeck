"""Client onboarding: a brand folder in, a working `knowledge/clients/<client>/` out (task 4.1).

One entry point, `onboard_client`, builds the theme (mode a: extracted from a supplied
template; mode b: a supplied `tokens.json`), checks fonts and their embedding licences,
registers icons, ingests past decks (task 4.2) and writes whatever the loader requires.

Every write goes through the new client's `ClientNamespace`: a target that resolves outside
`clients/<client>/` raises `ClientIsolationError`, so a crafted brand folder (a symlinked
file, say) cannot make onboarding write into another client's folder or anywhere else. Past
decks are read for structure only (A1); the summary carries counts and file names, never deck
text.

**Not proven against a real corporate template** — see `autodeck.design.theme.extract` (Q5).
When extraction fails or yields unusable tokens, onboarding falls back to a supplied
`tokens.json` and says so in the summary; with none, it stops (the escalation trigger).
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml

from autodeck.design.theme.extract import EXTRACTION_GAPS, extract_tokens
from autodeck.design.theme.tokens import DesignTokens
from autodeck.knowledge.context_assembler import ClientNamespace
from autodeck.knowledge.loader import CLIENTS_DIR, ClientIsolationError, KnowledgeError

#: Written into every stub so a person, the UI or the CLI can tell a stub from curated text.
STUB_MARKER = "TODO:"
FONT_SUFFIXES = (".ttf", ".otf")
TEMPLATE_SUFFIXES = (".pptx", ".potx")

#: `OS/2.fsType` bit 1: "restricted license embedding" — the font must not be embedded.
FS_RESTRICTED = 0x0002
_FS_LABELS = (
    (0x0002, "restricted license embedding"),
    (0x0004, "preview & print embedding"),
    (0x0008, "editable embedding"),
)

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class OnboardError(KnowledgeError):
    """The brand folder cannot be turned into a client namespace (message says why)."""


@dataclass
class FontReport:
    family: str
    status: str  # "available" | "supplied" | "missing"


@dataclass
class FontFileReport:
    name: str
    family: str | None = None
    fs_type: int | None = None
    license_checked: bool = False
    restricted: bool = False
    license_note: str = ""


@dataclass
class OnboardResult:
    client: str
    root: Path
    theme_mode: str = ""  # "a (template extracted)" | "b (tokens.json)" | "kept existing"
    theme_notes: list[str] = field(default_factory=list)
    colour_count: int = 0
    families: list[FontReport] = field(default_factory=list)
    font_files: list[FontFileReport] = field(default_factory=list)
    icons_copied: list[str] = field(default_factory=list)
    icons_skipped: list[str] = field(default_factory=list)
    decks_copied: list[str] = field(default_factory=list)
    deck_count: int = 0
    slide_count: int = 0
    profile_files: int = 0
    gap_count: int = 0
    stubs: list[str] = field(default_factory=list)
    copied_docs: list[str] = field(default_factory=list)
    headers_proposed: bool = False
    warnings: list[str] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        """Counts and names only — never deck text."""
        by_status = {s: [f.family for f in self.families if f.status == s] for s in
                     ("available", "supplied", "missing")}  # fmt: skip
        restricted = [f.name for f in self.font_files if f.restricted]
        lines = [
            f"client: {self.client}  ({self.root})",
            f"theme: mode {self.theme_mode}; {self.colour_count} colours",
            *(f"  note: {n}" for n in self.theme_notes),
            "fonts: "
            f"{len(by_status['available'])} available, {len(by_status['supplied'])} supplied, "
            f"{len(by_status['missing'])} missing"
            + (f" ({', '.join(by_status['missing'])})" if by_status["missing"] else ""),
            f"font files: {len(self.font_files)} copied, {len(restricted)} restricted"
            + (
                ""
                if all(f.license_checked for f in self.font_files)
                else "; licence not checked (fontTools not installed)"
            ),
            f"icons: {len(self.icons_copied)} copied, {len(self.icons_skipped)} skipped",
            f"decks: {self.deck_count} ({self.slide_count} slides), "
            f"{self.profile_files} profile file(s), {self.gap_count} catalog gap(s)",
            "stubs written: " + (", ".join(self.stubs) if self.stubs else "none"),
            "style/headers.proposed.yaml written (curate it into headers.yaml)"
            if self.headers_proposed
            else "headers.proposed.yaml: not written",
        ]
        lines += [f"WARNING: {w}" for w in self.warnings]
        return lines


# ---------------------------------------------------------------------------
# Guarded writes
# ---------------------------------------------------------------------------


class _ClientWriter:
    """Every file onboarding writes passes through here (the client's namespace guard)."""

    def __init__(self, namespace: ClientNamespace) -> None:
        self.namespace = namespace
        self.written: list[Path] = []

    def target(self, relative: str) -> Path:
        path = self.namespace.own_root / relative
        guarded = self.namespace.guard(path)
        # `own_root` is resolved; resolving the target follows any symlink already there.
        resolved = guarded.parent.resolve() / guarded.name
        if not self.namespace.owns(resolved) or (
            guarded.is_symlink() and not self.namespace.owns(guarded.resolve())
        ):
            raise ClientIsolationError(
                f"onboarding for {self.namespace.client!r} would write {path}, outside its "
                f"own folder {self.namespace.own_root}"
            )
        return guarded

    def write_bytes(self, relative: str, data: bytes) -> Path:
        path = self.target(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.written.append(path)
        return path

    def write_text(self, relative: str, text: str) -> Path:
        return self.write_bytes(relative, text.encode("utf-8"))

    def copy(self, source: Path, relative: str) -> Path:
        return self.write_bytes(relative, Path(source).read_bytes())

    def exists(self, relative: str) -> bool:
        return self.target(relative).exists()


# ---------------------------------------------------------------------------
# Brand folder
# ---------------------------------------------------------------------------


def validate_client_name(name: str) -> str:
    """A plain folder name (A4): letters, digits, `-` and `_`; never a path."""
    if not isinstance(name, str) or not _NAME.match(name):
        raise OnboardError(
            f"invalid client name {name!r}: use a plain folder name of letters, digits, "
            "'-' and '_' (no slashes, dots or spaces)"
        )
    return name


@dataclass
class _Brand:
    folder: Path
    template: Path | None
    decks: list[Path]
    fonts: list[Path]
    icons: list[Path]
    tokens: Path | None
    docs: dict[str, Path]  # relative target -> source


def _scan_brand(folder: Path, template: Path | None) -> _Brand:
    if not folder.is_dir():
        raise OnboardError(f"brand folder not found: {folder}")
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    pptx = [p for p in files if p.suffix.lower() in TEMPLATE_SUFFIXES]
    chosen: Path | None = None
    if template is not None:
        chosen = template if template.is_absolute() or template.exists() else folder / template
        if not chosen.is_file():
            raise OnboardError(f"--template {template} is not a file")
        chosen = chosen.resolve()
    else:
        named = [p for p in pptx if p.suffix.lower() == ".potx"] or [
            p for p in pptx if p.stem.lower().startswith("template")
        ]
        chosen = named[0] if named else None
    decks = [p for p in pptx if p.suffix.lower() == ".pptx" and p.resolve() != chosen]
    top = {p.name.lower(): p for p in files if p.parent == folder}
    docs: dict[str, Path] = {}
    for name in ("client.md", "value_prop.md"):
        if name in top:
            docs[name] = top[name]
    if "headers.yaml" in top:
        docs["style/headers.yaml"] = top["headers.yaml"]
    return _Brand(
        folder=folder,
        template=chosen,
        decks=decks,
        fonts=[p for p in files if p.suffix.lower() in FONT_SUFFIXES],
        icons=[p for p in files if p.suffix.lower() == ".svg"],
        tokens=top.get("tokens.json"),
        docs=docs,
    )


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


def _unusable(tokens: DesignTokens) -> str | None:
    palette = tokens.palette.as_scheme()
    if palette["dk1"].upper() == palette["lt1"].upper():
        return "text and background colours (dk1/lt1) are identical"
    if len({v.upper() for v in palette.values()}) < 4:
        return "fewer than four distinct colours were extracted"
    return None


def _load_supplied_tokens(path: Path) -> DesignTokens:
    try:
        return DesignTokens.load(path)
    except Exception as exc:
        raise OnboardError(f"{path} is not a valid tokens.json: {exc}") from exc


def _build_theme(
    brand: _Brand, writer: _ClientWriter, result: OnboardResult, display: str
) -> DesignTokens | None:
    """Mode (a) from a template, else mode (b); returns the tokens (None: keep existing)."""
    tokens: DesignTokens | None = None
    if brand.template is not None:
        reason: str | None = None
        try:
            extracted = extract_tokens(brand.template, name=display)
            reason = _unusable(extracted.tokens)
            tokens = None if reason else extracted.tokens
        except Exception as exc:
            reason = f"extraction failed: {exc}"
        if tokens is not None:
            result.theme_mode = "a (extracted from the template)"
            result.theme_notes += [f"extraction limitation: {g}" for g in EXTRACTION_GAPS[:2]]
            if brand.tokens is not None:
                result.theme_notes.append("tokens.json supplied but unused: the template wins")
            writer.copy(brand.template, "theme/template.pptx")
            if brand.template.suffix.lower() == ".potx":
                result.warnings.append(
                    "template is a .potx; copied as theme/template.pptx unchanged — re-save it "
                    "as .pptx if a consumer cannot open it"
                )
        elif brand.tokens is None:
            raise OnboardError(
                f"theme extraction from {brand.template.name} was not usable ({reason}) and "
                "no tokens.json was supplied to fall back on (mode b). Supply a tokens.json "
                "in the brand folder, or a different template."
            )
        else:
            result.warnings.append(
                f"template {brand.template.name} not usable ({reason}); fell back to the "
                "supplied tokens.json (mode b)"
            )
    if tokens is None and brand.tokens is not None:
        tokens = _load_supplied_tokens(brand.tokens)
        result.theme_mode = (
            "b (supplied tokens.json; template fallback)"
            if brand.template is not None
            else "b (supplied tokens.json)"
        )
    if tokens is None:
        if writer.exists("theme/tokens.json"):
            result.theme_mode = "kept existing"
            return None
        raise OnboardError(
            "no theme source: the brand folder needs a template (.pptx/.potx, e.g. "
            "template.pptx) to extract from, or a tokens.json"
        )
    writer.write_text("theme/tokens.json", _tokens_json(tokens))
    return tokens


def _tokens_json(tokens: DesignTokens) -> str:
    import json

    return json.dumps(tokens.model_dump(mode="json"), indent=2) + "\n"


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------


def _font_info(path: Path) -> FontFileReport:
    report = FontFileReport(name=path.name)
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        report.license_note = "license not checked"
        return report
    try:
        font = TTFont(str(path), lazy=True, fontNumber=0)
        names = font["name"]
        family = names.getDebugName(16) or names.getDebugName(1)
        report.family = str(family) if family else None
        fs_type = int(font["OS/2"].fsType) if "OS/2" in font else None
        note = names.getDebugName(13)
        font.close()
    except Exception as exc:
        report.license_note = f"license not checked ({type(exc).__name__})"
        return report
    report.license_checked = True
    report.fs_type = fs_type
    if fs_type is None:
        report.license_note = "no OS/2 table; embedding permission unknown"
    else:
        report.restricted = bool(fs_type & FS_RESTRICTED)
        labels = [label for bit, label in _FS_LABELS if fs_type & bit]
        report.license_note = f"fsType={fs_type} (" + (", ".join(labels) or "installable") + ")"
    if note:
        report.license_note += f"; licence text: {str(note).strip()[:80]}"
    return report


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _check_fonts(
    tokens: DesignTokens | None, brand: _Brand, writer: _ClientWriter, result: OnboardResult
) -> None:
    from autodeck.design.fonts import is_available

    for font in brand.fonts:
        report = _font_info(font)
        result.font_files.append(report)
        writer.copy(font, f"theme/fonts/{font.name}")
        if report.restricted:
            result.warnings.append(
                f"font {font.name}: restricted-license embedding ({report.license_note}); "
                "do not embed it in delivered decks without clearing the licence"
            )
    if result.font_files and not all(f.license_checked for f in result.font_files):
        result.warnings.append("font licence not checked (fontTools is not installed)")
    if tokens is None:
        return
    supplied = {_norm(f.family) for f in result.font_files if f.family}
    supplied |= {_norm(f.stem.split("-")[0]) for f in brand.fonts}
    for family in sorted(tokens.typography.families()):
        if is_available(family):
            status = "available"
        elif _norm(family) in supplied:
            status = "supplied"
        else:
            status = "missing"
            result.warnings.append(
                f"font family {family!r} is not installed and not in the brand folder; builds "
                "refuse to render without it (install it, or set AUTODECK_FONT_DIRS)"
            )
        result.families.append(FontReport(family, status))
    if any(f.status == "supplied" for f in result.families):
        result.warnings.append(
            "supplied fonts are stored in theme/fonts/ but builds resolve fonts from fonts/ "
            "or AUTODECK_FONT_DIRS; point AUTODECK_FONT_DIRS at theme/fonts/ to use them"
        )


# ---------------------------------------------------------------------------
# Icons, decks, text files
# ---------------------------------------------------------------------------


def _svg_problem(path: Path) -> str | None:
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError) as exc:
        return f"does not parse: {exc}"
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        return "root element is not <svg>"
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() in ("script", "foreignobject"):
            return "contains a script or foreignObject"
    return None


def _copy_icons(brand: _Brand, writer: _ClientWriter, result: OnboardResult) -> None:
    for icon in brand.icons:
        problem = _svg_problem(icon)
        if problem:
            result.icons_skipped.append(f"{icon.name}: {problem}")
            continue
        writer.copy(icon, f"theme/icons/{icon.name}")
        result.icons_copied.append(icon.name)
    if result.icons_skipped:
        result.warnings.append(f"{len(result.icons_skipped)} icon(s) skipped as invalid SVG")


def _ingest_decks(
    brand: _Brand, writer: _ClientWriter, result: OnboardResult
) -> dict[str, Any] | None:
    from autodeck.design.reference.service import ingest_client_decks
    from autodeck.knowledge.loader import KnowledgeError as _KE

    for deck in brand.decks:
        writer.copy(deck, f"decks/{deck.name}")
        result.decks_copied.append(deck.name)
    if not writer.namespace.own_root.joinpath("decks").is_dir():
        return None
    try:
        ingested = ingest_client_decks(writer.namespace)
    except _KE as exc:  # an unreadable deck: report, keep the rest of the onboarding
        result.warnings.append(f"reference ingestion failed: {exc}")
        return None
    writer.written.extend(ingested.written)
    result.deck_count = len(ingested.decks)
    result.slide_count = int(ingested.aggregate.get("slide_count", 0))
    result.profile_files = len(ingested.written)
    result.gap_count = len(ingested.gaps.get("gaps", []))
    return ingested.aggregate if ingested.decks else None


_STUBS = {
    "client.md": (
        "# {name}\n\n"
        f"{STUB_MARKER} describe this client: who they are, their market, their audience and "
        "what they care about. Onboarding wrote this stub because no client.md was supplied.\n"
    ),
    "value_prop.md": (
        "# {name} - value proposition\n\n"
        f"{STUB_MARKER} write how this client likes to be positioned (framing only; never "
        "evidence). Onboarding wrote this stub because no value_prop.md was supplied.\n"
    ),
}


def find_stubs(client_root: Path) -> list[str]:
    """Client files that still hold an onboarding stub (the `TODO:` marker)."""
    found: list[str] = []
    for name in _STUBS:
        path = Path(client_root) / name
        if path.is_file() and STUB_MARKER in path.read_text(encoding="utf-8", errors="replace"):
            found.append(name)
    return found


def _write_documents(
    brand: _Brand, writer: _ClientWriter, result: OnboardResult, display: str,
    aggregate: dict[str, Any] | None,
) -> None:  # fmt: skip
    for relative, source in brand.docs.items():
        writer.copy(source, relative)
        result.copied_docs.append(relative)
    for name, template in _STUBS.items():
        if not writer.exists(name):
            writer.write_text(name, template.format(name=display))
            result.stubs.append(name)
    if result.stubs:
        result.warnings.append(
            f"{', '.join(result.stubs)}: stub(s) written with a {STUB_MARKER} marker; fill "
            "them in before drafting"
        )
    if not writer.exists("style/headers.yaml") and aggregate:
        profile = aggregate.get("header", {}).get("profile")
        if profile:
            text = (
                "# PROPOSED from the client's past decks (autodeck onboard). Not in use: copy\n"
                "# what you agree with into headers.yaml, which a person curates.\n"
                + yaml.safe_dump(profile, sort_keys=True)
            )
            writer.write_text("style/headers.proposed.yaml", text)
            result.headers_proposed = True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def onboard_client(
    knowledge_root: Path,
    client: str,
    brand_folder: Path,
    *,
    name: str | None = None,
    template: Path | None = None,
    force: bool = False,
) -> OnboardResult:
    """Turn `brand_folder` into `knowledge_root/clients/<client>/`.

    Raises:
        OnboardError: bad client name, existing client without `force`, no usable theme
            source, or an invalid supplied `tokens.json`. A folder this call created is
            removed again on failure; with `force`, nothing is ever deleted.
        ClientIsolationError: a target would resolve outside the client's folder.
    """
    validate_client_name(client)
    knowledge_root = Path(knowledge_root)
    root = knowledge_root / CLIENTS_DIR / client
    if root.exists() and not force:
        raise OnboardError(
            f"client {client!r} already exists at {root}; pass --force to add or replace "
            "what the brand folder supplies (nothing is deleted)"
        )
    display = (name or client).strip() or client
    brand = _scan_brand(Path(brand_folder), template)
    has_theme = (root / "theme" / "tokens.json").exists()
    if brand.template is None and brand.tokens is None and not has_theme:
        raise OnboardError(
            "no theme source: the brand folder needs a template (.pptx/.potx, e.g. "
            "template.pptx) to extract from, or a tokens.json"
        )
    if brand.tokens is not None and brand.template is None:
        _load_supplied_tokens(brand.tokens)  # refuse an invalid file before writing anything

    namespace = ClientNamespace(client=client, knowledge_root=knowledge_root)
    fresh = not root.exists()
    root.mkdir(parents=True, exist_ok=True)
    try:
        return _onboard(namespace, brand, display)
    except Exception:
        if fresh:  # a folder this call created and nothing else touched: leave no husk
            shutil.rmtree(root, ignore_errors=True)
        raise


def _onboard(namespace: ClientNamespace, brand: _Brand, display: str) -> OnboardResult:
    writer = _ClientWriter(namespace)
    result = OnboardResult(client=namespace.client, root=namespace.own_root)

    tokens = _build_theme(brand, writer, result, display)
    if tokens is None:
        existing = namespace.own_root / "theme" / "tokens.json"
        try:
            tokens = DesignTokens.load(existing)
        except Exception as exc:
            result.warnings.append(f"existing theme/tokens.json is unreadable: {exc}")
    if tokens is not None:
        result.colour_count = len(tokens.palette.as_scheme())
    _check_fonts(tokens, brand, writer, result)
    _copy_icons(brand, writer, result)
    aggregate = _ingest_decks(brand, writer, result)
    _write_documents(brand, writer, result, display, aggregate)
    result.written = list(writer.written)
    return result


__all__ = [
    "STUB_MARKER",
    "OnboardError",
    "OnboardResult",
    "find_stubs",
    "onboard_client",
    "validate_client_name",
]
