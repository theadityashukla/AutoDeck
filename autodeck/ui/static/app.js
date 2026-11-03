// AutoDeck review UI (B40, B42). Plain JS, no build step, no downloads.
// Every action goes through the local API in autodeck/ui/server.py, which calls the
// same code the CLI does. Nothing here can approve a gate by itself (A7, B39): an approval
// is one explicit click that POSTs to the approve / sign route, nothing else.
"use strict";

const view = document.getElementById("view");
const toastEl = document.getElementById("toast");

// ---- helpers --------------------------------------------------------------

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);

const enc = encodeURIComponent;

async function api(path, body, method = "POST") {
  const init = body === undefined
    ? { method: "GET" }
    : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, init);
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const err = new Error(data.error || `${res.status} ${res.statusText}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

let toastTimer;
function toast(message, bad = false) {
  toastEl.textContent = message;
  toastEl.classList.toggle("bad", bad);
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.hidden = true; }, 4200);
}

const svg = (paths, size = 18, sw = 1.8) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

const ICON = {
  lock: svg('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>'),
  info: svg('<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.5"/>'),
  warn: svg('<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>'),
  upload: svg('<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>', 22),
  doc: svg('<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>', 14),
  user: svg('<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>', 16),
};

// A timeline/approval step rendered as a coloured bar (Brief, Outline, Claims, Final).
const STAGES = ["brief", "outline", "claims", "final"];
const STAGE_SCREEN = { brief: "plan", outline: "outline", claims: "claims", final: "final" };
const STAGE_LABEL = { brief: "Brief", outline: "Outline", claims: "Claims", final: "Final" };

function stepsHtml(stages) {
  return `<div class="steps" aria-label="Approvals">${STAGES.map((s) =>
    `<div class="step ${esc(stages?.[s] || "todo")}" title="${esc(s)}: ${esc(stages?.[s] || "todo")}"></div>`
  ).join("")}</div>`;
}

const ENV_WORD = { "dev-mistral": "Draft", sit: "Verification", prod: "Production" };

function tierChip(env) {
  if (!env) return "";
  const draft = env.name.startsWith("dev");
  return `<a class="chip" href="#/settings/models"><span class="dot ${draft ? "dot-warn" : "dot-ok"}"></span>${esc(env.label)} · change in Settings</a>`;
}

function setNav(key) {
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.dataset.nav === key) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}

function renderRecent(runs) {
  document.getElementById("recent").innerHTML = (runs || []).slice(0, 5).map((r) =>
    `<a class="nav-sub" href="${esc(runTarget(r))}">${esc(r.id)}</a>`
  ).join("") || '<div class="nav-sub muted">No runs yet</div>';
}

const fmtTime = (value) => (value ? String(value).replace("T", " ").slice(0, 16) : "");

function runHref(id) { return `#/run/${enc(id)}`; }
function screenHref(screen, id) { return screen ? `#/${screen}/${enc(id)}` : runHref(id); }

// Where "Open" should take you: the screen the run is waiting on, else the run page.
function isDraftRun(r) { return (r.stage_list || []).some((s) => s.key === "compose"); }

function runTarget(r) {
  // A draft-first run with a draft opens on the draft (B43); before that, on its run page.
  if (isDraftRun(r)) {
    const composed = (r.stage_list || []).find((s) => s.key === "compose")?.status === "done";
    if (composed) return `#/draft/${enc(r.id)}`;
    return runHref(r.id);
  }
  const yours = (r.stage_list || []).find((s) => s.status === "yours" && s.screen);
  if (yours) return screenHref(yours.screen, r.id);
  if (!(r.stage_list || []).length && r.resume) return r.resume.replace(/^#\/runs\//, "#/run/");
  return runHref(r.id);
}

// The one-line status of a run, from the stage list when the API gives it.
function runStatus(r) {
  const list = r.stage_list || [];
  const running = list.find((s) => s.status === "running") || (r.job?.status === "running" ? { label: r.job.step || "pipeline" } : null);
  if (running) return { group: "running", text: `Running · ${running.label}`, kind: "accent" };
  const failed = list.find((s) => s.status === "failed");
  if (failed) return { group: "waiting", text: `Failed · ${failed.label}`, kind: "bad" };
  const yours = list.find((s) => s.status === "yours");
  if (yours) return { group: "waiting", text: `Waiting on you · ${yours.label}`, kind: "warn" };
  if (r.stages?.final === "done") return { group: "done", text: "Done", kind: "ok" };
  return { group: "waiting", text: r.next || "In progress", kind: "muted" };
}

function lastActivity(r) {
  const times = [...(r.gates || []).map((g) => g.at), r.job?.finished_at, r.job?.started_at].filter(Boolean).map(fmtTime);
  return times.sort().pop() || "";
}

function runRows(runs) {
  if (!runs.length) return '<div class="empty">No runs yet. Describe a deck above.</div>';
  return `
    <div class="table-head"><div>Run</div><div>Client</div><div>Brief · Outline · Claims · Final</div><div></div></div>
    ${runs.map((r) => `
      <div class="table-row">
        <div><a class="cell-title" href="${esc(runTarget(r))}">${esc(r.id)}</a><div class="cell-sub">${esc(r.next)}</div></div>
        <div class="cell-sub cell-client">${esc(r.client || "—")}</div>
        ${stepsHtml(r.stages)}
        <a class="btn btn-pill self-end" href="${esc(runTarget(r))}">Open</a>
      </div>`).join("")}`;
}

// Header for every screen that lives inside a run: breadcrumb, title, four-step tracker.
function runHeader(runId, r, current, title, sub) {
  const tracker = STAGES.map((k) => {
    const st = r?.stages?.[k] || "todo";
    const cls = `pill ${current === k ? "cur" : st}`;
    const inner = `<span class="pdot"></span>${STAGE_LABEL[k]}`;
    return st === "todo" && current !== k
      ? `<span class="${cls}">${inner}</span>`
      : `<a class="${cls}" href="#/${STAGE_SCREEN[k]}/${enc(runId)}"${current === k ? ' aria-current="step"' : ""}>${inner}</a>`;
  }).join("");
  return `
    <div class="page-head">
      <div class="head-text">
        <div class="crumbs"><a href="#/runs">Runs</a> / <a href="${runHref(runId)}">${esc(runId)}</a></div>
        <h1 class="page-title">${esc(title)}</h1>
        ${sub ? `<p class="page-sub">${esc(sub)}</p>` : ""}
      </div>
      <div class="tracker" aria-label="Approvals">${tracker}</div>
    </div>`;
}

const runSummary = (runId) => api(`/api/runs/${enc(runId)}`).catch(() => null);

// An action failed. 409 means "not ready yet": say what the server said and link back to the run.
function actionError(box, err, runId) {
  if (box && err.status === 409) {
    box.hidden = false;
    box.className = "note warn";
    box.innerHTML = `${ICON.warn}<span>${esc(err.message)} <a href="${runHref(runId)}">Back to the run</a></span>`;
  } else {
    toast(err.message, true);
  }
}

function notReadyView(err, runId) {
  view.innerHTML = `
    <div class="page-head"><div class="head-text">
      <div class="crumbs"><a href="#/runs">Runs</a> / <a href="${runHref(runId)}">${esc(runId)}</a></div>
      <h1 class="page-title">Not ready yet</h1>
    </div></div>
    <div class="note warn">${ICON.warn}<span>${esc(err.message)}</span></div>
    <div class="row-end"><a class="btn" href="${runHref(runId)}">Back to the run</a></div>`;
}

const checkMark = (ok, size = "") =>
  `<span class="check-mark ${ok ? "ok" : "warn"} ${size}" aria-hidden="true">${ok ? "✓" : "!"}</span>`;

// ---- views ----------------------------------------------------------------

// ---- thinking indicator (shared by the slow single calls) --------------------

function thinkingHtml(label) {
  return `
    <div class="thinking" role="status" aria-live="polite">
      <div class="bubble planner typing" aria-hidden="true"><i></i><i></i><i></i></div>
      <span class="thinking-note small muted" id="think-note">${esc(label)}</span>
    </div>`;
}

// Counts seconds in #think-note while it is on the page; returns a stop function.
function startTicker(base, extra) {
  const started = Date.now();
  const timer = setInterval(() => {
    const note = document.getElementById("think-note");
    if (!note) { clearInterval(timer); return; }
    const secs = Math.round((Date.now() - started) / 1000);
    note.textContent = `${base} ${secs}s${secs >= 6 && extra ? " · " + extra : ""}`;
  }, 1000);
  return () => clearInterval(timer);
}

// ---- home -------------------------------------------------------------------

const EXAMPLES = [
  ["Evidence summary for a committee", "An evidence summary for a decision-making committee. Five slides. The audience will ask which source each number came from."],
  ["How it works, for specialists", "Explain how the technology works, for specialists. Three slides. Keep every mechanism claim tied to the source."],
  ["Results and caveats, one slide each", "Results and caveats across the studies, for a review board. Four slides. Say plainly where the sources do not compare."],
];

async function homeView() {
  setNav("home");
  const data = await api("/api/home");
  renderRecent(data.runs);
  const toFix = data.checks.filter((c) => !c.ok).length;
  const clientOpts = data.clients.map((c) => `<option>${esc(c)}</option>`).join("");
  const projectOpts = data.projects.map((p) => `<option>${esc(p)}</option>`).join("");
  view.innerHTML = `
    <div class="page-head">
      <div>
        <h1 class="page-title">What should this deck do?</h1>
        <p class="page-sub">Describe it in a sentence or two. AutoDeck drafts the brief, outline and every slide, with a source on every line.</p>
      </div>
      <span class="row gap-8"><span id="prov-chip"></span>${tierChip(data.env)}</span>
    </div>
    <div class="grid-2">
      <form class="panel" id="draft-form">
        <div class="segmented" id="mode" role="group" aria-label="How to start">
          <button type="button" data-mode="draft" aria-pressed="true">Draft from a prompt</button>
          <button type="button" data-mode="plan" aria-pressed="false">Plan in a chat first</button>
          <button type="button" data-mode="deck" aria-pressed="false">From an existing deck</button>
        </div>
        <div class="stack gap-16" id="prompt-wrap">
          <label class="field">Describe the deck
            <textarea class="textarea prompt-box" name="prompt" id="prompt" rows="5" required placeholder="What it is for, who will see it, how long."></textarea>
          </label>
          <div class="stack gap-8">
            <div class="small strong muted">Or start from an example</div>
            <div class="chips-row">${EXAMPLES.map(([label], i) => `<button type="button" class="chip-btn" data-ex="${i}">${esc(label)}</button>`).join("")}</div>
          </div>
          <label class="switch"><input type="checkbox" id="agent-on"><span class="track" aria-hidden="true"></span><span>Let the agent build it (beta)</span></label>
        </div>
        <div class="stack gap-16" id="deck-wrap" hidden>
          <label class="dropzone" id="deck-drop" for="deck-file">
            ${ICON.upload}<span id="deck-name">Drop a .pptx here, or choose one</span>
            <span class="field-hint" id="deck-hint">One PowerPoint file, up to 50 MB. Your deck becomes the source.</span>
            <input class="file-input" type="file" id="deck-file" accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation">
          </label>
          <div id="deck-err" class="note warn" role="alert" hidden></div>
          <div class="grid-even gap-16">
            <label class="field">Wording
              <select class="select" id="rd-wording"><option value="keep" selected>Keep my words, trim only to fit</option><option value="light">Allow light rewording</option></select>
            </label>
            <div class="field"><span>Options</span>
              <label class="switch"><input type="checkbox" id="rd-layouts" checked><span class="track" aria-hidden="true"></span><span>Change layouts where it helps</span></label>
              <label class="switch"><input type="checkbox" id="rd-papers"><span class="track" aria-hidden="true"></span><span>Also check figures against project papers</span></label>
            </div>
          </div>
          <div class="note">${ICON.info}<span><b>Your deck is the source.</b> Every statement on a new slide cites the original slide it came from. Nothing is added that the deck does not say. Citations are labelled as client-supplied deck.</span></div>
        </div>
        <div class="grid-even gap-16">
          <label class="field">Client
            <select class="select" name="client" required>${clientOpts}</select>
            <a class="field-hint" href="#/clients/new">New client…</a>
          </label>
          <label class="field">Project
            <select class="select" name="project" required>${projectOpts}</select>
          </label>
          <label class="field span-all">Run name
            <input class="input" name="run_id" required pattern="[A-Za-z0-9][A-Za-z0-9._\\-]*" placeholder="e.g. contoso-board-q4">
            <span class="field-hint">Letters, numbers, dots, dashes and underscores.</span>
          </label>
        </div>
        <fieldset class="field" role="radiogroup" aria-label="Design">
          <legend>Design</legend>
          ${["structured", "creative"].map((m) => `
            <label class="radio-row"><input type="radio" name="design_mode" value="${m}" ${(data.env.design_mode || "structured") === m ? "checked" : ""}>
              <span><span class="strong">${esc(DESIGN_LABEL[m])}</span>${(data.env.design_mode || "structured") === m ? ` <span class="small-13 muted">(default for ${esc(data.env.name)})</span>` : ""}<br><span class="small-13 muted">${esc(DESIGN_BLURB[m])}</span></span></label>`).join("")}
          <span class="field-hint">A run keeps the design mode it started with. Any model can run either mode.</span>
        </fieldset>
        <div class="note">${ICON.lock}<span>Only this client's knowledge is loaded. Nothing from other clients reaches the models.</span></div>
        <div id="go-row" class="row between wrap">
          <span class="muted small-13" id="go-hint">AutoDeck asks what it needs to know, then drafts. Nothing is approved until you approve it.</span>
          <button class="btn" id="go" type="submit" ${data.clients.length && data.projects.length ? "" : "disabled"}>Draft the deck</button>
        </div>
        <div id="working" hidden></div>
      </form>
      <section class="panel tight" aria-labelledby="ready-h">
        <div class="panel-head pb-10">
          <h2 class="h2" id="ready-h">Ready to build</h2>
          <span class="small-13 strong ${toFix ? "t-warn" : "t-ok"}">${toFix ? `${toFix} to fix` : "All set"}</span>
        </div>
        ${data.checks.map((c) => `
          <div class="check">
            ${checkMark(c.ok)}
            <div class="check-body">
              <div class="check-name">${esc(c.name)}<span class="sr-only">${c.ok ? " — ready" : " — needs fixing"}</span></div>
              <div class="check-note">${esc(c.note)}</div>
              ${!c.ok && c.fix ? `<div class="check-note mono">${esc(c.fix)}</div>` : ""}
            </div>
          </div>`).join("")}
      </section>
    </div>
    <section class="panel flush" aria-labelledby="runs-h">
      <div class="panel-head pb-12">
        <h2 class="h2" id="runs-h">Continue where you left off</h2>
        <a class="small-13" href="#/runs">All runs</a>
      </div>
      ${runRows(data.runs.slice(0, 5))}
    </section>`;

  const form = document.getElementById("draft-form");
  const prompt = document.getElementById("prompt");
  // The project's provenance mode, shown before the run starts; it follows the project picker.
  const paintProv = async () => {
    const chip = document.getElementById("prov-chip");
    const name = form.elements.project?.value;
    if (!chip || !name) return;
    try { chip.innerHTML = provenanceChip((await api(`/api/projects/${enc(name)}/settings`)).provenance); } catch { chip.innerHTML = ""; }
  };
  form.elements.project?.addEventListener("change", paintProv);
  paintProv();
  let mode = "draft";
  let deckFile = null;
  const MODE_TEXT = {
    draft: ["Draft the deck", "AutoDeck asks what it needs to know, then drafts. Nothing is approved until you approve it."],
    plan: ["Start planning", "Opens a conversation with the planner. When the brief is right, draft the deck from it."],
    deck: ["Redesign the deck", "AutoDeck keeps your story and asks what it needs to know before it redesigns. Nothing is approved until you approve it."],
  };
  const setMode = (m) => {
    mode = m;
    view.querySelectorAll("#mode [data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === m)));
    document.getElementById("prompt-wrap").hidden = m !== "draft";
    document.getElementById("deck-wrap").hidden = m !== "deck";
    prompt.required = m === "draft";
    document.getElementById("go").textContent = MODE_TEXT[m][0];
    document.getElementById("go-hint").textContent = MODE_TEXT[m][1];
  };
  const MAX_DECK = 50 * 1024 * 1024;
  const sizeText = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
  const deckErr = document.getElementById("deck-err");
  const pickDeck = (file) => {
    deckFile = null;
    deckErr.hidden = true;
    const label = document.getElementById("deck-name");
    if (!file) { label.textContent = "Drop a .pptx here, or choose one"; return; }
    if (!/\.pptx$/i.test(file.name)) {
      deckErr.hidden = false; deckErr.innerHTML = `${ICON.warn}<span>${esc(file.name)} is not a .pptx file. Save it as a PowerPoint (.pptx) first.</span>`;
      label.textContent = "Drop a .pptx here, or choose one"; return;
    }
    if (file.size > MAX_DECK) {
      deckErr.hidden = false; deckErr.innerHTML = `${ICON.warn}<span>${esc(file.name)} is ${esc(sizeText(file.size))}. Decks over 50 MB are not accepted.</span>`;
      label.textContent = "Drop a .pptx here, or choose one"; return;
    }
    deckFile = file;
    label.textContent = `${file.name} · ${sizeText(file.size)}`;
  };
  const agentBox = document.getElementById("agent-on");
  try { if (agentBox && localStorage.getItem("autodeck.agent") === "1") agentBox.checked = true; } catch { /* optional */ }
  if (agentBox) agentBox.addEventListener("change", () => {
    try { localStorage.setItem("autodeck.agent", agentBox.checked ? "1" : "0"); } catch { /* optional */ }
  });
  document.getElementById("deck-file").addEventListener("change", (e) => pickDeck(e.target.files[0]));
  const drop = document.getElementById("deck-drop");
  ["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (e) => { e.preventDefault(); pickDeck(e.dataTransfer?.files?.[0]); });
  document.getElementById("mode").addEventListener("click", (e) => {
    const b = e.target.closest("[data-mode]");
    if (b) setMode(b.dataset.mode);
  });
  view.querySelectorAll("[data-ex]").forEach((b) => b.addEventListener("click", () => {
    prompt.value = EXAMPLES[Number(b.dataset.ex)][1];
    prompt.focus();
  }));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(form).entries());
    if (mode === "draft" && agentBox?.checked) body.agent = true;
    if (mode === "deck" && !deckFile) {
      deckErr.hidden = false;
      if (!deckErr.textContent.trim()) deckErr.innerHTML = `${ICON.warn}<span>Choose the .pptx you want redesigned.</span>`;
      return;
    }
    if (mode === "plan") {
      delete body.prompt;
      try {
        const res = await api("/api/plan/start", body);
        location.hash = `#/plan/${enc(res.run_id)}`;
      } catch (err) { toast(err.message, true); }
      return;
    }
    // The checkpoint call takes several seconds: show the thinking indicator meanwhile.
    const goRow = document.getElementById("go-row");
    const working = document.getElementById("working");
    goRow.hidden = true;
    working.hidden = false;
    const thinkText = mode === "deck" ? "Reading your deck and working out what the redesign needs…" : "Reading the evidence and working out what the draft needs…";
    working.innerHTML = thinkingHtml(thinkText);
    const stop = startTicker(thinkText, "this is one short model call");
    form.setAttribute("aria-busy", "true");
    try {
      let res;
      if (mode === "deck") {
        res = await uploadDeck(deckFile, body, {
          wording: document.getElementById("rd-wording").value,
          layouts: document.getElementById("rd-layouts").checked,
          check_papers: document.getElementById("rd-papers").checked,
        });
        try { sessionStorage.setItem(`autodeck.redesign.${body.run_id}`, "1"); } catch { /* optional hint */ }
      } else {
        res = await api("/api/draft/start", body);
      }
      stop();
      location.hash = `#/clarify/${enc(res.run_id || body.run_id)}`;
    } catch (err) {
      stop();
      form.removeAttribute("aria-busy");
      working.hidden = true;
      goRow.hidden = false;
      toast(err.message, true);
    }
  });
}

// Sends the .pptx raw to the upload route. The custom header is required by the server.
async function uploadDeck(file, body, opts) {
  const q = new URLSearchParams({
    run_id: body.run_id, client: body.client, project: body.project, name: file.name,
    wording: opts.wording, layouts: String(opts.layouts), check_papers: String(opts.check_papers),
  });
  if (body.design_mode) q.set("design_mode", body.design_mode);
  const res = await fetch(`/api/redesign/upload?${q}`, {
    method: "POST",
    headers: {
      "X-AutoDeck-Upload": "1",
      "Content-Type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    },
    body: await file.arrayBuffer(),
  });
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const err = new Error(data.error || `${res.status} ${res.statusText}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

async function runsView() {
  setNav("runs");
  const data = await api("/api/runs");
  renderRecent(data.runs);
  const runs = data.runs;
  const clients = [...new Set(runs.map((r) => r.client).filter(Boolean))].sort();
  const state = { q: "", client: "all", seg: "all" };
  view.innerHTML = `
    <div class="page-head"><div>
      <h1 class="page-title">Runs</h1>
      <p class="page-sub">Every deck you have started. Approvals stay with the run.</p>
    </div></div>
    <div class="filters">
      <label class="field grow maxw-300">Search runs
        <input class="input" type="search" id="runs-q" placeholder="Run or project">
      </label>
      <label class="field">Client
        <select class="select" id="runs-client"><option value="all">All clients</option>${clients.map((c) => `<option>${esc(c)}</option>`).join("")}</select>
      </label>
      <div class="field"><span>Status</span>
        <div class="segmented" id="runs-seg" role="group" aria-label="Status">
          ${[["all", "All"], ["waiting", "Waiting on you"], ["running", "Running"], ["done", "Done"]].map(([k, l]) =>
            `<button type="button" data-seg="${k}" aria-pressed="${k === "all"}">${l}</button>`).join("")}
        </div>
      </div>
      <div class="grow"></div>
      <a class="btn" href="#/">New deck</a>
    </div>
    <section class="panel flush"><div id="runs-table"></div></section>`;

  const table = document.getElementById("runs-table");
  const paint = () => {
    const needle = state.q.trim().toLowerCase();
    const rows = runs.filter((r) => {
      const st = runStatus(r);
      return (state.seg === "all" || st.group === state.seg)
        && (state.client === "all" || r.client === state.client)
        && (!needle || `${r.id} ${r.project}`.toLowerCase().includes(needle));
    });
    if (!rows.length) { table.innerHTML = `<div class="empty">${runs.length ? "No runs match these filters." : "No runs yet. Start a planning session from Home."}</div>`; return; }
    table.innerHTML = `
      <div class="runs-grid head"><div>Run</div><div>Client</div><div>Brief · Outline · Claims · Final</div><div>Environment</div><div>Last activity</div><div></div></div>
      ${rows.map((r) => {
        const st = runStatus(r);
        const envName = r.env || "";
        return `
        <div class="runs-grid row">
          <div class="cell-stack"><a class="cell-title" href="${esc(runTarget(r))}">${esc(r.id)}</a><div class="cell-sub">${esc(r.project || "")}</div><div class="cell-sub strong t-${st.kind}">${esc(st.text)}</div></div>
          <div class="cell-client">${esc(r.client || "—")}</div>
          ${stepsHtml(r.stages)}
          <div><span class="badge env-${esc(envName)}">${esc(ENV_WORD[envName] || envName || "—")}</span></div>
          <div class="cell-client">${esc(lastActivity(r) || "—")}</div>
          <a class="btn btn-pill self-end" href="${esc(runTarget(r))}">${st.group === "waiting" ? "Review" : "Open"}</a>
        </div>`;
      }).join("")}`;
  };
  paint();
  document.getElementById("runs-q").addEventListener("input", (e) => { state.q = e.target.value; paint(); });
  document.getElementById("runs-client").addEventListener("change", (e) => { state.client = e.target.value; paint(); });
  document.getElementById("runs-seg").addEventListener("click", (e) => {
    const b = e.target.closest("[data-seg]");
    if (!b) return;
    state.seg = b.dataset.seg;
    document.querySelectorAll("#runs-seg button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    paint();
  });
}

// ---- planning ---------------------------------------------------------------

const EVIDENCE_KIND = { supported: "ok", thin: "warn", unsupported: "bad", unprobed: "" };

function briefHtml(b) {
  if (!b) return '<div class="empty">Nothing drafted yet.</div>';
  const field = (label, value, empty = "Not set yet") =>
    `<div class="bf"><div class="bf-label">${label}</div><div class="bf-value ${value ? "" : "muted"}">${value ? esc(value) : empty}</div></div>`;
  const list = (label, items) => items.length
    ? `<div class="bf"><div class="bf-label">${label}</div><div class="bf-value">${items.map(esc).join(" · ")}</div></div>` : "";
  const messages = b.key_messages.length
    ? b.key_messages.map((m) => `
        <details class="km">
          <summary><span class="km-id">${esc(m.id)}</span><span class="km-text">${esc(m.text)}</span><span class="badge ${EVIDENCE_KIND[m.evidence] ?? ""}">${esc(m.evidence)}</span></summary>
          <div class="km-detail">${m.notes ? esc(m.notes) : m.evidence === "unprobed" ? "Nobody has checked this against the papers yet." : "No notes from the evidence check."}${m.leads.length ? `<div class="small muted">Leads: <span class="mono">${m.leads.map(esc).join(", ")}</span></div>` : ""}</div>
        </details>`).join("")
    : '<div class="bf-value muted">None yet. The planner proposes them as you talk.</div>';
  const risks = b.open_risks.map((r) =>
    `<div class="risk"><div class="small strong t-warn">Accepted risk · ${esc(r.message_id)}</div><div class="small-13">${esc(r.description)} · accepted by ${esc(r.accepted_by)}</div></div>`).join("");
  const pins = b.layout_pins.map((p) => `${p.message_id}: ${p.target} = ${p.value}`);
  return `
    ${field("Objective", b.objective)}
    <div class="bf-row">${field("Audience", b.audience)}${field("Length", b.length_target ? `${b.length_target} slides` : "")}</div>
    <div class="bf"><div class="bf-label">Key messages</div><div class="km-list">${messages}</div></div>
    ${list("Must include", b.must_include)}${list("Must avoid", b.must_avoid)}${list("Layout pins", pins)}
    ${b.header_style ? field("Header style", b.header_style) : ""}
    ${risks}`;
}

async function planView(runId) {
  setNav("runs");
  const [s, r] = await Promise.all([api(`/api/plan/${enc(runId)}`), runSummary(runId)]);
  view.innerHTML = `
    ${runHeader(runId, r, "brief", "Plan the brief", "Talk it through with the planner. Nothing moves on until you approve.")}
    <div class="grid-2 equal plan-grid">
      <section class="panel flush chat-panel" aria-label="Conversation">
        <div class="panel-head divided"><h2 class="h2">Planner</h2><span class="small muted">${esc(s.client)} · ${esc(s.project)}</span></div>
        <div id="chat" class="chat"></div>
        <form id="say" class="chat-form">
          <label class="small muted" for="say-text">Message the planner</label>
          <div class="row end">
            <textarea class="textarea chat-input" id="say-text" rows="2" ${s.signed ? "disabled" : ""}></textarea>
            <button class="btn" type="submit" ${s.signed ? "disabled" : ""}>Send</button>
          </div>
          <span class="small muted">Enter sends, Shift+Enter adds a line.</span>
        </form>
      </section>
      <section class="panel flush" aria-labelledby="brief-h">
        <div class="panel-head pad"><h2 class="h2" id="brief-h">Draft brief</h2><span class="small strong ${s.signed ? "t-ok" : "t-warn"}" id="brief-state">${s.signed ? "Approved" : "Not approved"}</span></div>
        <div class="pad-x brief-body" id="draft"></div>
        <div class="panel-foot">
          <div id="sign-note" hidden></div>
          ${s.signed
            ? `<div class="note ok">${ICON.info}<span>The brief is approved. <a href="${runHref(runId)}">Open the run</a></span></div>`
            : `<ul class="blockers" id="blockers" hidden></ul>
               <button class="btn block" id="sign" type="button">Approve &amp; proceed</button>
               <button class="btn btn-quiet block" id="to-draft" type="button">Draft the deck from this conversation</button>
               <div class="small muted">Approves the objective, audience and key messages, then builds the outline. The planner cannot approve for you.</div>`}
        </div>
      </section>
    </div>`;

  const chat = document.getElementById("chat");
  const draft = document.getElementById("draft");
  const paint = (turns, thinking = false) => {
    chat.innerHTML = (turns.map((t) =>
      `<div class="bubble ${t.role === "human" ? "human" : "planner"}">${esc(t.text)}</div>`
    ).join("") || (thinking ? "" : '<div class="empty">Say what the deck is for and who will see it.</div>'))
      + (thinking ? `
        <div class="thinking" role="status" aria-live="polite">
          <div class="bubble planner typing" aria-hidden="true"><i></i><i></i><i></i></div>
          <span class="thinking-note small muted" id="thinking-note">Thinking…</span>
        </div>` : "");
    chat.scrollTop = chat.scrollHeight;
  };
  // While the planner works: an elapsed-time counter, and after a few seconds a line on
  // what usually takes the time (each key message is checked against the papers).
  let thinkTimer = null;
  const startThinking = (already = 0) => {
    const started = Date.now() - already * 1000;
    thinkTimer = setInterval(() => {
      const note = document.getElementById("thinking-note");
      if (!note) return;
      const secs = Math.round((Date.now() - started) / 1000);
      note.textContent = secs < 6
        ? `Thinking… ${secs}s`
        : `Thinking… ${secs}s · checking key messages against the papers`;
    }, 1000);
  };
  const stopThinking = () => { clearInterval(thinkTimer); thinkTimer = null; };
  const paintDraft = () => {
    draft.innerHTML = briefHtml(s.brief);
    const blockers = document.getElementById("blockers");
    const sign = document.getElementById("sign");
    if (!blockers || !sign) return;
    const list = s.blockers || [];
    blockers.hidden = !list.length;
    blockers.innerHTML = list.map((b) => `<li>${esc(b)}</li>`).join("");
    sign.disabled = list.length > 0;
    if (list.length) sign.setAttribute("aria-describedby", "blockers");
    else sign.removeAttribute("aria-describedby");
  };
  paint(s.transcript || [], !!s.thinking);
  paintDraft();
  if (s.error) toast(s.error, true);

  // Reopened while a reply is still being written (the conversation lives in the server,
  // not this page): show the indicator and check back until the reply lands.
  const followReply = () => {
    startThinking(s.thinking_for || 0);
    pollTimer = setInterval(async () => {
      if (!location.hash.startsWith(`#/plan/${enc(runId)}`)) { stopPolling(); stopThinking(); return; }
      try {
        const next = await api(`/api/plan/${enc(runId)}`);
        if (next.thinking) return;
        stopPolling(); stopThinking();
        Object.assign(s, next);
        paint(s.transcript || []);
        paintDraft();
        input.disabled = false;
        if (s.error) toast(s.error, true);
      } catch { /* keep waiting; the next tick retries */ }
    }, 2000);
  };

  const form = document.getElementById("say");
  const input = document.getElementById("say-text");
  if (s.thinking) { input.disabled = true; followReply(); }
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    input.disabled = true;
    paint([...(s.transcript || []), { role: "human", text }], true);
    startThinking();
    try {
      const next = await api(`/api/plan/${enc(runId)}/say`, { text });
      Object.assign(s, next);
      paint(s.transcript || []);
      paintDraft();
    } catch (err) {
      paint(s.transcript || []);
      toast(err.message, true);
    } finally {
      stopThinking();
      input.disabled = false;
      input.focus();
    }
  });

  const toDraft = document.getElementById("to-draft");
  if (toDraft) toDraft.addEventListener("click", async () => {
    toDraft.disabled = true;
    try {
      await api(`/api/runs/${enc(runId)}/draft-from-chat`, {});
      location.hash = runHref(runId);
    } catch (err) {
      toDraft.disabled = false;
      actionError(document.getElementById("sign-note"), err, runId);
    }
  });

  const sign = document.getElementById("sign");
  if (sign) sign.addEventListener("click", async () => {
    sign.disabled = true;
    try {
      await api(`/api/plan/${enc(runId)}/sign`, {});
      toast("Brief approved. Building the outline.");
      location.hash = runHref(runId);
    } catch (err) {
      sign.disabled = false;
      actionError(document.getElementById("sign-note"), err, runId);
    }
  });
}

