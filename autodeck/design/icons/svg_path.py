"""SVG path data → a normalised segment list.

Everything reduces to four primitives: move, line, cubic Bézier, close. Arcs and quadratics
are converted rather than carried through, because DrawingML's `a:arcTo` is parameterised
by swing angles rather than by SVG's endpoint form, and the conversion is the same
arithmetic either way — done once here, it is testable in isolation instead of tangled into
XML generation.

The parser handles the full path grammar: absolute and relative forms of M, L, H, V, C, S,
Q, T, A, Z, implicit repeated commands, and the reflection rules for S and T.

Owning phase: 0 (spike 0.6).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_COMMAND = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")
_SEPARATOR = re.compile(r"[\s,]*")

#: Circle/ellipse approximation constant: control-point offset for a 90° arc.
KAPPA = 0.5522847498307936


class SvgPathError(ValueError):
    """Malformed or unsupported path data."""


@dataclass(frozen=True)
class Move:
    x: float
    y: float


@dataclass(frozen=True)
class Line:
    x: float
    y: float


@dataclass(frozen=True)
class Cubic:
    x1: float
    y1: float
    x2: float
    y2: float
    x: float
    y: float


@dataclass(frozen=True)
class Close:
    pass


Segment = Move | Line | Cubic | Close
SubPath = list[Segment]

#: How many arguments each command consumes per repetition.
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}

#: Positions within an `A` command that are **flags** — a single character, `0` or `1`.
#: SVG allows flags to run together with the following number (`0 00-2.474` is
#: rotation=0, large-arc=0, sweep=0, x=-2.474), so they cannot be read with a number
#: pattern: `00` would scan as the single value 0. Lucide's `zap` icon does exactly this,
#: which is how the case was found rather than guessed at.
_ARC_FLAG_POSITIONS = frozenset({3, 4})


def parse_path(data: str) -> list[SubPath]:
    """Parse SVG path data into subpaths of normalised segments.

    Returns:
        One list of segments per subpath. Compound paths (an icon with a hole, or several
        disconnected strokes in one `d`) come back as several subpaths.

    Raises:
        SvgPathError: the data is malformed.
    """
    if not data.strip():
        return []
    return _Parser(data).run()


class _Parser:
    """Scans the path string, tracking current point and reflection state.

    A character-position scanner rather than a pre-tokenised list, because arc flags are
    only distinguishable from numbers by knowing which argument position you are at.
    """

    def __init__(self, data: str) -> None:
        self.data = data
        self.index = 0
        self.x = 0.0
        self.y = 0.0
        self.start_x = 0.0
        self.start_y = 0.0
        self.last_cubic_control: tuple[float, float] | None = None
        self.last_quad_control: tuple[float, float] | None = None
        self.subpaths: list[SubPath] = []
        self.current: SubPath = []

    def run(self) -> list[SubPath]:
        command = ""
        self._skip_separators()

        while self.index < len(self.data):
            match = _COMMAND.match(self.data, self.index)
            if match:
                command = match.group()
                self.index = match.end()
                self._skip_separators()
            elif not command:
                raise SvgPathError(
                    f"path data starts with a number, not a command: {self.data[:16]!r}"
                )
            elif command in ("M", "m"):
                # An implicit repeat after a moveto is a lineto, per the SVG grammar.
                command = "L" if command == "M" else "l"

            self._execute(command)
            self._skip_separators()

        self._flush()
        return self.subpaths

    # -- scanning ---------------------------------------------------------

    def _skip_separators(self) -> None:
        self.index = _SEPARATOR.match(self.data, self.index).end()  # type: ignore[union-attr]

    def _read_number(self) -> float:
        match = _NUMBER.match(self.data, self.index)
        if not match:
            raise SvgPathError(
                f"expected a number at offset {self.index} in path data: "
                f"{self.data[self.index : self.index + 16]!r}"
            )
        self.index = match.end()
        self._skip_separators()
        return float(match.group())

    def _read_flag(self) -> float:
        """Read a single-character arc flag.

        Reading this as a number is the classic SVG parsing bug: in `0 00-2.474` the two
        flags are packed against each other and against the following coordinate.
        """
        if self.index >= len(self.data) or self.data[self.index] not in "01":
            raise SvgPathError(
                f"expected an arc flag (0 or 1) at offset {self.index}: "
                f"{self.data[self.index : self.index + 8]!r}"
            )
        value = float(self.data[self.index])
        self.index += 1
        self._skip_separators()
        return value

    def _arguments(self, command: str) -> list[float]:
        """Read one command's arguments, treating arc flags as flags."""
        count = _ARITY[command]
        if command != "A":
            return [self._read_number() for _ in range(count)]
        return [
            self._read_flag() if position in _ARC_FLAG_POSITIONS else self._read_number()
            for position in range(count)
        ]

    def _flush(self) -> None:
        if self.current:
            self.subpaths.append(self.current)
            self.current = []

    def _emit(self, segment: Segment) -> None:
        self.current.append(segment)

    # -- commands ---------------------------------------------------------

    def _execute(self, command: str) -> None:
        upper = command.upper()
        relative = command.islower()

        if upper == "Z":
            self._emit(Close())
            self.x, self.y = self.start_x, self.start_y
            self.last_cubic_control = self.last_quad_control = None
            return

        if upper not in _ARITY:
            raise SvgPathError(f"unsupported path command {command!r}")

        args = self._arguments(upper)
        handler = getattr(self, f"_cmd_{upper.lower()}")
        handler(args, relative)

    def _cmd_m(self, args: list[float], relative: bool) -> None:
        x, y = args
        self.x = self.x + x if relative else x
        self.y = self.y + y if relative else y
        self._flush()
        self.start_x, self.start_y = self.x, self.y
        self._emit(Move(self.x, self.y))
        self.last_cubic_control = self.last_quad_control = None

    def _cmd_l(self, args: list[float], relative: bool) -> None:
        x, y = args
        self.x = self.x + x if relative else x
        self.y = self.y + y if relative else y
        self._emit(Line(self.x, self.y))
        self.last_cubic_control = self.last_quad_control = None

    def _cmd_h(self, args: list[float], relative: bool) -> None:
        self.x = self.x + args[0] if relative else args[0]
        self._emit(Line(self.x, self.y))
        self.last_cubic_control = self.last_quad_control = None

    def _cmd_v(self, args: list[float], relative: bool) -> None:
        self.y = self.y + args[0] if relative else args[0]
        self._emit(Line(self.x, self.y))
        self.last_cubic_control = self.last_quad_control = None

    def _cmd_c(self, args: list[float], relative: bool) -> None:
        x1, y1, x2, y2, x, y = args
        if relative:
            x1, y1 = x1 + self.x, y1 + self.y
            x2, y2 = x2 + self.x, y2 + self.y
            x, y = x + self.x, y + self.y
        self._cubic(x1, y1, x2, y2, x, y)

    def _cmd_s(self, args: list[float], relative: bool) -> None:
        """Smooth cubic: the first control point mirrors the previous one."""
        x2, y2, x, y = args
        if relative:
            x2, y2 = x2 + self.x, y2 + self.y
            x, y = x + self.x, y + self.y
        x1, y1 = self._reflect(self.last_cubic_control)
        self._cubic(x1, y1, x2, y2, x, y)

    def _cmd_q(self, args: list[float], relative: bool) -> None:
        qx, qy, x, y = args
        if relative:
            qx, qy = qx + self.x, qy + self.y
            x, y = x + self.x, y + self.y
        self._quadratic(qx, qy, x, y)

    def _cmd_t(self, args: list[float], relative: bool) -> None:
        """Smooth quadratic: the control point mirrors the previous one."""
        x, y = args
        if relative:
            x, y = x + self.x, y + self.y
        qx, qy = self._reflect(self.last_quad_control)
        self._quadratic(qx, qy, x, y)

    def _cmd_a(self, args: list[float], relative: bool) -> None:
        rx, ry, rotation, large_arc, sweep, x, y = args
        if relative:
            x, y = x + self.x, y + self.y
        for cubic in arc_to_cubics(
            self.x, self.y, rx, ry, rotation, bool(large_arc), bool(sweep), x, y
        ):
            self._emit(cubic)
        self.x, self.y = x, y
        self.last_cubic_control = self.last_quad_control = None

    # -- emission ---------------------------------------------------------

    def _cubic(self, x1: float, y1: float, x2: float, y2: float, x: float, y: float) -> None:
        self._emit(Cubic(x1, y1, x2, y2, x, y))
        self.x, self.y = x, y
        self.last_cubic_control = (x2, y2)
        self.last_quad_control = None

    def _quadratic(self, qx: float, qy: float, x: float, y: float) -> None:
        """Exact quadratic → cubic elevation. No approximation is involved."""
        x1 = self.x + 2 / 3 * (qx - self.x)
        y1 = self.y + 2 / 3 * (qy - self.y)
        x2 = x + 2 / 3 * (qx - x)
        y2 = y + 2 / 3 * (qy - y)
        self._emit(Cubic(x1, y1, x2, y2, x, y))
        self.x, self.y = x, y
        self.last_quad_control = (qx, qy)
        self.last_cubic_control = None

    def _reflect(self, control: tuple[float, float] | None) -> tuple[float, float]:
        """Mirror the previous control point about the current point.

        With no previous control point of the matching kind, SVG says the control point
        coincides with the current point.
        """
        if control is None:
            return self.x, self.y
        return 2 * self.x - control[0], 2 * self.y - control[1]


