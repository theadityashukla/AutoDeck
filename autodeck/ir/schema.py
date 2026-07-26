"""JSON-Schema export for LLM structured output.

Providers disagree about JSON Schema, and they disagree in ways that fail at request time
rather than at review time. Gemini's schema dialect rejects `$ref` and several validation
keywords; OpenAI-compatible strict mode (which Groq serves) requires every property to
appear in `required` and forbids open objects; Anthropic accepts near-full JSON Schema as
a tool input schema. Emitting one shape and hoping is how a provider swap turns into a
day of debugging, so the differences are handled here, once, behind a flavour argument.

The models themselves stay authoritative — this module only reshapes what pydantic emits.

Owning phase: 0 (task 0.2).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel

SchemaFlavor = Literal["standard", "strict", "gemini"]
"""Which dialect to emit.

- `standard` — pydantic's own output, `$defs` intact. Fine for Anthropic tool schemas and
  for writing the schema to disk.
- `strict` — OpenAI-compatible strict mode (Groq, and Gemini's OpenAI shim): every
  property listed in `required`, `additionalProperties: false` on every object.
- `gemini` — the native Gemini `response_schema` dialect: references inlined, unsupported
  keywords dropped.
"""

#: Keywords the Gemini schema dialect does not accept. `$ref` is absent because references
#: are inlined before this set is applied.
_GEMINI_UNSUPPORTED: frozenset[str] = frozenset(
    {
        "$defs",
        "$schema",
        "additionalProperties",
        "allOf",
        "const",
        "default",
        "discriminator",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "oneOf",
        "patternProperties",
        "prefixItems",
        "uniqueItems",
    }
)

#: Keys whose values are maps of *name -> schema*, so their keys are data, not keywords.
_SCHEMA_MAPS: frozenset[str] = frozenset({"properties", "$defs", "patternProperties"})

#: Keys whose value is a single nested schema.
_SCHEMA_VALUES: frozenset[str] = frozenset({"items", "not", "additionalProperties"})

#: Keys whose value is a list of nested schemas.
_SCHEMA_LISTS: frozenset[str] = frozenset({"anyOf", "oneOf", "allOf", "prefixItems"})


class SchemaError(RuntimeError):
    """Raised when a model cannot be expressed in the requested dialect."""


def _map_schema_objects(node: Any, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> Any:
    """Apply `fn` to every schema object in `node`, depth-first, structure-aware.

    Naively walking every dict would treat a *property named* `default` as the `default`
    keyword. Distinguishing schema positions from data positions is the whole point.
    """
    if isinstance(node, list):
        return [_map_schema_objects(item, fn) for item in node]
    if not isinstance(node, dict):
        return node

    result: dict[str, Any] = {}
    for key, value in fn(dict(node)).items():
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            result[key] = {name: _map_schema_objects(sub, fn) for name, sub in value.items()}
        elif key in _SCHEMA_VALUES or key in _SCHEMA_LISTS:
            result[key] = _map_schema_objects(value, fn)
        else:
            result[key] = value
    return result


def _inline_refs(node: Any, defs: dict[str, Any], stack: tuple[str, ...] = ()) -> Any:
    """Replace every `$ref` with the definition it points at.

    Raises `SchemaError` on a recursive model rather than recursing forever. No IR model is
    currently recursive; if one becomes so, the Gemini path needs a real answer and a silent
    stack overflow is the worst way to find that out.
    """
    if isinstance(node, list):
        return [_inline_refs(item, defs, stack) for item in node]
    if not isinstance(node, dict):
        return node

    ref = node.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        if name in stack:
            raise SchemaError(
                f"recursive model definition {name!r} (via {' -> '.join(stack)}); "
                "the Gemini schema dialect cannot express it because it has no $ref"
            )
        if name not in defs:
            raise SchemaError(f"unresolved schema reference {ref!r}")
        target = _inline_refs(defs[name], defs, (*stack, name))
        siblings = {k: v for k, v in node.items() if k != "$ref"}
        # Sibling keys (description, title) annotate the reference site and win.
        return {**target, **_inline_refs(siblings, defs, stack)}

    return {key: _inline_refs(value, defs, stack) for key, value in node.items()}


def _require_all_properties(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI strict mode: every declared property must be listed in `required`.

    Optionality is expressed by the property's type being nullable, which pydantic already
    emits for `X | None`. This is a schema-shape requirement, not a semantic change.
    """
    if schema.get("type") == "object" and isinstance(schema.get("properties"), dict):
        schema["required"] = list(schema["properties"].keys())
        schema.setdefault("additionalProperties", False)
    return schema


def _strip_gemini_unsupported(schema: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in schema.items() if k not in _GEMINI_UNSUPPORTED}


def export_schema(model: type[BaseModel], flavor: SchemaFlavor = "standard") -> dict[str, Any]:
    """Return the JSON Schema for `model` in the requested provider dialect.

    Args:
        model: any IR model — typically `Deck`, `Slide`, or a per-step response model.
        flavor: see `SchemaFlavor`.

    Raises:
        SchemaError: the model cannot be expressed in that dialect.
    """
    schema = model.model_json_schema(ref_template="#/$defs/{model}")

    if flavor == "standard":
        return schema

    if flavor == "strict":
        return _map_schema_objects(schema, _require_all_properties)

    defs = schema.pop("$defs", {})
    inlined = _inline_refs(schema, defs)
    return _map_schema_objects(inlined, _strip_gemini_unsupported)


def schema_digest(schema: dict[str, Any]) -> str:
    """Stable SHA-256 of a schema.

    Part of the provider cache key, so a schema edit invalidates cached responses instead
    of resuming a run against a contract that has since changed.
    """
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