// ---- outline ----------------------------------------------------------------

const LAYOUT_MOCKS = {
  title: '<div class="mk-center"><i class="mk w80 h10"></i><i class="mk w50 h5"></i></div>',
  callout: '<i class="mk w60 h8"></i><i class="mk-callout"></i>',
  bullets: '<i class="mk w60 h8"></i><div class="mk-list"><i class="mk w90 h4"></i><i class="mk w80 h4"></i><i class="mk w85 h4"></i></div>',
};
function layoutMock(component) {
  const c = String(component || "");
  if (c.startsWith("title")) return LAYOUT_MOCKS.title;
  if (c.includes("callout") || c.includes("takeaway")) return LAYOUT_MOCKS.callout;
  return LAYOUT_MOCKS.bullets;
}

function approvalLine(a) {
  if (!a) return "";
  if (a.approved) return `Approved by ${esc(a.by || "—")}${a.at ? " · " + esc(fmtTime(a.at)) : ""}`;
  return esc(a.detail || a.state || "Not approved");
}

async function outlineView(runId) {
  setNav("runs");
  const [d, r] = await Promise.all([api(`/api/runs/${enc(runId)}/outline`), runSummary(runId)]);
  const slides = d.slides || [];
  const findings = d.findings || [];
  const blocking = findings.filter((f) => f.severity === "blocking").length;
  let sel = slides[0]?.id;
  view.innerHTML = `
    ${runHeader(runId, r, "outline", "Approve the outline", `${slides.length} slide${slides.length === 1 ? "" : "s"}, no wording yet. Check the order and the intent of each.`)}
    <div class="grid-2 equal align-start">
      <div class="stack gap-14">
        <section class="panel tight">
          <div class="panel-head"><h2 class="h2">Outline${d.version ? ` <span class="muted small">v${esc(d.version)}</span>` : ""}</h2><span class="small muted">Select a slide for detail</span></div>
          <div id="slide-list" class="stack gap-2"></div>
        </section>
        <div class="note">${ICON.info}<span>A clean report says every message has a slide. It does not say the story works. Read the intents top to bottom as if they were the talk.</span></div>
      </div>
      <div class="stack gap-14">
        <section class="panel tight">
          <div class="row gap-8">
            ${checkMark(d.checks_pass && !blocking)}
            <h2 class="h2 ${d.checks_pass && !blocking ? "t-ok" : "t-warn"}">${d.checks_pass && !blocking ? "All mechanical checks pass" : "Some checks need a look"}</h2>
          </div>
          ${findings.map((f) => `
            <div class="check">
              ${checkMark(false, "sm")}
              <div class="check-body"><div class="check-name small-13"><span class="badge ${f.severity === "blocking" ? "bad" : "warn"}">${esc(f.severity)}</span> ${esc(f.label)}</div>
              <div class="check-note">${esc(f.text)}</div></div>
            </div>`).join("")}
          ${(d.corrections || []).length ? `<div class="small muted">Corrections applied: ${(d.corrections).map(esc).join("; ")}</div>` : ""}
          ${d.notes ? `<div class="small muted">${esc(d.notes)}</div>` : ""}
        </section>
        <section class="panel tight" id="slide-detail" aria-live="polite"></section>
      </div>
    </div>
    <div class="action-bar">
      <div id="act-note" hidden></div>
      <div class="action-right">
        ${d.approval?.approved
          ? `<div class="note ok">${ICON.info}<span>${approvalLine(d.approval)}. <a href="${runHref(runId)}">Open the run</a></span></div>`
          : `<button class="btn" id="approve" type="button">Approve &amp; proceed</button>
             <div class="small muted">Approves this outline and starts writing the slides. If the outline changes later, the approval stops counting.${d.approval?.detail && d.approval.state !== "pending" ? " " + esc(d.approval.detail) : ""}</div>`}
      </div>
    </div>`;

  const list = document.getElementById("slide-list");
  const detail = document.getElementById("slide-detail");
  const paint = () => {
    list.innerHTML = slides.map((s) => `
      <button type="button" class="row-btn ${s.id === sel ? "on" : ""}" data-id="${esc(s.id)}" aria-pressed="${s.id === sel}">
        <span class="tile">${esc(s.n)}</span>
        <span class="row-main">
          <span class="row-tags"><span class="badge">${esc(s.role)}</span><span class="mono">${esc(s.component)}</span>${(s.message_ids || []).map((m) => `<span class="badge accent">${esc(m)}</span>`).join("") || '<span class="badge">—</span>'}</span>
          <span class="row-text">${esc(s.intent)}</span>
        </span>
      </button>`).join("") || '<div class="empty">The outline has no slides.</div>';
    const cur = slides.find((s) => s.id === sel);
    if (!cur) { detail.innerHTML = ""; return; }
    const serves = (cur.message_ids || []).map((m) => `<div><span class="mono">${esc(m)}</span> ${esc((d.messages || {})[m] || "")}</div>`).join("")
      || "No key message. This slide frames the decision.";
    detail.innerHTML = `
      <h2 class="h3">Slide ${esc(cur.n)} detail</h2>
      <div class="kv"><div class="k">What this slide must do</div><div>${esc(cur.intent)}</div></div>
      <div class="kv"><div class="k">Serves</div><div class="stack gap-2">${serves}</div></div>
      <div class="kv"><div class="k">Layout</div>
        <div class="row gap-12"><div class="mock">${layoutMock(cur.component)}</div><span class="mono">${esc(cur.component)}</span></div></div>
      <div class="small muted">No wording yet. The outline has nowhere to put any.</div>`;
  };
  paint();
  list.addEventListener("click", (e) => {
    const b = e.target.closest("[data-id]");
    if (b) { sel = b.dataset.id; paint(); }
  });

  const approve = document.getElementById("approve");
  if (approve) approve.addEventListener("click", async () => {
    approve.disabled = true;
    try {
      await api(`/api/runs/${enc(runId)}/approve`, { gate: "outline" });
      toast("Outline approved. Writing the slides.");
      location.hash = runHref(runId);
    } catch (err) {
      approve.disabled = false;
      actionError(document.getElementById("act-note"), err, runId);
    }
  });
}

// ---- claims -----------------------------------------------------------------

