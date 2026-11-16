# Studio guide: building a deck in conversation (v3)

How to use the v3 studio, in plain steps. This is the counterpart of `docs/OWNER-GUIDE.md`,
which is the guide to v2's strict, gated pipeline. The studio has no gates and no approvals;
it is a chat beside a live deck, and every change can be undone.

**How these steps were checked (2026-11-16).** I started the scripted server and drove each
step over its HTTP API with `tests/studio/fixtures/scripts/design_flow.json`, and read
`autodeck/studio/static/app.js` and the front-end contract in `docs/phases/V3-PHASE-1.md` and
`V3-PHASE-2-3.md` for what the screens show. I did **not** look at the screens in a browser for
this guide, so button wording comes from the code, not from sight. I did not run a real model for this guide; the costs and behaviour
quoted for real models (sections 4 and 8) come from the 2026-11-15 real run as recorded in
`docs/phases/V3-PHASE-2-3.md`.

---

## 1. Start the studio

Setup, once: `./scripts/setup-dev-env.sh` and `uv sync` (LibreOffice and the Carlito font draw
the previews; without them everything works but slides show a placeholder, or start with
`--no-render`).

**Without a key (scripted, free).** A stand-in plays every model, so you can try the whole flow:

```bash
uv run python -m autodeck.studio \
    --script tests/studio/fixtures/scripts/design_flow.json \
    --workspace /tmp/studio-walkthrough
```

It prints `AutoDeck studio: http://127.0.0.1:8765/`. Open that address. The top bar shows a
small "Scripted" tag. Use a **fresh, empty** `--workspace` each time: the script's replies are
consumed in order across all threads, so a second walkthrough in a used workspace goes out of
step. Stop the server with Ctrl-C. Add `--port N` if 8765 is taken.

**With a real model.**

```bash
export OPENAI_API_KEY=...        # or put it in .env, which is gitignored
uv run python -m autodeck.studio --env dev-openai --workspace /tmp/studio-live
```

`dev-openai` is the environment that has been run live. A missing key is reported in one line
and the server does not start. Anything shown as a cost is an **estimate from assumed prices**,
not a charge.

## 2. Create an engagement

An engagement is one client and one project. It is the container for everything you make.

1. On the first screen ("Your engagements") use the form "New engagement". Pick a client and a
   project from the lists, optionally give it a title, and press "Create engagement".
2. If that pair already has an engagement, the studio opens it instead.

The lists come from the `knowledge/` folders. A fresh checkout has the clients
`northwind-retail` and `contoso-health` (fictional) and the project `llm-inference-efficiency`.
To use your own, add folders as v2 does (`knowledge/README.md`): a client needs `client.md`
and `value_prop.md`; a project needs `project.md` and `claims.md`. The studio reads the
knowledge as context and as sources; papers that have been ingested (`autodeck knowledge
ingest <project>`) can also be read and searched.

The engagement home shows three columns: **Sources**, **Artifacts** and **Threads**.

## 3. Build a deck in conversation

1. On the engagement home press **New thread**. The first time, nothing happens until you speak.
2. Write what you want in the message box at the bottom of the chat (Enter sends, Shift+Enter
   adds a line): for example "A five-slide readout for the northwind-retail team on why
   quantisation is the first thing to try, using the sources." The model asks only what would change
   the deck, at most three questions at once, each with a suggested answer; answer in the chat.
3. The lead model writes the argument (a brief and a storyline) and, for each slide, a short
   *brief in words*: what it must prove and what goes on it. Then the designer designs each
   slide in its own call. While this runs the chat shows "Working" and a live line per step,
   including "Designed slide s2 (2 attempts)". Only one turn runs at a time per engagement; the
   message box is disabled until it ends.
4. The deck appears in the panel beside the chat, in four tabs: **Slides** (a strip of
   thumbnails and one large preview), **Storyline** (the brief, the points, the design
   concept), **Changes** and **Design**. Previews take a few seconds to draw.

Every assistant message is labelled by what it did: **Talk** (a reply, nothing changed),
**Proposal** (options for you to pick; nothing changed yet) or **Change** (the deck changed;
the message says what, in words). Tool calls are in a collapsible list under it.

Slides built with no design chosen yet are drawn in a **provisional default design**.

## 4. Ask for design directions

Say the deck looks generic, or ask for other looks ("show me two different directions").

1. The lead states two directions in words (three if you ask for three). A system layer turns
   each into a palette that code checks for contrast, and the designer draws two sample slides
   in each (the opening and the slide with the most to show), at the same time.
2. The reply is a **Proposal** with one card per direction: its name, concept, a row of
   palette swatches, its rules, and the sample slides (placeholders until drawn).
3. A card line may say a sample could not be designed. A direction with no clean sample is
   dropped and the lead says so; one with some failed samples is shown as incomplete.

This is the most expensive action in the studio (about $3.63 estimated in the real run, before
the default was cut from three directions to two; not re-measured).

## 5. Pick one

On the card you like press **Use this**. The studio records the choice, tells the lead, and
the lead adopts the design. Press **Dismiss** instead to turn the options down; that is
remembered, and the next thread's recap will say what was dismissed.

After you pick, the **Design** tab shows the chosen design's name and version with a
"Decided" tag, its concept, rules, palette swatches and the text pairs it allows.

## 6. Recompose stale slides

