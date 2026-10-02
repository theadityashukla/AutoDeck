"""JSON-Schema export: the three provider dialects.

These matter because a schema that a provider rejects fails at request time, deep inside
an agent run, with an error message about JSON rather than about the model.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from autodeck.ir.models import Block, Claim, Deck, IRModel, Slide
from autodeck.ir.schema import SchemaError, export_schema, schema_digest


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
    """The structured-output contract itself tells the model a claim needs a citation."""
    citations = export_schema(Claim, "standard")["properties"]["citations"]
    assert citations["minItems"] == 1


# ---------------------------------------------------------------------------
# strict (OpenAI-compatible; Groq)
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
# gemini
# ---------------------------------------------------------------------------


def test_gemini_inlines_all_references() -> None:
    schema = export_schema(Deck, "gemini")
    assert "$defs" not in schema
    assert all("$ref" not in obj for obj in walk(schema))


def test_gemini_drops_unsupported_keywords() -> None:
    schema = export_schema(Deck, "gemini")
    for obj in walk(schema):
        assert not {"$defs", "additionalProperties", "default", "allOf"} & set(obj)


def test_gemini_preserves_the_a1_constraint_through_inlining() -> None:
    """Inlining must not quietly drop the constraint that carries the invariant."""
    schema = export_schema(Deck, "gemini")
    min_items = [obj["minItems"] for obj in walk(schema) if "minItems" in obj]
    assert 1 in min_items


def test_gemini_inlining_keeps_a_reference_site_description() -> None:
    class Inner(IRModel):
        value: int

    class Outer(IRModel):
        first: Inner
        second: Inner

    schema = export_schema(Outer, "gemini")
    assert schema["properties"]["first"]["properties"]["value"]["type"] == "integer"
    assert schema["properties"]["second"]["properties"]["value"]["type"] == "integer"


def test_recursive_models_fail_loudly_rather_than_hanging() -> None:
    class Node(BaseModel):
        children: list[Node] = []

    Node.model_rebuild()
    with pytest.raises(SchemaError, match="recursive model definition"):
        export_schema(Node, "gemini")


# ---------------------------------------------------------------------------
# Structure-aware walking
# ---------------------------------------------------------------------------


def test_a_property_named_like_a_keyword_is_not_stripped() -> None:
    """`default` in a *properties* map is a field name, not the `default` keyword."""

    class Tricky(IRModel):
        default: str
        const: int

    schema = export_schema(Tricky, "gemini")
    assert set(schema["properties"]) == {"default", "const"}


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------


def test_schema_digest_is_stable_and_order_independent() -> None:
    assert schema_digest({"a": 1, "b": 2}) == schema_digest({"b": 2, "a": 1})


def test_schema_digest_changes_with_the_schema() -> None:
    """A changed contract must invalidate cached provider responses (task 0.3)."""
    assert schema_digest(export_schema(Claim)) != schema_digest(export_schema(Block))


def test_gemini_optional_fields_use_nullable_not_anyof() -> None:
    """The bug this prevents is silent, which is why it needs a test.

    Pydantic emits `X | None` as a two-branch `anyOf`. Gemini's native response_schema
    accepts that shape and then omits the field entirely when X is an array of objects —
    no error, no warning. The Phase 2a planner returned briefs where scalar fields arrived
    and every `list[Model] | None` field was missing on every call, across three models.
    """
    from pydantic import BaseModel

    class Nested(BaseModel):
        id: str

    class Holder(BaseModel):
        required_scalar: str
        optional_scalar: str | None = None
        optional_objects: list[Nested] | None = None

    schema = export_schema(Holder, "gemini")
    properties = schema["properties"]

    assert "anyOf" not in properties["optional_scalar"]
    assert properties["optional_scalar"] == {"type": "string", "nullable": True} | {
        k: v for k, v in properties["optional_scalar"].items() if k not in ("type", "nullable")
    }
    optional_objects = properties["optional_objects"]
    assert "anyOf" not in optional_objects
    assert optional_objects["type"] == "array"
    assert optional_objects["nullable"] is True
    assert optional_objects["items"]["type"] == "object"


def test_collapsing_a_union_keeps_its_description() -> None:
    """Annotations sit on the union, not the branch. Dropping them would leave the model
    with a field and no idea what it is for."""
    from pydantic import BaseModel, Field

    class Holder(BaseModel):
        note: str | None = Field(default=None, description="Why this matters.")

    assert export_schema(Holder, "gemini")["properties"]["note"]["description"] == (
        "Why this matters."
    )


def test_a_genuine_union_is_left_alone() -> None:
    """Only nullable two-branch unions collapse. A real either/or must survive."""
    from pydantic import BaseModel

    class Holder(BaseModel):
        value: str | int

    assert "anyOf" in export_schema(Holder, "gemini")["properties"]["value"]