// "amber" is `uncorroborated` (B55): general knowledge nothing in the papers confirms. It never blocks, so never red.
const VERDICT_KIND = { supported: "ok", partially_supported: "warn", unsupported: "bad", contradicted: "bad", unverified: "neutral", uncorroborated: "amber" };
const vChip = (v) => `<span class="badge v-${VERDICT_KIND[v] || "neutral"}"><span class="dot"></span>${esc(v)}</span>`;

async function claimsView(runId) {
  setNav("runs");
  const [d, r] = await Promise.all([api(`/api/runs/${enc(runId)}/claims`), runSummary(runId)]);
  const claims = d.claims || [];
  const state = { filter: "all", sel: claims[0]?.id, queue: new Map(), drafts: {}, sent: false };
  const fails = (d.checks || []).filter((c) => !c.passed).length;
  const approved = !!d.approval?.approved;

  view.innerHTML = `
    ${runHeader(runId, r, "claims", "Review the claims", "Every factual sentence with its quote. Approve only what you have read.")}
    <div class="split">
      <section class="panel tight list-panel" aria-label="Claims">
        <div class="panel-head"><h2 class="h2">Claims</h2><span class="small muted" id="shown"></span></div>
        <div class="segmented fill" id="cl-filter" role="group" aria-label="Filter claims">
          ${[["all", "All"], ["needs", "Needs a look"], ["blocking", "Blocking"]].map(([k, l]) => `<button type="button" data-f="${k}" aria-pressed="${k === "all"}">${l}</button>`).join("")}
        </div>
        <div id="cl-list" class="scroll-list"></div>
      </section>
      <section class="panel detail-panel" id="cl-detail" aria-live="polite"></section>
    </div>
    <section class="panel bottom-bar">
      <div class="grow">
        <div class="eyebrow">Automatic checks · ${fails} fail${fails === 1 ? "" : "s"}</div>
        <div class="chips">${(d.checks || []).map((c) => `<span class="chip-check ${c.passed ? "ok" : "bad"}" title="${esc(c.detail)}">${checkMark(c.passed, "sm")}${esc(c.label)}</span>`).join("") || '<span class="muted small">No check results.</span>'}</div>
        ${(d.risks || []).length ? `<details class="risks"><summary>Accepted risks (${d.risks.length})</summary>${d.risks.map((k) => `<div class="small"><span class="mono">${esc(k.message_id)}</span> ${esc(k.text)} · accepted by ${esc(k.accepted_by)} · slides ${(k.slide_ids || []).map(esc).join(", ")}</div>`).join("")}</details>` : ""}
      </div>
      <div class="bottom-act">
        <div id="act-note" hidden></div>
        ${approved
          ? `<div class="note ok">${ICON.info}<span>${approvalLine(d.approval)}. <a href="${runHref(runId)}">Open the run</a></span></div>`
          : `<button class="btn block" id="approve" type="button">Approve &amp; proceed</button>
             <div class="small ${fails ? "t-warn" : "muted"}">${fails ? `${fails} check${fails === 1 ? "" : "s"} fail. You can still approve after reading ${fails === 1 ? "it" : "them"}; you cannot skip seeing ${fails === 1 ? "it" : "them"}.` : "Approves every claim shown, with its quote."}${d.approval?.detail && d.approval.state !== "pending" ? " " + esc(d.approval.detail) : ""}</div>`}
      </div>
    </section>`;

  const listEl = document.getElementById("cl-list");
  const detailEl = document.getElementById("cl-detail");
  const shown = () => claims.filter((c) => state.filter === "all" || (state.filter === "needs" ? c.verdict !== "supported" : c.blocking));

  const paintList = () => {
    const rows = shown();
    document.getElementById("shown").textContent = `${rows.length} shown`;
    const bySlide = [];
    rows.forEach((c) => {
      let g = bySlide.find((x) => x.slide === c.slide_id);
      if (!g) { g = { slide: c.slide_id, n: c.slide_n, role: c.role, rows: [] }; bySlide.push(g); }
      g.rows.push(c);
    });
    listEl.innerHTML = bySlide.map((g) => `
      <div class="group-title">SLIDE ${esc(String(g.n ?? g.slide).toUpperCase())} · ${esc(g.role)}</div>
      ${g.rows.map((c) => `
        <button type="button" class="claim-row ${c.id === state.sel ? "on" : ""}" data-id="${esc(c.id)}" aria-pressed="${c.id === state.sel}">
          <span class="claim-top"><span class="mono muted">${esc(c.id)}</span>${state.queue.has(c.id) ? '<span class="badge warn">queued</span>' : ""}${vChip(c.verdict)}</span>
          <span class="clamp-2">${esc(c.text)}</span>
        </button>`).join("")}`).join("") || '<div class="empty">Nothing matches this filter.</div>';
  };

  const paintDetail = () => {
    const c = claims.find((x) => x.id === state.sel);
    if (!c) { detailEl.innerHTML = '<div class="empty">Select a claim.</div>'; return; }
    const earlier = (d.send_backs || []).filter((s) => s.claim_id === c.id);
    const queued = state.queue.get(c.id);
    detailEl.innerHTML = `
      <div class="panel-head top">
        <div class="stack gap-2"><div class="strong small-13">Slide ${esc(c.slide_n)} · ${esc(c.role)} · ${esc(c.component)}</div><div class="small muted">Intent: ${esc(c.intent)}</div></div>
        <span class="badge v-${VERDICT_KIND[c.verdict] || "neutral"} lg"><span class="dot"></span><span class="mono">${esc(c.id)}</span> · ${esc(c.verdict)}</span>
      </div>
      <div class="kv"><div class="eyebrow">The sentence</div><div class="claim-text">${esc(c.text)}</div></div>
      <div class="kv"><div class="eyebrow">The quote${(c.citations || []).length > 1 ? "s" : ""}</div>
        ${(c.citations || []).map((q) => `
          <blockquote class="quote"><div class="quote-text">${esc(q.quote)}</div>
          <div class="small muted">${esc(docLabel(q.doc_id, q.page))} · p.${esc(q.page)}${q.retrieved_by ? " · retrieved by " + esc(q.retrieved_by) : ""}${q.sha256 ? ` · sha256 <span class="mono">${esc(String(q.sha256).slice(0, 8))}…</span>` : ""}</div></blockquote>`).join("")
          || '<div class="note warn">' + ICON.warn + '<span>This claim has no quote attached.</span></div>'}
      </div>
      ${(c.contradicting || []).length ? `<div class="kv"><div class="eyebrow">Contradicting passages</div>${c.contradicting.map((q) => `<blockquote class="quote bad"><div class="quote-text">${esc(q.quote)}</div><div class="small muted">${esc(q.doc_id)} · p.${esc(q.page)}</div></blockquote>`).join("")}</div>` : ""}
      <div class="kv"><div class="row gap-8 baseline"><div class="eyebrow">Validator notes</div><span class="small muted">a model's opinion</span></div><div class="small-13">${esc(c.notes || "No notes.")}</div></div>
      <div class="note warn">${ICON.warn}<span><b>The one question: does the quote say what the sentence says?</b> Look for a changed number or unit, a dropped condition, someone else's result, 'always' for 'in our experiments', a different quantity.</span></div>
      ${earlier.length ? `<div class="small muted">${earlier.map((s) => `Sent back earlier: “${esc(s.reason)}” by ${esc(s.by)}${s.at ? " · " + esc(fmtTime(s.at)) : ""}`).join("<br>")}</div>` : ""}
      <div class="send-box">
        <label class="field" for="why">What is wrong with this claim
          <textarea class="textarea short" id="why" rows="2" placeholder="Say what to change. The writer sees this note.">${esc(state.drafts[c.id] ?? queued ?? "")}</textarea>
        </label>
        <div class="row end gap-10">
          ${queued !== undefined ? '<button type="button" class="btn btn-quiet" id="unqueue">Remove from list</button>' : ""}
          <button type="button" class="btn btn-danger" id="queue">${queued !== undefined ? "Update note" : "Add to send-back list"}</button>
        </div>
        <div class="small muted">Sending back is the only way to reject a claim. Notes are collected below, then sent together.</div>
      </div>`;
    const why = document.getElementById("why");
    why.addEventListener("input", () => { state.drafts[c.id] = why.value; });
    document.getElementById("queue").addEventListener("click", () => {
      const reason = why.value.trim();
      if (!reason) { toast("Write what is wrong first.", true); return; }
      state.queue.set(c.id, reason);
      delete state.drafts[c.id];
      state.sent = false;
      paintList(); paintDetail(); paintQueue();
    });
    const un = document.getElementById("unqueue");
    if (un) un.addEventListener("click", () => { state.queue.delete(c.id); paintList(); paintDetail(); paintQueue(); });
  };

  // The send-back list lives in its own panel under the split so typing never loses focus.
  const queueEl = document.createElement("section");
  queueEl.className = "panel";
  queueEl.id = "cl-queue";
  queueEl.hidden = true;
  view.querySelector(".split").after(queueEl);

  const paintQueue = () => {
    const items = [...state.queue.entries()];
    queueEl.hidden = !items.length && !state.sent;
    if (state.sent) {
      queueEl.innerHTML = `
        <div class="row between wrap">
          <div><h2 class="h2">Sent back</h2><div class="small muted">${state.sent} claim${state.sent === 1 ? "" : "s"} recorded. Nothing is approved. Rewrite the claims to apply your notes.</div></div>
          <button class="btn" id="rewrite" type="button">Rewrite claims</button>
        </div>
        <div id="rewrite-note" hidden></div>`;
      document.getElementById("rewrite").addEventListener("click", async (e) => {
        e.target.disabled = true;
        try {
          await api(`/api/runs/${enc(runId)}/run`, { stage: "content" });
          location.hash = runHref(runId);
        } catch (err) {
          e.target.disabled = false;
          actionError(document.getElementById("rewrite-note"), err, runId);
        }
      });
      return;
    }
    queueEl.innerHTML = `
      <div class="row between wrap"><h2 class="h2">Send-back list (${items.length})</h2>
        <button class="btn btn-danger" id="send-back" type="button">Send back ${items.length} claim${items.length === 1 ? "" : "s"}</button></div>
      ${items.map(([id, reason]) => `<div class="check"><div class="check-body"><div class="check-name mono">${esc(id)}</div><div class="check-note">${esc(reason)}</div></div><button type="button" class="btn btn-pill" data-rm="${esc(id)}">Remove</button></div>`).join("")}
      <div id="sb-note" hidden></div>`;
    queueEl.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => {
      state.queue.delete(b.dataset.rm); paintList(); paintDetail(); paintQueue();
    }));
    document.getElementById("send-back").addEventListener("click", async (e) => {
      e.target.disabled = true;
      const payload = [...state.queue.entries()].map(([claim_id, reason]) => ({ claim_id, reason }));
      try {
        const res = await api(`/api/runs/${enc(runId)}/send-back`, { items: payload });
        state.sent = (res.sent || payload).length;
        state.queue.clear();
        toast("Sent back. Nothing was approved.");
        paintList(); paintDetail(); paintQueue();
      } catch (err) {
        e.target.disabled = false;
        actionError(document.getElementById("sb-note"), err, runId);
      }
    });
  };

  paintList(); paintDetail(); paintQueue();
  listEl.addEventListener("click", (e) => {
    const b = e.target.closest("[data-id]");
    if (b) { state.sel = b.dataset.id; paintList(); paintDetail(); }
  });
  document.getElementById("cl-filter").addEventListener("click", (e) => {
    const b = e.target.closest("[data-f]");
    if (!b) return;
    state.filter = b.dataset.f;
    document.querySelectorAll("#cl-filter button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    paintList();
  });

  const approve = document.getElementById("approve");
  if (approve) approve.addEventListener("click", async () => {
    approve.disabled = true;
    try {
      await api(`/api/runs/${enc(runId)}/approve`, { gate: "claims" });
      toast("Claims approved. Rendering the deck.");
      location.hash = runHref(runId);
    } catch (err) {
      approve.disabled = false;
      actionError(document.getElementById("act-note"), err, runId);
    }
  });
}

// ---- final deck -------------------------------------------------------------

async function finalView(runId) {
  setNav("runs");
  const [d, r] = await Promise.all([api(`/api/runs/${enc(runId)}/final`), runSummary(runId)]);
  const previews = d.previews || [];
  const checks = d.human_checks || [];
  const ticks = new Set();
  let sel = 0;
  const approved = !!d.approval?.approved;
  const crit = d.critique || {};
  const failing = (d.criteria || []).filter((c) => !c.passed).length;

  view.innerHTML = `
    ${runHeader(runId, r, "final", "Final deck", "Check it in PowerPoint on a copy, then approve.")}
    <div class="split final">
      <section class="panel viewer">
        <div class="row between wrap">
          <div class="small-13 strong t-2">deck.pptx · ${previews.length || "no"} slide preview${previews.length === 1 ? "" : "s"}${crit.score != null ? ` · critique score ${esc(crit.score)}/10${crit.looks != null ? ` after ${esc(crit.looks)} look${crit.looks === 1 ? "" : "s"}` : ""}` : ""}</div>
          <button class="btn btn-pill" id="open-copy" type="button">Open a copy in PowerPoint</button>
        </div>
        <div class="stage" id="stage"></div>
        <div class="small muted center" id="caption"></div>
        <div class="film" id="film"></div>
        <div id="copy-note" hidden></div>
      </section>
      <div class="stack gap-12 side-col">
        <section class="panel tight">
          <div class="panel-head"><h2 class="h3">Machine checks</h2><span class="small strong ${failing ? "t-warn" : "t-ok"}">${(d.criteria || []).length - failing} of ${(d.criteria || []).length} pass</span></div>
          ${(d.criteria || []).map((c) => `
            <div class="check">${checkMark(c.passed, "sm")}<div class="check-body"><div class="check-name small-13">${esc(c.label)}</div>${c.detail ? `<div class="check-note">${esc(c.detail)}</div>` : ""}</div></div>`).join("") || '<div class="small muted">No criteria reported.</div>'}
          ${(d.findings || []).length ? `<details class="risks"><summary>${d.findings.length} finding${d.findings.length === 1 ? "" : "s"}</summary>${d.findings.map((f) => `<div class="small"><span class="badge">${esc(f.section)}</span> ${esc(f.text)}</div>`).join("")}</details>` : ""}
        </section>
        <section class="panel tight">
          <div class="panel-head"><h2 class="h3">Your five checks in PowerPoint</h2><span class="small strong t-warn" id="tick-count"></span></div>
          ${checks.map((k, i) => `
            <div class="tick">
              <input type="checkbox" id="hc-${i}" data-i="${i}">
              <label for="hc-${i}"><span class="muted">${esc(k.n)}.</span> ${esc(k.title)}</label>
              ${k.steps ? `<details class="steps-detail"><summary class="small">Steps</summary><div class="small muted pre">${esc(k.steps)}</div></details>` : ""}
            </div>`).join("") || '<div class="small muted">The server listed no PowerPoint checks.</div>'}
          <div class="small muted">Do them on a copy. Saving from PowerPoint changes deck.pptx and voids your approval. Nothing in the code ticks these; the boxes only record what you did.</div>
        </section>
        <section class="panel tight">
          <div id="act-note" hidden></div>
          ${approved
            ? `<div class="note ok">${ICON.info}<span>${approvalLine(d.approval)}. <a href="${runHref(runId)}">Open the run</a></span></div>`
            : `<button class="btn block" id="approve" type="button" disabled>Approve final deck</button>
               <div class="small muted" id="approve-note"></div>`}
          <div class="small muted">Records deck digest <span class="mono">${esc(String(d.digest || "").slice(0, 12) || "—")}${d.digest ? "…" : ""}</span></div>
        </section>
        ${(d.header_flow || []).length ? `<details class="panel tight"><summary class="strong small-13">Header flow</summary>
          <div class="stack gap-2 pt-6">${d.header_flow.map((h) => `<div class="small-13"><span class="mono muted">${esc(h.slide_id)}</span> ${esc(h.text)}${h.kind ? ` <span class="muted small">(${esc(h.kind)})</span>` : ""}</div>`).join("")}
          ${(d.header_notes || []).map((n) => `<div class="small muted">${esc(n)}</div>`).join("")}
          <div class="small muted">Read top to bottom: does the argument hold without the rest of the slide?</div></div></details>` : ""}
      </div>
    </div>`;

  const stage = document.getElementById("stage");
  const film = document.getElementById("film");
  const paintViewer = () => {
    const p = previews[sel];
    stage.innerHTML = p
      ? `<img class="slide-img" src="${esc(p.url)}" alt="Slide ${esc(p.n)} preview">`
      : '<div class="empty">No slide previews were rendered for this deck.</div>';
    document.getElementById("caption").textContent = p ? `Slide ${p.n} · ${p.slide_id}` : "";
    film.innerHTML = previews.map((q, i) => `
      <button type="button" class="thumb ${i === sel ? "on" : ""}" data-i="${i}" aria-pressed="${i === sel}" aria-label="Slide ${esc(q.n)}, ${esc(q.slide_id)}">
        <img src="${esc(q.url)}" alt="" loading="lazy"><span class="small mono">${esc(q.slide_id)}</span>
      </button>`).join("");
  };
  paintViewer();
  film.addEventListener("click", (e) => {
    const b = e.target.closest("[data-i]");
    if (b) { sel = Number(b.dataset.i); paintViewer(); }
  });

  const approve = document.getElementById("approve");
  const updateApprove = () => {
    document.getElementById("tick-count").textContent = `${ticks.size} of ${checks.length || 5}`;
    if (!approve) return;
    const allTicked = checks.length > 0 && ticks.size === checks.length;
    approve.disabled = !(allTicked && d.passes);
    document.getElementById("approve-note").textContent = !d.passes
      ? "The final audit has not passed. Fix the failing checks first."
      : allTicked ? "All five ticked." : "Tick all five checks to approve.";
  };
  updateApprove();
  view.onchange = (e) => {
    const box = e.target.closest("[data-i][type=checkbox]");
    if (!box) return;
    if (box.checked) ticks.add(box.dataset.i); else ticks.delete(box.dataset.i);
    updateApprove();
  };

  document.getElementById("open-copy").addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      const res = await api(`/api/runs/${enc(runId)}/open-copy`, {});
      toast(`Opened a copy: ${res.path}`);
    } catch (err) {
      actionError(document.getElementById("copy-note"), err, runId);
    } finally { e.target.disabled = false; }
  });

  if (approve) approve.addEventListener("click", async () => {
    approve.disabled = true;
    try {
      await api(`/api/runs/${enc(runId)}/approve`, { gate: "final_render" });
      toast("Final deck approved.");
      location.hash = runHref(runId);
    } catch (err) {
      actionError(document.getElementById("act-note"), err, runId);
      updateApprove();
    }
  });
}

// ---- run (job progress) -----------------------------------------------------

let pollTimer = null;
function stopPolling() { clearInterval(pollTimer); pollTimer = null; }

const STAGE_MARK = { done: "✓", failed: "!", running: "", waiting: "", yours: "", locked: "" };
const STAGE_TAG = { running: "Running", yours: "Yours", failed: "Failed" };
const START_BTN = {
  outline: ["outline", "Build the outline"],
  content: ["content", "Write the slides"],
  validate: ["content", "Write slides and validate"],
  render: ["render", "Render and audit"],
  final_audit: ["render", "Render and audit"],
};

