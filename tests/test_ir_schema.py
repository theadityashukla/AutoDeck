"""JSON-Schema export: the three provider dialects.

These matter because a schema that a provider rejects fails at request time, deep inside
an agent run, with an error message about JSON rather than about the model.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from autodeck.ir.models import Block, Claim, Deck, IRModel, Slide
from autodeck.ir.schema import export_schema, schema_digest


def walk(node: Any) -> list[dict[str, Any]]:
    """Every schema object in the tree, for whole-document assertions."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(walk(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(walk(item))
    return found


# ---------------------------------------------------------------------------
# standard
# ---------------------------------------------------------------------------


def test_standard_keeps_refs_and_forbids_extra_properties() -> None:
    schema = export_schema(Deck, "standard")
    assert "$defs" in schema
    assert schema["additionalProperties"] is False


def test_a1_survives_into_the_exported_schema() -> None:
    """The structured-output contract itself tells the writer a claim needs a citation.

    Since B55 the IR's `Claim` may be `unsourced` in a normal deck, so its own schema no longer
    carries `minItems`; the writer never fills that model directly. What the writer fills is
    `ProposedClaim`, and there a claim still cannot be proposed without a citation — an
    unsourced statement is a separate, explicitly named block kind.
    """
    from autodeck.agents.content import ProposedClaim

    citations = export_schema(ProposedClaim, "standard")["properties"]["citations"]
    assert citations["minItems"] == 1
    with pytest.raises(ValueError, match="cited claim needs at least one citation"):
        Claim(text="x", citations=[])


# ---------------------------------------------------------------------------
# strict (OpenAI-compatible)
# ---------------------------------------------------------------------------


def test_strict_requires_every_property() -> None:
    schema = export_schema(Slide, "strict")
    for obj in walk(schema):
        if obj.get("type") == "object" and "properties" in obj:
            assert set(obj["required"]) == set(obj["properties"])
            assert obj["additionalProperties"] is False


def test_strict_keeps_optional_fields_nullable() -> None:
    """Optionality is expressed in the type, not by omission from `required`."""
    text = export_schema(Block, "strict")["properties"]["text"]
    assert {"type": "null"} in text["anyOf"]


# ---------------------------------------------------------------------------
# Structure-aware walking
# ---------------------------------------------------------------------------


def test_a_property_named_like_a_keyword_is_not_stripped() -> None:
    """`default` in a *properties* map is a field name, not the `default` keyword."""

    class Tricky(IRModel):
        default: str
        const: int

    schema = export_schema(Tricky, "strict")
    assert set(schema["properties"]) == {"default", "const"}


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------


def test_schema_digest_is_stable_and_order_independent() -> None:
    assert schema_digest({"a": 1, "b": 2}) == schema_digest({"b": 2, "a": 1})


def test_schema_digest_changes_with_the_schema() -> None:
    """A changed contract must invalidate cached provider responses (task 0.3)."""
    assert schema_digest(export_schema(Claim)) != schema_digest(export_schema(Block))


def test_a_genuine_union_is_left_alone() -> None:
    """A real either/or union must survive export."""

    class Holder(BaseModel):
        value: str | int

    assert "anyOf" in export_schema(Holder, "standard")["properties"]["value"]
