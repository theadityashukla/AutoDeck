"""JSON-Schema export for LLM structured output.

Providers disagree about JSON Schema, and they disagree in ways that fail at request time
rather than at review time. OpenAI-compatible strict mode (Mistral, OpenAI, Nebius)
requires every property to appear in `required` and forbids open objects; Anthropic
accepts near-full JSON Schema as a tool input schema. Emitting one shape and hoping is how a provider swap turns into a
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

SchemaFlavor = Literal["standard", "strict"]
"""Which dialect to emit.

- `standard` — pydantic's own output, `$defs` intact. Fine for Anthropic tool schemas and
  for writing the schema to disk.
- `strict` — OpenAI-compatible strict mode (Mistral, OpenAI, Nebius): every
  property listed in `required`, `additionalProperties: false` on every object.
"""

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


def _require_all_properties(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI strict mode: every declared property must be listed in `required`.

    Optionality is expressed by the property's type being nullable, which pydantic already
    emits for `X | None`. This is a schema-shape requirement, not a semantic change.
    """
    if schema.get("type") == "object" and isinstance(schema.get("properties"), dict):
        schema["required"] = list(schema["properties"].keys())
        schema.setdefault("additionalProperties", False)
    return schema


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

    raise SchemaError(f"unknown schema flavor {flavor!r}")


def schema_digest(schema: dict[str, Any]) -> str:
    """Stable SHA-256 of a schema.

    Part of the provider cache key, so a schema edit invalidates cached responses instead
    of resuming a run against a contract that has since changed.
    """
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
