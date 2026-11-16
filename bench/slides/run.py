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
# The reviewer
# ---------------------------------------------------------------------------

REVIEW_TOOL_NAME = "report"
REVIEW_IMAGE_WIDTH = 1600
REVIEW_PROMPT_NAME = "review.md"
REVIEW_NUDGE_TEXT = (
    "You did not call report. Review the slide by calling report exactly once, with the "
    "verdict, the findings and a one-sentence summary; do not answer in prose."
)
PALETTE_SLOTS = (
    "dk1",
    "lt1",
    "dk2",
    "lt2",
    "accent1",
    "accent2",
    "accent3",
    "accent4",
    "accent5",
    "accent6",
)


class ReviewFinding(ToolArgs):
    severity: Literal["blocking", "minor"] = Field(
        description="blocking: the slide must not go out like this. minor: worth fixing."
    )
    where: str = Field(description="Where on the slide, in words a designer can find.")
    problem: str = Field(description="What is wrong, as seen in the image.")
    fix: str = Field(description="What to change, specific enough to act on.")


class ReportArgs(ToolArgs):
    """`report`: the reviewer's one answer."""

    verdict: Literal["pass", "revise"] = Field(
        description="pass if the slide can go out; revise if it needs another pass."
    )
    findings: list[ReviewFinding] = Field(
        default_factory=list,
        description="Empty for a pass. A revise needs at least one blocking finding.",
    )
    summary: str = Field(default="", description="One sentence.")


REPORT_TOOL = ToolSpec(
    name=REVIEW_TOOL_NAME,
    description=(
        "Report your review of the slide. Call it exactly once: your verdict, your findings "
        "and a one-sentence summary."
    ),
    args_model=ReportArgs,
)


def build_review_user_text(
    case: Case, concept: Concept, tokens_path: Path = DEFAULT_TOKENS_PATH
) -> str:
    """The text half of the reviewer's user message: the slide's brief, then the design
    concept, with the brief author's notes after the content. A stable, plain format; no
    layout, no JSON."""
    content = case.content
    lines = ["# Slide brief", f"Talking header: {case.title}"]
    lines += ["", "Intent (what the slide must make the audience conclude):"]
    lines.append(case.intent.strip() or "(none given)")
    lines += ["", "Content:"]
    empty = True
    if content.points:
        empty = False
        lines += ["Points:", *[f"- {p}" for p in content.points]]
    if content.figures:
        empty = False
        lines += ["Key figures:", *[f"- {f.value}: {f.label}" for f in content.figures]]
    if content.chart is not None:
        empty = False
        chart = content.chart
        lines.append(f"Chart ({chart.kind}), categories: " + ", ".join(chart.categories))
        for series in chart.series:
            lines.append(f"- {series.name}: " + ", ".join(f"{v:g}" for v in series.values))
        if chart.emphasis:
            lines.append("Emphasised: " + ", ".join(chart.emphasis))
    if empty:
        lines.append("(none)")
    if case.notes.strip():
        lines += ["", "Notes from the brief's author:", case.notes.strip()]
    lines += ["", "# Design concept"]
    has_concept = bool(
        concept.concept.strip() or concept.rules or concept.palette or concept.name.strip()
    )
    if concept.id == "none" or not has_concept:
        lines.append("None given.")
    else:
        if concept.name.strip():
            lines.append(f"Name: {concept.name.strip()}")
        if concept.concept.strip():
            lines.append(f"Concept: {concept.concept.strip()}")
        if concept.rules:
            lines += ["Rules:", *[f"- {r}" for r in concept.rules]]
        if concept.palette or concept.roles:
            scheme = tokens_for_concept(concept, tokens_path).palette.as_scheme()
            lines.append("Palette (slot, colour, role):")
            for slot in PALETTE_SLOTS:
                role = concept.roles.get(slot, "")
                lines.append(f"- {slot} #{scheme[slot]}" + (f": {role}" if role else ""))
    lines += [
        "",
        "# The rendered slide",
        f"The image below is the rendered slide, {REVIEW_IMAGE_WIDTH} pixels wide. Review it "
        f"and call {REVIEW_TOOL_NAME}.",
    ]
    return "\n".join(lines)


def load_review_prompt(bench_dir: Path) -> str:
    """`prompts/review.md`, exactly as written (no placeholders)."""
    path = bench_dir / "prompts" / REVIEW_PROMPT_NAME
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BenchInputError(f"reviewer prompt not readable: {path}: {exc}") from exc


