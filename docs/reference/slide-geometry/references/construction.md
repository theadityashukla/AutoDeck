# Construction recipes

> **AutoDeck vendoring note (added by AutoDeck, not part of the upstream skill).**
> This is a verbatim copy of the owner's `slide-geometry` skill, vendored per plan
> §6.11.2 as the seed source for `DiagramSpec` types, art-direction selection rules,
> and label-placement conventions.
>
> **For AutoDeck implementation, the `python-pptx MSO_SHAPE` column of the shape
> vocabulary table below is authoritative.** The `pptxgenjs` column and the pptxgenjs
> canvas dimensions in the paragraph that follows are cross-reference only — decision
> D5 and plan §6.6 rejection (c) rule out JS generators for AutoDeck. Read past the
> leftmost column.
>
> AutoDeck's canvas is set by the theme/master builder (§6.8), not by a pptxgenjs
> `LAYOUT_*` constant. Keep this copy in sync with the upstream skill as either evolves.
>
> **Correction applied to this copy, owed upstream (Phase 3a, task 3a.6a).** The shape
> vocabulary table gave the triangle's python-pptx member as `ISOCELES_TRIANGLE`. The real
> member is `ISOSCELES_TRIANGLE` — verified against `pptx.enum.shapes.MSO_SHAPE`, where
> `ISOCELES_TRIANGLE` does not exist. Since PHASE-3A declares this column authoritative, a
> renderer copying the cell verbatim got an `AttributeError`. Fixed here; the upstream skill
> still carries the typo.

Medium-agnostic math plus a shape vocabulary mapping. Work in the target canvas's units; for PowerPoint via pptxgenjs remember the default `LAYOUT_16x9` canvas is 10" × 5.625" (set the layout before adding anything), and for wide decks `LAYOUT_WIDE` is 13.3" × 7.5". Reserve the top band for the slide's talking header; geometry lives in the content region below it.

## Shared math

**Radial placement.** For n items around center (cx, cy) at radius r, item i sits at angle θᵢ = start − i·(360/n), with θ measured counter-clockwise from 3 o'clock:
x = cx + r·cos(θᵢ·π/180), y = cy − r·sin(θᵢ·π/180).
Use start = 90° so the first item is at 12 o'clock. For a point-up equilateral triangle, n = 3 gives vertices at 90°, 210°, 330°.

**Label anchoring around a circle or polygon.** Place each label on the ray from the center through its node, at radius r + node_radius + gap. Horizontal alignment by angle: labels with θ near 90°/270° are center-aligned (above/below the node); labels on the left half are right-aligned; labels on the right half are left-aligned. This one rule prevents nearly all label collisions.

**Curved edge arrows on a polygon.** For an arrow along the edge between vertices A and B, use an arc whose chord is slightly inside the edge: midpoint M of AB, pulled toward the center by ~12% of the circumradius; draw the arc through A′–M–B′ where A′/B′ sit 15–20% of the edge length in from each vertex (so arrows do not collide with nodes). In shape terms this is an "arc" preset sized to the bounding box of those points, with an arrowhead on the leading end, rotated per edge — or three copies of one arc rotated 120° for the triangle case.

**Honest proportions.** When widths/heights encode quantities, scale linearly: elementᵢ = min_size + (valueᵢ/max_value)·(max_size − min_size). If values are unavailable or the claim is only qualitative, make all elements equal.

## Shape vocabulary mapping

| Concept | pptxgenjs preset | python-pptx MSO_SHAPE | SVG |
|---|---|---|---|
| Node / element | `ellipse`, `roundRect` | OVAL, ROUNDED_RECTANGLE | circle, rect rx |
| Triangle | `triangle` | ISOSCELES_TRIANGLE | path (3 pts) |
| Flow arrow | `line` with `endArrowType` | connector + arrowhead | path + marker-end |
| Curved arrow | `arc` with arrow | ARC + arrowhead line format | path (A command) + marker |
| Chevron step | `chevron` | CHEVRON | path |
| Ring segment | `blockArc` / `pie` | BLOCK_ARC, PIE | path (two arcs) |
| Funnel stage | `trapezoid` (flip as needed) | TRAPEZOID | path (4 pts) |
| Diagonal half-canvas | `rtTriangle` sized to full slide | RIGHT_TRIANGLE | path |
| Beam / axis | thin `rect` or `line` | RECTANGLE / connector | rect / line |
| Custom outline | `custGeom` with `points` | freeform builder | path |

Rasterized icons or diagram images are never a substitute for these; every element must remain individually selectable and recolorable in the final file.

## Recipes

