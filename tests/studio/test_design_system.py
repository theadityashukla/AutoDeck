"""Task 23.1: the design system's functions (`design.py` below the marker): the default
system, tokens per deck, the palette check, slugs, and the versioned store."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from autodeck.design.free_layout import contrast_ratio
from autodeck.knowledge.loader import ClientIsolationError
from autodeck.studio.design import (
    CONTRAST_LARGE,
    CONTRAST_TEXT,
    DEFAULT_TEXT_PAIRS,
    DesignDraft,
    DesignSystemStore,
    PaletteFinding,
    TextPair,
    check_draft,
    check_palette,
    deck_tokens,
    default_design_system,
    design_tokens,
    findings_text,
    slugify,
)
from autodeck.studio.engagement import create_engagement
from autodeck.studio.errors import (
    DesignSystemNotFoundError,
    InvalidSegmentError,
    PaletteRefusedError,
)
from autodeck.studio.models import DEFAULT_SYSTEM_ID, DesignPalette, DesignSystemRef
from tests.studio.helpers import (
    CLIENT,
    OTHER_CLIENT,
    PROJECT,
    T0,
    T1,
    dev_tokens,
    flow_draft,
    load_fixture_deck,
)


def test_the_default_system_is_the_base_palette_with_no_concept() -> None:
    base = dev_tokens()
    system = default_design_system(base)
    assert (system.id, system.version, system.marker) == (DEFAULT_SYSTEM_ID, 1, "provisional")
    assert system.is_default and system.created_at is None
    assert system.concept == "" and system.rules == [] and system.roles == {}
    assert system.palette.dk2 == base.palette.dk2.upper()
    assert system.background == "lt1"
    assert [(p.text, p.ground) for p in system.text_pairs] == list(DEFAULT_TEXT_PAIRS)
    assert system.made_by == "default"


def test_design_tokens_replace_only_the_ten_colour_slots() -> None:
    base = dev_tokens()
    draft = flow_draft("Demand curve")
    tokens = design_tokens(draft.palette, base)
    assert tokens.palette.lt2 == "0F1D30" and tokens.palette.dk1 == "0B1420"
    assert tokens.palette.hyperlink == base.palette.hyperlink
    assert tokens.typography == base.typography and tokens.spacing == base.spacing
    assert tokens.name == f"{base.name} + design"
    assert design_tokens(None, base) is base
    assert base.palette.lt2 != "0F1D30"  # the base object is not changed


def test_deck_tokens_follow_the_decks_reference() -> None:
    base = dev_tokens()
    deck = load_fixture_deck()
    assert deck_tokens(deck, base) is base
    draft = flow_draft("Demand curve")
    ref = DesignSystemRef(id="demand-curve", version=1, palette=draft.palette)
    designed = deck.model_copy(update={"design_system": ref})
    assert deck_tokens(designed, base).palette.lt2 == "0F1D30"
    legacy = deck.model_copy(update={"design_system": DesignSystemRef(id="x", version=1)})
    assert deck_tokens(legacy, base) is base


def test_a_good_palette_passes_and_a_bad_one_reports_every_measured_ratio() -> None:
    draft = flow_draft("Demand curve")
    assert check_draft(draft) == []
    bad = DesignPalette.model_validate({**draft.palette.model_dump(), "accent1": "#2B4466"})
    pairs = [
        TextPair(text="lt1", ground="lt2"),
        TextPair(text="accent1", ground="lt2"),
        TextPair(text="accent1", ground="accent4", large_only=True),
    ]
    findings = check_palette(bad, background="lt2", text_pairs=pairs)
    assert [(f.text, f.ground, f.needed, f.why) for f in findings] == [
        ("accent1", "lt2", CONTRAST_TEXT, "text pair"),
        ("accent1", "accent4", CONTRAST_LARGE, "large text pair"),
    ]
    assert findings[0].ratio == round(contrast_ratio("2B4466", "0F1D30"), 2)


def test_charts_need_dk2_readable_on_the_background() -> None:
    draft = flow_draft("Demand curve")
    dark_dk2 = DesignPalette.model_validate({**draft.palette.model_dump(), "dk2": "#1A2E4A"})
    findings = check_palette(
        dark_dk2, background="lt2", text_pairs=[TextPair(text="lt1", ground="lt2")]
    )
    assert [(f.text, f.ground, f.why) for f in findings] == [
        ("dk2", "lt2", "charts draw labels in dk2")
    ]
    assert (
        check_palette(
            dark_dk2, background="dk2", text_pairs=[TextPair(text="lt1", ground="dk2")]
        )
        == []
    )


def test_findings_text_is_exact() -> None:
    findings = [
        PaletteFinding("accent1", "lt2", 2.312, 4.5, "text pair"),
        PaletteFinding("dk2", "lt2", 1.4, 4.5, "charts draw labels in dk2"),
    ]
    assert findings_text(findings) == (
        "- accent1 on lt2: 2.31:1, needs 4.5:1 (text pair)\n"
        "- dk2 on lt2: 1.40:1, needs 4.5:1 (charts draw labels in dk2)"
    )
    assert findings_text([]) == ""


def test_draft_structure_is_validated() -> None:
    draft = flow_draft("Demand curve")
    data = draft.model_dump()
    with pytest.raises(ValidationError, match="every colour slot needs a role"):
        DesignDraft.model_validate({**data, "roles": {"lt2": "night"}})
    with pytest.raises(ValidationError, match="no normal-size text colour"):
        DesignDraft.model_validate(
            {**data, "text_pairs": [{"text": "lt1", "ground": "accent4"}]}
        )
    with pytest.raises(ValidationError, match="a slot on itself"):
        TextPair(text="lt1", ground="lt1")
    ref = draft.preview_ref("p0001-b")
    assert ref.palette == draft.palette and ref.marker == "provisional"


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Shelf price", "shelf-price"),
        ("  Demand / Curve! ", "demand-curve"),
        ("???", "design"),
        ("Default", "design-default"),
        ("x" * 50 + " y", "x" * 40),
    ],
)
def test_slugify(name: str, slug: str) -> None:
    assert slugify(name) == slug


def _engagement(knowledge_root: Path, workspace_root: Path, client: str = CLIENT):
    return create_engagement(
        client, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root, now=T0
    )


def test_the_store_adds_versions_and_never_rewrites_them(
    knowledge_root: Path, workspace_root: Path
) -> None:
    engagement = _engagement(knowledge_root, workspace_root)
    store = DesignSystemStore(engagement, base=dev_tokens())
    assert store.ids() == [] and store.versions("demand-curve") == []
    assert store.versions(DEFAULT_SYSTEM_ID) == [1]
    assert store.load(DEFAULT_SYSTEM_ID, 1).is_default
    first = store.add(flow_draft("Demand curve"), marker="decided", now=T0)
    assert (first.id, first.version, first.marker, first.created_at) == (
        "demand-curve",
        1,
        "decided",
        T0,
    )
    path = engagement.paths.design_system_version("demand-curve", 1)
    assert path.is_file()
    written = path.read_bytes()
    second = store.add(flow_draft("Demand curve"), marker="provisional", now=T1)
    assert second.version == 2 and path.read_bytes() == written
    assert store.ids() == ["demand-curve"] and store.versions("demand-curve") == [1, 2]
    assert store.load("demand-curve", 1) == first
    named = store.add(flow_draft("Itemised"), marker="decided", now=T1, system_id="house")
    assert (named.id, named.version) == ("house", 1)
    deck = load_fixture_deck().model_copy(update={"design_system": second.ref()})
    assert store.for_deck(deck) == second
    assert store.for_deck(load_fixture_deck()).is_default


def test_the_store_refuses_bad_palettes_and_unknown_versions(
    knowledge_root: Path, workspace_root: Path
) -> None:
    engagement = _engagement(knowledge_root, workspace_root)
    store = DesignSystemStore(engagement, base=dev_tokens())
    draft = flow_draft("Demand curve")
    bad = draft.model_copy(
        update={
            "palette": DesignPalette.model_validate(
                {**draft.palette.model_dump(), "accent1": "#2B4466"}
            )
        }
    )
    with pytest.raises(PaletteRefusedError, match=r"accent1 on lt2: \d\.\d\d:1, needs 4\.5:1"):
        store.add(bad, marker="decided", now=T0)
    assert store.ids() == []
    with pytest.raises(DesignSystemNotFoundError):
        store.load("demand-curve", 1)
    with pytest.raises(DesignSystemNotFoundError):
        store.load(DEFAULT_SYSTEM_ID, 2)
    with pytest.raises(InvalidSegmentError):
        store.add(draft, marker="decided", now=T0, system_id=DEFAULT_SYSTEM_ID)
    with pytest.raises(InvalidSegmentError):
        store.load("../x", 1)
    without_base = DesignSystemStore(engagement)
    with pytest.raises(DesignSystemNotFoundError, match="base tokens"):
        without_base.load(DEFAULT_SYSTEM_ID, 1)


def test_a_version_file_symlinked_into_another_client_is_refused(
    knowledge_root: Path, workspace_root: Path
) -> None:
    other = _engagement(knowledge_root, workspace_root, client=OTHER_CLIENT)
    DesignSystemStore(other, base=dev_tokens()).add(
        flow_draft("Demand curve"), marker="decided", now=T0
    )
    mine = _engagement(knowledge_root, workspace_root)
    mine.paths.design_systems.mkdir(parents=True)
    (mine.paths.design_systems / "demand-curve").symlink_to(
        other.paths.design_system_dir("demand-curve")
    )
    with pytest.raises(ClientIsolationError):
        DesignSystemStore(mine, base=dev_tokens()).load("demand-curve", 1)