// Which button, if any, starts the next chain: the first stage that is not done.
function nextAction(list, jobRunning) {
  if (jobRunning) return null;
  const first = list.find((s) => s.status !== "done");
  if (!first) return null;
  if (first.status === "yours") return { kind: "review", href: first.screen, label: `Review: ${first.label}` };
  if ((first.status === "waiting" || first.status === "failed" || first.status === "running") && START_BTN[first.key]) {
    return { kind: "start", stage: START_BTN[first.key][0], label: first.status === "failed" ? `Retry: ${START_BTN[first.key][1]}` : START_BTN[first.key][1] };
  }
  return null;
}

async function runView(runId) {
  setNav("runs");
  const r = await api(`/api/runs/${enc(runId)}`);
  if (isDraftRun(r) && showAssembling(r)) { await assemblingView(runId, r); return; }
  const list = r.stage_list || [];
  const job = r.job || null;
  const running = job?.status === "running";
  const yours = list.find((s) => s.status === "yours");
  const sub = running ? "The pipeline is working. It will stop and wait for you at the next approval."
    : yours ? `Waiting on you: ${yours.label}.` : r.next || "";
  const action = nextAction(list, running);

  view.innerHTML = `
    ${runHeader(runId, r, "", runId, sub)}
    <div class="grid-2 run-grid">
      <section class="panel">
        <div class="row between wrap">
          <h2 class="h2">Pipeline</h2>
          <div class="row gap-12">
            ${running ? '<button class="btn btn-quiet-accent" id="stop" type="button">Stop</button>' : ""}
            ${action?.kind === "start" ? `<button class="btn" id="start" type="button">${esc(action.label)}</button>` : ""}
            ${action?.kind === "review" ? `<a class="btn" href="${screenHref(action.href, runId)}">${esc(action.label)}</a>` : ""}
          </div>
        </div>
        <div id="act-note" hidden></div>
        <div class="timeline">
          ${list.map((s) => `
            <div class="tl-row">
              <span class="tl-mark st-${esc(s.status)}" aria-hidden="true">${STAGE_MARK[s.status] || ""}</span>
              <div class="tl-body">
                <div class="row gap-8"><span class="tl-name st-${esc(s.status)}">${esc(s.label)}</span>${STAGE_TAG[s.status] ? `<span class="tag tag-${esc(s.status)}">${STAGE_TAG[s.status]}</span>` : ""}<span class="sr-only">${esc(s.status)}</span></div>
                <div class="small-13 muted">${esc(s.detail || "")}${s.finished_at ? ` · ${esc(fmtTime(s.finished_at))}` : ""}</div>
                ${s.status === "running" ? '<div class="bar"><i></i></div><div class="small muted">Each reply is saved as it arrives.</div>' : ""}
              </div>
              ${s.screen && s.status !== "locked" ? `<a class="small-13 strong" href="${screenHref(s.screen, runId)}">View</a>` : ""}
            </div>`).join("") || `<div class="empty">${esc(r.next || "No stage information yet.")}</div>`}
        </div>
        <div id="job-box"></div>
        ${(r.env || "").startsWith("dev") ? `<div class="note warn">${ICON.warn}<span><b>Draft models:</b> a draft model can hit its request limit. If it does, run the same step again later; finished slides are kept. <a href="#/settings/models">Switch models</a></span></div>` : ""}
      </section>
      <div class="stack gap-14">
        <section class="panel tight">
          <h2 class="h3">This run</h2>
          <div class="kvrow"><span class="muted">Client</span><span>${esc(r.client || "—")}</span></div>
          <div class="kvrow"><span class="muted">Project</span><span>${esc(r.project || "—")}</span></div>
          <div class="kvrow"><span class="muted">Environment</span><span><span class="dot ${(r.env || "").startsWith("dev") ? "dot-warn" : "dot-ok"}"></span> ${esc(ENV_WORD[r.env] || r.env || "—")}${r.env ? ` (${esc(r.env)})` : ""}</span></div>
          ${(r.env || "").startsWith("dev") ? '<div class="small t-warn text-right">Draft, never a client deliverable</div>' : ""}
        </section>
        <section class="panel tight">
          <h2 class="h3">Approvals</h2>
          ${(r.gates || []).map((g) => `
            <div class="appr"><span class="dot ${g.approved ? "dot-ok" : "hollow"}"></span>
              <span class="appr-name">${esc(g.label)}</span>
              <span class="grow ${g.approved ? "" : "muted"}">${g.approved ? `${esc(g.by || "—")}${g.at ? " · " + esc(g.at) : ""}` : esc(g.state === "stale" || /not current/i.test(g.detail || "") ? "Not current" : "Pending")}</span></div>`).join("")}
        </section>
        ${r.command_hint ? `<div class="note">${ICON.info}<span>From a terminal: <span class="mono">${esc(r.command_hint)}</span></span></div>` : ""}
      </div>
    </div>`;

  const start = document.getElementById("start");
  if (start) start.addEventListener("click", async () => {
    start.disabled = true;
    try {
      await api(`/api/runs/${enc(runId)}/run`, { stage: action.stage });
      route();
    } catch (err) {
      start.disabled = false;
      actionError(document.getElementById("act-note"), err, runId);
    }
  });
  const stop = document.getElementById("stop");
  if (stop) stop.addEventListener("click", async () => {
    stop.disabled = true;
    try {
      await api(`/api/runs/${enc(runId)}/stop`, {});
      route();
    } catch (err) { stop.disabled = false; toast(err.message, true); }
  });

  const paintJob = (j) => {
    const box = document.getElementById("job-box");
    if (!box) return;
    if (!j) { box.innerHTML = ""; return; }
    const kind = j.status === "failed" ? "bad" : j.status === "running" ? "accent" : j.status === "stopped" ? "warn" : "ok";
    const lines = (j.log || []).slice(-60);
    box.innerHTML = `
      <div class="job-head">
        <span class="badge ${kind}">${esc(j.status)}</span>
        <span class="small muted">${esc((j.steps || []).join(" → "))}${j.step ? ` · now ${esc(j.step)}` : ""}${j.exit_code != null ? ` · exit ${esc(j.exit_code)}` : ""}${j.finished_at ? ` · ${esc(fmtTime(j.finished_at))}` : ""}</span>
      </div>
      ${j.message ? `<div class="small-13">${esc(j.message)}</div>` : ""}
      <pre class="log" id="log" tabindex="0" aria-label="Job log">${esc(lines.join("\n") || "No output yet.")}</pre>`;
    const log = document.getElementById("log");
    if (log) log.scrollTop = log.scrollHeight;
  };
  paintJob(job);

  if (running) {
    stopPolling();
    pollTimer = setInterval(async () => {
      if (!location.hash.startsWith(`#/run/${enc(runId)}`)) { stopPolling(); return; }
      try {
        const res = await api(`/api/runs/${enc(runId)}/job`);
        if (res.job && res.job.status === "running") paintJob(res.job);
        else { stopPolling(); route(); }
      } catch { /* keep polling; the server may be busy */ }
    }, 1500);
  }
}

// ---- knowledge --------------------------------------------------------------

async function knowledgeView() {
  setNav("knowledge");
  const data = await api("/api/knowledge");
  const projects = data.projects || [];
  const clients = data.clients || [];
  const state = { tab: "projects", proj: projects[0]?.name, client: clients[0]?.name };
  view.innerHTML = `
    <div class="page-head"><div>
      <h1 class="page-title">Knowledge</h1>
      <p class="page-sub">Research is shared by project. Client notes stay with their client.</p>
    </div></div>
    <div class="segmented" id="k-tabs" role="tablist" aria-label="Knowledge">
      <button type="button" role="tab" data-tab="projects">Projects</button>
      <button type="button" role="tab" data-tab="clients">Clients</button>
    </div>
    <div class="k-grid"><section class="panel tight self-start" id="k-list"></section><section class="panel" id="k-detail"></section></div>`;
  const listEl = document.getElementById("k-list");
  const detailEl = document.getElementById("k-detail");

  const paint = () => {
    const isP = state.tab === "projects";
    document.querySelectorAll("#k-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
    const items = isP ? projects : clients;
    const selName = isP ? state.proj : state.client;
    listEl.innerHTML = `<div class="eyebrow pad-s">${isP ? "PROJECTS" : "CLIENTS"}</div>` + (items.map((it) => {
      const meta = isP
        ? `${(it.papers || []).length} paper${(it.papers || []).length === 1 ? "" : "s"} · ${it.ingested ? "indexed" : "not indexed"}`
        : `${it.past_decks ?? 0} past deck${it.past_decks === 1 ? "" : "s"}`;
      return `<button type="button" class="list-btn ${it.name === selName ? "on" : ""}" data-name="${esc(it.name)}" aria-pressed="${it.name === selName}"><span class="strong">${esc(it.name)}</span><span class="small muted">${esc(meta)}</span></button>`;
    }).join("") || `<div class="small muted pad-s">None yet.</div>`);
    const cur = items.find((it) => it.name === selName);
    if (!cur) { detailEl.innerHTML = '<div class="empty">Nothing to show yet.</div>'; return; }
    if (isP) {
      detailEl.innerHTML = `
        <div class="row between"><div><h2 class="h1-20">${esc(cur.name)}</h2><div class="small-13 muted">Document store: ${cur.ingested ? "indexed" : "not indexed yet"}</div></div>
          <button class="btn btn-outline" type="button" disabled title="Not available yet">Re-index · Not available yet</button></div>
        <div>
          <div class="papers head"><div>Papers</div><div>Pages</div><div>Status</div></div>
          ${(cur.papers || []).map((p) => `
            <div class="papers row"><div class="mono ellipsis">${esc(p.doc_id)}</div><div class="small-13">${p.pages != null ? esc(p.pages) + " pp." : "—"}</div>
            <div><span class="badge ${p.ingested ? "ok" : "warn"}"><span class="dot"></span>${p.ingested ? "Indexed" : "Not indexed"}</span></div></div>`).join("") || '<div class="empty">No papers yet.</div>'}
        </div>
        ${cur.claims_md ? `<div class="note">${ICON.doc}<span><span class="mono strong">claims.md</span> · ${cur.curated_claims != null ? esc(cur.curated_claims) : "some"} hand-checked claims · a single curated claim is never capped</span></div>` : ""}
        <button class="dropzone wide" type="button" disabled title="Not available yet">${ICON.upload}Add papers (PDF) · Not available yet</button>
        <div class="small muted">Put PDFs in <span class="mono">knowledge/projects/${esc(cur.name)}/papers/</span>; the file name becomes the document id cited on every slide.</div>
        <div class="note">${ICON.info}<span>Papers are evidence. Past decks and positioning language never are.</span></div>`;
    } else {
      detailEl.innerHTML = `
        <div class="row between"><h2 class="h1-20">${esc(cur.name)}</h2><span class="muted small">Edit the files in knowledge/clients/${esc(cur.name)}</span></div>
        <div class="kv rule"><div class="eyebrow">CLIENT.MD</div><div>${esc(cur.summary || "—")}</div></div>
        <div class="kv rule"><div class="eyebrow">POSITIONING LANGUAGE (VALUE_PROP.MD)</div><div>${esc(cur.positioning || "—")}</div><div class="small strong t-warn">framing, never fact</div></div>
        <div class="kv rule"><div class="eyebrow">BRAND</div><div>${cur.has_template ? "Corporate template present" : "No corporate template"}${cur.theme ? ` · theme ${esc(cur.theme)}` : ""}</div></div>
        <div class="grid-even">
          <div class="kv rule"><div class="eyebrow">PAST DECKS</div><div>${esc(cur.past_decks ?? 0)} deck${cur.past_decks === 1 ? "" : "s"}</div></div>
          <div class="kv rule"><div class="eyebrow">ENGAGEMENT NOTES</div><div>${esc(cur.engagement_notes ?? 0)} note${cur.engagement_notes === 1 ? "" : "s"}</div></div>
        </div>
        <div class="note">${ICON.info}<span>Isolated: nothing here reaches another client's builds.</span></div>
        <div class="row-end"><a class="btn btn-outline" href="#/clients/new">New client</a></div>`;
    }
  };
  paint();
  document.getElementById("k-tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]");
    if (b) { state.tab = b.dataset.tab; paint(); }
  });
  listEl.addEventListener("click", (e) => {
    const b = e.target.closest("[data-name]");
    if (!b) return;
    state[state.tab === "projects" ? "proj" : "client"] = b.dataset.name;
    paint();
  });
}

async function newClientView() {
  setNav("clients");
  const data = await api("/api/clients");
  view.innerHTML = `
    <div class="page-head"><div>
      <h1 class="page-title">New client</h1>
      <p class="page-sub">A private space for one client. Its notes, brand and past decks never reach another client's builds.</p>
    </div></div>
    <form id="client-form" class="stack">
      <div class="grid-even">
        <div class="stack">
          <section class="panel">
            <div class="panel-head"><h2 class="h2">About the client</h2><span class="small muted">Required</span></div>
            <label class="field">Name
              <input class="input" name="name" required pattern="[a-z0-9][a-z0-9-]*" placeholder="e.g. fabrikam-energy">
              <span class="field-hint">Lower case, numbers and dashes. Folder: knowledge/clients/&lt;name&gt;</span>
            </label>
            <label class="field">Who they are and what they care about
              <textarea class="textarea" name="client_md" required placeholder="Who the client is, their priorities, their audience."></textarea>
            </label>
          </section>
          <section class="panel">
            <div class="panel-head"><h2 class="h2">Positioning language</h2><span class="small muted">Required</span></div>
            <label class="field">How the client wants to be described
              <textarea class="textarea" name="value_prop_md" id="value-prop" required placeholder="Value proposition and messaging, in words, without figures."></textarea>
            </label>
            <div class="note warn">${ICON.info}<span>This is treated as framing, never as fact. Lines with numbers, named studies or claims like "proven" are flagged below and would need a source.</span></div>
            <div class="lint" id="lint" aria-live="polite"></div>
          </section>
        </div>
        <div class="stack">
          <section class="panel">
            <div class="panel-head"><h2 class="h2">Brand</h2><span class="small muted">Optional · add files to the client folder</span></div>
            <div class="grid-even" style="gap:12px">
              <div class="dropzone" aria-disabled="true">${ICON.upload}Corporate template<span class="field-hint">theme/template.pptx</span></div>
              <div class="dropzone" aria-disabled="true">${ICON.upload}Colours and fonts<span class="field-hint">theme/tokens.json</span></div>
            </div>
          </section>
          <section class="panel">
            <div class="panel-head"><h2 class="h2">Past decks</h2><span class="small muted">Optional</span></div>
            <div class="dropzone" aria-disabled="true">${ICON.upload}Decks this client liked<span class="field-hint">decks/ · read for tone and structure only, never as evidence</span></div>
          </section>
          <section class="panel" style="gap:8px">
            <h2 class="h2">Existing clients</h2>
            <div class="muted">${data.clients.map(esc).join(", ") || "None yet"}</div>
          </section>
        </div>
      </div>
      <div class="row-end">
        <span class="muted" style="flex-grow:1;font-size:13px">You can edit these files later. Projects are chosen per deck, not per client.</span>
        <a class="btn btn-quiet" href="#/">Cancel</a>
        <button class="btn" type="submit">Create client</button>
      </div>
    </form>`;

  const valueProp = document.getElementById("value-prop");
  const lintBox = document.getElementById("lint");
  let lintTimer;
  valueProp.addEventListener("input", () => {
    clearTimeout(lintTimer);
    lintTimer = setTimeout(async () => {
      try {
        const res = await api("/api/lint/framing", { text: valueProp.value });
        lintBox.innerHTML = res.findings.map((f) =>
          `<div class="lint-item"><strong>${esc(f.reason)}</strong> · ${esc(f.excerpt)}</div>`
        ).join("");
      } catch { lintBox.innerHTML = ""; }
    }, 350);
  });

  document.getElementById("client-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(event.target).entries());
    try {
      const res = await api("/api/clients", body);
      toast(`Created ${res.name}.`);
      location.hash = "#/";
    } catch (err) {
      toast(err.message, true);
    }
  });
}

function redesignView() {
  setNav("home");
  view.innerHTML = `
    <div class="page-head"><div>
      <h1 class="page-title">Redesign a deck</h1>
      <p class="page-sub">Keep your story. AutoDeck rebuilds each slide in the client's brand and picks a better layout where one helps.</p>
    </div></div>
    <section class="panel">
      <div class="dropzone" aria-disabled="true" style="min-height:180px">${ICON.upload}Drop a .pptx<span class="field-hint">Your deck becomes the source: every statement cites the slide it came from.</span></div>
      <div class="note warn">${ICON.info}<span>Not built yet. The pipeline cannot read an existing deck today; the rule it will follow is recorded as decision B41.</span></div>
    </section>
    <div class="row-end"><a class="btn btn-quiet" href="#/">Back</a></div>`;
}


// ---- settings ---------------------------------------------------------------

const ROLE_LABEL = {
  planner: "Planner", outline: "Outline", content: "Slide writing", validation: "Claim validation",
  aesthetic: "Art direction", ingest_vlm: "Reading slides (images)",
};
const ENV_BLURB = {
  sit: "The models production uses, for checking accuracy before a real deck.",
  prod: "For real client deliverables.",
};

const asList = (x) => (Array.isArray(x) ? x : Array.isArray(x?.keys) ? x.keys : Array.isArray(x?.checks) ? x.checks : Array.isArray(x?.items) ? x.items : []);

const SETTINGS_TABS = [["profile", "Profile"], ["models", "Models"], ["project", "Project"], ["memory", "Memory"], ["system", "Keys and rendering"]];
const PROVENANCE_BLURB = {
  normal: "Normal: facts are checked against your papers, and the deck may also use what you told us and the model's general knowledge. Each is labelled.",
  strict: "Strict (MLR): every statement must quote your papers. Nothing you typed and no general knowledge reaches the deck.",
};
const DESIGN_LABEL = { structured: "Structured (catalog layouts)", creative: "Creative (writer designs each slide)" };
const DESIGN_BLURB = {
  structured: "Each slide uses a layout from the catalog. Safest for smaller models.",
  creative: "The writer places every element of every slide. Stronger models do this best.",
};
const PROVENANCE_LABEL = { normal: "Normal", strict: "Strict (MLR)" };

// A small "Design: Structured" chip next to the provenance chip, reusing its styling.
function designChip(mode) {
  if (!mode) return "";
  return `<span class="chip" title="${esc(DESIGN_BLURB[mode] || "")}">Design: ${esc(mode === "creative" ? "Creative" : "Structured")}</span>`;
}

// A small "Provenance: Normal" chip; the run's own mode once a draft exists.
function provenanceChip(mode) {
  if (!mode) return "";
  return `<span class="chip" title="${esc(PROVENANCE_BLURB[mode] || "")}"><span class="dot ${mode === "strict" ? "dot-ok" : "dot-warn"}"></span>Provenance: ${esc(PROVENANCE_LABEL[mode] || mode)}</span>`;
}
const PROFILE_SOURCE = { saved: "saved here", git: "taken from git config until you save one", system: "taken from this computer's user name until you save one" };

function initials(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}