**Triangle with edge arrows (three reinforcing points).** Circumradius r ≈ 30% of content-region height, centered slightly left if labels are long. Vertices via radial placement (90°, 210°, 330°); nodes as 0.5–0.7" circles, theme accent fill, white 2–4 word label inside or the label outside per the anchoring rule with the node kept small. Three edge arcs per the curved-arrow recipe, same rotational direction, stroke ~2pt, arrowheads modest. Optional center caption: the system's name, muted color. Common fault: arrows drawn vertex-to-vertex through the nodes — inset the endpoints.

**Three- to six-node cycle.** Radial placement on an invisible circle; connect consecutive nodes with arcs head-to-tail (arrowheads all clockwise or all counter-clockwise, never mixed). For ring-segment styling instead, draw n `blockArc` segments each spanning (360/n − gap)° with gap ≈ 6–10°, rotating each into position; put the arrowhead as a small triangle at each segment's leading end.

**Chevron / path sequence.** Equal-width chevrons with slight negative spacing so points nest; first or final chevron carries the accent depending on whether the argument emphasizes the start or the destination. For a journey path instead, draw one smooth curve (SVG cubic; in pptx, a `custGeom` polyline with gentle bends or a series of arcs), place milestone nodes at equal arc-length intervals, alternate labels above/below.

**Funnel.** Stacked trapezoids: stage i has top width wᵢ and bottom width wᵢ₊₁ (the next stage's top), heights equal, 2–4pt vertical gaps. Compute widths from real quantities when available (honest proportions), else taper uniformly ~12–15% per stage. Labels inside each band, left-padded; metrics right of the funnel aligned per band.

**True 2×2.** Two thin lines with arrowheads at all four ends, crossing at the content region's center; pole labels at each arrowhead (small, muted). Items as labeled dots plotted at their positions. Optional quadrant tints at 6–10% opacity with a small corner caption per quadrant. Never box the quadrants with visible strokes — the axes are the geometry.

**Balance beam.** Fulcrum: small triangle at bottom-center. Beam: thin rectangle across it, rotated 0–6° (rotation states a verdict — use 0° for a genuinely open tradeoff). Weights: two rounded rectangles or circles hung at the beam ends (short vertical lines as strings keep it schematic rather than cartoonish). Labels inside the weights; the traded quantity captioned beneath the fulcrum.

**Diagonal split canvas.** One right triangle sized to the full content region covers one half; its fill tints or inverts that side. Content on each side stays inside a safe area inset from the diagonal by at least one text-line height. Put the visually heavier content on the lower-left; the accent on the side the argument favors.

**Radial hub / orbit / compass.** Center shape ~1.4–1.8× satellite size, satellites via radial placement, connectors as plain 1–1.5pt lines center-edge to satellite-edge (never center-to-center — lines must not pierce shapes). For orbit, additionally draw the circle itself at radius r, 1pt, muted, behind the satellites. Labels per the anchoring rule.

**Iceberg.** Waterline: full-width line or subtle band at ~35% from the top of the content region. Above: one compact shape (the visible part). Below: one larger mass (roughly 2–3× the visual weight, or honest to the data). Simple angular `custGeom` outlines read better than literal iceberg art. Labels: right of each mass with leader lines if the shapes carry no room.

**Pyramid / strata.** Horizontal bands from a common centerline, widths stepping down toward the apex (honest proportions if quantified). Flat fills stepping through tints of one hue, darkest at the base. Labels inside bands; if a band is too thin for text, label outside-right with a leader line.

**Venn.** Two or three circles, radius ~28% of content height, centers offset so overlaps are generous (~35% of radius); fills at 25–40% transparency in distinct theme tints so intersections visibly mix; 1pt strokes. Set labels in the exclusive regions and — most importantly — in the shared region, which is the slide's point.

**Gap and bridge.** Two platform rectangles at the same height with a 15–20% gap; the gap may drop to a lower band (the risk). Bridge: a rectangle or shallow arc spanning the gap, accent color, carrying the enabling capability's label. Current-state platform muted; target-state platform slightly emphasized.

## Rendering hygiene

- Align to a simple grid: content-region margins ≥ 5% of slide width; geometry centered in the region unless labels force asymmetry — then center the *visual mass*, not the bounding box.
- Strokes consistent across the slide (pick one weight for structure, one lighter for leaders); arrowheads small and uniform.
- Minimum label size ~12–14pt equivalents; if the geometry forces smaller, the slide is overloaded — remove points or split.
- Z-order: background tints, then structure (lines, arcs), then nodes, then text.
- Verify by rendering to an image and looking: label collisions, arrows piercing nodes, and off-center masses are geometry bugs, not styling taste.
