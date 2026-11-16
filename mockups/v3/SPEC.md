# AutoDeck v3 mock-up — build spec

A clickable, scripted mock-up of the v3 conversation (see `docs/AUTODECK_V3_PLAN.md`, §4–§10
and "First step"). No model calls, no real rendering, no backend. It exists so the owner can
click through the planned product and say what is wrong. It is throwaway.

All content is fictional. The page says so once, quietly, in the top bar ("Scripted mock-up,
fictional data").

## 1. Files and ownership

Everything lives in `mockups/v3/`.

| File | Owner | What |
|---|---|---|
| `src/slides.js` | slides agent | Deck content, the four design directions, slide rendering. Contract in §3. |
| `src/body.html` | app agent | Page markup (no `<html>`, `<head>`, `<body>`, doctype). |
| `src/app.css` | app agent | App styles. |
| `src/app.js` | app agent | State, script, interactions. |
| `src/slides.stub.js` | app agent | A minimal stand-in for `slides.js` used only for the app agent's own testing. |
| `build.py` | app agent | Concatenates into `index.html` (§2). |

Do not edit files you do not own. Do not commit or push. Do not create other documents.

## 2. Output page format (hosting constraints — these are hard rules)

`build.py` writes `mockups/v3/index.html` as a **fragment**: no doctype, `<html>`, `<head>`
or `<body>` tags. In order:

1. `<title>AutoDeck v3 Mock-up</title>`
2. `<meta name="claude:viewport-fit-sides" content="cover">`
3. one `<link rel="stylesheet">` per URL in the `FONT_LINKS` list that `build.py` reads from
   the first lines of `src/slides.js` (see §3), if any
4. `<style>` with `app.css`
5. the contents of `body.html`
6. `<script>` with `slides.js` (or the stub when run with `--stub`), then `<script>` with `app.js`

Rules for the page:

- No external resources except Google Fonts stylesheets (`https://fonts.googleapis.com`).
  No CDN libraries: plain HTML, CSS and JS only. No images from URLs; draw with CSS/SVG.
- Never use `alert`, `confirm` or `prompt`; build dialogs in the page. No `<a download>`.
- Toggle visibility with the `hidden` attribute.
- `html, body { height: 100% }`; do not use `100vh`. Keep any existing `:root` padding.
- The outer wrapper has `padding-left: max(16px, env(safe-area-inset-left, 0px))` and the
  same for the right. The page body never scrolls horizontally, at any width down to 380px.
- Theme: every app colour is a CSS custom property defined on bare `:root` (light values),
  redefined under `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {…; color-scheme: dark} }`
  and again under `:root[data-theme="dark"] {…; color-scheme: dark}`. `body` sets an
  explicit background from a token. No component rule uses a literal colour.
  (Slides are the exception: a slide is a document with its own fixed palette.)
- Visible keyboard focus states; respect `prefers-reduced-motion`.
- Wrap any `localStorage` use in try/catch; the page must work without it.

## 3. Slide contract (`src/slides.js`)

The first lines of the file are a comment block that `build.py` parses:

```js
/* FONT_LINKS
https://fonts.googleapis.com/css2?family=...&display=swap
*/
```

(one URL per line; the block may be empty). The file then defines one global:

```js
window.MockSlides = {
  css,                 // string: all slide CSS, every selector scoped under .ms-slide
  directions,          // array, see below
  slideIds,            // ['s1', ... 's8']
  headers(state),      // -> [{ id, n, header, intent }] for the current state
  render(slideId, directionId, state),   // -> HTML string for one slide
  renderSample(directionId),             // -> [html, html, html]: title + two content slides
};
```

- `state` is `{ lead: 'cost' | 'latency', s4Hero: boolean, s6Short: boolean }`.
- `render` returns one element: `<div class="ms-slide ms-dir-<directionId>" ...>` with
  `aspect-ratio: 16 / 9; width: 100%; container-type: inline-size; overflow: hidden`.
  **All sizes inside use `cqw` units** so the same markup is correct as a 120px thumbnail
  and as an 900px main view. No fixed pixel sizes inside a slide. No scripts inside.
- The app injects `css` once into a `<style>` element.
- `directions` has four entries, in this order:

```js
{ id: 'default', name: 'Default', provisional: true,
  concept: '…', palette: [{ name, hex, role }], type: { display, body }, rules: ['…'] }
{ id: 'a', … }, { id: 'b', … }, { id: 'c', … }   // provisional: false
```

  `concept` is one or two sentences naming the visual idea. `rules` are three to five short
  statements of what the system does and never does.

### The deck

"Serving the assistant for less" — a proposal to Northwind Retail (a fictional retailer) on
cutting the cost of running its shopping assistant. Eight slides. Headers are talking
headers (full sentences that state the slide's point).

| id | Header when `lead: 'cost'` | Header when `lead: 'latency'` | Content |
|---|---|---|---|
| s1 | Northwind can serve its shopping assistant at 38% lower cost | Northwind's shopping assistant can answer in under a second | Title slide. Client name, date "November 2026". |
| s2 | Inference, not training, is now most of the bill | Shoppers leave when an answer takes more than two seconds | One simple chart or comparison. |
| s3 | Three techniques account for most of the saving | Three techniques cut response time and cost together | Quantisation, context caching, request batching: three items. |
| s4 | Quantisation alone cuts serving cost by 38% | (same) | A bar comparison (before/after). When `s4Hero` is true: the number "38%" is the hero of the slide and the comparison becomes a quiet footnote. |
| s5 | Caching repeated context removes a fifth of the compute | (same) | Deliberately the densest slide: a small diagram plus four short points. |
| s6 | A phased rollout over two quarters keeps risk low while the savings build | (same) | Three phases on a timeline. When `s6Short` is true the header is "Two quarters, three phases". |
| s7 | What it costs and what it returns | What faster answers are worth | Two or three figures side by side. |
| s8 | Decision needed: approve the pilot by 30 November | (same) | Closing slide: the ask, and next steps. |

`lead` changes the header and the content emphasis of s1, s2, s3 and s7 only.

### The four directions

- **`default`** is what a system produces when nobody decided the design: competent and
  instantly recognisable as a template (title top-left, bullets, a blue accent bar). It must
  look plausible, not broken. It is the "before".
- **`a`, `b`, `c`** are three genuinely different design directions for this deck, each
  derived from the subject (the economics of running a model for a retailer) and each one a
  deck a designer would be proud of. They must differ in idea, not only in colour: different
  composition, type, and use of space. None may look like a stock template. Each must hold
  across all eight slides.

## 4. The app

### 4.1 Look

The owner's stated taste for this product's UI: light, clean, calm, close to a native macOS
settings window; frosted panels used sparingly; system fonts; **one blue accent**. Follow it.

- UI font: `-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif`. Mono for
  small technical labels: `ui-monospace, "SF Mono", Menlo, monospace`.
- Neutrals are cool greys with a slight blue bias, not pure grey.
- The deck is the lit object on the page; chrome stays quiet. Slides sit on a slightly
  darker stage with a soft shadow.
- Markers: `decided` shows nothing (the quiet state). `provisional` is a dashed outline with
  a small amber "Provisional" tag. `stale` desaturates the slide slightly and shows a small
  orange-red "Stale" tag. Never rely on colour alone: the tag text is always present.
- Tiers are shown as one hue in four strengths (Lead strongest, Low lightest), not four
  different colours.
- No emoji anywhere. No gradient heroes. Icons, if any, are simple inline SVG.

### 4.2 Screens

**Top bar:** product name "AutoDeck"; engagement switcher showing "Northwind Retail ·
Inference efficiency" (a second, disabled entry "Contoso Health · locked to its own
engagement" illustrates client isolation); the "Scripted mock-up, fictional data" note; a
"Restart" button that resets all state.

**Engagement home** (`#home`, the start view): three columns that stack on narrow screens.

- Sources: five papers (make up plausible titles about quantisation, caching, batching),
  "Scoping call, 14 July (transcript, 42 min)", "Northwind 2025 vendor deck (uploaded)",
  "What you have said in threads".
- Artifacts: "Serving the assistant for less" (deck, 8 slides, design provisional);
  "Scoping call notes" (notes); "Board evidence pack" (deck, tagged Strict).
- Threads: "Storyline and first draft" (yesterday, closed; opens read-only with four or five
  canned messages); "Design and refinement" (today; the main scripted thread); "Scoping
  call notes" (opens the notes view).

**Thread view** (`#thread`): two panes. Left: the conversation. Right: the artifact panel.
Below about 900px the panes become two tabs, "Chat" and "Deck".

Artifact panel tabs:

- **Slides** — a strip of eight thumbnails with markers, and the selected slide large.
  Clicking a thumbnail selects it; clicking the large slide's header area or body selects an
  element ("Header of slide 4", "Body of slide 4"). The current selection appears as a chip
  above the composer ("About: slide 4 · header") with a clear button. No selection means the
  message is about the whole deck.
- **Storyline** — the eight headers in order from `MockSlides.headers(state)`, each with its
  intent and marker.
- **Design** — the current direction: name, concept, palette swatches, type, rules, and
  whether it is provisional or decided.
- **Changes** — the change log, newest first. Each entry: what changed in a sentence, the
  instruction that caused it, thread name, the layer and tier that made it, and an Undo
  button. Undo is enabled on the most recent change that has not been undone (others show
  the tooltip "Undo later changes first"). Undone entries stay, struck through, with a Redo.

Composer: a text field, suggested-message chips (the script), an editing-mode switch
(**Auto** / **Propose first**), and a routing control (**Auto**, or pin to Lead / Senior /
Mid / Low). Typing free text and sending gets the reply: "This is a scripted mock-up. Pick
one of the suggested messages to continue."

Every assistant message carries a small routing line under it, expandable into a trace:
which layers ran, on which tier, how long, and a relative cost bar. Tiers are named Lead,
Senior, Mid, Low. Use these exact layer names: Direction, System, Composition, Placement,
Mechanics, Review.

Every assistant message is one of three kinds, labelled: **Talk** (nothing changed),
**Proposal** (options or a preview; nothing changed yet), **Change** (the deck was edited;
lists what changed and links to the Changes tab).

**Notes view** (`#notes`): the notes artifact with seven fixed sections (Summary, Attendees,
Themes, Decisions, Key dates, Action items, Open questions and risks). Fill with plausible
items from a scoping call. Each item shows a transcript time like "12:40" that, when
clicked, reveals the quoted transcript line beneath it. One action item has "Owner TBD". A
small chat beside it has one chip, "Turn this into a readout deck", which answers with a
Change message and adds "Scoping call readout" (deck, 5 slides, provisional) to the
engagement home's artifact list.

**Strict view** (`#strict`): the "Board evidence pack" artifact. Shows what is different in
strict mode, mostly static:

- a "Strict" badge and a four-step approvals bar (Brief approved, Outline approved, Claims
  pending, Final render locked);
- one slide (render `s4` in direction `a` or the current one) beside a claims table: three
  claims, each with a verdict (Supported, Supported, Partially supported) and a "Show
  source" control that reveals the document name, page and verbatim quote;
- the editing-mode switch locked to Propose first, with a note explaining why;
- the Export button disabled with the reason "Two approvals outstanding".

### 4.3 State

```js
state = {
  direction: 'default',          // which design direction the deck uses
  designDecided: false,
  lead: 'cost',
  s4Hero: false, s6Short: false,
  stale: [],                     // slide ids
  checked: false,                // fact-check has run
  log: [],                       // change entries
  step: 0,                       // position in the script
  mode: 'auto',                  // or 'propose'
  route: 'auto',                 // or 'lead' | 'senior' | 'mid' | 'low'
  selection: null,               // { slide: 's4', part: 'slide'|'header'|'body' }
}
```

A slide's marker: `stale` if its id is in `state.stale`; otherwise `provisional` while
`designDecided` is false; otherwise `decided`.

A change entry stores the patch it applied and the previous values, so Undo restores them
and Redo reapplies them. Slides are always re-rendered from state.

### 4.4 The script ("Design and refinement" thread)

The thread opens with a recap message already present (kind: Talk), built as if from state:

> Picking up from yesterday. The deck has 8 slides and the argument is settled: it leads
> with cost. The design is still the provisional default, since nothing was decided.
> Rejected so far: a dark theme, and an ROI calculator slide. Open: whether slide 5 is too
> dense, and the pilot date on slide 8.

Its routing line: "Built from the deck's state and change log. No earlier chat was read."

Then the steps. Each step is offered as a chip; chips for later steps appear as earlier ones
are done, but order is not enforced beyond what a step needs (steps 3–8 need step 2 done).
Where a step needs a selection and there is none, the chip selects it first.

1. **"The deck looks generic. Give it a real design."** → Proposal. Short text: the default
   was never a decision; here are three directions drawn from the content. Shows three cards,
   one per direction `a`, `b`, `c`: name, concept, and the three sample slides from
   `renderSample`. Each card has "Use this direction". Trace: Direction · Lead (wrote three
   concepts); System · Senior (three systems, in parallel); Composition · Mid (nine sample
   slides, in parallel); Placement · Low; Review · Senior (read the renders cold).
2. **Choosing a direction** (the button on a card) → Change. Sets `direction`,
   `designDecided: true`. Text: the system is now decided, all eight slides were recomposed
   in it, and the choice was noted in your preferences for later decks. Trace: System ·
   Senior; Composition · Mid (8 slides in parallel); Placement · Low. The Lead is listed as
   "not needed".
3. **"Make the number the hero"** (selection: slide 4) → Change. Sets `s4Hero: true`. Trace:
   Composition · Mid; Placement · Low. Lead "not needed".
4. **"Shorten this title"** (selection: slide 6 · header) → Change. Sets `s6Short: true`.
   Trace: Mechanics · Low only, with the line "Routed straight to the lowest tier. The lead
   was not invoked."
5. **"Is slide 5 too dense?"** (selection: slide 5) → Talk. An opinion: it carries a diagram
   and four points; suggests cutting to the diagram and two points, and asks whether to do
   it. Nothing changes. Two follow-up chips: "Yes, cut it down" (Talk reply in the mock-up:
   "In the product this would recompose slide 5. Not scripted here.") and "Leave it".
6. **"Lead with latency, not cost"** → Change to the argument. Sets `lead: 'latency'`, and
   `stale: ['s1','s2','s3','s7']`. Text: the storyline was updated; four slides were built
   on the old argument and are now marked stale; nothing was rebuilt. A button in the
   message, "Rebuild the 4 stale slides", clears `stale` (a second Change entry). Trace for
   the first: Direction · Lead. For the rebuild: Composition · Mid (4 in parallel);
   Placement · Low; Review · Senior.
   While stale, a stale slide renders with the **old** lead (`lead: 'cost'`) content, and
   the Storyline tab shows the new header beside the tag.
7. **"Check the numbers against my sources"** → Talk with a result card. Sets `checked`.
   Five figures checked; four found, each with a source note (document and page); one not
   found: "38% (slides 1 and 4): the quantisation paper reports a range of 35 to 41%. The
   exact figure does not appear." Text ends: "Nothing is blocked. Tell me if you want the
   range instead." Trace: Mechanics · Low (extracted figures); Review · Senior.
8. **Export** (a button in the artifact panel header, always visible) → opens a dialog: one
   confirmation. It lists anything provisional or stale and, if the check has run, the
   unverified figure; if the check has not run it says "Figures have not been checked
   against your sources" with a "Check now" link that runs step 7. "Export .pptx" closes the
   dialog and shows a toast "Exported (mock-up: no file is written)".

**Propose first mode:** every step that would be a Change instead produces a Proposal with a
before/after preview of the affected slide(s) and two buttons, "Apply" and "Dismiss". Apply
makes the change and adds the Change message.

**Routing override:** when `route` is not `auto`, the trace of the next message shows every
layer run on the pinned tier, with the line "Pinned by you" and a visibly larger cost bar
when the pin is Lead.

### 4.5 Behaviour details

- Hash routing with plain names only: `#home`, `#thread`, `#notes`, `#strict`,
  `#history` (the read-only earlier thread). Show `#home` when the hash is empty.
- When a Change happens, briefly highlight the affected thumbnails.
- The conversation scrolls to the newest message; the artifact panel does not jump.
- Restart resets everything and returns to `#home`.
- The page must be complete at rest: on first load the home view is fully populated.

## 5. Checks before you report done

- No console errors on load or during the full script, in both modes (Auto, Propose first).
- No horizontal page scroll at 1280px, 900px and 390px widths.
- Light and dark themes both legible.
- Undo then Redo of each change restores the slides exactly.