async function settingsView(tab = "profile") {
  setNav("settings");
  if (!SETTINGS_TABS.some(([k]) => k === tab)) tab = "profile";
  const data = await api("/api/settings");
  const profile = data.profile || { name: "", source: "" };
  const keys = asList(data.keys);
  const rendering = asList(data.rendering);
  const env = data.env;

  const profilePage = `
    <div class="grid-2 settings align-start">
      <section class="panel">
        <div class="profile-head">
          <div class="avatar" aria-hidden="true">${esc(initials(profile.name))}</div>
          <div class="stack gap-2">
            <h2 class="h2">${esc(profile.name || "No name yet")}</h2>
            <div class="small muted">${esc(PROFILE_SOURCE[profile.source] || "")}</div>
          </div>
        </div>
        <form id="profile-form" class="stack gap-10">
          <label class="field">Your name
            <input class="input" name="name" required maxlength="80" value="${esc(profile.name)}" autocomplete="name">
            <span class="field-hint">This is the name every approval you give is recorded under, beside a fingerprint of what you approved.</span>
          </label>
          <div class="row-end"><button class="btn" type="submit">Save</button></div>
        </form>
      </section>
      <section class="panel tight">
        <h2 class="h2">How approvals work</h2>
        <div class="note">${ICON.lock}<span>There is no setting that approves a gate. An approval is you clicking Approve on a screen you have reviewed.</span></div>
        <div class="small-13">Approving the brief, the outline, the claims or the final deck records this name and the date. If what you approved changes later, the approval stops counting and the run asks you again.</div>
        <div class="small-13 muted">Stored on this computer only, in your home folder, not in the project.</div>
      </section>
    </div>`;

  const modelsPage = `
    <section class="panel">
      <h2 class="h2">Models</h2>
      <div class="envs" role="radiogroup" aria-label="Model environment">
        ${data.envs.map((e) => `
          <button type="button" role="radio" class="envcard ${e.name === env.name ? "on" : ""}" aria-checked="${e.name === env.name}" data-env="${esc(e.name)}">
            <span class="row between"><span class="strong">${esc(e.label)}</span><span class="mono muted small">${esc(e.name)}</span></span>
            <span class="small-13">${esc(e.note || ENV_BLURB[e.name] || "")}</span>
            ${e.name.startsWith("dev") ? '<span class="badge warn self-start">Daily request limits</span>' : ""}
          </button>`).join("")}
      </div>
      <div class="note ${env.name.startsWith("dev") ? "warn" : ""}">${ICON.info}<span>${esc(env.note)}</span></div>
      ${(env.missing_credentials || []).length ? `<div class="note bad">${ICON.info}<span>Missing keys: <span class="mono">${env.missing_credentials.map(esc).join(", ")}</span> · <a href="#/settings/system">see Keys</a></span></div>` : ""}
      <div class="strong small-13">Who does what</div>
      <div>
        <div class="roles head"><div>Role</div><div>Provider</div><div>Model</div></div>
        ${(env.roles || []).map((r) => `<div class="roles row"><div><div class="small-13 strong">${esc(ROLE_LABEL[r.role] || r.role)}</div><div class="mono muted small">${esc(r.role)}</div></div><div class="small-13">${esc(r.provider)}</div><div class="mono">${esc(r.model)}</div></div>`).join("")}
      </div>
      <div class="note">${ICON.info}<span>The build manifest records the environment and every model, so a draft deck is never mistaken for a final one.</span></div>
    </section>`;

  const systemPage = `
    <div class="grid-2 settings align-start">
      <section class="panel tight" id="keys">
        <h2 class="h2">Provider keys</h2>
        ${keys.map((k, i) => `
          <div class="check ${i ? "" : "first"}">${checkMark(!!k.set)}
            <div class="check-body"><div class="check-name mono">${esc(k.var || k.name)}</div>
            <div class="check-note">${esc(k.provider || "")}${k.needed_by?.length ? " · used by " + k.needed_by.map(esc).join(", ") : ""}${k.set ? " · set" : " · not set"}</div></div>
          </div>`).join("") || '<div class="small muted">No key information from the server yet.</div>'}
        <div class="note plain">${ICON.lock}<span>Keys are read from your environment, or from .env in the AutoDeck folder (restart AutoDeck after editing it). AutoDeck never stores or shows them.</span></div>
      </section>
      <section class="panel tight">
        <h2 class="h2">Rendering</h2>
        ${rendering.map((c, i) => {
          const ok = c.ok ?? c.passed ?? !!c.found;
          return `<div class="check ${i ? "" : "first"}">${checkMark(ok)}<div class="check-body"><div class="check-name">${esc(c.name || c.label)}</div><div class="check-note">${esc(c.note || c.detail || "")}</div></div></div>`;
        }).join("") || '<div class="small muted">Rendering checks are listed on Home under “Ready to build”.</div>'}
      </section>
    </div>`;

  let projectPage = "";
  let projectState = null;
  if (tab === "project") {
    const names = (await api("/api/projects")).projects || [];
    let chosen = names[0] || "";
    try { chosen = names.includes(sessionStorage.getItem("autodeck.settings.project")) ? sessionStorage.getItem("autodeck.settings.project") : chosen; } catch { /* optional */ }
    if (chosen) {
      const ps = await api(`/api/projects/${enc(chosen)}/settings`);
      projectState = { name: chosen, names, ps };
      projectPage = `
        <section class="panel">
          <h2 class="h2">Project settings</h2>
          <form id="project-form" class="stack gap-10">
            <label class="field">Project
              <select class="input" name="project">${names.map((n) => `<option value="${esc(n)}" ${n === chosen ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
            </label>
            <fieldset class="field" role="radiogroup" aria-label="Provenance">
              <legend>Provenance</legend>
              ${["normal", "strict"].map((m) => `
                <label class="radio-row"><input type="radio" name="provenance" value="${m}" ${ps.provenance === m ? "checked" : ""}>
                  <span><span class="strong">${esc(PROVENANCE_LABEL[m])}</span><br><span class="small-13 muted">${esc(PROVENANCE_BLURB[m])}</span></span></label>`).join("")}
              <span class="field-hint">A run keeps the mode it started with; a change applies to new runs. Use Strict for decks that go through MLR review.</span>
            </fieldset>
            <label class="field">Names that contain numbers (e.g. Type 2 diabetes)
              <textarea class="input" name="named_terms" rows="6" spellcheck="false">${esc((ps.named_terms || []).join("\n"))}</textarea>
              <span class="field-hint">One per line. The number checks treat these as names, not as quantities.</span>
            </label>
            <div class="row-end"><button class="btn" type="submit">Save</button></div>
          </form>
        </section>`;
    } else {
      projectPage = '<section class="panel"><div class="empty">No projects yet.</div></section>';
    }
  }

  let memoryPage = "";
  let memoryState = null;
  if (tab === "memory") {
    const clients = (await api("/api/clients")).clients || [];
    const names = (await api("/api/projects")).projects || [];
    const pick = (key, list) => {
      let v = list[0] || "";
      try { const saved = sessionStorage.getItem(key); if (list.includes(saved)) v = saved; } catch { /* optional */ }
      return v;
    };
    const client = pick("autodeck.settings.memory.client", clients);
    const project = pick("autodeck.settings.memory.project", names);
    if (client && project) {
      const mem = await api(`/api/memory?client=${enc(client)}&project=${enc(project)}`);
      memoryState = { client, project };
      const opts = (list, chosen) => list.map((n) => `<option value="${esc(n)}" ${n === chosen ? "selected" : ""}>${esc(n)}</option>`).join("");
      memoryPage = `
        <section class="panel">
          <h2 class="h2">Agent memory</h2>
          <p class="small-13 muted">What the drafting agent carries from one run to the next. It is context for spelling and style; it is never a source, so nothing here reaches a slide without a citation. You can edit either file; a note that names a client or states a figure is refused in the owner file.</p>
          <div class="stack gap-10">
            <div class="grid-2">
              <label class="field">Client
                <select class="input" id="memory-client">${opts(clients, client)}</select>
              </label>
              <label class="field">Project
                <select class="input" id="memory-project">${opts(names, project)}</select>
              </label>
            </div>
            ${[["engagement", "This engagement", "Terms, people, open actions, decisions and deck preferences for this client and project."], ["owner", "How I like to work", "Note style and deck habits, for every client. Never a client fact."]].map(([scope, label, hint]) => `
              <label class="field">${label}
                <textarea class="input mono" id="memory-${scope}" rows="12" spellcheck="false">${esc(mem[scope] || "")}</textarea>
                <span class="field-hint">${hint}</span>
              </label>
              <div class="row-end"><button class="btn" type="button" data-memory-save="${scope}">Save ${scope === "owner" ? "owner" : "engagement"} memory</button></div>`).join("")}
            <div class="strong small-13">Recent changes</div>
            ${(mem.audit || []).length ? `<div class="stack gap-8">${mem.audit.map((a) => `<div class="small-13"><span class="mono muted">${esc(a.at || "")}</span> · ${esc(a.scope)} · ${esc(a.op)}${a.section ? " · " + esc(a.section) : ""}${a.text ? " · " + esc(a.text) : ""}</div>`).join("")}</div>` : '<div class="small muted">Nothing remembered yet.</div>'}
          </div>
        </section>`;
    } else {
      memoryPage = '<section class="panel"><div class="empty">Add a client and a project first.</div></section>';
    }
  }

  view.innerHTML = `
    <div class="page-head"><div>
      <h1 class="page-title">Settings</h1>
      <p class="page-sub">For this computer. Applies to new runs started from this window.</p>
    </div></div>
    <nav class="segmented self-start" aria-label="Settings sections">
      ${SETTINGS_TABS.map(([k, l]) => `<a href="#/settings/${k}" ${k === tab ? 'aria-current="page"' : ""}>${l}</a>`).join("")}
    </nav>
    ${{ profile: profilePage, models: modelsPage, project: projectPage, memory: memoryPage, system: systemPage }[tab]}`;

  if (memoryState) {
    for (const [id, key] of [["memory-client", "client"], ["memory-project", "project"]]) {
      document.getElementById(id).addEventListener("change", (e) => {
        try { sessionStorage.setItem(`autodeck.settings.memory.${key}`, e.target.value); } catch { /* optional */ }
        settingsView("memory");
      });
    }
    view.querySelectorAll("[data-memory-save]").forEach((b) => b.addEventListener("click", async () => {
      const scope = b.dataset.memorySave;
      try {
        await api("/api/memory", { ...memoryState, scope, content: document.getElementById(`memory-${scope}`).value }, "PUT");
        toast("Saved.");
        settingsView("memory");
      } catch (err) { toast(err.message, true); }
    }));
  }

  const pform = document.getElementById("project-form");
  if (pform && projectState) {
    pform.elements.project.addEventListener("change", (e) => {
      try { sessionStorage.setItem("autodeck.settings.project", e.target.value); } catch { /* optional */ }
      settingsView("project");
    });
    pform.addEventListener("submit", async (event) => {
      event.preventDefault();
      const fd = new FormData(pform);
      try {
        await api(`/api/projects/${enc(projectState.name)}/settings`, {
          provenance: String(fd.get("provenance") || ""),
          named_terms: String(fd.get("named_terms") || "").split("\n").map((t) => t.trim()).filter(Boolean),
        });
        toast("Saved. New runs in this project use these settings.");
        settingsView("project");
      } catch (err) { toast(err.message, true); }
    });
  }

  view.querySelectorAll("[data-env]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api("/api/settings", { env: b.dataset.env });
      settingsView("models");
    } catch (err) { toast(err.message, true); }
  }));
  const form = document.getElementById("profile-form");
  if (form) form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = String(new FormData(event.target).get("name") || "").trim();
    try {
      await api("/api/profile", { name });
      toast("Saved. Approvals will carry this name.");
      settingsView("profile");
    } catch (err) { toast(err.message, true); }
  });
}

// ---- draft-first (Phase 3c: B43, B47, B48) ----------------------------------
// The checkpoint, the assembling run page, the draft review (with the one conversation) and
// the approvals on the draft. Nothing here approves by itself: the only approving call is the
// explicit click on an "Approve & proceed" button, which POSTs to /api/runs/<id>/approve.

const DRAFT_STEPS = ["draft", "revise", "validate", "preview"];
const draftPill = (text = "Draft — not approved") => `<span class="draft-pill"><span class="dot"></span>${esc(text)}</span>`;

const docLabel = (id, page) => {
  const s = String(id ?? "");
  if (s.startsWith("conversation--")) return page != null && page !== "" ? `from you · message ${page}` : "from you";
  if (s.startsWith("transcript--")) return page != null && page !== "" ? `from the meeting · turn ${page}` : "from the meeting";
  return s.startsWith("client-deck--") ? `client-supplied deck · ${s.slice("client-deck--".length)}` : s;
};
// A block that makes a claim: judged, cited, or the model's own general knowledge (unsourced).
const isClaimBlk = (b) => !!(b.verdict || (b.citations || []).length || b.basis === "unsourced");

const slideTitle = (s) => {
  const t = (s.blocks || []).find((b) => /title|head/i.test(b.slot || "") && b.text);
  return t?.text || s.intent || `Slide ${s.n}`;
};
// A headline with a verdict (B62) or a storyline finding (B70) stays in the list, so its note can be opened.
const isTitleOnly = (s, b) => /title|head/i.test(b.slot || "") && !b.verdict && !(b.citations || []).length
  && slideTitle(s) === b.text
  && !(b.slot === "headline" && (s.headline_check || (s.storyline_findings || []).length));

// verdict -> display info; "" is framing (a connecting line with no source and no check).
function verdictOf(v) {
  if (!v) return { key: "framing", label: "Framing", kind: "neutral", cls: "vf" };
  const kind = VERDICT_KIND[v] || "neutral";
  return { key: v, label: v === "partially_supported" ? "partial" : v.replace(/_/g, " "), kind, cls: `v-${kind}` };
}

function draftCounts(d) {
  const blocks = (d.slides || []).flatMap((s) => s.blocks || []);
  const claims = blocks.filter((b) => isClaimBlk(b));
  const n = (f) => claims.filter(f).length;
  return {
    slides: (d.slides || []).length,
    claims: claims.length,
    supported: n((b) => b.verdict === "supported"),
    partial: n((b) => b.verdict === "partially_supported"),
    unsupported: n((b) => b.verdict === "unsupported" || b.verdict === "contradicted"),
    unverified: n((b) => !b.verdict || b.verdict === "unverified"),
  };
}

function slideLevel(s) {
  const vs = (s.blocks || []).map((b) => b.verdict);
  if (vs.some((v) => v === "unsupported" || v === "contradicted") || s.flag === "blocking") return "bad";
  if (vs.some((v) => v === "partially_supported") || s.flag === "partial") return "warn";
  return "";
}

const sigOf = (s) => JSON.stringify([(s.blocks || []).map((b) => [b.id, b.text]), s.intent]);

const wireframe = (s) => `<div class="mock">${layoutMock(s.component)}</div>`;
const thumbBody = (s) => (s.preview
  ? `<img src="${esc(s.preview)}" alt="" loading="lazy">`
  : `<span class="thumb-wire">${wireframe(s)}</span>`);

function draftTracker(runId, approvals) {
  const items = [["brief", "Brief"], ["outline", "Outline"], ["claims", "Claims"], ["final", "Final"]];
  return `<div class="tracker" aria-label="Approvals">${items.map(([k, l]) => {
    const ok = !!approvals?.[k]?.approved;
    return `<a class="pill ${ok ? "done" : "todo"}" href="#/approve/${enc(runId)}"><span class="pdot"></span>${l}<span class="sr-only"> ${ok ? "approved" : "pending"}</span></a>`;
  }).join("")}</div>`;
}

function redesignLine(r) {
  const st = r.settings || {};
  const parts = [st.wording === "light" ? "light rewording allowed" : "your words kept", st.layouts === false ? "layouts kept" : "layouts may change"];
  if (st.check_papers) parts.push("figures also checked against project papers");
  return `Redesign of ${st.source_file || "your deck"} · ${parts.join(" · ")}`;
}

function draftHead(runId, d, title, sub) {
  const c = draftCounts(d);
  const chip = (cls, text) => `<span class="chip">${cls ? `<span class="dot ${cls}"></span>` : ""}${esc(text)}</span>`;
  return `
    <div class="page-head">
      <div class="head-text">
        <div class="crumbs"><a href="#/runs">Runs</a> / <a href="${runHref(runId)}">${esc(runId)}</a> / Draft</div>
        <div class="row gap-12 wrap"><h1 class="page-title">${esc(title)}</h1>${draftPill()}</div>
        ${sub ? `<p class="page-sub">${esc(sub)}</p>` : ""}
        <div class="chips-row">
          ${chip("", `${c.slides} slide${c.slides === 1 ? "" : "s"}`)}${chip("", `${c.claims} claim${c.claims === 1 ? "" : "s"}`)}
          ${chip("dot-ok", `${c.supported} supported`)}
          ${c.partial ? chip("dot-warn", `${c.partial} partial`) : ""}
          ${c.unsupported ? chip("dot-bad", `${c.unsupported} unsupported`) : ""}
        </div>
      </div>
      <div class="stack gap-10 items-end">
        ${draftTracker(runId, d.approvals)}
        <a class="btn btn-pill" href="#/approve/${enc(runId)}">Review approvals</a>
      </div>
    </div>`;
}

// ---- checkpoint: "Before I draft" ---------------------------------------------

async function clarifyView(runId) {
  setNav("runs");
  const c = await api(`/api/runs/${enc(runId)}/clarify`);
  const assumptions = c.assumptions || [];
  const questions = c.questions || [];
  const prior = c.answers || {};
  const state = {
    corrections: {},   // assumption index -> corrected text
    editing: new Set(),
    picked: new Set(),  // answers chosen from the model's own options: not typed, so not "from you"
    values: Object.fromEntries(questions.map((q) => [q.id, prior[q.id] ?? q.suggested_answer ?? ""])),
  };
  const optLabel = (o) => (typeof o === "string" ? o : o?.label ?? o?.text ?? o?.value ?? "");
  let isRedesign = Boolean(c.redesign) || c.mode === "redesign";
  try { isRedesign = isRedesign || sessionStorage.getItem(`autodeck.redesign.${runId}`) === "1"; } catch { /* optional hint */ }

  view.innerHTML = `
    <div class="page-head"><div class="head-text">
      <div class="crumbs"><a href="#/runs">Runs</a> / <a href="${runHref(runId)}">${esc(runId)}</a> / Checkpoint</div>
      <h1 class="page-title">${isRedesign ? "Before I redesign" : "Before I draft"}</h1>
      <p class="page-sub">${esc(c.prompt || "")}</p>
    </div>${draftPill(isRedesign ? "Nothing redesigned yet" : "Nothing drafted yet")}</div>
    <div class="grid-2 equal align-start">
      <section class="panel" aria-labelledby="as-h">
        <div class="panel-head"><h2 class="h2" id="as-h">What I will assume</h2><span class="small muted">Correct anything that is off</span></div>
        <div id="assume"></div>
      </section>
      <section class="panel" aria-labelledby="q-h">
        <div class="panel-head"><h2 class="h2" id="q-h">${questions.length ? `${questions.length} question${questions.length === 1 ? "" : "s"}` : "Questions"}</h2><span class="small muted">Only what would change the deck</span></div>
        <div id="qs"></div>
      </section>
    </div>
    <div class="action-bar">
      <div id="act-note" hidden></div>
      <div class="action-right">
        ${c.answered
          ? `<div class="note ok">${ICON.info}<span>You already answered. <a href="${runHref(runId)}">Open the run</a></span></div>`
          : `<button class="btn" id="go" type="button">${isRedesign ? "Redesign the deck" : "Draft the deck"}</button>
             <div class="small muted">Writes the brief, outline and every slide in one go. Nothing is approved by drafting.</div>`}
      </div>
    </div>`;

  const aEl = document.getElementById("assume");
  const qEl = document.getElementById("qs");
  const paintAssume = () => {
    aEl.innerHTML = assumptions.map((a, i) => {
      const edited = state.corrections[i] !== undefined && state.corrections[i].trim() !== String(a.statement).trim();
      const open = state.editing.has(i);
      return `
        <div class="as-row">
          <div class="as-top"><span class="eyebrow">${esc(a.topic)}</span>${edited ? '<span class="badge accent">Corrected</span>' : ""}
            ${c.answered ? "" : `<button type="button" class="link-btn" data-fix="${i}" aria-expanded="${open}">${open ? "Done" : "Correct"}</button>`}</div>
          ${open
            ? `<label class="sr-only" for="as-${i}">Corrected ${esc(a.topic)}</label><input class="input" id="as-${i}" data-as="${i}" value="${esc(state.corrections[i] ?? a.statement)}">`
            : `<div class="as-text">${esc(edited ? state.corrections[i] : a.statement)}</div>`}
        </div>`;
    }).join("") || '<div class="empty">No assumptions to show.</div>';
  };
  const paintQs = () => {
    if (!questions.length) { qEl.innerHTML = '<div class="note plain">' + ICON.info + '<span>Nothing to ask — check the assumptions and draft.</span></div>'; return; }
    qEl.innerHTML = questions.map((q) => `
      <div class="q-row">
        <h3 class="h3">${esc(q.question)}</h3>
        ${q.why ? `<div class="small-13 muted">${esc(q.why)}</div>` : ""}
        ${(q.options || []).length ? `<div class="chips-row" role="group" aria-label="Options for ${esc(q.question)}">${q.options.map((o) =>
          `<button type="button" class="chip-btn" data-q="${esc(q.id)}" data-opt="${esc(optLabel(o))}" aria-pressed="${state.values[q.id] === optLabel(o)}">${esc(optLabel(o))}</button>`).join("")}</div>` : ""}
        <label class="sr-only" for="q-${esc(q.id)}">Your answer: ${esc(q.question)}</label>
        <input class="input" id="q-${esc(q.id)}" data-qin="${esc(q.id)}" value="${esc(state.values[q.id])}" ${c.answered ? "disabled" : ""}>
        ${state.values[q.id] === (q.suggested_answer ?? "") ? '<div class="small muted">Suggested answer. Edit it or pick another.</div>' : ""}
      </div>`).join("");
  };
  paintAssume(); paintQs();

  aEl.addEventListener("click", (e) => {
    const b = e.target.closest("[data-fix]");
    if (!b) return;
    const i = Number(b.dataset.fix);
    if (state.editing.has(i)) state.editing.delete(i); else state.editing.add(i);
    paintAssume();
    document.getElementById(`as-${i}`)?.focus();
  });
  aEl.addEventListener("input", (e) => {
    const f = e.target.closest("[data-as]");
    if (f) state.corrections[Number(f.dataset.as)] = f.value;
  });
  qEl.addEventListener("click", (e) => {
    const b = e.target.closest("[data-opt]");
    if (!b) return;
    state.values[b.dataset.q] = b.dataset.opt;
    state.picked.add(b.dataset.q);
    paintQs();
  });
  qEl.addEventListener("input", (e) => {
    const f = e.target.closest("[data-qin]");
    if (!f) return;
    state.values[f.dataset.qin] = f.value;
    state.picked.delete(f.dataset.qin);
    // Keep focus while the option chips and the "suggested" hint catch up.
    f.closest(".q-row").querySelectorAll("[data-opt]").forEach((o) => o.setAttribute("aria-pressed", String(o.dataset.opt === f.value)));
  });

  const go = document.getElementById("go");
  if (go) go.addEventListener("click", async () => {
    const corrections = assumptions
      .map((a, i) => (state.corrections[i] !== undefined && state.corrections[i].trim() && state.corrections[i].trim() !== String(a.statement).trim()
        ? `${a.topic}: ${state.corrections[i].trim()}` : null))
      .filter(Boolean);
    const changed = questions.some((q) => (state.values[q.id] ?? "") !== (q.suggested_answer ?? ""));
    const untouched = !changed && !corrections.length;
    go.disabled = true;
    try {
      await api(`/api/runs/${enc(runId)}/answers`, {
        accept_all: untouched, answers: untouched ? {} : state.values, corrections,
        // Left as suggested or picked from the offered options: the model's wording (B55).
        accepted: questions.filter((q) => state.picked.has(q.id) || (state.values[q.id] ?? "") === (q.suggested_answer ?? "")).map((q) => q.id),
      });
      location.hash = runHref(runId);
    } catch (err) {
      go.disabled = false;
      actionError(document.getElementById("act-note"), err, runId);
    }
  });
}

// ---- assembling: the run page for a draft-first run ----------------------------

function showAssembling(r) {
  const j = r.job;
  if (j?.status === "running") return (j.steps || []).some((s) => DRAFT_STEPS.includes(s)) || DRAFT_STEPS.includes(j.step);
  const render = (r.stage_list || []).find((s) => s.key === "render");
  return !render || render.status === "locked";
}

// ---- the deck agent's session (Phase 4c) -------------------------------------------

const agentSess = { runId: null, data: null, all: false };

async function loadAgentSession(runId) {
  if (agentSess.runId !== runId) Object.assign(agentSess, { runId, data: null, all: false });
  try { agentSess.data = await api(`/api/runs/${enc(runId)}/session`); } catch { /* keep the last one */ }
  return agentSess.data;
}

// A compact timeline of what the agent has done so far; the newest row is last.
function agentTimelineHtml(runId) {
  const rows = agentSess.runId === runId ? agentSess.data?.timeline || [] : [];
  if (!rows.length) return "";
  const shown = agentSess.all ? rows : rows.slice(-30);
  return `<div class="agent-tl" aria-label="What the agent has done">
    ${shown.map((x) => `<div class="agent-row${x.error ? " err" : ""}"><span class="mono muted">${esc(x.step)}</span> · ${esc(x.tool || x.role)} — ${esc(x.summary || "")}</div>`).join("")}
    ${rows.length > 30 ? `<button type="button" class="link-btn small" data-agent-all>${agentSess.all ? "Show the last 30" : `Show all ${rows.length}`}</button>` : ""}
  </div>`;
}

function agentMetaLine(runId) {
  const m = agentSess.runId === runId ? agentSess.data?.meta : null;
  if (!m) return "";
  const n = m.steps ?? m.step_count ?? m.n_steps ?? "?";
  const fell = m.fell_back ?? m.fallback ?? false;
  return `<div class="small-13 muted">Agent: ${esc(n)} steps · ${esc(m.stop_reason ?? "unknown")} · fell back: ${fell ? "yes" : "no"}</div>`;
}

function bindAgentToggle(root, repaint) {
  const b = root.querySelector("[data-agent-all]");
  if (b) b.addEventListener("click", () => { agentSess.all = !agentSess.all; repaint(); });
}

const STEP_STAGE = { clarify: "clarify", draft: "compose", revise: "compose", validate: "validate", preview: "preview" };
const ASSEMBLY = ["clarify", "compose", "validate", "preview"];
const ASSEMBLY_NOTE = {
  clarify: "Your answers are recorded",
  compose: "One call writes the brief, outline and slides, citing as it goes",
  validate: "Code finds each quote on its page; a second model checks it supports the sentence",
  preview: "Draws each slide, marked Draft",
};

async function assemblingView(runId, r0) {
  setNav("runs");
  const state = { r: r0, job: r0.job || null, d: null, settings: null };
  const answered = () => (state.r.stage_list || []).find((s) => s.key === "clarify")?.status === "done";
  try { state.settings = await api("/api/settings"); } catch { /* the picker just stays hidden */ }

  view.innerHTML = `
    <div class="page-head">
      <div class="head-text">
        <div class="crumbs"><a href="#/runs">Runs</a> / ${esc(runId)}</div>
        <h1 class="page-title" id="as-title">Drafting your deck</h1>
        <p class="page-sub" id="as-sub"></p>
      </div>
      ${draftPill()}
    </div>
    <div class="grid-2 equal align-start">
      <section class="panel" aria-labelledby="doing-h">
        <h2 class="h2" id="doing-h">What AutoDeck is doing</h2>
        <div class="timeline" id="as-steps"></div>
        <div id="as-fail" hidden></div>
        <div id="job-box"></div>
        <div class="small muted">Code checks that each quote exists. A second model checks it supports the sentence. Nothing is approved until you approve it.</div>
      </section>
      <section class="panel" aria-labelledby="shape-h">
        <div class="panel-head"><h2 class="h2" id="shape-h">Taking shape</h2><span class="small muted">As written, not yet checked by you</span></div>
        <div id="as-shape"></div>
      </section>
    </div>
    <div class="action-bar">
      <div class="small muted" id="as-hint">Opens as soon as the draft exists. Slides fill in as previews appear.</div>
      <div class="action-right row gap-12" id="as-actions"></div>
    </div>`;

  const paint = () => {
    const { r, job, d } = state;
    const running = job?.status === "running";
    const list = (r.stage_list || []).filter((s) => ASSEMBLY.includes(s.key));
    // The job lives in server memory and is gone after a restart; the stage's saved status
    // is not. Either one failing must offer "Try again", or a failed run has no way out.
    const failed = (job && (job.status === "failed" || job.status === "stopped"))
      || (!running && list.some((s) => s.key === "compose" && s.status === "failed"));
    const runningStage = running ? STEP_STAGE[job.step] : null;
    const started = job?.started_at ? Date.parse(job.started_at) : NaN;
    const secs = running && !Number.isNaN(started) ? Math.max(0, Math.round((Date.now() - started) / 1000)) : null;
    const composed = list.find((s) => s.key === "compose")?.status === "done";
    document.getElementById("as-title").textContent = running ? (job.steps || []).includes("revise") ? "Revising the draft" : "Drafting your deck"
      : failed ? "The draft stopped" : composed ? "The draft is ready" : "Waiting to draft";
    document.getElementById("as-sub").textContent = running
      ? `${secs != null ? `${secs}s elapsed · ` : ""}${job.step_label || job.step || "working"}`
      : failed ? (job?.message || "A step failed. Nothing was approved.") : composed ? "Review it, revise it, then approve." : r.next || "";

    const stepsEl = document.getElementById("as-steps");
    stepsEl.innerHTML = list.map((s) => {
      const status = runningStage === s.key ? "running" : s.status;
      let note = s.detail || ASSEMBLY_NOTE[s.key] || "";
      if (s.key === "compose" && d) { const c = draftCounts(d); note = `${plural(c.slides, "slide")} · ${plural(c.claims, "claim")}`; }
      return `
        <div class="tl-row">
          <span class="tl-mark st-${esc(status)}" aria-hidden="true">${STAGE_MARK[status] || ""}</span>
          <div class="tl-body">
            <div class="row gap-8"><span class="tl-name st-${esc(status)}">${esc(s.label)}</span>${STAGE_TAG[status] ? `<span class="tag tag-${esc(status)}">${STAGE_TAG[status]}</span>` : ""}<span class="sr-only">${esc(status)}</span></div>
            <div class="small-13 muted">${esc(note)}</div>
            ${status === "running" ? '<div class="bar"><i></i></div>' : ""}
            ${s.key === "compose" ? (status === "running" ? agentTimelineHtml(runId) : agentMetaLine(runId)) : ""}
          </div>
        </div>`;
    }).join("") || `<div class="empty">${esc(r.next || "No stage information yet.")}</div>`;
    bindAgentToggle(stepsEl, paint);

    const box = document.getElementById("job-box");
    if (job) {
      const lines = (job.log || []).slice(-40);
      box.innerHTML = `
        <div class="job-head"><span class="badge ${failed ? "bad" : running ? "accent" : "ok"}">${esc(job.status)}</span>
          <span class="small muted">${esc((job.steps || []).join(" → "))}${job.step ? ` · now ${esc(job.step)}` : ""}</span></div>
        <pre class="log" id="log" tabindex="0" aria-label="Job log">${esc(lines.join("\n") || "No output yet.")}</pre>`;
      const log = document.getElementById("log");
      if (log) log.scrollTop = log.scrollHeight;
    } else box.innerHTML = "";

    const shape = document.getElementById("as-shape");
    if (!d) {
      shape.innerHTML = '<div class="empty">The brief and slides appear here as soon as they are written.</div>';
    } else {
      const b = d.brief || {};
      shape.innerHTML = `
        ${b.objective ? `<div class="small-13"><span class="strong">Objective</span> · ${esc(b.objective)}</div>` : ""}
        ${b.audience ? `<div class="small-13"><span class="strong">Audience</span> · ${esc(b.audience)}</div>` : ""}
        <div class="stack gap-2">${(b.key_messages || []).map((m) => `
          <div class="row between gap-12 km-line"><div class="small-13"><span class="mono muted">${esc(m.id)}</span> ${esc(m.text)}</div>
            <span class="badge ${EVIDENCE_KIND[m.evidence] ?? ""}">${esc(m.evidence)}</span></div>`).join("")}</div>
        <div class="film left">${(d.slides || []).map((s) => `
          <div class="thumb static" aria-label="Slide ${esc(s.n)}">${thumbBody(s)}<span class="small thumb-cap">${esc(s.n)} ${esc(slideTitle(s))}</span></div>`).join("")}</div>`;
    }

    const acts = document.getElementById("as-actions");
    const parts = [];
    const canRetry = failed && !composed && answered();
    // A failed draft is recovered here, not in a terminal: say what went wrong in plain
    // words and offer other models beside "Try again". Only environments whose keys are
    // all set can be picked; the choice is remembered (Settings shows the same list).
    const failMsg = job?.message || list.find((s) => s.status === "failed")?.detail || "";
    const quota = /429|rate.?limit|quota|exhausted|503|unavailable|overloaded/i.test(failMsg);
    const hint = document.getElementById("as-hint");
    if (canRetry) {
      hint.textContent = quota
        ? "These models are out of quota or overloaded right now. Pick other models and try again, or try the same ones later."
        : "Fix what the message says, or pick other models, then try again. Nothing was approved.";
      const envs = state.settings?.envs || [];
      const current = state.settings?.env?.name;
      if (envs.length > 1) {
        parts.push(`<label class="sr-only" for="retry-env">Models to use</label>
          <select class="select" id="retry-env">${envs.map((e) => {
            const missing = (e.missing_credentials || []).length > 0;
            return `<option value="${esc(e.name)}"${e.name === current ? " selected" : ""}${missing ? " disabled" : ""}>${esc(e.label)}${missing ? " (key not set)" : ""}</option>`;
          }).join("")}</select>`);
      }
    } else {
      hint.textContent = "Opens as soon as the draft exists. Slides fill in as previews appear.";
    }
    if (running) parts.push('<button class="btn btn-quiet-accent" id="stop" type="button">Stop</button>');
    if (canRetry) parts.push('<button class="btn btn-quiet" id="retry" type="button">Try again</button>');
    if (!answered() && !running && !composed) parts.push(`<a class="btn btn-quiet" href="#/clarify/${enc(runId)}">Open the checkpoint</a>`);
    parts.push(d
      ? `<a class="btn" href="#/draft/${enc(runId)}">Open the draft</a>`
      : '<button class="btn" type="button" disabled>Open the draft</button>');
    acts.innerHTML = parts.join("");
    const stop = document.getElementById("stop");
    if (stop) stop.addEventListener("click", async () => {
      stop.disabled = true;
      try { await api(`/api/runs/${enc(runId)}/stop`, {}); } catch (err) { stop.disabled = false; toast(err.message, true); }
    });
    const retry = document.getElementById("retry");
    if (retry) retry.addEventListener("click", async () => {
      retry.disabled = true;
      try {
        const pick = document.getElementById("retry-env")?.value;
        if (pick && pick !== state.settings?.env?.name) {
          state.settings = await api("/api/settings", { env: pick });
        }
        await api(`/api/runs/${enc(runId)}/answers`, { accept_all: true });
        route();
      } catch (err) { retry.disabled = false; toast(err.message, true); }
    });
  };

  // Ask for the draft only once the compose step has finished; before that the server
  // answers 409 ("no draft yet"), which is expected but clutters the console.
  const composed = () => (state.r?.stage_list || []).some((x) => x.key === "compose" && x.status === "done");
  const fetchDraft = async () => {
    if (!state.d && !composed()) return;
    try { state.d = await api(`/api/runs/${enc(runId)}/draft`); } catch { /* not composed yet */ }
  };
  await fetchDraft();
  await loadAgentSession(runId);
  paint();
  if (state.job?.status === "running") {
    stopPolling();
    pollTimer = setInterval(async () => {
      if (!location.hash.startsWith(`#/run/${enc(runId)}`)) { stopPolling(); return; }
      try {
        const [r, j] = await Promise.all([api(`/api/runs/${enc(runId)}`), api(`/api/runs/${enc(runId)}/job`)]);
        state.r = r; state.job = j.job || r.job || null;
        await loadAgentSession(runId);
        await fetchDraft();
        paint();
        if (!state.job || state.job.status !== "running") stopPolling();
      } catch { /* keep polling; the server may be busy */ }
    }, 1500);
  }
}

