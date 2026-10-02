// AutoDeck review UI (B40). Plain JS, no build step, no downloads.
// Every action goes through the local API in autodeck/ui/server.py, which calls the
// same code the CLI does. Nothing here can approve a gate by itself (A7, B39).
"use strict";

const view = document.getElementById("view");
const toastEl = document.getElementById("toast");

// ---- helpers --------------------------------------------------------------

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);

async function api(path, body) {
  const init = body === undefined
    ? { method: "GET" }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, init);
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
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

const ICON = {
  lock: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
  info: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.5"/></svg>',
  upload: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg>',
};

const STAGES = ["brief", "outline", "claims", "final"];

function stepsHtml(stages) {
  return `<div class="steps" aria-label="Approvals">${STAGES.map((s) =>
    `<div class="step ${esc(stages?.[s] || "todo")}" title="${esc(s)}: ${esc(stages?.[s] || "todo")}"></div>`
  ).join("")}</div>`;
}

function tierChip(env) {
  if (!env) return "";
  const draft = env.name === "dev";
  return `<a class="chip" href="#/settings"><span class="dot" style="background:${draft ? "var(--warn-dot)" : "var(--ok-dot)"}"></span>${esc(env.label)} · change in Settings</a>`;
}

function setNav(key) {
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.dataset.nav === key) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}

function renderRecent(runs) {
  document.getElementById("recent").innerHTML = (runs || []).slice(0, 5).map((r) =>
    `<a class="nav-sub" href="#/runs/${encodeURIComponent(r.id)}">${esc(r.id)}</a>`
  ).join("") || '<div class="nav-sub muted">No runs yet</div>';
}

function runRows(runs) {
  if (!runs.length) return '<div class="empty">No runs yet. Start a planning session above.</div>';
  return `
    <div class="table-head"><div>Run</div><div>Client</div><div>Brief · Outline · Claims · Final</div><div></div></div>
    ${runs.map((r) => `
      <div class="table-row">
        <div><div class="cell-title">${esc(r.id)}</div><div class="cell-sub">${esc(r.next)}</div></div>
        <div class="cell-sub" style="font-size:13px;color:var(--text-2)">${esc(r.client || "—")}</div>
        ${stepsHtml(r.stages)}
        <a class="btn btn-pill" style="justify-self:end" href="#/runs/${encodeURIComponent(r.id)}">Open</a>
      </div>`).join("")}`;
}

// ---- views ----------------------------------------------------------------

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
        <h1 class="page-title">Start a deck</h1>
        <p class="page-sub">Every slide traceable to a source. Four approvals, all yours.</p>
      </div>
      ${tierChip(data.env)}
    </div>
    <div class="grid-2">
      <form class="panel" id="plan-form">
        <div class="segmented" role="tablist" aria-label="Start from">
          <button type="button" role="tab" aria-selected="true">From research</button>
          <a role="tab" aria-selected="false" href="#/redesign">From an existing deck</a>
        </div>
        <div class="grid-even" style="gap:16px">
          <label class="field">Client
            <select class="select" name="client" required>${clientOpts}</select>
            <a class="field-hint" href="#/clients/new">New client…</a>
          </label>
          <label class="field">Project
            <select class="select" name="project" required>${projectOpts}</select>
          </label>
          <label class="field" style="grid-column:1/-1">Run name
            <input class="input" name="run_id" required pattern="[A-Za-z0-9][A-Za-z0-9._-]*" placeholder="e.g. contoso-board-q4">
            <span class="field-hint">Letters, numbers, dots, dashes and underscores.</span>
          </label>
        </div>
        <div class="note">${ICON.lock}<span>Only this client's knowledge is loaded. Nothing from other clients reaches the models.</span></div>
        <div class="row" style="justify-content:space-between">
          <span class="muted" style="font-size:13px">Opens a conversation with the planner. You sign the brief when it is right.</span>
          <button class="btn" type="submit" ${data.clients.length && data.projects.length ? "" : "disabled"}>Start planning</button>
        </div>
      </form>
      <section class="panel" style="gap:4px" aria-labelledby="ready-h">
        <div class="panel-head" style="padding-bottom:10px">
          <h2 class="h2" id="ready-h">Ready to build</h2>
          <span style="font-size:13px;font-weight:600;color:${toFix ? "var(--warn)" : "var(--ok)"}">${toFix ? `${toFix} to fix` : "All set"}</span>
        </div>
        ${data.checks.map((c) => `
          <div class="check">
            <div class="check-mark" style="background:${c.ok ? "var(--ok-dot)" : "var(--warn-dot)"}" aria-hidden="true">${c.ok ? "✓" : "!"}</div>
            <div class="check-body">
              <div class="check-name">${esc(c.name)}<span class="sr-only">${c.ok ? " — ready" : " — needs fixing"}</span></div>
              <div class="check-note">${esc(c.note)}</div>
              ${!c.ok && c.fix ? `<div class="check-note mono">${esc(c.fix)}</div>` : ""}
            </div>
          </div>`).join("")}
      </section>
    </div>
    <section class="panel" style="gap:0" aria-labelledby="runs-h">
      <div class="panel-head" style="padding-bottom:12px">
        <h2 class="h2" id="runs-h">Continue where you left off</h2>
        <a href="#/runs" style="font-size:13px;font-weight:500">All runs</a>
      </div>
      ${runRows(data.runs.slice(0, 5))}
    </section>`;

  document.getElementById("plan-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    const body = Object.fromEntries(form.entries());
    try {
      const res = await api("/api/plan/start", body);
      location.hash = `#/plan/${encodeURIComponent(res.run_id)}`;
    } catch (err) {
      toast(err.message, true);
    }
  });
}