# ---------------------------------------------------------------------------
# Arc conversion
# ---------------------------------------------------------------------------


def arc_to_cubics(
    x0: float,
    y0: float,
    rx: float,
    ry: float,
    rotation_deg: float,
    large_arc: bool,
    sweep: bool,
    x: float,
    y: float,
) -> list[Cubic]:
    """Convert an SVG elliptical arc to cubic Béziers.

    Implements the endpoint-to-centre parameterisation from the SVG specification
    (appendix F.6), then splits the sweep into segments of at most 90° — beyond that a
    single cubic's error becomes visible at the sizes icons are actually scaled to.

    Degenerate cases (zero radius, coincident endpoints) fall back to a straight line, as
    the specification requires.
    """
    if x0 == x and y0 == y:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [Cubic(x0, y0, x, y, x, y)]

    phi = math.radians(rotation_deg % 360)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)

    dx2 = (x0 - x) / 2
    dy2 = (y0 - y) / 2
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    # Scale radii up if they are too small to span the endpoints (spec F.6.6).
    lambda_ = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lambda_ > 1:
        scale = math.sqrt(lambda_)
        rx *= scale
        ry *= scale

    numerator = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    denominator = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    factor = math.sqrt(max(numerator / denominator, 0.0)) if denominator else 0.0
    if large_arc == sweep:
        factor = -factor

    cxp = factor * rx * y1p / ry
    cyp = -factor * ry * x1p / rx
    cx = cos_phi * cxp - sin_phi * cyp + (x0 + x) / 2
    cy = sin_phi * cxp + cos_phi * cyp + (y0 + y) / 2

    start_angle = _angle(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = _angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    delta %= 2 * math.pi
    if not sweep:
        delta -= 2 * math.pi

    steps = max(math.ceil(abs(delta) / (math.pi / 2)), 1)
    step = delta / steps

    cubics: list[Cubic] = []
    angle = start_angle
    for _ in range(steps):
        cubics.append(_arc_segment(cx, cy, rx, ry, cos_phi, sin_phi, angle, angle + step))
        angle += step
    return cubics


def _angle(ux: float, uy: float, vx: float, vy: float) -> float:
    """Signed angle between two vectors."""
    dot = ux * vx + uy * vy
    magnitude = math.sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy))
    if magnitude == 0:
        return 0.0
    value = max(-1.0, min(1.0, dot / magnitude))
    sign = -1.0 if (ux * vy - uy * vx) < 0 else 1.0
    return sign * math.acos(value)


