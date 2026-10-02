# Owner's guide to GATE 2 and GATE 3

This is the step-by-step for the person who has to approve things. You do not need to have
read the code. Every command below was checked against `--help` and the source, and every
"example output" block is what the real program printed when run against scripted stand-in
models (the same technique the test suite uses), so the screens are genuine — but the
*content* is from a test fixture and yours will differ.

---

## 1. What you are doing, and why

AutoDeck will not produce a deck until a person has approved it at four points (invariant
A7). You are the person. The four approvals are:

1. **Sign the brief** — what the deck is for, who it is for, and what it must say.
2. **Approve the outline** — the ordered list of slides, before any wording exists.
3. **Approve the claims** (this is "GATE 2") — every factual sentence, with the quote that
   is supposed to back it.
4. **Approve the final render** (this is "GATE 3") — the finished PowerPoint file, after you
   have tried it in PowerPoint yourself. Available now: section 6b.

Each later step refuses to run until the one before it is approved, and there is no flag,
option or setting that skips an approval. That is deliberate: the system is built so it can
never approve its own work.

**This guide covers all four approvals.** Approvals 1, 2 and 3 are one sitting: budget about
an hour (an estimate, not a measurement). Approval 4 comes after, and needs PowerPoint on
your computer and, as a rough estimate, another half hour for the hands-on checks. You need
this repository on your computer and two API keys, `GEMINI_API_KEY` and `GROQ_API_KEY` (see
section 2). If GATE 2 is already approved, go straight to section 6b.

The short version of the whole session:

| # | Command | Your job |
|---|---|---|
| 0 | `uv run autodeck knowledge ingest llm-inference-efficiency` | Wait. Nothing to decide. |
| 1 | `uv run autodeck plan …` | Talk to the planner, then type `/sign <your name>`. |
| 2 | `uv run autodeck outline …` | Read the slide list. Then `approve … outline`. |
| 3 | `uv run autodeck content …` then `validate …` | Nothing to decide; read any warnings. |
| 4 | `uv run autodeck gate2 …` | Read each claim against its quote. Then `approve … claims`. |
| 5a | `uv run autodeck render …` | Wait. Read what the art director and the critic did. |
| 5b | `uv run autodeck gate3 …` | Read the report and the headline list. |
| 5c | (no command: PowerPoint) | Open a copy of `deck.pptx` and do the five hands-on checks. |
| 5d | `uv run autodeck approve … final_render` | Only if all five worked and nothing failed. |

---

## 2. Before you start

**Get the right code.** Check out the branch that has every fix, and install:

```bash
git checkout v2/phase-3b-render-qa
git pull
uv sync
```

**Install the system tools.** From the repository root:

```bash
./scripts/setup-dev-env.sh
```

This installs three things a fresh machine lacks: the Inter fonts (into `fonts/` and
`~/.local/share/fonts/`), and `libreoffice-impress` and `poppler-utils` (through `apt-get`,
so it assumes Debian or Ubuntu; on another system the script stops with an error saying
`soffice` or `pdftoppm` is not on PATH, and you install those two yourself). It then proves
the render path works by building a one-slide file, converting it to PDF and turning that
into an image, and ends by printing a `Verified:` list. For *this* session the fonts are the
part that matters: the `content` step measures text against the real font, and refuses to run
without it. LibreOffice and poppler are for rendering, which step 5 (section 6b) uses. You can check the
fonts on their own:

```bash
uv run autodeck fonts check --tokens config/tokens/dev.json
```

Every line should start with `OK`. (Without `--tokens` it checks Aptos instead, which is
the eventual deliverable font and is not installable here — `MISSING Aptos` lines from
that form are expected and are not a problem for this session.)

**Set your keys.** In the dev environment, the planner, outline and validation steps use
Gemini and the content step uses Groq, so you need both:

```bash
export GEMINI_API_KEY=...
export GROQ_API_KEY=...
uv run autodeck models
```

`autodeck models` lists which model each step uses. If a key is missing it says so:

```
environment: dev
  aesthetic    gemini   gemini-3.1-flash-lite
  content      groq     openai/gpt-oss-120b
  ingest_vlm   gemini   gemini-2.5-flash
  outline      gemini   gemini-3.6-flash
  planner      gemini   gemini-3.7-flash
  validation   gemini   gemini-3.5-flash

missing credentials: GEMINI_API_KEY, GROQ_API_KEY

Note: A3 and A8 are model-sensitive (B8). A dev-environment accuracy result is a smoke test, not a verification — measure headline metrics on sit.
```

(That output is from a shell with both keys removed. With both set, the
`missing credentials` line is absent.)

**Build the document store (once).** The planner checks your key messages against the
research papers in `knowledge/projects/llm-inference-efficiency/papers/`. That needs the
papers converted into a searchable store, and `plan` refuses to start without it:

```bash
uv run autodeck knowledge ingest llm-inference-efficiency
```

It is slow the first time (it downloads a layout model) and needs no API key. It skips
papers it has already done, so if it is interrupted, run it again. The store goes in
`corpus/`, which is not committed to git. Example output (from a real run on the five seed
papers — the numbers are real for this corpus):

```
  ingested  dettmers-2022-llm-int8                                20p  242 elements  coverage 100%
  ingested  frantar-2023-gptq                                     16p  185 elements  coverage 100%
  ingested  kwon-2023-pagedattention-vllm                         16p  255 elements  coverage 100%
  ingested  leviathan-2023-speculative-decoding                   13p  179 elements  coverage 100%
  ingested  pope-2022-efficiently-scaling-transformer-inference   18p  253 elements  coverage 100%
```

If you skip this step, `plan` stops at once with exit code 2 and tells you what to run.

**Run every command from the repository root.** The folders `runs/` and `corpus/` are created
relative to where you are standing. If you run a command from a different folder it will
not find your earlier work.

A mistyped run id is an error, not a new run. Only `plan` creates a run; every other command
refuses an id it does not know and creates nothing:

```
no such run 'northwind-mielstone' under runs. Runs are created by `autodeck plan`; check the id with `ls` on the runs directory.
```

(The `runs` in that message is the folder it looked in, relative to where you are standing —
if the id is right and you still get this, you are in the wrong folder.)

**The free-tier quota.** `STATUS.md` records that the free Gemini tier allows roughly 20
requests per model per day. The steps are spread over different models so they mostly do not
share one allowance (`autodeck models` shows which), with one exception that matters: the
evidence check in `plan` and the `validate` step both use the `validation` model, so they draw
on the same 20 (and `render`'s art direction draws on the `outline` model's 20). The content step uses Groq, whose free tier is limited per minute instead
(the comment in `config/models.yaml` says 8000 tokens a minute). What costs a request:

- each planner turn (one request), plus one request per key message every time the planner
  re-checks the evidence;
- the outline step (one request);
- the content step (about one request per slide);
- the validate step (about one request per six claims);
- the render step (section 6b): one request for art direction and one to three for the
  critique, which uses the `aesthetic` model.

A reply the program cannot parse is retried, and each retry is also a request.

When the quota is spent, the program waits and retries a few times on its own (up to about a
minute per wait), then gives up. `plan`, `outline`, `content`, `validate` and `render` then stop with a
short message and **exit code 5** — not a Python error. This is what `plan` printed when the
real Gemini client was pointed at a stand-in server that always answers 429:

```
Planning q429 for northwind-retail / llm-inference-efficiency (env=dev)
Type to talk. /brief to see the draft, /sign <name> to approve, /quit to leave.

you > hello there
STOPPED: role 'planner' (gemini, model gemini-3.7-flash) was rate limited.
  The provider refused the call (HTTP 429) and waiting inside the command did not clear it.
  On a free tier this is almost always that model's daily quota: it resets daily, so running the command again sooner will not help.
  Saved: no draft had been started. Nothing is approved.
  Then run `autodeck plan q429 --client northwind-retail --project llm-inference-efficiency` again.
```

It tells you which role and model ran out, what that means, and what was saved. **The fix is
to wait for the quota to reset, then run the same command again** — not to run it again
straight away. How long that is depends on the provider: Gemini's free tier is a daily
allowance per model (wait until tomorrow), Groq's is per minute (the `content` example below
says so).

**Nothing that finished is lost.** Every reply from the model is saved to
`runs/<run>/llm_cache/` the moment it arrives, and a command that is run again replays those
replies at no cost and only asks the model for what did not finish. `plan` keeps your draft
brief as well (section 3). Here is `content` on a five-slide deck, with the quota running
out on the third request (stand-in server again):

```
  s1       1 block(s), 0 note(s)
  s2       2 block(s), 0 note(s)
STOPPED: role 'content' (groq, model openai/gpt-oss-120b) was rate limited.
  The provider refused the call (HTTP 429) and waiting inside the command did not clear it.
  Groq's free tier is limited per minute (tokens), so waiting a minute or two is usually enough.
  Saved: no IR version was written (the latest is still v1). 2 completed provider call(s) are saved under runs/northwind-quota/llm_cache; a re-run replays them at no cost and only pays for what did not finish.
  Then run `autodeck content northwind-quota` again.
```

Nothing was written (`status` shows `content   failed`, and the deck is still IR v1). Running
the same command later:

```
  s1       1 block(s), 0 note(s)
  s2       2 block(s), 0 note(s)
  s3       3 block(s), 0 note(s)
  s4       2 block(s), 0 note(s)
  s5       2 block(s), 0 note(s)

wrote IR v2
```

(The rest of that output is the usual lint report.) It asked the model for **3** slides, not
5: the two that had finished were replayed from the cache — the stand-in server counted the
requests. A third run asked for none.

`validate` stops the same way, and it is marked as failed so that `gate2` and `approve …
claims` stay closed until it has really finished (a validator that ran out of quota has judged
nothing, and a table of unjudged claims must not be approvable):

```
validation batch of 4 claim(s) failed (RateLimitError): gemini: rate limited (429) — treated as unjudged
STOPPED: role 'validation' (gemini, model gemini-3.5-flash) was rate limited.
  The provider refused the call (HTTP 429) and waiting inside the command did not clear it.
  On a free tier this is almost always that model's daily quota: it resets daily, so running the command again sooner will not help.
  Saved: the validate stage is marked failed, so `gate2` and `approve ... claims` stay closed until it completes. 5 completed provider call(s) are saved under runs/northwind-quota/llm_cache; a re-run replays them at no cost and only pays for what did not finish.
  Then run `autodeck validate northwind-quota` again.
```

```
run 'northwind-quota' has not been validated yet. Run `autodeck validate northwind-quota` first.
```