// ---- draft review ---------------------------------------------------------------

const COVER_LABEL = { covered: "Covered", hedged: "Hedged", gap: "Gap", left_out: "Left out" };
const COVER_KIND = { covered: "ok", hedged: "warn", gap: "bad", left_out: "accent" };
const REVISE_STEP_LABEL = {
  revise: "Rewriting the slides you touched",
  validate: "Checking the changed claims",
  preview: "Re-rendering the changed previews",
};
const SUGGESTIONS = ["Add a slide on cost", "Make slide 3 shorter", "Cite the source for every number"];

async function draftView(runId) {
  setNav("runs");
  let [d, jobRes] = await Promise.all([api(`/api/runs/${enc(runId)}/draft`), api(`/api/runs/${enc(runId)}/job`).catch(() => ({}))]);
  const st = { slide: 0, block: null, tab: "claim", revising: null };
  let job = jobRes.job || null;

  // Block ids are unique only within a slide (every slide has a b1), so look in the slide
  // on screen; searching the whole deck would show slide 1's b2 for slide 4's b2.
  const blockOf = (id) => {
    const s = d.slides[st.slide];
    const b = s ? [...s.blocks, ...(s.notes || [])].find((x) => x.id === id) : null;
    return b ? [s, b] : [null, null];
  };
  const defaultBlock = () => {
    const s = d.slides[st.slide];
    if (!s) return null;
    const worst = s.blocks.find((b) => b.verdict && b.verdict !== "supported") || s.blocks.find((b) => isClaimBlk(b));
    return (worst || s.blocks[0])?.id ?? null;
  };
  st.block = defaultBlock();
  await loadAgentSession(runId);
  // Rejections grouped by what went wrong; old runs without `failures` fall back to the strings.
  const FAILURE_LABEL = {
    quote_not_found: "Quote not found in the source",
    quote_splice: "Quote joined two passages",
    doc_not_shown: "Quote not found in the source",
    uncitable: "Quote not found in the source",
    overflow_item: "Too long for its slot",
    overflow_stack: "Too long for its slot",
    overflow_text: "Too long for its slot",
    unknown_slot: "Not a slot of this layout",
    computed_slot: "Not a slot of this layout",
    framing_fence: "Framing carried a fact",
    numeral_unmatched: "Number not in a cited source",
    header_fact_unbacked: "Headline fact not backed on the slide",
    subjectless_point: "Comparison point does not name its side",
    mode_blocked: "Not allowed in strict mode",
    missing_slot: "Required part empty",
    ir_invalid: "Could not be built",
  };
  const failureGroups = (xs) => {
    const groups = new Map();
    (xs || []).forEach((r) => {
      if (!r || typeof r !== "object") return;
      const label = FAILURE_LABEL[r.kind] || "Dropped";
      if (!groups.has(label)) groups.set(label, []);
      groups.get(label).push(r);
    });
    return [...groups.entries()];
  };

  const coverageFlag = () => (d.coverage || []).filter((c) => c.status && c.status !== "covered").length;

  view.innerHTML = `
    <div id="dr-head"></div>
    <div id="dr-banner" hidden></div>
    <div id="rev" hidden></div>
    <div class="dr-grid" id="dr-grid">
      <nav class="film-col" id="film" aria-label="Slides"></nav>
      <section class="panel dr-stage" id="stage" aria-live="polite"></section>
      <section class="panel dr-insp" id="insp" aria-label="Inspector"></section>
    </div>
    <section class="panel chat-dock" aria-labelledby="chat-h">
      <div class="panel-head"><h2 class="h2" id="chat-h">Tell AutoDeck what to change</h2><span class="small muted">One conversation. Only the slides you touch are redone.</span></div>
      <div class="chat dock-chat" id="chat" aria-live="polite"></div>
      <form id="say" class="stack gap-8">
        <label class="sr-only" for="revise">Your instruction</label>
        <textarea class="textarea chat-input" id="revise" rows="2" placeholder="For example: Slide 2: say what the mechanism does in one line"></textarea>
        <div class="row between wrap gap-12">
          <div class="chips-row">${SUGGESTIONS.map((s, i) => `<button type="button" class="chip-btn" data-sg="${i}">${esc(s)}</button>`).join("")}</div>
          <div class="row gap-12"><span class="small muted">Enter sends, Shift+Enter adds a line.</span><button class="btn" id="send" type="submit">Revise</button></div>
        </div>
      </form>
    </section>`;

  const headEl = document.getElementById("dr-head");
  const filmEl = document.getElementById("film");
  const stageEl = document.getElementById("stage");
  const inspEl = document.getElementById("insp");
  const chatEl = document.getElementById("chat");
  const reviseEl = document.getElementById("revise");
  const sendBtn = document.getElementById("send");

  const paintHead = () => {
    headEl.innerHTML = draftHead(runId, d, d.brief?.objective ? d.brief.objective.replace(/\.$/, "") : runId,
      d.redesign ? redesignLine(d.redesign) : d.notes || (d.validated ? "" : "Claims are still being checked."));
  };

  const paintFilm = () => {
    filmEl.innerHTML = d.slides.map((s, i) => {
      const lvl = slideLevel(s);
      return `<button type="button" class="thumb ${i === st.slide ? "on" : ""}" data-i="${i}" aria-pressed="${i === st.slide}" aria-label="Slide ${esc(s.n)}: ${esc(slideTitle(s))}${lvl ? lvl === "bad" ? ", has an unsupported claim" : ", needs a look" : ""}">
        ${thumbBody(s)}<span class="thumb-num"><span>${esc(s.n)}</span>${lvl ? `<span class="dot ${lvl === "bad" ? "dot-bad" : "dot-warn"}"></span>` : ""}</span></button>`;
    }).join("") || '<div class="empty">No slides.</div>';
  };

  const blockBtn = (s, b, n) => {
    const v = verdictOf(b.verdict);
    const claim = isClaimBlk(b);
    return `<button type="button" class="blk ${v.cls} ${b.id === st.block ? "on" : ""}" data-b="${esc(b.id)}" aria-pressed="${b.id === st.block}">${esc(b.text)}${claim ? `<sup>${n}</sup>` : ""}<span class="sr-only"> ${esc(v.label)}</span></button>`;
  };

  const redesignPanel = (s) => {
    if (!d.redesign) return "";
    const ch = (d.redesign.changes || []).find((x) => x.slide_id === s.id);
    // The composer writes "kept" when the layout did not change; anything else is a reason.
    const changed = !!ch && !/^kept\.?$/i.test((ch.why || "").trim());
    const orig = s.original || [];
    const text = (o) => `<div class="orig-slide"><div class="small strong muted">Original slide ${esc(o.slide)}</div><div class="orig-text">${esc(o.text) || '<span class="muted">No text.</span>'}</div></div>`;
    const proposed = s.blocks.filter((b) => b.text).map((b) => `<li>${esc(b.text)}</li>`).join("");
    return `
      <div class="row between wrap gap-8"><div class="eyebrow">Your slide and the proposal</div>
        <span class="badge ${changed ? "accent" : ""}">${changed ? "Layout changed" : "Layout kept"}</span></div>
      <div class="compare">
        <section class="compare-col" aria-label="Original">${orig.map(text).join("") || '<div class="muted small-13">No slide of your deck maps to this one.</div>'}</section>
        <section class="compare-col" aria-label="Proposed"><div class="small strong muted">Proposed</div><ul class="compare-list">${proposed || "<li class='muted'>No text.</li>"}</ul></section>
      </div>
      ${changed ? `<div class="note plain">${ICON.info}<span><b>Why:</b> ${esc(ch.why)}</span></div>` : ""}`;
  };

  const paintStage = () => {
    const s = d.slides[st.slide];
    if (!s) { stageEl.innerHTML = '<div class="empty">The draft has no slides.</div>'; return; }
    let n = 0;
    const list = s.blocks.filter((b) => !isTitleOnly(s, b)).map((b) => blockBtn(s, b, (isClaimBlk(b)) ? ++n : 0)).join("");
    const lvl = slideLevel(s);
    stageEl.innerHTML = `
      <div class="row between wrap"><div class="small strong muted">Slide ${esc(s.n)} of ${d.slides.length} · ${esc(s.role)}</div>
        <div class="row gap-8">${lvl ? `<span class="badge ${lvl}">${lvl === "bad" ? "Has an unsupported claim" : "Needs a look"}</span>` : ""}${draftPill()}</div></div>
      ${redesignPanel(s)}
      ${s.preview
        ? `<div class="stage"><img class="slide-img" src="${esc(s.preview)}" alt="Draft preview of slide ${esc(s.n)}: ${esc(slideTitle(s))}"></div>
           <div class="eyebrow">Text on this slide</div><div class="blk-list">${list || '<span class="muted small-13">No text blocks.</span>'}</div>`
        : `<div class="slide-frame"><h2 class="slide-h">${esc(slideTitle(s))}</h2><div class="blk-list">${list || '<span class="muted small-13">No text blocks.</span>'}</div></div>`}
      ${(s.notes || []).length ? `<div class="small-13"><b>Speaker notes</b> ${s.notes.map((b) => esc(b.text)).join(" ")}</div>` : ""}
      <div class="legend small muted"><span><span class="swatch ok"></span>supported</span><span><span class="swatch warn"></span>partial</span><span><span class="swatch bad"></span>unsupported</span><span><span class="swatch frame"></span>framing, no source</span></div>`;
  };

  const fillChat = (text) => {
    reviseEl.value = text;
    reviseEl.scrollIntoView({ block: "center", behavior: "smooth" });
    reviseEl.focus();
  };

  const evidenceLine = (m) => `<div class="km-card">
      <div class="row between gap-12"><div class="small-13"><span class="mono muted">${esc(m.id)}</span> ${esc(m.text)}</div><span class="badge ${EVIDENCE_KIND[m.evidence] ?? ""}">${esc(m.evidence)}</span></div>
      ${m.origin ? `<div class="small muted">From ${esc(m.origin)}${(m.slides || []).length ? ` · slides ${m.slides.map(esc).join(", ")}` : ""}</div>` : ""}
      ${m.notes && m.evidence !== "supported" ? `<div class="small-13 muted">${esc(m.notes)}</div>` : ""}
    </div>`;

  // B62: a talking header carries no citation; the validator judges it against the slide's claims.
  const STORY_ISSUE = { unspeakable: "Can't be said aloud", breaks_chain: "Doesn't follow from the slide before", repeats: "Repeats an earlier slide" };
  // B70: advisory storyline findings for this slide's header; they never block.
  const storyNotes = (s) => (s.storyline_findings || []).map((f) => `<div class="note plain">${ICON.info}<span><b>${esc(STORY_ISSUE[f.issue] || f.issue)}.</b> ${esc(f.notes)}</span></div>`).join("");
  const storyLine = (d) => {
    const c = d.storyline_check;
    if (!c) return "";
    const n = (c.findings || []).length;
    return `<div class="note plain">${ICON.info}<span><b>Storyline: ${c.tells_story && !n ? "tells one story" : `${n} issue${n === 1 ? "" : "s"}`}.</b> ${esc(c.summary)} Advisory; it never blocks.</span></div>`;
  };
  const headlineNote = (s) => storyNotes(s) ? headlineVerdict(s) + storyNotes(s) : headlineVerdict(s);
  const headlineVerdict = (s) => {
    const h = s.headline_check;
    if (!h) return `<div class="note plain">${ICON.info}<span>Headline. It cites nothing itself; every fact in it must be stated by a sourced sentence on this slide. Not checked yet.</span></div>`;
    if (h.verdict === "carried") return `<div class="kv"><div class="eyebrow">Checked by</div><div class="row gap-8">${checkMark(true, "sm")}<span class="small-13">Independent check: <b>carried by the slide's claims</b></span></div></div>`;
    setTimeout(() => document.getElementById("fixh")?.addEventListener("click", () => fillChat(`Slide ${s.n}: the headline overstates the slide (${h.notes}). Rewrite it to say only what the slide's claims say.`)));
    return `<div class="note warn">${ICON.warn}<span><b>Headline says more than the slide.</b> ${esc(h.notes)} This blocks the final render.</span></div>
      <div class="row gap-10 wrap"><button type="button" class="btn btn-quiet" id="fixh">Ask AutoDeck to fix</button></div>`;
  };

  const paintInsp = () => {
    const covN = coverageFlag();
    const tabs = [["claim", "Claim"], ["brief", "Brief"], ["outline", "Outline"], ["coverage", "Coverage"]];
    let body = "";
    if (st.tab === "claim") {
      const [s, b] = blockOf(st.block);
      if (!b) body = '<div class="empty">Select a sentence on the slide.</div>';
      else {
        const v = verdictOf(b.verdict);
        const cites = b.citations || [];
        const isClaim = isClaimBlk(b);
        const unsourced = b.basis === "unsourced";
        const unsupported = b.verdict === "unsupported" || b.verdict === "contradicted";
        const fix = unsupported ? `Slide ${s.n}: "${b.text}" is not supported by its source. Narrow it to what the source says, or remove it.`
          : b.verdict === "partially_supported" ? `Slide ${s.n}: reword "${b.text}" to match what the source says`
          : `Slide ${s.n}: tighten the wording of "${b.text}"`;
        body = `
          <div class="row between gap-12 wrap"><span class="mono muted">${esc(b.id)}</span><span class="row gap-8">${unsourced ? '<span class="badge v-amber" title="The model\'s general knowledge, not quoted from a source">unsourced</span>' : ""}${(b.citations || []).some((q) => q.source_class === "conversation") ? '<span class="badge accent">from you</span>' : ""}${isClaim ? vChip(b.verdict || "unverified") : '<span class="badge v-neutral">Framing</span>'}</span></div>
          <div class="claim-text sm">${esc(b.text)}</div>
          ${isClaim ? `
            <div class="kv"><div class="eyebrow">Source</div>
              ${cites.map((q) => `<blockquote class="quote"><div class="quote-text">${esc(q.quote)}</div>
                <div class="small muted"><span class="strong">${esc(docLabel(q.doc_id, q.page))}</span> · ${q.page != null && q.page !== "" ? `p.${esc(q.page)}` : "no page"}</div></blockquote>`).join("")
                || (unsourced
                  ? `<div class="note plain">${ICON.info}<span>General knowledge: the model wrote this without a source. It is checked against your papers; if they do not confirm it, it is marked uncorroborated.</span></div>`
                  : `<div class="note warn">${ICON.warn}<span>No source resolved for this sentence.</span></div>`)}
            </div>
            <div class="kv"><div class="eyebrow">Checked by</div>
              <div class="row gap-8">${checkMark(cites.length > 0, "sm")}<span class="small-13">Code: ${cites.length ? "quote found on its page" : "no citation resolved"}</span></div>
              <div class="row gap-8">${checkMark(b.verdict === "supported", "sm")}<span class="small-13">Independent check: <b>${esc(v.label === "Framing" ? "not checked yet" : v.label)}</b>${b.verdict_notes ? ` — ${esc(b.verdict_notes)}` : ""}</span></div>
            </div>
            <div class="row gap-10 wrap"><button type="button" class="btn btn-quiet" id="fix">Ask AutoDeck to fix</button><button type="button" class="btn btn-outline" id="rm">Remove this claim</button></div>`
          : b.slot === "headline" ? headlineNote(s)
          : `<div class="note plain">${ICON.info}<span>Framing. A connecting line with no factual claim, so it carries no source and no check. It is yours to read.</span></div>`}`;
        setTimeout(() => {
          document.getElementById("fix")?.addEventListener("click", () => fillChat(fix));
          document.getElementById("rm")?.addEventListener("click", () => fillChat(`Slide ${s.n}: remove "${b.text}"`));
        });
      }
    } else if (st.tab === "brief") {
      const br = d.brief || {};
      const f = (l, v) => `<div class="bf"><div class="bf-label">${l}</div><div class="bf-value ${v ? "" : "muted"}">${v ? esc(v) : "Not set"}</div></div>`;
      body = `${f("Objective", br.objective)}${f("Audience", br.audience)}${f("Length", br.length_target ? `${br.length_target} slides` : "")}
        <div class="eyebrow">Key messages</div>${(br.key_messages || []).map(evidenceLine).join("") || '<div class="muted small-13">No key messages.</div>'}
        ${(br.must_include || []).length ? f("Must include", br.must_include.join(" · ")) : ""}${(br.must_avoid || []).length ? f("Must avoid", br.must_avoid.join(" · ")) : ""}
        ${(br.open_risks || []).map((k) => `<div class="risk"><div class="small strong t-warn">Named risk · ${esc(k.message_id)}</div><div class="small-13">${esc(k.description)} · ${esc(k.accepted_by)}</div></div>`).join("")}`;
    } else if (st.tab === "outline") {
      body = d.slides.map((s, i) => `
        <button type="button" class="row-btn ${i === st.slide ? "on" : ""}" data-o="${i}" aria-pressed="${i === st.slide}">
          <span class="tile">${esc(s.n)}</span>
          <span class="row-main"><span class="row-tags"><span class="badge">${esc(s.role)}</span><span class="mono">${esc(s.component)}</span>${(s.message_ids || []).map((m) => `<span class="badge accent">${esc(m)}</span>`).join("")}</span>
          <span class="small-13">${esc(slideTitle(s))}</span><span class="small muted">${esc(s.intent)}</span></span>
        </button>`).join("");
    } else {
      const items = d.coverage || [];
      const odd = (xs) => (xs || []).map((x) => (typeof x === "string" ? x : Object.values(x || {}).filter((v) => typeof v === "string" || typeof v === "number").join(" · ")));
      body = `
        <div class="small-13 muted">Every message you agreed to, and what the draft did with it. Nothing is dropped silently.</div>
        ${storyLine(d)}
        ${items.map((c) => `
          <div class="km-card"><div class="row between gap-12"><div class="small-13">${esc(c.item)}</div><span class="badge ${COVER_KIND[c.status] || ""}">${esc(COVER_LABEL[c.status] || c.status)}</span></div>
          ${c.detail ? `<div class="small muted">${esc(c.detail)}</div>` : ""}</div>`).join("")
          || '<div class="empty">No coverage items were recorded for this draft.</div>'}
        ${failureGroups(d.failures).length
          ? failureGroups(d.failures).map(([label, rows]) => `<div class="eyebrow">${esc(label)}</div>${rows.map((r) => `<div class="small-13 muted">${r.slide_id ? `<span class="mono">${esc(r.slide_id)}</span> · ` : ""}${esc(r.message)}</div>`).join("")}`).join("")
          : (odd(d.rejections).length ? `<div class="eyebrow">Dropped for a citation that did not resolve</div>${odd(d.rejections).map((t) => `<div class="small-13 muted">${esc(t)}</div>`).join("")}` : "")}
        ${odd(d.repairs).length ? `<div class="eyebrow">Repaired</div>${odd(d.repairs).map((t) => `<div class="small-13 muted">${esc(t)}</div>`).join("")}` : ""}
        ${(d.advisories || []).length ? `<div class="eyebrow">Suggestions</div>${d.advisories.map((r) => `<div class="small-13 muted">${r.slide_id ? `<span class="mono">${esc(r.slide_id)}</span> · ` : ""}${esc(r.message ?? r)}</div>`).join("")}` : ""}
        ${odd(d.incomplete_slots).length ? `<div class="eyebrow">Left incomplete</div>${odd(d.incomplete_slots).map((t) => `<div class="small-13 muted">${esc(t)}</div>`).join("")}` : ""}`;
    }
    inspEl.innerHTML = `
      <div class="segmented fill" role="group" aria-label="Inspector">${tabs.map(([k, l]) =>
        `<button type="button" data-t="${k}" ${st.tab === k ? 'aria-current="true"' : ""} aria-pressed="${st.tab === k}">${l}${k === "coverage" && covN ? `<span class="count-badge" aria-label="${covN} to look at">${covN}</span>` : ""}</button>`).join("")}</div>
      <div class="insp-body">${body}</div>`;
  };

  const agentRun = () => agentSess.runId === runId && !!agentSess.data?.timeline?.length;
  const paintChat = () => {
    const turns = (d.revisions || []).flatMap((r) => [
      r.instruction ? { role: "human", text: r.instruction } : null,
      r.reply ? { role: "planner", text: r.reply } : null,
    ]).filter(Boolean);
    if (st.revising && !st.revising.done) turns.push({ role: "human", text: st.revising.instruction });
    chatEl.innerHTML = turns.map((t) => `<div class="bubble ${t.role === "human" ? "human" : "planner"}">${esc(t.text)}</div>`).join("")
      || '<div class="empty">Nothing yet. Ask for a change and only the slides it touches are redone.</div>';
    chatEl.scrollTop = chatEl.scrollHeight;
    reviseEl.placeholder = agentRun()
      ? "The agent that built this deck will make the change"
      : "For example: Slide 2: say what the mechanism does in one line";
  };

  const paintAll = () => { paintHead(); paintFilm(); paintStage(); paintInsp(); paintChat(); };
  paintAll();

  filmEl.addEventListener("click", (e) => {
    const b = e.target.closest("[data-i]");
    if (!b) return;
    st.slide = Number(b.dataset.i); st.block = defaultBlock(); paintFilm(); paintStage(); paintInsp();
  });
  stageEl.addEventListener("click", (e) => {
    const b = e.target.closest("[data-b]");
    if (b) { st.block = b.dataset.b; st.tab = "claim"; paintStage(); paintInsp(); }
  });
  inspEl.addEventListener("click", (e) => {
    const t = e.target.closest("[data-t]");
    if (t) { st.tab = t.dataset.t; paintInsp(); return; }
    const o = e.target.closest("[data-o]");
    if (o) { st.slide = Number(o.dataset.o); st.block = defaultBlock(); paintFilm(); paintStage(); paintInsp(); }
  });
  view.querySelectorAll("[data-sg]").forEach((b) => b.addEventListener("click", () => fillChat(SUGGESTIONS[Number(b.dataset.sg)])));
  reviseEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); document.getElementById("say").requestSubmit(); }
  });

  // ---- revising (the same conversation, after the draft exists) ----
  const revEl = document.getElementById("rev");
  const gridEl = document.getElementById("dr-grid");

  const paintRev = (j) => {
    const rv = st.revising;
    const running = j?.status === "running";
    const failed = j && (j.status === "failed" || j.status === "stopped");
    const finished = !running;
    const steps = (j?.steps?.length ? j.steps : ["revise", "validate", "preview"]);
    const idx = steps.indexOf(j?.step);
    const lastReply = (d.revisions || []).slice(-1)[0]?.reply || "";
    const changed = rv.changed || new Set();
    const cards = d.slides.map((s) => {
      const isNew = changed.has(s.id);
      let tag;
      if (!rv.diffed && !finished) tag = '<div class="rc-state wait">Waiting for the rewrite…</div>';
      else if (isNew) tag = finished && !failed
        ? `<div class="rc-state chg"><span class="badge accent">Changed</span><span class="small muted">${plural((s.blocks || []).filter((b) => isClaimBlk(b)).length, "claim")}</span></div>`
        : '<div class="rc-state run"><span class="spin" aria-hidden="true"></span>Revising…</div>';
      else tag = '<div class="rc-state keep"><span aria-hidden="true">✓</span>Unchanged — verdicts kept</div>';
      return `<div class="rcard ${isNew ? "hot" : ""}"><div class="rc-thumb">${thumbBody(s)}</div><div class="small strong"><span class="mono muted">${esc(s.id)}</span> ${esc(slideTitle(s))}</div>${tag}</div>`;
    }).join("");
    revEl.innerHTML = `
      <div class="grid-2 equal align-start">
        <section class="panel" aria-labelledby="rv-h">
          <div class="panel-head"><h2 class="h2" id="rv-h">The draft · ${d.slides.length} slide${d.slides.length === 1 ? "" : "s"}</h2><span class="row gap-8">${provenanceChip(d.provenance)}${designChip(d.design_mode)}${draftPill()}</span></div>
          <div class="rcards">${cards}</div>
          <div class="note plain">${ICON.info}<span>A revision redoes the slides it touches and nothing else. The other slides keep the checks they already passed.</span></div>
        </section>
        <section class="panel" aria-labelledby="ch-h">
          <div class="panel-head"><h2 class="h2" id="ch-h">${running ? "Revising the draft" : failed ? "The revision stopped" : "Revision done"}</h2><span class="small muted">${running ? "Working" : failed ? "Nothing was changed past this point" : "Finished"}</span></div>
          <div class="bubble human self-start">${esc(rv.instruction)}</div>
          ${finished && !failed && lastReply ? `<div class="bubble planner">${esc(lastReply)}</div>` : ""}
          ${failed ? `<div class="note warn">${ICON.warn}<span>${esc(j.message || "The step failed.")}</span></div>` : ""}
          <div class="stack gap-2"><div class="eyebrow">This revision</div>${steps.map((s, i) => {
            const state = finished ? (failed && i >= Math.max(idx, 0) ? "failed" : "done") : i < idx ? "done" : i === idx ? "running" : "waiting";
            return `<div class="row gap-10 rv-step"><span class="tl-mark st-${state === "failed" ? "failed" : state}" aria-hidden="true">${state === "done" ? "✓" : state === "failed" ? "!" : ""}</span><span class="small-13 ${state === "waiting" ? "muted" : ""}">${esc(REVISE_STEP_LABEL[s] || s)}</span><span class="small muted grow text-right">${state === "done" ? "Done" : state === "running" ? "Running" : state === "failed" ? "Stopped" : "Waiting"}</span></div>`;
          }).join("")}</div>
          <div class="note warn">${ICON.warn}<span>Anything you approved that covers a changed slide stops counting. Approvals for the rest stay.</span></div>
          ${running ? '<div class="bar"><i></i></div>' : ""}
          ${running ? agentTimelineHtml(runId) : agentMetaLine(runId)}
          <div class="row gap-12 wrap">${finished ? '<button class="btn" id="back" type="button">Back to the draft</button>' : ""}<a class="btn btn-quiet" href="#/approve/${enc(runId)}">Review approvals</a></div>
        </section>
      </div>`;
    const back = document.getElementById("back");
    if (back) back.addEventListener("click", () => leaveRevising());
    bindAgentToggle(revEl, () => paintRev(j));
  };

  const leaveRevising = () => {
    st.revising = null;
    revEl.hidden = true; gridEl.hidden = false;
    sendBtn.disabled = false; reviseEl.disabled = false;
    st.slide = Math.min(st.slide, Math.max(0, d.slides.length - 1));
    st.block = defaultBlock();
    paintAll();
  };

  const refreshDraft = async () => { try { d = await api(`/api/runs/${enc(runId)}/draft`); } catch { /* keep the last one */ } };

  const beginRevising = (instruction, j) => {
    const before = new Map(d.slides.map((s) => [s.id, sigOf(s)]));
    st.revising = { instruction, before, diffed: false, changed: new Set(), done: false };
    gridEl.hidden = true; revEl.hidden = false;
    sendBtn.disabled = true; reviseEl.disabled = true;
    paintRev(j);
    paintChat();
    stopPolling();
    pollTimer = setInterval(async () => {
      if (!location.hash.startsWith(`#/draft/${enc(runId)}`)) { stopPolling(); return; }
      try {
        const res = await api(`/api/runs/${enc(runId)}/job`);
        const cur = res.job;
        await loadAgentSession(runId);
        const rv = st.revising;
        if (!rv) { stopPolling(); return; }
        const running = cur?.status === "running";
        if (cur && (!running || cur.step !== "revise") && !rv.diffed) {
          await refreshDraft();
          rv.changed = new Set(d.slides.filter((s) => rv.before.get(s.id) !== sigOf(s)).map((s) => s.id));
          rv.diffed = true;
        }
        if (!running) {
          stopPolling();
          await refreshDraft();
          rv.changed = new Set(d.slides.filter((s) => rv.before.get(s.id) !== sigOf(s)).map((s) => s.id));
          rv.done = true;
          paintHead(); paintChat();
        }
        paintRev(cur);
      } catch { /* keep polling */ }
    }, 1500);
  };

  document.getElementById("say").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = reviseEl.value.trim();
    if (!text) return;
    sendBtn.disabled = true;
    try {
      const res = await api(`/api/runs/${enc(runId)}/chat`, { text });
      if (res.mode === "revise") {
        reviseEl.value = "";
        beginRevising(text, res.job);
      } else {
        toast("The conversation took that as planning input. Nothing was revised.", true);
        sendBtn.disabled = false;
      }
    } catch (err) {
      sendBtn.disabled = false;
      toast(err.message, true);
    }
  });

  // Opened while a job is already running for this run.
  if (job?.status === "running") {
    if ((job.steps || []).includes("revise")) {
      beginRevising("Revising the draft", job);
    } else if ((job.steps || []).some((s) => DRAFT_STEPS.includes(s))) {
      const ban = document.getElementById("dr-banner");
      ban.hidden = false;
      ban.className = "note";
      ban.innerHTML = `${ICON.info}<span>Still ${esc(String(job.step_label || "working").toLowerCase())}. Slides and checks fill in as they finish.</span>`;
      stopPolling();
      pollTimer = setInterval(async () => {
        if (!location.hash.startsWith(`#/draft/${enc(runId)}`)) { stopPolling(); return; }
        try {
          const res = await api(`/api/runs/${enc(runId)}/job`);
          if (!res.job || res.job.status !== "running") { stopPolling(); route(); }
        } catch { /* keep waiting */ }
      }, 2000);
    }
  }
}