def _arc_segment(
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    cos_phi: float,
    sin_phi: float,
    start: float,
    end: float,
) -> Cubic:
    """One arc span of at most 90° as a cubic Bézier."""
    alpha = 4 / 3 * math.tan((end - start) / 4)

    def point(angle: float) -> tuple[float, float]:
        px = rx * math.cos(angle)
        py = ry * math.sin(angle)
        return cx + cos_phi * px - sin_phi * py, cy + sin_phi * px + cos_phi * py

    def derivative(angle: float) -> tuple[float, float]:
        dx = -rx * math.sin(angle)
        dy = ry * math.cos(angle)
        return cos_phi * dx - sin_phi * dy, sin_phi * dx + cos_phi * dy

    x1, y1 = point(start)
    x2, y2 = point(end)
    dx1, dy1 = derivative(start)
    dx2, dy2 = derivative(end)

    return Cubic(
        x1 + alpha * dx1,
        y1 + alpha * dy1,
        x2 - alpha * dx2,
        y2 - alpha * dy2,
        x2,
        y2,
    )


# ---------------------------------------------------------------------------
# Primitive shapes
# ---------------------------------------------------------------------------


def circle_subpath(cx: float, cy: float, r: float) -> SubPath:
    """A circle as four cubic Béziers.

    Lucide uses `<circle>` freely (`target` is three of them), so this is a live path, not a
    completeness exercise.
    """
    offset = r * KAPPA
    return [
        Move(cx + r, cy),
        Cubic(cx + r, cy + offset, cx + offset, cy + r, cx, cy + r),
        Cubic(cx - offset, cy + r, cx - r, cy + offset, cx - r, cy),
        Cubic(cx - r, cy - offset, cx - offset, cy - r, cx, cy - r),
        Cubic(cx + offset, cy - r, cx + r, cy - offset, cx + r, cy),
        Close(),
    ]