**Two consequences of the cache.** First, running a command again with nothing changed gives
you *the same result* — it is replaying the same replies — so re-running `outline` or `content`
is not a way to get a second opinion. (Changing what the model is shown does ask it again: a
claim you send back changes the writer's prompt, so the next `content` is a fresh request.)
If you really want a fresh attempt, delete the saved replies for the run and run the command
again (this costs requests):

```bash
rm -r runs/northwind-milestone/llm_cache
```

In the test run, the `outline` command made 1 request the first time, 0 when run again, and 1
again after that folder was deleted. Second, the cache is only for model replies; it is not an
approval and nothing in it is trusted — every step still checks its own results.

A missing key stops the command the same way, before any request is made:

```
STOPPED: role 'planner' (gemini, model gemini-3.7-flash) has no API key.
  The environment variable GEMINI_API_KEY is not set. Set it in this shell, then run the command again.
  Saved: no draft had been started. Nothing is approved.
  Then run `autodeck plan nokey --client northwind-retail --project llm-inference-efficiency` again.
```

A key the provider turns down (a `401`/`403` answer) reads like this:

```
Planning badkey for northwind-retail / llm-inference-efficiency (env=dev)
Type to talk. /brief to see the draft, /sign <name> to approve, /quit to leave.

you > hello
STOPPED: role 'planner' (gemini, model gemini-3.7-flash) was refused: the provider rejected the credentials.
  Check that GEMINI_API_KEY holds a valid key for gemini, then run the command again.
  Saved: no draft had been started. Nothing is approved.
  Then run `autodeck plan badkey --client northwind-retail --project llm-inference-efficiency` again.
```

---

## 3. Step 1 — the planning conversation, and how to sign

### What this step is

```bash
uv run autodeck plan northwind-milestone --client northwind-retail --project llm-inference-efficiency
```

`northwind-milestone` is the **run id** — a name you choose for this deck. Every later
command takes the same run id. `--client` and `--project` name the folders under
`knowledge/` to use.

The planner is an AI that interviews you about the deck, like a colleague who has read the
background folders. It is trying to end up with a **brief**: the objective (the decision the
deck should produce), the audience, and the **key messages** — the handful of things the
deck must land. As you agree key messages, it checks each one against the research papers
and tells you how well the evidence backs it. That check is the main point of this step: a
gap found here costs one sentence of conversation, and the same gap found at GATE 2 costs a
rewrite of every slide built on it.

### What you type

Just talk. Say what decision the deck is for, who is in the room, and how long it should
be. Good answers are specific and in the client's own words: *who* decides, *what* they are
choosing between, and *what you already know that the papers cannot tell you*. The planner
will propose a storyline; it is easier to correct a concrete proposal than to write one from
nothing, so say "no, the second point should be…" freely.

Three commands are recognised, and only these (they must start the line exactly as shown):

| Type | What it does |
|---|---|
| `/brief` | Shows the current draft of the brief. Changes nothing. |
| `/sign <your name>` | Signs the brief, ends the session. The name can be several words. |
| `/quit` (or `/exit`) | Leaves without signing. Your draft is kept. |

The session ends only when *you* type `/sign <name>`. The planner can suggest the brief looks
finished, but that suggestion is ignored by the code; it cannot sign for you. Signing with no
name is refused:

```
Planning signname for northwind-retail / llm-inference-efficiency (env=dev)
Type to talk. /brief to see the draft, /sign <name> to approve, /quit to leave.

you > hi

planner > Noted.

you > /sign
sign-off needs the name of whoever is approving. A7 records who approved each gate; an unnamed approval is not one.
you > /sign   
sign-off needs the name of whoever is approving. A7 records who approved each gate; an unnamed approval is not one.
you > /exit

left without signing; transcript kept, draft kept at runs/signname/draft_brief.json (run `autodeck plan signname --client northwind-retail --project llm-inference-efficiency` to resume it)
```

### Example session

Example output (from a test fixture with scripted stand-in models — your content will
differ). The planner's first reply, with the evidence check it triggered:

```
Planning northwind-milestone for northwind-retail / llm-inference-efficiency (env=dev)
Type to talk. /brief to see the draft, /sign <name> to approve, /quit to leave.

you > We need to decide whether to serve the model better or buy more GPUs. Audience is the CTO and two engineering leads. Five slides.

planner > Understood: the decision is serve-better versus buy-more-GPUs, for a CTO and two engineering leads. Here is a first storyline, four messages. I am checking each against the corpus now.

  evidence · km1: SUPPORTED
      kwon-2023-pagedattention-vllm states near-zero waste in KV cache memory as the design goal; the message's terms match.
  evidence · km2: THIN
      The corpus measures memory (LLM.int8() halves inference memory), not cost in currency; GPTQ says it gives no speedup on the multiplications.
  evidence · km3: SUPPORTED
      leviathan-2023-speculative-decoding says outputs are unchanged.
  evidence · km4: UNSUPPORTED
      No document in the corpus compares hosted-API pricing with self-hosting.
```

Type `/brief` at any time to see exactly what is recorded. Read it carefully before signing —
**what is in `/brief` is what you are signing**, and anything the planner merely *said* in
conversation but did not record does not exist:

```
you > /brief
objective: Decide whether to serve the current model better or buy more GPUs.
audience: CTO and two engineering leads
length_target: 5
header_style: (not set)
key_messages:
  - [km1] (supported) Serving throughput is bounded by wasted KV-cache memory, not by compute.
      probe: kwon-2023-pagedattention-vllm states near-zero waste in KV cache memory as the design goal; the message's terms match.
  - [km2] (thin) Quantisation cuts our inference cost by half.
      probe: The corpus measures memory (LLM.int8() halves inference memory), not cost in currency; GPTQ says it gives no speedup on the multiplications.
  - [km3] (supported) Speculative decoding speeds up generation without changing the model's outputs.
      probe: leviathan-2023-speculative-decoding says outputs are unchanged.
  - [km4] (unsupported) Moving to a hosted API would cost less than self-hosting at our volume.
      probe: No document in the corpus compares hosted-API pricing with self-hosting.
must_include: (none)
must_avoid: (none)
layout_pins:
  (none)
open_risks:
  (none)
```

### What the evidence labels mean

Each key message is labelled by a check the program runs itself (the AI proposes messages; it
does not get to decide whether they are supported):

| Label | Meaning |
|---|---|
| `supported` | A citable passage backs the message on the terms it states. |
| `thin` | Something related exists but it measures a different thing, holds only under a specific setup, is one source, or is someone else's reported result. The message would read as solid and then fall apart under a client's question. |
| `unsupported` | Nothing in the papers or the curated claims backs it. (If search finds nothing at all, the program says `unsupported` without even asking the AI.) |
| `unprobed` | Nobody has checked. Not a verdict on the message. |

You may see `(capped)` after a label. It means the AI said `supported` but the program
lowered it to `thin`, because the only evidence found was a single passage from the papers
(a single hand-curated claim from `claims.md` is left alone).

If you see `UNPROBED` right after the planner said it was checking, the check itself failed —
usually because the quota ran out; the program records "nobody judged this" instead of
guessing. `unprobed` messages do not block signing; the program only notes them afterwards
(`note: … were never probed against the corpus. Not a failure — but nobody looked.`).

### What signing means, and accepted risks

Signing says: **I approve this brief** — its objective, audience and key messages — as the
thing the deck will be built and judged against. The brief is saved as a numbered version
(`runs/<run>/brief/v1.yaml`, plain text you can open) and stamped with your name. Later
steps compare the outline and the claims back to it.

A message labelled `thin` or `unsupported` **cannot be signed as it stands.** You have three
honest options, and the planner will offer them: reword the message so the evidence does
back it; find a source; or **carry the gap** — keep the message and record a risk. Carrying
is allowed, but it is written down, with your name on it. The program enforces this when you
type `/sign`:

```
you > /sign Jane Owner
this brief cannot be signed off yet: 1 validation error for DeckBrief
  Value error, key message(s) km2, km4 have weak or absent evidence but no matching entry in open_risks. Carrying an unsupported message is allowed (plan §7); carrying it without recording who accepted the gap is not — it would vanish before the audit report (A8). [type=value_error, input_value={'run_id': 'northwind-mil...': [], 'open_risks': []}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/value_error

Carrying a weak message is allowed — it needs a recorded risk with someone's name on it. Ask the planner to add one (A8).
```

(The raw-looking error text is real; the useful part is the sentence after `Value error`.)

To carry a gap, tell the planner in plain words that you accept it and give your name, as in
the example below. The planner then records an "open risk": which message, what is missing,
**who accepted it**, and optionally how the deck will hedge. There is no separate command for
this — the planner writes it, so **check it with `/brief`** under `open_risks:` and make sure
the name is yours and the description is what you meant:

```
you > Yes, I accept km2 and km4 as risks. My name is Jane Owner.

planner > Recorded. km2 and km4 are carried as open risks accepted by Jane Owner, and both will appear in the audit report. Show the brief with /brief and, if it is right, sign with /sign <your name>.

you > /brief
objective: Decide whether to serve the current model better or buy more GPUs.
audience: CTO and two engineering leads
length_target: 5
header_style: (not set)
key_messages:
  - [km1] (supported) Serving throughput is bounded by wasted KV-cache memory, not by compute.
      probe: kwon-2023-pagedattention-vllm states near-zero waste in KV cache memory as the design goal; the message's terms match.
  - [km2] (thin) Quantisation cuts our inference cost by half.
      probe: The corpus measures memory (LLM.int8() halves inference memory), not cost in currency; GPTQ says it gives no speedup on the multiplications.
  - [km3] (supported) Speculative decoding speeds up generation without changing the model's outputs.
      probe: leviathan-2023-speculative-decoding says outputs are unchanged.
  - [km4] (unsupported) Moving to a hosted API would cost less than self-hosting at our volume.
      probe: No document in the corpus compares hosted-API pricing with self-hosting.
must_include: (none)
must_avoid: (none)
layout_pins:
  (none)
open_risks:
  - km2: The corpus supports memory halving, not a cost halving; wording to be hedged to memory. (accepted by Jane Owner)
  - km4: Nothing in the corpus compares hosted-API and self-hosted cost. (accepted by Jane Owner)
you > /sign Jane Owner

brief v1 signed off by Jane Owner

Next: autodeck outline northwind-milestone --client northwind-retail --project llm-inference-efficiency
```

What accepting a risk commits you to: the message stays in the deck's plan; the risk appears
by name in the GATE 2 report (section 6) and in the audit record; and you have said, in
writing, that you know the evidence is weaker than the message sounds. It does not make the
message true, and the claim writer and validator still have to back every sentence
individually.

### If you leave without signing

`/quit`, `/exit`, Ctrl-C and Ctrl-D all leave without signing (exit code 1). Nothing is
approved, and **the draft is kept**. Example output:

```
Planning quit-demo for northwind-retail / llm-inference-efficiency (env=dev)
Type to talk. /brief to see the draft, /sign <name> to approve, /quit to leave.

you > Audience is the CTO.

planner > Noted.

you > /quit

left without signing; transcript kept, draft kept at runs/quit-demo/draft_brief.json (run `autodeck plan quit-demo --client northwind-retail --project llm-inference-efficiency` to resume it)
```

`status` mentions the saved draft:

```
run quit-demo (env=dev)
stages:
  ingest         not-started
  plan           not-started
  outline        not-started
  content        not-started
  validate       not-started
  art_direction  not-started
  render         not-started
  audit          not-started
  (an unsigned draft brief is saved at runs/quit-demo/draft_brief.json; `autodeck plan` resumes it)
gates:
  brief          PENDING
  outline        PENDING
  claims         PENDING
  final_render   PENDING
```

Run the same `plan` command again, with the same run id, and it picks the draft up and says
so. `/brief` shows the draft exactly as you left it:

```
Planning quit-demo for northwind-retail / llm-inference-efficiency (env=dev)
Resumed the unsigned draft from an earlier session (1 key message(s)); /brief shows it. Nothing is approved until you /sign.
Type to talk. /brief to see the draft, /sign <name> to approve, /quit to leave.

you > /brief
objective: Decide.
audience: CTO
length_target: (not set)
header_style: (not set)
key_messages:
  - [km1] (unprobed) Serving throughput is bounded by wasted KV-cache memory, not by compute.
must_include: (none)
must_avoid: (none)
layout_pins:
  (none)
open_risks:
  (none)
you > /quit

left without signing; transcript kept, draft kept at runs/quit-demo/draft_brief.json (run `autodeck plan quit-demo --client northwind-retail --project llm-inference-efficiency` to resume it)
```

Resuming approves nothing: you still have to type `/sign <your name>`. The draft is saved
after every turn as well as on the way out, so a crash or a spent quota costs you at most the
turn that was in flight. Ctrl-C and Ctrl-D end the same way (in a test run, each printed
`left without signing; transcript kept, draft kept at runs/quit-demo/draft_brief.json …`,
exit code 1). The conversation so far is in `runs/<run>/logs/planner.jsonl`, and a resumed
session carries on from it. The draft is stored in `runs/<run>/draft_brief.json`; signing
deletes it, because the signed brief (`brief/v1.yaml`) replaces it.

Once a brief is signed, the session is over. The code's own advice for changing a signed
brief is to start a new run (a new run id) — editing a signed brief would invalidate the
approval that the next step reviews against.

The next step refuses to run on a run whose brief is unsigned:

```
GATE 'brief' requires human approval before run 'quit-demo' continues. Review the artifacts under runs/quit-demo/ and record approval with `autodeck approve quit-demo brief`. The pipeline never self-approves (A7).
```

---

## 4. Step 2 — the outline (GATE 1)

```bash
uv run autodeck outline northwind-milestone --client northwind-retail --project llm-inference-efficiency
```

The AI turns the signed brief into an **outline**: a list of slides, each with a role in the
story, a layout type, a one-line intent, and which key messages it serves. There is no slide
wording yet — the outline has nowhere to put any. Example output (test fixture):

```
wrote runs/northwind-milestone/ir/v1.json
  s1       opening        title                [-]
           Open the deck on the decision: serve better or buy more GPUs.
  s2       evidence       bullets_supporting   [km1]
           Establish that throughput is bounded by KV-cache memory waste, not compute.
  s3       evidence       bullets_supporting   [km2]
           Show what quantisation does and does not buy: memory, not (yet) cost.
  s4       evidence       bullets_supporting   [km3]
           Show that speculative decoding speeds generation without changing outputs.
  s5       recommendation callout_takeaway     [km4]
           Frame the hosted-API question as open, to be settled with the client's own volume data.

GATE 1 — outline v1 against brief v1
run: northwind-milestone · 5 slide(s)

All mechanical checks pass.

These are the checkable criteria only. The gate asks whether this outline delivers the brief's argument, and no check here answers that — read the slide intents in order and decide. Approve with `autodeck approve northwind-milestone outline`.
```

Reading a line: `s3  evidence  bullets_supporting  [km2]` is slide 3, playing an evidence
role, using the bullets layout, serving key message `km2`. The indented line under it is
what that slide must accomplish.

### What the report checks

Below the slide list is the GATE 1 report. It checks only what a machine can check: every key
message has at least one slide; `must_include` and `must_avoid` are respected; any layout pin
you asked for is honoured (or the deviation is stated); the slide count is within your target;
accepted risks carry through. Findings are either **BLOCKING** or **advisory**. A blocking
finding is a check that failed, for example:

```
GATE 1 — outline v1 against brief v1
run: northwind-milestone · 4 slide(s)

[BLOCKING] key message coverage: km3 is in the brief but no slide serves it: "Speculative decoding speeds up generation without changing the model's outputs."
[advisory] length: 4 slides against a target of 5 — under target. Check the outline's notes for what was left out.

These are the checkable criteria only. The gate asks whether this outline delivers the brief's argument, and no check here answers that — read the slide intents in order and decide. Approve with `autodeck approve northwind-milestone outline`.
```

Even a blocking finding is not a rejection — you can read it and still approve; what you
cannot do is not see it. When there is at least one blocking finding the command exits with
code 4; that is a report, not a crash.

### The one question you are answering

**Does this sequence of slides make the brief's argument, in order, honouring any pins?**
Not "is it pretty" — there is no wording or design yet. Read the intent lines top to bottom
as if they were the talk. A clean report ("All mechanical checks pass") says every message
has a slide; it does not say the story works. That judgement is yours.

### Approving

```bash
uv run autodeck approve northwind-milestone outline --by "Your Name"
```

```
approved outline for northwind-milestone
  covers sha256 205779d5ed3aea87...
still pending: claims, final_render
```

**This is how you sign from here on.** `approve` takes `--by` and, if you leave it off,
records the name `owner`. Put your real name in. The gate names are exactly `brief`,
`outline`, `claims` and `final_render`. (`brief` was already approved when you typed `/sign`;
the `approve` command *can* record it too, but `/sign` is the intended route.)

Three things about `approve`:

- **It records what you approved, not just that you did.** Note the `covers sha256 …` line
  in the output above: that is a fingerprint of the exact outline file at the moment you ran
  the command, and it is stored in `runs/<run>/state.json` next to your name and the time.
  Every later step re-checks it (see "If you do not like the outline" below).
- **It refuses to approve something that does not exist.** On a run where the stage has not
  run, nothing is recorded:

  ```
  cannot approve GATE 'claims' for run 'quit-demo': the validate stage has not completed. Run `autodeck validate quit-demo` first. Nothing was recorded.
  ```

  and the same for `outline` (`the outline stage has not completed`), `brief` (the run has no
  brief) and `final_render` (there is no rendered deck; section 6b says what else it requires). Approving the claims also needs them
  to be current — if `content` has been run since `validate`, it refuses with
  `the facts changed after validation (IR v8); re-run `autodeck validate <run>`` (section 6).
- **It does not check that you have looked.** It records whatever you tell it, in any order
  that the stages allow. The system relies on you not running it until you have read the
  thing.

### If you do not like the outline

Run the same `outline` command again, *before* you approve. It does not take your feedback —
the only input is the signed brief — so the one thing you can change is the model's answer
itself. Because model replies are cached (section 2), **a plain re-run replays the same
outline**: in the test run, running `outline` a second time made no request to the model and
wrote the same outline. To get a different attempt, delete the saved replies first:

```bash
rm -r runs/northwind-milestone/llm_cache
uv run autodeck outline northwind-milestone --client northwind-retail --project llm-inference-efficiency
```

(That costs one request, and `wrote …/ir/v1.json` appears again: the outline is always
`v1`, and a new one replaces it.) If the problem is the brief itself, the brief cannot be
edited once signed; start a new run id and plan again.

**If you re-run `outline` after approving it, the approval is withdrawn automatically** — if
the outline that comes out is different. The approval is tied to the fingerprint of the file
you approved; a different file no longer matches. In the test run, an outline regenerated
after approval gave this, and `content` refused to continue:

```
run northwind-reoutline (env=dev)
stages:
  ingest         not-started
  plan           completed
  outline        completed
  content        not-started
  validate       not-started
  art_direction  not-started
  render         not-started
  audit          not-started
gates:
  brief          2026-10-01T20:27:05+00:00 by Jane Owner
  outline        NOT CURRENT (2026-10-01T20:27:05+00:00 by Jane Owner) — the outline changed after it was approved; review what is there now and re-approve it
  claims         PENDING
  final_render   PENDING
```

```
GATE 'outline' is not approved for run 'northwind-reoutline': the outline changed after it was approved; review what is there now and re-approve it. Review the artifacts under runs/northwind-reoutline/ and record approval with `autodeck approve northwind-reoutline outline`. The pipeline never self-approves (A7).
```

Review the outline that is there now and approve it again:

```
approved outline for northwind-reoutline
  covers sha256 784550535bff6c3d...
still pending: claims, final_render
```

If the re-run produced exactly the same outline (a replayed one does), the fingerprint still
matches and the approval stands.

---

## 5. Step 3 — content and validation

```bash
uv run autodeck content  northwind-milestone
uv run autodeck validate northwind-milestone
```

Neither command takes `--client` or `--project` (they read them from the run). Nothing here
needs your judgement; you are reading for warnings.

**`content`** writes the wording of every slide from the approved outline, one request per
slide, and runs two automatic checks on the result. Each slide's reply is saved as it
arrives, so if the quota runs out part-way you run the same command again and only the
unfinished slides are asked for (section 2). If you run it before approving the
outline:

```
GATE 'outline' requires human approval before run 'northwind-milestone' continues. Review the artifacts under runs/northwind-milestone/ and record approval with `autodeck approve northwind-milestone outline`. The pipeline never self-approves (A7).
```

(Exit code 3 means "a gate is not approved yet". It is the system working.) Normal output
looks like this:

```
  s1       1 block(s), 0 note(s)
  s2       2 block(s), 0 note(s)
  s3       3 block(s), 0 note(s)
  s4       2 block(s), 0 note(s)
  s5       2 block(s), 0 note(s)

wrote IR v3

A2 — numeric lint
0 numeral(s) · 0 derivation(s)

Every numeral traces to a cited span or a re-executed derivation.

A5 — framing lint
3 framing block(s) · 6 block(s) of free text · 0 demoted

Every framing block stays on the right side of the fence.

Header flow — read top to bottom; does the argument hold without the rest of the slide?

1. [s1] 'Serve better before you buy more' (framing, 6 word(s))
2. [s2] 'Where serving capacity is lost' (section_header, 5 word(s))
3. [s3] 'What quantisation buys' (section_header, 3 word(s))
4. [s4] 'Faster generation, same outputs' (section_header, 4 word(s))
5. [s5] 'Settle hosted versus self-hosted with your own volume data' (framing, 9 word(s))

Mechanical checks: nothing to flag.

This pass does not judge whether the sequence carries the argument — a human does. Read the numbered list above top to bottom, covering the rest of each slide, and ask whether it would still make the deck's case.

Next: autodeck validate northwind-milestone
```

What the pieces mean:

- `s3  3 block(s), 0 note(s)` — how many pieces of text landed on each slide.
- **A2 — numeric lint**: every number in the text must appear in the passage it cites, or be
  computed in the open from cited numbers. `0 numeral(s)` and "Every numeral traces…" is
  clean. A `[BLOCKING] uncited numeral` line means a number in a sentence is in no cited
  passage. Note that this counts digits inside names too: in a test, the phrase `LLM.int8`
  was blocked as an uncited `8` because the cited quote did not contain that digit. That is
  how the check is designed, not a fault in your deck.
- **A5 — framing lint**: free text on a slide that is not a cited claim (headlines, labels)
  may not contain numbers, named studies, or "proven to" / comparative language. If it does,
  it is demoted to a claim, and a claim with no citation cannot exist, so the build stops.
  `0 demoted` is clean. This is a fixed list of patterns, so ordinary factual wording can
  slip past it (see the A5 decision in section 8) — read headlines for facts yourself.
- **Header flow**: the slide headlines listed in order, for you to skim and ask whether the
  argument holds from headlines alone. Advisory only.

**If a sentence is too long for its slot it is dropped**, not shortened — and every dropped
sentence is listed on its own line, with the slide, the slot, and the first 60 characters of
the sentence. Example (the writer produced a sentence longer than its one-line slot allows;
output from a test fixture):

```
wrote IR v2

2 block(s) dropped during citation/budget resolution (one line each; a dropped block is gone from the deck, not shortened):
  slide s3: dropped block 'b2' (slot 'points'): “Quantisation halves inference memory while keeping full-prec…” — overflow: bullets_supporting.points[1]: 138 characters does not fit (points (each item): at most 1 line(s), roughly 88 characters, at 16pt Inter)
  slide s3: dropped block 'b3' (slot 'points'): “GPTQ does not speed up the multiplications themselves, becau…” — overflow: bullets_supporting.points[1]: 138 characters does not fit (points (each item): at most 1 line(s), roughly 88 characters, at 16pt Inter)
```

Things to know. The dropped sentences are gone from the deck, so a slide can end up with less
than you expected (here slide `s3` lost both its claims and kept only its headline). **A slot
is dropped as a unit:** only the second sentence was too long, but both were removed, which is
why both are listed with the same reason. The count in the heading is the number of sentences
removed. And the fix is not simply to run `content` again — that replays the same replies
(section 2). Delete `runs/<run>/llm_cache` first, or send the claim back with a reason (which
changes what the writer is shown).

If the writer left a *required* slot empty (nothing was written, so nothing was dropped), it
says so separately. A render cannot proceed with such a slot empty:

```
wrote IR v2

1 required slot(s) have no block — nothing was written for them, so nothing was dropped, but a render cannot proceed with them empty:
  slide s2: bullets_supporting.headline: required slot is missing or empty
```

**`validate`** sends every claim to a second, independent AI pass that re-searches the papers
itself (it is not shown the writer's citation as evidence) and gives each claim a verdict. It
prints a summary table:

```
wrote v7

A3 — claim verdicts
4 claim(s) · 0 blocking · 0 capped

supported: PagedAttention is designed for near-zero waste in KV cache memory.
    The span states near-zero KV-cache waste as the design goal.
partially_supported: Quantisation halves inference memory while keeping full-precision performance.
    The span backs halving memory; it does not say cost halves. Only safe as worded.
supported: GPTQ gives no speedup on the multiplications themselves.
    The span says GPTQ gives no speedup for the multiplications.
supported: Speculative decoding speeds up sampling without changing the model's outputs.
    The span says outputs are unchanged.

Next: autodeck gate2 northwind-milestone
```

(In this fixture the validator's answers were scripted, so the verdict text is not real model
output.) The command refuses to run if `content` has not: `run '…' has no content yet. Run
`autodeck content …` first.` (exit 3).

Each time you run `content` it rewrites **every** slide and produces a new version with no
verdicts, so always run `validate` again after `content`.

---

## 6. Step 4 — GATE 2, the claims table

```bash
uv run autodeck gate2 northwind-milestone
```

This prints the audit report, six automatic checks, and a list of claim ids. It refuses to run
until `validate` has (`run '…' has not been validated yet`, exit 3). It approves nothing; run it
as often as you like. Each time, it also writes the report it printed to
`runs/<run>/audit_report.md` (and says so in its last lines), so the file on disk is always the
report for the latest version of the deck.

### Reading one claim

The report walks slide by slide. For each claim you get a table row and a detail block.
Example output (test fixture; the verdicts were scripted):

```
### Slide `s2` — evidence · component `bullets_supporting`

*Intent:* Establish that throughput is bounded by KV-cache memory waste, not compute.

| Block | Claim | Verdict | Evidence |
|---|---|---|---|
| `b2` | PagedAttention is designed for near-zero waste in KV cache memory. | supported | `kwon-2023-pagedattention-vllm` p.1 |

**`b2` — supported**

PagedAttention is designed for near-zero waste in KV cache memory.

> near-zero waste in KV cache memory

— `kwon-2023-pagedattention-vllm` p.1 · retrieved by writer · sha256 `0380bb2fc62d7e55…`

*Validator notes:* The span states near-zero KV-cache waste as the design goal.
```

(This sample and the ones after it come from the end of the send-back cycle described
further down, which is why the claim-id list below it mentions an earlier send-back; your
first `gate2` will not have that section.)

Read it top to bottom:

1. **The sentence** — `PagedAttention is designed for near-zero waste in KV cache memory.`
   This is what will appear on the slide.
2. **The verdict** — `supported` here. What each verdict means:

   | Verdict | Meaning |
   |---|---|
   | `supported` | A passage backs the sentence on its stated terms. |
   | `partially_supported` | Part is backed, or it is backed only under a condition the sentence does not state. Takes the lower verdict when in doubt. Does not block. |
   | `unsupported` | Nothing backs it. **Blocks the final render.** |
   | `contradicted` | A passage elsewhere in the corpus says otherwise, even if the cited one is valid. **Blocks the final render.** |
   | `unverified` | Validation never reached this claim. Counted as a failure. |

3. **The source** — `kwon-2023-pagedattention-vllm p.1`: which document and which page. The
   document id is the PDF's filename in `knowledge/projects/llm-inference-efficiency/papers/`.
4. **The quote** — the line starting `>` is the exact text from that page.
   The `sha256` is a fingerprint of the quote text, so a quote altered after the fact would no longer match.
5. **Validator notes** — the second AI's reasoning. Useful, but it is a model's opinion.

### The one question per claim

**Does the quote actually say what the sentence says?** Put your finger over the verdict and
compare the sentence to the quote. Look for: a number or unit that changed; a condition in
the quote that the sentence dropped ("on an A100", "for a 13B model"); the authors citing
someone else's result rather than their own; "always" or "all" where the quote says "in
our experiments"; and a different quantity (memory in the quote, cost in the sentence).

The example shows exactly that case. The claim on `s3` is `partially_supported`:

```
| Block | Claim | Verdict | Evidence |
|---|---|---|---|
| `b2` | Quantisation halves inference memory while keeping full-precision performance. | partially_supported | `dettmers-2022-llm-int8` p.1 |
| `b3` | GPTQ gives no speedup on the multiplications themselves. | supported | `frantar-2023-gptq` p.2 |

**`b2` — partially_supported**

Quantisation halves inference memory while keeping full-precision performance.

> cut the memory needed for inference by half while retaining full precision performance

— `dettmers-2022-llm-int8` p.1 · retrieved by writer · sha256 `8fb54a880f66a204…`

*Validator notes:* The span backs halving memory; it does not say cost halves. Only safe as worded.
```

The validator's note says the quote backs halving *memory*, not cost — which is the gap the
owner accepted as a risk for `km2` in section 3. Whether the slide's wording is now careful
enough is for you to judge.

### The six automatic checks, the risks, and the claim list

After the report, `gate2` prints:

```
==============================================================================
GATE 2 checkable criteria (docs/phases/PHASE-2B.md)
  [PASS] zero blocks verdict unsupported/contradicted (and none left unverified)
  [PASS] numeric linter: zero unmatched numerals, every derivation re-executes
  [PASS] framing linter clean, no unresolved demotions
  [PASS] every claim shows doc, page and a verbatim quote
  [PASS] conflicts section present where sources disagree (A8)
  [PASS] open_risks from the brief appear in the report

Stable claim ids, for `autodeck send-back --claim`:
  s2:b2  [supported]  PagedAttention is designed for near-zero waste in KV cache memory.
  s3:b2  [partially_supported]  Quantisation halves inference memory while keeping full-precision performance.
  s3:b3  [supported]  GPTQ gives no speedup on the multiplications themselves.
  s4:b2  [supported]  Speculative decoding speeds up sampling without changing the model's outputs.

1 claim(s) already sent back in an earlier round:
  s4:b2 (v4, by Jane Owner): The word always overstates the source, which reports a gain under stated conditions.

Audit report written to runs/northwind-milestone/audit_report.md
```

- `[PASS]`/`[FAIL]` lines are what a machine can check. **A clean set of PASS lines is not
  the gate** — it says every claim has a quote, not that the quote supports the sentence.
  The command exits with code 4 if any line fails.
- The **Open risks** section of the report repeats each risk you accepted in section 3,
  with your name and which slide carries it. If one is missing, that is a `FAIL`.
- The **claim ids** (`s3:b2` = slide 3, block 2) are what you pass to `send-back`. They
  change whenever `content` is re-run, so always read them off the latest `gate2`.

What a failing run looks like (a different scripted validator answer that marked one claim
`unsupported`):

```
==============================================================================
GATE 2 checkable criteria (docs/phases/PHASE-2B.md)
  [FAIL] zero blocks verdict unsupported/contradicted (and none left unverified)
         1 blocking block(s), 0 unverified claim(s)
  [PASS] numeric linter: zero unmatched numerals, every derivation re-executes
  [PASS] framing linter clean, no unresolved demotions
  [PASS] every claim shows doc, page and a verbatim quote
  [PASS] conflicts section present where sources disagree (A8)
  [PASS] open_risks from the brief appear in the report

Stable claim ids, for `autodeck send-back --claim`:
  s2:b2  [supported]  PagedAttention is designed for near-zero waste in KV cache memory.
  s3:b2  [partially_supported]  Quantisation halves inference memory while keeping full-precision performance.
  s3:b3  [supported]  GPTQ gives no speedup on the multiplications themselves.
  s4:b2  [unsupported]  Speculative decoding always speeds up sampling without changing the outputs.

Audit report written to runs/northwind-milestone/audit_report.md
```

### Approving

When you have read every claim and are satisfied:

```bash
uv run autodeck approve northwind-milestone claims --by "Your Name"
```

```
approved claims for northwind-milestone
  covers sha256 2e79b95917388dbd...
still pending: final_render
```

The `covers sha256 …` line is the fingerprint of the *facts* in the validated claims table you
just reviewed: every claim sentence with its quote, source and verdict, and the wording of
every other block. `still pending: final_render` is correct — that is approval 4, the finished
deck (section 6b). Finish by printing the state:

```bash
uv run autodeck status northwind-milestone
```

```
run northwind-milestone (env=dev)
stages:
  ingest         not-started
  plan           completed
  outline        completed
  content        completed
  validate       completed
  art_direction  not-started
  render         not-started
  audit          not-started
gates:
  brief          2026-10-01T21:46:26+00:00 by Jane Owner
  outline        2026-10-01T21:46:27+00:00 by Jane Owner
  claims         2026-10-01T21:46:27+00:00 by Jane Owner
  final_render   PENDING
```

`status` shows `plan`, `outline`, `content` and `validate` as `completed` once they are (`ingest`
always stays `not-started`, because the document store is built outside any run;
`art_direction`, `render` and `audit` stay `not-started` until step 5, section 6b), and the
`gates:` section shows who approved what and when.

**An approval stops counting if what it covered changes.** The claims approval is tied to
the *facts* of the deck, not to a file: the claim sentences, their quotes and sources, their
verdicts, and the wording of every other block. If you run `content` again after approving,
every verdict is wiped (section 5), so the facts no longer match what you reviewed, and
`status` says so:

```
run northwind-milestone (env=dev)
stages:
  ingest         not-started
  plan           completed
  outline        completed
  content        completed
  validate       completed
  art_direction  not-started
  render         not-started
  audit          not-started
gates:
  brief          2026-10-01T21:46:26+00:00 by Jane Owner
  outline        2026-10-01T21:46:27+00:00 by Jane Owner
  claims         NOT CURRENT (2026-10-01T21:46:27+00:00 by Jane Owner) — the facts changed after validation (IR v8); re-run `autodeck validate northwind-milestone`
  final_render   PENDING
```

Approving the new table is refused until it has been validated again:

```
cannot approve GATE 'claims' for run 'northwind-milestone': the facts changed after validation (IR v8); re-run `autodeck validate northwind-milestone`. Nothing was recorded.
```

Run `validate` and `gate2` again, read the new table, and approve that one. The same happens
to the outline if its file changes (section 4). A line starting `NOT CURRENT` in `status`
always means "approved once, but no longer valid"; `PENDING` means never approved.

What does **not** stop the claims approval counting: the finishing steps of section 6b (art
direction and the critique) save new versions of the deck that change colours, type sizes,
layouts and icons but cannot change a word, number, quote or verdict. Those versions have
the same facts, so the approval stands. Only a changed claim, citation, verdict or sentence
voids it.

### Rejecting specific claims

If a claim is wrong, weak, or overstated, send it back instead of approving:

```bash
uv run autodeck send-back northwind-milestone --claim s4:b2 --reason "…" --by "Your Name"
```

Give one `--reason` for each `--claim` (both can be repeated, in matching order), and the
reason is required — the writer is shown it. Example output:

```
sent back s4:b2 (v4) — The word always overstates the source, which reports a gain under stated conditions.

wrote runs/northwind-milestone/send_backs.json

This is a rejection, not an approval — GATE 2 still needs `autodeck approve northwind-milestone claims` once every claim is addressed. Re-run `autodeck content northwind-milestone` so the writer sees this.
```

An id that is not in the current claim list is refused (`unknown claim id(s)`, exit 1), and a
missing `--reason` is refused by the command line itself (exit 2). The rejection is stored
in `runs/<run>/send_backs.json`, including a copy of the sentence and its quote.

**A send-back is not an approval.** After it, do the cycle again:

```bash
uv run autodeck content  northwind-milestone
uv run autodeck validate northwind-milestone
uv run autodeck gate2    northwind-milestone
```

On the next `content` the writer is shown your rejection and reason. If it writes the
identical sentence again, the program throws that sentence away and says so:

```
wrote IR v5

1 block(s) dropped as a verbatim repeat of a GATE 2 send-back:
  slide s4 face block 'b2' dropped: identical to the claim sent back as 's4:b2' against IR v4 by Jane Owner — The word always overstates the source, which reports a gain under stated conditions.
```

**Be clear about what this does and does not guarantee.** The check is an exact-text match.
A sentence that says the same wrong thing in different words is *not* caught — the writer is
told why you rejected the original, which is the other half of the defence, but nothing forces
it. So after a send-back, read the replacement at `gate2` as critically as the first one. Also,
`gate2` lists earlier send-backs by their old ids (`1 claim(s) already sent back in an earlier
round:`), and an id can now point at a different sentence.

---

## 6b. Step 5 — GATE 3, the finished deck

### What this step is

Four things happen, in this order, and only the last two are yours:

1. **Art direction** — the program decides, slide by slide, whether the slide is led by text,
   by a diagram or by icons, and an AI art director proposes taste changes: which accent
   colour a slide uses, how large its type is, which icons a "three pillars" slide carries.
2. **True-render critique** — the deck is actually drawn (by LibreOffice, to pictures), an
   AI critic looks at the pictures, scores them out of 10 and proposes more changes of the
   same kind, and the program redraws. Up to three looks.
3. **The final audit** — `gate3` re-checks the finished file by machine and prints one
   report. This is the second half of "GATE 3".
4. **Your hands-on checks in PowerPoint**, then your approval.

**The prerequisite is a current claims approval** (section 6): `autodeck status <run>` must
show a date and a name on the `claims` line, not `NOT CURRENT` and not `PENDING`. You do not
have to remember to check: `render` and `gate3` both refuse (exit 3) without it, and
`approve … final_render` refuses too.

**Art direction and the critique cannot change a word, a number, a quote or a source.**
Their whole vocabulary is a short fixed list (accent colour, type size, which block is
emphasised, which layout, which icons); it has no way to write text, and the program refuses
any proposal that would alter a fact. So they do **not** void your claims approval, and you do
not need to read the claims again. Only a changed claim, citation, verdict or sentence does
that — which in practice means only running `content` again. You will see this in the
`status` output below: `claims` stays approved through the whole step.

### `autodeck render` — build the deck

```bash
uv run autodeck render northwind-milestone
```

Takes a run id and nothing else (it also has `--runs-root` and `--env`, which you leave
alone). It needs `GEMINI_API_KEY` (set in section 2) and no other key; it refuses to start
unless the claims approval is current. It costs about 1 request for art direction (on the
same model as `outline`, so it shares that model's daily 20) plus 1 to 3 for the critique (on
the `aesthetic` model, one per look at the deck), and takes a minute or two because it draws the deck
for real. For a run whose claims are not approved (here a run called `quit-demo`) it stops at once:

```
GATE 'claims' requires human approval before run 'quit-demo' continues. Review the artifacts under runs/quit-demo/ and record approval with `autodeck approve quit-demo claims`. The pipeline never self-approves (A7).
```

(exit 3, nothing written). Example output from a run that works (from a test fixture with
scripted stand-in models — your content will differ; the art director and the critic here
are scripts, so what they "decided" is not what a real model would say). This is the plain
five-slide deck the `content` step writes:

```
Art direction
  s1         text_led       (rule) title
  s2         text_led       (rule) bullets_supporting
  s3         text_led       (rule) bullets_supporting
  s4         text_led       (rule) bullets_supporting
  s5         text_led       (rule) callout_takeaway
  1 action(s) applied, 1 rejected
    applied  set_accent slide_id=s5 accent=accent2
    rejected set_accent slide_id=s9 accent=accent3: unknown slide_id 's9'
  Rationale: The deck is four text slides and a close; give the closing takeaway the second accent so it reads as the conclusion, and keep the evidence slides plain.
wrote IR v8

Aesthetic loop
  Stopped: no_actions. Best score: 8.5/10.
  iteration 0: score 6.5, 1 QA finding(s), 1 applied, 0 rejected
    applied  set_type_scale slide_id=s3 scale=compact
  iteration 1: score 8.5, 1 QA finding(s), 0 applied, 0 rejected
wrote IR v9

Wrote runs/northwind-milestone/deck.pptx
Rendered 5 slide(s) to PNG in runs/northwind-milestone/previews/final
What the critic saw, per iteration: runs/northwind-milestone/previews/aesthetic

Next: autodeck gate3 northwind-milestone
```

How to read it, top to bottom:

- **`Art direction`, one line per slide**: the slide id, its **mode**, the word in brackets
  saying *why*, and the layout. The modes are `text_led`, `diagram_led` and `icon_anchored`.
  `(rule)` means the program chose it from what is on the slide (a diagram makes it
  `diagram_led`, icons make it `icon_anchored`, anything else is `text_led`). `(pin)` would
  mean it follows a layout pin you put in the brief at the planning step. The art director
  does not choose modes.
- **`1 action(s) applied, 1 rejected`**: the art director's proposals. Each line is one of
  the fixed actions (`set_accent`, `set_type_scale`, `assign_icons`, `swap_component`,
  `set_emphasis`) with the slide it targets. `rejected` lines carry the reason; here the
  stand-in proposed a change to a slide `s9` that does not exist, and the program said so and
  moved on. A rejection is the safeguards working, not an error.
- **`Rationale:`** — the art director's own explanation, printed so you can judge it. It is
  reporting only; nothing in it is applied.
- **`wrote IR v8`** — the deck's next saved version. Every presentation pass saves its own
  version (the numbers continue from the validate step, which wrote v7).
- **`Aesthetic loop`** (the critique): `Stopped:` says why it ended, `Best score:` is the
  critic's mark out of 10, and each `iteration` line is one look: its score, how many
  mechanical layout problems (`QA finding(s)`: overlaps, text off the safe area, text too
  small, low contrast) the file had, and what was applied or rejected. The stop reasons, in
  plain words: `target_reached` — scored 8 or more *and* no layout problem is left open (a high mark over
  a layout problem does not end it: in the example above the second look scored 8.5 with one
  problem still open and the critic had nothing more to propose, so it ended `no_actions`); `no_actions` — the critic had nothing to
  change; `all_rejected` — everything it proposed was refused; `max_iterations` — three
  looks done; `qa_regression` — a change made the layout problems worse, so it was dropped and
  the best earlier deck kept; `audit_failed` — a change broke the re-check of claims on the
  page, so it was dropped; `model_error` — the critic did not answer (below).
- **Where the files are.** `runs/northwind-milestone/deck.pptx` is the deck. The pictures
  of it are `runs/northwind-milestone/previews/final/deck-1.png`, `deck-2.png`, … one per
  slide: open them in any image viewer to see the deck without PowerPoint. What the critic
  looked at, iteration by iteration, is under `previews/aesthetic/iter-0/png/`,
  `iter-1/png/`, … Those pictures are LibreOffice's drawing, **not PowerPoint's**, which is why the five checks
  below exist: a picture cannot show you whether a shape can be recoloured.

The state afterwards. Note that the claims line did not change:

```
run northwind-milestone (env=dev)
stages:
  ingest         not-started
  plan           completed
  outline        completed
  content        completed
  validate       completed
  art_direction  completed
  render         completed
  audit          not-started
gates:
  brief          2026-10-01T21:46:26+00:00 by Jane Owner
  outline        2026-10-01T21:46:27+00:00 by Jane Owner
  claims         2026-10-01T21:46:27+00:00 by Jane Owner
  final_render   PENDING
```

`autodeck ir versions northwind-milestone` now lists `v1 … v9`: the two new versions are the
art direction pass (v8) and the critique's change (v9). They changed no fact.

**You can run `render` again at any time**, and it always runs every stage again (there is
no option to skip one). It writes a new `deck.pptx` over the old one and a new IR version. That
matters if you have already approved the finished deck (below): whether the approval
survives depends on whether the new file is actually different, and in my tests it was.
Even when the stand-in models gave the same instructions again, the new file differed from
the old one and `status` showed the following (from a test fixture that has only the claims
approval; wherever I have cut output in this guide, a line `(… N lines omitted …)` says how
many lines are missing):

```
(… 10 lines omitted …)
gates:
  brief          PENDING
  outline        PENDING
  claims         2026-10-02T08:09:20+00:00 by owner
  final_render   NOT CURRENT (2026-10-02T08:09:25+00:00 by Jane Owner) — the rendered deck changed after it was approved; review what is there now and re-approve it
```

and you approve again: run `gate3` on the new deck first (`approve` refuses a deck `gate3` has not described),
then approve. If `status` says `NOT CURRENT`, you must read what is there now and approve again. Because real models answer differently each time, expect a
re-run to produce a different deck, and expect to redo the PowerPoint checks on it.

**If the critique did not happen.** Two ways this shows. If the critic's free-tier quota is
spent (Gemini, per day), `render` still finishes the deck, then stops with exit code 5:

```
Art direction
  s1         text_led       (rule) bullets_supporting
  s2         diagram_led    (rule) framework_diagram
  s3         icon_anchored  (rule) icon_pillars
  s4         text_led       (rule) chart_focus
  1 action(s) applied, 0 rejected
    applied  assign_icons slide_id=s3 slot=pillar_icon concepts=['speed', 'security', 'growth'] color_token=accent1
  Rationale: Give the capability slide its icons.
wrote IR v2

Aesthetic loop
  Stopped: model_error (iteration 0: RateLimitError: gemini: rate limited (429)). Best score: none.

Wrote runs/r1/deck.pptx
Rendered 4 slide(s) to PNG in runs/r1/previews/final
What the critic saw, per iteration: runs/r1/previews/aesthetic

STOPPED: role 'aesthetic' (gemini, model gemini-3.1-flash-lite) was rate limited.
  The provider refused the call (HTTP 429) and waiting inside the command did not clear it.
  On a free tier this is almost always that model's daily quota: it resets daily, so running the command again sooner will not help.
  Saved: IR versions up to v2 were written; runs/r1/deck.pptx exists but was not (fully) critiqued. The run's response cache is empty, so a re-run repeats every model call.
  Then run `autodeck render r1` again.
```

(In this test the stand-in model does not write to the response cache, which is why the
`Saved:` line says it is empty; with the real model it counts the saved calls.) `deck.pptx` exists and is
a valid deck, only it did not get the critic's pass. You can go on to `gate3` and
judge it as it is, or wait a day and run `render` again, which replays what finished. If
instead the critic answered with something unusable, you get the same files and exit
code 0, and one yellow line:

```
(… 10 lines omitted …)
Aesthetic loop
  Stopped: model_error (iteration 0: ProviderError: the reply was not valid JSON). Best score: none.

Wrote runs/r1/deck.pptx
Rendered 4 slide(s) to PNG in runs/r1/previews/final
What the critic saw, per iteration: runs/r1/previews/aesthetic

The deck was not (fully) critiqued: a model call failed (details above). The deck is rendered and safe to review; run `autodeck render r1` again to retry the critique (completed provider calls replay from the cache).

Next: autodeck gate3 r1
```

If the *art director's* quota is the one spent, the message names `role 'outline'`, and the
rule-chosen modes are used without the model's taste. If the deck has an icon slide, that
slide gets its icons from the art director, so no deck can be drawn yet, and the message
ends with a line saying so (exit 5, no `deck.pptx`):

```
STOPPED: role 'outline' (gemini, model gemini-3.6-flash) was rate limited.
  The provider refused the call (HTTP 429) and waiting inside the command did not clear it.
  On a free tier this is almost always that model's daily quota: it resets daily, so running the command again sooner will not help.
  Saved: IR versions up to v2 were written. The run's response cache is empty, so a re-run repeats every model call.
  Then run `autodeck render r1` again.
  No deck was drawn: the icon slide (s3) could not get its icons because the art-direction call above failed. Re-run `autodeck render r1` later.
```

Wait for the quota to reset and run `render` again. (A deck with no icon slide is still drawn,
and the command then exits 5 as in the critic case above.)

### `autodeck gate3` — the final audit

```bash
uv run autodeck gate3 northwind-milestone
```

Takes a run id. It also takes `--knowledge-root` (default `knowledge`), which is where it
finds the client's header style; you only need it if you are not standing in the repository
root, in which case you get `project '…' not found at …` and exit code 1 (section 2: run
every command from the repository root). It uses no model and no key, can be run as often as you
like, and approves nothing. It re-reads the files on disk every time, so the report always
describes the `deck.pptx` that is there now. It writes down what it concluded (pass or fail,
and for which deck), because `approve … final_render` reads that. It needs the claims
approval to be current, and refuses without it (exit 3, nothing written):

```
GATE 'claims' is not approved for run 'r1': the facts changed after validation (IR v6); re-run `autodeck validate r1`. Review the artifacts under runs/r1/ and record approval with `autodeck approve r1 claims`. The pipeline never self-approves (A7).
```

Before `render` has run it says so:

```
run 'northwind-milestone' has no rendered deck. Run `autodeck render northwind-milestone` first.
```

**Read the first four lines first.** The three paths it prints are the three things you
get together: the **deck** (`deck.pptx`), the **final audit report**
(`final_audit_report.md`: the report `gate3` prints, saved to a file) and the **build
manifest** (`build_manifest.json`, the record of which models, prompts and knowledge
produced the deck; you do not need to read it, but send it along if asked). Then the report
itself, and then, as a summary at the very bottom, the four criteria a second time, so you do
not have to scroll back. The terminal does not repeat the claim-by-claim audit (it is the
GATE 2 report you have already read): the file `final_audit_report.md` has it, and the
terminal has one line saying so. Here is a deck where everything the machine can check
passes — from a different test fixture with a chart, a diagram and three icons, because the
plain deck above cannot pass (see below):

```
GATE 3 - the owner gets these together
  Deck:               runs/r1/deck.pptx
  Final audit report: runs/r1/final_audit_report.md
  Build manifest:     runs/r1/build_manifest.json

# GATE 3 - final deck review

Deck: `runs/r1/deck.pptx`
Deck digest: `b5d0e6b8a17a37a67fff97e6e1aab5f728ec57f4650942668cd21aaa511d42e1`

`autodeck approve <run> final_render` records this digest. If the deck changes after this report was written, the approval no longer counts.

## Checkable criteria

[PASS] Post-render audit passes (every claim on its slide, every number traced) - no findings
[PASS] No deterministic QA findings - no findings
[PASS] No blocking grammar findings - no blocking findings
[PASS] At least one native chart, one native diagram and one theme-recolourable icon - 1 chart(s), 1 diagram(s), 3 icon(s)

All four checkable criteria pass.

## Findings

### Post-render audit

- numeric re-lint [advisory] numeral matched without its unit · slide s4 (rendered): '0.42' → matches finance p.2 on value only — the span qualifies it as 'usd' and the text does not. The value is in the span, so A2 holds — but the unit came from the source rather than from the text, and a bare figure on a slide is one axis label away from meaning something else. The only match in this module wider than a shared (value, unit) key, and it is reported every time precisely because it is wider.

### Deterministic QA

None.

### Grammar

None.

## Header flow

Header flow — read top to bottom; does the argument hold without the rest of the slide?

1. [s1] 'The kernel rewrite cut cost per token by 41%.' (claim, 9 word(s))
2. [s2] 'A two-step rollout gets the platform live' (framing, 7 word(s))
3. [s3] 'Three things we do well' (framing, 5 word(s))
4. [s4] 'Cost per token fell' (framing, 4 word(s))

Mechanical checks (advisory — never blocks a build):
  s1: ends in punctuation the style disallows: 'The kernel rewrite cut cost per token by 41%.'
  s4: serves message 'm1' (position 1) after message 'm2' (position 2) - a storyline break, or a deliberate recap?

This pass does not judge whether the sequence carries the argument — a human does. Read the numbered list above top to bottom, covering the rest of each slide, and ask whether it would still make the deck's case.

## Claim-level audit

The claim-level audit is in `runs/r1/final_audit_report.md` (it repeats the GATE 2 table you have already reviewed).

## Human checks - do these in PowerPoint, by a person

These five checks must be done in PowerPoint by a person. Nothing in this report has checked them, and a clean run of every criterion above does not stand in for them.

- [ ] A diagram node can be selected and recoloured.
- [ ] An icon can be selected and recoloured from the theme palette.
- [ ] A chart's underlying data can be edited.
- [ ] Theme colours and fonts appear in PowerPoint's own Design UI.
- [ ] Adding a new slide by hand inherits the master's look.

==============================================================================
  [PASS] Post-render audit passes (every claim on its slide, every number traced)
         no findings
  [PASS] No deterministic QA findings
         no findings
  [PASS] No blocking grammar findings
         no blocking findings
  [PASS] At least one native chart, one native diagram and one theme-recolourable icon
         1 chart(s), 1 diagram(s), 3 icon(s)

Approve with `autodeck approve r1 final_render` after doing the five PowerPoint checks above; the approval records the deck digest shown (b5d0e6b8a17a37a6...). A clean run above is not the gate.
```

This is verbatim. The file `runs/r1/final_audit_report.md` holds the same report with the
claim-by-claim audit (the GATE 2 report again, plus the conflicts, risks and linter
sections) in place of the line under `## Claim-level audit`.

What each part tells you:

- **The deck digest** (`b5d0e6b8…`) is a fingerprint of the exact file. `approve … final_render`
  stores it. The report and the approval therefore name the same file, and if `deck.pptx` is
  changed afterwards the approval stops counting.
- **The four checkable criteria.** In plain words:
  1. *Post-render audit passes* — after drawing, the program read the text back out of the
     PowerPoint file and confirmed that every claim sentence is on its slide with its
     citation, that every number on a slide traces to a source (the "no number appears
     from nowhere" rule, checked on the finished file, not on the plan), that the slides in
     the file are the slides in the plan, and that no stray picture is hiding in the file.
  2. *No deterministic QA findings* — pure arithmetic on the file: no two shapes overlap,
     nothing sits outside the safe margin, no text is below the minimum size, and text
     contrast is at least 4.5 to 1. A failure names the slide and the shape.
  3. *No blocking grammar findings* — the design rules (word count per slide, at most one
     diagram, no pile-up of icon, chart and diagram on one slide, icons not crowded together).
  4. *At least one native chart, one native diagram and one theme-recolourable icon* — the
     file has to contain one of each, as real PowerPoint objects, counted from the file. It is
     there so that PowerPoint checks 1, 2 and 3 below have something to try. The counts are
     shown (`1 chart(s), 1 diagram(s), 3 icon(s)`).
- **Header flow** — the headline of each slide in order. **Read this list top to bottom, as
  if you were reading only the headlines aloud. Does the argument hold?** It is the one
  place the report asks you to judge the story rather than the file; the lines under
  `Mechanical checks` are advisory (for instance, a headline that ends in a full stop).
  A slide with no headline of its own is listed as `'(empty)'`.
- **Findings** — the full text of anything that failed or was noted, under *Post-render
  audit*, *Deterministic QA* and *Grammar*. An `[advisory]` numeric line, as above, is a
  note and does not fail a criterion.
- **Human checks** — the five boxes at the end, all empty. Nothing in the program has ticked
  or can tick them. They are your job, next.

**What a `FAIL` looks like, and the one you should expect on a real deck.** This is the
`gate3` output for the plain `northwind-milestone` deck above:

```
GATE 3 - the owner gets these together
  Deck:               runs/northwind-milestone/deck.pptx
  Final audit report: runs/northwind-milestone/final_audit_report.md
  Build manifest:     runs/northwind-milestone/build_manifest.json

# GATE 3 - final deck review

Deck: `runs/northwind-milestone/deck.pptx`
Deck digest: `73dcea0c3deb53db032615da72cbba70056a75bf2cff650ffb96986fae55749a`

`autodeck approve <run> final_render` records this digest. If the deck changes after this report was written, the approval no longer counts.

## Checkable criteria

[PASS] Post-render audit passes (every claim on its slide, every number traced) - no findings
[FAIL] No deterministic QA findings - 1 finding(s); first: [insufficient contrast] slide s5 - TextBox 2: measured 3.66 against 4.5; fix by token (palette.accent2)
[PASS] No blocking grammar findings - no blocking findings
[FAIL] At least one native chart, one native diagram and one theme-recolourable icon - 0 chart(s), 0 diagram(s), 0 icon(s)

2 of 4 checkable criteria fail.

## Findings

### Post-render audit

None.

### Deterministic QA

- [insufficient contrast] slide s5 - TextBox 2: measured 3.66 against 4.5; fix by token (palette.accent2)

### Grammar

None.

## Header flow

Header flow — read top to bottom; does the argument hold without the rest of the slide?

1. [s1] 'Serve better before you buy more' (framing, 6 word(s))
2. [s2] 'Where serving capacity is lost' (section_header, 5 word(s))
3. [s3] 'What quantisation buys' (section_header, 3 word(s))
4. [s4] 'Faster generation, same outputs' (section_header, 4 word(s))
5. [s5] 'Settle hosted versus self-hosted with your own volume data' (framing, 9 word(s))

Mechanical checks: nothing to flag.

This pass does not judge whether the sequence carries the argument — a human does. Read the numbered list above top to bottom, covering the rest of each slide, and ask whether it would still make the deck's case.

## Claim-level audit

The claim-level audit is in `runs/northwind-milestone/final_audit_report.md` (it repeats the GATE 2 table you have already reviewed).

## Human checks - do these in PowerPoint, by a person

These five checks must be done in PowerPoint by a person. Nothing in this report has checked them, and a clean run of every criterion above does not stand in for them.

- [ ] A diagram node can be selected and recoloured.
- [ ] An icon can be selected and recoloured from the theme palette.
- [ ] A chart's underlying data can be edited.
- [ ] Theme colours and fonts appear in PowerPoint's own Design UI.
- [ ] Adding a new slide by hand inherits the master's look.

==============================================================================
  [PASS] Post-render audit passes (every claim on its slide, every number traced)
         no findings
  [FAIL] No deterministic QA findings
         1 finding(s); first: [insufficient contrast] slide s5 - TextBox 2: measured 3.66 against 4.5; fix by token (palette.accent2)
  [PASS] No blocking grammar findings
         no blocking findings
  [FAIL] At least one native chart, one native diagram and one theme-recolourable icon
         0 chart(s), 0 diagram(s), 0 icon(s)

Not approvable: `autodeck approve northwind-milestone final_render` will refuse this deck while a criterion above fails. Fix what it names, run `autodeck render northwind-milestone` again, then `autodeck gate3 northwind-milestone`.
```

`gate3` exited with code 4 on that run. That is a report, not a crash; the files were
written all the same. Note the last line: with a `[FAIL]` above, it does not invite you to
approve, because `approve … final_render` will refuse this deck (see "Approving").

- `[FAIL] No deterministic QA findings` names slide `s5`, the shape `TextBox 2` and the
  numbers: contrast 3.66 where 4.5 is needed, and the remedy ("fix by token
  `palette.accent2`": use a different theme colour there). In this run the cause is the
  stand-in art director's choice of `accent2` for the closing slide. A real failure of this
  kind has the same shape: a slide, a shape, a measurement and a remedy. The usual next move is to run
  `render` again and see whether the models choose differently; if the same finding comes
  back, send the report (section 7).
- `[FAIL] At least one native chart…` shows `0 chart(s), 0 diagram(s), 0 icon(s)`. **On a
  deck made by the real `content` step this is likely to fail, every time.** That step writes
  headlines, bullets and callouts, and can add charts, but it cannot create diagrams; the
  only things art direction can add are icons (on an icon-pillars slide). So a deck from
  `plan → outline → content` as the pipeline stands will not contain the diagram that
  PowerPoint check 1 needs. This is a limit of the program, not something you did wrong and
  not something you can fix by re-running. **If criterion 4 fails, do the checks below that you can
  (checks 4 and 5 need nothing special; checks 1 to 3 can be tried only on an object that
  exists, and the counts on the failing line tell you which), mark the others "could not try
  — nothing to select", send the report back, and do not approve.** The
  phase's own exit criteria require a native diagram, so a deck without one does not meet
  the bar; it is a defect to take back to Claude (section 8, the GATE 3 decision).

### The five checks in PowerPoint

These are the ones no program can do for you. The phase document gives the reason in one
sentence: *"D1, D10 and D11 all fail silently if verified any other way."* In plain terms:
the things that make a deck "editable" (that a diagram is made of real shapes, that an icon
takes its colour from the theme, that a chart carries its data) look **identical** whether
they work or not. A picture of the slide, a screenshot, or a program reading the file all
look fine and can all be wrong; the only test that cannot be fooled is the one you do, with
your own hands, in PowerPoint. Nothing in the code has ticked these five boxes, and nothing
will.

**Do them on a copy.** Saving a changed file from PowerPoint changes `deck.pptx`, and that
would void your approval. So copy it first, for example (from the repository root):

```bash
cp runs/northwind-milestone/deck.pptx ~/Desktop/check.pptx
```

and open `~/Desktop/check.pptx` in PowerPoint. Close it without saving when you are done.
Open `previews/final/` too, so you know which slide is which; slide `s2` in the report is
slide 2 in the file. The report's claim-by-claim section names each slide's layout (`framework_diagram`
is the diagram slide, `chart_focus` the chart slide, `icon_pillars` the icon slide).

**Open the Selection Pane first; checks 1 and 2 need it.** On the **Home** tab, at the far
right, click **Arrange**, then **Selection Pane**. A panel opens at the side listing every
shape on the current slide by name. Clicking a name selects that shape.

1. **A diagram node can be selected and recoloured.**
   - Go to the diagram slide. In the Selection Pane, look for names beginning
     `diagram:` — for example `diagram:process_flow:1:1`. The parts are
     `diagram:<kind>:<which diagram on the slide>:<part number>`. In the example the
     coloured shapes (arrows) and their text labels alternate in the list; click a coloured
     shape, not a label.
   - Click `diagram:process_flow:1:1` in the pane (or click the coloured shape on the slide).
     It should show selection handles around that one shape.
   - On the **Shape Format** tab click **Shape Fill**, and under **Theme Colors** pick a
     different colour.
   - **PASS:** that one shape changes colour and the rest of the diagram does not; the colour
     you picked was in the Theme Colors row. **FAIL:** clicking selects the whole diagram as one
     picture (a **Picture Format** tab appears instead of Shape Format); or there is
     no `diagram:` name in the pane; or Shape Fill is greyed out.
2. **An icon can be selected and recoloured from the theme palette.**
   - Go to the icon slide. In the Selection Pane look for names beginning `icon:` — for
     example `icon:lucide:shield-check`. Some icons have two or more pieces with the same
     name; hold **Ctrl** (**Cmd** on a Mac) and click each of them in the pane so that the
     whole icon is selected.
   - Icons are drawn in outline, so use **Shape Format › Shape Outline** (not Shape Fill)
     and pick a different colour under **Theme Colors**.
   - **PASS:** the icon, all of it, takes the new colour. **FAIL:** the icon is a picture
     (Picture Format tab), cannot be selected, or Shape Outline offers no Theme Colors row.
3. **A chart's underlying data can be edited.**
   - Go to the chart slide. Right-click the chart and choose **Edit Data**. A spreadsheet
     window opens with the chart's numbers (this needs Excel installed alongside PowerPoint).
   - Change one number, for example double the value in the first data cell, and click out of the
     sheet.
   - **PASS:** the bar or line moves to match. **FAIL:** there is no Edit Data entry, or the
     window says the linked file is unavailable, or the chart does not move. Close the
     spreadsheet window, and when you finish do not save the file.
4. **Theme colours and fonts appear in PowerPoint's own Design UI.**
   - Open the **Design** tab. In the **Variants** group click the small down arrow (the
     "more" arrow), point to **Colors**, and at the bottom choose **Customize Colors…**. The
     dialog that opens shows the colours of the theme this deck is using right now. Look at
     the six **Accent** boxes, then press **Cancel**. In this development theme (named
     `AutoDeck Dev (Inter)`) they are a deep blue, a teal, an orange, a dark red, a
     grey-purple and a grey (hex `1B4965`, `1E8E7E`, `D98324`, `A4303F`, `5E5A80`, `7A8B99`).
     A client theme will show the client's colours instead.
   - Do the same under **Fonts › Customize Fonts…**: the **Heading font** should read
     `Inter Display` and the **Body font** `Inter` (in this development theme). Cancel.
   - **PASS:** the dialogs show the deck's own colours and fonts. **FAIL:** they show
     Microsoft's Office defaults (an Office blue and orange, Calibri or Aptos), meaning the
     deck is not carrying its own theme.
   - If the fonts *look* different on screen but the names are right, Inter is not installed on this
     computer; PowerPoint is substituting. That is not a failure of this check. The font
     files are in the repository's `fonts/` folder if you want them installed.
5. **Adding a new slide by hand inherits the master's look.**
   - On the **Home** tab click the lower half of **New Slide** (the words, with the arrow),
     and choose **Title and Content**.
   - **PASS:** the new slide has the same background, the same heading font and colour, and
     the same margins as the slides already in the deck; typing into its placeholders uses
     the deck's fonts. **FAIL:** it comes up with a different look (white page, Calibri or Aptos
     text, Office blue and orange).

Write down, for each of the five, PASS or FAIL and one sentence about what you saw. That is
what you send back (section 7). **If any check fails, do not approve.**

### Approving

Only after you have looked at the preview pictures, read the header-flow list, and done the
five checks:

```bash
uv run autodeck approve northwind-milestone final_render --by "Your Name"
```

```
approved final_render for r1
  covers sha256 b5d0e6b8a17a37a6...
still pending: brief, outline
```

(This block is from the fixture that passed `gate3`. `still pending: brief, outline` appears
only because that test fixture has no earlier approvals; yours will print nothing after the
`covers` line if every earlier gate is current.)

The `covers sha256` value is the first 16 characters of the **deck digest** that `gate3`
printed and put in the report. **Changing `deck.pptx` afterwards voids the approval.** I tested this with a one-point
nudge of one shape, made to the file by script, and PowerPoint rewrites a file when it saves,
so treat saving from PowerPoint the same way (this is why you work on a copy):

```
(… 10 lines omitted …)
gates:
  brief          PENDING
  outline        PENDING
  claims         2026-10-02T08:09:20+00:00 by owner
  final_render   NOT CURRENT (2026-10-02T08:09:35+00:00 by Jane Owner) — the rendered deck changed after it was approved; review what is there now and re-approve it
```

Check this with `autodeck status <run>` before you send anything back.

`approve … final_render` checks two things before it records anything, and writes nothing
if either fails (exit 1). First, the claims approval must be current. If you run `content`
after approving the claims and then try to approve the finished deck:

```
cannot approve GATE 'final_render' for run 'r1': the claims approval does not count: the facts changed after validation (IR v6); re-run `autodeck validate r1`. Run `autodeck gate2 r1`, review the claims, and `autodeck approve r1 claims` first. Nothing was recorded.
```

Second, `gate3` must have been run on **this exact deck** and passed. A deck `gate3` never
described (you have not run it, or you rendered again, or the file changed since):

```
cannot approve GATE 'final_render' for run 'r1': the final audit has not been run on this deck. Run `autodeck gate3 r1` first. Nothing was recorded.
```

and a deck whose final audit failed (`[FAIL]` lines, exit 4):

```
cannot approve GATE 'final_render' for run 'northwind-milestone': the final audit did not pass on this deck. Fix what it reports, then re-run `autodeck render northwind-milestone` and `autodeck gate3 northwind-milestone`. Nothing was recorded.
```

So you no longer need to check `status` before you approve as a precaution; the command
checks for you. It still does not check that you did the five PowerPoint checks. That is
yours, and the only part of GATE 3 no program can see.

When all four gates show a name and a date, you are done:

```
run r1 (env=dev)
stages:
  ingest         not-started
  plan           not-started
  outline        not-started
  content        not-started
  validate       completed
  art_direction  completed
  render         completed
  audit          completed
gates:
  brief          PENDING
  outline        PENDING
  claims         2026-10-02T08:09:20+00:00 by owner
  final_render   2026-10-02T08:09:25+00:00 by Jane Owner
```

(This is the fixture that passed `gate3`. It skipped the brief and outline approvals, so those
two show `PENDING`; yours would show a name and a date on all four lines. `audit completed`
is the build manifest `gate3` wrote. The plain `northwind-milestone` deck cannot be shown in
this state: its `gate3` has two `FAIL` lines, so `approve` refuses it.)

### If something fails

| You see | Exit | In plain words | Do this |
|---|---|---|---|
| `GATE 'claims' requires human approval…` or `…is not approved… the facts changed after validation` (from `render`) | 3 | The claims table is not approved, or not the latest. | `autodeck status <run>`; if `NOT CURRENT`, run `validate`, `gate2`, read, and approve the claims again (section 6). |
| `run '…' has no rendered deck` (from `gate3`) | 3 | `render` has not finished here. | `uv run autodeck render <run>`. |
| `GATE 'claims' is not approved … the facts changed after validation` (from `gate3`) | 3 | The claims table was changed after you approved it, so a final audit would describe a deck nobody may ship. Nothing was written. | `validate`, `gate2`, read, approve the claims again (section 6); then `render` and `gate3`. |
| `cannot approve GATE 'final_render' … the final audit has not been run on this deck` | 1 | `gate3` has not run on the file that is there now (or the file changed since). Nothing was recorded. | `uv run autodeck gate3 <run>`, then approve. |
| `cannot approve GATE 'final_render' … the final audit did not pass` | 1 | `gate3` showed a `[FAIL]`. Nothing was recorded. | Fix what it names, `render` again, `gate3` again. Do not approve. |
| `cannot approve GATE 'final_render' … the claims approval does not count` | 1 | The claims table changed or was never approved. Nothing was recorded. | Approve the claims again (section 6), then `render` and `gate3`. |
| `[FAIL]` lines, exit 4 (from `gate3`) | 4 | A criterion failed. The report and files are still written, and `approve … final_render` will refuse this deck. | Read the failing line: slide, shape, measurement. Run `render` again once. If it fails the same way, send the report back. Do not approve. |
| `Final render is blocked … by N finding(s)` (from `render`) | 4 | A claim is `unsupported`, `contradicted` or `unverified`, or a lint fails, even though the claims were approved (`approve` does not stop you approving them). Nothing is rendered. | Go back to section 6: send back, `content`, `validate`, `gate2`, approve; then `render`. |
| `STOPPED: role 'aesthetic' …` / `role 'outline' …` (from `render`) | 5 | A model's free-tier quota is spent, or a key is missing. A deck may already exist; `Saved:` says. | Wait, then run `render` again (it replays what finished). Or carry on to `gate3` with the deck you have. |
| `The deck was not (fully) critiqued` | 0 | A model reply was unusable. The deck is fine to review. | `render` again, or go on to `gate3`. |
| `The deck could not be rendered: LibreOffice not found` (or a missing font) | 1 | The drawing tool is not installed. | `./scripts/setup-dev-env.sh` (section 2), then `render` again. |
| `final_render` shows `NOT CURRENT` in `status` | 0 | The deck file changed after you approved. | Read what is there now, redo the checks if it was re-rendered, and approve again. |

Exits 3 and 4 are reports, not crashes (the program refusing, or telling you what failed); exit 5 means wait; the rest is for
Claude. If you are ever unsure: do not approve. Nothing is lost by waiting.

---

## 7. What to send back to Claude afterwards

### After GATE 2 (claims approved)

Send two things:

1. **The run id** (`northwind-milestone`, or whatever you chose).
2. **The file `runs/<run id>/audit_report.md`** (`runs/northwind-milestone/audit_report.md`).
   `gate2` writes it every time it runs, so there is nothing to redirect or copy out of the
   terminal — but run `uv run autodeck gate2 <run id>` once more after your last `validate`,
   so the file is the report for the deck you approved.

That is all that is needed after GATE 2, together with a line per decision in section 8.

### After GATE 3 (finished deck)

Send these:

1. **The run id.**
2. **The file `runs/<run id>/final_audit_report.md`.** `gate3` writes it every time it runs, so
   run `uv run autodeck gate3 <run id>` once more after your last `render`, so the file
   describes the deck you checked. If `gate3` exited with code 4, send it anyway: the
   `[FAIL]` lines are what Claude needs.
3. **Which of the five PowerPoint checks passed and which failed, with one sentence each** on
   what you saw. Something like this (made-up content, to show the shape):

   ```
   Run: northwind-milestone
   1 diagram node recolour: could not try - the deck has no diagram (criterion 4 failed)
   2 icon recolour: could not try - no icons in the deck
   3 chart data: could not try - no chart in the deck
   4 theme colours and fonts: PASS - Customize Colors showed the six deck accents; fonts Inter Display / Inter
   5 new slide: PASS - Title and Content came up in the deck's font and background
   Approved final_render: no - waiting on the diagram
   ```

   Say "could not try" rather than PASS when there was nothing to try the check on; a check
   nobody could run is not a pass.
4. **The output of `uv run autodeck status <run id>`**, so it is clear which gates are
   current.
5. **If any check failed: `runs/<run id>/deck.pptx` itself**, and say which slide.

If you want to send more, the run folder `runs/<run id>/` holds the rest (derived data;
`runs/` is in `.gitignore`). From the test run above:

| File | What it is |
|---|---|
| `state.json` | Which steps finished, and **who approved each gate, when, and the fingerprint of what they approved**. Approvals live only here (decision B30, below). |
| `brief/v1.yaml` | The brief you signed. |
| `ir/v1.json`, `ir/v2.json`, … | Every version of the deck: outline, then each content pass, then each validated pass. The highest number is the latest. |
| `audit_report.md` | The report `gate2` printed, as of its last run. |
| `deck.pptx` | The finished deck (`render`). Do not open-and-save it; check a copy (section 6b). |
| `final_audit_report.md` | The report `gate3` printed, as of its last run. |
| `build_manifest.json` | Which environment, models, prompts and knowledge made the deck (`gate3`). |
| `previews/final/` | One PNG per slide of the finished deck, as LibreOffice draws it. |
| `previews/aesthetic/iter-N/png/` | What the critic looked at on each look. |
| `logs/planner.jsonl` | The planning conversation. |
| `draft_brief.json` | Only while a planning session is unsigned. |
| `send_backs.json` | Only if you rejected claims. |
| `llm_cache/` | Saved model replies, so a re-run does not pay twice. Safe to delete (section 2). |

---

## 8. Five decisions, answerable in one line each

These are open questions recorded in `STATUS.md`, `DECISIONS.md` and the phase handovers.
The first four block nothing; the fifth is your answer at GATE 3. Reply with the short form
shown.

**B30 — should approvals be saved somewhere permanent?** Your approval (name, time, and now
the fingerprint of what you approved) is saved only in `runs/<id>/state.json`, and that file
is not kept in git, so it does not survive a lost machine; only the notes in `DECISIONS.md`
do. (The fingerprint stops an approval silently covering changed content on your machine; it
does not make the record survive it.) An approval is the one thing in a
run that cannot be reproduced, so it is the one thing that should not be treated as
disposable. Options: **(1)** `autodeck approve` also writes a small committed ledger file
(`approvals/<run_id>.yaml`) with gate, approver, time, and the version and hash of what was
approved; **(2)** fold the approval into the build manifest, which exists only once a deck is
built, so the early gates would have nowhere to live; **(3)** leave it and keep relying on
notes in `DECISIONS.md`. The entry lists option 1 first, as "the order I would take them"; that is the recommendation
on record. Reply: *"B30: option 1"*
(or 2, or 3).

**A5 — should section headers be fenced?** The rule (A5) is that free text that is not a
cited claim may not state facts, because facts need citations. The test for that is a closed
list of factual-sounding patterns (numbers, named studies, "proven to", comparatives). The
handover records that a headline is terse enough to slip past it: "Quantisation halves
serving cost" passed as an uncited section header, and the input from the headers work is to
lean yes, narrowly. One correction to how `STATUS.md` words this, checked against the code: a
later fix (commit `f4a2649`) already runs section-header text through the same pattern list —
a header containing "proven to cut cost by 40%" is demoted, while "Quantisation halves serving
cost" still passes, in a header or in framing text. So the real question is whether to go
beyond that list for headers. Options: yes, narrowly; or no, leave it. Reply: *"A5: yes"* or
*"A5: no"*.

**Chart verdicts.** Claims get a verdict from the validator; charts never do, and a chart's
citations are not linked to individual data points, so "the source table cell is the
citation" cannot literally be checked. Fixing it needs a change to the deck's data model.
Options (my reading of the recorded item, which names the problem and the need for a change
but not a choice): make that data-model change; or leave it as a known gap for now. No
recommendation is recorded. Reply: *"charts: change it"* or *"charts: leave it"*.

**Which error for "does not fit"?** Two layout functions (`split_rows`, `split_columns`) signal
that content does not fit by raising a generic `ValueError`, while a neighbouring one
(`Box.reserve`) raises the specific `LayoutOverflowError`. Making them consistent is a
breaking change that a test currently pins. Options (same caveat as above): switch them to
`LayoutOverflowError`; or keep `ValueError`. No recommendation is recorded. Reply:
*"split_rows: switch"* or *"split_rows: keep"*.

**GATE 3 — is the finished deck approved?** After the five PowerPoint checks (section 6b).
Reply: *"GATE 3: approved"* once you have run `autodeck approve <run> final_render`, or
*"GATE 3: not approved — checks 2 and 3 failed"* (name the checks). If `gate3` showed a
`[FAIL]` on criterion 4 (no native chart, diagram or icon), there is a second question: the
deck the pipeline writes today has no native diagram, so PowerPoint check 1 cannot be tried.
Options: hold the approval until the pipeline can make one — the phase's exit criteria (the
GATE 3 list in `docs/phases/PHASE-3B.md`) require a native diagram, so this is the option
on record; or approve with check 1 untried and the risk accepted. Reply: *"diagram: hold"* or
*"diagram: approve without"*.

---

## 9. If something goes wrong

| You see | It means | Do this |
|---|---|---|
| `FontNotFoundError`, or `MISSING …` in `fonts check` | A font the layout is measured against is not installed. The program refuses to substitute one, on purpose. | Run `./scripts/setup-dev-env.sh`, then `uv run autodeck fonts check --tokens config/tokens/dev.json`. |
| `STOPPED: role '…' (…) was rate limited` (exit 5; `render` too) | Daily free-tier quota for that model is spent. Finished work is saved. | Wait for the quota to reset, then run the same command again; it resumes. Do not keep re-running. |
| `STOPPED: role '…' (…) has no API key` / `…the provider rejected the credentials` (exit 5) | The key is not set in this terminal, or is not valid. | `export GEMINI_API_KEY=…` / `export GROQ_API_KEY=…` (the message names which), then `uv run autodeck models`. |
| `no ingested documents under …` (exit 2) | The document store is empty. | `uv run autodeck knowledge ingest llm-inference-efficiency` |
| `GATE '…' requires human approval before run '…' continues` (exit 3) | A previous approval is missing. **This is the system working.** | Approve the gate it names, once you have judged it. |
| `Final render is blocked … by N finding(s)` (exit 4, from `render`) | A claim is `unsupported`/`contradicted`/`unverified` or a lint is failing, though the claims were approved (`approve` does not stop you approving them). Also the system working; `gate2`'s six checks show the same conditions earlier. | Fix the content (send back, re-run `content` and `validate`, approve the new table). No flag skips it. |
| `GATE '…' is not approved for run '…': the … changed after it was approved` (exit 3) | You re-ran a step after approving what it made, and the result is different. **The system working.** | Read what is there now, then `uv run autodeck approve <run> <gate>` again. |
| `cannot approve GATE '…' for run '…': …` (exit 1) | There is nothing to approve yet, or the facts changed after validation (`the facts changed after validation (IR vN); re-run autodeck validate <run>`). For `final_render` also: the claims approval is not current, or `gate3` has not passed on this deck. Nothing was recorded. | Run the step it names (`validate`, or `gate3`). |
| `no such run '…'` (exit 1) | The run id is mistyped, or you are in a different folder. | Check the spelling and that you are in the repository root. |
| `run '…' has no content yet` / `has not been validated yet` (exit 3) | You skipped a step. | Run the one it names. |
| `outline` exits 4 | Report has a BLOCKING finding. | Read it; see section 4. |
| `gate2` exits 4 | At least one of the six checks says FAIL. | Read the FAIL lines; fix or send back; re-run `content`, `validate`, `gate2`. |
| `render` exits 3, 4 or 5, or `gate3` exits 3 or 4 (exit 3 also when the claims approval is stale); `The deck was not (fully) critiqued`; `LibreOffice not found`; `project '…' not found` (`gate3`, exit 1) | The finishing step. | The table at the end of section 6b says what each means and what to do. |
| `status` shows a gate as `NOT CURRENT` | It was approved, but the thing it covered has changed since. | Read what is there now and approve it again. |

If you are ever unsure whether to approve: don't. Nothing is lost by waiting, and every
command can be re-run.
