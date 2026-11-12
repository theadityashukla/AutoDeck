(function () {
  'use strict';

  var MS = window.MockSlides;
  var TIER = { lead: 'Lead', senior: 'Senior', mid: 'Mid', low: 'Low' };
  var TIER_W = { lead: 6, senior: 3, mid: 1.5, low: 0.5 };   // relative cost per unit of work
  var TIER_T = { lead: 2.2, senior: 1.4, mid: 1, low: 0.6 }; // relative time
  var ALL = MS.slideIds.slice();
  var THREAD = 'Design and refinement';
  var VIEWS = ['home', 'thread', 'notes', 'strict', 'history'];
  var KIND = { talk: 'Talk', proposal: 'Proposal', change: 'Change' };

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function clone(v) { return JSON.parse(JSON.stringify(v)); }

  /* ------------------------------------------------------------------ data */

  var SOURCES = [
    ['Post-training quantisation for large language model serving: an empirical study', 'Paper · 2025 · 18 pages'],
    ['Eight-bit weights, four-bit activations: where the accuracy goes', 'Paper · 2025 · 12 pages'],
    ['Prefix caching and context reuse in production assistants', 'Paper · 2024 · 14 pages'],
    ['Continuous batching under bursty retail traffic', 'Paper · 2025 · 10 pages'],
    ['Cost per answer: a measurement framework for hosted inference', 'Paper · 2024 · 16 pages'],
    ['Scoping call, 14 July (transcript, 42 min)', 'Transcript · 3 speakers'],
    ['Northwind 2025 vendor deck (uploaded)', 'Slides · 24 pages'],
    ['What you have said in threads', 'Decisions and preferences · updated today']
  ];

  var NOTES = [
    { h: 'Summary', items: [
      ['02:10', 'Northwind runs a shopping assistant that costs more to serve each month than the team budgeted. They want a plan that lowers the cost of each answer without a visible drop in quality.',
        'Priya: The assistant costs more to serve every month than we budgeted, and traffic is still growing. I need a plan I can take to finance.']
    ] },
    { h: 'Attendees', items: [
      ['00:30', 'Dana Okafor, engagement lead (us)', 'Dana: Thanks for making time. I am Dana, I lead the engagement on our side.'],
      ['00:48', 'Priya Raman, platform lead (Northwind)', 'Priya: I am Priya. I run the platform team that owns the assistant.'],
      ['01:05', 'Marcus Webb, finance partner (Northwind)', 'Marcus: Marcus, finance. I sign off the serving budget, so I will mostly be listening for numbers.']
    ] },
    { h: 'Themes', items: [
      ['08:20', 'Serving cost is the pressure, not model quality. The team is happy with the answers.',
        'Priya: Nobody is complaining about the answers. The complaint is the invoice.'],
      ['17:35', 'Slow answers at peak hours lose shoppers, which makes latency a useful second argument.',
        'Priya: At peak, answers take three or four seconds. We see people leave the chat during that wait.'],
      ['26:10', 'There is little appetite for a large migration or a change of vendor.',
        'Marcus: I will say it plainly: we are not moving vendors this year. Anything that works on what we run today is welcome.']
    ] },
    { h: 'Decisions', items: [
      ['31:45', 'Lead the proposal with cost. Latency is the supporting argument.',
        'Dana: So we lead with cost and use latency as the supporting point. Priya: Yes, that is what finance will read first.'],
      ['33:02', 'No ROI calculator in the first draft.',
        'Marcus: I do not want a calculator in the room. Show me the three figures and let me ask questions.'],
      ['38:15', 'Pilot on one product category, not the whole catalogue.',
        'Priya: Footwear is a good first category. High traffic, simple questions, easy to measure.']
    ] },
    { h: 'Key dates', items: [
      ['12:40', 'Board pack is due on 12 December.',
        'Marcus: The board pack closes on the twelfth of December. Anything after that waits for February.'],
      ['36:20', 'Northwind wants the pilot decision by 30 November.',
        'Priya: If we are going to pilot before the new year, we need a yes by the thirtieth of November.'],
      ['19:50', 'The peak trading period starts on 20 November. No changes to production during it.',
        'Priya: From the twentieth we freeze. No deploys, nothing that touches the assistant.']
    ] },
    { h: 'Action items', items: [
      ['40:05', 'Dana to send the draft deck to Priya by Friday.',
        'Dana: I will get a draft deck to you by Friday.'],
      ['40:30', 'Priya to share twelve months of serving cost by endpoint.',
        'Priya: I can pull twelve months of cost by endpoint. I will send it this week.'],
      ['41:02', 'Marcus to confirm the budget ceiling for a pilot.',
        'Marcus: Let me check the ceiling with my director and come back to you.'],
      ['41:30', 'Agree who signs off a change to how traffic is shaped. Owner TBD.',
        'Priya: Someone has to approve the traffic shaping. Marcus: Not me. Dana: We will park that. Nobody took it.', 'Owner TBD']
    ] },
    { h: 'Open questions and risks', items: [
      ['22:48', 'Does eight-bit quantisation change the quality of product comparisons?',
        'Priya: My worry is comparisons. If it gets the size or the price wrong in a comparison, we lose trust fast.'],
      ['24:10', 'How fresh must a cached answer be when prices change hourly?',
        'Priya: Prices move every hour on some lines. A cached answer with an old price is worse than a slow one.'],
      ['29:15', 'The vendor contract may limit self-hosting.',
        'Marcus: I have not read the self-hosting clause since we signed. I would not assume it is open.']
    ] }
  ];

  var CLAIMS = [
    { t: 'Inference accounts for 71% of the monthly bill for the shopping assistant.', v: 'Supported',
      doc: 'Northwind 2025 vendor deck', page: 'p. 12',
      q: 'Serving and inference now account for 71% of total assistant run cost; training and fine-tuning make up the rest.' },
    { t: 'Caching repeated context removes about a fifth of the compute.', v: 'Supported',
      doc: 'Prefix caching and context reuse in production assistants', page: 'p. 6',
      q: 'On workloads with a shared system prompt, prefix caching removed 19 to 23% of total compute.' },
    { t: 'Quantisation alone cuts serving cost by 38%.', v: 'Partially supported',
      doc: 'Post-training quantisation for large language model serving: an empirical study', page: 'p. 9',
      q: 'Across the models tested, serving cost fell by between 35 and 41%, depending on batch size and hardware.' }
  ];

  var CHECK = [
    { fig: '$412,000 a month to serve the assistant (slide 2)', ok: true, src: 'Northwind 2025 vendor deck, p. 7' },
    { fig: '71% of the bill is inference (slide 2)', ok: true, src: 'Northwind 2025 vendor deck, p. 12' },
    { fig: '21% of compute removed by caching (slide 5)', ok: true, src: 'Prefix caching and context reuse in production assistants, p. 6' },
    { fig: '$180,000 pilot cost over one quarter (slide 7)', ok: true, src: 'Northwind 2025 vendor deck, p. 19' },
    { fig: '38% (slides 1 and 4)', ok: false, src: 'The quantisation paper reports a range of 35 to 41%. The exact figure does not appear.' }
  ];

  var HISTORY = [
    { role: 'user', text: 'Draft a storyline for the Northwind deck from the scoping call and the papers.' },
    { role: 'assistant', kind: 'proposal',
      text: 'Here is a storyline in eight slides. It opens with the saving, shows where the money goes, names three techniques, proves the biggest one, explains caching, sets out a phased rollout, puts the numbers side by side and ends with the decision. I have not built any slides yet.',
      trace: { rows: [
        { layer: 'Direction', tier: 'lead', note: 'wrote the argument and eight headers', units: 1, secs: 9 },
        { layer: 'Review', tier: 'senior', note: 'checked the order against the call notes', units: 1, secs: 5 }
      ] } },
    { role: 'user', text: 'Lead with cost. Drop the ROI calculator slide.' },
    { role: 'assistant', kind: 'change',
      text: 'Done. The storyline leads with cost and the ROI calculator slide is gone. Eight slides remain.',
      items: ['Slide 1 now states the 38% saving', 'ROI calculator slide removed', 'Rejected idea noted: ROI calculator'],
      trace: { rows: [
        { layer: 'Direction', tier: 'lead', note: 'reordered the argument', units: 1, secs: 6 },
        { layer: 'Mechanics', tier: 'low', note: 'renumbered slides', units: 1, secs: 1 }
      ] } },
    { role: 'assistant', kind: 'talk',
      text: 'The design is still the provisional default. We have not decided on one. That is the next thread.',
      trace: { plain: 'Built from the deck\'s state and change log. No earlier chat was read.' } }
  ];

  /* ----------------------------------------------------------------- state */

  var state, ui;

  function freshState() {
    return {
      direction: 'default', designDecided: false, lead: 'cost', s4Hero: false, s6Short: false,
      stale: [], checked: false, log: [], step: 0, mode: 'auto', route: 'auto', selection: null
    };
  }
  function freshUi() {
    return {
      slide: 's1', ptab: 'slides', nextId: 1, busy: false, gen: (ui ? ui.gen + 1 : 1),
      msgs: [], notesMsgs: [], readout: false, did1: false, did5: false, followup5: false,
      flash: null, scroll: { main: true, notes: true }, notesChipUsed: false, logId: 1
    };
  }

  function initMessages() {
    pushMsg({
      role: 'assistant', kind: 'talk',
      text: 'Picking up from yesterday. The deck has 8 slides and the argument is settled: it leads with cost. The design is still the provisional default, since nothing was decided. Rejected so far: a dark theme, and an ROI calculator slide. Open: whether slide 5 is too dense, and the pilot date on slide 8.',
      trace: { plain: 'Built from the deck\'s state and change log. No earlier chat was read.' }
    }, 'main');
    pushMsg({
      role: 'assistant', kind: 'talk',
      text: 'I wrote these notes from the transcript. Every item links to the line it came from. I can turn them into a short readout deck.',
      trace: { plain: 'Built from the transcript only. No other thread was read.' }
    }, 'notes');
  }

  function reset() {
    state = freshState();
    ui = freshUi();
    initMessages();
  }

  /* ------------------------------------------------------------- selectors */

  function slideState(st, lead) { return { lead: lead || st.lead, s4Hero: st.s4Hero, s6Short: st.s6Short }; }
  function effLead(id, st, ignoreStale) { return (!ignoreStale && st.stale.indexOf(id) >= 0) ? 'cost' : st.lead; }
  function slideHtml(id, st, ignoreStale) {
    return MS.render(id, st.direction, slideState(st, effLead(id, st, ignoreStale)));
  }
  function marker(id, st) {
    return st.stale.indexOf(id) >= 0 ? 'stale' : (st.designDecided ? 'decided' : 'provisional');
  }
  function dirOf(id) { return MS.directions.filter(function (d) { return d.id === id; })[0] || MS.directions[0]; }
  function headerFor(id, st) {
    var hs = MS.headers(slideState(st, effLead(id, st)));
    return hs.filter(function (h) { return h.id === id; })[0] || { n: 0, header: '', intent: '' };
  }
  function slideNum(id) { return ALL.indexOf(id) + 1; }
  function tagHtml(mk) {
    if (mk === 'provisional') return '<span class="tag tag-prov">Provisional</span>';
    if (mk === 'stale') return '<span class="tag tag-stale">Stale</span>';
    return '';
  }
  function aboutLabel(sel) {
    if (!sel) return 'whole deck';
    var s = 'slide ' + slideNum(sel.slide);
    if (sel.part === 'header') s += ' · header';
    if (sel.part === 'body') s += ' · body';
    return s;
  }
  function withPatch(st, patch) {
    var c = clone(st);
    Object.keys(patch).forEach(function (k) { c[k] = clone(patch[k]); });
    return c;
  }

  /* --------------------------------------------------------------- tracing */

  function makeTrace(rows, foot) {
    var pin = state.route;
    if (pin === 'auto') return { rows: clone(rows), foot: foot || '' };
    var out = [];
    rows.forEach(function (r) {
      if (r.skip) return;
      var c = clone(r);
      c.secs = Math.round(r.secs * TIER_T[pin] / TIER_T[r.tier] * 10) / 10;
      c.tier = pin;
      out.push(c);
    });
    return { rows: out, pinned: pin, foot: 'Pinned by you' + (pin === 'lead' ? '. Every layer ran on the Lead, which is the most expensive tier.' : '.') };
  }
  function layerSummary(rows) {
    return rows.filter(function (r) { return !r.skip; }).map(function (r) { return r.layer + ' · ' + TIER[r.tier]; }).join(', ');
  }
  function traceTotals(t) {
    var s = 0, c = 0;
    t.rows.forEach(function (r) { if (!r.skip) { s += r.secs; c += r.units * TIER_W[r.tier]; } });
    return { secs: Math.round(s * 10) / 10, cost: Math.round(c * 10) / 10 };
  }
  function traceHtml(m) {
    var t = m.trace;
    if (!t) return '';
    if (t.plain) return '<div class="route plain"><span class="route-l">Routing</span><span>' + esc(t.plain) + '</span></div>';
    var run = t.rows.filter(function (r) { return !r.skip; });
    var tot = traceTotals(t);
    var summary = run.map(function (r) { return r.layer + ' ' + TIER[r.tier]; }).join(' · ');
    var rows = t.rows.map(function (r) {
      if (r.skip) {
        return '<li class="tr skip"><span class="tr-layer">' + r.layer + '</span><span class="tier t-' + r.tier + ' off">' + TIER[r.tier] + '</span><span class="tr-note">Not needed</span><span class="tr-time"></span><span class="bar"></span></li>';
      }
      var cost = r.units * TIER_W[r.tier];
      var w = Math.max(3, Math.min(100, cost / 25 * 100));
      return '<li class="tr"><span class="tr-layer">' + r.layer + '</span><span class="tier t-' + r.tier + '">' + TIER[r.tier] + '</span><span class="tr-note">' + esc(r.note) + '</span><span class="tr-time">' + r.secs + ' s</span><span class="bar" title="Relative cost ' + cost + '"><i style="width:' + w + '%"></i></span></li>';
    }).join('');
    var tw = Math.max(3, Math.min(100, tot.cost / 150 * 100));
    return '<details class="route' + (t.pinned === 'lead' ? ' pin-lead' : '') + '" data-mid="' + m.id + '"' + (m.open ? ' open' : '') + '>' +
      '<summary><span class="route-l">Routing</span><span class="route-sum">' + esc(summary || 'No layers ran') + '</span><span class="route-t">' + tot.secs + ' s</span></summary>' +
      '<ol class="trace">' + rows + '</ol>' +
      (t.foot ? '<p class="trace-foot' + (t.pinned ? ' pinned' : '') + '">' + esc(t.foot) + '</p>' : '') +
      '<div class="trace-total"><span>Total ' + tot.secs + ' s</span><span class="bar big" title="Relative cost ' + tot.cost + '"><i style="width:' + tw + '%"></i></span><span>Relative cost ' + tot.cost + '</span></div>' +
      '</details>';
  }

  /* -------------------------------------------------------------- messages */

  function pushMsg(m, list) {
    m.id = ui.nextId++;
    m.list = list || 'main';
    (m.list === 'notes' ? ui.notesMsgs : ui.msgs).push(m);
    ui.scroll[m.list] = true;
    return m;
  }

  function msgHtml(m) {
    if (m.role === 'user') {
      return '<article class="msg user"><div class="bubble">' + esc(m.text) + '</div>' +
        (m.about ? '<div class="u-about">About: ' + esc(m.about) + '</div>' : '') + '</article>';
    }
    var h = '<article class="msg assistant m-' + m.kind + '" data-mid="' + m.id + '">';
    h += '<div class="msg-meta"><span class="kind kind-' + m.kind + '">' + KIND[m.kind] + '</span>';
    if (m.kind === 'proposal' && m.status) h += '<span class="pstat">' + (m.status === 'applied' ? 'Applied' : m.status === 'dismissed' ? 'Dismissed' : 'Waiting for you') + '</span>';
    h += '</div><div class="bubble">';
    h += '<p>' + esc(m.text) + '</p>';
    if (m.cards) h += cardsHtml(m);
    if (m.preview) h += previewHtml(m);
    if (m.items) h += '<ul class="items">' + m.items.map(function (i) { return '<li>' + esc(i) + '</li>'; }).join('') + '</ul>';
    if (m.check) h += checkHtml(m);
    if (m.after) h += '<p>' + esc(m.after) + '</p>';
    var acts = '';
    if (m.kind === 'proposal' && m.change) {
      if (m.status === 'open') acts += '<button type="button" class="btn primary" data-action="apply" data-mid="' + m.id + '">Apply</button><button type="button" class="btn" data-action="dismiss" data-mid="' + m.id + '">Dismiss</button>';
    }
    if (m.rebuild) {
      var n = state.stale.length;
      acts += n > 0
        ? '<button type="button" class="btn" data-action="rebuild">Rebuild the 4 stale slides</button>'
        : '<button type="button" class="btn" aria-disabled="true" title="Nothing is stale right now">Rebuild the 4 stale slides</button>';
    }
    if (m.link === 'changes') acts += '<button type="button" class="linkbtn" data-action="goto-changes">View in the Changes tab</button>';
    if (m.link === 'home') acts += '<a class="linkbtn" href="#home">See it on the engagement home</a>';
    if (acts) h += '<div class="acts">' + acts + '</div>';
    h += '</div>' + traceHtml(m) + '</article>';
    return h;
  }

  function cardsHtml(m) {
    return '<div class="dir-cards">' + MS.directions.slice(1).map(function (d) {
      var chosen = state.designDecided && state.direction === d.id;
      var locked = state.designDecided;
      var pending = state.mode === 'propose';
      var btn;
      if (chosen) btn = '<button type="button" class="btn" aria-disabled="true">In use</button>';
      else if (locked) btn = '<button type="button" class="btn" aria-disabled="true" title="A direction is already decided">Use this direction</button>';
      else btn = '<button type="button" class="btn primary" data-action="pick-dir" data-dir="' + d.id + '">Use this direction</button>';
      return '<div class="dir-card"><div class="dir-card-h"><strong>' + esc(d.name) + '</strong></div><p class="dir-concept">' + esc(d.concept) + '</p>' +
        '<div class="samples">' + (m.samples[d.id] || []).map(function (s) { return '<div class="sample">' + s + '</div>'; }).join('') + '</div>' + btn + '</div>';
    }).join('') + '</div>';
  }

  function previewHtml(m) {
    var p = m.preview;
    var h = '<div class="preview">';
    p.slides.forEach(function (s) {
      h += '<div class="pv-row"><div class="pv"><span class="pv-l">Before · slide ' + s.n + '</span><div class="pv-s">' + s.before + '</div></div>' +
        '<div class="pv"><span class="pv-l">After · slide ' + s.n + '</span><div class="pv-s">' + s.after + '</div></div></div>';
    });
    if (p.more) h += '<p class="pv-more">' + esc(p.more) + '</p>';
    if (p.list) h += '<ul class="items">' + p.list.map(function (i) { return '<li>' + esc(i) + '</li>'; }).join('') + '</ul>';
    return h + '</div>';
  }

  function checkHtml() {
    return '<div class="check"><div class="check-h">Five figures checked</div><ul>' + CHECK.map(function (c) {
      return '<li class="' + (c.ok ? 'ok' : 'no') + '"><span class="ck-s">' + (c.ok ? 'Found' : 'Not found') + '</span><span class="ck-t"><strong>' + esc(c.fig) + '</strong>' +
        (c.ok ? '<span class="ck-src">' + esc(c.src) + '</span>' : '<span class="ck-src">' + esc(c.src) + '</span>') + '</span></li>';
    }).join('') + '</ul></div>';
  }

  function renderMsgsInto(el, list, key) {
    var prev = el.scrollTop;
    var h = list.map(msgHtml).join('');
    if (ui.busy && ui.busyList === key) h += '<article class="msg assistant typing" aria-label="Working"><div class="bubble"><span class="dots"><i></i><i></i><i></i></span></div></article>';
    el.innerHTML = h;
    if (ui.scroll[key]) {
      var last = el.querySelector('.msg:last-child');
      el.scrollTop = el.scrollHeight;
      if (last && !last.classList.contains('typing') && last.offsetHeight > el.clientHeight - 24) el.scrollTop = last.offsetTop - el.offsetTop - 12;
      ui.scroll[key] = false;
    } else el.scrollTop = prev;
  }

  function renderChats() {
    renderMsgsInto($('#msgs'), ui.msgs, 'main');
    renderMsgsInto($('#notes-msgs'), ui.notesMsgs, 'notes');
  }

  /* ------------------------------------------------------------- composer */

  function buildComposers() {
    $$('.composer').forEach(function (c) {
      var scope = c.getAttribute('data-scope');
      c.innerHTML =
        '<div class="chips" role="group" aria-label="Suggested messages"></div>' +
        (scope === 'thread' ? '<div class="about"></div>' : '') +
        '<form class="cform" autocomplete="off"><input type="text" class="cinput" aria-label="Message" placeholder="' + (scope === 'thread' ? 'Message about the deck' : 'Message about the notes') + '"><button type="submit" class="btn primary">Send</button></form>' +
        '<div class="controls">' +
        '<div class="ctl"><span class="ctl-l" id="ml-' + scope + '">Editing</span><div class="seg" role="group" aria-labelledby="ml-' + scope + '" data-seg="mode">' +
        '<button type="button" data-mode="auto" title="Edits are applied and logged straight away">Auto</button>' +
        '<button type="button" data-mode="propose" title="Edits are shown as a preview first">Propose first</button></div></div>' +
        '<div class="ctl"><span class="ctl-l" id="rl-' + scope + '">Routing</span><div class="seg" role="group" aria-labelledby="rl-' + scope + '" data-seg="route">' +
        ['auto', 'lead', 'senior', 'mid', 'low'].map(function (r) { return '<button type="button" data-route="' + r + '">' + (r === 'auto' ? 'Auto' : TIER[r]) + '</button>'; }).join('') +
        '</div></div></div>';
    });
  }

  function chipDefs(scope) {
    var c = [];
    if (scope === 'notes') {
      if (!ui.notesChipUsed) c.push({ id: 'n1', label: 'Turn this into a readout deck' });
      return c;
    }
    if (ui.followup5) c.push({ id: 'f5y', label: 'Yes, cut it down' }, { id: 'f5n', label: 'Leave it' });
    if (!ui.did1) c.push({ id: 's1', label: 'The deck looks generic. Give it a real design.' });
    if (state.designDecided) {
      if (!state.s4Hero) c.push({ id: 's3', label: 'Make the number the hero' });
      if (!state.s6Short) c.push({ id: 's4', label: 'Shorten this title' });
      if (!ui.did5) c.push({ id: 's5', label: 'Is slide 5 too dense?' });
      if (state.lead === 'cost') c.push({ id: 's6', label: 'Lead with latency, not cost' });
      if (!state.checked) c.push({ id: 's7', label: 'Check the numbers against my sources' });
    }
    return c;
  }

  function renderComposers() {
    $$('.composer').forEach(function (c) {
      var scope = c.getAttribute('data-scope');
      var chips = chipDefs(scope);
      var hint = '';
      if (scope === 'thread' && ui.did1 && !state.designDecided) hint = '<span class="chip-hint">Choose a direction on one of the cards to continue.</span>';
      if (scope === 'thread' && !chips.length && !hint) hint = '<span class="chip-hint">Nothing left in this script. Export when you are ready.</span>';
      if (scope === 'notes' && !chips.length) hint = '<span class="chip-hint">Readout deck added to the engagement.</span>';
      $('.chips', c).innerHTML = chips.map(function (x) {
        return '<button type="button" class="chip" data-chip="' + x.id + '"' + (ui.busy ? ' aria-disabled="true"' : '') + '>' + esc(x.label) + '</button>';
      }).join('') + hint;
      $$('[data-mode]', c).forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-mode') === state.mode)); });
      $$('[data-route]', c).forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-route') === state.route)); });
      var ab = $('.about', c);
      if (ab) {
        ab.innerHTML = state.selection
          ? '<span class="about-chip active">About: ' + esc(aboutLabel(state.selection)) + '<button type="button" class="x" data-action="clear-sel" aria-label="Clear selection">' +
            '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 2l6 6M8 2L2 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button></span>'
          : '<span class="about-chip">About: whole deck</span>';
      }
    });
  }

  /* ----------------------------------------------------------------- panel */

  function renderPtabs() {
    var tabs = [['slides', 'Slides'], ['story', 'Storyline'], ['design', 'Design'], ['changes', 'Changes' + (state.log.length ? ' (' + state.log.length + ')' : '')]];
    $('#ptabs').innerHTML = tabs.map(function (t) {
      return '<button type="button" role="tab" data-ptab="' + t[0] + '" aria-selected="' + (ui.ptab === t[0]) + '">' + t[1] + '</button>';
    }).join('');
  }

  function thumbsHtml() {
    return '<div class="strip" role="listbox" aria-label="Slides">' + ALL.map(function (id) {
      var mk = marker(id, state);
      var flash = ui.flash && ui.flash.indexOf(id) >= 0;
      var selSlide = state.selection && state.selection.slide === id;
      return '<button type="button" role="option" class="thumb mk-' + mk + (id === ui.slide ? ' cur' : '') + (flash ? ' flash' : '') + '" data-slide="' + id + '" aria-selected="' + (id === ui.slide) + '" aria-label="Slide ' + slideNum(id) + (mk === 'decided' ? '' : ', ' + mk) + '">' +
        '<span class="th-frame"><span class="th-slide">' + slideHtml(id, state) + '</span></span>' +
        '<span class="th-meta"><span class="th-n">' + slideNum(id) + '</span>' + tagHtml(mk) + (selSlide ? '<span class="th-sel" aria-hidden="true"></span>' : '') + '</span></button>';
    }).join('') + '</div>';
  }

  function stageHtml(id, st, sel, big) {
    var mk = marker(id, st);
    return '<div class="stage mk-' + mk + '"><div class="stage-slide"' + (big ? ' data-stage="1" title="Click the header or the body to select it"' : '') + '>' + slideHtml(id, st) +
      (sel ? '<div class="sel sel-' + sel + '" aria-hidden="true"></div>' : '') + '</div></div>';
  }

  function slidesTab() {
    var id = ui.slide, mk = marker(id, state);
    var hd = headerFor(id, state);
    var sel = state.selection && state.selection.slide === id ? state.selection.part : null;
    var part = state.selection && state.selection.slide === id ? state.selection.part : null;
    var h = thumbsHtml();
    h += '<div class="stage-top"><div class="stage-title"><span class="mono">Slide ' + slideNum(id) + ' of 8</span><span class="stage-head">' + esc(hd.header) + '</span></div>' +
      '<div class="stage-tags">' + tagHtml(mk) + '<span class="dir-name">' + esc(dirOf(state.direction).name) + '</span></div></div>';
    h += stageHtml(id, state, sel, true);
    h += '<div class="pick" role="group" aria-label="Select part of slide ' + slideNum(id) + '"><span class="pick-l">Ask about</span>' +
      [['slide', 'Whole slide'], ['header', 'Header'], ['body', 'Body']].map(function (p) {
        return '<button type="button" class="pickbtn" data-pick="' + p[0] + '" aria-pressed="' + (part === p[0]) + '">' + p[1] + '</button>';
      }).join('') + '</div>';
    if (state.selection) {
      h += '<div class="narrow-only gochat"><span>About: ' + esc(aboutLabel(state.selection)) + '</span><button type="button" class="btn" data-action="go-chat">Ask in chat</button></div>';
    }
    if (mk === 'stale') h += '<p class="stale-note">This slide was built on the earlier argument (cost). It has not been rebuilt, so it still shows the old content.</p>';
    return h;
  }

  function storyTab() {
    var hs = MS.headers(slideState(state));
    return '<ol class="story">' + hs.map(function (x) {
      var mk = marker(x.id, state);
      return '<li class="story-i"><span class="story-n mono">' + x.n + '</span><div class="story-b"><div class="story-h">' + esc(x.header) + '</div>' +
        '<div class="story-int">' + esc(x.intent) + '</div>' +
        (mk === 'stale' ? '<div class="story-note">The slide itself still shows: ' + esc(headerFor(x.id, state).header) + '</div>' : '') +
        '</div><div class="story-t">' + (tagHtml(mk) || '<span class="tag tag-ok">Decided</span>') + '</div></li>';
    }).join('') + '</ol>';
  }

  function designTab() {
    var d = dirOf(state.direction);
    var h = '<div class="design"><div class="design-top"><h2>' + esc(d.name) + '</h2>' +
      (state.designDecided ? '<span class="tag tag-ok">Decided</span>' : '<span class="tag tag-prov">Provisional</span>') + '</div>';
    h += '<p class="status-line">' + (state.designDecided
      ? 'You chose this direction. It is saved to your preferences for later decks.'
      : 'Nobody decided this design. It is what the system produces by default. Ask for a real design in the chat.') + '</p>';
    h += '<p class="concept">' + esc(d.concept) + '</p>';
    h += '<h3 class="mini-h">Palette</h3><ul class="swatches">' + d.palette.map(function (p) {
      return '<li><span class="sw" style="background:' + esc(p.hex) + '"></span><span class="sw-n">' + esc(p.name) + '</span><span class="sw-h mono">' + esc(p.hex) + '</span><span class="sw-r">' + esc(p.role) + '</span></li>';
    }).join('') + '</ul>';
    h += '<h3 class="mini-h">Type</h3><dl class="type"><dt>Display</dt><dd>' + esc(d.type.display) + '</dd><dt>Body</dt><dd>' + esc(d.type.body) + '</dd></dl>';
    h += '<h3 class="mini-h">Rules</h3><ul class="rules">' + d.rules.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul></div>';
    return h;
  }

  function undoable(e) {
    var i = state.log.indexOf(e);
    return !e.undone && state.log.slice(i + 1).every(function (x) { return x.undone; });
  }
  function redoable(e) {
    if (!e.undone || e.superseded) return false;
    var i = state.log.indexOf(e);
    return state.log.slice(0, i).every(function (x) { return !x.undone || x.superseded; });
  }

  function changesTab() {
    if (!state.log.length) return '<div class="empty"><strong>No changes yet.</strong><p>Edits made in the chat appear here, newest first, each with an Undo.</p></div>';
    return '<ol class="changes">' + state.log.slice().reverse().map(function (e) {
      var undo = '';
      if (e.undone) {
        var ok = redoable(e);
        undo = '<button type="button" class="btn" data-action="redo" data-eid="' + e.id + '"' + (ok ? '' : ' aria-disabled="true" title="' + (e.superseded ? 'Superseded by a later change' : 'Redo earlier changes first') + '"') + '>Redo</button>';
      } else {
        var ok2 = undoable(e);
        undo = '<button type="button" class="btn" data-action="undo" data-eid="' + e.id + '"' + (ok2 ? '' : ' aria-disabled="true" title="Undo later changes first"') + '>Undo</button>';
      }
      return '<li class="chg' + (e.undone ? ' undone' : '') + '"><div class="chg-main"><div class="chg-what">' + esc(e.what) + (e.undone ? ' <span class="tag tag-plain">Undone</span>' : '') + '</div>' +
        '<div class="chg-meta"><span>Instruction: “' + esc(e.instruction) + '”</span><span>Thread: ' + esc(e.thread) + '</span><span>Made by: ' + esc(e.layers) + '</span></div></div>' + undo + '</li>';
    }).join('') + '</ol>';
  }

  function renderPanel() {
    renderPtabs();
    var body = $('#panel-body');
    var prev = body.scrollTop;
    var h = ui.ptab === 'slides' ? slidesTab() : ui.ptab === 'story' ? storyTab() : ui.ptab === 'design' ? designTab() : changesTab();
    var strip = $('.strip', body);
    var sx = strip ? strip.scrollLeft : 0;
    body.innerHTML = h;
    body.scrollTop = prev;
    var ns = $('.strip', body);
    if (ns) ns.scrollLeft = sx;
    if (ui.ptab === 'slides' && !ui.stripSeen) { ui.stripSeen = true; }
  }

  function renderThread() {
    renderChats();
    renderComposers();
    renderPanel();
    renderDialogIfOpen();
  }

  /* ------------------------------------------------------------ changes */

  function flash(ids) {
    ui.flash = ids.slice();
    var g = ui.gen;
    setTimeout(function () {
      if (g !== ui.gen) return;
      ui.flash = null;
      $$('.thumb.flash').forEach(function (e) { e.classList.remove('flash'); });
    }, 1700);
  }

  function applyChange(spec, trace, list) {
    var prev = {};
    Object.keys(spec.patch).forEach(function (k) { prev[k] = clone(state[k]); });
    state.log.forEach(function (e) { if (e.undone) e.superseded = true; });
    var entry = {
      id: ui.logId++, what: spec.what, instruction: spec.instruction, thread: THREAD,
      layers: spec.layers || layerSummary(spec.rows), patch: clone(spec.patch), prev: prev,
      affected: spec.affected.slice(), undone: false, superseded: false
    };
    state.log.push(entry);
    Object.keys(spec.patch).forEach(function (k) { state[k] = clone(spec.patch[k]); });
    flash(spec.affected);
    pushMsg({ role: 'assistant', kind: 'change', text: spec.doneText, items: spec.items, rebuild: !!spec.rebuild, link: 'changes', trace: trace }, list || 'main');
  }

  function stepChange(spec, list) {
    var trace = makeTrace(spec.rows, spec.foot);
    spec.layers = layerSummary(trace.rows);
    if (state.mode === 'propose') {
      var after = withPatch(state, spec.patch);
      var ids = spec.preview;
      var slides = ids.map(function (id) {
        return { n: slideNum(id), before: slideHtml(id, state, false), after: slideHtml(id, after, true) };
      });
      var more = spec.previewMore || (spec.affected.length > ids.length ? 'Plus ' + (spec.affected.length - ids.length) + ' more slides, changed the same way.' : '');
      pushMsg({ role: 'assistant', kind: 'proposal', text: spec.proposeText, preview: { slides: slides, more: more }, change: spec, status: 'open', trace: trace }, 'main');
    } else {
      applyChange(spec, trace);
    }
  }

  function applyProposal(m) {
    if (m.status !== 'open') return;
    m.status = 'applied';
    if (m.change.artifact) { applyReadout(m.change, { plain: 'Applied from the proposal. No layers re-ran.' }); return; }
    applyChange(m.change, { plain: 'Applied from the proposal as previewed. No layers re-ran.' });
    state.step = Math.max(state.step, m.change.step || 0);
    renderThread();
  }

  function setLog(e, undo) {
    var keys = Object.keys(e.patch);
    keys.forEach(function (k) { state[k] = clone(undo ? e.prev[k] : e.patch[k]); });
    e.undone = undo;
    flash(e.affected);
    renderThread();
  }

  /* ---------------------------------------------------------- the script */

  function specDirection(dirId) {
    var d = dirOf(dirId);
    return {
      step: 2, what: 'Chose ' + d.name + ' as the design and recomposed all eight slides in it.',
      instruction: 'Use this direction (' + d.name + ')', affected: ALL.slice(),
      patch: { direction: dirId, designDecided: true }, preview: ['s1', 's4'],
      rows: [
        { layer: 'Direction', tier: 'lead', skip: true },
        { layer: 'System', tier: 'senior', note: 'wrote the decided system', units: 1, secs: 6 },
        { layer: 'Composition', tier: 'mid', note: '8 slides in parallel', units: 8, secs: 7 },
        { layer: 'Placement', tier: 'low', note: 'placed text and shapes', units: 8, secs: 2 }
      ],
      foot: 'The Lead was not needed. The direction was already chosen.',
      proposeText: 'This would make ' + d.name + ' the decided design and recompose all eight slides in it. Slides 1 and 4 are shown below. Nothing has changed yet.',
      doneText: 'Done. ' + d.name + ' is now the decided system. All eight slides were recomposed in it, and I noted the choice in your preferences for later decks.',
      items: ['All eight slides recomposed in ' + d.name, 'Design status: provisional to decided', 'Saved to your preferences: ' + d.name]
    };
  }
  function specHero() {
    return {
      step: 3, what: 'Slide 4 now leads with the number 38%. The before and after bars are a quiet footnote.',
      instruction: 'Make the number the hero', affected: ['s4'], patch: { s4Hero: true }, preview: ['s4'],
      rows: [
        { layer: 'Direction', tier: 'lead', skip: true },
        { layer: 'Composition', tier: 'mid', note: 'recomposed slide 4', units: 1, secs: 4 },
        { layer: 'Placement', tier: 'low', note: 'placed the number and footnote', units: 1, secs: 1 }
      ],
      proposeText: 'Slide 4 would lead with 38% and the before and after bars would become a footnote. Nothing has changed yet.',
      doneText: 'Done. Slide 4 now leads with 38%. The before and after bars moved to a footnote.',
      items: ['Slide 4: the number 38% is the hero', 'Slide 4: bar comparison reduced to a footnote']
    };
  }
  function specShort() {
    return {
      step: 4, what: 'Slide 6 header shortened to “Two quarters, three phases”.',
      instruction: 'Shorten this title', affected: ['s6'], patch: { s6Short: true }, preview: ['s6'],
      rows: [{ layer: 'Mechanics', tier: 'low', note: 'edited one header', units: 1, secs: 1 }],
      foot: 'Routed straight to the lowest tier. The lead was not invoked.',
      proposeText: 'The header on slide 6 would become “Two quarters, three phases”. Nothing has changed yet.',
      doneText: 'Done. The header on slide 6 now reads “Two quarters, three phases”.',
      items: ['Slide 6 header: Two quarters, three phases']
    };
  }
  function specLead() {
    return {
      step: 6, what: 'Changed the argument to lead with latency. Slides 1, 2, 3 and 7 are now stale.',
      instruction: 'Lead with latency, not cost', affected: ['s1', 's2', 's3', 's7'],
      patch: { lead: 'latency', stale: ['s1', 's2', 's3', 's7'] }, preview: ['s1', 's2'], rebuild: true,
      rows: [{ layer: 'Direction', tier: 'lead', note: 'rewrote the argument and four headers', units: 1, secs: 8 }],
      proposeText: 'This would change the argument to lead with latency and mark slides 1, 2, 3 and 7 as stale, because they were built on the cost argument. Nothing would be rebuilt yet. Slides 1 and 2 are shown as they would read once rebuilt.',
      doneText: 'The storyline now leads with latency. Four slides were built on the old argument, so I marked them stale: slides 1, 2, 3 and 7. Nothing was rebuilt.',
      items: ['Storyline: headers on slides 1, 2, 3 and 7 now lead with latency', 'Slides 1, 2, 3 and 7 marked Stale, still showing the cost argument']
    };
  }
  function specRebuild() {
    return {
      step: 6, what: 'Rebuilt slides 1, 2, 3 and 7 on the latency argument.',
      instruction: 'Rebuild the 4 stale slides', affected: state.stale.slice(),
      patch: { stale: [] }, preview: ['s1', 's2'],
      rows: [
        { layer: 'Direction', tier: 'lead', skip: true },
        { layer: 'Composition', tier: 'mid', note: '4 slides in parallel', units: 4, secs: 6 },
        { layer: 'Placement', tier: 'low', note: 'placed text and shapes', units: 4, secs: 2 },
        { layer: 'Review', tier: 'senior', note: 'read the four renders', units: 1, secs: 5 }
      ],
      proposeText: 'This would rebuild the four stale slides on the latency argument. Slides 1 and 2 are shown before and after. Nothing has changed yet.',
      doneText: 'Rebuilt. Slides 1, 2, 3 and 7 now follow the latency argument and are no longer stale.',
      items: ['Slides 1, 2, 3 and 7 rebuilt on the latency argument', 'Stale markers cleared']
    };
  }
  function specReadout() {
    return {
      artifact: true, list: 'notes',
      proposeText: 'This would create a five-slide readout deck from the notes and add it to the engagement. It would be provisional, because no design has been decided for it. Nothing has been created yet.',
      doneText: 'Done. I made a five-slide readout deck from these notes and added it to the engagement. It is provisional: its design has not been decided.',
      items: ['Scoping call readout (deck, 5 slides, provisional) added to Artifacts', 'Slides: summary, themes, decisions, key dates, next steps'],
      preview: { list: ['Slide 1: What we heard', 'Slide 2: Themes', 'Slide 3: Decisions so far', 'Slide 4: Key dates', 'Slide 5: Next steps and open questions'] },
      rows: [
        { layer: 'Direction', tier: 'lead', note: 'chose the five points from the notes', units: 1, secs: 6 },
        { layer: 'Composition', tier: 'mid', note: '5 slides in parallel', units: 5, secs: 5 },
        { layer: 'Placement', tier: 'low', note: 'placed text and shapes', units: 5, secs: 2 }
      ]
    };
  }

  function applyReadout(spec, trace) {
    ui.readout = true;
    ui.notesChipUsed = true;
    pushMsg({ role: 'assistant', kind: 'change', text: spec.doneText, items: spec.items, link: 'home', trace: trace }, 'notes');
    renderChats(); renderComposers(); renderHome();
  }

  function stepReadout() {
    var spec = specReadout();
    var trace = makeTrace(spec.rows);
    if (state.mode === 'propose') {
      pushMsg({ role: 'assistant', kind: 'proposal', text: spec.proposeText, preview: spec.preview, change: spec, status: 'open', trace: trace }, 'notes');
    } else {
      applyReadout(spec, trace);
    }
  }

  var STEPS = {
    s1: { label: 'The deck looks generic. Give it a real design.', run: function () {
      ui.did1 = true; state.step = Math.max(state.step, 1);
      var samples = {};
      MS.directions.slice(1).forEach(function (d) { samples[d.id] = MS.renderSample(d.id); });
      pushMsg({
        role: 'assistant', kind: 'proposal', samples: samples, cards: true,
        text: 'The default was never a decision. It is what you get when nobody chooses. Here are three directions drawn from the content of this deck. Pick one and I will recompose all eight slides in it.',
        trace: makeTrace([
          { layer: 'Direction', tier: 'lead', note: 'wrote three concepts', units: 1, secs: 9 },
          { layer: 'System', tier: 'senior', note: 'three systems, in parallel', units: 3, secs: 7 },
          { layer: 'Composition', tier: 'mid', note: 'nine sample slides, in parallel', units: 9, secs: 6 },
          { layer: 'Placement', tier: 'low', note: 'placed text and shapes', units: 9, secs: 2 },
          { layer: 'Review', tier: 'senior', note: 'read the renders cold', units: 3, secs: 5 }
        ])
      });
    } },
    s3: { label: 'Make the number the hero', sel: { slide: 's4', part: 'slide' }, run: function () { state.step = Math.max(state.step, 3); stepChange(specHero()); } },
    s4: { label: 'Shorten this title', sel: { slide: 's6', part: 'header' }, strict: true, run: function () { state.step = Math.max(state.step, 4); stepChange(specShort()); } },
    s5: { label: 'Is slide 5 too dense?', sel: { slide: 's5', part: 'slide' }, run: function () {
      ui.did5 = true; ui.followup5 = true; state.step = Math.max(state.step, 5);
      pushMsg({
        role: 'assistant', kind: 'talk',
        text: 'Yes, a little. Slide 5 carries a diagram and four points, which is more than any other slide. I would cut it to the diagram and two points: the 21% figure and the one on cache freshness. The other two can go in the notes. Want me to do that?',
        trace: makeTrace([{ layer: 'Review', tier: 'senior', note: 'read slide 5 against the others', units: 1, secs: 4 }])
      });
    } },
    s6: { label: 'Lead with latency, not cost', run: function () { state.step = Math.max(state.step, 6); stepChange(specLead()); } },
    s7: { label: 'Check the numbers against my sources', run: function () {
      state.checked = true; state.step = Math.max(state.step, 7);
      pushMsg({
        role: 'assistant', kind: 'talk', check: true,
        text: 'I checked the five figures that appear in the deck against your sources. Four are in your documents. One is not there in that exact form.',
        after: 'Nothing is blocked. Tell me if you want the range instead.',
        trace: makeTrace([
          { layer: 'Mechanics', tier: 'low', note: 'extracted the figures', units: 5, secs: 2 },
          { layer: 'Review', tier: 'senior', note: 'matched each to a source', units: 5, secs: 6 }
        ])
      });
    } },
    f5y: { label: 'Yes, cut it down', run: function () {
      ui.followup5 = false;
      pushMsg({ role: 'assistant', kind: 'talk', text: 'In the product this would recompose slide 5. Not scripted here.', trace: { plain: 'Nothing ran. This step is not scripted in the mock-up.' } });
    } },
    f5n: { label: 'Leave it', run: function () {
      ui.followup5 = false;
      pushMsg({ role: 'assistant', kind: 'talk', text: 'Understood. Slide 5 stays as it is. I will not raise it again unless you ask.', trace: { plain: 'Nothing ran. No layers were needed.' } });
    } },
    n1: { label: 'Turn this into a readout deck', list: 'notes', run: function () { stepReadout(); } }
  };

  function say(label, fn, list, about) {
    if (ui.busy) return;
    list = list || 'main';
    pushMsg({ role: 'user', text: label, about: about || null }, list);
    ui.busy = true; ui.busyList = list;
    var g = ui.gen;
    renderChats(); renderComposers(); renderDialogIfOpen();
    setTimeout(function () {
      if (g !== ui.gen) return;
      ui.busy = false; ui.busyList = null;
      fn();
      renderThread();
      if (list === 'notes') { renderChats(); renderComposers(); }
    }, 520);
  }

  function runStep(id) {
    var s = STEPS[id];
    if (!s || ui.busy) return;
    var about = null;
    if (s.sel) {
      var cur = state.selection;
      if (!cur || cur.slide !== s.sel.slide || (s.sel.part !== 'slide' && cur.part !== s.sel.part)) state.selection = { slide: s.sel.slide, part: s.sel.part };
      ui.slide = s.sel.slide;
      about = aboutLabel(state.selection);
    }
    say(s.label, function () {
      state.selection = null;
      s.run();
    }, s.list, about);
    if (s.sel) { renderPanel(); }
  }

  /* ------------------------------------------------------------------ home */

  function renderHome() {
    $('#home-sources').innerHTML = SOURCES.map(function (s) {
      return '<li class="row"><span class="ico" aria-hidden="true"><svg width="14" height="14" viewBox="0 0 14 14"><path d="M3.5 1.5h5l3 3v8h-8z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><path d="M8.5 1.5v3h3" fill="none" stroke="currentColor" stroke-width="1.2"/></svg></span>' +
        '<span class="row-b"><span class="row-t">' + esc(s[0]) + '</span><span class="row-m">' + esc(s[1]) + '</span></span></li>';
    }).join('');
    var design = state.designDecided ? 'design decided: ' + dirOf(state.direction).name : 'design provisional';
    var arts = [
      { t: 'Serving the assistant for less', m: 'Deck · 8 slides · ' + design, href: '#thread', tags: [] },
      { t: 'Scoping call notes', m: 'Notes · 7 sections', href: '#notes', tags: [] },
      { t: 'Board evidence pack', m: 'Deck · 6 slides', href: '#strict', tags: ['<span class="tag tag-strict">Strict</span>'] }
    ];
    if (ui.readout) arts.push({ t: 'Scoping call readout', m: 'Deck · 5 slides · provisional', href: '', tags: ['<span class="tag tag-prov">Provisional</span>'], isNew: true });
    $('#art-count').textContent = arts.length;
    $('#home-artifacts').innerHTML = arts.map(function (a) {
      var inner = '<span class="ico" aria-hidden="true"><svg width="14" height="14" viewBox="0 0 14 14"><rect x="1.5" y="2.5" width="11" height="8" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M4.5 12.5h5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg></span>' +
        '<span class="row-b"><span class="row-t">' + esc(a.t) + (a.isNew ? ' <span class="tag tag-ok">New</span>' : '') + '</span><span class="row-m">' + esc(a.m) + '</span></span>' + a.tags.join('');
      return a.href ? '<li><a class="row link" href="' + a.href + '">' + inner + '</a></li>'
        : '<li><button type="button" class="row link" data-action="toast" data-msg="Not scripted in this mock-up.">' + inner + '</button></li>';
    }).join('');
    $('#home-threads').innerHTML = [
      ['Storyline and first draft', 'Yesterday · closed, read-only', '#history'],
      ['Design and refinement', 'Today · open', '#thread'],
      ['Scoping call notes', '14 July · notes', '#notes']
    ].map(function (t) {
      return '<li><a class="row link" href="' + t[2] + '"><span class="ico" aria-hidden="true"><svg width="14" height="14" viewBox="0 0 14 14"><path d="M2 3.5a1.5 1.5 0 0 1 1.5-1.5h7A1.5 1.5 0 0 1 12 3.5v5A1.5 1.5 0 0 1 10.5 10H6l-3 2.5V10A1.5 1.5 0 0 1 2 8.5z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg></span>' +
        '<span class="row-b"><span class="row-t">' + esc(t[0]) + '</span><span class="row-m">' + esc(t[1]) + '</span></span></a></li>';
    }).join('');
  }

  /* ----------------------------------------------------------- notes view */

  function renderNotes() {
    $('#notes-body').innerHTML = NOTES.map(function (s) {
      return '<section class="n-sec"><h2>' + esc(s.h) + '</h2><ul class="n-list">' + s.items.map(function (it, i) {
        var id = 'q-' + s.h.replace(/\W+/g, '') + i;
        return '<li class="n-item"><div class="n-line"><span class="n-text">' + esc(it[1]) + (it[3] ? ' <span class="tag tag-prov">' + esc(it[3]) + '</span>' : '') + '</span>' +
          '<button type="button" class="time mono" aria-expanded="false" aria-controls="' + id + '">' + it[0] + '</button></div>' +
          '<blockquote class="quote" id="' + id + '" hidden><span class="q-l mono">Transcript ' + it[0] + '</span>' + esc(it[2]) + '</blockquote></li>';
      }).join('') + '</ul></section>';
    }).join('');
  }

  function renderStrict() {
    var dir = state.designDecided ? state.direction : 'a';
    $('#strict-stage').innerHTML = '<div class="stage-slide">' + MS.render('s4', dir, { lead: 'cost', s4Hero: false, s6Short: false }) + '</div>';
    $('#claims-list').innerHTML = CLAIMS.map(function (c, i) {
      var cls = c.v === 'Supported' ? 'ok' : 'part';
      return '<div class="claim"><div class="claim-top"><p class="claim-t">' + esc(c.t) + '</p><span class="verdict v-' + cls + '">' + c.v + '</span></div>' +
        '<button type="button" class="linkbtn" aria-expanded="false" aria-controls="src-' + i + '" data-src="' + i + '">Show source</button>' +
        '<div class="src" id="src-' + i + '" hidden><div class="src-doc">' + esc(c.doc) + ', ' + esc(c.page) + '</div><blockquote class="quote">' + esc(c.q) + '</blockquote></div></div>';
    }).join('');
  }

  /* ------------------------------------------------------------- dialogs */

  var lastFocus = null;
  function dialogItems() {
    var items = [];
    if (!state.designDecided) items.push('The design is provisional. Nobody has chosen it yet.');
    if (state.stale.length) items.push(state.stale.length + ' slides are stale and still show the earlier argument: ' + state.stale.map(slideNum).join(', ') + '.');
    if (state.checked) items.push('One figure is not verified: 38% (slides 1 and 4). The quantisation paper reports a range of 35 to 41%.');
    else items.push('Figures have not been checked against your sources. ' + (ui.busy ? 'Checking now.' : '<button type="button" class="linkbtn" data-action="check-now">Check now</button>'));
    return items;
  }
  function renderDialogIfOpen() { if (!$('#dialog').hidden) $('#dlg-body').innerHTML = '<p>Before you export, note:</p><ul class="items">' + dialogItems().map(function (i) { return '<li>' + (i.indexOf('<button') >= 0 ? i : esc(i)) + '</li>'; }).join('') + '</ul><p class="muted">You can export anyway. Nothing is blocked.</p>'; }
  function openDialog() {
    lastFocus = document.activeElement;
    $('#dialog').hidden = false;
    renderDialogIfOpen();
    $('#dlg-export').focus();
  }
  function closeDialog() {
    $('#dialog').hidden = true;
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  var toastT;
  function toast(msg) {
    var t = $('#toast');
    t.textContent = msg; t.hidden = false;
    clearTimeout(toastT);
    toastT = setTimeout(function () { t.hidden = true; }, 3200);
  }

  /* --------------------------------------------------------------- routing */

  function route() {
    var v = location.hash.replace(/^#/, '');
    if (VIEWS.indexOf(v) < 0) v = 'home';
    VIEWS.forEach(function (n) { $('#' + n).hidden = n !== v; });
    if (v === 'home') renderHome();
    if (v === 'thread') { ui.scroll.main = true; renderThread(); }
    if (v === 'notes') { ui.scroll.notes = true; renderChats(); renderComposers(); }
    if (v === 'strict') renderStrict();
    if (v === 'history') {
      var hist = $('#hist-msgs');
      hist.innerHTML = HISTORY.map(function (m, i) { var c = clone(m); c.id = 'h' + i; return msgHtml(c); }).join('');
    }
    var focusId = { home: 'home-h', thread: 'thread-h', notes: 'notes-h', strict: 'strict-h', history: 'hist-h' }[v];
    var f = document.getElementById(focusId);
    if (f && ui.navigated) f.focus({ preventScroll: true });
    ui.navigated = true;
    var scroller = v === 'home' ? $('#home') : v === 'history' ? $('#history') : v === 'strict' ? $('#strict') : v === 'notes' ? $('#notes') : null;
    if (scroller) scroller.scrollTop = 0;
    document.body.setAttribute('data-view', v);
  }

  function setTab(t) {
    $('#thread').setAttribute('data-tab', t);
    $$('[data-ttab]').forEach(function (b) { b.setAttribute('aria-selected', String(b.getAttribute('data-ttab') === t)); });
  }

  /* ---------------------------------------------------------------- events */

  document.addEventListener('click', function (e) {
    var t = e.target;
    var el;

    if ((el = t.closest('#sw-btn'))) {
      var m = $('#sw-menu');
      m.hidden = !m.hidden;
      el.setAttribute('aria-expanded', String(!m.hidden));
      return;
    }
    if (!t.closest('.switcher')) { $('#sw-menu').hidden = true; $('#sw-btn').setAttribute('aria-expanded', 'false'); }

    if (t.closest('#restart')) {
      reset();
      buildComposers();
      setTab('chat');
      $('#dialog').hidden = true; $('#toast').hidden = true;
      renderNotes(); renderStrict();
      if (location.hash === '#home' || location.hash === '') route(); else location.hash = '#home';
      return;
    }

    if ((el = t.closest('[data-ttab]'))) { setTab(el.getAttribute('data-ttab')); return; }
    if ((el = t.closest('[data-ptab]'))) { ui.ptab = el.getAttribute('data-ptab'); renderPanel(); return; }

    if ((el = t.closest('[data-chip]'))) {
      if (el.getAttribute('aria-disabled') === 'true') return;
      runStep(el.getAttribute('data-chip'));
      return;
    }
    if ((el = t.closest('[data-mode]'))) { state.mode = el.getAttribute('data-mode'); renderComposers(); renderMsgsInto($('#msgs'), ui.msgs, 'main'); return; }
    if ((el = t.closest('[data-route]'))) { state.route = el.getAttribute('data-route'); renderComposers(); return; }

    if ((el = t.closest('.thumb'))) {
      var id = el.getAttribute('data-slide');
      ui.slide = id;
      state.selection = { slide: id, part: 'slide' };
      renderPanel(); renderComposers();
      return;
    }
    if ((el = t.closest('[data-pick]'))) {
      var part = el.getAttribute('data-pick');
      var cur = state.selection;
      state.selection = (cur && cur.slide === ui.slide && cur.part === part) ? null : { slide: ui.slide, part: part };
      renderPanel(); renderComposers();
      return;
    }
    if ((el = t.closest('[data-stage]'))) {
      var r = el.getBoundingClientRect();
      var y = (e.clientY - r.top) / r.height;
      var p = y < 0.26 ? 'header' : 'body';
      var c2 = state.selection;
      state.selection = (c2 && c2.slide === ui.slide && c2.part === p) ? null : { slide: ui.slide, part: p };
      renderPanel(); renderComposers();
      return;
    }

    if ((el = t.closest('.time'))) {
      var q = document.getElementById(el.getAttribute('aria-controls'));
      q.hidden = !q.hidden;
      el.setAttribute('aria-expanded', String(!q.hidden));
      return;
    }
    if ((el = t.closest('[data-src]'))) {
      var s = document.getElementById('src-' + el.getAttribute('data-src'));
      s.hidden = !s.hidden;
      el.setAttribute('aria-expanded', String(!s.hidden));
      el.textContent = s.hidden ? 'Show source' : 'Hide source';
      return;
    }

    if ((el = t.closest('[data-action]'))) {
      var a = el.getAttribute('data-action');
      if (el.getAttribute('aria-disabled') === 'true') return;
      if (a === 'close-menu') { $('#sw-menu').hidden = true; $('#sw-btn').setAttribute('aria-expanded', 'false'); }
      else if (a === 'clear-sel') { state.selection = null; renderPanel(); renderComposers(); }
      else if (a === 'go-chat') setTab('chat');
      else if (a === 'goto-changes') { ui.ptab = 'changes'; setTab('deck'); renderPanel(); }
      else if (a === 'toast') toast(el.getAttribute('data-msg'));
      else if (a === 'export') openDialog();
      else if (a === 'close-dialog') closeDialog();
      else if (a === 'do-export') { closeDialog(); toast('Exported (mock-up: no file is written)'); }
      else if (a === 'check-now') runStep('s7');
      else if (a === 'pick-dir') {
        if (ui.busy || state.designDecided) return;
        var dir = dirOf(el.getAttribute('data-dir'));
        say('Use this direction: ' + dir.name, function () { stepChange(specDirection(dir.id)); });
      }
      else if (a === 'rebuild') {
        if (!state.stale.length) return;
        say('Rebuild the 4 stale slides', function () { stepChange(specRebuild()); });
      }
      else if (a === 'apply' || a === 'dismiss') {
        var mid = +el.getAttribute('data-mid');
        var msg = ui.msgs.concat(ui.notesMsgs).filter(function (x) { return x.id === mid; })[0];
        if (!msg || msg.status !== 'open') return;
        if (a === 'apply') applyProposal(msg);
        else { msg.status = 'dismissed'; renderChats(); }
        if (a === 'apply') { renderThread(); renderHome(); }
      }
      else if (a === 'undo' || a === 'redo') {
        var eid = +el.getAttribute('data-eid');
        var en = state.log.filter(function (x) { return x.id === eid; })[0];
        if (!en) return;
        if (a === 'undo' && undoable(en)) setLog(en, true);
        if (a === 'redo' && redoable(en)) setLog(en, false);
      }
      return;
    }

    if (t.classList && t.classList.contains('scrim') && t.id === 'dialog') closeDialog();
  });

  document.addEventListener('submit', function (e) {
    var f = e.target.closest('.cform');
    if (!f) return;
    e.preventDefault();
    var inp = $('.cinput', f);
    var v = inp.value.trim();
    if (!v || ui.busy) return;
    inp.value = '';
    var scope = f.parentNode.getAttribute('data-scope') === 'notes' ? 'notes' : 'main';
    say(v, function () {
      pushMsg({ role: 'assistant', kind: 'talk', text: 'This is a scripted mock-up. Pick one of the suggested messages to continue.', trace: { plain: 'Nothing ran. Free text is not read in the mock-up.' } }, scope);
    }, scope, scope === 'main' && state.selection ? aboutLabel(state.selection) : null);
  });

  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (!d.matches || !d.matches('details.route')) return;
    var mid = +d.getAttribute('data-mid');
    ui.msgs.concat(ui.notesMsgs).forEach(function (m) { if (m.id === mid) m.open = d.open; });
    if (d.open) d.scrollIntoView({ block: 'nearest' });
  }, true);

  document.addEventListener('keydown', function (e) {
    var dlg = $('#dialog');
    if (e.key === 'Escape') {
      if (!dlg.hidden) { closeDialog(); return; }
      if (!$('#sw-menu').hidden) { $('#sw-menu').hidden = true; $('#sw-btn').setAttribute('aria-expanded', 'false'); $('#sw-btn').focus(); }
    }
    if (e.key === 'Tab' && !dlg.hidden) {
      var f = $$('button, a[href], input', dlg).filter(function (x) { return !x.disabled && x.offsetParent !== null; });
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });

  window.addEventListener('hashchange', route);

  /* ------------------------------------------------------------------ boot */

  (function boot() {
    var st = document.createElement('style');
    st.id = 'ms-css';
    st.textContent = MS.css;
    document.head.appendChild(st);
    reset();
    buildComposers();
    renderNotes();
    renderStrict();
    renderHome();
    route();
  })();
})();