// ---- approve on the draft ---------------------------------------------------------

async function approveDraftView(runId) {
  setNav("runs");
  const [d, r] = await Promise.all([api(`/api/runs/${enc(runId)}/draft`), runSummary(runId)]);
  const gate = (k) => (r?.gates || []).find((g) => g.gate === k) || {};
  const ok = {
    brief: !!(gate("brief").approved ?? d.approvals?.brief?.approved),
    outline: !!(gate("outline").approved ?? d.approvals?.outline?.approved),
    claims: !!(gate("claims").approved ?? d.approvals?.claims?.approved),
    final: !!(gate("final_render").approved ?? d.approvals?.final?.approved),
  };
  const by = (k) => {
    const g = gate(k === "final" ? "final_render" : k);
    return g.approved ? `Approved by ${esc(g.by || "—")}${g.at ? " · " + esc(g.at) : ""}` : "";
  };
  const br = d.brief || {};
  const msgs = br.key_messages || [];
  const weak = msgs.filter((m) => m.evidence === "thin" || m.evidence === "unsupported");
  const c = draftCounts(d);
  const audited = (r?.stage_list || []).find((s) => s.key === "final_audit")?.status === "done";
  const prev = ok.brief, prevO = ok.outline;
  const all3 = ok.brief && ok.outline && ok.claims;
  const status = (k, unlocked) => (ok[k] ? "done" : unlocked ? "active" : "locked");
  const sBrief = status("brief", true), sOutline = status("outline", prev), sClaims = status("claims", prevO);

  const num = (n, s) => `<div class="ap-num ${s}" aria-hidden="true">${s === "done" ? "✓" : n}</div>`;
  const actionFor = (key, s, lockNote, label = "Approve &amp; proceed") => {
    if (s === "done") return `<div class="ap-done"><span class="check-mark ok sm" aria-hidden="true">✓</span><b>Approved</b></div><div class="small muted">${by(key)}</div>`;
    if (s === "locked") return `<button class="btn" type="button" disabled>${label}</button><div class="small muted">${esc(lockNote)}</div>`;
    return `<button class="btn" type="button" id="ap-${key}">${label}</button>`;
  };

  view.innerHTML = `
    <div class="page-head">
      <div class="head-text">
        <div class="crumbs"><a href="#/runs">Runs</a> / <a href="#/draft/${enc(runId)}">${esc(runId)}</a> / Approve the draft</div>
        <h1 class="page-title">Approve the draft</h1>
        <p class="page-sub">Each approval covers the draft exactly as it is now. Change something later and only what it touches needs approving again.</p>
      </div>
      <a class="btn btn-quiet" href="#/draft/${enc(runId)}">Back to the draft</a>
    </div>
    <div class="grid-2 align-start">
      <div class="stack gap-14">
        <section class="panel ap-card ${sBrief}" aria-labelledby="ap-brief-h">
          ${num(1, sBrief)}
          <div class="ap-body">
            <h2 class="h2" id="ap-brief-h">Brief</h2>
            ${br.objective ? `<div class="small-13"><span class="strong">Objective</span> · ${esc(br.objective)}</div>` : ""}
            ${br.audience ? `<div class="small-13"><span class="strong">Audience</span> · ${esc(br.audience)}</div>` : ""}
            <div class="stack gap-8" id="ap-msgs">${msgs.map((m) => {
              const isWeak = m.evidence === "thin" || m.evidence === "unsupported";
              const risk = (br.open_risks || []).find((k) => k.message_id === m.id);
              return `<div class="km-card">
                <div class="row between gap-12"><div class="small-13"><span class="mono muted">${esc(m.id)}</span> ${esc(m.text)}</div><span class="badge ${EVIDENCE_KIND[m.evidence] ?? ""}">${esc(m.evidence)}</span></div>
                ${isWeak ? (sBrief === "done" || risk
                  ? `<div class="small-13 muted">${risk ? `Carried as a named risk · ${esc(risk.accepted_by)}` : esc(m.notes || "")}</div>`
                  : `<div class="small-13 muted">${esc(m.notes || (m.evidence === "unsupported" ? "No source backs this message yet." : "Only one non-curated source backs this."))}</div>
                     <div class="tick"><input type="checkbox" id="risk-${esc(m.id)}" data-risk="${esc(m.id)}"><label for="risk-${esc(m.id)}">Carry as a named risk</label></div>
                     <label class="field reword" id="rw-${esc(m.id)}" hidden>Say in a line how you are carrying it (optional)
                       <input class="input" data-reword="${esc(m.id)}" maxlength="160" placeholder="e.g. Stated as ongoing work, not a result"></label>`) : ""}
              </div>`;
            }).join("") || '<div class="muted small-13">No key messages.</div>'}</div>
            <div id="ap-brief-note" hidden></div>
          </div>
          <div class="ap-act">${actionFor("brief", sBrief, "")}</div>
        </section>
        <section class="panel ap-card ${sOutline}" aria-labelledby="ap-outline-h">
          ${num(2, sOutline)}
          <div class="ap-body"><h2 class="h2" id="ap-outline-h">Outline</h2>
            ${d.slides.map((s) => `<div class="small-13"><span class="mono muted">${esc(s.id)}</span> ${esc(slideTitle(s))}</div>`).join("")}
            <div id="ap-outline-note" hidden></div></div>
          <div class="ap-act">${actionFor("outline", sOutline, "Approve the brief first")}</div>
        </section>
        <section class="panel ap-card ${sClaims}" aria-labelledby="ap-claims-h">
          ${num(3, sClaims)}
          <div class="ap-body"><h2 class="h2" id="ap-claims-h">Claims</h2>
            <div class="chips-row"><span class="chip">${plural(c.claims, "claim")}</span><span class="chip"><span class="dot dot-ok"></span>${c.supported} supported</span>
              <span class="chip"><span class="dot dot-warn"></span>${c.partial} partial</span><span class="chip"><span class="dot dot-bad"></span>${c.unsupported} unsupported</span></div>
            ${c.partial + c.unsupported ? '<div class="small-13 muted">Each one is shown in the draft with the checker\'s note.</div>' : ""}
            <a class="small-13 strong" href="#/draft/${enc(runId)}">Read them in the draft</a>
            <div id="ap-claims-note" hidden></div></div>
          <div class="ap-act">${actionFor("claims", sClaims, "Approve the outline first")}</div>
        </section>
        <section class="panel ap-card ${all3 ? "active" : "locked"}" aria-labelledby="ap-final-h">
          ${num(4, ok.final ? "done" : all3 ? "active" : "locked")}
          <div class="ap-body"><h2 class="h2" id="ap-final-h">Final deck</h2>
            <div class="small-13 muted">Art direction and critique, then your five checks in PowerPoint and the last approval.</div>
            <div id="ap-final-note" hidden></div></div>
          <div class="ap-act">${ok.final
            ? `<div class="ap-done"><span class="check-mark ok sm" aria-hidden="true">✓</span><b>Approved</b></div><div class="small muted">${by("final")}</div>`
            : audited ? `<a class="btn" href="#/final/${enc(runId)}">Open the final deck</a>`
            : all3 ? '<button class="btn" type="button" id="ap-final">Build the final deck</button>'
            : '<button class="btn" type="button" disabled>Build the final deck</button><div class="small muted">Locked until the three are approved</div>'}</div>
        </section>
      </div>
      <section class="panel tight">
        <h2 class="h2">Draft vs final</h2>
        <div class="row gap-10 top"><span class="badge warn">Draft</span><div class="small-13">Previews marked Draft. Never exported.</div></div>
        <div class="row gap-10 top"><span class="badge ok">Final</span><div class="small-13">Made after the approvals and art-directed. A deck.pptx with the audit report and manifest.</div></div>
        <div class="note plain">${ICON.lock}<span>Every approval records your name and a fingerprint of what you saw.</span></div>
      </section>
    </div>`;

  const post = async (btn, noteId, body, done) => {
    btn.disabled = true;
    const note = document.getElementById(noteId);
    try {
      await api(`/api/runs/${enc(runId)}/approve`, body);
      toast(done);
      route();
    } catch (err) {
      btn.disabled = false;
      if (note) {
        note.hidden = false;
        note.className = "note warn";
        note.innerHTML = `${ICON.warn}<span>${esc(err.message)}</span>`;
      } else toast(err.message, true);
    }
  };

  view.querySelectorAll("[data-risk]").forEach((box) => box.addEventListener("change", () => {
    const rw = document.getElementById(`rw-${box.dataset.risk}`);
    if (rw) rw.hidden = !box.checked;
  }));
  const b1 = document.getElementById("ap-brief");
  if (b1) b1.addEventListener("click", () => {
    const risks = {};
    weak.forEach((m) => {
      const box = view.querySelector(`[data-risk="${CSS.escape(m.id)}"]`);
      if (box?.checked) {
        const rw = view.querySelector(`[data-reword="${CSS.escape(m.id)}"]`)?.value.trim();
        risks[m.id] = rw || m.notes || `Evidence is ${m.evidence}`;
      }
    });
    post(b1, "ap-brief-note", { gate: "brief", accepted_risks: risks }, "Brief approved.");
  });
  const b2 = document.getElementById("ap-outline");
  if (b2) b2.addEventListener("click", () => post(b2, "ap-outline-note", { gate: "outline" }, "Outline approved."));
  const b3 = document.getElementById("ap-claims");
  if (b3) b3.addEventListener("click", () => post(b3, "ap-claims-note", { gate: "claims" }, "Claims approved."));
  const b4 = document.getElementById("ap-final");
  if (b4) b4.addEventListener("click", async () => {
    b4.disabled = true;
    try {
      await api(`/api/runs/${enc(runId)}/run`, { stage: "render" });
      location.hash = runHref(runId);
    } catch (err) {
      b4.disabled = false;
      actionError(document.getElementById("ap-final-note"), err, runId);
    }
  });
}