async function runsView() {
  setNav("runs");
  const data = await api("/api/runs");
  renderRecent(data.runs);
  view.innerHTML = `
    <div class="page-head"><div>
      <h1 class="page-title">Runs</h1>
      <p class="page-sub">Every deck you have started, and what each one is waiting for.</p>
    </div></div>
    <section class="panel" style="gap:0">${runRows(data.runs)}</section>`;
}

async function runView(runId) {
  setNav("runs");
  const r = await api(`/api/runs/${encodeURIComponent(runId)}`);
  view.innerHTML = `
    <div class="page-head">
      <div>
        <p class="page-sub" style="margin:0 0 4px">${esc(r.client || "")}${r.project ? " · " + esc(r.project) : ""}</p>
        <h1 class="page-title">${esc(r.id)}</h1>
      </div>
      ${r.env ? `<span class="chip"><span class="dot" style="background:${r.env === "dev" ? "var(--warn-dot)" : "var(--ok-dot)"}"></span>Built on ${esc(r.env)}</span>` : ""}
    </div>
    <section class="panel">
      <h2 class="h2">${esc(r.next)}</h2>
      ${stepsHtml(r.stages)}
      <div class="grid-even" style="gap:12px">
        ${r.gates.map((g) => `
          <div class="check" style="border-top:1px solid var(--hairline)">
            <div class="check-mark" style="background:${g.approved ? "var(--ok-dot)" : "var(--fill-strong)"}" aria-hidden="true">${g.approved ? "✓" : ""}</div>
            <div class="check-body">
              <div class="check-name">${esc(g.label)}</div>
              <div class="check-note">${g.approved ? `Approved by ${esc(g.by || "—")}${g.at ? " · " + esc(g.at) : ""}` : "Not approved"}</div>
            </div>
          </div>`).join("")}
      </div>
      ${r.resume ? `<div class="row-end"><a class="btn" href="${esc(r.resume)}">Continue</a></div>` : ""}
    </section>
    ${r.command_hint ? `<div class="note">${ICON.info}<span>Next step from a terminal: <span class="mono">${esc(r.command_hint)}</span></span></div>` : ""}`;
}

