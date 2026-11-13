/* AutoDeck studio front end. Plain JavaScript, no libraries, no build step, no inline
   handlers (the CSP forbids inline script). Contract: docs/phases/V3-PHASE-1.md,
   "Front-end contract". */
"use strict";

(function () {
  // ------------------------------------------------------------------ helpers
  const $ = (id) => document.getElementById(id);

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
        else if (v === true) el.setAttribute(k, "");
        else el.setAttribute(k, v);
      }
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  function add(el, ...kids) {
    for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) el.append(k.nodeType ? k : document.createTextNode(String(k)));
    return el;
  }

  function clear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
    return el;
  }

  function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return String(iso);
    return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function plural(n, one, many) {
    return n + " " + (n === 1 ? one : many || one + "s");
  }

  let toastTimer = null;
  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 6500);
  }

  class ApiError extends Error {
    constructor(status, code, message) {
      super(message);
      this.status = status;
      this.code = code;
    }
  }

  async function api(method, path, body) {
    const opts = { method, headers: {} };
    if (method !== "GET") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body || {});
    }
    let res;
    try {
      res = await fetch(path, opts);
    } catch (e) {
      throw new ApiError(0, "network", "Could not reach the studio server.");
    }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      const err = data && data.error;
      throw new ApiError(res.status, (err && err.code) || "error",
        (err && err.message) || "The request failed (" + res.status + ").");
    }
    return data;
  }

  const enc = encodeURIComponent;
  const engPath = (c, p) => "/api/engagements/" + enc(c) + "/" + enc(p);
  const engHash = (c, p) => "#/e/" + enc(c) + "/" + enc(p);
  const threadHash = (c, p, t) => engHash(c, p) + "/t/" + enc(t);

  // A diff line from the API ("+ slides[s2] = {...}", "~ a.b: 'x' -> 'y'", "- path") in words.
  function unquote(v) {
    v = String(v).trim();
    if (v.length > 1 && v[0] === "'" && v[v.length - 1] === "'") v = v.slice(1, -1);
    return v;
  }
  function readablePath(path) {
    return path
      .replace(/slides\[(\w+)\]/g, "slide $1")
      .replace(/\.points\[\w+\]/g, " point")
      .replace(/\.blocks\[(\w+)\]/g, ", $1 block")
      .replace(/\.(?=\w)/g, ", ")
      .replace(/_/g, " ");
  }
  function objectGist(v) {
    // The first readable string inside a (possibly clipped) JSON object, skipping the id.
    const re = /"(\w+)":\s*"((?:[^"\\]|\\.)*)("|$)/g;
    let m;
    while ((m = re.exec(v))) if (m[1] !== "id") return m[2].replace(/\\"/g, '"').trim();
    return "";
  }
  function describeLine(line) {
    const m = /^([+~-])\s+(.*)$/s.exec(line || "");
    if (!m) return String(line || "").trim();
    const [, sign, rest] = m;
    const idOf = (v) => { const x = /"id":\s*"(\w+)"/.exec(v); return x ? x[1] : null; };
    if (sign === "+") {
      const eq = rest.indexOf(" = ");
      const path = eq < 0 ? rest : rest.slice(0, eq);
      const val = eq < 0 ? "" : rest.slice(eq + 3);
      const id = idOf(val);
      const what = readablePath(path.replace(/\[\d+\]/, id ? "[" + id + "]" : "")).replace(/^(slide|storyline point)\s+(\w+)$/, "$1 $2");
      const gist = objectGist(val);
      return "Added " + what + (gist ? ": " + gist : "");
    }
    if (sign === "-") return "Removed " + readablePath(rest.split(" = ")[0]);
    const colon = rest.indexOf(": ");
    if (colon < 0) return "Changed " + readablePath(rest);
    const path = readablePath(rest.slice(0, colon));
    const arrow = rest.slice(colon + 2).split(" -> ");
    if (arrow.length < 2) return "Changed " + path;
    const from = unquote(arrow[0]);
    const to = arrow.slice(1).join(" -> ").trim();
    const toText = to.startsWith("{") ? objectGist(to) || "set" : unquote(to);
    if (from === "null") return "Set " + path + (toText ? ": " + toText : "");
    return "Changed " + path + ": " + from + " \u2192 " + toText;
  }
  // The headline for a change entry: what changed, first diff line, plus a count of the rest.
  function changeHeadline(e) {
    const lines = (e && e.lines) || [];
    if (!lines.length) return (e && (e.instruction || e.id)) || "";
    return describeLine(lines[0]) + (lines.length > 1 ? " (+" + (lines.length - 1) + " more)" : "");
  }

  function threadTitle(s) {
    const t = ((s && s.title) || "").trim();
    return t || (s && s.preview) || "New thread";
  }

  function markerTag(marker) {
    if (marker === "provisional") return h("span", { class: "tag tag-prov", text: "Provisional" });
    if (marker === "stale") return h("span", { class: "tag tag-stale", text: "Stale" });
    return null;
  }

  // ------------------------------------------------------------------ app state
  const app = { health: null, thread: null };

  function setCrumb(c, p) {
    const el = $("crumb");
    if (c) {
      el.textContent = c + " · " + p;
      el.href = engHash(c, p);
      el.hidden = false;
    } else {
      el.hidden = true;
    }
  }

  async function loadHealth() {
    try {
      app.health = await api("GET", "/api/health");
      $("model-id").textContent = app.health.model_id || "";
      $("scripted-tag").hidden = !app.health.scripted;
    } catch (e) {
      toast(e.message);
    }
  }

  // ------------------------------------------------------------------ router
  function parseHash() {
    const raw = location.hash.replace(/^#/, "");
    const parts = raw.split("/").filter(Boolean).map((s) => {
      try { return decodeURIComponent(s); } catch (e) { return s; }
    });
    if (parts[0] === "e" && parts.length >= 3) {
      if (parts[3] === "t" && parts[4]) return { name: "thread", client: parts[1], project: parts[2], thread: parts[4] };
      return { name: "engagement", client: parts[1], project: parts[2] };
    }
    return { name: "home" };
  }

  let routeToken = 0;
  async function route() {
    const token = ++routeToken;
    teardownThread();
    const r = parseHash();
    for (const id of ["view-home", "view-engagement", "view-thread"]) $(id).hidden = true;
    setCrumb(r.client, r.project);
    document.title = "AutoDeck";
    if (r.name === "home") await showHome(token);
    else if (r.name === "engagement") await showEngagement(r, token);
    else await showThread(r, token);
  }

  // ------------------------------------------------------------------ engagements
  function names(list, key) {
    const out = [];
    for (const item of list || []) {
      if (typeof item === "string") out.push({ name: item });
      else if (item && typeof item === "object") {
        out.push({ name: item.name || item[key] || item.id || "", client: item.client });
      }
    }
    return out.filter((x) => x.name);
  }

  async function showHome(token) {
    const view = $("view-home");
    view.hidden = false;
    clear(view).append(h("div", { class: "scroll", id: "home-scroll" }, h("div", { class: "page-inner" }, h("p", { class: "muted", text: "Loading." }))));
    let data;
    try { data = await api("GET", "/api/engagements"); } catch (e) {
      if (token !== routeToken) return;
      clear(view).append(h("div", { class: "scroll" }, h("div", { class: "page-inner" }, h("p", { class: "err-line", text: e.message }))));
      return;
    }
    if (token !== routeToken) return;
    const engs = data.engagements || [];
    const clients = names((data.knowledge || {}).clients, "client");
    const projects = names((data.knowledge || {}).projects, "project");

    const cIn = h("input", { class: "input", id: "f-client", list: "dl-client", autocomplete: "off", required: true, spellcheck: "false" });
    const pIn = h("input", { class: "input", id: "f-project", list: "dl-project", autocomplete: "off", required: true, spellcheck: "false" });
    const tIn = h("input", { class: "input", id: "f-title", autocomplete: "off", placeholder: "Optional" });
    const dlC = h("datalist", { id: "dl-client" }, clients.map((c) => h("option", { value: c.name })));
    const dlP = h("datalist", { id: "dl-project" });
    const fillProjects = () => {
      clear(dlP);
      const c = cIn.value.trim();
      const scoped = projects.filter((p) => !p.client || !c || p.client === c);
      for (const p of scoped) dlP.append(h("option", { value: p.name }));
    };
    cIn.addEventListener("input", fillProjects);
    fillProjects();
    const submit = h("button", { class: "btn primary", type: "submit", text: "Create engagement" });
    const form = h("form", { class: "form", novalidate: true },
      h("div", { class: "field" }, h("label", { for: "f-client", text: "Client" }), cIn, dlC),
      h("div", { class: "field" }, h("label", { for: "f-project", text: "Project" }), pIn, dlP),
      h("div", { class: "field" }, h("label", { for: "f-title", text: "Title" }), tIn),
      submit);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const client = cIn.value.trim();
      const project = pIn.value.trim();
      if (!client || !project) { toast("Choose a client and a project."); return; }
      const body = { client, project };
      if (tIn.value.trim()) body.title = tIn.value.trim();
      submit.disabled = true;
      try {
        const res = await api("POST", "/api/engagements", body);
        location.hash = engHash(res.engagement.client, res.engagement.project);
      } catch (e) {
        if (e.code === "conflict") {
          toast("That engagement already exists; opening it.");
          location.hash = engHash(client, project);
        } else toast(e.message);
        submit.disabled = false;
      }
    });

    const list = engs.length
      ? h("ul", null, engs.map((en) => {
          const body = h("span", { class: "row-b" },
            h("span", { class: "row-t", text: en.title || en.client + " · " + en.project }),
            h("span", { class: "row-m", text: en.client + " · " + en.project + (en.created_at ? " · created " + fmtTime(en.created_at) : "") }),
            en.error ? h("span", { class: "row-err", text: "Cannot be opened: " + en.error }) : null);
          return h("li", null, en.error
            ? h("div", { class: "row off", "aria-disabled": "true" }, body)
            : h("a", { class: "row", href: engHash(en.client, en.project) }, body));
        }))
      : h("p", { class: "empty", text: "No engagements yet. Create one below." });

    clear(view).append(h("div", { class: "scroll" }, h("div", { class: "page-inner" },
      h("div", { class: "page-head" }, h("div", null, h("h1", { id: "home-h", text: "Engagements" }),
        h("p", { class: "lede", text: "Pick up where you left off, or start a new one." }))),
      h("div", { class: "stack" },
        h("div", { class: "col" }, h("div", { class: "col-h" }, "Your engagements", h("span", { class: "count", text: String(engs.length) })), list),
        h("div", { class: "card" }, h("h2", { class: "card-h", text: "New engagement" }), form)))));
  }

  async function showEngagement(r, token) {
    const view = $("view-engagement");
    view.hidden = false;
    clear(view).append(h("div", { class: "scroll" }, h("div", { class: "page-inner" }, h("p", { class: "muted", text: "Loading." }))));
    let data;
    try { data = await api("GET", engPath(r.client, r.project)); } catch (e) {
      if (token !== routeToken) return;
      clear(view).append(h("div", { class: "scroll" }, h("div", { class: "page-inner" },
        h("a", { class: "back", href: "#/", text: "Engagements" }),
        h("p", { class: "err-line", text: e.message }))));
      return;
    }
    if (token !== routeToken) return;
    const en = data.engagement;
    document.title = (en.title || en.project) + " - AutoDeck";
    const threads = (data.threads || []).slice().sort((a, b) => String(b.last_activity || b.created_at).localeCompare(String(a.last_activity || a.created_at)));
    const newBtn = h("button", { class: "btn primary", type: "button", text: "New thread" });
    newBtn.addEventListener("click", async () => {
      newBtn.disabled = true;
      try {
        const res = await api("POST", engPath(r.client, r.project) + "/threads", {});
        location.hash = threadHash(r.client, r.project, res.thread.id);
      } catch (e) {
        toast(e.message);
        newBtn.disabled = false;
      }
    });
    const col = (title, items, emptyText) => h("section", { class: "col" },
      h("h2", { class: "col-h" }, title, h("span", { class: "count", text: String(items.length) })),
      items.length ? h("ul", null, items) : h("p", { class: "empty", text: emptyText }));

    const sources = (data.sources || []).map((s) => h("li", null, h("div", { class: "row" }, h("span", { class: "row-b" },
      h("span", { class: "row-t", text: s.title }), s.detail ? h("span", { class: "row-m", text: s.detail }) : null))));
    const arts = (data.artifacts || []).map((a) => h("li", null, h("div", { class: "row" }, h("span", { class: "row-b" },
      h("span", { class: "row-t", text: a.title || a.id }),
      h("span", { class: "row-m", text: plural(a.slide_count, "slide") + (a.updated_at ? " · updated " + fmtTime(a.updated_at) : "") })))));
    const thr = threads.map((t) => h("li", null, h("a", { class: "row", href: threadHash(r.client, r.project, t.id) }, h("span", { class: "row-b" },
      h("span", { class: "row-t", text: threadTitle(t) }),
      h("span", { class: "row-m", text: plural(t.turns, "turn") + (t.last_activity ? " · " + fmtTime(t.last_activity) : "") })))));

    clear(view).append(h("div", { class: "scroll" }, h("div", { class: "page-inner" },
      h("div", { class: "page-head" },
        h("div", null, h("a", { class: "back", href: "#/", text: "Engagements" }),
          h("h1", { id: "eng-h", text: en.title || en.client + " · " + en.project }),
          en.title ? h("p", { class: "lede", text: en.client + " · " + en.project }) : null),
        newBtn),
      h("div", { class: "cols" },
        col("Sources", sources, "No sources found."),
        col("Artifacts", arts, "No artifact yet. Start a thread and ask for a deck."),
        col("Threads", thr, "No threads yet.")))));
  }

  // ------------------------------------------------------------------ thread
  const EVENT_TYPES = ["turn_started", "assistant_text", "tool_called", "tool_finished", "artifact_created",
    "change_recorded", "change_reverted", "proposal_created", "proposal_resolved", "turn_finished",
    "previews_ready", "proposal_previews_ready"];

  const STOP_TEXT = {
    step_cap: "Stopped: the step limit for one turn was reached.",
    token_cap: "Stopped: the token limit for one turn was reached.",
    stalled: "Stopped: the model gave no answer.",
  };

  function teardownThread() {
    const T = app.thread;
    if (!T) return;
    T.dead = true;
    if (T.es) T.es.close();
    clearInterval(T.timer);
    clearTimeout(T.reconnectTimer);
    clearTimeout(T.refreshTimer);
    app.thread = null;
  }

  function slideTitle(slide) {
    const blocks = slide.blocks || [];
    const t = blocks.find((b) => b.id === "title" && b.text) || blocks.find((b) => b.kind === "text" && b.text);
    return t ? t.text : slide.id;
  }

  async function showThread(r, token) {
    const view = $("view-thread");
    view.hidden = false;
    clear(view).append(h("p", { class: "muted", text: "Loading." }));
    const T = {
      client: r.client, project: r.project, id: r.thread,
      E: engPath(r.client, r.project), summary: null, messages: [], running: null, live: null,
      artifacts: [], artId: null, art: null, changes: null, proposals: {}, panelTab: "slides",
      slideId: null, flash: new Set(), renderAsked: new Set(), lastEvent: 0, connLost: false,
      tab: "chat", els: {}, dead: false, busy: false,
    };
    T.base = T.E + "/threads/" + enc(T.id);
    try {
      const [th, eng] = await Promise.all([api("GET", T.base), api("GET", T.E)]);
      if (token !== routeToken) return;
      T.summary = th.thread;
      T.messages = th.messages || [];
      T.running = th.running_turn || null;
      applyEngagement(T, eng);
      seedLive(T);
    } catch (e) {
      if (token !== routeToken) return;
      clear(view).append(h("div", { class: "scroll" }, h("div", { class: "page-inner" },
        h("a", { class: "back", href: engHash(r.client, r.project), text: "Engagement" }),
        h("p", { class: "err-line", text: e.message }))));
      return;
    }
    app.thread = T;
    document.title = threadTitle(T.summary) + " - AutoDeck";
    buildThreadDom(T, view);
    renderMessages(T);
    renderLive(T);
    renderComposer(T);
    renderPanel(T);
    connect(T);
    T.timer = setInterval(() => tick(T), 5000);
    if (T.artId) refreshArtifact(T);
  }

  function applyEngagement(T, eng) {
    T.artifacts = eng.artifacts || [];
    T.proposals = {};
    for (const p of eng.proposals || []) T.proposals[p.id] = p;
    if (!T.artId || !T.artifacts.some((a) => a.id === T.artId)) T.artId = T.artifacts.length ? T.artifacts[0].id : null;
    if (eng.running_turn !== undefined && !T.running) T.running = eng.running_turn || null;
  }

  function seedLive(T) {
    // A turn that is running when the page opens: take what the record already holds.
    if (!T.running) { T.live = null; return; }
    const open = T.messages.filter((m) => m.type === "assistant" && m.kind === null).pop();
    if (T.live && T.live.turn_id === T.running) return;
    T.live = {
      turn_id: T.running, origin: null, text: null, model_id: open ? open.model_id : null,
      texts: open ? (open.texts || []).slice() : [], tools: open ? (open.tools || []).map((t, i) => ({ call_id: "r" + i, name: t.name, summary: t.summary, error: t.error, done: true })) : [],
      changes: [],
    };
  }

  function buildThreadDom(T, view) {
    const E = T.els;
    E.chatTab = h("button", { type: "button", role: "tab", id: "tab-chat", "aria-controls": "chat-pane", text: "Chat" });
    E.deckTab = h("button", { type: "button", role: "tab", id: "tab-deck", "aria-controls": "panel-pane", text: "Deck" });
    E.chatTab.addEventListener("click", () => setTab(T, "chat"));
    E.deckTab.addEventListener("click", () => setTab(T, "deck"));
    E.conn = h("span", { class: "conn", role: "status", hidden: true, text: "Reconnecting." });
    E.list = h("div", { class: "msgs-list", id: "msgs-list" });
    E.liveBox = h("div", { class: "live", id: "live" });
    E.msgs = h("div", { class: "msgs", id: "msgs", tabindex: "0", role: "log", "aria-label": "Conversation" }, E.list, E.liveBox);
    E.input = h("textarea", { class: "cinput", id: "composer-input", rows: "1", "aria-label": "Message", placeholder: "Message the model" });
    E.title = h("h1", { class: "chat-title", text: threadTitle(T.summary) });
    E.send = h("button", { class: "btn primary", type: "submit", text: "Send" });
    E.hint = h("p", { class: "hint", id: "composer-hint" });
    E.form = h("form", { class: "cform" }, E.input, E.send);
    E.form.addEventListener("submit", (ev) => { ev.preventDefault(); sendMessage(T); });
    E.input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); sendMessage(T); }
    });
    E.input.addEventListener("input", () => {
      E.input.style.height = "auto";
      E.input.style.height = Math.min(E.input.scrollHeight, 160) + "px";
    });
    const chat = h("section", { class: "chat", id: "chat-pane", "aria-label": "Conversation" },
      h("div", { class: "chat-head" }, E.title, E.conn),
      E.msgs,
      h("div", { class: "composer" }, E.form, E.hint));
    E.panelHead = h("div", { class: "panel-head" });
    E.panelBody = h("div", { class: "panel-body", id: "panel-body" });
    const panel = h("section", { class: "panel", id: "panel-pane", "aria-label": "Artifact" }, E.panelHead, E.panelBody);
    E.root = h("div", { class: "thread", "data-tab": T.tab },
      h("div", { class: "thread-tabs", role: "tablist", "aria-label": "Thread panes" }, E.chatTab, E.deckTab),
      h("div", { class: "thread-grid" }, chat, panel));
    clear(view).append(E.root);
    setTab(T, "chat");
  }

  function renderTitle(T) {
    const t = threadTitle(T.summary);
    T.els.title.textContent = t;
    document.title = t + " - AutoDeck";
  }

  function setTab(T, tab) {
    T.tab = tab;
    T.els.root.setAttribute("data-tab", tab);
    T.els.chatTab.setAttribute("aria-selected", String(tab === "chat"));
    T.els.deckTab.setAttribute("aria-selected", String(tab === "deck"));
  }

  // ---- composer
  function renderComposer(T) {
    const E = T.els;
    const busy = !!T.running || T.busy;
    const was = E.input.disabled;
    E.input.disabled = busy;
    E.send.disabled = busy;
    E.input.placeholder = T.running ? "A turn is running. You can write again when it finishes." : "Message the model";
    E.hint.textContent = T.running ? "" : "Enter sends, Shift+Enter adds a line.";
    if (was && !busy && document.activeElement === document.body) E.input.focus();
  }

  async function sendMessage(T) {
    const text = T.els.input.value;
    if (!text.trim() || T.running || T.busy) return;
    T.busy = true;
    renderComposer(T);
    try {
      const res = await api("POST", T.base + "/messages", { text });
      T.els.input.value = "";
      T.els.input.style.height = "auto";
      beginLive(T, res.turn_id, "owner", text);
    } catch (e) {
      toast(e.message);
      if (e.code === "turn_in_progress") refreshThread(T);
    }
    T.busy = false;
    renderComposer(T);
  }

  function beginLive(T, turnId, origin, text, model) {
    T.running = turnId;
    if (origin === "owner" && text && !T.summary.title && !T.summary.preview) {
      T.summary.preview = text.replace(/\s+/g, " ").trim().slice(0, 80);
      renderTitle(T);
    }
    if (!T.live || T.live.turn_id !== turnId) {
      T.live = { turn_id: turnId, origin, text, model_id: model || null, texts: [], tools: [], changes: [] };
    } else {
      if (origin) T.live.origin = origin;
      if (text !== null && text !== undefined) T.live.text = text;
      if (model) T.live.model_id = model;
    }
    renderLive(T);
    renderComposer(T);
  }

  // ---- messages
  function nearBottom(el) { return el.scrollHeight - el.scrollTop - el.clientHeight < 80; }

  function toolList(tools, openDefault) {
    if (!tools || !tools.length) return null;
    const errs = tools.filter((t) => t.error).length;
    const d = h("details", { class: "tools" },
      h("summary", { text: plural(tools.length, "tool call") + (errs ? ", " + plural(errs, "failed", "failed") : "") }),
      h("ul", { class: "tool-list" }, tools.map((t) => h("li", { class: t.error ? "tool-err" : "" },
        h("span", { class: "tool-name", text: t.name }),
        h("span", { class: "tool-sum", text: (t.error ? "Failed: " : "") + (t.summary || (t.done === false ? "running" : "")) })))));
    if (openDefault) d.open = true;
    return d;
  }

  function modelOf(m) { return m ? h("span", { class: "tag tag-plain mono", text: m }) : null; }

  function renderAssistant(T, m) {
    const kindLabel = { talk: "Talk", proposal: "Proposal", change: "Change" }[m.kind] || "Talk";
    const kids = [];
    for (const t of m.texts || []) if (t && t.trim()) kids.push(h("p", { text: t }));
    const tl = toolList(m.tools);
    if (tl) kids.push(tl);
    if ((m.created_artifacts || []).length) kids.push(h("p", { class: "quiet", text: "Created " + (m.created_artifacts.length === 1 ? "the deck" : "decks") + " " + m.created_artifacts.join(", ") + "." }));
    const ids = [].concat(m.change_ids || []);
    const undone = m.undone_ids || [];
    const redone = m.redone_ids || [];
    if (ids.length || undone.length || redone.length) {
      const byId = {};
      for (const e of (T.changes && T.changes.entries) || []) byId[e.id] = e;
      const li = (id, verb) => h("li", { text: (verb ? verb + ": " : "") + (byId[id] ? changeHeadline(byId[id]) : id) });
      kids.push(h("ul", { class: "items" }, ids.map((i) => li(i, "")), undone.map((i) => li(i, "Undone")), redone.map((i) => li(i, "Redone"))));
      const link = h("button", { class: "linkbtn", type: "button", text: "View in Changes" });
      link.addEventListener("click", () => { T.panelTab = "changes"; renderPanel(T); setTab(T, "deck"); });
      kids.push(h("div", { class: "acts" }, link));
    }
    for (const pid of m.proposal_ids || []) {
      const p = T.proposals[pid];
      kids.push(p ? proposalCard(T, p) : h("p", { class: "quiet", text: "Proposal " + pid + " is not available." }));
    }
    if (m.error) kids.push(h("p", { class: "err-line", text: "This turn failed: " + m.error }));
    else if (m.stop_reason && m.stop_reason !== "replied") kids.push(h("p", { class: "quiet", text: STOP_TEXT[m.stop_reason] || "Stopped: " + m.stop_reason + "." }));
    if (!kids.length) kids.push(h("p", { class: "quiet", text: "No reply." }));
    return h("article", { class: "msg assistant", "data-turn": m.turn_id },
      h("div", { class: "msg-meta" }, h("span", { class: "kind kind-" + (m.kind || "talk"), text: kindLabel }), modelOf(m.model_id)),
      h("div", { class: "bubble" }, kids));
  }

  function renderMessages(T) {
    const E = T.els;
    const stick = nearBottom(E.msgs);
    const open = T.running;
    const items = [];
    for (const m of T.messages) {
      if (m.type === "user") {
        items.push(h("article", { class: "msg user" },
          m.origin === "choice" ? h("span", { class: "u-about", text: "Your choice" }) : null,
          h("div", { class: "bubble", text: m.text })));
      } else if (m.type === "assistant") {
        if (m.kind === null && open) continue; // shown live
        items.push(renderAssistant(T, m));
      } else if (m.type === "note") {
        items.push(h("p", { class: "note-line", text: m.text }));
      }
    }
    if (!items.length && !T.live) items.push(h("p", { class: "empty", text: "Say what deck you want, or ask a question." }));
    clear(E.list).append(...items);
    if (stick) E.msgs.scrollTop = E.msgs.scrollHeight;
  }

  function renderLive(T) {
    const E = T.els;
    const stick = nearBottom(E.msgs);
    clear(E.liveBox);
    const L = T.live;
    if (L) {
      const inRecord = T.messages.some((m) => m.type === "user" && m.turn_id === L.turn_id);
      const kids = [];
      if (L.text && !inRecord) kids.push(h("article", { class: "msg user" }, L.origin === "choice" ? h("span", { class: "u-about", text: "Your choice" }) : null, h("div", { class: "bubble", text: L.text })));
      const body = [];
      for (const t of L.texts) if (t && t.trim()) body.push(h("p", { text: t }));
      const tl = toolList(L.tools, true);
      if (tl) body.push(tl);
      for (const c of L.changes) body.push(h("p", { class: "quiet", text: "Recorded: " + c }));
      body.push(h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")));
      kids.push(h("article", { class: "msg assistant", "aria-busy": "true" },
        h("div", { class: "msg-meta" }, h("span", { class: "kind kind-working", text: "Working" }), modelOf(L.model_id)),
        h("div", { class: "bubble" }, body)));
      E.liveBox.append(...kids);
    }
    if (stick) E.msgs.scrollTop = E.msgs.scrollHeight;
  }

  // ---- proposals
  function proposalCard(T, p) {
    const open = p.status === "open";
    const busy = !!T.running || T.busy;
    const head = h("div", { class: "msg-meta" }, h("span", { class: "quiet", text: p.summary }));
    const opts = h("div", { class: "opts" }, (p.options || []).map((o) => {
      const chosen = p.status === "accepted" && p.chosen === o.id;
      const kids = [
        h("div", { class: "opt-h" }, h("span", { class: "opt-id", text: "Option " + o.id }), h("span", { class: "opt-label", text: o.label }),
          chosen ? h("span", { class: "tag tag-ok", text: "Chosen" }) : null),
        h("p", { class: "opt-text", text: o.text }),
      ];
      const n = (o.slide_ids || []).length;
      if (n) {
        const pv = o.previews || [];
        kids.push(h("div", { class: "samples" }, (o.slide_ids || []).map((sid, i) => h("div", { class: "sample" },
          pv[i] ? h("img", { src: pv[i], alt: "Option " + o.id + ", slide " + (i + 1), loading: "lazy" })
                : h("div", { class: "ph" }, h("b", { text: sid }), h("span", { text: "Preview not ready" }))))));
      }
      if (open) {
        const b = h("button", { class: "btn small primary", type: "button", text: "Use this", disabled: busy });
        b.setAttribute("aria-label", "Use option " + o.id + ": " + o.label);
        b.addEventListener("click", () => pickOption(T, p, o.id));
        kids.push(h("div", { class: "acts" }, b));
      }
      return h("div", { class: "opt" + (chosen ? " chosen" : "") + (!open && !chosen ? " passed" : "") }, kids);
    }));
    const foot = [];
    if (open) {
      const d = h("button", { class: "btn small", type: "button", text: "Dismiss", disabled: busy });
      d.addEventListener("click", () => dismissProposal(T, p));
      foot.push(h("div", { class: "acts" }, d));
    } else {
      const by = p.resolved_by === "chat" ? " in the conversation" : "";
      foot.push(h("p", { class: "pstat", text: p.status === "dismissed" ? "Dismissed" + by + "." : "Option " + p.chosen + " chosen" + by + "." }));
    }
    return h("div", { class: "proposal", "data-proposal": p.id }, head, opts, foot);
  }

  async function pickOption(T, p, optionId) {
    if (T.busy || T.running) return;
    T.busy = true;
    renderComposer(T); renderMessages(T);
    try {
      const res = await api("POST", T.E + "/proposals/" + enc(p.id) + "/pick", { option_id: optionId, thread_id: T.id });
      T.proposals[p.id] = res.proposal;
      T.busy = false;
      beginLive(T, res.turn_id, "choice", "I pick option " + optionId + " of " + p.id + ": " + ((p.options.find((o) => o.id === optionId) || {}).label || "") + ".");
      renderMessages(T);
      return;
    } catch (e) {
      toast(e.message);
      if (e.code === "proposal_resolved" || e.code === "turn_in_progress") { await refreshEngagement(T); await refreshThread(T); }
    }
    T.busy = false;
    renderComposer(T); renderMessages(T);
  }

  async function dismissProposal(T, p) {
    if (T.busy || T.running) return;
    T.busy = true;
    renderMessages(T);
    try {
      const res = await api("POST", T.E + "/proposals/" + enc(p.id) + "/dismiss", { thread_id: T.id });
      T.proposals[p.id] = res.proposal;
      await refreshThread(T);
    } catch (e) {
      toast(e.message);
      if (e.code === "proposal_resolved") await refreshEngagement(T);
    }
    T.busy = false;
    renderMessages(T);
    renderComposer(T);
  }

  // ---- refreshing
  async function refreshEngagement(T) {
    try {
      const eng = await api("GET", T.E);
      if (T.dead) return;
      applyEngagement(T, eng);
    } catch (e) { /* keep what we have */ }
  }

  async function refreshThread(T) {
    try {
      const th = await api("GET", T.base);
      if (T.dead) return;
      T.summary = th.thread;
      T.messages = th.messages || [];
      T.running = th.running_turn || null;
      if (!T.running) T.live = null; else seedLive(T);
      renderTitle(T);
      renderMessages(T); renderLive(T); renderComposer(T);
    } catch (e) { /* the next tick tries again */ }
  }

  function scheduleArtifactRefresh(T) {
    clearTimeout(T.refreshTimer);
    if (T.running) return; // refreshed when the turn finishes; reading mid-turn can race the writes
    T.refreshTimer = setTimeout(async () => {
      await refreshEngagement(T);
      await refreshArtifact(T);
    }, 150);
  }

  function slideFingerprints(art) {
    const out = {};
    if (art && art.deck) for (const s of art.deck.slides || []) out[s.id] = JSON.stringify(s);
    return out;
  }

  async function refreshArtifact(T) {
    if (!T.artId) { T.art = null; T.changes = null; renderPanel(T); return; }
    const id = T.artId;
    const base = T.E + "/artifacts/" + enc(id);
    try {
      const [art, changes] = await Promise.all([api("GET", base), api("GET", base + "/changes")]);
      if (T.dead || T.artId !== id) return;
      const before = slideFingerprints(T.art);
      const hadBefore = T.art && T.art.id === art.id;
      const after = slideFingerprints(art);
      T.flash = new Set();
      if (hadBefore) for (const sid of Object.keys(after)) if (before[sid] !== after[sid]) T.flash.add(sid);
      T.art = art;
      T.changes = changes;
      renderPanel(T);
      renderMessages(T);
      if (T.flash.size) setTimeout(() => { T.flash = new Set(); }, 2000);
      if (!art.render && !T.renderAsked.has(id)) {
        T.renderAsked.add(id);
        try { await api("POST", base + "/render", { thread_id: T.id }); } catch (e) { toast(e.message); }
      }
    } catch (e) {
      if (!T.dead) toast(e.message);
    }
  }

  function tick(T) {
    if (T.dead) return;
    if (T.running) refreshThread(T);
    if (T.art && !T.art.render) refreshArtifact(T);
  }

  // ---- event stream
  function connect(T) {
    if (T.dead) return;
    const es = new EventSource(T.base + "/events");
    T.es = es;
    es.addEventListener("open", () => {
      const wasLost = T.connLost;
      T.connLost = false;
      T.els.conn.hidden = true;
      if (wasLost) { refreshEngagement(T).then(() => { refreshThread(T); scheduleArtifactRefresh(T); }); }
    });
    es.addEventListener("error", () => {
      if (T.dead) return;
      T.connLost = true;
      T.els.conn.hidden = false;
      if (es.readyState === EventSource.CLOSED) {
        // The browser gave up (for example the server refused). Start over; the open handler resyncs.
        T.reconnectTimer = setTimeout(() => connect(T), 3000);
      }
    });
    for (const type of EVENT_TYPES) {
      es.addEventListener(type, (ev) => {
        let data;
        try { data = JSON.parse(ev.data); } catch (e) { return; }
        const id = parseInt(ev.lastEventId, 10);
        if (!isNaN(id)) { if (id <= T.lastEvent) return; T.lastEvent = id; }
        onEvent(T, type, data);
      });
    }
  }

  function liveFor(T, turnId) {
    if (!T.live || T.live.turn_id !== turnId) {
      T.running = turnId;
      T.live = { turn_id: turnId, origin: null, text: null, model_id: null, texts: [], tools: [], changes: [] };
      renderComposer(T);
    }
    return T.live;
  }

  function onEvent(T, type, d) {
    switch (type) {
      case "turn_started":
        beginLive(T, d.turn_id, d.origin, d.text || null, d.model_id);
        break;
      case "assistant_text": {
        const L = liveFor(T, d.turn_id);
        if (d.model_id) L.model_id = d.model_id;
        if (!L.texts.includes(d.text)) L.texts.push(d.text);
        renderLive(T);
        break;
      }
      case "tool_called": {
        const L = liveFor(T, d.turn_id);
        if (!L.tools.some((t) => t.call_id === d.call_id)) L.tools.push({ call_id: d.call_id, name: d.name, summary: "", error: false, done: false });
        renderLive(T);
        break;
      }
      case "tool_finished": {
        const L = liveFor(T, d.turn_id);
        let t = L.tools.find((x) => x.call_id === d.call_id);
        if (!t) { t = { call_id: d.call_id, name: d.name }; L.tools.push(t); }
        t.summary = d.summary; t.error = !!d.error; t.done = true;
        renderLive(T);
        break;
      }
      case "change_recorded":
        if (T.live) { T.live.changes.push(d.instruction || d.entry_id); renderLive(T); }
        if (!T.artId) T.artId = d.artifact_id;
        scheduleArtifactRefresh(T);
        break;
      case "artifact_created":
        if (!T.artId) T.artId = d.artifact_id;
        scheduleArtifactRefresh(T);
        break;
      case "change_reverted":
        scheduleArtifactRefresh(T);
        break;
      case "proposal_created":
      case "proposal_resolved":
        refreshEngagement(T).then(() => renderMessages(T));
        break;
      case "turn_finished":
        T.live = null;
        T.running = null;
        renderLive(T); renderComposer(T);
        if (d.error) toast("The turn failed: " + d.error);
        refreshEngagement(T).then(() => refreshThread(T)).then(() => { renderPanel(T); });
        scheduleArtifactRefresh(T);
        break;
      case "previews_ready":
        if (!T.artId || d.artifact_id === T.artId) scheduleArtifactRefresh(T);
        break;
      case "proposal_previews_ready":
        refreshEngagement(T).then(() => renderMessages(T));
        break;
      default:
    }
  }

  // ---- artifact panel
  function renderPanel(T) {
    const E = T.els;
    const keep = E.panelBody.scrollTop;
    clear(E.panelHead);
    clear(E.panelBody);
    const tabs = [["slides", "Slides"], ["storyline", "Storyline"], ["changes", "Changes"]];
    const tablist = h("div", { class: "ptabs", role: "tablist", "aria-label": "Artifact views" }, tabs.map(([k, label]) => {
      const b = h("button", { type: "button", role: "tab", "aria-selected": String(T.panelTab === k), "aria-controls": "panel-body", text: label });
      b.addEventListener("click", () => { T.panelTab = k; renderPanel(T); });
      return b;
    }));
    E.panelHead.append(tablist);
    if (T.artifacts.length > 1) {
      const sel = h("select", { class: "input picker", "aria-label": "Deck" }, T.artifacts.map((a) => h("option", { value: a.id, selected: a.id === T.artId, text: a.title || a.id })));
      sel.addEventListener("change", () => { T.artId = sel.value; T.art = null; T.changes = null; T.slideId = null; renderPanel(T); refreshArtifact(T); });
      E.panelHead.append(sel);
    }
    E.panelBody.setAttribute("role", "tabpanel");
    if (!T.artId) {
      E.panelBody.append(h("p", { class: "empty", text: "No deck yet. Ask the model to start one and it will appear here." }));
      return;
    }
    if (!T.art) {
      E.panelBody.append(h("p", { class: "muted", text: "Loading the deck." }));
      return;
    }
    if (T.panelTab === "slides") renderSlides(T);
    else if (T.panelTab === "storyline") renderStoryline(T);
    else renderChanges(T);
    E.panelBody.scrollTop = keep;
  }

  function slideVisual(T, slide, index, big) {
    const r = T.art.render;
    const ph = (reason) => h("div", { class: "ph" + (big ? " big" : "") }, h("b", { text: slide.id }), h("span", { text: reason }));
    if (!r) return ph("Rendering the preview.");
    if (!r.rendered) return ph(r.note || "Preview not rendered.");
    const reason = (r.placeholders || {})[slide.id];
    if (reason) return ph(reason);
    const src = (r.images || [])[index];
    if (!src) return ph(r.note || "Preview not available.");
    const img = h("img", { src, alt: big ? "Slide " + (index + 1) + ": " + slideTitle(slide) : "", loading: big ? "eager" : "lazy" });
    img.addEventListener("error", () => { img.replaceWith(ph("Preview not available.")); });
    return img;
  }

  function renderSlides(T) {
    const body = T.els.panelBody;
    const slides = T.art.deck.slides || [];
    if (!slides.length) {
      body.append(h("p", { class: "empty", text: "The deck has no slides yet." }));
      return;
    }
    let idx = slides.findIndex((s) => s.id === T.slideId);
    if (idx < 0) { idx = 0; T.slideId = slides[0].id; }
    const cur = slides[idx];
    const strip = h("div", { class: "strip", role: "group", "aria-label": "Slides" }, slides.map((s, i) => {
      const b = h("button", { type: "button", class: "thumb mk-" + s.marker + (i === idx ? " cur" : "") + (T.flash.has(s.id) ? " flash" : ""), "aria-pressed": String(i === idx), "aria-label": "Slide " + (i + 1) + ": " + slideTitle(s) + (s.marker !== "decided" ? ", " + s.marker : "") },
        h("span", { class: "th-frame" }, slideVisual(T, s, i, false)),
        h("span", { class: "th-meta" }, h("span", { class: "th-n", text: String(i + 1) }), markerTag(s.marker)));
      b.addEventListener("click", () => { T.slideId = s.id; renderPanel(T); });
      return b;
    }));
    const r = T.art.render;
    const note = r && !r.rendered && r.note ? h("p", { class: "quiet", text: r.note }) : null;
    add(body,
      strip,
      h("div", { class: "stage-top" },
        h("div", { class: "stage-title" }, h("span", { class: "stage-head", text: slideTitle(cur) }), h("span", { class: "mono", text: "Slide " + (idx + 1) + " of " + slides.length + " · " + cur.id })),
        markerTag(cur.marker)),
      h("div", { class: "stage mk-" + cur.marker + (T.flash.has(cur.id) ? " flash" : "") }, h("div", { class: "stage-slide" }, slideVisual(T, cur, idx, true))),
      cur.intent ? h("p", { class: "intent", text: cur.intent }) : null,
      note);
  }

  function renderStoryline(T) {
    const d = T.art.deck;
    const body = T.els.panelBody;
    const sec = (title, marker, ...kids) => h("section", { class: "sec" }, h("h2", { class: "sec-h" }, title, markerTag(marker)), kids);
    const b = d.brief;
    add(body, sec("Brief", b && b.marker, b
      ? h("dl", { class: "kv" },
          h("dt", { text: "Audience" }), h("dd", { text: b.audience || "Not set" }),
          h("dt", { text: "Goal" }), h("dd", { text: b.goal || "Not set" }),
          b.notes ? h("dt", { text: "Notes" }) : null, b.notes ? h("dd", { text: b.notes }) : null)
      : h("p", { class: "muted", text: "No brief yet." })));
    const pts = (d.storyline && d.storyline.points) || [];
    add(body, sec("Storyline", d.storyline && d.storyline.marker, pts.length
      ? h("ol", { class: "story" }, pts.map((p, i) => {
          const serving = (d.slides || []).map((s, j) => ({ s, j })).filter((x) => (x.s.serves || []).includes(p.id));
          return h("li", { class: "story-i" },
            h("span", { class: "story-n mono", text: String(i + 1) }),
            h("span", { class: "story-t", text: p.text }),
            h("span", { class: "story-s" }, serving.length
              ? serving.map((x) => h("span", { class: "tag", text: "Slide " + (x.j + 1) }))
              : h("span", { class: "quiet", text: "No slide serves this yet." })));
        }))
      : h("p", { class: "muted", text: "No storyline yet." })));
    const c = d.design_concept;
    add(body, sec("Design concept", c && c.marker, c ? h("p", { class: "concept", text: c.text }) : h("p", { class: "muted", text: "No design concept yet." })));
  }

  async function doRevert(T, action, btn) {
    if (!T.artId) return;
    btn.disabled = true;
    try {
      const res = await api("POST", T.E + "/artifacts/" + enc(T.artId) + "/" + action, { thread_id: T.id });
      if (res.changes) T.changes = res.changes;
      await refreshArtifact(T);
      await refreshThread(T);
    } catch (e) {
      toast(e.message);
      await refreshArtifact(T);
    }
  }

  function renderChanges(T) {
    const body = T.els.panelBody;
    const entries = (T.changes && T.changes.entries) || [];
    if (!entries.length) {
      body.append(h("p", { class: "empty", text: "No changes yet." }));
      return;
    }
    if (T.running) body.append(h("p", { class: "quiet", text: "Undo and redo wait until the running turn finishes." }));
    const items = [];
    let prev = null; // entries are newest first; a run shares one instruction and thread
    for (const e of entries) {
      if (!prev || prev.instruction !== e.instruction || prev.thread_id !== e.thread_id) {
        items.push(h("li", { class: "chg-from", text: e.instruction || "(no instruction recorded)" }));
      }
      prev = e;
      const what = changeHeadline(e);
      const acts = [];
      if (e.can_undo) acts.push(h("button", { class: "btn small", type: "button", text: "Undo", disabled: !!T.running, "aria-label": "Undo: " + what, onclick: (ev) => doRevert(T, "undo", ev.currentTarget) }));
      if (e.can_redo) acts.push(h("button", { class: "btn small", type: "button", text: "Redo", disabled: !!T.running, "aria-label": "Redo: " + what, onclick: (ev) => doRevert(T, "redo", ev.currentTarget) }));
      const meta = [e.layer, e.model_id, e.thread_id ? "thread " + e.thread_id : null, fmtTime(e.created_at)].filter(Boolean).join(" \u00b7 ");
      const rest = (e.lines || []).slice(1);
      items.push(h("li", { class: "chg" + (e.live ? "" : " undone") + (e.is_head ? " head" : "") },
        h("div", { class: "chg-main" },
          h("span", { class: "chg-what" }, describeLine((e.lines || [])[0]) || e.instruction || e.id, " ",
            !e.live ? h("span", { class: "tag tag-plain", text: "Undone" }) : null,
            e.is_head && e.live ? h("span", { class: "tag tag-ok", text: "Current" }) : null),
          h("span", { class: "chg-meta", text: meta }),
          rest.length || e.truncated
            ? h("details", { class: "lines" },
                h("summary", { text: rest.length ? plural(rest.length, "more line") + (e.truncated ? " (more not shown)" : "") : "More not shown" }),
                h("pre", { text: rest.join("\n") }))
            : null),
        acts.length ? h("div", { class: "acts" }, acts) : null));
    }
    body.append(h("ol", { class: "changes" }, items));
  }

  // ------------------------------------------------------------------ boot
  window.addEventListener("hashchange", route);
  loadHealth();
  route();
})();
