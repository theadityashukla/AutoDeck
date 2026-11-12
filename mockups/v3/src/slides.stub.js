/* FONT_LINKS
*/
/* Minimal stand-in for slides.js. Same window.MockSlides interface, simple slides. */
window.MockSlides = (function () {
  var ids = ['s1', 's2', 's3', 's4', 's5', 's6', 's7', 's8'];
  var H = {
    s1: ['Northwind can serve its shopping assistant at 38% lower cost', 'Northwind\'s shopping assistant can answer in under a second', 'Open with the claim'],
    s2: ['Inference, not training, is now most of the bill', 'Shoppers leave when an answer takes more than two seconds', 'Show where the money goes'],
    s3: ['Three techniques account for most of the saving', 'Three techniques cut response time and cost together', 'Name the three techniques'],
    s4: ['Quantisation alone cuts serving cost by 38%', null, 'Prove the biggest lever'],
    s5: ['Caching repeated context removes a fifth of the compute', null, 'Explain how caching works'],
    s6: ['A phased rollout over two quarters keeps risk low while the savings build', null, 'Show the rollout is safe'],
    s7: ['What it costs and what it returns', 'What faster answers are worth', 'Put the numbers side by side'],
    s8: ['Decision needed: approve the pilot by 30 November', null, 'Ask for the decision']
  };
  function head(id, st) {
    var h = H[id];
    if (id === 's6' && st.s6Short) return 'Two quarters, three phases';
    return (st.lead === 'latency' && h[1]) ? h[1] : h[0];
  }
  var css = [
    '.ms-slide{aspect-ratio:16/9;width:100%;container-type:inline-size;overflow:hidden;position:relative;font-family:system-ui,sans-serif}',
    '.ms-slide h3{margin:0;font-weight:700;line-height:1.15}',
    '.ms-slide .b{position:absolute;left:6cqw;right:6cqw;bottom:6cqw;font-size:2.2cqw;line-height:1.4}',
    '.ms-slide .t{position:absolute;left:6cqw;right:6cqw;top:5cqw;font-size:3.6cqw}',
    '.ms-slide .n{position:absolute;right:3cqw;top:2cqw;font-size:1.8cqw;opacity:.6}',
    '.ms-slide .hero{position:absolute;left:6cqw;top:16cqw;font-size:16cqw;font-weight:800}',
    '.ms-slide .bars{position:absolute;left:6cqw;bottom:6cqw;display:flex;gap:2cqw;align-items:flex-end}',
    '.ms-slide .bars i{display:block;width:6cqw;background:currentColor;opacity:.7}',
    '.ms-slide .foot{position:absolute;right:6cqw;bottom:3cqw;font-size:1.6cqw;opacity:.7}',
    '.ms-dir-default{background:#fff;color:#222}',
    '.ms-dir-default::before{content:"";position:absolute;left:0;top:0;bottom:0;width:1.4cqw;background:#2b6cb0}',
    '.ms-dir-a{background:#14202b;color:#f1ece2;font-family:Georgia,serif}',
    '.ms-dir-b{background:#f4efe6;color:#1b3a2f}',
    '.ms-dir-b h3{text-transform:uppercase;letter-spacing:.04em}',
    '.ms-dir-c{background:#e84a2f;color:#fff;font-family:Helvetica,Arial,sans-serif}'
  ].join('');
  function render(id, dir, st) {
    var n = ids.indexOf(id) + 1, h = head(id, st), body = '';
    if (id === 's4' && st.s4Hero) body = '<div class="hero">38%</div><div class="foot">Before 100, after 62</div>';
    else if (id === 's4') body = '<div class="bars"><i style="height:20cqw"></i><i style="height:12.4cqw"></i></div>';
    else if (id === 's5') body = '<div class="b">Cache hit: reuse context<br>Point one<br>Point two<br>Point three<br>Point four</div>';
    else body = '<div class="b">' + (st.lead === 'latency' && 's1 s2 s3 s7'.indexOf(id) >= 0 ? 'Latency lead. ' : 'Cost lead. ') + 'Body of slide ' + n + '</div>';
    return '<div class="ms-slide ms-dir-' + dir + '"><div class="n">' + n + '</div><h3 class="t">' + h + '</h3>' + body + '</div>';
  }
  var dirs = [
    { id: 'default', name: 'Default', provisional: true, concept: 'The template look: title top-left, bullets and a blue bar.', palette: [{ name: 'Blue', hex: '#2b6cb0', role: 'Accent bar' }, { name: 'White', hex: '#ffffff', role: 'Ground' }], type: { display: 'System sans', body: 'System sans' }, rules: ['Title top-left.', 'Bullets for everything.', 'Blue bar on the left.'] },
    { id: 'a', name: 'Ledger', provisional: false, concept: 'Dark ground and a serif, like a financial statement.', palette: [{ name: 'Ink', hex: '#14202b', role: 'Ground' }, { name: 'Paper', hex: '#f1ece2', role: 'Text' }], type: { display: 'Georgia', body: 'Georgia' }, rules: ['One idea per slide.', 'No decoration.', 'Numbers set large.'] },
    { id: 'b', name: 'Field notes', provisional: false, concept: 'Warm paper and green, with capitals for headers.', palette: [{ name: 'Paper', hex: '#f4efe6', role: 'Ground' }, { name: 'Pine', hex: '#1b3a2f', role: 'Text' }], type: { display: 'System sans, capitals', body: 'System sans' }, rules: ['Capitals for headers.', 'Warm ground.', 'Short lines.'] },
    { id: 'c', name: 'Signal', provisional: false, concept: 'A single hot colour field with white type.', palette: [{ name: 'Signal', hex: '#e84a2f', role: 'Ground' }, { name: 'White', hex: '#ffffff', role: 'Text' }], type: { display: 'Helvetica', body: 'Helvetica' }, rules: ['One colour.', 'White type only.', 'Big headers.'] }
  ];
  return {
    css: css,
    directions: dirs,
    slideIds: ids,
    headers: function (st) { return ids.map(function (id, i) { return { id: id, n: i + 1, header: head(id, st), intent: H[id][2] }; }); },
    render: render,
    renderSample: function (d) {
      var st = { lead: 'cost', s4Hero: false, s6Short: false };
      return [render('s1', d, st), render('s2', d, st), render('s4', d, st)];
    }
  };
})();