def ellipse_subpath(cx: float, cy: float, rx: float, ry: float) -> SubPath:
    ox, oy = rx * KAPPA, ry * KAPPA
    return [
        Move(cx + rx, cy),
        Cubic(cx + rx, cy + oy, cx + ox, cy + ry, cx, cy + ry),
        Cubic(cx - ox, cy + ry, cx - rx, cy + oy, cx - rx, cy),
        Cubic(cx - rx, cy - oy, cx - ox, cy - ry, cx, cy - ry),
        Cubic(cx + ox, cy - ry, cx + rx, cy - oy, cx + rx, cy),
        Close(),
    ]


def rect_subpath(x: float, y: float, width: float, height: float, rx: float = 0.0) -> SubPath:
    """A rectangle, optionally with rounded corners."""
    if rx <= 0:
        return [
            Move(x, y),
            Line(x + width, y),
            Line(x + width, y + height),
            Line(x, y + height),
            Close(),
        ]
    r = min(rx, width / 2, height / 2)
    k = r * KAPPA
    return [
        Move(x + r, y),
        Line(x + width - r, y),
        Cubic(x + width - r + k, y, x + width, y + r - k, x + width, y + r),
        Line(x + width, y + height - r),
        Cubic(
            x + width,
            y + height - r + k,
            x + width - r + k,
            y + height,
            x + width - r,
            y + height,
        ),
        Line(x + r, y + height),
        Cubic(x + r - k, y + height, x, y + height - r + k, x, y + height - r),
        Line(x, y + r),
        Cubic(x, y + r - k, x + r - k, y, x + r, y),
        Close(),
    ]


def polyline_subpath(points: list[tuple[float, float]], close: bool = False) -> SubPath:
    if not points:
        return []
    segments: SubPath = [Move(*points[0])]
    segments.extend(Line(px, py) for px, py in points[1:])
    if close:
        segments.append(Close())
    return segments