// ---- router ---------------------------------------------------------------

async function route() {
  stopPolling();
  const hash = location.hash.replace(/^#/, "") || "/";
  const parts = hash.split("/").filter(Boolean).map(decodeURIComponent);
  const runId = parts[1] || "";
  try {
    if (parts.length === 0) await homeView();
    else if ((parts[0] === "run" || parts[0] === "runs") && runId) await runView(runId);
    else if (parts[0] === "runs") await runsView();
    else if (parts[0] === "plan" && runId) await planView(runId);
    else if (parts[0] === "clarify" && runId) await clarifyView(runId);
    else if (parts[0] === "draft" && runId) await draftView(runId);
    else if (parts[0] === "approve" && runId) await approveDraftView(runId);
    else if (parts[0] === "outline" && runId) await outlineView(runId);
    else if (parts[0] === "claims" && runId) await claimsView(runId);
    else if (parts[0] === "final" && runId) await finalView(runId);
    else if (parts[0] === "knowledge") await knowledgeView();
    else if (parts[0] === "clients") await newClientView();
    else if (parts[0] === "redesign") redesignView();
    else if (parts[0] === "settings") await settingsView(parts[1]);
    else await homeView();
  } catch (err) {
    if (err.status === 409 && runId) notReadyView(err, runId);
    else view.innerHTML = `<div class="note bad">${ICON.info}<span>${esc(err.message)}</span></div>`;
  }
  view.focus({ preventScroll: true });
}

// Views that do not list runs still show the sidebar's recent runs; refreshed on every
// navigation so a run started a moment ago is there when you leave it.
const refreshRecent = () => api("/api/runs").then((d) => renderRecent(d.runs)).catch(() => {});
window.addEventListener("hashchange", () => { route(); refreshRecent(); });
route();
refreshRecent();