async function planView(runId) {
  setNav("home");
  const s = await api(`/api/plan/${encodeURIComponent(runId)}`);
  view.innerHTML = `
    <div class="page-head">
      <div>
        <p class="page-sub" style="margin:0 0 4px">${esc(s.client)} · ${esc(s.project)}</p>
        <h1 class="page-title">Planning: ${esc(s.run_id)}</h1>
      </div>
      <span class="chip">${s.signed ? "Brief signed" : "Draft, not signed"}</span>
    </div>
    <div class="grid-2" style="align-items:start">
      <section class="panel" aria-label="Conversation">
        <div id="chat" class="stack" style="gap:12px;max-height:56vh;overflow-y:auto"></div>
        <form id="say" class="row">
          <label class="sr-only" for="say-text">Message</label>
          <input class="input" id="say-text" autocomplete="off" placeholder="Tell the planner about the deck" ${s.signed ? "disabled" : ""}>
          <button class="btn" type="submit" ${s.signed ? "disabled" : ""}>Send</button>
        </form>
      </section>
      <section class="panel" aria-labelledby="brief-h">
        <h2 class="h2" id="brief-h">Draft brief</h2>
        <pre id="draft" class="mono" style="white-space:pre-wrap;margin:0;line-height:1.5">${esc(s.draft || "Nothing drafted yet.")}</pre>
        <form id="sign" class="stack" style="gap:10px" ${s.signed ? "hidden" : ""}>
          <label class="field">Sign as
            <input class="input" name="name" required placeholder="Your name">
          </label>
          <button class="btn" type="submit">Sign the brief</button>
          <span class="field-hint">Signing is approval 1 of 4. The planner cannot sign for you.</span>
        </form>
      </section>
    </div>`;

  const chat = document.getElementById("chat");
  const paint = (turns) => {
    chat.innerHTML = turns.map((t) => `
      <div style="align-self:${t.role === "human" ? "flex-end" : "flex-start"};max-width:85%;padding:10px 14px;border-radius:14px;line-height:1.5;white-space:pre-wrap;background:${t.role === "human" ? "var(--btn)" : "var(--fill)"};color:${t.role === "human" ? "var(--on-accent)" : "var(--text)"}">${esc(t.text)}</div>`
    ).join("") || '<div class="empty">Say what the deck is for and who will see it.</div>';
    chat.scrollTop = chat.scrollHeight;
  };
  paint(s.transcript);

  document.getElementById("say").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("say-text");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    input.disabled = true;
    paint([...s.transcript, { role: "human", text }, { role: "planner", text: "…" }]);
    try {
      const next = await api(`/api/plan/${encodeURIComponent(runId)}/say`, { text });
      Object.assign(s, next);
      paint(s.transcript);
      document.getElementById("draft").textContent = s.draft || "Nothing drafted yet.";
    } catch (err) {
      paint(s.transcript);
      toast(err.message, true);
    } finally {
      input.disabled = false;
      input.focus();
    }
  });

  document.getElementById("sign").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = new FormData(event.target).get("name");
    try {
      await api(`/api/plan/${encodeURIComponent(runId)}/sign`, { name });
      toast("Brief signed.");
      route();
    } catch (err) {
      toast(err.message, true);
    }
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

async function settingsView() {
  setNav("settings");
  const data = await api("/api/settings");
  view.innerHTML = `
    <div class="page-head"><div>
      <h1 class="page-title">Settings</h1>
      <p class="page-sub">Applies to new runs started from this window.</p>
    </div></div>
    <section class="panel" style="max-width:720px">
      <h2 class="h2">Models</h2>
      <div class="segmented" role="radiogroup" aria-label="Model tier">
        ${data.envs.map((e) => `<button type="button" role="radio" aria-selected="${e.name === data.env.name}" aria-checked="${e.name === data.env.name}" data-env="${esc(e.name)}">${esc(e.label)}</button>`).join("")}
      </div>
      <div class="note ${data.env.name === "dev" ? "warn" : ""}">${ICON.info}<span>${esc(data.env.note)}</span></div>
      ${data.env.missing_credentials.length ? `<div class="note bad">${ICON.info}<span>Missing keys: <span class="mono">${data.env.missing_credentials.map(esc).join(", ")}</span></span></div>` : ""}
      <div>${data.env.roles.map((r) => `<div class="check"><div class="check-body"><div class="check-name">${esc(r.role)}</div><div class="check-note mono">${esc(r.provider)} · ${esc(r.model)}</div></div></div>`).join("")}</div>
    </section>`;
  view.querySelectorAll("[data-env]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api("/api/settings", { env: b.dataset.env });
      settingsView();
    } catch (err) { toast(err.message, true); }
  }));
}

// ---- router ---------------------------------------------------------------

async function route() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const parts = hash.split("/").filter(Boolean).map(decodeURIComponent);
  try {
    if (parts.length === 0) await homeView();
    else if (parts[0] === "runs" && parts[1]) await runView(parts[1]);
    else if (parts[0] === "runs") await runsView();
    else if (parts[0] === "plan" && parts[1]) await planView(parts[1]);
    else if (parts[0] === "clients") await newClientView();
    else if (parts[0] === "redesign") redesignView();
    else if (parts[0] === "settings") await settingsView();
    else await homeView();
  } catch (err) {
    view.innerHTML = `<div class="note bad">${ICON.info}<span>${esc(err.message)}</span></div>`;
  }
  view.focus({ preventScroll: true });
}

window.addEventListener("hashchange", route);
route();
// Views that do not list runs still show the sidebar's recent runs.
api("/api/runs").then((d) => renderRecent(d.runs)).catch(() => {});
