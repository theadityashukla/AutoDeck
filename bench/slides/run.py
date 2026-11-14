"""The slide bench harness: one model, one slide to design, one rendered slide back.

See SPEC.md next to this file; it is the contract. In short, for every
(model, case, concept, feedback, repeat) a trial gives the model one slide brief and one tool,
`write_slide`, validates and layout-checks what comes back (feeding errors back to the model),
renders a clean slide, and optionally shows the model its own render once. Results go to
`--out`, outside the repository, with a contact sheet per model.

This is a measuring tool, not product code. It imports from `autodeck.studio` and v2 and
changes neither. Notes on the places where it had to choose:

* **Images.** v2's `converse` carries text only. `ImageMessage` (a `Message` with an `images`
  field) and `_BenchOpenAIMixin` add the smallest support: the mixin builds the normal
  request, then replaces the content of an image-carrying user message with a text part plus
  `image_url` data-URL parts. The image goes in a user message *after* the tool result,
  because Chat Completions accepts only text inside a `tool` message.
* **Usage.** `completion_tokens` from OpenAI already includes reasoning tokens (reported
  separately as `completion_tokens_details.reasoning_tokens`, a subset), so cost counts
  `prompt_tokens` and `completion_tokens` and the reasoning count is recorded for information.
* **Temperature.** OpenAI's newer models reject a non-default temperature, so the mixin
  removes it from the request body.
* **Renderability is part of QA.** Layout QA does not notice a glyph id that is not in the
  icon library; the renderer then draws a placeholder. The harness therefore also builds the
  PPTX in memory on every attempt, and a placeholder is returned to the model as a finding
  (`[render]`).
* **No cache.** `ProviderConfig.cache` is left `None`; every call is a fresh call.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import typing
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from autodeck.design.fonts import FontNotFoundError
from autodeck.design.theme.tokens import DesignTokens, Palette
from autodeck.ir import models as v2
from autodeck.ir.schema import export_schema
from autodeck.providers.base import (
    AssistantTurn,
    BaseProvider,
    ImageInput,
    Message,
    ProviderConfig,
    ProviderResponseError,
    ToolCall,
    ToolSpec,
    Usage,
)
from autodeck.providers.openai_compat import OpenAICompatProvider
from autodeck.providers.registry import PROVIDERS, api_key_env
from autodeck.studio import models as studio_models
from autodeck.studio.models import DeckArtifact, Slide
from autodeck.studio.render import build_pptx, render_previews
from autodeck.studio.render_adapter import check_slide
from autodeck.studio.tool_args import SLIDE_FIELDS_HELP, ToolArgs

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parents[1]
DEFAULT_TOKENS_PATH = REPO_ROOT / "config" / "tokens" / "dev.json"

TOOL_NAME = "write_slide"
PREVIEW_DPI = 120
CALL_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_OUTPUT_TOKENS = 32000

NUDGE_TEXT = (
    "You did not call write_slide. Design the slide by calling write_slide with the whole "
    "slide (blocks and layout); do not answer in prose."
)
VISUAL_QUESTION = (
    "This is the rendered slide. If it can be clearly improved, call write_slide once more; "
    "otherwise reply DONE."
)
ACCEPTED_TEXT = "Accepted: the slide is valid and passes the layout checks."

Status = Literal["clean", "unclean", "failed", "budget_stopped", "skipped", "dry_run"]


# ---------------------------------------------------------------------------
# Inputs: cases, concepts, prices, tokens
# ---------------------------------------------------------------------------


class BenchInputError(RuntimeError):
    """A case, concept, price file or command line the harness cannot use."""


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Figure(_Loose):
    value: str
    label: str = ""


class ChartSeriesIn(_Loose):
    name: str
    values: list[float]


class ChartIn(_Loose):
    kind: str
    categories: list[str]
    series: list[ChartSeriesIn]
    emphasis: list[str] = Field(default_factory=list)


class CaseContent(_Loose):
    points: list[str] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    chart: ChartIn | None = None


class Case(_Loose):
    id: str = Field(min_length=1)
    title: str
    intent: str = ""
    content: CaseContent = Field(default_factory=CaseContent)
    notes: str = ""


class Concept(_Loose):
    id: str = Field(min_length=1)
    name: str = ""
    concept: str = ""
    rules: list[str] = Field(default_factory=list)
    palette: dict[str, str] = Field(default_factory=dict)
    roles: dict[str, str] = Field(default_factory=dict)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BenchInputError(f"{path}: not readable as YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise BenchInputError(f"{path}: must be a mapping at the top level")
    return raw


def load_case(path: Path) -> Case:
    try:
        case = Case.model_validate(_load_yaml(path))
    except ValidationError as exc:
        raise BenchInputError(f"{path}: invalid case: {exc}") from exc
    if case.id != path.stem:
        raise BenchInputError(f"{path}: id {case.id!r} must equal the file name {path.stem!r}")
    return case


def load_concept(path: Path) -> Concept:
    try:
        concept = Concept.model_validate(_load_yaml(path))
    except ValidationError as exc:
        raise BenchInputError(f"{path}: invalid concept: {exc}") from exc
    if concept.id != path.stem:
        raise BenchInputError(
            f"{path}: id {concept.id!r} must equal the file name {path.stem!r}"
        )
    return concept


def list_case_ids(bench_dir: Path) -> list[str]:
    return sorted(p.stem for p in (bench_dir / "cases").glob("*.yaml"))


def resolve_cases(spec: str, bench_dir: Path) -> list[Case]:
    ids = list_case_ids(bench_dir) if spec.strip() == "all" else _csv(spec)
    if not ids:
        raise BenchInputError(f"no cases found in {bench_dir / 'cases'}")
    cases = []
    for case_id in ids:
        path = bench_dir / "cases" / f"{case_id}.yaml"
        if not path.is_file():
            raise BenchInputError(f"unknown case {case_id!r}: {path} does not exist")
        cases.append(load_case(path))
    return cases


def resolve_concepts(spec: str, bench_dir: Path) -> list[Concept]:
    concepts = []
    for concept_id in _csv(spec):
        path = bench_dir / "concepts" / f"{concept_id}.yaml"
        if not path.is_file():
            raise BenchInputError(f"unknown concept {concept_id!r}: {path} does not exist")
        concepts.append(load_concept(path))
    if not concepts:
        raise BenchInputError("no concepts given")
    return concepts


def _csv(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


@dataclass(frozen=True)
class Price:
    """Assumed US dollars per million tokens."""

    input: float
    output: float


def load_prices(path: Path) -> dict[str, Price]:
    raw = _load_yaml(path)
    models = raw.get("models")
    if not isinstance(models, dict):
        raise BenchInputError(f"{path}: needs a `models` mapping")
    prices: dict[str, Price] = {}
    for name, entry in models.items():
        try:
            prices[str(name)] = Price(
                input=float(entry["input"]), output=float(entry["output"])
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BenchInputError(
                f"{path}: {name}: needs numeric `input` and `output`"
            ) from exc
    return prices


def tokens_for_concept(concept: Concept, base_path: Path = DEFAULT_TOKENS_PATH) -> DesignTokens:
    """The default tokens with the concept's palette laid over them, in memory.

    A concept changes palette colours only: fonts, sizes and spacing stay the default's. One
    `DesignTokens` object feeds both layout QA (contrast reads `tokens.palette`) and the
    renderer (the theme and every colour token are built from the same object), so the
    override reaches both. The repository's token files are never written.
    """
    base = DesignTokens.load(base_path)
    if not concept.palette:
        return base
    slots = set(Palette.model_fields)
    merged = base.palette.model_dump()
    for slot, value in concept.palette.items():
        if slot not in slots:
            raise BenchInputError(
                f"concept {concept.id!r}: unknown palette slot {slot!r}; "
                f"slots are {', '.join(sorted(slots))}"
            )
        merged[slot] = str(value).strip().lstrip("#").upper()
    try:
        palette = Palette.model_validate(merged)
    except ValidationError as exc:
        raise BenchInputError(f"concept {concept.id!r}: bad palette colour: {exc}") from exc
    return base.model_copy(update={"palette": palette, "name": f"{base.name} + {concept.id}"})


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

_ALIASES: dict[int, str] = {}


def _alias(name: str, annotation: Any) -> Any:
    _ALIASES[id(annotation)] = name
    return annotation


_COLOR = _alias("ColorToken", v2.ColorToken)
_ROLE = _alias("TextRole", v2.TextRole)
_HALIGN = _alias("HAlign", v2.HAlign)
_VANCHOR = _alias("VAnchor", v2.VAnchor)
_SHAPE = _alias("ShapeKind", v2.ShapeKind)
_BLOCKKIND = _alias("BlockKind", studio_models.BlockKind)
_CHARTKIND = _alias("ChartKind", v2.ChartKind)

_VALUE_SETS: dict[str, Any] = {
    "ColorToken": _COLOR,
    "TextRole": _ROLE,
    "HAlign": _HALIGN,
    "VAnchor": _VANCHOR,
    "ShapeKind": _SHAPE,
    "BlockKind": _BLOCKKIND,
    "ChartKind": _CHARTKIND,
}

_SKIPPED_FIELDS = {
    ("Slide", "marker"),
    ("Slide", "serves"),
    ("Block", "source_note"),
}


def _type_str(annotation: Any) -> str:
    alias = _ALIASES.get(id(annotation))
    if alias:
        return alias
    origin = get_origin(annotation)
    if origin is Literal:
        return " | ".join(repr(a) for a in get_args(annotation))
    if origin in (typing.Union, getattr(__import__("types"), "UnionType", None)):
        parts = [a for a in get_args(annotation) if a is not type(None)]
        text = " or ".join(_type_str(a) for a in parts)
        return f"{text} (optional)" if len(parts) != len(get_args(annotation)) else text
    if origin is list:
        return f"list of {_type_str(get_args(annotation)[0])}"
    if origin is typing.Annotated:
        return _type_str(get_args(annotation)[0])
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation)


def _describe_model(cls: type[BaseModel]) -> str:
    lines = [f"{cls.__name__}:"]
    for name, info in cls.model_fields.items():
        if (cls.__name__, name) in _SKIPPED_FIELDS:
            continue
        annotation = info.annotation
        if get_origin(annotation) is typing.Annotated:
            annotation = get_args(annotation)[0]
        text = f"  {name}: {_type_str(annotation)}"
        if not info.is_required():
            default = info.get_default(call_default_factory=True)
            text += f" = {default!r}"
        if info.description:
            text += f" -- {info.description}"
        lines.append(text)
    return "\n".join(lines)


def vocabulary_text() -> str:
    """The elements and fields the layout accepts, generated from the models."""
    from autodeck.design.icons.library import icon_names

    classes: list[type[BaseModel]] = [
        Slide,
        studio_models.Block,
        studio_models.ChartData,
        v2.ChartSeries,
        v2.IconRef,
        v2.FreeLayout,
        v2.Placement,
        v2.TextElement,
        v2.VisualElement,
        v2.ShapeElement,
    ]
    parts = [_describe_model(c) for c in classes]
    sets = ["Value sets:"]
    for name, annotation in _VALUE_SETS.items():
        sets.append(f"  {name}: " + ", ".join(str(a) for a in get_args(annotation)))
    notes = [
        "Layout elements (FreeLayout.elements) are `text`, `chart`, `figure`, `icon` "
        "or `shape`.",
        "A `text` element places a text block, a `chart`/`figure`/`icon` element places the "
        "block of that kind, a `shape` places a block-less panel, band, rule or marker. "
        "Every block is placed exactly once. A `diagram` element is not available.",
        "A `figure` block draws only a captioned empty frame (there is no image library).",
        f"icon `glyph_id` must be one of: {', '.join(icon_names())}.",
        "Placement `x`, `y`, `w`, `h` are percent of the slide's width and height.",
    ]
    return "\n\n".join([*parts, "\n".join(sets), "\n".join(notes)])


def master_text(tokens: DesignTokens) -> str:
    """Slide size, safe area, type roles, minimum size, source band."""
    width = tokens.slide_width_emu / 12700
    height = tokens.slide_height_emu / 12700
    spacing = tokens.spacing
    typo = tokens.typography
    sx = spacing.safe_area / width * 100
    sy = spacing.safe_area / height * 100
    mx = spacing.margin_x / width * 100
    my = spacing.margin_y / height * 100
    lines = [
        f"Slide: {width:g} x {height:g} pt (16:9). Placements are percent of the slide, so 1% "
        f"of the width is {width / 100:g}pt and 1% of the height is {height / 100:g}pt.",
        f"Safe area: text and visuals must stay inside {spacing.safe_area:g}pt of every edge, "
        f"that is x from {sx:.1f}% to {100 - sx:.1f}% and y from {sy:.1f}% to "
        f"{100 - sy:.1f}%. A shape may bleed to the slide edge; text may not.",
        f"Page margins used by the master: {spacing.margin_x:g}pt left and right "
        f"({mx:.1f}%), {spacing.margin_y:g}pt top and bottom ({my:.1f}%).",
        f"Fonts: headings {typo.major}, body {typo.minor}; line height {typo.line_height:g}. "
        "Fonts are fixed; only colours can change.",
        "Type roles (point size): "
        + ", ".join(
            f"{role} {getattr(typo, role):g}pt"
            for role in ("display", "title", "heading", "body", "caption")
        )
        + ", label (caption size, capitals, letter-spaced). "
        + f"Minimum text size {typo.minimum:g}pt; "
        "`size_pt` overrides a role's size.",
        "Source band: none. This slide draws no source line, so the whole safe area is yours.",
    ]
    return "\n".join(lines)


def palette_text(tokens: DesignTokens, concept: Concept) -> str:
    lines = []
    for slot, hex_value in tokens.palette.as_scheme().items():
        key = {"hlink": "hyperlink", "folHlink": "followed_hyperlink"}.get(slot, slot)
        if key in ("hyperlink", "followed_hyperlink"):
            continue
        role = concept.roles.get(key, "")
        lines.append(f"- {key}: #{hex_value}" + (f" -- {role}" if role else ""))
    lines.append("Colour tokens are used by name (for example `accent1`), never as hex.")
    return "\n".join(lines)


def build_system_prompt(bench_dir: Path, tokens: DesignTokens, concept: Concept) -> str:
    path = bench_dir / "prompts" / "slide.md"
    try:
        template = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BenchInputError(f"system prompt not readable: {path}: {exc}") from exc
    filled = {
        "{{MASTER}}": master_text(tokens),
        "{{PALETTE}}": palette_text(tokens, concept),
        "{{VOCABULARY}}": vocabulary_text(),
    }
    for placeholder, text in filled.items():
        template = template.replace(placeholder, text)
    return template


def build_user_text(case: Case, concept: Concept) -> str:
    content = case.content
    lines = [
        "# Slide brief",
        f"Slide id: {case.id}",
        f"Headline: {case.title}",
    ]
    if case.intent.strip():
        lines += ["", "What the slide must make the audience conclude:", case.intent.strip()]
    lines += ["", "## Content (the only content you may put on the slide)"]
    if content.points:
        lines += ["", "Points:", *[f"- {p}" for p in content.points]]
    if content.figures:
        lines += ["", "Key figures:", *[f"- {f.value}: {f.label}" for f in content.figures]]
    if content.chart is not None:
        chart = content.chart
        lines += ["", f"Chart ({chart.kind}), categories: " + ", ".join(chart.categories)]
        for series in chart.series:
            lines.append(f"- {series.name}: " + ", ".join(f"{v:g}" for v in series.values))
        if chart.emphasis:
            lines.append("Emphasise: " + ", ".join(chart.emphasis))
    if case.notes.strip():
        lines += ["", "Notes (what matters; not for the slide):", case.notes.strip()]
    lines += ["", "## Design direction"]
    if concept.id == "none" or not (concept.concept.strip() or concept.rules):
        lines.append("None given. Use your own judgement.")
    else:
        if concept.name:
            lines.append(f"Name: {concept.name}")
        if concept.concept.strip():
            lines.append(f"Concept: {concept.concept.strip()}")
        if concept.rules:
            lines += ["Rules:", *[f"- {r}" for r in concept.rules]]
    lines += ["", f"Design this slide and call {TOOL_NAME}."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Talking to a model
# ---------------------------------------------------------------------------


class WriteSlideArgs(ToolArgs):
    """`write_slide`: the whole slide, blocks and free layout together."""

    slide: Slide = Field(description=SLIDE_FIELDS_HELP)


WRITE_SLIDE_TOOL = ToolSpec(
    name=TOOL_NAME,
    description=(
        "Write the slide: its blocks (the words, chart or icons) and its free layout (where "
        "each block goes, plus any shapes). Call it again with the whole corrected slide to "
        "change it."
    ),
    args_model=WriteSlideArgs,
)


@dataclass(frozen=True)
class ImageMessage(Message):
    """A user message that also carries images. Understood by `_BenchOpenAIMixin`."""

    images: tuple[ImageInput, ...] = ()


@dataclass(frozen=True)
class BenchUsage(Usage):
    """`Usage` plus what OpenAI reports inside the counts (for information, not added)."""

    reasoning_tokens: int = 0
    cached_tokens: int = 0


class _BenchOpenAIMixin:
    """Image support and OpenAI-model fixes for an `OpenAICompatProvider` subclass."""

    @staticmethod
    def _usage(payload: dict[str, Any]) -> Usage:
        usage = payload.get("usage") or {}
        completion = usage.get("completion_tokens_details") or {}
        prompt = usage.get("prompt_tokens_details") or {}
        return BenchUsage(
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            reasoning_tokens=int(completion.get("reasoning_tokens", 0) or 0),
            cached_tokens=int(prompt.get("cached_tokens", 0) or 0),
        )

    def build_converse_request(
        self,
        *,
        messages: list[Message],
        tools: list[ToolSpec],
        system: str | None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        parent = typing.cast(Any, super())
        url, headers, body = parent.build_converse_request(
            messages=messages, tools=tools, system=system
        )
        # Newer OpenAI models accept only the default temperature.
        body.pop("temperature", None)
        offset = 1 if system else 0
        for index, message in enumerate(messages):
            images = getattr(message, "images", ())
            if not images:
                continue
            provider = typing.cast(OpenAICompatProvider, self)
            parts: list[dict[str, Any]] = [{"type": "text", "text": message.content}]
            parts.extend(provider._image_part(image) for image in images)
            body["messages"][index + offset]["content"] = parts
        return url, headers, body


#: Models that reject function tools together with reasoning on Chat Completions
#: ("Function tools with reasoning_effort are not supported ... use /v1/responses"). They are
#: called through the Responses endpoint so they can be run with reasoning on.
RESPONSES_MODEL_PREFIXES = ("gpt-5.6",)
REASONING_LEVELS = ("none", "low", "medium", "high", "xhigh")


def uses_responses(spec: str, api: str = "auto") -> bool:
    if api == "responses":
        return True
    if api == "chat":
        return False
    return spec.partition(":")[2].startswith(RESPONSES_MODEL_PREFIXES)


def effective_reasoning(spec: str, reasoning: str, api: str = "auto") -> str:
    """What the trial record says about reasoning: the requested level where it is sent
    (Responses path), else "default" (Chat Completions models run at their own default)."""
    return reasoning if uses_responses(spec, api) else "default"


class _BenchResponsesMixin:
    """OpenAI `/v1/responses` with function tools, reasoning and image input.

    Presents the same `converse` interface as the Chat Completions adapter. Stateless
    (`store: false`): every call resends the whole conversation as input items. Reasoning
    items are not carried between calls.
    """

    reasoning_effort: str = "medium"

    @property
    def _responses_url(self) -> str:
        return f"{typing.cast(OpenAICompatProvider, self).base_url.rstrip('/')}/responses"

    def build_converse_request(
        self,
        *,
        messages: list[Message],
        tools: list[ToolSpec],
        system: str | None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        provider = typing.cast(OpenAICompatProvider, self)
        items: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": m.tool_call_id,
                        "output": m.content,
                    }
                )
            elif m.role == "assistant":
                if m.content:
                    items.append({"role": "assistant", "content": m.content})
                for c in m.tool_calls:
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": c.id,
                            "name": c.name,
                            "arguments": json.dumps(c.arguments, ensure_ascii=False),
                        }
                    )
            else:
                images = getattr(m, "images", ())
                if images:
                    parts: list[dict[str, Any]] = [{"type": "input_text", "text": m.content}]
                    parts += [
                        {
                            "type": "input_image",
                            "image_url": provider._image_part(image)["image_url"]["url"],
                        }
                        for image in images
                    ]
                    items.append({"role": "user", "content": parts})
                else:
                    items.append({"role": "user", "content": m.content})
        body: dict[str, Any] = {
            "model": provider.config.model,
            "input": items,
            "max_output_tokens": provider.config.max_output_tokens,
            "reasoning": {"effort": self.reasoning_effort},
            "store": False,
        }
        if system:
            body["instructions"] = system
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": export_schema(t.args_model, "strict"),
                    "strict": False,
                }
                for t in tools
            ]
            body["tool_choice"] = "auto"
        return self._responses_url, provider._headers(), body

    def parse_converse_response(self, payload: dict[str, Any]) -> AssistantTurn:
        error = payload.get("error")
        if error or payload.get("status") == "failed":
            raise ProviderResponseError(
                f"responses API error: {error or payload.get('status')}"
            )
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for item in payload.get("output") or []:
            kind = item.get("type")
            if kind == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text":
                        text_parts.append(part.get("text", ""))
                    elif part.get("type") == "refusal":
                        text_parts.append(f"[refusal] {part.get('refusal', '')}")
            elif kind == "function_call":
                raw_args = item.get("arguments")
                try:
                    parsed = json.loads(raw_args) if raw_args else {}
                except (TypeError, ValueError):
                    parsed = None
                calls.append(
                    ToolCall(
                        id=str(item.get("call_id") or item.get("id") or ""),
                        name=item.get("name", ""),
                        arguments=parsed
                        if isinstance(parsed, dict)
                        else {"__invalid__": raw_args},
                    )
                )
        if payload.get("status") == "incomplete" and not calls:
            reason = (payload.get("incomplete_details") or {}).get("reason", "unknown")
            text_parts.append(f"[response incomplete: {reason}]")
        usage = payload.get("usage") or {}
        out_details = usage.get("output_tokens_details") or {}
        in_details = usage.get("input_tokens_details") or {}
        return AssistantTurn(
            text="".join(text_parts),
            tool_calls=calls,
            usage=BenchUsage(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                reasoning_tokens=int(out_details.get("reasoning_tokens", 0) or 0),
                cached_tokens=int(in_details.get("cached_tokens", 0) or 0),
            ),
        )


def make_provider(
    spec: str,
    *,
    max_output_tokens: int,
    api_key: str | None = None,
    reasoning: str = "medium",
    api: str = "auto",
) -> BaseProvider:
    """A provider for `provider:model`, with image support, no cache and a long timeout.

    Raises:
        BenchInputError: the spec is malformed, the provider unknown or without image support.
        ProviderAuthError: (v2's) no API key in the environment.
    """
    provider_name, sep, model = spec.partition(":")
    if not sep or not model:
        raise BenchInputError(f"model {spec!r} must be written provider:model")
    cls = PROVIDERS.get(provider_name)
    if cls is None:
        raise BenchInputError(
            f"unknown provider {provider_name!r}; known: {', '.join(sorted(PROVIDERS))}"
        )
    if not issubclass(cls, OpenAICompatProvider):
        raise BenchInputError(
            f"provider {provider_name!r} is not OpenAI-compatible; the bench can send images "
            "only through that wire format"
        )
    responses = uses_responses(spec, api)
    mixin = _BenchResponsesMixin if responses else _BenchOpenAIMixin
    bench_cls = type(f"Bench{cls.__name__}", (mixin, cls), {})
    key = api_key if api_key is not None else os.environ.get(api_key_env(provider_name), "")
    provider = bench_cls(
        ProviderConfig(
            model=model,
            api_key=key,
            timeout=CALL_TIMEOUT_SECONDS,
            max_output_tokens=max_output_tokens,
            cache=None,
        )
    )
    if responses:
        typing.cast(Any, provider).reasoning_effort = reasoning
    return provider


class ConverseModel(typing.Protocol):
    def converse(
        self, messages: list[Message], tools: list[ToolSpec], *, system: str | None = None
    ) -> AssistantTurn: ...


_KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
]


def scrub(text: str) -> str:
    """Remove anything that looks like a key, and any env var secret, from `text`."""
    for name, value in os.environ.items():
        if value and len(value) >= 8 and re.search(r"KEY|TOKEN|SECRET", name, re.I):
            text = text.replace(value, "[redacted]")
    for pattern in _KEY_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


class BudgetStop(RuntimeError):
    """The budget guard refused to start a model call."""


class Ledger:
    """Estimated spend so far, from recorded token counts and assumed prices."""

    def __init__(self, budget: float, spent: float = 0.0) -> None:
        self.budget = budget
        self.spent = spent
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            if self.spent >= self.budget:
                raise BudgetStop(
                    f"estimated spend ${self.spent:.4f} has reached the budget "
                    f"${self.budget:.2f}; no further model calls"
                )

    def add(self, cost: float) -> None:
        with self._lock:
            self.spent += cost

    def exhausted(self) -> bool:
        with self._lock:
            return self.spent >= self.budget


def estimate_cost(price: Price, input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * price.input + output_tokens * price.output) / 1_000_000


# ---------------------------------------------------------------------------
# QA and rendering
# ---------------------------------------------------------------------------

Finding = dict[str, str]


def _wrap_deck(slide: Slide) -> DeckArtifact:
    return DeckArtifact(id="bench", client="bench", project="bench", slides=[slide])


def qa_findings(slide: Slide, tokens: DesignTokens) -> list[Finding]:
    """Layout QA, plus a dry build of the PPTX so a slide the renderer would replace with a
    placeholder (an unknown icon, a chart that cannot be built) is a finding, not a clean
    slide. Never raises for model content; a missing font does raise (nothing is
    honest then)."""
    try:
        found = check_slide(slide, tokens)
        if found:
            return [
                {"block": f.block_id, "check": f.check, "message": f.message} for f in found
            ]
        with tempfile.TemporaryDirectory() as scratch:
            built = build_pptx(
                _wrap_deck(slide), tokens=tokens, out_path=Path(scratch) / "qa.pptx"
            )
        reason = built.placeholders.get(slide.id)
        if reason:
            return [{"block": "", "check": "render", "message": reason}]
        return []
    except FontNotFoundError:
        raise
    except Exception as exc:
        return [{"block": "", "check": "qa_error", "message": f"{type(exc).__name__}: {exc}"}]


_RENDER_LOCK = threading.Lock()

_SYS_CLR = re.compile(r'<a:(dk1|lt1)><a:sysClr [^>]*?lastClr="([0-9A-Fa-f]{6})"[^>]*?/></a:\1>')


def patch_theme_colours(pptx_path: Path) -> None:
    """Make `dk1`/`lt1` plain `srgbClr` in the PPTX theme, in place.

    v2's master builder writes those two slots as `sysClr` (a documented, unfixed gap, see
    `master_builder._colour_value`) and LibreOffice then draws the system black and white
    whatever the token says. A concept that changes `dk1` or `lt1` (a dark background, say)
    would therefore render wrongly while the layout QA, which reads the tokens, judges it
    right. The bench patches its own copy of the file, not v2.
    """
    import zipfile

    theme_name = "ppt/theme/theme1.xml"
    with zipfile.ZipFile(pptx_path) as zin:
        items = [(info, zin.read(info.filename)) for info in zin.infolist()]
    patched = False
    for index, (info, data) in enumerate(items):
        if info.filename == theme_name:
            text = data.decode("utf-8")
            new = _SYS_CLR.sub(r'<a:\1><a:srgbClr val="\2"/></a:\1>', text)
            patched = new != text
            items[index] = (info, new.encode("utf-8"))
    if not patched:
        return
    tmp = pptx_path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in items:
            zout.writestr(info, data)
    os.replace(tmp, pptx_path)


def render_slide(slide: Slide, tokens: DesignTokens, *, pptx_path: Path, png_path: Path) -> str:
    """Build the PPTX and rasterise it to `png_path`. Returns "" or why it failed."""
    with _RENDER_LOCK:
        built = build_pptx(_wrap_deck(slide), tokens=tokens, out_path=pptx_path)
        if built.placeholders:
            return "; ".join(built.placeholders.values())
        patch_theme_colours(built.path)
        with tempfile.TemporaryDirectory() as scratch:
            previews = render_previews(
                built.path, out_dir=Path(scratch), tokens=tokens, dpi=PREVIEW_DPI
            )
            if not previews.rendered or not previews.images:
                return previews.note or "no preview was produced"
            png_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(previews.images[0], png_path)
    return ""


def element_counts(slide: Slide | None) -> dict[str, int]:
    counts = {"text": 0, "shape": 0, "chart": 0, "icon": 0, "figure": 0}
    if slide is None or slide.layout is None:
        return counts
    for kind, n in Counter(e.type for e in slide.layout.elements).items():
        counts[kind] = counts.get(kind, 0) + n
    return counts


def format_findings(findings: Sequence[Finding]) -> str:
    return "\n".join(
        f"- [{f['check']}] {f['block'] or 'slide'}: {f['message']}" for f in findings
    )


def _validation_message(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors(include_url=False, include_input=False)[:20]:
        where = ".".join(str(p) for p in err["loc"])
        lines.append(f"- {where or 'arguments'}: {err['msg']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# One trial
# ---------------------------------------------------------------------------


class TrialFailure(RuntimeError):
    """The trial cannot continue and is recorded as failed."""


@dataclass
class TrialSpec:
    model: str
    case: Case
    concept: Concept
    feedback: str
    repeat: int

    @property
    def key(self) -> str:
        return f"{self.model} {self.case.id} {self.concept.id} {self.feedback} r{self.repeat}"


def model_dirname(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model)


def trial_dir(out: Path, spec: TrialSpec) -> Path:
    return (
        out
        / model_dirname(spec.model)
        / spec.case.id
        / spec.concept.id
        / spec.feedback
        / f"r{spec.repeat}"
    )


def _serialise_messages(messages: Sequence[Message], image_names: Sequence[str]) -> list[Any]:
    names = list(image_names)
    out: list[Any] = []
    for m in messages:
        entry: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            entry["tool_calls"] = [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls
            ]
        if m.tool_call_id:
            entry["tool_call_id"] = m.tool_call_id
        images = getattr(m, "images", ())
        if images:
            entry["images"] = [names.pop(0) if names else "slide.png" for _ in images]
        out.append(entry)
    return out


@dataclass
class TrialContext:
    model_name: str
    model: ConverseModel
    system: str
    tokens: DesignTokens
    price: Price | None
    ledger: Ledger
    attempts: int
    out: Path
    qa: Callable[[Slide, DesignTokens], list[Finding]] = qa_findings
    render: Callable[..., str] = render_slide
    reasoning: str = "default"


class Trial:
    def __init__(self, ctx: TrialContext, spec: TrialSpec) -> None:
        self.ctx = ctx
        self.spec = spec
        self.dir = trial_dir(ctx.out, spec)
        self.messages: list[Message] = []
        self.design_attempts: list[dict[str, Any]] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.reasoning_tokens = 0
        self.model_calls = 0
        self.slide: Slide | None = None  # last slide that validated
        self.clean = False
        self.findings: list[Finding] = []
        self.revision: dict[str, Any] = {
            "state": "n/a" if spec.feedback == "qa" else "not_attempted"
        }
        self.rendered = False
        self.render_note = ""
        self.error = ""
        self.status: Status = "unclean"
        self.image_names: list[str] = []

    # -- model calls ---------------------------------------------------------

    def _call(self) -> tuple[AssistantTurn, dict[str, Any]]:
        self.ctx.ledger.check()
        started = time.perf_counter()
        turn = self.ctx.model.converse(
            list(self.messages), [WRITE_SLIDE_TOOL], system=self.ctx.system
        )
        seconds = time.perf_counter() - started
        usage = turn.usage
        self.model_calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.reasoning_tokens += getattr(usage, "reasoning_tokens", 0)
        if self.ctx.price is not None:
            self.ctx.ledger.add(
                estimate_cost(self.ctx.price, usage.input_tokens, usage.output_tokens)
            )
        info = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "reasoning_tokens": getattr(usage, "reasoning_tokens", 0),
            "seconds": round(seconds, 2),
        }
        self.messages.append(
            Message(role="assistant", content=turn.text, tool_calls=list(turn.tool_calls))
        )
        return turn, info

    def _answer(self, turn: AssistantTurn, primary: ToolCall | None, result: str) -> None:
        """One tool message per call the model made: the real result to `primary`."""
        for call in turn.tool_calls:
            if primary is not None and call is primary:
                text = result
            elif primary is None:
                text = f"No such tool {call.name!r}. {result}"
            else:
                text = f"Not run: only one {TOOL_NAME} call is read per turn."
            self.messages.append(Message(role="tool", content=text, tool_call_id=call.id))

    def _evaluate(self, call: ToolCall) -> tuple[Slide | None, list[Finding], str, str]:
        """Validate and QA one write_slide call: (slide, findings, outcome, tool result)."""
        arguments = call.arguments
        if "__invalid__" in arguments:
            message = "The arguments were not valid JSON. Call write_slide again."
            return None, [_finding("validation", message)], "validation_error", message
        try:
            args = WriteSlideArgs.model_validate(arguments)
        except ValidationError as exc:
            detail = _validation_message(exc)
            result = (
                "write_slide was rejected; nothing was written. Fix these and call "
                f"write_slide again with the whole slide:\n{detail}"
            )
            return None, [_finding("validation", detail)], "validation_error", result
        slide = args.slide.model_copy(update={"id": self.spec.case.id})
        self.slide = slide
        findings = self.ctx.qa(slide, self.ctx.tokens)
        if findings:
            result = (
                "The slide is valid but fails the layout checks. Fix these and call "
                "write_slide again with the whole corrected slide:\n"
                f"{format_findings(findings)}"
            )
            return slide, findings, "qa_findings", result
        return slide, [], "clean", ACCEPTED_TEXT

    # -- the trial -------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        started = time.perf_counter()
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            self._design()
            if self.clean:
                self._render_final()
                if self.spec.feedback == "visual" and self.rendered:
                    self._visual()
            self.status = "clean" if self.clean else "unclean"
        except BudgetStop as exc:
            self.status = "budget_stopped"
            self.error = str(exc)
        except TrialFailure as exc:
            self.status = "failed"
            self.error = scrub(str(exc))
        except Exception as exc:
            self.status = "failed"
            self.error = scrub(f"{type(exc).__name__}: {exc}")
            (self.dir / "traceback.txt").write_text(
                scrub(traceback.format_exc()), encoding="utf-8"
            )
        return self._write(time.perf_counter() - started)

    def _design(self) -> None:
        self.messages.append(
            Message(role="user", content=build_user_text(self.spec.case, self.spec.concept))
        )
        nudged = False
        wrote = False
        for n in range(1, self.ctx.attempts + 1):
            turn, info = self._call()
            attempt: dict[str, Any] = {"n": n, **info}
            self.design_attempts.append(attempt)
            writes = [c for c in turn.tool_calls if c.name == TOOL_NAME]
            if not writes:
                attempt["outcome"] = "no_tool_call"
                attempt["text"] = scrub(turn.text[:500])
                if nudged:
                    raise TrialFailure(f"the model did not call {TOOL_NAME} (after one nudge)")
                nudged = True
                if turn.tool_calls:
                    self._answer(turn, None, NUDGE_TEXT)
                else:
                    self.messages.append(Message(role="user", content=NUDGE_TEXT))
                continue
            wrote = True
            _, findings, outcome, result = self._evaluate(writes[0])
            attempt["outcome"] = outcome
            if findings:
                attempt["findings"] = findings
            self._answer(turn, writes[0], result)
            self.findings = findings
            if outcome == "clean":
                self.clean = True
                return
        if not wrote:
            raise TrialFailure(f"the model never called {TOOL_NAME}")

    def _render_final(self) -> None:
        assert self.slide is not None
        note = self.ctx.render(
            self.slide,
            self.ctx.tokens,
            pptx_path=self.dir / "slide.pptx",
            png_path=self.dir / "slide.png",
        )
        self.rendered = not note
        self.render_note = note

    def _visual(self) -> None:
        assert self.slide is not None
        image = ImageInput(data=(self.dir / "slide.png").read_bytes())
        self.messages.append(
            ImageMessage(role="user", content=VISUAL_QUESTION, images=(image,))
        )
        calls: list[dict[str, Any]] = []
        self.revision = {"state": "kept_original", "calls": calls}
        before = self.slide
        for k in (1, 2):
            try:
                turn, info = self._call()
            except BudgetStop as exc:
                self.revision["state"] = "skipped_budget"
                self.revision["note"] = str(exc)
                return
            calls.append(info)
            writes = [c for c in turn.tool_calls if c.name == TOOL_NAME]
            if not writes:
                info["outcome"] = "done" if k == 1 else "no_tool_call"
                info["text"] = scrub(turn.text[:200])
                self.revision["state"] = "kept_original" if k == 1 else "failed"
                return
            slide, findings, outcome, result = self._evaluate(writes[0])
            info["outcome"] = outcome
            if findings:
                info["findings"] = findings
            self._answer(turn, writes[0], result)
            if outcome == "clean" and slide is not None:
                note = self.ctx.render(
                    slide,
                    self.ctx.tokens,
                    pptx_path=self.dir / "slide.revised.pptx",
                    png_path=self.dir / "slide.revised.png",
                )
                if not note:
                    self._commit_revision(before, slide)
                    return
                info["outcome"] = "render_failed"
                info["render_note"] = note
                break
            self.revision["last_findings"] = findings
        self.slide = before  # fall back to the earlier clean slide
        self.revision["state"] = "failed"

    def _commit_revision(self, before: Slide, after: Slide) -> None:
        (self.dir / "slide.before.json").write_text(
            before.model_dump_json(indent=2), encoding="utf-8"
        )
        os.replace(self.dir / "slide.png", self.dir / "slide.before.png")
        os.replace(self.dir / "slide.pptx", self.dir / "slide.before.pptx")
        os.replace(self.dir / "slide.revised.png", self.dir / "slide.png")
        os.replace(self.dir / "slide.revised.pptx", self.dir / "slide.pptx")
        self.slide = after
        self.revision["state"] = "revised"

    # -- output ----------------------------------------------------------------

    def _write(self, seconds: float) -> dict[str, Any]:
        for stale in ("slide.revised.png", "slide.revised.pptx"):
            (self.dir / stale).unlink(missing_ok=True)
        if self.slide is not None:
            (self.dir / "slide.json").write_text(
                self.slide.model_dump_json(indent=2), encoding="utf-8"
            )
        image_names = (
            ["slide.before.png" if self.revision["state"] == "revised" else "slide.png"]
            if self.spec.feedback == "visual"
            else []
        )
        (self.dir / "transcript.json").write_text(
            json.dumps(
                {
                    "system": self.ctx.system,
                    "messages": _serialise_messages(self.messages, image_names),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        priced = self.ctx.price is not None
        cost = (
            estimate_cost(self.ctx.price, self.input_tokens, self.output_tokens)
            if self.ctx.price is not None
            else 0.0
        )
        record: dict[str, Any] = {
            "model": self.spec.model,
            "case": self.spec.case.id,
            "concept": self.spec.concept.id,
            "feedback": self.spec.feedback,
            "repeat": self.spec.repeat,
            "status": self.status,
            "clean": self.clean,
            "attempts_used": len(self.design_attempts),
            "attempts": self.design_attempts,
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "seconds": round(seconds, 2),
            "cost_usd": round(cost, 6),
            "priced": priced,
            "reasoning": self.ctx.reasoning,
            "revision": self.revision,
            "rendered": self.rendered,
            "render_note": self.render_note,
            "findings": [] if self.clean else self.findings,
            "element_counts": element_counts(self.slide),
            "error": self.error,
            "dir": str(self.dir),
        }
        (self.dir / "trial.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return record


def _finding(check: str, message: str) -> Finding:
    return {"block": "", "check": check, "message": message}


def skipped_record(spec: TrialSpec, out: Path, reason: str) -> dict[str, Any]:
    directory = trial_dir(out, spec)
    directory.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "model": spec.model,
        "case": spec.case.id,
        "concept": spec.concept.id,
        "feedback": spec.feedback,
        "repeat": spec.repeat,
        "status": "skipped",
        "clean": False,
        "attempts_used": 0,
        "attempts": [],
        "model_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "seconds": 0.0,
        "cost_usd": 0.0,
        "priced": True,
        "reasoning": "",
        "revision": {"state": "n/a"},
        "rendered": False,
        "render_note": "",
        "findings": [],
        "element_counts": element_counts(None),
        "error": reason,
        "dir": str(directory),
    }
    (directory / "trial.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

RUN_STATUSES = ("clean", "unclean", "failed", "budget_stopped")
COUNT_KINDS = ("text", "shape", "chart", "icon", "figure")

CSV_COLUMNS = [
    "row_type",
    "model",
    "case",
    "concept",
    "feedback",
    "repeat",
    "status",
    "clean",
    "attempts",
    "model_calls",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "seconds",
    "cost_usd",
    "reasoning",
    "revision",
    "n_text",
    "n_shape",
    "n_chart",
    "n_icon",
    "n_figure",
    "trials",
    "clean_rate",
    "mean_attempts",
    "mean_attempts_to_clean",
    "findings",
    "error",
]


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def aggregate(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ran = [r for r in records if r["status"] in RUN_STATUSES]
    clean = [r for r in ran if r["clean"]]
    with_slide = [r for r in ran if sum(r["element_counts"].values()) > 0]
    result: dict[str, Any] = {
        "trials": len(ran),
        "clean": len(clean),
        "failed": sum(r["status"] == "failed" for r in ran),
        "skipped": sum(r["status"] == "skipped" for r in records),
        "clean_rate": round(len(clean) / len(ran), 3) if ran else None,
        "mean_attempts": _mean([r["attempts_used"] for r in ran if r["attempts_used"]]),
        "mean_attempts_to_clean": _mean([r["attempts_used"] for r in clean]),
        "input_tokens": sum(r["input_tokens"] for r in ran),
        "output_tokens": sum(r["output_tokens"] for r in ran),
        "reasoning_tokens": sum(r["reasoning_tokens"] for r in ran),
        "cost_usd": round(sum(r["cost_usd"] for r in ran), 6),
        "mean_cost_usd": _mean([r["cost_usd"] for r in ran]),
        "mean_element_counts": {
            kind: _mean([r["element_counts"].get(kind, 0) for r in with_slide])
            for kind in COUNT_KINDS
        },
        "revised": sum(r["revision"].get("state") == "revised" for r in ran),
        "reasoning": sorted({r.get("reasoning", "") for r in ran}),
    }
    return result


def summarise(records: Sequence[dict[str, Any]], *, models: Sequence[str]) -> dict[str, Any]:
    by_model = {m: [r for r in records if r["model"] == m] for m in models}
    groups: dict[str, Any] = {}
    for m, recs in by_model.items():
        keys = sorted({(r["concept"], r["feedback"]) for r in recs})
        groups[m] = {
            f"{c}/{f}": aggregate([r for r in recs if (r["concept"], r["feedback"]) == (c, f)])
            for c, f in keys
        }
    return {
        "models": {m: aggregate(recs) for m, recs in by_model.items()},
        "groups": groups,
    }


def write_summary(
    out: Path,
    records: Sequence[dict[str, Any]],
    *,
    models: Sequence[str],
    extra: dict[str, Any],
) -> dict[str, Any]:
    summary = summarise(records, models=models)
    summary.update(extra)
    summary["trials"] = [{k: v for k, v in r.items() if k != "attempts"} for r in records]
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with (out / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in records:
            counts = r["element_counts"]
            writer.writerow(
                {
                    "row_type": "trial",
                    "model": r["model"],
                    "case": r["case"],
                    "concept": r["concept"],
                    "feedback": r["feedback"],
                    "repeat": r["repeat"],
                    "status": r["status"],
                    "clean": int(r["clean"]),
                    "attempts": r["attempts_used"],
                    "model_calls": r["model_calls"],
                    "input_tokens": r["input_tokens"],
                    "output_tokens": r["output_tokens"],
                    "reasoning_tokens": r["reasoning_tokens"],
                    "seconds": r["seconds"],
                    "cost_usd": r["cost_usd"],
                    "reasoning": r.get("reasoning", ""),
                    "revision": r["revision"].get("state", ""),
                    **{f"n_{k}": counts.get(k, 0) for k in COUNT_KINDS},
                    "findings": " | ".join(
                        f"[{f['check']}] {f['block']}: {f['message']}" for f in r["findings"]
                    ),
                    "error": r["error"],
                }
            )
        for m, agg in summary["models"].items():
            writer.writerow(
                {
                    "row_type": "model_total",
                    "model": m,
                    "trials": agg["trials"],
                    "clean": agg["clean"],
                    "clean_rate": agg["clean_rate"],
                    "mean_attempts": agg["mean_attempts"],
                    "mean_attempts_to_clean": agg["mean_attempts_to_clean"],
                    "input_tokens": agg["input_tokens"],
                    "output_tokens": agg["output_tokens"],
                    "reasoning_tokens": agg["reasoning_tokens"],
                    "cost_usd": agg["cost_usd"],
                    "reasoning": "/".join(agg["reasoning"]),
                    **{f"n_{k}": agg["mean_element_counts"][k] for k in COUNT_KINDS},
                }
            )
    return summary


# ---------------------------------------------------------------------------
# Contact sheets
# ---------------------------------------------------------------------------

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
]
_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf",
]


def _font(size: int, bold: bool = False) -> Any:
    from PIL import ImageFont

    for path in _BOLD_CANDIDATES if bold else _FONT_CANDIDATES:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _wrap(draw: Any, text: str, font: Any, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split(" "):
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


CELL_W = 560
IMG_H = 315
HEAD_H = 74
CELL_PAD = 10
ROW_LABEL_W = 170
COL_HEAD_H = 40
TITLE_H = 90

_STATUS_COLOURS = {
    "clean": (46, 125, 50),
    "unclean": (230, 140, 0),
    "failed": (190, 40, 40),
    "budget_stopped": (120, 120, 120),
    "skipped": (150, 150, 150),
}


def _cell_text(r: dict[str, Any]) -> tuple[str, str]:
    """(headline, detail) for a cell; the image area carries the text for non-clean cells."""
    state = r["status"].upper().replace("_", " ")
    revision = r["revision"].get("state", "")
    tags = ""
    if revision == "revised":
        tags = "  REVISED (after shown)"
    elif revision == "failed":
        tags = "  revision failed, earlier slide kept"
    elif revision == "skipped_budget":
        tags = "  revision skipped (budget)"
    elif revision == "kept_original" and r["feedback"] == "visual":
        tags = "  no revision (DONE)"
    cost = f"${r['cost_usd']:.4f}" + ("" if r["priced"] else " (unpriced)")
    headline = f"{state}  attempts {r['attempts_used']}  {cost}{tags}"
    detail = (
        f"{r['input_tokens']:,} in / {r['output_tokens']:,} out tokens  {r['seconds']:.0f}s"
    )
    return headline, detail


def _problem_text(r: dict[str, Any]) -> str:
    parts: list[str] = []
    if r["error"]:
        parts.append(r["error"])
    if r["findings"]:
        parts.append("Findings:\n" + format_findings(r["findings"]))
    if r["render_note"]:
        parts.append("Render: " + r["render_note"])
    return "\n".join(parts) or "(nothing recorded)"


def write_sheet(out: Path, model: str, records: Sequence[dict[str, Any]]) -> Path | None:
    from PIL import Image, ImageDraw

    recs = [r for r in records if r["model"] == model]
    if not recs:
        return None
    cases = sorted({r["case"] for r in recs})
    many = len({r["repeat"] for r in recs}) > 1
    columns = sorted({(r["concept"], r["feedback"], r["repeat"] if many else 0) for r in recs})
    cell_h = HEAD_H + IMG_H + CELL_PAD
    width = ROW_LABEL_W + len(columns) * (CELL_W + CELL_PAD) + CELL_PAD
    height = TITLE_H + COL_HEAD_H + len(cases) * cell_h + CELL_PAD
    sheet = Image.new("RGB", (width, height), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    f_title, f_bold, f_text, f_small = _font(26, True), _font(15, True), _font(14), _font(12)
    agg = aggregate(recs)
    draw.text((CELL_PAD, 12), f"{model}", font=f_title, fill=(20, 20, 20))
    rate = "n/a" if agg["clean_rate"] is None else f"{agg['clean_rate']:.0%}"
    draw.text(
        (CELL_PAD, 50),
        f"{agg['trials']} trials, clean {rate}, ${agg['cost_usd']:.4f} estimated "
        f"(assumed prices), {agg['input_tokens']:,} in / {agg['output_tokens']:,} out tokens",
        font=f_text,
        fill=(60, 60, 60),
    )
    for ci, (concept, feedback, repeat) in enumerate(columns):
        x = ROW_LABEL_W + ci * (CELL_W + CELL_PAD) + CELL_PAD
        label = f"{concept} / {feedback}" + (f" / r{repeat}" if many else "")
        draw.text((x, TITLE_H + 10), label, font=f_bold, fill=(20, 20, 20))
    index = {
        (r["case"], r["concept"], r["feedback"], r["repeat"] if many else 0): r for r in recs
    }
    for ri, case in enumerate(cases):
        y = TITLE_H + COL_HEAD_H + ri * cell_h
        for i, line in enumerate(_wrap(draw, case, f_bold, ROW_LABEL_W - 2 * CELL_PAD)[:6]):
            draw.text((CELL_PAD, y + 6 + i * 19), line, font=f_bold, fill=(20, 20, 20))
        for ci, (concept, feedback, repeat) in enumerate(columns):
            x = ROW_LABEL_W + ci * (CELL_W + CELL_PAD) + CELL_PAD
            r = index.get((case, concept, feedback, repeat))
            if r is None:
                continue
            _draw_cell(sheet, draw, x, y, r, (f_bold, f_text, f_small))
    path = out / f"sheet-{model_dirname(model)}.png"
    sheet.save(path)
    return path


def _draw_cell(
    sheet: Any, draw: Any, x: int, y: int, r: dict[str, Any], fonts: tuple[Any, Any, Any]
) -> None:
    from PIL import Image

    f_bold, f_text, f_small = fonts
    colour = _STATUS_COLOURS.get(r["status"], (100, 100, 100))
    draw.rectangle(
        [x, y, x + CELL_W, y + HEAD_H + IMG_H], fill=(255, 255, 255), outline=colour, width=3
    )
    draw.rectangle([x, y, x + CELL_W, y + 6], fill=colour)
    label = f"{r['case']} | {r['concept']} | {r['feedback']}"
    draw.text((x + 8, y + 10), label[:70], font=f_bold, fill=(20, 20, 20))
    headline, detail = _cell_text(r)
    draw.text((x + 8, y + 32), headline[:78], font=f_text, fill=colour)
    draw.text((x + 8, y + 52), detail, font=f_small, fill=(90, 90, 90))
    top = y + HEAD_H
    png = Path(r["dir"]) / "slide.png"
    if r["clean"] and r["rendered"] and png.is_file():
        with Image.open(png) as image:
            image = image.convert("RGB")
            image.thumbnail((CELL_W - 6, IMG_H - 3))
            sheet.paste(image, (x + 3, top))
        return
    text = _problem_text(r)
    lines = _wrap(draw, text, f_small, CELL_W - 20)
    room = (IMG_H - 10) // 15
    if len(lines) > room:
        lines = [*lines[: room - 1], "..."]
    for i, line in enumerate(lines):
        draw.text((x + 10, top + 6 + i * 15), line, font=f_small, fill=(120, 20, 20))


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass
class RunConfig:
    models: list[str]
    cases: list[Case]
    concepts: list[Concept]
    feedback: list[str]
    attempts: int
    budget: float
    out: Path
    repeat: int = 1
    dry_run: bool = False
    allow_unpriced: bool = False
    workers: int = 1
    skip_existing: bool = False
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    reasoning: str = "medium"
    api: str = "auto"
    bench_dir: Path = BENCH_DIR
    prices_path: Path = field(default_factory=lambda: BENCH_DIR / "prices.yaml")
    tokens_path: Path = DEFAULT_TOKENS_PATH


def check_prices(models: Sequence[str], prices: dict[str, Price], allow_unpriced: bool) -> None:
    missing = [m for m in models if m not in prices]
    if missing and not allow_unpriced:
        raise BenchInputError(
            f"no assumed price for {', '.join(missing)} in prices.yaml; add one, or pass "
            "--allow-unpriced (the budget guard then cannot count that model's spend)"
        )


def expand_trials(cfg: RunConfig) -> list[TrialSpec]:
    return [
        TrialSpec(model, case, concept, feedback, r)
        for model in cfg.models
        for case in cfg.cases
        for concept in cfg.concepts
        for feedback in cfg.feedback
        for r in range(1, cfg.repeat + 1)
    ]


def write_dry_run(
    cfg: RunConfig, spec: TrialSpec, provider: BaseProvider, system: str, user: str
) -> dict[str, Any]:
    directory = trial_dir(cfg.out, spec)
    directory.mkdir(parents=True, exist_ok=True)
    _url, _headers, body = provider.build_converse_request(
        messages=[Message(role="user", content=user)],
        tools=[WRITE_SLIDE_TOOL],
        system=system,
    )
    # Headers are never written: they carry the key.
    (directory / "request.json").write_text(
        json.dumps({"url": _url, "body": body}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (directory / "system.md").write_text(system, encoding="utf-8")
    (directory / "user.md").write_text(user, encoding="utf-8")
    chars = len(json.dumps(body, ensure_ascii=False))
    return {
        "model": spec.model,
        "case": spec.case.id,
        "concept": spec.concept.id,
        "feedback": spec.feedback,
        "repeat": spec.repeat,
        "status": "dry_run",
        "approx_input_tokens_first_call": chars // 4,
        "dir": str(directory),
    }


def run(
    cfg: RunConfig,
    *,
    provider_factory: Callable[[str], ConverseModel] | None = None,
    qa: Callable[[Slide, DesignTokens], list[Finding]] | None = None,
    render: Callable[..., str] | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run every trial; returns the summary (or the dry-run listing).

    `provider_factory`, `qa` and `render` exist so tests can use a fake model and skip
    LibreOffice; the command line never sets them.
    """
    prices = load_prices(cfg.prices_path)
    check_prices(cfg.models, prices, cfg.allow_unpriced)
    for model in cfg.models:
        if model not in prices:
            log(f"WARNING: {model} is unpriced; the budget guard cannot count its spend.")
    if cfg.reasoning not in REASONING_LEVELS:
        raise BenchInputError(f"--reasoning must be one of {', '.join(REASONING_LEVELS)}")
    if any(f not in ("qa", "visual") for f in cfg.feedback):
        raise BenchInputError("--feedback must be qa or visual")
    cfg.out.mkdir(parents=True, exist_ok=True)

    tokens_by_concept = {c.id: tokens_for_concept(c, cfg.tokens_path) for c in cfg.concepts}
    systems = {
        c.id: build_system_prompt(cfg.bench_dir, tokens_by_concept[c.id], c)
        for c in cfg.concepts
    }
    specs = expand_trials(cfg)

    providers: dict[str, ConverseModel] = {}
    for model in cfg.models:
        if cfg.dry_run:
            providers[model] = make_provider(
                model,
                max_output_tokens=cfg.max_output_tokens,
                api_key="dry-run",
                reasoning=cfg.reasoning,
                api=cfg.api,
            )
        elif provider_factory is not None:
            providers[model] = provider_factory(model)
        else:
            providers[model] = make_provider(
                model,
                max_output_tokens=cfg.max_output_tokens,
                reasoning=cfg.reasoning,
                api=cfg.api,
            )

    if cfg.dry_run:
        listing = [
            write_dry_run(
                cfg,
                s,
                typing.cast(BaseProvider, providers[s.model]),
                systems[s.concept.id],
                build_user_text(s.case, s.concept),
            )
            for s in specs
        ]
        total = sum(item["approx_input_tokens_first_call"] for item in listing)
        (cfg.out / "dry-run.json").write_text(json.dumps(listing, indent=2), encoding="utf-8")
        log(
            f"dry run: {len(listing)} requests written under {cfg.out}; about {total:,} input "
            "tokens for the first call of every trial (later calls and revisions add more). "
            "No model was called."
        )
        return {"dry_run": True, "requests": listing}

    ledger = Ledger(cfg.budget)
    records: list[dict[str, Any]] = []
    records_lock = threading.Lock()
    done = 0
    started = time.time()

    # Resume: trials already finished on disk count against the budget and are not re-run.
    pending: list[TrialSpec] = []
    for spec in specs:
        existing = trial_dir(cfg.out, spec) / "trial.json"
        if cfg.skip_existing and existing.is_file():
            record = json.loads(existing.read_text(encoding="utf-8"))
            if record.get("status") in ("clean", "unclean"):
                ledger.add(record.get("cost_usd", 0.0))
                records.append(record)
                continue
        pending.append(spec)
    if len(records):
        log(
            f"skip-existing: reused {len(records)} finished trials "
            f"(${ledger.spent:.4f} counted)"
        )

    def work(spec: TrialSpec) -> None:
        nonlocal done
        if ledger.exhausted():
            record = skipped_record(
                spec, cfg.out, "budget guard: estimated spend reached the budget"
            )
        else:
            ctx = TrialContext(
                model_name=spec.model,
                model=providers[spec.model],
                system=systems[spec.concept.id],
                tokens=tokens_by_concept[spec.concept.id],
                price=prices.get(spec.model),
                ledger=ledger,
                attempts=cfg.attempts,
                out=cfg.out,
                qa=qa or qa_findings,
                render=render or render_slide,
                reasoning=effective_reasoning(spec.model, cfg.reasoning, cfg.api),
            )
            record = Trial(ctx, spec).run()
        with records_lock:
            records.append(record)
            done += 1
            log(
                f"[{done}/{len(pending)}] {spec.key}: {record['status']} "
                f"attempts={record['attempts_used']} ${record['cost_usd']:.4f} "
                f"(total ${ledger.spent:.4f}/{cfg.budget:.2f})"
                + (f" error: {record['error'][:120]}" if record["error"] else "")
            )

    if cfg.workers > 1:
        with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
            list(pool.map(work, pending))
    else:
        for spec in pending:
            work(spec)

    order = {s.key: i for i, s in enumerate(specs)}
    records.sort(
        key=lambda r: order.get(
            f"{r['model']} {r['case']} {r['concept']} {r['feedback']} r{r['repeat']}", 0
        )
    )
    skipped = [r for r in records if r["status"] == "skipped"]
    stopped = [r for r in records if r["status"] == "budget_stopped"]
    revisions_skipped = [r for r in records if r["revision"].get("state") == "skipped_budget"]
    budget_report = {
        "budget_usd": cfg.budget,
        "estimated_spend_usd": round(ledger.spent, 6),
        "guard_tripped": bool(skipped or stopped or revisions_skipped),
        "trials_not_started": [
            f"{r['model']} {r['case']} {r['concept']} {r['feedback']} r{r['repeat']}"
            for r in skipped
        ],
        "trials_stopped_mid_trial": [
            f"{r['model']} {r['case']} {r['concept']} {r['feedback']} r{r['repeat']}"
            for r in stopped
        ],
        "revisions_skipped": [
            f"{r['model']} {r['case']} {r['concept']} r{r['repeat']}" for r in revisions_skipped
        ],
    }
    extra = {
        "budget": budget_report,
        "prices": {
            m: {"input": p.input, "output": p.output}
            for m, p in prices.items()
            if m in cfg.models
        },
        "prices_note": "assumed, deliberately high; not confirmed prices",
        "config": {
            "models": cfg.models,
            "cases": [c.id for c in cfg.cases],
            "concepts": [c.id for c in cfg.concepts],
            "feedback": cfg.feedback,
            "attempts": cfg.attempts,
            "repeat": cfg.repeat,
            "workers": cfg.workers,
            "reasoning_requested": cfg.reasoning,
            "reasoning_by_model": {
                m: effective_reasoning(m, cfg.reasoning, cfg.api) for m in cfg.models
            },
            "endpoint_by_model": {
                m: "responses" if uses_responses(m, cfg.api) else "chat.completions"
                for m in cfg.models
            },
        },
        "wall_seconds": round(time.time() - started, 1),
    }
    summary = write_summary(cfg.out, records, models=cfg.models, extra=extra)
    for model in cfg.models:
        sheet = write_sheet(cfg.out, model, records)
        if sheet:
            log(f"contact sheet: {sheet}")
    if budget_report["guard_tripped"]:
        log(
            f"BUDGET GUARD: estimated spend ${ledger.spent:.4f} reached ${cfg.budget:.2f}. "
            f"{len(skipped)} trials not started, {len(stopped)} stopped mid-trial, "
            f"{len(revisions_skipped)} visual revisions skipped. See summary.json budget."
        )
    log(f"summary: {cfg.out / 'summary.json'}  total estimated ${ledger.spent:.4f}")
    return summary


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Slide bench harness (see SPEC.md).")
    p.add_argument(
        "--env-model",
        action="append",
        dest="models",
        required=True,
        help="provider:model; repeat for several models",
    )
    p.add_argument("--cases", default="all", help="all, or comma-separated case ids")
    p.add_argument("--concepts", default="none", help="comma-separated concept ids")
    p.add_argument(
        "--feedback",
        default="qa",
        help="qa, visual, or qa,visual (visual also shows the model its render once)",
    )
    p.add_argument("--attempts", type=int, default=4, help="model calls per slide (default 4)")
    p.add_argument("--budget", type=float, default=5.00, help="US dollars of estimated spend")
    p.add_argument(
        "--out", required=True, type=Path, help="output directory (outside the repo)"
    )
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--dry-run", action="store_true", help="write requests, call no model")
    p.add_argument("--allow-unpriced", action="store_true")
    p.add_argument("--workers", type=int, default=1, help="trials in parallel (default 1)")
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="reuse finished trials already in --out (they count against the budget)",
    )
    p.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    p.add_argument(
        "--reasoning",
        default="medium",
        choices=REASONING_LEVELS,
        help="reasoning effort, sent to models called through the Responses "
        "endpoint (gpt-5.6-*); other models run at their own default",
    )
    p.add_argument(
        "--api",
        default="auto",
        choices=["auto", "chat", "responses"],
        help="auto: Responses for gpt-5.6-*, Chat Completions otherwise",
    )
    p.add_argument("--bench-dir", type=Path, default=BENCH_DIR, help=argparse.SUPPRESS)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.attempts < 1 or args.repeat < 1 or args.workers < 1 or args.budget <= 0:
        print(
            "error: --attempts, --repeat, --workers and --budget must be positive",
            file=sys.stderr,
        )
        return 2
    try:
        cfg = RunConfig(
            models=list(dict.fromkeys(args.models)),
            cases=resolve_cases(args.cases, args.bench_dir),
            concepts=resolve_concepts(args.concepts, args.bench_dir),
            feedback=_csv(args.feedback),
            attempts=args.attempts,
            budget=args.budget,
            out=args.out,
            repeat=args.repeat,
            dry_run=args.dry_run,
            allow_unpriced=args.allow_unpriced,
            workers=args.workers,
            skip_existing=args.skip_existing,
            max_output_tokens=args.max_output_tokens,
            reasoning=args.reasoning,
            api=args.api,
            bench_dir=args.bench_dir,
            prices_path=args.bench_dir / "prices.yaml"
            if (args.bench_dir / "prices.yaml").is_file()
            else BENCH_DIR / "prices.yaml",
        )
        run(cfg)
    except BenchInputError as exc:
        print(f"error: {scrub(str(exc))}", file=sys.stderr)
        return 2
    except Exception as exc:  # a missing key and the like: say what, never print a value
        print(f"error: {type(exc).__name__}: {scrub(str(exc))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
