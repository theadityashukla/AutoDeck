---
name: slide-geometry
description: Design slides whose geometry encodes the relationship between points — triangles with reinforcing arrows, cycles, funnels, split canvases, balance beams, radial hubs — instead of the default rows of rounded rectangles that make decks look AI-generated. Use this skill whenever creating or designing slides, decks, or presentations; whenever a slide carries 2–6 parallel points; and especially when the user asks for slides that are more visual, more creative, less boxy, or "not typical AI slides." Also use it when critiquing or redesigning existing slides that look templated.
---

# Slide Geometry — layouts that encode meaning

AI-generated slides have a signature failure: every set of N points becomes N rounded rectangles in a row or a grid, regardless of what the points *are*. Boxes say nothing about how ideas relate — and the relationship is usually the most important thing on the slide. This skill replaces the box default with one discipline:

**The geometry of the slide must encode the relationship between its points.**

Three mutually reinforcing pillars are a triangle with arrows along its edges. Three sequential steps are a path. Three options in tension are neither — and pretending otherwise misleads the audience. The shape is not decoration; it is a claim about how the ideas connect.

## Workflow — run this for every slide with 2+ parallel points

1. **Classify the relationship first, before any layout.** Use the table below. This is the load-bearing step; everything else follows from it. If you catch yourself placing boxes before you have named the relationship, stop and classify.
2. **Choose a geometry that encodes that relationship.** Read `references/geometry-catalog.md` and pick from the family the classification points to. Prefer the simplest geometry that carries the meaning.
3. **Apply the load-bearing test.** Ask: *if this geometry were replaced by a plain list, would information be lost?* If nothing would be lost, the geometry is decoration — choose a better one, or accept that this content is genuinely a list. An elegant list is always better than fake geometry.
4. **Construct natively.** Read `references/construction.md` for coordinate math and shape recipes. Build from real shapes, lines, and arrowheads — editable vector elements in the target medium — never a rasterized diagram image, and never SmartArt.
5. **Verify against the craft rules** below before moving to the next slide.

## Step 1 — Relationship classification

Ask the identifying question for each; the first confident "yes" names the relationship.

| Relationship | Identifying question | Geometry families (see catalog) |
|---|---|---|
| Sequence | Does order matter — does A lead to B? | path, chevron flow, staircase, numbered arc |
| Cycle | Does the last step feed the first? | ring, flywheel, orbit |
| Mutual reinforcement | Does each point strengthen the others? | triangle with edge arrows, interlocked ring |
| Tension / tradeoff | Does more of A mean less of B? | balance beam, slider, opposed arrows |
| Complement | Do the parts complete one whole? | split shape, interlocking halves, shared core |
| Convergence | Do many inputs produce one output? | funnel, tributaries, arrows to center |
| Divergence | Does one thing branch into many? | tree, starburst, delta |
| Hierarchy / foundation | Does one rest on, or outrank, another? | pyramid, strata, podium, iceberg |
| Overlap | Do they share common ground? | Venn, lens |
| Containment | Is one a subset of another? | nested shapes |
| Transformation | Is this before vs. after, current vs. target? | split canvas with crossing arrow, gap and bridge |
| None (a true list) | Honestly none of the above? | a well-set list — do NOT force geometry |

Two subtleties. First, the same three points can hold different relationships depending on the argument — three capabilities might be sequential in a delivery story and mutually reinforcing in a value story; classify against *this slide's* message. Second, at 7+ points, group into 2–4 families first, then apply geometry to the families; no geometry survives eight labels.

## Craft rules

- **One geometry per slide.** A slide is one idea; two geometries is two slides.
- **Restraint is what separates this from clip-art.** Flat fills from the deck's theme, one accent color, thin consistent strokes, generous whitespace. No 3D, bevels, glows, drop-shadow stacking, or gradient drama. The geometry should feel inevitable, not decorated.
- **Labels stay horizontal and predictable.** Every element gets a short text label at the anchor position the catalog specifies for that geometry. Never curve body text; never rotate labels beyond what a vertical axis caption requires. Geometry plus unlabeled icons is hieroglyphics — the reader should never need a legend.
- **Arrows mean flow, causality, or influence — nothing else.** An arrow that is really just a connector misstates the relationship; use a plain line.
- **Proportion is a factual claim.** If sizes or positions encode quantity (funnel widths, podium heights), make them honest to the numbers or make all elements equal. Never exaggerate for drama.
- **Text budgets still apply.** Geometry buys clarity, not room: node labels of 2–4 words, support lines under ~10. If the content cannot compress to that, the slide is overloaded — split it.
- **Respect the deck's rhythm.** Do not repeat the same geometry on consecutive slides; alternate density; a plain, well-set text slide between two geometric ones makes both stronger.

## Anti-patterns — refuse these even if they feel faster

- N rounded rectangles in a row or grid for related points ("box disease").
- The SmartArt look: chunky glossy chevrons, 3D pyramids, default-blue cycle wheels.
- Decorative geometry that fails the load-bearing test (a triangle for three unrelated points).
- A 2×2 whose axes are not real, labeled continuums — that is four boxes wearing a costume.
- Icon-only or geometry-only slides with no labels.
- Rasterized diagram images pasted where native shapes belong.

## Using this skill alongside other tools

- **In Claude.ai / Enterprise deck creation:** the pptx skill owns file mechanics and overall deck craft; this skill decides *what to draw* on slides with parallel points. Build geometries from preset shapes, rotated shapes, and lines with arrowheads per `references/construction.md`, keeping every element native and editable.
- **In HTML or SVG artifacts:** same catalog; `references/construction.md` includes SVG equivalents.
- **When critiquing or redesigning an existing deck:** run the classification on each boxy slide and propose the geometry its relationship implies, citing which relationship you detected and why.