Adopting a design (or changing a slide's brief) means the slides built from the old one are out
of date. They are **computed** to be stale, not marked by hand:

- Each affected thumbnail shows a "Stale" tag and is drawn desaturated, with the reason as a
  tooltip ("design system changed", "brief changed").
- A **Recompose N stale slides** button appears above the strip. Press it (or just say "yes,
  recompose them"): the lead calls the designer again for those slides, each in the new design.
- A slide that could not be designed shows "Failed to compose" with the first finding, and
  keeps its previous design. The lead must tell you when that happens.
- A slide never designed shows "Not designed yet".

Nothing rebuilds by itself. If you undo the change that made slides stale, they are fresh again.

## 7. Small edits, undo and redo

**Small edits.** Say exactly what you want: "Retitle slide 2 to Quantisation cuts the bill by
38%", "swap slides 1 and 3", "move slide 3 to 1", "mark slide 2 decided". Messages in these
fixed shapes go straight to a cheap **mechanic** model without the lead. Looser wording ("put
the pilot slide before the cost one") is first judged by a small router model; anything
long, multi-line, a question, or unclear goes to the lead. The mechanic can hand a message
back to the lead if it cannot do it. If you always want the lead, switch the control next to
the send button from **Auto** to **Lead**; it is remembered per thread.

**Undo and redo.** Open the **Changes** tab: every change in the deck's history, newest
first, with a sentence saying what it was ("Retitled slide 2: ..."), its layer and model, the
thread and the time. Press **Undo** on the newest live entry; an undone entry stays in the list
struck through, and **Redo** appears on it. Undo restores the earlier deck exactly, byte for
byte. You can also ask the lead to undo in the chat; the mechanic cannot ("undo that" goes to
the lead). Things to know:

- Undo goes back along the history one entry at a time. You cannot undo one change from the
  middle and keep the later ones. That is not built.
- Each slide's design is its own entry, so recomposing three slides can be undone one slide at a
  time, from the newest.
- A change made in another thread can be undone from any thread.

**New threads and the recap.** Threads are disposable. Start a new one from the engagement
home at any time; if the engagement already has a deck or a proposal, the new thread opens with
a short **recap** the model writes from the deck's state, its change history (including what
you undid or dismissed) and memory, not from the old chat. The old thread's replies are not
carried over; only the changes it made, and the words of the messages that caused them, are.

## 8. Read the routing and cost line

Under each assistant message is one quiet line, for example `Mechanic · gpt-5.4-mini · 2
calls · $0.003 est.` or `Router → Lead · 3 layers · 41.2k tokens · $0.86 est.`. A handoff reads
`Mechanic → Lead`. Click it to expand a table: one row per layer that ran (role, layer, model,
calls, tokens in and out, cost or "unpriced"), why the route was chosen (rule, router model,
your override), and a note that prices are assumed.

- "est." is always shown. The figures come from assumed, deliberately high prices that were
  never confirmed (`config/studio_prices.yaml`). They are not bills.
- "cost unknown" means a model on that turn is missing from the price file.
- In the 2026-11-15 real run, the first build of a four-slide deck cost about $3.24 estimated,
  a design proposal about $3.63, adopting and recomposing about $1.43, and a rule-routed
  retitle about $0.02. The lead resends about 14k tokens on every call, so even a one-line
  question to the lead cost about $0.17 estimated.

The **Changes** tab also names the layer and model that made each change.

## 9. What does not exist yet

- **Export.** There is no PPTX download and no export confirmation in the studio. Previews are
  PNG images. The renderer can write a PPTX (Phase 0 does it), but nothing in the interface
  offers it. (`scripts/studio_demo.py` shows the Phase 0 path.)
- **Strict mode and traceability.** A deck made here has no citations and nothing checks its
  figures. For a traceable deck use v2 (`docs/OWNER-GUIDE.md`). A fact-check tool is planned.
- **A propose-first setting.** Editing is automatic; the model decides whether to talk, propose
  or change. Undo is your safety.
- **Selecting a slide or element to scope a message.** You name slides in words ("slide 2").
- **Several threads editing at once.** One turn runs at a time; a second gets "a turn is running".
- **Meeting notes, recordings and transcripts** in the studio. v2 has them.
- **A reviewer.** Layout is checked in code on every slide, but no second model reads the
  render. Check the slides yourself; flaws such as a label floating away from its figure are
  not caught by anything.
- **Richer drawing:** styled charts, curved or diagonal lines, bold or coloured words inside a
  sentence, more fonts, images.
- **Taste memory:** what you choose and reject is not yet written to your memory.
- **Deleting or renaming** threads, engagements or artifacts.
- **Running on an Anthropic model.** The `sit` and `prod` bindings have never been tried live.

## 10. If something goes wrong

| What you see | What to do |
|---|---|
| "Could not reach the studio server." | The server stopped; start it again. State is on disk in the workspace. |
| "A turn is running." | Wait for the running turn; undo and redo also wait. |
| Slides show "Preview not available" or "Preview not rendered" | LibreOffice or the font is missing, or `--no-render` was used. Run `scripts/setup-dev-env.sh`. A failed render is not retried until the deck changes. |
| Replies make no sense after you reused a workspace with the scripted model | The script is out of step. Stop and start with a fresh empty `--workspace`. |
| "That belongs to another client's engagement." | The isolation guard refused something that reached another client's data. Nothing was shown. |
| A turn ends with an error line | Read what it says. The Changes tab shows whether anything was changed before the error; ask again in a new message. |
| You do not trust a figure | Check it against the source yourself. The studio does not. |
