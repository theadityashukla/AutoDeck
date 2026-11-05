"""Client onboarding (4.1): brand folder to client namespace, and the client theme in builds.

Synthetic brand folders only; no model call. The template is `extract.build_synthetic_template`,
past decks come from `tests.test_reference_decks.build_deck`, fonts are built with fontTools
(skipped where it is absent).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from autodeck.cli import app
from autodeck.design import onboard as onboard_module
from autodeck.design.onboard import (
    STUB_MARKER,
    OnboardError,
    find_stubs,
    onboard_client,
    validate_client_name,
)
from autodeck.design.theme.extract import build_synthetic_template
from autodeck.design.theme.resolve import DEFAULT_TOKENS, resolve_tokens_path
from autodeck.design.theme.tokens import DesignTokens, Palette, Typography
from autodeck.ir.store import IRStore
from autodeck.knowledge.context_assembler import ClientNamespace
from autodeck.knowledge.loader import ClientIsolationError, KnowledgeLoader
from tests.test_reference_decks import TITLES, build_deck
from tests.two_clients import ALPHA, BETA, THEME_HEX, TwoClientWorld, canary

runner = CliRunner()

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<path d="M0 0h24v24H0z"/></svg>'
)


# -- fixtures ---------------------------------------------------------------------------


def snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def make_font(path: Path, *, family: str, fs_type: int) -> Path:
    pytest.importorskip("fontTools")
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef"])
    builder.setupCharacterMap({})
    pen = TTGlyphPen(None)
    builder.setupGlyf({".notdef": pen.glyph()})
    builder.setupHorizontalMetrics({".notdef": (500, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": family, "styleName": "Regular"})
    builder.setupOS2(fsType=fs_type)
    builder.setupPost()
    path.parent.mkdir(parents=True, exist_ok=True)
    builder.save(str(path))
    return path


@pytest.fixture
def knowledge(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    (root / "clients").mkdir(parents=True)
    return root


@pytest.fixture
def brand(tmp_path: Path) -> Path:
    folder = tmp_path / "brand"
    folder.mkdir()
    return folder


def with_template(brand: Path) -> Path:
    return build_synthetic_template(brand / "template.pptx")


def with_tokens(brand: Path, *, major: str = "Carlito", minor: str = "Carlito") -> Path:
    tokens = DesignTokens(
        name="Supplied",
        palette=Palette(accent1="123456"),
        typography=Typography(major=major, minor=minor),
    )
    return tokens.save(brand / "tokens.json")


def onboard(knowledge: Path, brand: Path, client: str = "acme", **kw):  # type: ignore[no-untyped-def]
    return onboard_client(knowledge, client, brand, **kw)


# -- theme: mode a, mode b, fallback, refusal --------------------------------------------


def test_mode_a_extracts_tokens_and_copies_the_template(knowledge: Path, brand: Path) -> None:
    with_template(brand)
    result = onboard(knowledge, brand, name="Acme Corp")
    root = knowledge / "clients" / "acme"
    tokens = DesignTokens.load(root / "theme" / "tokens.json")
    assert tokens.name == "Acme Corp"
    assert tokens.palette.accent1 == "8C2F39"
    assert tokens.typography.major == "Inter Display"
    assert (root / "theme" / "template.pptx").is_file()
    assert result.theme_mode.startswith("a") and result.colour_count == 12
    assert any("extraction limitation" in n for n in result.theme_notes)
    loaded = KnowledgeLoader(knowledge).load_client("acme")
    assert loaded.tokens_path and loaded.template_path


def test_mode_b_validates_and_copies_tokens(knowledge: Path, brand: Path) -> None:
    with_tokens(brand)
    result = onboard(knowledge, brand)
    saved = DesignTokens.load(knowledge / "clients" / "acme" / "theme" / "tokens.json")
    assert saved.palette.accent1 == "123456"
    assert result.theme_mode.startswith("b")
    assert not (knowledge / "clients" / "acme" / "theme" / "template.pptx").exists()


def test_an_invalid_tokens_file_is_refused_and_nothing_is_left(
    knowledge: Path, brand: Path
) -> None:
    (brand / "tokens.json").write_text(json.dumps({"colors": {"primary": "#fff"}}))
    with pytest.raises(OnboardError, match=r"not a valid tokens\.json"):
        onboard(knowledge, brand)
    assert not (knowledge / "clients" / "acme").exists()


def test_a_broken_template_falls_back_to_supplied_tokens(knowledge: Path, brand: Path) -> None:
    (brand / "template.pptx").write_bytes(b"not a zip")
    with_tokens(brand)
    result = onboard(knowledge, brand)
    assert result.theme_mode.startswith("b") and "fallback" in result.theme_mode
    assert any("fell back" in w for w in result.warnings)
    assert not (knowledge / "clients" / "acme" / "theme" / "template.pptx").exists()


def test_a_broken_template_without_tokens_stops_clearly(knowledge: Path, brand: Path) -> None:
    (brand / "template.pptx").write_bytes(b"not a zip")
    with pytest.raises(OnboardError, match=r"no tokens\.json was supplied"):
        onboard(knowledge, brand)
    assert not (knowledge / "clients" / "acme").exists()


def test_unusable_extracted_tokens_fall_back(
    knowledge: Path, brand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_template(brand)
    with_tokens(brand)
    monkeypatch.setattr(onboard_module, "_unusable", lambda tokens: "forced for the test")
    result = onboard(knowledge, brand)
    assert "fallback" in result.theme_mode
    assert any("forced for the test" in w for w in result.warnings)


def test_no_theme_source_is_refused_saying_what_is_needed(knowledge: Path, brand: Path) -> None:
    (brand / "client.md").write_text("# Acme\n")
    with pytest.raises(OnboardError, match=r"template .* or a tokens\.json"):
        onboard(knowledge, brand)
    assert not (knowledge / "clients" / "acme").exists()


def test_an_explicit_template_option_picks_the_template(knowledge: Path, brand: Path) -> None:
    build_synthetic_template(brand / "corporate-master.pptx")
    onboard(knowledge, brand, template=Path("corporate-master.pptx"))
    assert (knowledge / "clients" / "acme" / "theme" / "template.pptx").is_file()
    assert not (knowledge / "clients" / "acme" / "decks").exists()


# -- fonts -------------------------------------------------------------------------------


def test_fonts_are_reported_available_or_missing(knowledge: Path, brand: Path) -> None:
    with_tokens(brand, major="Carlito", minor="Zzz Nonexistent Sans")
    result = onboard(knowledge, brand)
    status = {f.family: f.status for f in result.families}
    assert status["Zzz Nonexistent Sans"] == "missing"
    assert any("Zzz Nonexistent Sans" in w for w in result.warnings)
    from autodeck.design.fonts import is_available

    if is_available("Carlito"):
        assert status["Carlito"] == "available"


def test_a_supplied_font_is_copied_and_makes_its_family_supplied(
    knowledge: Path, brand: Path
) -> None:
    make_font(brand / "fonts" / "Zzz-Brand-Regular.ttf", family="Zzz Brand", fs_type=0)
    with_tokens(brand, major="Zzz Brand", minor="Zzz Brand")
    result = onboard(knowledge, brand)
    assert (
        knowledge / "clients" / "acme" / "theme" / "fonts" / "Zzz-Brand-Regular.ttf"
    ).is_file()
    assert {f.family: f.status for f in result.families} == {"Zzz Brand": "supplied"}
    [report] = result.font_files
    assert report.license_checked and not report.restricted and report.fs_type == 0


def test_a_restricted_embedding_font_is_flagged(knowledge: Path, brand: Path) -> None:
    make_font(brand / "Locked-Regular.ttf", family="Locked", fs_type=0x0002)
    make_font(brand / "Open-Regular.ttf", family="Open", fs_type=0x0008)
    with_tokens(brand)
    result = onboard(knowledge, brand)
    restricted = {f.name: f.restricted for f in result.font_files}
    assert restricted == {"Locked-Regular.ttf": True, "Open-Regular.ttf": False}
    assert any("Locked-Regular.ttf" in w and "restricted" in w for w in result.warnings)
    assert not any("Open-Regular.ttf" in w for w in result.warnings)
    assert "1 restricted" in "\n".join(result.summary_lines())


def test_without_fonttools_the_license_is_recorded_as_not_checked(
    knowledge: Path, brand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (brand / "Plain-Regular.ttf").write_bytes(b"\x00\x01 not really a font")
    with_tokens(brand)
    import builtins

    real_import = builtins.__import__

    def no_fonttools(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name.startswith("fontTools"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_fonttools)
    result = onboard(knowledge, brand)
    [report] = result.font_files
    assert not report.license_checked and report.license_note == "license not checked"
    assert any("licence not checked" in w for w in result.warnings)


# -- icons -------------------------------------------------------------------------------


def test_icons_are_validated_copied_or_skipped(knowledge: Path, brand: Path) -> None:
    with_tokens(brand)
    (brand / "icons").mkdir()
    (brand / "icons" / "good.svg").write_text(SVG)
    (brand / "icons" / "broken.svg").write_text("<svg><path")
    (brand / "icons" / "notsvg.svg").write_text("<html/>")
    (brand / "icons" / "script.svg").write_text(SVG.replace("<path", "<script/><path"))
    result = onboard(knowledge, brand)
    icons = knowledge / "clients" / "acme" / "theme" / "icons"
    assert sorted(p.name for p in icons.iterdir()) == ["good.svg"]
    assert result.icons_copied == ["good.svg"]
    assert len(result.icons_skipped) == 3
    assert any("3 icon(s) skipped" in w for w in result.warnings)


# -- decks, stubs, headers ---------------------------------------------------------------


def test_past_decks_are_copied_and_ingested_into_profiles(knowledge: Path, brand: Path) -> None:
    with_template(brand)
    build_deck(brand / "past" / "Margin Review.pptx")
    result = onboard(knowledge, brand)
    decks = knowledge / "clients" / "acme" / "decks"
    assert (decks / "Margin Review.pptx").is_file()
    assert len(list(decks.glob("*.profile.json"))) == 1
    assert (decks / "profile.json").is_file() and (decks / "gaps.json").is_file()
    assert result.deck_count == 1 and result.slide_count > 0 and result.profile_files >= 3
    assert not (decks / "template.pptx").exists()  # the template is not a past deck
    loaded = KnowledgeLoader(knowledge).load_client("acme")
    assert loaded.reference_profile and len(loaded.decks) == 1


def test_stubs_carry_a_todo_the_loader_accepts(knowledge: Path, brand: Path) -> None:
    with_tokens(brand)
    result = onboard(knowledge, brand)
    root = knowledge / "clients" / "acme"
    assert sorted(result.stubs) == ["client.md", "value_prop.md"]
    for name in result.stubs:
        assert STUB_MARKER in (root / name).read_text()
    assert find_stubs(root) == ["client.md", "value_prop.md"]
    KnowledgeLoader(knowledge).load_client("acme")  # both required files exist


def test_supplied_text_files_are_copied_not_stubbed(knowledge: Path, brand: Path) -> None:
    with_tokens(brand)
    (brand / "client.md").write_text("# Acme\n\nReal text.\n")
    (brand / "value_prop.md").write_text("# VP\n\nFraming.\n")
    (brand / "headers.yaml").write_text("style: assertion\nmax_words: 9\n")
    result = onboard(knowledge, brand)
    root = knowledge / "clients" / "acme"
    assert result.stubs == [] and find_stubs(root) == []
    assert (root / "client.md").read_text().startswith("# Acme")
    assert yaml.safe_load((root / "style" / "headers.yaml").read_text())["max_words"] == 9
    assert not (root / "style" / "headers.proposed.yaml").exists()


def test_derived_headers_are_proposed_never_written_as_headers_yaml(
    knowledge: Path, brand: Path
) -> None:
    with_tokens(brand)
    build_deck(brand / "Margin Review.pptx")
    result = onboard(knowledge, brand)
    style = knowledge / "clients" / "acme" / "style"
    assert result.headers_proposed
    assert not (style / "headers.yaml").exists()
    proposed = yaml.safe_load((style / "headers.proposed.yaml").read_text())
    assert "style" in proposed and "max_words" in proposed
    assert "headers.proposed.yaml" in "\n".join(result.summary_lines())


def test_the_summary_never_contains_deck_text(knowledge: Path, brand: Path) -> None:
    with_tokens(brand)
    build_deck(brand / "Margin Review.pptx")
    text = "\n".join(onboard(knowledge, brand).summary_lines())
    for title in (*TITLES.values(), "Retail margin review", "Where we are today"):
        assert title not in text


# -- refusals and --force ----------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["", "../escape", "a/b", "..", ".hidden", "has space", "x" * 80]
)
def test_a_bad_client_name_is_refused(knowledge: Path, brand: Path, name: str) -> None:
    with_tokens(brand)
    with pytest.raises(OnboardError, match="invalid client name"):
        onboard(knowledge, brand, client=name)
    assert snapshot_tree(knowledge) == {}
    assert validate_client_name("northwind-retail") == "northwind-retail"


def test_an_existing_client_is_refused_without_force(knowledge: Path, brand: Path) -> None:
    with_tokens(brand)
    (knowledge / "clients" / "acme").mkdir()
    (knowledge / "clients" / "acme" / "client.md").write_text("mine")
    before = snapshot_tree(knowledge)
    with pytest.raises(OnboardError, match="already exists"):
        onboard(knowledge, brand)
    assert snapshot_tree(knowledge) == before


def test_force_replaces_only_what_is_supplied_and_deletes_nothing(
    knowledge: Path, brand: Path
) -> None:
    with_tokens(brand)
    build_deck(brand / "First.pptx")
    onboard(knowledge, brand)
    root = knowledge / "clients" / "acme"
    (root / "client.md").write_text("# Curated\n\nWritten by a person.\n")
    (root / "extra.txt").write_text("keep me")
    (root / "theme" / "icons").mkdir(parents=True, exist_ok=True)
    (root / "theme" / "icons" / "old.svg").write_text(SVG)
    before = snapshot_tree(root)

    second = brand.parent / "brand2"
    second.mkdir()
    (second / "value_prop.md").write_text("# New framing\n")
    result = onboard(knowledge, second, force=True)

    after = snapshot_tree(root)
    assert set(before) <= set(after)  # nothing deleted
    assert after["client.md"] == before["client.md"]  # curated text is not replaced by a stub
    assert after["extra.txt"] == before["extra.txt"]
    assert after["theme/tokens.json"] == before["theme/tokens.json"]  # kept: none supplied
    assert after["decks/First.pptx"] == before["decks/First.pptx"]
    assert after["value_prop.md"] == b"# New framing\n"
    assert result.theme_mode == "kept existing" and result.stubs == []


def test_force_replaces_a_supplied_theme(knowledge: Path, brand: Path) -> None:
    with_tokens(brand)
    onboard(knowledge, brand)
    with_template(brand)
    (brand / "tokens.json").unlink()
    onboard(knowledge, brand, force=True)
    tokens = DesignTokens.load(knowledge / "clients" / "acme" / "theme" / "tokens.json")
    assert tokens.palette.accent1 == "8C2F39"


# -- nothing outside the client folder ---------------------------------------------------


def test_nothing_is_written_outside_the_clients_folder(
    knowledge: Path, brand: Path, tmp_path: Path
) -> None:
    other = knowledge / "clients" / "other"
    other.mkdir()
    (other / "client.md").write_text("other")
    with_template(brand)
    build_deck(brand / "Past.pptx")
    (brand / "i.svg").write_text(SVG)
    (brand / "client.md").write_text("x")
    before_other = snapshot_tree(other)
    before_brand = snapshot_tree(brand)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = snapshot_tree(tmp_path / "outside")

    onboard(knowledge, brand)

    assert snapshot_tree(other) == before_other
    assert snapshot_tree(brand) == before_brand  # the brand folder is only read
    assert snapshot_tree(outside) == sentinel
    top = {p.name for p in (knowledge / "clients").iterdir()}
    assert top == {"acme", "other"}
    assert {p.name for p in knowledge.iterdir()} == {"clients"}


def test_a_symlink_into_another_client_cannot_be_written_through(
    knowledge: Path, brand: Path
) -> None:
    other = knowledge / "clients" / "other"
    other.mkdir()
    (other / "client.md").write_text("other client's text")
    with_tokens(brand)
    (brand / "client.md").write_text("supplied")
    acme = knowledge / "clients" / "acme"
    acme.mkdir()
    (acme / "client.md").symlink_to(other / "client.md")
    with pytest.raises(ClientIsolationError):
        onboard(knowledge, brand, force=True)
    assert (other / "client.md").read_text() == "other client's text"


def test_writes_go_through_the_clients_namespace_guard(
    knowledge: Path, brand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_tokens(brand)
    guarded: list[Path] = []
    real = ClientNamespace.guard

    def spy(self, path):  # type: ignore[no-untyped-def]
        guarded.append(Path(path))
        return real(self, path)

    monkeypatch.setattr(ClientNamespace, "guard", spy)
    result = onboard(knowledge, brand)
    assert result.written
    assert {p for p in result.written} <= {p for p in guarded}


# -- the CLI -----------------------------------------------------------------------------


def test_the_cli_onboards_and_prints_a_summary(knowledge: Path, brand: Path) -> None:
    with_template(brand)
    build_deck(brand / "Margin Review.pptx")
    result = runner.invoke(
        app,
        ["onboard", "--client", "acme", "--brand", str(brand), "--name", "Acme",
         "--knowledge-root", str(knowledge)],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "theme: mode a" in result.output and "decks: 1" in result.output
    for title in TITLES.values():
        assert title not in result.output
    again = runner.invoke(
        app,
        [
            "onboard",
            "--client",
            "acme",
            "--brand",
            str(brand),
            "--knowledge-root",
            str(knowledge),
        ],
    )
    assert again.exit_code == 1 and "already exists" in again.output


def test_the_cli_refuses_a_bad_name(knowledge: Path, brand: Path) -> None:
    with_tokens(brand)
    result = runner.invoke(
        app,
        [
            "onboard",
            "--client",
            "../x",
            "--brand",
            str(brand),
            "--knowledge-root",
            str(knowledge),
        ],
    )
    assert result.exit_code == 1 and "invalid client name" in result.output


# -- the client theme in builds ----------------------------------------------------------


def test_resolution_prefers_explicit_then_client_then_default(
    knowledge: Path, brand: Path
) -> None:
    with_tokens(brand)
    onboard(knowledge, brand)
    own = knowledge / "clients" / "acme" / "theme" / "tokens.json"
    assert resolve_tokens_path(None, knowledge_root=knowledge, client="acme") == own
    assert (
        resolve_tokens_path(None, knowledge_root=knowledge, client="nobody") == DEFAULT_TOKENS
    )
    explicit = Path("config/tokens/aptos.json")
    assert resolve_tokens_path(explicit, knowledge_root=knowledge, client="acme") == explicit


def test_a_tokens_symlink_into_another_client_is_a_build_error(
    knowledge: Path, brand: Path
) -> None:
    with_tokens(brand)
    onboard(knowledge, brand, client="victim")
    mine = knowledge / "clients" / "mine" / "theme"
    mine.mkdir(parents=True)
    (mine / "tokens.json").symlink_to(
        knowledge / "clients" / "victim" / "theme" / "tokens.json"
    )
    with pytest.raises(ClientIsolationError):
        resolve_tokens_path(None, knowledge_root=knowledge, client="mine")


@pytest.fixture(scope="module")
def drafted(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    with pytest.MonkeyPatch.context() as mp:
        world = TwoClientWorld(tmp_path_factory.mktemp("theme-wiring"), mp)
        for client in (ALPHA, BETA):
            world.b1(client)
        yield world


def deck_theme(world: TwoClientWorld, client: str) -> str:
    return IRStore(world.runs, f"b1-{client}").load().theme_ref


@pytest.mark.parametrize("client", [ALPHA, BETA])
def test_a_client_with_its_own_tokens_gets_them_in_its_deck(
    drafted: TwoClientWorld, client: str
) -> None:
    theme_ref = Path(deck_theme(drafted, client))
    assert theme_ref == drafted.knowledge / "clients" / client / "theme" / "tokens.json"
    tokens = DesignTokens.load(theme_ref)
    assert tokens.name == canary(client, "THEME")
    assert tokens.palette.accent1 == THEME_HEX[client]
    other = BETA if client == ALPHA else ALPHA
    assert other not in str(theme_ref)
    assert THEME_HEX[other] not in theme_ref.read_text()


@pytest.mark.parametrize("client", [ALPHA, BETA])
def test_the_clients_theme_never_reaches_the_other_clients_run(
    drafted: TwoClientWorld, client: str
) -> None:
    other = BETA if client == ALPHA else ALPHA
    run = drafted.runs / f"b1-{other}"
    for path in run.rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert canary(client, "THEME") not in text and THEME_HEX[client] not in text


def test_a_client_without_tokens_falls_back_to_the_dev_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = TwoClientWorld(tmp_path, monkeypatch)
    (world.knowledge / "clients" / BETA / "theme" / "tokens.json").unlink()
    world.b1(BETA)
    assert deck_theme(world, BETA) == str(DEFAULT_TOKENS)


def test_an_explicit_tokens_option_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = TwoClientWorld(tmp_path, monkeypatch)
    build = world.start_b1(ALPHA)
    explicit = Path("config/tokens/dev.json")
    world.cli("draft", build.run_id, "--tokens", str(explicit), *world.data_roots)
    assert deck_theme(world, ALPHA) == str(explicit)


def test_the_ui_does_not_override_the_client_theme_by_default() -> None:
    from autodeck.ui.api import DEFAULT_TOKENS as UI_DEFAULT
    from autodeck.ui.api import Roots
    from autodeck.ui.jobs import _tokens_args

    assert UI_DEFAULT == DEFAULT_TOKENS
    assert _tokens_args(Roots()) == []
    assert _tokens_args(Roots(tokens=Path("custom/tokens.json"))) == [
        "--tokens",
        "custom/tokens.json",
    ]
