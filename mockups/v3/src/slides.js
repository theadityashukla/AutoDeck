/* FONT_LINKS
https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..900&family=Fraunces:ital,opsz,wght@0,9..144,300..600;1,9..144,300..600&family=IBM+Plex+Mono:wght@400;500;600&display=swap
*/
/*
 * AutoDeck v3 mock-up: slide content, four design directions, rendering.
 * Contract: SPEC.md section 3. Plain script, defines window.MockSlides.
 * Every size inside a slide is in cqw or %, so a slide renders the same at
 * thumbnail and full size. All content is fictional.
 */
(function () {
  'use strict';

  var IDS = ['s1', 's2', 's3', 's4', 's5', 's6', 's7', 's8'];

  /* ------------------------------------------------------------------ */
  /* Content                                                             */
  /* ------------------------------------------------------------------ */

  function norm(state) {
    state = state || {};
    return {
      lead: state.lead === 'latency' ? 'latency' : 'cost',
      s4Hero: !!state.s4Hero,
      s6Short: !!state.s6Short
    };
  }

  function headerText(id, st) {
    var lat = st.lead === 'latency';
    switch (id) {
      case 's1': return lat ? "Northwind's shopping assistant can answer in under a second"
                            : 'Northwind can serve its shopping assistant at 38% lower cost';
      case 's2': return lat ? 'Shoppers leave when an answer takes more than two seconds'
                            : 'Inference, not training, is now most of the bill';
      case 's3': return lat ? 'Three techniques cut response time and cost together'
                            : 'Three techniques account for most of the saving';
      case 's4': return 'Quantisation alone cuts serving cost by 38%';
      case 's5': return 'Caching repeated context removes a fifth of the compute';
      case 's6': return st.s6Short ? 'Two quarters, three phases'
                                   : 'A phased rollout over two quarters keeps risk low while the savings build';
      case 's7': return lat ? 'What faster answers are worth' : 'What it costs and what it returns';
      case 's8': return 'Decision needed: approve the pilot by 30 November';
    }
    return '';
  }

  function intentText(id, st) {
    var lat = st.lead === 'latency';
    switch (id) {
      case 's1': return lat ? 'Title: open on the speed result' : 'Title: open on the cost result';
      case 's2': return lat ? 'Why it matters: slow answers lose shoppers' : 'Why it matters: the bill has moved to inference';
      case 's3': return 'Overview: the three techniques';
      case 's4': return 'Evidence: the largest single saving';
      case 's5': return 'Evidence: how caching saves compute';
      case 's6': return 'Plan: a low-risk, phased rollout';
      case 's7': return lat ? 'Business case: the value of speed' : 'Business case: cost and return';
      case 's8': return 'Close: the decision and next steps';
    }
    return '';
  }

  var TECH = {
    cost: [
      { n: '01', name: 'Quantisation', what: 'Smaller numbers inside the model, same answers', fig: '&minus;38%', unit: 'serving cost' },
      { n: '02', name: 'Context caching', what: 'Reuse the part every request repeats', fig: '&minus;21%', unit: 'compute' },
      { n: '03', name: 'Request batching', what: 'Answer shoppers in groups at peak', fig: '2.3&times;', unit: 'peak capacity' }
    ],
    latency: [
      { n: '01', name: 'Quantisation', what: 'Smaller numbers inside the model, same answers', fig: '&minus;0.9 s', unit: 'and 38% cheaper' },
      { n: '02', name: 'Context caching', what: 'Reuse the part every request repeats', fig: '&minus;0.7 s', unit: 'and 21% less compute' },
      { n: '03', name: 'Request batching', what: 'Answer shoppers in groups at peak', fig: '&minus;0.2 s', unit: 'and no queue at peak' }
    ]
  };

  var FIGS7 = {
    cost: [
      { fig: '$310k', label: 'one-off cost' },
      { fig: '$1.9M', label: 'saved per year' },
      { fig: '2 mo', label: 'to pay back' }
    ],
    latency: [
      { fig: '+4.1%', label: 'conversion in assistant chats' },
      { fig: '$6.2M', label: 'added revenue a year' },
      { fig: '&minus;27%', label: 'abandoned chats' }
    ]
  };

  var POINTS5 = [
    '68% of every request repeats: the same instructions and catalogue.',
    'That shared part is computed once an hour, then reused.',
    'Net compute falls 21% after misses and refreshes.',
    'Answers are unchanged; the cache resets when prices change.'
  ];

  var REQ5 = [
    { label: 'Instructions', pct: 18, cached: true },
    { label: 'Catalogue', pct: 50, cached: true },
    { label: 'Chat', pct: 22, cached: false },
    { label: 'Ask', pct: 10, cached: false }
  ];

  var PHASES = [
    { name: 'Pilot', when: 'Jan&ndash;Feb', what: 'Quantised model on 5% of traffic', save: '15%' },
    { name: 'Scale', when: 'Mar&ndash;Apr', what: 'All traffic, plus context caching', save: '30%' },
    { name: 'Optimise', when: 'May&ndash;Jun', what: 'Batching at peak, full run rate', save: '38%' }
  ];

  var STEPS8 = [
    { when: '2 Dec', what: 'Kick-off with the platform team' },
    { when: '9 Dec', what: 'Quantised model in shadow mode' },
    { when: '13 Jan', what: 'First savings report' }
  ];

  var ABANDON = [
    { t: 'under 1 s', v: 6 }, { t: '1&ndash;2 s', v: 9 }, { t: '2&ndash;3 s', v: 21 }, { t: 'over 3 s', v: 34 }
  ];

  function pg(id) { return '0' + id.slice(1) + ' / 08'; }

  function hdr(cls, id, st, inner) {
    return '<h2 class="' + cls + '" data-part="header">' + (inner || headerText(id, st)) + '</h2>';
  }

  /* ------------------------------------------------------------------ */
  /* Direction: default (the "before")                                   */
  /* ------------------------------------------------------------------ */

  function dShell(id, st, body) {
    return '<div class="ms-in">' + hdr('d-h', id, st) + '<div class="d-bar"></div>' +
      '<div class="d-body" data-part="body">' + body + '</div>' +
      '<div class="d-foot"><span>Northwind Retail&nbsp;&nbsp;|&nbsp;&nbsp;Serving the assistant for less</span><span>' + id.slice(1) + '</span></div></div>';
  }
  function dUl(items, cls) {
    return '<ul class="d-ul ' + (cls || '') + '">' + items.map(function (t) { return '<li>' + t + '</li>'; }).join('') + '</ul>';
  }

  var D = {
    s1: function (st) {
      var lat = st.lead === 'latency';
      return '<div class="ms-in d-title"><div class="d-kick">PROPOSAL</div>' + hdr('d-th', 's1', st) +
        '<div class="d-sub" data-part="body">Serving the assistant for less<br><span>' +
        (lat ? 'Median answer time: 2.6 s today, 0.8 s proposed' : 'Cost per 1,000 answers: $4.20 today, $2.60 proposed') +
        '</span></div><div class="d-band"><span>Northwind Retail&nbsp;&nbsp;|&nbsp;&nbsp;November 2026</span><span>Confidential</span></div></div>';
    },
    s2: function (st) {
      if (st.lead === 'latency') {
        return dShell('s2', st, '<div class="d-two">' +
          dUl(['Chat abandonment more than doubles past two seconds', 'Median answer today: 2.6 seconds', 'Source: Northwind assistant logs, Q3 2026']) +
          '<div class="d-chart"><div class="d-ctitle">Abandoned chats by wait time</div><div class="d-vbars">' +
          ABANDON.map(function (a) { return '<div class="d-vb"><div class="d-vbf" style="height:' + (a.v / 34 * 100) + '%"><span>' + a.v + '%</span></div><em>' + a.t + '</em></div>'; }).join('') +
          '</div></div></div>');
      }
      return dShell('s2', st, '<div class="d-two">' +
        dUl(['Inference is 79% of AI spend in 2026, up from 42% in 2024', 'Every shopper question adds cost; training is a one-off', 'Source: Northwind finance, FY2026 forecast']) +
        '<div class="d-chart"><div class="d-ctitle">Share of AI spend</div><div class="d-vbars d-stk">' +
        [['2024', 42], ['2026', 79]].map(function (y) {
          return '<div class="d-vb"><div class="d-col"><div class="d-c2" style="height:' + (100 - y[1]) + '%">' + (100 - y[1]) + '%</div><div class="d-c1" style="height:' + y[1] + '%">' + y[1] + '%</div></div><em>' + y[0] + '</em></div>';
        }).join('') + '</div><div class="d-leg"><i class="k1"></i>Inference <i class="k2"></i>Training</div></div></div>');
    },
    s3: function (st) {
      var t = TECH[st.lead];
      return dShell('s3', st, '<div class="d-three">' + t.map(function (x, i) {
        return '<div class="d-c"><div class="d-num">' + (i + 1) + '</div><h3>' + x.name + '</h3><p>' + x.what + '</p><p class="d-m">' + x.fig + ' ' + x.unit + '</p></div>';
      }).join('') + '</div>');
    },
    s4: function (st) {
      if (st.s4Hero) {
        return dShell('s4', st, '<div class="d-hero"><div class="d-big">38%</div><div class="d-bigt">lower monthly serving cost with 8-bit weights</div></div>' +
          '<div class="d-fn">Monthly serving cost: $412k before, $255k after. Same answer quality on 2,000 test questions.</div>');
      }
      return dShell('s4', st, '<div class="d-two">' + dUl(['8-bit weights instead of 16-bit', 'Same answer quality on 2,000 test questions', 'Monthly cost falls by $157k']) +
        '<div class="d-chart"><div class="d-ctitle">Monthly serving cost</div>' +
        '<div class="d-hb"><em>Before</em><div class="d-hbt"><div class="d-hbf k2" style="width:100%"></div></div><span>$412k</span></div>' +
        '<div class="d-hb"><em>After</em><div class="d-hbt"><div class="d-hbf" style="width:62%"></div></div><span>$255k</span></div></div></div>');
    },
    s5: function (st) {
      return dShell('s5', st, '<div class="d-two d-dense"><div class="d-chart"><div class="d-ctitle">One request (2,400 tokens)</div><div class="d-req">' +
        REQ5.map(function (r) { return '<div class="' + (r.cached ? 'k1' : 'k2') + '" style="width:' + r.pct + '%">' + r.pct + '%</div>'; }).join('') +
        '</div><div class="d-reql">' + REQ5.map(function (r) { return '<span style="width:' + r.pct + '%">' + r.label + '</span>'; }).join('') +
        '</div><div class="d-leg"><i class="k1"></i>Cached <i class="k2"></i>Computed each time</div></div>' + dUl(POINTS5, 'd-sm') + '</div>');
    },
    s6: function (st) {
      return dShell('s6', st, '<div class="d-tl"><div class="d-line"></div>' + PHASES.map(function (p, i) {
        return '<div class="d-ph"><div class="d-dot">' + (i + 1) + '</div><h3>' + p.name + '</h3><p class="d-m">' + p.when + ' 2027</p><p>' + p.what + '</p><p>Savings: ' + p.save + '</p></div>';
      }).join('') + '</div>');
    },
    s7: function (st) {
      return dShell('s7', st, '<div class="d-three">' + FIGS7[st.lead].map(function (f) {
        return '<div class="d-kpi"><div class="d-kv">' + f.fig + '</div><p>' + f.label + '</p></div>';
      }).join('') + '</div>');
    },
    s8: function (st) {
      return dShell('s8', st, '<div class="d-two"><div class="d-ask"><h3>The ask</h3><p>Approve a six-week pilot on 5% of assistant traffic.</p><p>Budget: $85k</p></div>' +
        '<div><h3 class="d-h3">Next steps</h3>' + dUl(STEPS8.map(function (s) { return s.when + ': ' + s.what; })) + '</div></div>');
    }
  };

  /* ------------------------------------------------------------------ */
  /* Direction a: Itemised (the receipt)                                 */
  /* ------------------------------------------------------------------ */

  var ZIG = (function () {
    var p = ['0% 0%', '100% 0%'];
    var n = 24;
    for (var i = n; i >= 0; i--) {
      var x = (i / n * 100).toFixed(3);
      p.push(x + '% ' + (i % 2 === 0 ? '100%' : 'calc(100% - 1.1cqw)'));
    }
    return 'polygon(' + p.join(',') + ')';
  })();

  function aLi(l, v, cls) {
    return '<div class="a-li ' + (cls || '') + '"><span class="l">' + l + '</span><span class="dots"></span><span class="v">' + v + '</span></div>';
  }
  function aRc(inner, cls) {
    return '<div class="a-rcw ' + (cls || '') + '"><div class="a-rc" data-part="body">' + inner + '</div></div>';
  }
  function aTop(title, meta) {
    return '<div class="a-shop">' + title + '</div><div class="a-meta">' + meta + '</div><div class="a-sep"></div>';
  }
  function aSide(id, st, kicker, below, hcls) {
    return '<div class="a-side"><div class="a-k">' + pg(id) + '&nbsp;&nbsp;&middot;&nbsp;&nbsp;' + kicker + '</div>' +
      hdr('a-h ' + (hcls || ''), id, st) + (below || '') + '</div>';
  }
  function aBar(pct, cls) {
    return '<div class="a-bar ' + (cls || '') + '"><i style="width:' + pct + '%"></i></div>';
  }

  var A = {
    s1: function (st) {
      var lat = st.lead === 'latency';
      var rc = lat
        ? aTop('NORTHWIND RETAIL', 'Shopping assistant &middot; median answer') +
          aLi('Today', '2.6 s') + aLi('Quantised model', '&minus;0.9 s') + aLi('Cached context', '&minus;0.7 s') + aLi('Batched queue', '&minus;0.2 s') +
          '<div class="a-sep"></div>' + aLi('NEW ANSWER TIME', '<b class="a-hl">0.8 s</b>', 'a-tot')
        : aTop('NORTHWIND RETAIL', 'Shopping assistant &middot; per 1,000 answers') +
          aLi('Answers a month', '3.1M') + aLi('Cost today', '$4.20') + aLi('Quantised model', '&minus;$1.60') + aLi('New cost', '$2.60') +
          '<div class="a-sep"></div>' + aLi('SAVING', '<b class="a-hl">38%</b>', 'a-tot');
      rc += '<div class="a-sep"></div><div class="a-meta">PROPOSAL NW-2611 &middot; NOV 2026<br>THANK YOU FOR READING</div>';
      return '<div class="ms-in">' + aRc(rc) + aSide('s1', st, 'Proposal', '<div class="a-note"><b>Serving the assistant for less</b><br>For Northwind Retail &middot; November 2026</div>', 'a-h1') + '</div>';
    },
    s2: function (st) {
      var rc;
      if (st.lead === 'latency') {
        rc = aTop('ABANDONED CHATS', 'by wait for an answer &middot; Q3 2026') +
          ABANDON.map(function (a, i) {
            return (i === 2 ? '<div class="a-cut">&mdash; 2 s &mdash;</div>' : '') + aLi(a.t, a.v + '%', i > 1 ? 'a-em' : '') + aBar(a.v / 34 * 100, i > 1 ? 'a-bar-hl' : '');
          }).join('') + '<div class="a-sep"></div>' + aLi('TODAY, MEDIAN', '<b class="a-hl">2.6 s</b>', 'a-tot');
        return '<div class="ms-in">' + aRc(rc) + aSide('s2', st, 'Why now', '<div class="a-note">Past two seconds, one chat in five is abandoned. The assistant answers in 2.6 s today.</div>') + '</div>';
      }
      rc = aTop('AI SPEND, NORTHWIND', 'share by type &middot; FY2024 vs FY2026') +
        '<div class="a-yr">FY2024</div>' + aLi('Training', '58%') + aBar(58) + aLi('Inference', '42%') + aBar(42, 'a-bar-hl') +
        '<div class="a-yr">FY2026</div>' + aLi('Training', '21%') + aBar(21) + aLi('Inference', '79%', 'a-em') + aBar(79, 'a-bar-hl') +
        '<div class="a-sep"></div>' + aLi('INFERENCE', '<b class="a-hl">79%</b>', 'a-tot');
      return '<div class="ms-in">' + aRc(rc) + aSide('s2', st, 'Why now', '<div class="a-note">Training is paid once. Every shopper question is paid every time: 3.1M of them a month.</div>') + '</div>';
    },
    s3: function (st) {
      var t = TECH[st.lead];
      var rc = aTop('THREE TECHNIQUES', st.lead === 'latency' ? 'seconds saved per answer' : 'what each one removes') +
        t.map(function (x) {
          return '<div class="a-item">' + aLi(x.n + ' ' + x.name, '<b>' + x.fig + '</b>') + '<div class="a-sub">' + x.unit + '</div></div>';
        }).join('') + '<div class="a-sep"></div>' +
        (st.lead === 'latency' ? aLi('TOTAL', '<b class="a-hl">&minus;1.8 s</b>', 'a-tot') : aLi('LARGEST', '<b class="a-hl">38%</b>', 'a-tot'));
      var below = '<ol class="a-list">' + t.map(function (x) { return '<li><span>' + x.n + '</span>' + x.what + '</li>'; }).join('') + '</ol>';
      return '<div class="ms-in">' + aRc(rc) + aSide('s3', st, 'The method', below) + '</div>';
    },
    s4: function (st) {
      if (st.s4Hero) {
        var stub = aTop('MONTHLY SERVING', 'before and after') + aLi('Before', '$412k') + aLi('After', '$255k');
        return '<div class="ms-in">' + aRc(stub, 'a-stub') +
          aSide('s4', st, 'Quantisation', '<div class="a-hero">&minus;38%</div><div class="a-note">8-bit weights. Same answer quality on 2,000 test questions.</div>', 'a-hs') + '</div>';
      }
      var rc = aTop('MONTHLY SERVING', '3.1M answers &middot; 16-bit vs 8-bit') +
        aLi('Before', '$412,000') + aBar(100, 'a-bar-tall') + aLi('After', '$255,000') + aBar(62, 'a-bar-tall a-bar-hl') +
        '<div class="a-sep"></div>' + aLi('Saved a month', '$157,000') + aLi('SAVING', '<b class="a-hl">38%</b>', 'a-tot');
      return '<div class="ms-in">' + aRc(rc) + aSide('s4', st, 'Quantisation', '<div class="a-note">8-bit weights instead of 16-bit. Same answer quality on 2,000 test questions.</div>') + '</div>';
    },
    s5: function (st) {
      var rc = aTop('ONE REQUEST', '2,400 tokens &middot; what is in it') +
        '<div class="a-req">' + REQ5.map(function (r) { return '<i class="' + (r.cached ? 'c' : '') + '" style="width:' + r.pct + '%"></i>'; }).join('') + '</div>' +
        '<div class="a-brace"><span style="width:68%">cached, reused</span><span style="width:32%">fresh</span></div>' +
        REQ5.map(function (r) { return aLi(r.label + (r.cached ? ' *' : ''), r.pct + '%'); }).join('') +
        '<div class="a-sep"></div>' + aLi('Repeated', '68%') + aLi('COMPUTE SAVED', '<b class="a-hl">21%</b>', 'a-tot') +
        '<div class="a-meta">* refreshed hourly</div>';
      var below = '<ol class="a-list a-list-sm">' + POINTS5.map(function (p, i) { return '<li><span>0' + (i + 1) + '</span>' + p + '</li>'; }).join('') + '</ol>';
      return '<div class="ms-in">' + aRc(rc) + aSide('s5', st, 'Context caching', below, 'a-hsm') + '</div>';
    },
    s6: function (st) {
      var rc = aTop('ROLLOUT', 'Q1&ndash;Q2 2027 &middot; savings run rate') +
        PHASES.map(function (p, i) {
          return (i === 2 ? '<div class="a-yr">Q2 2027</div>' : (i === 0 ? '<div class="a-yr">Q1 2027</div>' : '')) +
            '<div class="a-item">' + aLi(p.when + ' ' + p.name, '<b>' + p.save + '</b>') + '<div class="a-sub">' + p.what + '</div></div>';
        }).join('') + '<div class="a-sep"></div>' + aLi('RUN RATE, JUN', '<b class="a-hl">38%</b>', 'a-tot');
      var steps = '<div class="a-steps">' + PHASES.map(function (p, i) {
        return '<div class="a-step" style="height:' + [40, 70, 100][i] + '%"><b>' + p.save + '</b><span>' + p.name + '</span></div>';
      }).join('') + '</div>';
      return '<div class="ms-in">' + aRc(rc) + aSide('s6', st, 'The plan', steps) + '</div>';
    },
    s7: function (st) {
      var lat = st.lead === 'latency';
      var rc = lat
        ? aTop('WORTH OF SPEED', 'per year &middot; assistant chats') +
          aLi('Chats a year', '37M') + aLi('Conversion', '3.20%') + aLi('Faster, measured', '3.33%') + aLi('Extra orders', '48,000') + aLi('Avg basket', '$129') +
          '<div class="a-sep"></div>' + aLi('ADDED REVENUE', '<b class="a-hl">$6.2M</b>', 'a-tot')
        : aTop('THE BILL', 'one-off and recurring') +
          aLi('Engineering', '$240,000') + aLi('Evaluation', '$70,000') + aLi('One-off cost', '$310,000') +
          '<div class="a-sep"></div>' + aLi('Saved a month', '$157,000') + aLi('SAVED A YEAR', '<b class="a-hl">$1.9M</b>', 'a-tot');
      var figs = '<div class="a-figs">' + FIGS7[st.lead].map(function (f) {
        return '<div><b>' + f.fig + '</b><span>' + f.label + '</span></div>';
      }).join('') + '</div>';
      return '<div class="ms-in">' + aRc(rc) + aSide('s7', st, 'The case', figs) + '</div>';
    },
    s8: function (st) {
      var rc = aTop('PILOT ORDER', 'for approval &middot; NW-2611') +
        aLi('Scope', '6 weeks') + aLi('Traffic', '5%') + aLi('Budget', '$85,000') +
        '<div class="a-sep"></div>' + aLi('APPROVE BY', '<b class="a-hl">30 NOV</b>', 'a-tot') +
        '<div class="a-sign"><span></span>Approved, Northwind Retail</div>';
      var below = '<div class="a-next">' + STEPS8.map(function (s) {
        return '<div><b>' + s.when + '</b><span>' + s.what + '</span></div>';
      }).join('') + '</div>';
      return '<div class="ms-in">' + aRc(rc) + aSide('s8', st, 'The ask', below) + '</div>';
    }
  };

  /* ------------------------------------------------------------------ */
  /* Direction b: Shelf price (the price ticket)                         */
  /* ------------------------------------------------------------------ */

  function bShelf(id, note) {
    return '<div class="b-shelf"><span class="b-bc"></span><span>Northwind Retail</span><span class="b-fine">' + (note || 'Serving the assistant for less') + '</span><span class="b-pg">' + pg(id) + '</span></div>';
  }
  function bTag(inner, cls, style) {
    return '<div class="b-tag ' + (cls || '') + '"' + (style ? ' style="' + style + '"' : '') + '>' + inner + '</div>';
  }

  var B = {
    s1: function (st) {
      var lat = st.lead === 'latency';
      var tag = lat
        ? '<div class="b-tl">Median answer</div><div class="b-was">was 2.6 s</div><div class="b-big">0.8<small>s</small></div><div class="b-tf">even at the 8 pm peak</div>'
        : '<div class="b-tl">Per 1,000 answers</div><div class="b-was">was $4.20</div><div class="b-big">$2.60</div><div class="b-tf">38% lower serving cost</div>';
      return '<div class="ms-in">' + hdr('b-h b-h1', 's1', st) +
        '<div data-part="body">' + bTag(tag, 'b-tag-r') + '<div class="b-meta">A proposal to Northwind Retail<br>November 2026</div></div>' + bShelf('s1') + '</div>';
    },
    s2: function (st) {
      if (st.lead === 'latency') {
        return '<div class="ms-in">' + hdr('b-h', 's2', st) + '<div data-part="body">' +
          bTag('<div class="b-tl">Wait limit</div><div class="b-big">2<small>s</small></div><div class="b-tf">after that, 1 in 5 chats ends</div>', 'b-tag-r') +
          '<div class="b-vbars"><div class="b-lim"><span>2 s</span></div>' + ABANDON.map(function (a, i) {
            return '<div class="b-vb"><div class="b-vbf' + (i > 1 ? ' hot' : '') + '" style="height:' + (a.v / 34 * 100) + '%"><b>' + a.v + '%</b></div><span>' + a.t + '</span></div>';
          }).join('') + '</div></div>' + bShelf('s2', 'Abandoned chats by wait, Q3 2026') + '</div>';
      }
      return '<div class="ms-in">' + hdr('b-h', 's2', st) + '<div data-part="body">' +
        bTag('<div class="b-tl">Inference share</div><div class="b-was">was 42%</div><div class="b-big">79%</div><div class="b-tf">of AI spend in 2026</div>', 'b-tag-r') +
        '<div class="b-rows">' + [['2024', 42], ['2026', 79]].map(function (y) {
          return '<div class="b-row"><span class="b-yr">' + y[0] + '</span><div class="b-track"><div class="b-tr" style="width:' + (100 - y[1]) + '%">Training ' + (100 - y[1]) + '%</div><div class="b-inf" style="width:' + y[1] + '%">Inference ' + y[1] + '%</div></div></div>';
        }).join('') + '</div></div>' + bShelf('s2', 'Share of AI spend, Northwind finance') + '</div>';
    },
    s3: function (st) {
      return '<div class="ms-in">' + hdr('b-h b-hw', 's3', st) + '<div class="b-rail" data-part="body">' +
        TECH[st.lead].map(function (x, i) {
          return bTag('<div class="b-tl">' + x.n + ' &middot; ' + x.name + '</div><div class="b-mid">' + x.fig + '</div><div class="b-tf"><b>' + x.unit + '</b><br>' + x.what + '</div>', 'b-tag-s' + (i === 0 ? ' b-lead' : ''));
        }).join('') + '</div>' + bShelf('s3') + '</div>';
    },
    s4: function (st) {
      if (st.s4Hero) {
        return '<div class="ms-in">' + hdr('b-h b-hn', 's4', st) +
          '<div data-part="body"><div class="b-hero">38<small>%</small></div><div class="b-herot">less to serve,<br>every month</div></div>' +
          bShelf('s4', '$412k &rarr; $255k a month &middot; 8-bit weights &middot; same answers') + '</div>';
      }
      return '<div class="ms-in">' + hdr('b-h', 's4', st) + '<div data-part="body">' +
        bTag('<div class="b-tl">Monthly serving</div><div class="b-was">was $412k</div><div class="b-big">$255k</div><div class="b-tf">8-bit weights, same answers</div>', 'b-tag-r') +
        '<div class="b-hbars"><div class="b-hb"><span>Before</span><div class="b-hbt"><div class="b-hbf old" style="width:100%"></div></div><b class="strike">$412k</b></div>' +
        '<div class="b-hb"><span>After</span><div class="b-hbt"><div class="b-hbf" style="width:62%"></div><em>&minus;38%</em></div><b>$255k</b></div></div></div>' +
        bShelf('s4', 'Monthly serving cost, 3.1M answers') + '</div>';
    },
    s5: function (st) {
      return '<div class="ms-in">' + hdr('b-h', 's5', st) + '<div data-part="body">' +
        bTag('<div class="b-tl">Compute</div><div class="b-was">was 100%</div><div class="b-big">79%</div><div class="b-tf">after caching</div>', 'b-tag-r') +
        '<div class="b-diag"><div class="b-dl">One request, 2,400 tokens</div><div class="b-req">' + REQ5.map(function (r) {
          return '<div class="' + (r.cached ? 'c' : '') + '" style="width:' + r.pct + '%"><b>' + r.pct + '%</b><span>' + r.label + '</span></div>';
        }).join('') + '</div><div class="b-brk"><span style="width:68%">cached, computed once an hour</span></div></div>' +
        '<ol class="b-pts">' + POINTS5.map(function (p, i) { return '<li><b>' + (i + 1) + '</b>' + p + '</li>'; }).join('') + '</ol></div>' +
        bShelf('s5', 'Context caching') + '</div>';
    },
    s6: function (st) {
      return '<div class="ms-in">' + hdr('b-h' + (st.s6Short ? ' b-hn' : ' b-h6'), 's6', st) + '<div class="b-stairs" data-part="body">' +
        PHASES.map(function (p, i) {
          return '<div class="b-st" style="height:' + [52, 76, 100][i] + '%">' + bTag('<div class="b-tl">' + p.when + ' 2027</div><div class="b-mid">' + p.save + '</div><div class="b-tf"><b>' + p.name + '</b><br>' + p.what + '</div>', 'b-tag-s' + (i === 2 ? ' b-lead' : '')) + '</div>';
        }).join('') + '</div>' + bShelf('s6', 'Savings run rate by phase &middot; Q1 and Q2 2027') + '</div>';
    },
    s7: function (st) {
      return '<div class="ms-in">' + hdr('b-h b-hw', 's7', st) + '<div class="b-rail b-rail7" data-part="body">' +
        FIGS7[st.lead].map(function (f, i) {
          return bTag('<div class="b-mid">' + f.fig + '</div><div class="b-tf"><b>' + f.label + '</b></div>', 'b-tag-s' + (i === 1 ? ' b-lead' : ''));
        }).join('') + '</div>' + bShelf('s7', st.lead === 'latency' ? 'Measured on a 5% test group, Q3 2026' : 'Payback from the monthly saving of $157k') + '</div>';
    },
    s8: function (st) {
      return '<div class="ms-in">' + hdr('b-h b-hw', 's8', st) + '<div data-part="body">' +
        bTag('<div class="b-tl">The ask</div><div class="b-mid">$85k</div><div class="b-tf"><b>six-week pilot</b><br>on 5% of assistant traffic</div>', 'b-tag-ask') +
        '<div class="b-next"><div class="b-dl">Next steps</div>' + STEPS8.map(function (s) { return '<div><b>' + s.when + '</b><span>' + s.what + '</span></div>'; }).join('') + '</div></div>' +
        bShelf('s8', 'Approve by 30 November 2026') + '</div>';
    }
  };

  /* ------------------------------------------------------------------ */
  /* Direction c: Demand curve (one line through the day)                */
  /* ------------------------------------------------------------------ */

  var VB_W = 160, VB_H = 90;
  function X(x) { return (x / VB_W * 100).toFixed(2) + '%'; }
  function Y(y) { return (y / VB_H * 100).toFixed(2) + '%'; }
  function f2(n) { return Math.round(n * 100) / 100; }

  function smooth(pts) {
    var d = 'M' + f2(pts[0][0]) + ' ' + f2(pts[0][1]);
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      d += ' C' + f2(p1[0] + (p2[0] - p0[0]) / 6) + ' ' + f2(p1[1] + (p2[1] - p0[1]) / 6) + ' ' +
        f2(p2[0] - (p3[0] - p1[0]) / 6) + ' ' + f2(p2[1] - (p3[1] - p1[1]) / 6) + ' ' + f2(p2[0]) + ' ' + f2(p2[1]);
    }
    return d;
  }
  var DAY = [0.12, 0.08, 0.06, 0.05, 0.06, 0.1, 0.2, 0.32, 0.42, 0.5, 0.58, 0.72, 0.86, 0.8, 0.66, 0.6, 0.62, 0.7, 0.84, 0.96, 1, 0.82, 0.5, 0.25, 0.14];
  function dayPts(x0, x1, base, amp, scale) {
    return DAY.map(function (v, i) { return [x0 + (x1 - x0) * i / (DAY.length - 1), base - amp * v * (scale || 1)]; });
  }
  function svg(inner) {
    return '<svg class="c-svg" viewBox="0 0 160 90" aria-hidden="true">' + inner + '</svg>';
  }
  function cLab(x, y, inner, cls, align) {
    var st = 'top:' + Y(y) + ';';
    if (align === 'right') st += 'right:' + X(VB_W - x) + ';text-align:right;';
    else st += 'left:' + X(x) + ';';
    return '<div class="c-l ' + (cls || '') + '" style="' + st + '">' + inner + '</div>';
  }
  var EMPH = {
    s1c: '38% lower cost', s1l: 'under a second', s2c: 'Inference', s2l: 'two seconds', s3c: 'Three techniques', s3l: 'Three techniques',
    s4: '38%', s5: 'a fifth', s6: 'two quarters', s6s: 'Two quarters', s7c: 'returns', s7l: 'worth', s8: '30 November'
  };
  function cHead(id, st, cls) {
    var lat = st.lead === 'latency';
    var key = id;
    if (id === 's1' || id === 's2' || id === 's3' || id === 's7') key = id + (lat ? 'l' : 'c');
    if (id === 's6' && st.s6Short) key = 's6s';
    var t = headerText(id, st), p = EMPH[key];
    if (p && t.indexOf(p) >= 0) t = t.replace(p, '<em>' + p + '</em>');
    return hdr('c-h ' + (cls || ''), id, st, t);
  }
  function cKick(id, label) {
    return '<div class="c-k">' + pg(id) + '&nbsp;&nbsp;&mdash;&nbsp;&nbsp;' + label + '</div>';
  }

  var Cd = {
    s1: function (st) {
      var lat = st.lead === 'latency';
      var demand = dayPts(0, 160, 80, 30);
      var g = '<path d="' + smooth(demand) + ' L160 90 L0 90 Z" class="c-fill"/>' +
        '<path d="' + smooth(demand) + '" class="' + (lat ? 'c-line' : 'c-line2') + '"/>';
      var labs = '';
      if (lat) {
        g += '<circle cx="133.33" cy="50" r="1.3" class="c-dot"/>';
        labs = cLab(130, 37.5, '<b>0.8 s</b> median answer,<br>even at the 8 pm peak', 'c-ann', 'right');
      } else {
        var after = dayPts(0, 160, 80, 30, 0.62);
        g += '<path d="' + smooth(after) + '" class="c-line"/>';
        g += '<line x1="133.33" y1="50" x2="133.33" y2="61.4" class="c-gap"/>';
        labs = cLab(130, 39.5, '<b>&minus;38%</b> serving cost,<br>hour by hour', 'c-ann', 'right');
      }
      return '<div class="ms-in">' + svg(g) + cKick('s1', 'A proposal to Northwind Retail') + cHead('s1', st, 'c-h1') +
        '<div data-part="body">' + labs + cLab(11, 82.5, 'Serving the assistant for less&nbsp;&nbsp;&middot;&nbsp;&nbsp;November 2026', 'c-meta') + '</div></div>';
    },
    s2: function (st) {
      if (st.lead === 'latency') {
        var xs = [24, 62, 100, 138];
        var pts = ABANDON.map(function (a, i) { return [xs[i], 82 - a.v * 1.05]; });
        var g = '<line x1="12" y1="82" x2="150" y2="82" class="c-axis"/>' +
          '<path d="' + smooth([[12, 82 - 5 * 1.05]].concat(pts).concat([[150, 82 - 36 * 1.05]])) + '" class="c-line"/>' +
          '<line x1="81" y1="40" x2="81" y2="82" class="c-gap"/>' +
          pts.map(function (p) { return '<circle cx="' + p[0] + '" cy="' + f2(p[1]) + '" r="1.1" class="c-dot"/>'; }).join('');
        var labs = ABANDON.map(function (a, i) {
          return cLab(xs[i] - 2, pts[i][1] - 8.5, a.v + '%', 'c-v') + cLab(xs[i] - 4, 84, a.t, 'c-ax');
        }).join('') + cLab(83, 40, '2 s: abandonment<br>more than doubles', 'c-ann2');
        return '<div class="ms-in">' + svg(g) + cKick('s2', 'Why speed matters') + cHead('s2', st) + '<div data-part="body">' + labs + '</div></div>';
      }
      var yrs = [['2022', 30], ['2023', 36], ['2024', 42], ['2025', 63], ['2026', 79]];
      var xs2 = [12, 46.5, 81, 115.5, 150];
      var top = yrs.map(function (y, i) { return [xs2[i], 82 - 42 * y[1] / 100]; });
      var g2 = '<rect x="12" y="40" width="138" height="42" class="c-band"/>' +
        '<path d="' + smooth(top) + ' L150 82 L12 82 Z" class="c-area"/>' +
        '<path d="' + smooth(top) + '" class="c-line"/>' +
        [2, 4].map(function (i) { return '<circle cx="' + xs2[i] + '" cy="' + f2(top[i][1]) + '" r="1.2" class="c-dot"/>'; }).join('');
      var labs2 = yrs.map(function (y, i) { return cLab(xs2[i] - (i === 4 ? 6 : i === 0 ? 0 : 3), 84, y[0], 'c-ax'); }).join('') +
        cLab(16, 43, 'Training', 'c-ax c-in') + cLab(16, 74, 'Inference', 'c-ax c-dark') +
        cLab(83, top[2][1] - 6.5, '42%', 'c-v') + cLab(146, top[4][1] - 6.5, '79%', 'c-v', 'right');
      return '<div class="ms-in">' + svg(g2) + cKick('s2', 'Where the money goes') + cHead('s2', st) + '<div data-part="body">' + labs2 + '</div></div>';
    },
    s3: function (st) {
      var pts = [[0, 38], [24, 44], [70, 55], [114, 64], [160, 70]];
      var g = '<path d="' + smooth(pts) + '" class="c-line"/>' +
        [1, 2, 3].map(function (i) { return '<circle cx="' + pts[i][0] + '" cy="' + pts[i][1] + '" r="1.3" class="c-dot"/>'; }).join('');
      var labs = TECH[st.lead].map(function (x, i) {
        var p = pts[i + 1];
        return cLab(p[0] - 1.5, p[1] + 3, '<div class="c-fig3">' + x.fig + '</div><div class="c-n">' + x.name + '</div><div class="c-d">' + x.unit + '</div>', 'c-blk');
      }).join('');
      return '<div class="ms-in">' + svg(g) + cKick('s3', 'The method') + cHead('s3', st) + '<div data-part="body">' + labs + '</div></div>';
    },
    s4: function (st) {
      if (st.s4Hero) {
        var dip = [[0, 70], [40, 71], [80, 76], [120, 82], [160, 83]];
        var g = '<path d="' + smooth(dip) + '" class="c-line"/>';
        return '<div class="ms-in">' + svg(g) + cKick('s4', 'Quantisation') + cHead('s4', st, 'c-hs') +
          '<div data-part="body"><div class="c-hero">38%</div>' +
          cLab(11, 79, 'Monthly serving cost: $412k before, $255k after. 8-bit weights; same answers on 2,000 test questions.', 'c-meta') + '</div></div>';
      }
      var g2 = '<line x1="12" y1="47" x2="132" y2="47" class="c-bar1"/><line x1="12" y1="64" x2="86.4" y2="64" class="c-bar2"/>' +
        '<line x1="86.4" y1="64" x2="132" y2="64" class="c-ghost"/><line x1="132" y1="49" x2="132" y2="62" class="c-gap"/>';
      var labs = cLab(12, 37.5, 'Before &middot; 16-bit', 'c-ax') + cLab(12, 54.5, 'After &middot; 8-bit', 'c-ax') +
        cLab(135, 44.4, '$412k', 'c-v') + cLab(86.4, 67, '$255k', 'c-v', 'right') + cLab(112, 66.5, '&minus;38%', 'c-fig4') +
        cLab(11, 82.5, 'Monthly serving cost, 3.1M answers. Same answer quality on 2,000 test questions.', 'c-meta');
      return '<div class="ms-in">' + svg(g2) + cKick('s4', 'Quantisation') + cHead('s4', st) + '<div data-part="body">' + labs + '</div></div>';
    },
    s5: function (st) {
      var x = 11, w = 76, g = '', labs = '';
      REQ5.forEach(function (r) {
        var ww = w * r.pct / 100;
        g += '<rect x="' + f2(x + 0.3) + '" y="48" width="' + f2(ww - 0.6) + '" height="6" class="' + (r.cached ? 'c-seg1' : 'c-seg2') + '"/>';
        labs += cLab(x + 0.3, 56, r.pct + '%<br><span>' + r.label + '</span>', 'c-segl');
        x += ww;
      });
      g += '<path d="M11.3 45 L11.3 43 L62.4 43 L62.4 45" class="c-brk"/>';
      labs += cLab(11.3, 36.5, 'computed once an hour, reused', 'c-ann3') + cLab(11, 69, 'One request, 2,400 tokens', 'c-ax');
      var bot = dayPts(0, 160, 88, 8);
      g += '<path d="' + smooth(bot) + '" class="c-faint"/><path d="' + smooth(dayPts(0, 160, 88, 8, 0.79)) + '" class="c-line c-thin"/>';
      var pts = '<ol class="c-pts" style="left:' + X(95) + ';top:' + Y(34) + '">' + POINTS5.map(function (p, i) { return '<li><b>' + (i + 1) + '</b>' + p + '</li>'; }).join('') + '</ol>';
      return '<div class="ms-in">' + svg(g) + cKick('s5', 'Context caching') + cHead('s5', st) + '<div data-part="body">' + labs + pts + '</div></div>';
    },
    s6: function (st) {
      var pts = [[12, 80], [35, 78], [58, 70], [81, 64], [104, 57], [127, 50], [150, 46]];
      var g = '<line x1="12" y1="80" x2="150" y2="80" class="c-axis"/>' +
        '<path d="' + smooth(pts) + ' L150 80 L12 80 Z" class="c-fill"/><path d="' + smooth(pts) + '" class="c-line"/>' +
        [58, 104].map(function (x) { return '<line x1="' + x + '" y1="80" x2="' + x + '" y2="82" class="c-axis"/>'; }).join('') +
        [[58, 70], [104, 57], [150, 46]].map(function (p) { return '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="1.3" class="c-dot"/>'; }).join('');
      var ends = [[58, 70], [104, 57], [150, 46]];
      var labs = PHASES.map(function (p, i) {
        var e = ends[i];
        return cLab(e[0] - 2.5, e[1] - 13, '<div class="c-fig6">' + p.save + '</div><div class="c-n">' + p.name + ' &middot; ' + p.when + '</div><div class="c-d">' + p.what + '</div>', 'c-blk6', 'right');
      }).join('') + cLab(12, 83, 'Q1 2027', 'c-ax') + cLab(104, 83, 'Q2 2027', 'c-ax') + cLab(150, 83, 'savings run rate', 'c-ax', 'right');
      return '<div class="ms-in">' + svg(g) + cKick('s6', 'The plan') + cHead('s6', st, st.s6Short ? '' : 'c-h6') + '<div data-part="body">' + labs + '</div></div>';
    },
    s7: function (st) {
      var curve = dayPts(0, 160, 88, 12);
      var g = '<path d="' + smooth(curve) + ' L160 90 L0 90 Z" class="c-fill"/><path d="' + smooth(curve) + '" class="c-line"/>';
      var cols = [11, 59, 107];
      var labs = FIGS7[st.lead].map(function (f, i) {
        return cLab(cols[i], 40, '<div class="c-fig7">' + f.fig + '</div><div class="c-d7">' + f.label + '</div>', 'c-blk7');
      }).join('');
      return '<div class="ms-in">' + svg(g) + cKick('s7', 'The case') + cHead('s7', st) + '<div data-part="body">' + labs + '</div></div>';
    },
    s8: function (st) {
      var xs = [14, 56, 98, 140];
      var g = '<line x1="0" y1="62" x2="160" y2="62" class="c-line c-thin"/>' +
        xs.map(function (x, i) { return '<circle cx="' + x + '" cy="62" r="' + (i === 0 ? 2.2 : 1.1) + '" class="' + (i === 0 ? 'c-dot' : 'c-dot2') + '"/>'; }).join('');
      var labs = cLab(11, 34, 'Approve a six-week pilot on 5% of assistant traffic, for <b>$85k</b>.', 'c-ask') +
        cLab(11, 66, '<div class="c-n">30 Nov</div><div class="c-d">Decision</div>', 'c-blk8') +
        STEPS8.map(function (s, i) { return cLab(xs[i + 1] - 3, 66, '<div class="c-n">' + s.when + '</div><div class="c-d">' + s.what + '</div>', 'c-blk8'); }).join('');
      return '<div class="ms-in">' + svg(g) + cKick('s8', 'The decision') + cHead('s8', st) + '<div data-part="body">' + labs + '</div></div>';
    }
  };

  var RENDER = { 'default': D, a: A, b: B, c: Cd };

  /* ------------------------------------------------------------------ */
  /* CSS                                                                 */
  /* ------------------------------------------------------------------ */

  var MONO = '"IBM Plex Mono","JetBrains Mono","SF Mono",Menlo,Consolas,"DejaVu Sans Mono",monospace';
  var COND = 'Archivo,"Arial Narrow","Roboto Condensed","Helvetica Neue",Inter,Arial,sans-serif';
  var SANS = 'Archivo,"Helvetica Neue",Inter,"Segoe UI",Arial,sans-serif';
  var SERIF = 'Fraunces,Georgia,"Iowan Old Style","DejaVu Serif","Times New Roman",serif';

  var css = [
    /* base */
    '.ms-slide{display:block;position:relative;aspect-ratio:16/9;width:100%;container-type:inline-size;overflow:hidden;box-sizing:border-box;line-height:1.25;text-align:left;font-size:1.6cqw;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}',
    '.ms-slide *,.ms-slide *::before,.ms-slide *::after{box-sizing:border-box;margin:0;padding:0}',
    '.ms-slide ol,.ms-slide ul{list-style:none}',
    '.ms-slide b{font-weight:inherit}',
    '.ms-slide em{font-style:normal}',
    '.ms-slide h2,.ms-slide h3{font-weight:inherit;font-size:inherit}',
    '.ms-slide .ms-in{position:absolute;inset:0;overflow:hidden}',
    '.ms-slide svg{display:block}',

    /* ---------- default ---------- */
    '.ms-slide.ms-dir-default .ms-in{background:#fff;color:#1f2937;font-family:Calibri,Carlito,Arial,Helvetica,"Liberation Sans",sans-serif;padding:4.2cqw 5.5cqw 0}',
    '.ms-slide.ms-dir-default .d-h{font-size:3.3cqw;font-weight:700;line-height:1.15;color:#111827;max-width:82cqw}',
    '.ms-slide.ms-dir-default .d-bar{width:8cqw;height:.5cqw;background:#2563eb;margin-top:1.3cqw}',
    '.ms-slide.ms-dir-default .d-body{position:absolute;left:5.5cqw;right:5.5cqw;top:17.5cqw;bottom:6.5cqw}',
    '.ms-slide.ms-dir-default .d-foot{position:absolute;left:5.5cqw;right:5.5cqw;bottom:1.8cqw;display:flex;justify-content:space-between;font-size:1.05cqw;color:#6b7280;border-top:.1cqw solid #e5e7eb;padding-top:.8cqw}',
    '.ms-slide.ms-dir-default .d-ul li{position:relative;font-size:1.85cqw;line-height:1.35;padding-left:2.4cqw;margin-bottom:1.4cqw}',
    '.ms-slide.ms-dir-default .d-ul li::before{content:"";position:absolute;left:0;top:.75cqw;width:.8cqw;height:.8cqw;background:#2563eb}',
    '.ms-slide.ms-dir-default .d-ul.d-sm li{font-size:1.55cqw;margin-bottom:1cqw}',
    '.ms-slide.ms-dir-default .d-ul.d-sm li::before{top:.6cqw}',
    '.ms-slide.ms-dir-default .d-two{display:grid;grid-template-columns:1fr 1fr;gap:5cqw;height:100%}',
    '.ms-slide.ms-dir-default .d-chart{display:flex;flex-direction:column;min-height:0}',
    '.ms-slide.ms-dir-default .d-ctitle{font-size:1.4cqw;font-weight:700;color:#374151;margin-bottom:1.2cqw}',
    '.ms-slide.ms-dir-default .d-vbars{flex:1;display:flex;align-items:flex-end;gap:2.5cqw;border-bottom:.15cqw solid #9ca3af;padding:0 1cqw;min-height:0}',
    '.ms-slide.ms-dir-default .d-vb{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;position:relative}',
    '.ms-slide.ms-dir-default .d-vb em{position:absolute;bottom:-2.2cqw;left:0;right:0;text-align:center;font-size:1.2cqw;color:#4b5563}',
    '.ms-slide.ms-dir-default .d-vbf{background:#2563eb;position:relative}',
    '.ms-slide.ms-dir-default .d-vbf span{position:absolute;top:-2cqw;left:0;right:0;text-align:center;font-size:1.25cqw;font-weight:700}',
    '.ms-slide.ms-dir-default .d-stk{margin-bottom:2.4cqw}',
    '.ms-slide.ms-dir-default .d-col{height:88%;display:flex;flex-direction:column;width:60%;margin:0 auto}',
    '.ms-slide.ms-dir-default .d-c1,.ms-slide.ms-dir-default .d-c2{display:flex;align-items:center;justify-content:center;font-size:1.25cqw;font-weight:700;color:#fff}',
    '.ms-slide.ms-dir-default .d-c1{background:#2563eb}.ms-slide.ms-dir-default .d-c2{background:#9ca3af}',
    '.ms-slide.ms-dir-default .d-vbars:not(.d-stk){margin-bottom:2.4cqw}',
    '.ms-slide.ms-dir-default .d-leg{font-size:1.15cqw;color:#4b5563;display:flex;align-items:center;gap:.6cqw}',
    '.ms-slide.ms-dir-default .d-leg i{display:inline-block;width:1cqw;height:1cqw;background:#2563eb}',
    '.ms-slide.ms-dir-default .d-leg i.k2{background:#9ca3af;margin-left:1.2cqw}',
    '.ms-slide.ms-dir-default .d-three{display:grid;grid-template-columns:repeat(3,1fr);gap:3cqw}',
    '.ms-slide.ms-dir-default .d-c h3,.ms-slide.ms-dir-default .d-ph h3{font-size:1.9cqw;font-weight:700;margin:1.2cqw 0 .7cqw;color:#111827}',
    '.ms-slide.ms-dir-default .d-c p,.ms-slide.ms-dir-default .d-ph p{font-size:1.5cqw;line-height:1.35;color:#4b5563;margin-bottom:.5cqw}',
    '.ms-slide.ms-dir-default p.d-m{color:#2563eb;font-weight:700}',
    '.ms-slide.ms-dir-default .d-num,.ms-slide.ms-dir-default .d-dot{width:4cqw;height:4cqw;border-radius:50%;background:#2563eb;color:#fff;display:flex;align-items:center;justify-content:center;font-size:1.8cqw;font-weight:700}',
    '.ms-slide.ms-dir-default .d-hero{display:flex;align-items:center;gap:4cqw;margin-top:1cqw}',
    '.ms-slide.ms-dir-default .d-big{font-size:13cqw;font-weight:700;color:#2563eb;line-height:1}',
    '.ms-slide.ms-dir-default .d-bigt{font-size:2.4cqw;color:#374151;max-width:34cqw;line-height:1.3}',
    '.ms-slide.ms-dir-default .d-fn{position:absolute;left:0;bottom:0;font-size:1.2cqw;color:#6b7280}',
    '.ms-slide.ms-dir-default .d-hb{display:flex;align-items:center;gap:1.2cqw;margin:1.6cqw 0 2.2cqw}',
    '.ms-slide.ms-dir-default .d-hb em{width:6cqw;font-size:1.4cqw;color:#374151}',
    '.ms-slide.ms-dir-default .d-hb span{width:6cqw;font-size:1.5cqw;font-weight:700}',
    '.ms-slide.ms-dir-default .d-hbt{flex:1;height:4.2cqw}',
    '.ms-slide.ms-dir-default .d-hbf{height:100%;background:#2563eb}.ms-slide.ms-dir-default .d-hbf.k2{background:#9ca3af}',
    '.ms-slide.ms-dir-default .d-dense{grid-template-columns:1.05fr 1fr;gap:3.5cqw}',
    '.ms-slide.ms-dir-default .d-req{display:flex;height:5cqw;margin-top:1cqw}',
    '.ms-slide.ms-dir-default .d-req div{display:flex;align-items:center;justify-content:center;color:#fff;font-size:1.2cqw;font-weight:700;border-right:.2cqw solid #fff;background:#2563eb}',
    '.ms-slide.ms-dir-default .d-req div.k2{background:#9ca3af}',
    '.ms-slide.ms-dir-default .d-reql{display:flex;font-size:1.05cqw;color:#4b5563;margin:.7cqw 0 2cqw}',
    '.ms-slide.ms-dir-default .d-reql span{text-align:center;overflow:hidden;white-space:nowrap}',
    '.ms-slide.ms-dir-default .d-tl{position:relative;display:grid;grid-template-columns:repeat(3,1fr);gap:3cqw;padding-top:1cqw}',
    '.ms-slide.ms-dir-default .d-line{position:absolute;left:2cqw;right:2cqw;top:2.9cqw;height:.3cqw;background:#bfdbfe}',
    '.ms-slide.ms-dir-default .d-dot{position:relative}',
    '.ms-slide.ms-dir-default .d-kpi{background:#f3f4f6;padding:3cqw 2.5cqw;margin-top:2cqw}',
    '.ms-slide.ms-dir-default .d-kv{font-size:5.4cqw;font-weight:700;color:#2563eb;line-height:1}',
    '.ms-slide.ms-dir-default .d-kpi p{font-size:1.7cqw;color:#374151;margin-top:1.2cqw}',
    '.ms-slide.ms-dir-default .d-ask{border-left:.6cqw solid #2563eb;background:#eff6ff;padding:2.4cqw 2.6cqw;align-self:start}',
    '.ms-slide.ms-dir-default .d-ask h3,.ms-slide.ms-dir-default .d-h3{font-size:2cqw;font-weight:700;margin-bottom:1.2cqw;color:#111827}',
    '.ms-slide.ms-dir-default .d-ask p{font-size:1.8cqw;line-height:1.35;margin-bottom:.8cqw}',
    '.ms-slide.ms-dir-default .d-title{padding:0}',
    '.ms-slide.ms-dir-default .d-kick{position:absolute;left:7cqw;top:9cqw;font-size:1.3cqw;font-weight:700;letter-spacing:.15em;color:#2563eb}',
    '.ms-slide.ms-dir-default .d-th{position:absolute;left:7cqw;top:12.5cqw;width:72cqw;font-size:4.3cqw;font-weight:700;line-height:1.15;color:#111827}',
    '.ms-slide.ms-dir-default .d-sub{position:absolute;left:7cqw;top:27.5cqw;font-size:2.1cqw;color:#374151;line-height:1.5}',
    '.ms-slide.ms-dir-default .d-sub span{font-size:1.6cqw;color:#6b7280}',
    '.ms-slide.ms-dir-default .d-band{position:absolute;left:0;right:0;bottom:0;height:8cqw;background:#1e40af;border-top:1cqw solid #60a5fa;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 7cqw;font-size:1.4cqw}',

    /* ---------- a: Itemised ---------- */
    '.ms-slide.ms-dir-a .ms-in{background:#d3dccf;color:#20252b;font-family:' + MONO + '}',
    '.ms-slide.ms-dir-a .a-rcw{position:absolute;left:6cqw;top:0;width:37cqw;filter:drop-shadow(0 .35cqw .5cqw rgba(40,55,45,.18))}',
        '.ms-slide.ms-dir-a .a-rc{background:#fcfcf9;padding:3.6cqw 3cqw 3.6cqw;clip-path:' + ZIG + ';font-size:1.4cqw;line-height:1.6}',
        '.ms-slide.ms-dir-a .a-shop{text-align:center;font-weight:600;letter-spacing:.14em;font-size:1.3cqw}',
    '.ms-slide.ms-dir-a .a-meta{text-align:center;color:#7a827c;font-size:1cqw;letter-spacing:.04em;line-height:1.5}',
    '.ms-slide.ms-dir-a .a-sep{border-top:.18cqw dashed #a9b0aa;margin:1.1cqw 0}',
    '.ms-slide.ms-dir-a .a-li{display:flex;align-items:baseline;gap:.6cqw;white-space:nowrap}',
    '.ms-slide.ms-dir-a .a-li .dots{flex:1;min-width:1cqw;border-bottom:.2cqw dotted #b3bab4}',
    '.ms-slide.ms-dir-a .a-li .v{font-weight:500}',
    '.ms-slide.ms-dir-a .a-li.a-em .l,.ms-slide.ms-dir-a .a-li.a-em .v{font-weight:600}',
    '.ms-slide.ms-dir-a .a-tot{font-size:1.9cqw;font-weight:600;letter-spacing:-.01em}',
    '.ms-slide.ms-dir-a .a-tot .l{font-size:1.3cqw;letter-spacing:.08em}',
    '.ms-slide.ms-dir-a .a-hl{background:linear-gradient(transparent 48%,#f1e05a 48%,#f1e05a 92%,transparent 92%);padding:0 .3cqw;font-weight:600}',
    '.ms-slide.ms-dir-a .a-bar{height:1.1cqw;margin:.2cqw 0 .7cqw}',
    '.ms-slide.ms-dir-a .a-bar i{display:block;height:100%;background:repeating-linear-gradient(90deg,#9aa39c 0 .3cqw,transparent .3cqw .45cqw)}',
    '.ms-slide.ms-dir-a .a-bar-hl i{background:repeating-linear-gradient(90deg,#3446c9 0 .3cqw,transparent .3cqw .45cqw)}',
    '.ms-slide.ms-dir-a .a-bar-tall{height:2.6cqw;margin:.4cqw 0 1.2cqw}',
    '.ms-slide.ms-dir-a .a-yr{font-size:1.05cqw;letter-spacing:.14em;color:#3446c9;font-weight:600;margin:.5cqw 0 .1cqw}',
    '.ms-slide.ms-dir-a .a-cut{text-align:center;color:#3446c9;font-size:1.05cqw;letter-spacing:.1em;margin:.2cqw 0}',
    '.ms-slide.ms-dir-a .a-item{margin-bottom:1cqw}',
    '.ms-slide.ms-dir-a .a-sub{color:#6c746e;font-size:1.1cqw;padding-left:2.2cqw}',
    '.ms-slide.ms-dir-a .a-req{display:flex;height:2.6cqw;gap:.25cqw;margin:.4cqw 0 .4cqw}',
    '.ms-slide.ms-dir-a .a-req i{display:block;background:repeating-linear-gradient(90deg,#9aa39c 0 .3cqw,transparent .3cqw .45cqw)}',
    '.ms-slide.ms-dir-a .a-req i.c{background:repeating-linear-gradient(90deg,#3446c9 0 .3cqw,transparent .3cqw .45cqw)}',
    '.ms-slide.ms-dir-a .a-brace{display:flex;font-size:1cqw;color:#3446c9;margin-bottom:.8cqw}',
    '.ms-slide.ms-dir-a .a-brace span{border-top:.18cqw solid currentColor;padding-top:.2cqw;text-align:center;white-space:nowrap}',
    '.ms-slide.ms-dir-a .a-brace span+span{color:#7a827c;margin-left:.6cqw}',
    '.ms-slide.ms-dir-a .a-sign{margin-top:2.6cqw;font-size:1cqw;color:#7a827c;text-align:center}',
    '.ms-slide.ms-dir-a .a-sign span{display:block;border-bottom:.18cqw solid #20252b;height:3cqw;margin:0 1.5cqw .6cqw}',
    '.ms-slide.ms-dir-a .a-side{position:absolute;left:49cqw;right:5.5cqw;top:5.4cqw;bottom:4.2cqw;display:flex;flex-direction:column}',
    '.ms-slide.ms-dir-a .a-k{font-size:1.05cqw;letter-spacing:.16em;color:#5d6a61;text-transform:uppercase;margin-bottom:1.8cqw;white-space:nowrap}',
    '.ms-slide.ms-dir-a .a-h{font-size:3.3cqw;font-weight:600;line-height:1.17;letter-spacing:-.045em;color:#1b2026}',
    '.ms-slide.ms-dir-a .a-h1{font-size:3.9cqw}',
    '.ms-slide.ms-dir-a .a-hsm,.ms-slide.ms-dir-a .a-hs{font-size:2.9cqw}',
    '.ms-slide.ms-dir-a .a-note{margin-top:auto;font-size:1.35cqw;line-height:1.55;color:#48524b;max-width:40cqw}',
    '.ms-slide.ms-dir-a .a-note b{font-weight:600;color:#20252b}',
    '.ms-slide.ms-dir-a .a-hero{font-size:13.5cqw;font-weight:500;letter-spacing:-.08em;line-height:1;color:#3446c9;margin-top:auto}',
    '.ms-slide.ms-dir-a .a-hero+.a-note{margin-top:1.4cqw}',
    '.ms-slide.ms-dir-a .a-list{margin-top:auto;font-size:1.3cqw;line-height:1.5;color:#3a433d}',
    '.ms-slide.ms-dir-a .a-list li{display:flex;gap:1.2cqw;padding:.9cqw 0;border-top:.15cqw solid #bcc5bc}',
    '.ms-slide.ms-dir-a .a-list li span{color:#3446c9;font-weight:600}',
    '.ms-slide.ms-dir-a .a-list-sm{font-size:1.2cqw;line-height:1.45}',
    '.ms-slide.ms-dir-a .a-list-sm li{padding:.7cqw 0}',
    '.ms-slide.ms-dir-a .a-steps{margin-top:auto;height:19cqw;display:flex;align-items:flex-end;gap:.8cqw;border-bottom:.2cqw solid #20252b}',
    '.ms-slide.ms-dir-a .a-step{flex:1;background:repeating-linear-gradient(90deg,#b6c0b7 0 .3cqw,transparent .3cqw .45cqw);display:flex;flex-direction:column;justify-content:flex-start;padding:.8cqw 0 0 .8cqw}',
    '.ms-slide.ms-dir-a .a-step:last-child{background:repeating-linear-gradient(90deg,#3446c9 0 .3cqw,transparent .3cqw .45cqw)}',
    '.ms-slide.ms-dir-a .a-step b{font-size:2.6cqw;font-weight:600;letter-spacing:-.05em;line-height:1;background:#d3dccf;align-self:flex-start;padding:0 .4cqw .3cqw 0}',
    '.ms-slide.ms-dir-a .a-step span{font-size:1.05cqw;letter-spacing:.1em;text-transform:uppercase;background:#d3dccf;align-self:flex-start;padding-right:.4cqw}',
    '.ms-slide.ms-dir-a .a-figs{margin-top:auto;display:grid;grid-template-columns:repeat(3,1fr);gap:1.6cqw}',
    '.ms-slide.ms-dir-a .a-figs div{border-top:.25cqw solid #20252b;padding-top:1cqw}',
    '.ms-slide.ms-dir-a .a-figs b{display:block;font-size:3.2cqw;font-weight:600;letter-spacing:-.06em;line-height:1.1;white-space:nowrap}',
    '.ms-slide.ms-dir-a .a-figs div:nth-child(2) b{color:#3446c9}',
    '.ms-slide.ms-dir-a .a-figs span{display:block;font-size:1.1cqw;line-height:1.4;color:#48524b;margin-top:.6cqw}',
    '.ms-slide.ms-dir-a .a-next{margin-top:auto}',
    '.ms-slide.ms-dir-a .a-next div{display:flex;gap:1.6cqw;font-size:1.35cqw;padding:1cqw 0;border-top:.15cqw solid #bcc5bc}',
    '.ms-slide.ms-dir-a .a-next b{color:#3446c9;font-weight:600;width:6.5cqw;flex:none}',

    /* ---------- b: Shelf price ---------- */
    '.ms-slide.ms-dir-b .ms-in{background:#0e5a43;color:#fff;font-family:' + SANS + '}',
    '.ms-slide.ms-dir-b .b-h{position:absolute;left:5cqw;top:4.6cqw;width:55cqw;font-family:' + COND + ';font-stretch:62%;font-weight:800;font-size:4.6cqw;line-height:1;letter-spacing:-.005em}',
    '.ms-slide.ms-dir-b .b-h1{font-size:6.2cqw;width:56cqw;line-height:.96}',
    '.ms-slide.ms-dir-b .b-hw{width:84cqw}',
    '.ms-slide.ms-dir-b .b-hn{width:46cqw}',
    '.ms-slide.ms-dir-b .b-h6{width:60cqw;font-size:4.2cqw}',
    '.ms-slide.ms-dir-b .b-tag{background:#ffd43b;color:#10241b;position:relative;padding:2.2cqw 2.4cqw 2cqw;border-radius:.5cqw .5cqw .5cqw 2.4cqw}',
    '.ms-slide.ms-dir-b .b-tag::before{content:"";position:absolute;top:1.5cqw;right:1.5cqw;width:1.3cqw;height:1.3cqw;border-radius:50%;background:#0e5a43}',
    '.ms-slide.ms-dir-b .b-tag-r{position:absolute;right:5cqw;top:4.6cqw;min-width:27cqw;max-width:37cqw}',
    '.ms-slide.ms-dir-b .b-tl{font-size:1.1cqw;font-weight:700;letter-spacing:.14em;text-transform:uppercase;padding-right:2cqw;white-space:nowrap}',
    '.ms-slide.ms-dir-b .b-was{font-size:1.5cqw;font-weight:600;margin-top:1cqw;text-decoration:line-through;text-decoration-color:#d9363e;text-decoration-thickness:.28cqw}',
    '.ms-slide.ms-dir-b .b-big{font-family:' + COND + ';font-stretch:62%;font-weight:800;font-size:9.6cqw;line-height:.9;letter-spacing:-.02em;margin:.4cqw 0 .8cqw;white-space:nowrap}',
    '.ms-slide.ms-dir-b .b-big small{font-size:.45em;margin-left:.15em}',
    '.ms-slide.ms-dir-b .b-mid{font-family:' + COND + ';font-stretch:62%;font-weight:800;font-size:6.4cqw;line-height:.95;letter-spacing:-.02em;margin:.8cqw 0 .8cqw;white-space:nowrap}',
    '.ms-slide.ms-dir-b .b-tf{font-size:1.2cqw;line-height:1.35}',
    '.ms-slide.ms-dir-b .b-tf b{font-weight:700}',
    '.ms-slide.ms-dir-b .b-meta{position:absolute;left:5cqw;bottom:8.6cqw;font-size:1.5cqw;line-height:1.45;color:#a9dcc6}',
    '.ms-slide.ms-dir-b .b-shelf{position:absolute;left:0;right:0;bottom:0;height:5cqw;background:#09412f;border-top:.4cqw solid #ffd43b;display:flex;align-items:center;gap:2cqw;padding:0 5cqw;font-size:1cqw;letter-spacing:.12em;text-transform:uppercase;color:#a9dcc6;white-space:nowrap}',
    '.ms-slide.ms-dir-b .b-shelf .b-fine{letter-spacing:.04em;text-transform:none;color:#7fbfa4;overflow:hidden;text-overflow:ellipsis}',
    '.ms-slide.ms-dir-b .b-shelf .b-pg{margin-left:auto;font-weight:700;color:#fff}',
    '.ms-slide.ms-dir-b .b-bc{flex:none;width:6cqw;height:2.2cqw;background:repeating-linear-gradient(90deg,#d6efe3 0 .16cqw,transparent .16cqw .32cqw,#d6efe3 .32cqw .7cqw,transparent .7cqw .86cqw,#d6efe3 .86cqw .96cqw,transparent .96cqw 1.3cqw)}',
    /* b charts */
    '.ms-slide.ms-dir-b .b-rows{position:absolute;left:5cqw;right:5cqw;bottom:9cqw}',
    '.ms-slide.ms-dir-b .b-row{display:flex;align-items:center;gap:1.6cqw;margin-top:1.4cqw}',
    '.ms-slide.ms-dir-b .b-yr{font-family:' + COND + ';font-stretch:62%;font-weight:800;font-size:2.6cqw;width:5.5cqw}',
    '.ms-slide.ms-dir-b .b-track{flex:1;display:flex;height:5cqw;gap:.4cqw}',
    '.ms-slide.ms-dir-b .b-tr,.ms-slide.ms-dir-b .b-inf{display:flex;align-items:center;padding:0 1.2cqw;font-size:1.3cqw;font-weight:700;white-space:nowrap;overflow:hidden}',
    '.ms-slide.ms-dir-b .b-tr{border:.25cqw solid #6fbf9c;color:#cfeee0}',
    '.ms-slide.ms-dir-b .b-inf{background:#ffd43b;color:#10241b}',
    '.ms-slide.ms-dir-b .b-vbars{position:absolute;left:5cqw;width:55cqw;bottom:11.2cqw;height:20cqw;display:flex;align-items:flex-end;gap:1.6cqw;border-bottom:.25cqw solid #cfeee0}',
    '.ms-slide.ms-dir-b .b-vb{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;position:relative}',
    '.ms-slide.ms-dir-b .b-vb>span{position:absolute;left:0;right:0;bottom:-2.4cqw;font-size:1.15cqw;color:#a9dcc6;text-align:center}',
    '.ms-slide.ms-dir-b .b-vbf{background:#2f7c62;position:relative}',
    '.ms-slide.ms-dir-b .b-vbf.hot{background:#ffd43b}',
    '.ms-slide.ms-dir-b .b-vbf b{position:absolute;top:-3cqw;left:0;right:0;text-align:center;font-family:' + COND + ';font-stretch:62%;font-weight:800;font-size:2.4cqw}',
    '.ms-slide.ms-dir-b .b-lim{position:absolute;left:50%;top:-1cqw;bottom:0;border-left:.25cqw dashed #fff;z-index:1}',
    '.ms-slide.ms-dir-b .b-lim span{position:absolute;left:.6cqw;top:-.4cqw;font-size:1.1cqw;font-weight:700;white-space:nowrap}',
    '.ms-slide.ms-dir-b .b-rail{position:absolute;left:5cqw;right:5cqw;bottom:8.4cqw;display:grid;grid-template-columns:repeat(3,1fr);gap:2.4cqw;align-items:end}',
    '.ms-slide.ms-dir-b .b-tag-s{padding:2cqw 2.2cqw 2cqw}',
    '.ms-slide.ms-dir-b .b-rail .b-tag-s:not(.b-lead),.ms-slide.ms-dir-b .b-stairs .b-tag-s:not(.b-lead){background:#e9f6ef}',
    '.ms-slide.ms-dir-b .b-rail7 .b-tag-s{min-height:15cqw}',
    '.ms-slide.ms-dir-b .b-rail7 .b-lead{min-height:19cqw}',
    '.ms-slide.ms-dir-b .b-rail7 .b-mid{font-size:7.4cqw;margin-top:0}',
    '.ms-slide.ms-dir-b .b-hbars{position:absolute;left:5cqw;width:56cqw;bottom:9.4cqw}',
    '.ms-slide.ms-dir-b .b-hb{display:flex;align-items:center;gap:1.4cqw;margin-top:1.4cqw}',
    '.ms-slide.ms-dir-b .b-hb>span{width:6cqw;font-size:1.3cqw;font-weight:700;color:#a9dcc6;text-transform:uppercase;letter-spacing:.08em}',
    '.ms-slide.ms-dir-b .b-hbt{flex:1;height:4.4cqw;position:relative;display:flex;align-items:center}',
    '.ms-slide.ms-dir-b .b-hbf{height:100%;background:#ffd43b}',
    '.ms-slide.ms-dir-b .b-hbf.old{background:transparent;border:.25cqw solid #6fbf9c}',
    '.ms-slide.ms-dir-b .b-hbt em{margin-left:1cqw;font-family:' + COND + ';font-stretch:62%;font-weight:800;font-size:2.6cqw;color:#ffd43b}',
    '.ms-slide.ms-dir-b .b-hb>b{width:7cqw;font-family:' + COND + ';font-stretch:62%;font-weight:800;font-size:2.8cqw}',
    '.ms-slide.ms-dir-b .b-hb>b.strike{text-decoration:line-through;text-decoration-color:#ff6b6b;text-decoration-thickness:.3cqw;color:#a9dcc6}',
    '.ms-slide.ms-dir-b .b-hero{position:absolute;right:4cqw;bottom:2.6cqw;font-family:' + COND + ';font-stretch:62%;font-weight:900;font-size:40cqw;line-height:.8;letter-spacing:-.04em;color:#ffd43b;white-space:nowrap}',
    '.ms-slide.ms-dir-b .b-hero small{font-size:.42em;letter-spacing:0}',
    '.ms-slide.ms-dir-b .b-herot{position:absolute;left:5cqw;bottom:9cqw;font-size:2cqw;line-height:1.3;font-weight:600;color:#cfeee0}',
    '.ms-slide.ms-dir-b .b-diag{position:absolute;left:5cqw;width:44cqw;bottom:9.4cqw}',
    '.ms-slide.ms-dir-b .b-dl{font-size:1.1cqw;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#a9dcc6;margin-bottom:1cqw}',
    '.ms-slide.ms-dir-b .b-req{display:flex;height:9cqw;gap:.3cqw}',
    '.ms-slide.ms-dir-b .b-req div{background:#2f7c62;padding:.8cqw;display:flex;flex-direction:column;justify-content:space-between;overflow:hidden;min-width:0}',
    '.ms-slide.ms-dir-b .b-req div.c{background:#ffd43b;color:#10241b}',
    '.ms-slide.ms-dir-b .b-req b{font-family:' + COND + ';font-stretch:62%;font-weight:800;font-size:2.1cqw;line-height:1}',
    '.ms-slide.ms-dir-b .b-req span{font-size:1cqw;font-weight:600;white-space:nowrap}',
    '.ms-slide.ms-dir-b .b-brk span{display:block;margin-top:.8cqw;border-top:.25cqw solid #ffd43b;padding-top:.5cqw;font-size:1.1cqw;color:#ffd43b;font-weight:600;white-space:nowrap}',
    '.ms-slide.ms-dir-b .b-pts{position:absolute;left:53cqw;right:5cqw;bottom:9.4cqw;display:grid;grid-template-columns:1fr 1fr;gap:1.6cqw 2.2cqw}',
    '.ms-slide.ms-dir-b .b-pts li{font-size:1.25cqw;line-height:1.38;color:#e6f5ee;border-top:.25cqw solid #6fbf9c;padding-top:.8cqw}',
    '.ms-slide.ms-dir-b .b-pts b{display:block;font-family:' + COND + ';font-stretch:62%;font-weight:800;font-size:2cqw;color:#ffd43b;line-height:1;margin-bottom:.4cqw}',
    '.ms-slide.ms-dir-b .b-stairs{position:absolute;left:5cqw;right:5cqw;bottom:8.4cqw;height:30cqw;display:grid;grid-template-columns:repeat(3,1fr);gap:2.4cqw;align-items:end}',
    '.ms-slide.ms-dir-b .b-hn~.b-stairs{height:33cqw}',
    '.ms-slide.ms-dir-b .b-st{display:flex;flex-direction:column;justify-content:flex-start;border-left:.25cqw solid #6fbf9c}',
    '.ms-slide.ms-dir-b .b-st .b-tag{margin-left:-.25cqw}',
    '.ms-slide.ms-dir-b .b-tag-ask{position:absolute;left:5cqw;bottom:8.4cqw;width:36cqw}',
    '.ms-slide.ms-dir-b .b-tag-ask .b-mid{font-size:10cqw}',
    '.ms-slide.ms-dir-b .b-tag-ask .b-tf{font-size:1.5cqw}',
    '.ms-slide.ms-dir-b .b-next{position:absolute;left:47cqw;right:5cqw;bottom:8.6cqw}',
    '.ms-slide.ms-dir-b .b-next>div:not(.b-dl){display:flex;align-items:baseline;gap:2cqw;border-top:.25cqw solid #6fbf9c;padding:1.2cqw 0}',
    '.ms-slide.ms-dir-b .b-next b{font-family:' + COND + ';font-stretch:62%;font-weight:800;font-size:2.6cqw;color:#ffd43b;min-width:8cqw;flex:none;white-space:nowrap}',
    '.ms-slide.ms-dir-b .b-next span{font-size:1.5cqw}',

    /* ---------- c: Demand curve ---------- */
    '.ms-slide.ms-dir-c .ms-in{background:#0f1d30;color:#eaf0f7;font-family:' + SANS + '}',
    '.ms-slide.ms-dir-c .c-svg{position:absolute;inset:0;width:100%;height:100%}',
    '.ms-slide.ms-dir-c .c-line{fill:none;stroke:#f2a57e;stroke-width:.5;stroke-linecap:round}',
    '.ms-slide.ms-dir-c .c-thin{stroke-width:.3}',
    '.ms-slide.ms-dir-c .c-line2{fill:none;stroke:#7fa6d8;stroke-width:.35;stroke-dasharray:1.2 1}',
    '.ms-slide.ms-dir-c .c-faint{fill:none;stroke:#3a5272;stroke-width:.3}',
    '.ms-slide.ms-dir-c .c-fill{fill:#14273f}',
    '.ms-slide.ms-dir-c .c-band{fill:#15283f;stroke:#2c4361;stroke-width:.2}',
    '.ms-slide.ms-dir-c .c-area{fill:#f2a57e;opacity:.92}',
    '.ms-slide.ms-dir-c .c-axis{stroke:#3a5272;stroke-width:.25}',
    '.ms-slide.ms-dir-c .c-gap{stroke:#eaf0f7;stroke-width:.25;stroke-dasharray:.6 .6}',
    '.ms-slide.ms-dir-c .c-dot{fill:#f2a57e;stroke:#0f1d30;stroke-width:.5}',
    '.ms-slide.ms-dir-c .c-dot2{fill:#0f1d30;stroke:#eaf0f7;stroke-width:.35}',
    '.ms-slide.ms-dir-c .c-bar1{stroke:#7fa6d8;stroke-width:3}',
    '.ms-slide.ms-dir-c .c-bar2{stroke:#f2a57e;stroke-width:3}',
    '.ms-slide.ms-dir-c .c-ghost{stroke:#2c4361;stroke-width:3;stroke-dasharray:.6 .6}',
    '.ms-slide.ms-dir-c .c-seg1{fill:#f2a57e}.ms-slide.ms-dir-c .c-seg2{fill:#2f4a6c}',
    '.ms-slide.ms-dir-c .c-brk{fill:none;stroke:#f2a57e;stroke-width:.3}',
    '.ms-slide.ms-dir-c .c-k{position:absolute;left:7cqw;top:5cqw;font-size:1.05cqw;letter-spacing:.2em;text-transform:uppercase;color:#8597b3;font-weight:600;white-space:nowrap}',
    '.ms-slide.ms-dir-c .c-h{position:absolute;left:7cqw;top:8.2cqw;width:60cqw;font-family:' + SERIF + ';font-weight:300;font-size:3.9cqw;line-height:1.12;letter-spacing:-.012em;font-variation-settings:"opsz" 72}',
    '.ms-slide.ms-dir-c .c-h em{font-style:italic;color:#f2a57e}',
    '.ms-slide.ms-dir-c .c-h1{font-size:4.9cqw;width:66cqw;top:9cqw}',
    '.ms-slide.ms-dir-c .c-h6{font-size:3.4cqw;width:60cqw}',
    '.ms-slide.ms-dir-c .c-hs{font-size:3cqw;width:56cqw}',
    '.ms-slide.ms-dir-c .c-l{position:absolute;font-size:1.15cqw;line-height:1.35;color:#a8b8cf;white-space:nowrap}',
    '.ms-slide.ms-dir-c .c-ann{font-size:1.35cqw;color:#eaf0f7}',
    '.ms-slide.ms-dir-c .c-ann b{font-family:' + SERIF + ';font-weight:400;font-style:italic;font-size:2.3cqw;color:#f2a57e}',
    '.ms-slide.ms-dir-c .c-ann2{font-size:1.25cqw;color:#eaf0f7}',
    '.ms-slide.ms-dir-c .c-ann3{font-size:1.1cqw;color:#f2a57e;letter-spacing:.04em}',
    '.ms-slide.ms-dir-c .c-meta{font-size:1.15cqw;color:#8597b3;letter-spacing:.03em}',
    '.ms-slide.ms-dir-c .c-ax{font-size:1.05cqw;color:#8597b3;letter-spacing:.08em;text-transform:uppercase}',
    '.ms-slide.ms-dir-c .c-in{color:#a8b8cf}',
    '.ms-slide.ms-dir-c .c-dark{color:#0f1d30;font-weight:700}',
    '.ms-slide.ms-dir-c .c-v{font-family:' + SERIF + ';font-size:2.2cqw;font-weight:400;color:#eaf0f7}',
    '.ms-slide.ms-dir-c .c-blk,.ms-slide.ms-dir-c .c-blk6,.ms-slide.ms-dir-c .c-blk7,.ms-slide.ms-dir-c .c-blk8{white-space:normal}',
    '.ms-slide.ms-dir-c .c-blk{width:26cqw}',
    '.ms-slide.ms-dir-c .c-fig3{font-family:' + SERIF + ';font-weight:300;font-size:3.2cqw;line-height:1.1;color:#f2a57e;white-space:nowrap}',
    '.ms-slide.ms-dir-c .c-n{font-size:1.35cqw;font-weight:600;color:#eaf0f7;margin-top:.3cqw;white-space:nowrap}',
    '.ms-slide.ms-dir-c .c-d{font-size:1.15cqw;color:#a8b8cf;margin-top:.2cqw}',
    '.ms-slide.ms-dir-c .c-hero{position:absolute;left:6cqw;top:16cqw;font-family:' + SERIF + ';font-weight:300;font-size:26cqw;line-height:1;letter-spacing:-.04em;color:#f2a57e;font-variation-settings:"opsz" 144;white-space:nowrap}',
    '.ms-slide.ms-dir-c .c-fig4{font-family:' + SERIF + ';font-style:italic;font-size:2.6cqw;color:#f2a57e}',
    '.ms-slide.ms-dir-c .c-segl{font-size:1.05cqw;color:#eaf0f7;line-height:1.25}',
    '.ms-slide.ms-dir-c .c-segl span{color:#8597b3}',
    '.ms-slide.ms-dir-c .c-pts{position:absolute;right:6cqw;display:flex;flex-direction:column;gap:1.2cqw}',
    '.ms-slide.ms-dir-c .c-pts li{display:flex;gap:1.2cqw;font-size:1.25cqw;line-height:1.4;color:#d5dfec;border-top:.12cqw solid #2c4361;padding-top:1cqw}',
    '.ms-slide.ms-dir-c .c-pts b{font-family:' + SERIF + ';font-style:italic;color:#f2a57e;font-size:1.6cqw;line-height:1.1;flex:none;width:1.6cqw}',
    '.ms-slide.ms-dir-c .c-blk6{width:24cqw;text-align:right}',
    '.ms-slide.ms-dir-c .c-fig6{font-family:' + SERIF + ';font-weight:300;font-size:2.8cqw;line-height:1.05;color:#f2a57e}',
    '.ms-slide.ms-dir-c .c-blk7{width:27cqw;border-left:.12cqw solid #2c4361;padding-left:1.6cqw}',
    '.ms-slide.ms-dir-c .c-fig7{font-family:' + SERIF + ';font-weight:300;font-size:7cqw;line-height:1;letter-spacing:-.03em;color:#eaf0f7;white-space:nowrap}',
    '.ms-slide.ms-dir-c .c-blk7:nth-child(2) .c-fig7{color:#f2a57e}',
    '.ms-slide.ms-dir-c .c-d7{font-size:1.35cqw;color:#a8b8cf;margin-top:1cqw}',
    '.ms-slide.ms-dir-c .c-ask{font-family:' + SERIF + ';font-style:italic;font-weight:300;font-size:2.2cqw;color:#d5dfec;white-space:normal;width:70cqw;line-height:1.3}',
    '.ms-slide.ms-dir-c .c-ask b{color:#f2a57e;font-weight:400}',
    '.ms-slide.ms-dir-c .c-blk8{width:14cqw}',
    '.ms-slide.ms-dir-c .c-blk8 .c-n{font-family:' + SERIF + ';font-weight:400;font-size:1.9cqw;color:#f2a57e}'
  ].join('\n');

  /* ------------------------------------------------------------------ */
  /* Directions                                                          */
  /* ------------------------------------------------------------------ */

  var directions = [
    {
      id: 'default', name: 'Default', provisional: true,
      concept: 'No design decision was made: the stock layout every deck tool falls back to. Title top-left, a blue accent bar, bullets, a footer.',
      palette: [
        { name: 'White', hex: '#FFFFFF', role: 'Background' },
        { name: 'Ink', hex: '#111827', role: 'Titles and text' },
        { name: 'Template blue', hex: '#2563EB', role: 'Accent bar, bullets, charts' },
        { name: 'Grey', hex: '#9CA3AF', role: 'Secondary chart series' },
        { name: 'Pale blue', hex: '#EFF6FF', role: 'Callout boxes' }
      ],
      type: { display: 'Calibri / Arial Bold', body: 'Calibri / Arial' },
      rules: [
        'Every slide uses the same title-and-bullets layout.',
        'One blue accent bar under every title.',
        'Charts use the template blue and grey.',
        'Nothing is sized or placed for the argument.'
      ]
    },
    {
      id: 'a', name: 'Itemised', provisional: false,
      concept: 'Every slide is a till receipt for the claim it makes: the assistant\'s bill, itemised line by line, with the total circled in highlighter. The argument sits beside it on the counter.',
      palette: [
        { name: 'Counter sage', hex: '#D3DCCF', role: 'Ground' },
        { name: 'Receipt', hex: '#FCFCF9', role: 'The receipt paper' },
        { name: 'Print', hex: '#20252B', role: 'Text and printed bars' },
        { name: 'Carbon blue', hex: '#3446C9', role: 'The figure that matters' },
        { name: 'Highlighter', hex: '#F1E05A', role: 'The total, once per slide' }
      ],
      type: { display: 'IBM Plex Mono SemiBold', body: 'IBM Plex Mono' },
      rules: [
        'One monospace face; figures align like a till roll.',
        'The receipt holds the evidence, always on the left; the claim stands on the right.',
        'Charts are printed as dotted thermal bars, never smooth fills.',
        'Highlighter marks exactly one total per slide.',
        'No icons, no boxes, no photography.'
      ]
    },
    {
      id: 'b', name: 'Shelf price', provisional: false,
      concept: 'Each slide states its number the way a supermarket shelf states a price: one condensed figure on a yellow ticket, the old value struck through, the reasoning in small print on the shelf edge.',
      palette: [
        { name: 'Aisle green', hex: '#0E5A43', role: 'Ground' },
        { name: 'Ticket yellow', hex: '#FFD43B', role: 'The price ticket and the key series' },
        { name: 'Ticket ink', hex: '#10241B', role: 'Text on tickets' },
        { name: 'Shelf mint', hex: '#A9DCC6', role: 'Labels and small print' },
        { name: 'Markdown red', hex: '#D9363E', role: 'Strike-through on old values only' }
      ],
      type: { display: 'Archivo Condensed ExtraBold', body: 'Archivo' },
      rules: [
        'One yellow ticket per slide carries the number; everything else is quieter.',
        'Old values are struck through in red, never deleted.',
        'Headers are condensed and set large, top left, in two or three lines.',
        'A shelf edge runs along the foot of every slide with the fine print.',
        'Red is only ever a strike-through.'
      ]
    },
    {
      id: 'c', name: 'Demand curve', provisional: false,
      concept: 'One line runs through every slide: the assistant\'s traffic over a day, which is what the bill follows. Charts, timelines and figures hang off that line in calm, open space.',
      palette: [
        { name: 'Night', hex: '#0F1D30', role: 'Ground' },
        { name: 'Curve', hex: '#F2A57E', role: 'The line and the figure that matters' },
        { name: 'Paper', hex: '#EAF0F7', role: 'Headers and figures' },
        { name: 'Mist', hex: '#A8B8CF', role: 'Labels and body' },
        { name: 'Before', hex: '#7FA6D8', role: 'The old state in comparisons' }
      ],
      type: { display: 'Fraunces Light, italic for emphasis', body: 'Archivo' },
      rules: [
        'Every slide has exactly one continuous line, and it carries the data.',
        'The header is a light serif; its key phrase turns italic and coloured.',
        'Content is left-aligned and hangs off the line; at least a third of the slide stays empty.',
        'Peach marks the one thing to look at; everything else is in cool greys.'
      ]
    }
  ];

  /* ------------------------------------------------------------------ */
  /* Public API                                                          */
  /* ------------------------------------------------------------------ */

  function headers(state) {
    var st = norm(state);
    return IDS.map(function (id, i) {
      return { id: id, n: i + 1, header: headerText(id, st), intent: intentText(id, st) };
    });
  }

  function render(slideId, directionId, state) {
    var st = norm(state);
    var dir = RENDER[directionId] ? directionId : 'default';
    var id = IDS.indexOf(slideId) >= 0 ? slideId : 's1';
    var label = 'Slide ' + id.slice(1) + ': ' + headerText(id, st);
    return '<div class="ms-slide ms-dir-' + dir + ' ms-' + id + '" data-slide="' + id + '" data-direction="' + dir + '" aria-label="' + label.replace(/"/g, '&quot;') + '">' + RENDER[dir][id](st) + '</div>';
  }

  function renderSample(directionId) {
    var st = { lead: 'cost', s4Hero: false, s6Short: false };
    return [render('s1', directionId, st), render('s3', directionId, st), render('s4', directionId, st)];
  }

  window.MockSlides = {
    css: css,
    directions: directions,
    slideIds: IDS.slice(),
    headers: headers,
    render: render,
    renderSample: renderSample
  };
})();