def review_image(path: Path) -> tuple[ImageInput, dict[str, int]]:
    """The slide render as the reviewer sees it: a PNG, 1600 pixels wide."""
    import io

    from PIL import Image

    with Image.open(path) as opened:
        image = opened.convert("RGB")
        if image.width != REVIEW_IMAGE_WIDTH:
            height = max(1, round(image.height * REVIEW_IMAGE_WIDTH / image.width))
            image = image.resize((REVIEW_IMAGE_WIDTH, height), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
    data = buffer.getvalue()
    return ImageInput(data=data), {
        "width": image.width,
        "height": image.height,
        "bytes": len(data),
    }


def review_feedback_text(report: dict[str, Any]) -> str:
    """The designer's next instruction after a `revise`: the blocking findings, then the
    minor ones marked optional, each quoted as the reviewer wrote it."""

    def block(title: str, items: list[dict[str, str]]) -> list[str]:
        out = [title]
        for n, f in enumerate(items, 1):
            out += [
                f"{n}. Where: {f['where']}",
                f"   Problem: {f['problem']}",
                f"   Fix: {f['fix']}",
            ]
        return out

    findings = report["findings"]
    blocking = [f for f in findings if f["severity"] == "blocking"]
    minor = [f for f in findings if f["severity"] == "minor"]
    lines = [
        "A reviewer looked at the rendered slide and asked for a revision. Its findings "
        "follow, verbatim. Fix every blocking finding. The minor findings are optional. "
        f"Then call {TOOL_NAME} with the whole corrected slide.",
    ]
    if report.get("summary"):
        lines += ["", f"Reviewer's summary: {report['summary']}"]
    lines += ["", *block("BLOCKING findings (fix these):", blocking)]
    if minor:
        lines += ["", *block("MINOR findings (optional):", minor)]
    return "\n".join(lines)


@dataclass
class ReviewItem:
    """One slide to review: a render, its brief and its concept."""

    label: str
    image: Path
    case: Case
    concept: Concept
    source: str = ""
    designer_model: str = ""


class Reviewer:
    """The reviewer model: one call per slide, one tool, one nudge."""

    def __init__(
        self,
        name: str,
        model: ConverseModel,
        system: str,
        price: Price | None,
        ledger: Ledger,
        *,
        reasoning: str = "default",
        tokens_path: Path = DEFAULT_TOKENS_PATH,
    ) -> None:
        self.name = name
        self.model = model
        self.system = system
        self.price = price
        self.ledger = ledger
        self.reasoning = reasoning
        self.tokens_path = tokens_path

    def review(self, item: ReviewItem, image_path: Path | None = None) -> dict[str, Any]:
        """Review one render. Returns the review record (never raises for model or budget
        trouble); the record carries a private `_messages` list for the transcript."""
        path = image_path or item.image
        started = time.perf_counter()
        record: dict[str, Any] = {
            "slide": item.label,
            "case": item.case.id,
            "concept": item.concept.id,
            "reviewer": self.name,
            "status": "failed",
            "verdict": None,
            "raw_verdict": None,
            "downgraded": False,
            "pass_with_blocking": False,
            "findings": [],
            "summary": "",
            "error": "",
            "calls": 0,
            "nudged": False,
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "seconds": 0.0,
            "cost_usd": 0.0,
            "priced": self.price is not None,
            "reasoning": self.reasoning,
            "raw_tool_call": None,
            "image_sent": {},
        }
        messages: list[Message] = []
        record["_messages"] = messages
        try:
            image, sent = review_image(path)
            record["image_sent"] = sent
            messages.append(
                ImageMessage(
                    role="user",
                    content=build_review_user_text(item.case, item.concept, self.tokens_path),
                    images=(image,),
                )
            )
            self._converse(record, messages)
        except BudgetStop as exc:
            record["status"] = "budget_stopped"
            record["error"] = str(exc)
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = scrub(f"{type(exc).__name__}: {exc}")
        record["seconds"] = round(time.perf_counter() - started, 2)
        record["cost_usd"] = round(record["cost_usd"], 6)
        return record

    def _converse(self, record: dict[str, Any], messages: list[Message]) -> None:
        for attempt in (1, 2):
            self.ledger.check()
            started = time.perf_counter()
            turn = self.model.converse(list(messages), [REPORT_TOOL], system=self.system)
            elapsed = time.perf_counter() - started
            usage = turn.usage
            record["calls"] += 1
            record["input_tokens"] += usage.input_tokens
            record["output_tokens"] += usage.output_tokens
            record["reasoning_tokens"] += getattr(usage, "reasoning_tokens", 0)
            if self.price is not None:
                cost = estimate_cost(self.price, usage.input_tokens, usage.output_tokens)
                record["cost_usd"] += cost
                self.ledger.add(cost)
            messages.append(
                Message(role="assistant", content=turn.text, tool_calls=list(turn.tool_calls))
            )
            reports = [c for c in turn.tool_calls if c.name == REVIEW_TOOL_NAME]
            problem = ""
            if reports:
                call = reports[0]
                record["raw_tool_call"] = {
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
                if "__invalid__" in call.arguments:
                    problem = "The arguments were not valid JSON."
                else:
                    try:
                        args = ReportArgs.model_validate(call.arguments)
                    except ValidationError as exc:
                        problem = _validation_message(exc)
                    else:
                        self._accept(record, args)
                        return
            record["seconds_last_call"] = round(elapsed, 2)
            if attempt == 2:
                record["error"] = scrub(
                    f"the reviewer did not call {REVIEW_TOOL_NAME} correctly (after one nudge)"
                    + (f": {problem}" if problem else "")
                )
                return
            record["nudged"] = True
            text = REVIEW_NUDGE_TEXT
            if problem:
                text = f"The report call was rejected:\n{problem}\n{REVIEW_NUDGE_TEXT}"
            if turn.tool_calls:
                for call in turn.tool_calls:
                    messages.append(Message(role="tool", content=text, tool_call_id=call.id))
            else:
                messages.append(Message(role="user", content=text))

    @staticmethod
    def _accept(record: dict[str, Any], args: ReportArgs) -> None:
        findings = [f.model_dump() for f in args.findings]
        blocking = any(f["severity"] == "blocking" for f in findings)
        record["raw_verdict"] = args.verdict
        record["findings"] = findings
        record["summary"] = args.summary.strip()
        record["status"] = "ok"
        if args.verdict == "revise" and not blocking:
            record["verdict"] = "pass"
            record["downgraded"] = True
        else:
            record["verdict"] = args.verdict
        if args.verdict == "pass" and blocking:
            record["pass_with_blocking"] = True


def write_review_files(
    directory: Path, stem: str, record: dict[str, Any], image_name: str
) -> None:
    """`<stem>.json` (the record) and `<stem>.transcript.json` (the messages, the image
    replaced by its file name)."""
    directory.mkdir(parents=True, exist_ok=True)
    messages: list[Message] = record.get("_messages", [])
    public = {k: v for k, v in record.items() if not k.startswith("_")}
    public["image_file"] = image_name
    (directory / f"{stem}.json").write_text(
        scrub(json.dumps(public, indent=2, ensure_ascii=False)), encoding="utf-8"
    )
    transcript = {
        "system": "(the contents of prompts/review.md)",
        "messages": _serialise_messages(messages, [image_name]),
    }
    (directory / f"{stem}.transcript.json").write_text(
        scrub(json.dumps(transcript, indent=2, ensure_ascii=False)), encoding="utf-8"
    )


def review_summary_fields(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """What trial.json and the summaries keep of one review."""
    if record is None:
        return None
    findings = record["findings"]
    return {
        "status": record["status"],
        "verdict": record["verdict"],
        "raw_verdict": record["raw_verdict"],
        "downgraded": record["downgraded"],
        "pass_with_blocking": record["pass_with_blocking"],
        "n_blocking": sum(f["severity"] == "blocking" for f in findings),
        "n_minor": sum(f["severity"] == "minor" for f in findings),
        "findings": findings,
        "summary": record["summary"],
        "error": record["error"],
        "nudged": record["nudged"],
        "input_tokens": record["input_tokens"],
        "output_tokens": record["output_tokens"],
        "seconds": record["seconds"],
        "cost_usd": record["cost_usd"],
    }


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
    reviewer: Reviewer | None = None


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
        self.reviews: dict[str, dict[str, Any] | None] = {"first": None, "second": None}

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
                elif self.spec.feedback == "review" and self.rendered:
                    self._review()
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
        self._revise(done_is_ok=True)

    def _review(self) -> None:
        """Review the clean slide; on `revise`, send the findings to the designer for one
        revision (same validation and QA, one retry); review the revised slide once more."""
        reviewer = self.ctx.reviewer
        assert reviewer is not None and self.slide is not None
        first = reviewer.review(self._review_item(), self.dir / "slide.png")
        self.reviews["first"] = first
        if first["status"] != "ok":
            return
        if first["verdict"] != "revise":
            self.revision = {"state": "not_needed"}
            return
        self.messages.append(Message(role="user", content=review_feedback_text(first)))
        self._revise(done_is_ok=False)
        if self.revision["state"] == "revised":
            self.reviews["second"] = reviewer.review(
                self._review_item(), self.dir / "slide.png"
            )

    def _review_item(self) -> ReviewItem:
        return ReviewItem(
            label=self.spec.key,
            image=self.dir / "slide.png",
            case=self.spec.case,
            concept=self.spec.concept,
            designer_model=self.spec.model,
        )

    def _revise(self, *, done_is_ok: bool) -> None:
        """One revision call, with one retry if the slide fails validation or QA. The
        revised slide replaces the earlier one only if it is clean and renders; otherwise
        the earlier clean slide is kept."""
        calls: list[dict[str, Any]] = []
        self.revision = {"state": "kept_original", "calls": calls}
        before = self.slide
        assert before is not None
        for k in (1, 2):
            try:
                turn, info = self._call()
            except BudgetStop as exc:
                self.slide = before
                self.revision["state"] = "skipped_budget"
                self.revision["note"] = str(exc)
                return
            calls.append(info)
            writes = [c for c in turn.tool_calls if c.name == TOOL_NAME]
            if not writes:
                self.slide = before
                info["outcome"] = "done" if (done_is_ok and k == 1) else "no_tool_call"
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
        revised = self.revision["state"] == "revised"
        for key, number, name in (
            ("first", 1, "slide.before.png" if revised else "slide.png"),
            ("second", 2, "slide.png"),
        ):
            review_record = self.reviews[key]
            if review_record is not None:
                write_review_files(self.dir, f"review-{number}", review_record, name)
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
            **review_cost_fields(cost, self.reviews),
            "priced": priced,
            "reasoning": self.ctx.reasoning,
            "revision": self.revision,
            "review": review_trial_fields(self.spec.feedback, self.revision, self.reviews),
            "rendered": self.rendered,
            "render_note": self.render_note,
            "findings": [] if self.clean else self.findings,
            "element_counts": element_counts(self.slide),
            "error": self.error,
            "dir": str(self.dir),
        }
        (self.dir / "trial.json").write_text(
            scrub(json.dumps(record, indent=2, ensure_ascii=False)), encoding="utf-8"
        )
        return record


def review_cost_fields(
    designer_cost: float, reviews: dict[str, dict[str, Any] | None]
) -> dict[str, Any]:
    """The reviewer's spend, kept apart from the designer's `cost_usd`, and the total."""
    done = [v for v in reviews.values() if v is not None]
    review_cost = sum(v["cost_usd"] for v in done)
    return {
        "review_calls": sum(v["calls"] for v in done),
        "review_input_tokens": sum(v["input_tokens"] for v in done),
        "review_output_tokens": sum(v["output_tokens"] for v in done),
        "review_seconds": round(sum(v["seconds"] for v in done), 2),
        "review_cost_usd": round(review_cost, 6),
        "total_cost_usd": round(designer_cost + review_cost, 6),
    }


def review_trial_fields(
    feedback: str, revision: dict[str, Any], reviews: dict[str, dict[str, Any] | None]
) -> dict[str, Any] | None:
    """The review story of one trial: first verdict, whether a revision happened and was
    clean, second verdict."""
    if feedback != "review":
        return None
    first = review_summary_fields(reviews["first"])
    second = review_summary_fields(reviews["second"])
    state = revision.get("state", "")
    return {
        "first": first,
        "second": second,
        "first_verdict": (first or {}).get("verdict"),
        "revision": state,
        "revised": state == "revised",
        "revision_clean": state == "revised",
        "second_verdict": (second or {}).get("verdict"),
    }


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
        **review_cost_fields(0.0, {"first": None, "second": None}),
        "priced": True,
        "reasoning": "",
        "revision": {"state": "n/a"},
        "review": None,
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
    "review_cost_usd",
    "total_cost_usd",
    "reasoning",
    "revision",
    "review_first",
    "review_revised",
    "review_revision_clean",
    "review_second",
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


def review_counts(records: Sequence[dict[str, Any]]) -> dict[str, int]:
    """How the reviewer's verdicts went, over the trials that used it."""
    reviewed = [r for r in records if r.get("review")]
    firsts = [r["review"]["first"] for r in reviewed if r["review"]["first"]]
    seconds = [r["review"]["second"] for r in reviewed if r["review"]["second"]]

    def n(items: list[dict[str, Any]], verdict: str) -> int:
        return sum(1 for i in items if i["verdict"] == verdict)

    return {
        "trials_reviewed": len(reviewed),
        "first_pass": n(firsts, "pass"),
        "first_revise": n(firsts, "revise"),
        "first_downgraded": sum(1 for i in firsts if i["downgraded"]),
        "first_failed": sum(1 for i in firsts if i["status"] == "failed"),
        "revisions": sum(1 for r in reviewed if r["review"]["revised"]),
        "revisions_failed": sum(1 for r in reviewed if r["review"]["revision"] == "failed"),
        "second_pass": n(seconds, "pass"),
        "second_revise": n(seconds, "revise"),
        "second_failed": sum(1 for i in seconds if i["status"] == "failed"),
        "review_calls_budget_stopped": sum(
            1 for i in [*firsts, *seconds] if i["status"] == "budget_stopped"
        ),
    }


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
        "review_cost_usd": round(sum(r.get("review_cost_usd", 0.0) for r in ran), 6),
        "total_cost_usd": round(sum(r.get("total_cost_usd", r["cost_usd"]) for r in ran), 6),
        "review_input_tokens": sum(r.get("review_input_tokens", 0) for r in ran),
        "review_output_tokens": sum(r.get("review_output_tokens", 0) for r in ran),
        "reviews": review_counts(ran),
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


def _scrub_file(path: Path) -> None:
    path.write_text(scrub(path.read_text(encoding="utf-8")), encoding="utf-8")


def _review_csv(r: dict[str, Any]) -> dict[str, Any]:
    review = r.get("review")
    if not review:
        return {}
    return {
        "review_first": review["first_verdict"] or "",
        "review_revised": int(review["revised"]),
        "review_revision_clean": int(review["revision_clean"]),
        "review_second": review["second_verdict"] or "",
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
        scrub(json.dumps(summary, indent=2, ensure_ascii=False)), encoding="utf-8"
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
                    "review_cost_usd": r.get("review_cost_usd", 0.0),
                    "total_cost_usd": r.get("total_cost_usd", r["cost_usd"]),
                    "reasoning": r.get("reasoning", ""),
                    "revision": r["revision"].get("state", ""),
                    **_review_csv(r),
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
                    "review_cost_usd": agg["review_cost_usd"],
                    "total_cost_usd": agg["total_cost_usd"],
                    "reasoning": "/".join(agg["reasoning"]),
                    **{f"n_{k}": agg["mean_element_counts"][k] for k in COUNT_KINDS},
                }
            )
    _scrub_file(out / "summary.csv")
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
    review = r.get("review")
    if review:
        story = [review["first_verdict"] or "no review"]
        if review["revision"] not in ("not_needed", "not_attempted", "n/a"):
            story.append(review["revision"])
        if review["second_verdict"]:
            story.append(review["second_verdict"])
        detail += "  review: " + " > ".join(story)
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
# Review contact sheets: slides beside what the reviewer said
# ---------------------------------------------------------------------------

REVIEW_IMG_W = 600
REVIEW_TEXT_W = 780
REVIEW_LINE_H = 20
REVIEW_ROWS_PER_PAGE = 10
_GREEN, _ORANGE, _RED, _GREY, _INK = (
    (46, 125, 50),
    (200, 110, 0),
    (190, 40, 40),
    (110, 110, 110),
    (25, 25, 25),
)


@dataclass
class SheetRow:
    """One row of a review sheet: one or two captioned images, then text blocks."""

    title: str
    images: list[tuple[str, Path | None]]
    blocks: list[tuple[str, tuple[int, int, int], bool]] = field(default_factory=list)


def verdict_text(review: dict[str, Any] | None, label: str = "") -> tuple[str, tuple[int, ...]]:
    """(headline, colour) for one review summary or record."""
    prefix = f"{label}: " if label else ""
    if review is None:
        return f"{prefix}not reviewed", _GREY
    status = review["status"]
    if status == "budget_stopped":
        return f"{prefix}NOT RUN (budget guard)", _GREY
    if status != "ok":
        return f"{prefix}REVIEW FAILED: {review['error']}", _RED
    verdict = (review["verdict"] or "").upper()
    note = ""
    if review["downgraded"]:
        note = "  (the reviewer said revise with no blocking finding: counted as pass)"
    if review["pass_with_blocking"]:
        note = "  (passed, yet lists a blocking finding)"
    return f"{prefix}{verdict}{note}", _ORANGE if verdict == "REVISE" else _GREEN


def review_blocks(
    review: dict[str, Any] | None, label: str = ""
) -> list[tuple[str, tuple[int, int, int], bool]]:
    head, colour = verdict_text(review, label)
    blocks: list[tuple[str, tuple[int, int, int], bool]] = [
        (head, typing.cast(tuple[int, int, int], colour), True)
    ]
    if review is None or review["status"] != "ok":
        return blocks
    if review["summary"]:
        blocks.append((review["summary"], _INK, False))
    for n, f in enumerate(review["findings"], 1):
        colour = _RED if f["severity"] == "blocking" else _GREY
        blocks.append(
            (
                f"{n}. [{f['severity'].upper()}] {f['where']}\n"
                f"Problem: {f['problem']}\nFix: {f['fix']}",
                colour,
                False,
            )
        )
    if not review["findings"]:
        blocks.append(("No findings.", _GREY, False))
    return blocks


def write_row_sheet(
    out: Path, stem: str, title: str, subtitle: str, rows: Sequence[SheetRow]
) -> list[Path]:
    """Paginated sheets of rows (images left, wrapped text right). Text is never truncated:
    a row grows to hold it."""
    from PIL import Image, ImageDraw

    if not rows:
        return []
    pages = [
        rows[i : i + REVIEW_ROWS_PER_PAGE] for i in range(0, len(rows), REVIEW_ROWS_PER_PAGE)
    ]
    n_img = max(len(r.images) for r in rows)
    text_x = CELL_PAD + n_img * (REVIEW_IMG_W + CELL_PAD) + CELL_PAD
    width = text_x + REVIEW_TEXT_W + CELL_PAD
    f_title, f_bold, f_text = _font(26, True), _font(16, True), _font(15)
    f_cap = _font(13)
    paths: list[Path] = []
    for page_no, page in enumerate(pages, 1):
        layouts = []
        for row in page:
            probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
            lines: list[tuple[str, tuple[int, int, int], bool]] = [
                (line, _INK, True) for line in _wrap(probe, row.title, f_bold, REVIEW_TEXT_W)
            ]
            for text, colour, bold in row.blocks:
                for line in _wrap(probe, text, f_bold if bold else f_text, REVIEW_TEXT_W):
                    lines.append((line, colour, bold))
                lines.append(("", colour, False))
            img_h = round(REVIEW_IMG_W * 9 / 16) + 24
            height = max(img_h, len(lines) * REVIEW_LINE_H) + 2 * CELL_PAD
            layouts.append((row, lines, height))
        total_h = TITLE_H + sum(h + CELL_PAD for _, _, h in layouts) + CELL_PAD
        sheet = Image.new("RGB", (width, total_h), (245, 245, 245))
        draw = ImageDraw.Draw(sheet)
        suffix = f"  (page {page_no} of {len(pages)})" if len(pages) > 1 else ""
        draw.text((CELL_PAD, 12), title + suffix, font=f_title, fill=_INK)
        draw.text((CELL_PAD, 50), subtitle, font=f_text, fill=(60, 60, 60))
        y = TITLE_H
        for row, lines, height in layouts:
            draw.rectangle([CELL_PAD, y, width - CELL_PAD, y + height], fill=(255, 255, 255))
            for i, (caption, path) in enumerate(row.images):
                x = CELL_PAD * 2 + i * (REVIEW_IMG_W + CELL_PAD)
                draw.text((x, y + CELL_PAD), caption, font=f_cap, fill=(90, 90, 90))
                if path is not None and path.is_file():
                    with Image.open(path) as image:
                        image = image.convert("RGB")
                        image.thumbnail((REVIEW_IMG_W, REVIEW_IMG_W))
                        sheet.paste(image, (x, y + CELL_PAD + 20))
                        draw.rectangle(
                            [
                                x,
                                y + CELL_PAD + 20,
                                x + image.width,
                                y + CELL_PAD + 20 + image.height,
                            ],
                            outline=(200, 200, 200),
                        )
                else:
                    draw.text((x, y + CELL_PAD + 24), "(no image)", font=f_text, fill=_GREY)
            ty = y + CELL_PAD
            for text, colour, bold in lines:
                draw.text((text_x, ty), text, font=f_bold if bold else f_text, fill=colour)
                ty += REVIEW_LINE_H
            y += height + CELL_PAD
        name = f"{stem}-p{page_no}.png" if len(pages) > 1 else f"{stem}.png"
        path = out / name
        sheet.save(path)
        paths.append(path)
    return paths


def write_reviewed_sheet(
    out: Path, model: str, records: Sequence[dict[str, Any]]
) -> list[Path]:
    """For `--feedback review` trials: before and after side by side where a revision
    happened, the findings that prompted it, and both verdicts."""
    rows: list[SheetRow] = []
    for r in records:
        if r["model"] != model or not r.get("review") or not r["review"]["first"]:
            continue
        d = Path(r["dir"])
        review = r["review"]
        revised = review["revised"]
        images: list[tuple[str, Path | None]] = (
            [
                ("before (reviewed)", d / "slide.before.png"),
                ("after (revised)", d / "slide.png"),
            ]
            if revised
            else [("reviewed", d / "slide.png")]
        )
        blocks = review_blocks(review["first"], "first review")
        if revised or review["revision"] in ("failed", "kept_original", "skipped_budget"):
            blocks.append(
                (f"Designer revision: {review['revision']}", _INK, True),
            )
        if review["second"]:
            blocks += review_blocks(review["second"], "second review")
        cost = f"designer ${r['cost_usd']:.4f} + reviewer ${r['review_cost_usd']:.4f}"
        rows.append(
            SheetRow(f"{r['case']} | {r['concept']} | r{r['repeat']}   {cost}", images, blocks)
        )
    agg = aggregate([r for r in records if r["model"] == model])
    sub = (
        f"designer {model}   {agg['trials']} trials   designer ${agg['cost_usd']:.4f}  "
        f"reviewer ${agg['review_cost_usd']:.4f}  total ${agg['total_cost_usd']:.4f} "
        "(assumed prices)"
    )
    return write_row_sheet(
        out, f"sheet-reviewed-{model_dirname(model)}", f"Reviewed: {model}", sub, rows
    )


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
    reviewer: str | None = None
    allow_self_review: bool = False
    reviewer_reasoning: str | None = None  # default: the same as `reasoning`


def check_prices(models: Sequence[str], prices: dict[str, Price], allow_unpriced: bool) -> None:
    missing = [m for m in models if m not in prices]
    if missing and not allow_unpriced:
        raise BenchInputError(
            f"no assumed price for {', '.join(missing)} in prices.yaml; add one, or pass "
            "--allow-unpriced (the budget guard then cannot count that model's spend)"
        )


def refuse_self_review(reviewer: str, designers: Sequence[str], allow: bool) -> None:
    """The reviewer must be a different model from the designer it reviews."""
    same = [m for m in designers if m.strip().lower() == reviewer.strip().lower()]
    if same and not allow:
        raise BenchInputError(
            f"the reviewer {reviewer} is also a designer ({', '.join(same)}); a model "
            "reviewing its own slides is not the test. Pass --allow-self-review to do it anyway"
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
    if any(f not in ("qa", "visual", "review") for f in cfg.feedback):
        raise BenchInputError("--feedback must be qa, visual or review")
    reviewing = "review" in cfg.feedback
    if reviewing:
        if not cfg.reviewer:
            raise BenchInputError("--feedback review needs --reviewer provider:model")
        refuse_self_review(cfg.reviewer, cfg.models, cfg.allow_self_review)
        check_prices([cfg.reviewer], prices, cfg.allow_unpriced)
        if cfg.reviewer not in prices:
            log(f"WARNING: {cfg.reviewer} is unpriced; the budget guard cannot count it.")
    review_system = load_review_prompt(cfg.bench_dir) if reviewing else ""
    cfg.out.mkdir(parents=True, exist_ok=True)

    tokens_by_concept = {c.id: tokens_for_concept(c, cfg.tokens_path) for c in cfg.concepts}
    systems = {
        c.id: build_system_prompt(cfg.bench_dir, tokens_by_concept[c.id], c)
        for c in cfg.concepts
    }
    specs = expand_trials(cfg)

    providers: dict[str, ConverseModel] = {}
    reviewer_reasoning = cfg.reviewer_reasoning or cfg.reasoning
    for model in [*cfg.models, *([cfg.reviewer] if reviewing and cfg.reviewer else [])]:
        if model in providers:
            continue
        is_reviewer = model == cfg.reviewer and model not in cfg.models
        level = reviewer_reasoning if is_reviewer else cfg.reasoning
        if cfg.dry_run:
            providers[model] = make_provider(
                model,
                max_output_tokens=cfg.max_output_tokens,
                api_key="dry-run",
                reasoning=level,
                api=cfg.api,
            )
        elif provider_factory is not None:
            providers[model] = provider_factory(model)
        else:
            providers[model] = make_provider(
                model,
                max_output_tokens=cfg.max_output_tokens,
                reasoning=level,
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
        if reviewing:
            (cfg.out / "review-system.md").write_text(review_system, encoding="utf-8")
            sample = build_review_user_text(specs[0].case, specs[0].concept, cfg.tokens_path)
            (cfg.out / "review-user-sample.md").write_text(sample, encoding="utf-8")
        log(
            f"dry run: {len(listing)} requests written under {cfg.out}; about {total:,} input "
            "tokens for the first call of every trial (later calls and revisions add more). "
            "No model was called."
        )
        return {"dry_run": True, "requests": listing}

    ledger = Ledger(cfg.budget)
    reviewer_obj: Reviewer | None = None
    if reviewing and cfg.reviewer:
        reviewer_obj = Reviewer(
            cfg.reviewer,
            providers[cfg.reviewer],
            review_system,
            prices.get(cfg.reviewer),
            ledger,
            reasoning=effective_reasoning(cfg.reviewer, reviewer_reasoning, cfg.api),
            tokens_path=cfg.tokens_path,
        )
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
                reviewer=reviewer_obj,
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
    reviews_skipped = [
        f"{r['model']} {r['case']} {r['concept']} r{r['repeat']} ({which})"
        for r in records
        if r.get("review")
        for which in ("first", "second")
        if (r["review"][which] or {}).get("status") == "budget_stopped"
    ]
    budget_report = {
        "budget_usd": cfg.budget,
        "estimated_spend_usd": round(ledger.spent, 6),
        "guard_tripped": bool(skipped or stopped or revisions_skipped or reviews_skipped),
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
        "reviews_skipped": reviews_skipped,
    }
    extra = {
        "budget": budget_report,
        "prices": {
            m: {"input": p.input, "output": p.output}
            for m, p in prices.items()
            if m in cfg.models or m == cfg.reviewer
        },
        "prices_note": "assumed, deliberately high; not confirmed prices",
        "config": {
            "models": cfg.models,
            "cases": [c.id for c in cfg.cases],
            "concepts": [c.id for c in cfg.concepts],
            "feedback": cfg.feedback,
            "reviewer": cfg.reviewer if reviewing else None,
            "reviewer_reasoning": (
                effective_reasoning(cfg.reviewer or "", reviewer_reasoning, cfg.api)
                if reviewing
                else None
            ),
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
        for reviewed in write_reviewed_sheet(cfg.out, model, records) if reviewing else []:
            log(f"contact sheet (review): {reviewed}")
    if budget_report["guard_tripped"]:
        log(
            f"BUDGET GUARD: estimated spend ${ledger.spent:.4f} reached ${cfg.budget:.2f}. "
            f"{len(skipped)} trials not started, {len(stopped)} stopped mid-trial, "
            f"{len(revisions_skipped)} revisions and {len(reviews_skipped)} reviews skipped. "
            "See summary.json budget."
        )
    log(f"summary: {cfg.out / 'summary.json'}  total estimated ${ledger.spent:.4f}")
    return summary


# ---------------------------------------------------------------------------
# Review-only mode: review slides that already exist
# ---------------------------------------------------------------------------

REVIEW_INPUT_NAME = "review-input.json"


def _slide_dirs(root: Path) -> list[Path]:
    return sorted({p.parent for p in root.rglob("slide.png")})


def item_from_directory(directory: Path, bench_dir: Path) -> ReviewItem:
    """A `ReviewItem` for a directory holding `slide.png` and either `review-input.json`
    (the case and concept written out, as `convert_studio_deck` does) or a bench
    `trial.json` (the case and concept ids, read from `bench_dir`)."""
    image = directory / "slide.png"
    designer = ""
    explicit = directory / REVIEW_INPUT_NAME
    trial_json = directory / "trial.json"
    if explicit.is_file():
        raw = json.loads(explicit.read_text(encoding="utf-8"))
        try:
            case = Case.model_validate(raw["case"])
            concept = Concept.model_validate(raw.get("concept") or {"id": "none"})
        except (KeyError, ValidationError) as exc:
            raise BenchInputError(f"{explicit}: not a usable review input: {exc}") from exc
        designer = str(raw.get("designer_model", ""))
        label = directory.name
    elif trial_json.is_file():
        trial = json.loads(trial_json.read_text(encoding="utf-8"))
        case_path = bench_dir / "cases" / f"{trial.get('case')}.yaml"
        concept_path = bench_dir / "concepts" / f"{trial.get('concept')}.yaml"
        if not case_path.is_file() or not concept_path.is_file():
            raise BenchInputError(
                f"{directory}: its case or concept ({trial.get('case')}, "
                f"{trial.get('concept')}) is not in {bench_dir}"
            )
        case, concept = load_case(case_path), load_concept(concept_path)
        designer = str(trial.get("model", ""))
        label = "__".join(
            [
                model_dirname(designer) or "unknown",
                case.id,
                concept.id,
                str(trial.get("feedback", "")),
                f"r{trial.get('repeat', 1)}",
            ]
        )
    else:
        raise BenchInputError(
            f"{directory}: has slide.png but neither {REVIEW_INPUT_NAME} nor trial.json, so "
            "the case and concept cannot be recovered"
        )
    return ReviewItem(
        label=label,
        image=image,
        case=case,
        concept=concept,
        source=str(directory),
        designer_model=designer,
    )


def discover_review_items(
    directories: Sequence[Path], bench_dir: Path, log: Callable[[str], None] = print
) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for root in directories:
        if not root.is_dir():
            raise BenchInputError(f"{root}: not a directory")
        found = _slide_dirs(root)
        if not found:
            log(f"WARNING: no slide.png under {root}")
        for directory in found:
            items.append(item_from_directory(directory, bench_dir))
    return items


def triple_item(spec: str, bench_dir: Path) -> ReviewItem:
    """`image,case,concept` -> an item; the ids are looked up in `bench_dir`."""
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 3 or not all(parts):
        raise BenchInputError(f"--review-item {spec!r} must be image,case,concept")
    image, case_id, concept_id = parts
    path = Path(image)
    if not path.is_file():
        raise BenchInputError(f"--review-item: {path} is not a file")
    case = resolve_cases(case_id, bench_dir)[0]
    concept = resolve_concepts(concept_id, bench_dir)[0]
    return ReviewItem(
        label=f"{path.stem}__{case.id}__{concept.id}",
        image=path,
        case=case,
        concept=concept,
        source=str(path),
    )


def _studio_case(slide: dict[str, Any]) -> Case:
    brief = slide.get("brief") or {}
    content = brief.get("content") or {}
    chart = content.get("chart")
    data: dict[str, Any] = {
        "id": str(slide.get("id") or "slide"),
        "title": str(brief.get("header") or ""),
        "intent": str(brief.get("intent") or slide.get("intent") or ""),
        "content": {
            "points": [str(p) for p in content.get("points") or []],
            "figures": [
                {"value": str(f.get("value", "")), "label": str(f.get("label", ""))}
                for f in content.get("figures") or []
            ],
            "chart": chart if isinstance(chart, dict) and chart.get("series") else None,
        },
        "notes": str(brief.get("notes") or ""),
    }
    if not data["title"]:
        for block in slide.get("blocks") or []:
            if block.get("kind") == "text" and block.get("text"):
                data["title"] = str(block["text"])
                break
    return Case.model_validate(data)


def _studio_concept(deck: dict[str, Any]) -> Concept:
    system = deck.get("design_system") or {}
    direction = deck.get("design_concept") or {}
    palette = {k: str(v) for k, v in (system.get("palette") or {}).items()}
    return Concept.model_validate(
        {
            "id": str(system.get("id") or "deck"),
            "name": str(direction.get("name") or system.get("id") or ""),
            "concept": str(direction.get("concept") or direction.get("idea") or ""),
            "rules": [str(x) for x in direction.get("rules") or []],
            "palette": palette,
            "roles": {k: str(v) for k, v in (system.get("roles") or {}).items()},
        }
    )


def convert_studio_deck(
    deck_path: Path,
    images: Sequence[Path],
    out_dir: Path,
    only: Sequence[int] | None = None,
) -> list[Path]:
    """Turn a studio deck JSON and one render per slide (in slide order) into directories a
    review run can read: `slide.json`, `slide.png`, `review-input.json`. Returns them.
    `only` keeps just those slide numbers (1-based)."""
    try:
        deck = json.loads(deck_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BenchInputError(f"{deck_path}: not readable as a deck: {exc}") from exc
    slides = deck.get("slides")
    if not isinstance(slides, list) or not slides:
        raise BenchInputError(f"{deck_path}: no slides")
    if len(images) != len(slides):
        raise BenchInputError(
            f"{deck_path} has {len(slides)} slides but {len(images)} images were given"
        )
    concept = _studio_concept(deck)
    deck_id = str(deck.get("id") or "deck")
    made: list[Path] = []
    for n, (slide, image) in enumerate(zip(slides, images, strict=True), 1):
        if only is not None and n not in only:
            continue
        case = _studio_case(slide)
        directory = out_dir / f"{deck_id}-{n:02d}-{case.id}"
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image, directory / "slide.png")
        (directory / "slide.json").write_text(
            json.dumps(slide, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (directory / REVIEW_INPUT_NAME).write_text(
            json.dumps(
                {
                    "case": case.model_dump(),
                    "concept": concept.model_dump(),
                    "source_image": str(image),
                    "source_deck": str(deck_path),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        made.append(directory)
    return made


@dataclass
class ReviewOnlyConfig:
    reviewer: str
    items: list[ReviewItem]
    budget: float
    out: Path
    bench_dir: Path = BENCH_DIR
    prices_path: Path = field(default_factory=lambda: BENCH_DIR / "prices.yaml")
    tokens_path: Path = DEFAULT_TOKENS_PATH
    reasoning: str = "medium"
    api: str = "auto"
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    allow_unpriced: bool = False
    allow_self_review: bool = False
    workers: int = 1
    dry_run: bool = False


def _unique_labels(items: Sequence[ReviewItem]) -> list[str]:
    seen: Counter[str] = Counter()
    labels = []
    for item in items:
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", item.label)
        seen[base] += 1
        labels.append(base if seen[base] == 1 else f"{base}-{seen[base]}")
    return labels


REVIEW_CSV_COLUMNS = [
    "slide",
    "case",
    "concept",
    "designer_model",
    "status",
    "verdict",
    "raw_verdict",
    "downgraded",
    "n_blocking",
    "n_minor",
    "summary",
    "findings",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "seconds",
    "cost_usd",
    "source",
    "error",
]


def run_review_only(
    cfg: ReviewOnlyConfig,
    *,
    provider_factory: Callable[[str], ConverseModel] | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Review every item once; write `review.json` per slide, summary.json/csv and the
    sheet. No designer is called."""
    prices = load_prices(cfg.prices_path)
    check_prices([cfg.reviewer], prices, cfg.allow_unpriced)
    if cfg.reviewer not in prices:
        log(f"WARNING: {cfg.reviewer} is unpriced; the budget guard cannot count its spend.")
    if cfg.reasoning not in REASONING_LEVELS:
        raise BenchInputError(f"--reasoning must be one of {', '.join(REASONING_LEVELS)}")
    if not cfg.items:
        raise BenchInputError("nothing to review: no slides found")
    designers = sorted({i.designer_model for i in cfg.items if i.designer_model})
    refuse_self_review(cfg.reviewer, designers, cfg.allow_self_review)
    system = load_review_prompt(cfg.bench_dir)
    cfg.out.mkdir(parents=True, exist_ok=True)
    labels = _unique_labels(cfg.items)
    base = cfg.out / model_dirname(cfg.reviewer)

    if cfg.dry_run:
        listing = []
        for item, label in zip(cfg.items, labels, strict=True):
            directory = base / label
            directory.mkdir(parents=True, exist_ok=True)
            text = build_review_user_text(item.case, item.concept, cfg.tokens_path)
            (directory / "user.md").write_text(text, encoding="utf-8")
            listing.append({"slide": label, "image": str(item.image), "dir": str(directory)})
        (cfg.out / "review-system.md").write_text(system, encoding="utf-8")
        (cfg.out / "dry-run.json").write_text(json.dumps(listing, indent=2), encoding="utf-8")
        log(
            f"dry run: {len(listing)} review requests written under {base}. "
            "No model was called."
        )
        return {"dry_run": True, "requests": listing}

    if provider_factory is not None:
        model = provider_factory(cfg.reviewer)
    else:
        model = make_provider(
            cfg.reviewer,
            max_output_tokens=cfg.max_output_tokens,
            reasoning=cfg.reasoning,
            api=cfg.api,
        )
    ledger = Ledger(cfg.budget)
    reviewer = Reviewer(
        cfg.reviewer,
        model,
        system,
        prices.get(cfg.reviewer),
        ledger,
        reasoning=effective_reasoning(cfg.reviewer, cfg.reasoning, cfg.api),
        tokens_path=cfg.tokens_path,
    )
    results: list[dict[str, Any]] = [{} for _ in cfg.items]
    done = 0
    lock = threading.Lock()
    started = time.time()

    def work(index: int) -> None:
        nonlocal done
        item, label = cfg.items[index], labels[index]
        directory = base / label
        record = reviewer.review(item)  # a budget stop is recorded, not raised
        write_review_files(directory, "review", record, item.image.name)
        record["_dir"] = str(directory)
        results[index] = record
        with lock:
            done += 1
            log(
                f"[{done}/{len(cfg.items)}] {label}: {record['status']} "
                f"{record['verdict'] or ''} ${record['cost_usd']:.4f} "
                f"(total ${ledger.spent:.4f}/{cfg.budget:.2f})"
                + (f" error: {record['error'][:120]}" if record["error"] else "")
            )

    if cfg.workers > 1:
        with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
            list(pool.map(work, range(len(cfg.items))))
    else:
        for index in range(len(cfg.items)):
            work(index)

    rows = []
    for item, label, record in zip(cfg.items, labels, results, strict=True):
        fields = review_summary_fields(record) or {}
        rows.append(
            {
                "slide": label,
                "case": item.case.id,
                "concept": item.concept.id,
                "designer_model": item.designer_model,
                "source": item.source,
                "image": str(item.image),
                "dir": record["_dir"],
                "reasoning_tokens": record["reasoning_tokens"],
                **fields,
            }
        )
    counts = {
        "reviewed": len(rows),
        "pass": sum(r["verdict"] == "pass" for r in rows),
        "revise": sum(r["verdict"] == "revise" for r in rows),
        "downgraded": sum(bool(r["downgraded"]) for r in rows),
        "failed": sum(r["status"] == "failed" for r in rows),
        "budget_stopped": sum(r["status"] == "budget_stopped" for r in rows),
    }
    summary = {
        "reviewer": cfg.reviewer,
        "counts": counts,
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "reasoning_tokens": sum(r["reasoning_tokens"] for r in rows),
        "seconds": round(sum(r["seconds"] for r in rows), 2),
        "review_cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
        "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
        "budget": {
            "budget_usd": cfg.budget,
            "estimated_spend_usd": round(ledger.spent, 6),
            "guard_tripped": counts["budget_stopped"] > 0,
            "not_reviewed": [r["slide"] for r in rows if r["status"] == "budget_stopped"],
        },
        "config": {
            "reasoning_requested": cfg.reasoning,
            "reasoning": effective_reasoning(cfg.reviewer, cfg.reasoning, cfg.api),
            "endpoint": "responses"
            if uses_responses(cfg.reviewer, cfg.api)
            else "chat.completions",
        },
        "prices": {
            cfg.reviewer: {
                "input": prices[cfg.reviewer].input,
                "output": prices[cfg.reviewer].output,
            }
        }
        if cfg.reviewer in prices
        else {},
        "prices_note": "assumed, deliberately high; not confirmed prices",
        "wall_seconds": round(time.time() - started, 1),
        "slides": rows,
    }
    (cfg.out / "summary.json").write_text(
        scrub(json.dumps(summary, indent=2, ensure_ascii=False)), encoding="utf-8"
    )
    with (cfg.out / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "findings": " | ".join(
                        f"[{f['severity']}] {f['where']}: {f['problem']} -> {f['fix']}"
                        for f in row.get("findings", [])
                    ),
                }
            )
    _scrub_file(cfg.out / "summary.csv")
    sheet_rows = [
        SheetRow(
            f"{row['slide']}   (case {row['case']}, concept {row['concept']})   "
            f"${row['cost_usd']:.4f}",
            [("", Path(row["image"]))],
            review_blocks(row),
        )
        for row in rows
    ]
    subtitle = (
        f"{counts['reviewed']} slides   pass {counts['pass']}   revise {counts['revise']}   "
        f"failed {counts['failed']}   ${summary['total_cost_usd']:.4f} estimated "
        f"(assumed prices)   reasoning {summary['config']['reasoning']}"
    )
    for sheet in write_row_sheet(
        cfg.out,
        f"sheet-review-{model_dirname(cfg.reviewer)}",
        f"Reviewer: {cfg.reviewer}",
        subtitle,
        sheet_rows,
    ):
        log(f"contact sheet: {sheet}")
    if counts["budget_stopped"]:
        log(
            f"BUDGET GUARD: estimated spend ${ledger.spent:.4f} reached ${cfg.budget:.2f}; "
            f"{counts['budget_stopped']} slides not reviewed. See summary.json budget."
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
        default=[],
        help="designer, provider:model; repeat for several models (not used by review-only "
        "mode)",
    )
    p.add_argument("--cases", default="all", help="all, or comma-separated case ids")
    p.add_argument("--concepts", default="none", help="comma-separated concept ids")
    p.add_argument(
        "--feedback",
        default="qa",
        help="qa, visual, review, or a comma list. visual shows the designer its own render "
        "once; review has the --reviewer critique the clean slide and sends its findings back "
        "for one revision",
    )
    p.add_argument("--reviewer", help="provider:model of the slide reviewer (review modes)")
    p.add_argument(
        "--allow-self-review",
        action="store_true",
        help="let the reviewer be the same model as a designer it reviews",
    )
    p.add_argument(
        "--reviewer-reasoning",
        choices=REASONING_LEVELS,
        help="reasoning effort for the reviewer (default: the value of --reasoning)",
    )
    p.add_argument(
        "--review-dir",
        action="append",
        type=Path,
        default=[],
        help="review-only mode: a directory of existing trial outputs (every slide.png under "
        "it); repeatable",
    )
    p.add_argument(
        "--review-item",
        action="append",
        default=[],
        help="review-only mode: image,case,concept (ids from the bench directory); repeatable",
    )
    p.add_argument(
        "--studio-deck",
        type=Path,
        help="review-only mode: a studio deck JSON (current.json) whose slides to review, "
        "with --studio-images",
    )
    p.add_argument(
        "--studio-slides",
        help="only these slide numbers of --studio-deck, 1-based, comma-separated (e.g. 1,4)",
    )
    p.add_argument(
        "--studio-images",
        nargs="+",
        type=Path,
        help="one render per slide of --studio-deck, in slide order",
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
    review_only = bool(args.review_dir or args.review_item or args.studio_deck)
    prices_path = (
        args.bench_dir / "prices.yaml"
        if (args.bench_dir / "prices.yaml").is_file()
        else BENCH_DIR / "prices.yaml"
    )
    try:
        if review_only:
            if not args.reviewer:
                raise BenchInputError("review-only mode needs --reviewer provider:model")
            if args.models:
                raise BenchInputError("review-only mode designs nothing: drop --env-model")
            items = discover_review_items(args.review_dir, args.bench_dir)
            items += [triple_item(s, args.bench_dir) for s in args.review_item]
            if args.studio_deck:
                if not args.studio_images:
                    raise BenchInputError("--studio-deck needs --studio-images")
                converted = convert_studio_deck(
                    args.studio_deck,
                    args.studio_images,
                    args.out / "inputs" / "studio",
                    only=[int(x) for x in _csv(args.studio_slides)]
                    if args.studio_slides
                    else None,
                )
                items += discover_review_items(converted, args.bench_dir)
            run_review_only(
                ReviewOnlyConfig(
                    reviewer=args.reviewer,
                    items=items,
                    budget=args.budget,
                    out=args.out,
                    bench_dir=args.bench_dir,
                    prices_path=prices_path,
                    reasoning=args.reviewer_reasoning or args.reasoning,
                    api=args.api,
                    max_output_tokens=args.max_output_tokens,
                    allow_unpriced=args.allow_unpriced,
                    allow_self_review=args.allow_self_review,
                    workers=args.workers,
                    dry_run=args.dry_run,
                )
            )
            return 0
        if not args.models:
            raise BenchInputError("give at least one --env-model (or use review-only mode)")
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
            prices_path=prices_path,
            reviewer=args.reviewer,
            allow_self_review=args.allow_self_review,
            reviewer_reasoning=args.reviewer_reasoning,
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
