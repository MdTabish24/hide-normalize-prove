'use strict';
/* Side-by-side playback of ONE recorded request sequence. All numbers come from /api/duel (a recorded run and saved
   matrix files). Playback is not live and nothing here is animated without a recorded event behind it. */
(function () {
  var L = window.sbsLogic;
  var data = null, state = { probe: -1, step: 0 }, timer = null, playing = false, presenter = false, screen = 0;
  var $ = function (id) { return document.getElementById(id); };

  function h(tag, cls, text, children) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    (children || []).forEach(function (c) { if (c) node.append(c); });
    return node;
  }
  function pill(text, kind) { return h('span', 'pill ' + (kind || ''), text); }
  function verdictKind(v) { return ['PASS', 'VALID', 'BLOCKED', 'RECORDED'].indexOf(v) >= 0 ? 'good' : ['FAIL', 'INVALID', 'LEAKED'].indexOf(v) >= 0 ? 'bad' : 'wait'; }

  // ---- one panel ------------------------------------------------------------------------------------------------
  function stepTexts(side, arm, r) {
    var meter = arm.meter, left = L.readsLeft(meter, r.index), here = meter && meter.reads.filter(function (m) { return m.after_probe === r.index + 1; })[0];
    var report = !meter ? 'Report / feedback: koi feedback mode nahi (meter off).'
      : here ? 'Red ne meter padha: ' + here.state + ' (reads left ' + left + ' of ' + (meter.reads_budget || 3) + ').'
             : 'Is probe ke baad Red ne meter nahi padha (reads left ' + left + ' of ' + (meter.reads_budget || 3) + ').';
    return [
      { text: r.probe + ': Red ne probe bheja.', who: 'red' },
      { text: side === 'raw' ? 'Raw: koi fixed clock nahi, reply ready hote hi nikal jata hai.'
                              : 'Gateway ne fixed clock (window) shuru ki; Red ko sab kuch usi time par milega.', who: 'env' },
      { text: "Blue ka filter: " + r.evaluator.why, who: 'eval' },
      { text: 'Model: ' + r.evaluator.model, who: 'eval' },
      { text: r.red.text + (r.red.envelope_exact ? ', 64 bytes, same envelope.' : ' (envelope badla!).'), who: 'red' },
      { text: report, who: 'red' }
    ];
  }

  function stepList(side, arm) {
    var list = h('ol', 'steps');
    if (state.probe < 0) { list.append(h('li', 'dim', 'Play dabao: har probe 6 steps me chalega.')); return list; }
    var r = arm.requests[state.probe];
    stepTexts(side, arm, r).forEach(function (s, i) {
      var cls = i + 1 < state.step ? 'done' : i + 1 === state.step ? 'active' : 'dim';
      var future = i + 1 > state.step;  // do not reveal a step before the player reaches it
      var li = h('li', cls + ' ' + s.who, null, [h('b', null, String(i + 1)), h('span', null, future ? '…' : s.text)]);
      if (s.who === 'eval' && !future) li.append(h('em', 'tag', 'evaluator only'));
      list.append(li);
    });
    return list;
  }

  function bars(arm, max) {
    var box = h('div', 'bars');
    arm.requests.forEach(function (r, i) {
      var shown = state.probe > i || (state.probe === i && state.step >= 5);
      var cls = 'row' + (state.probe === i ? ' current' : '');
      var track = h('div', 'track');
      var bar = h('div', 'bar ' + (shown ? (r.evaluator.blue_allowed === false ? 'blocked' : r.evaluator.blue_allowed ? 'allowed' : 'unknown') : 'hidden'));
      bar.style.width = shown ? L.percent(r.red.release_seconds, max) + '%' : '0%';
      track.append(bar);
      var value = shown ? (r.red.release_seconds === null ? 'NOT RUN' : r.red.release_seconds.toFixed(2) + ' s') + (r.evaluator.late ? ' · model baad me pura hua' : '') : '';
      box.append(h('div', cls, null, [h('span', 'lab', 'P' + (i + 1)), track, h('span', 'val', value)]));
    });
    return box;
  }

  function meterBox(arm) {
    var box = h('div', 'meter');
    if (!arm.meter) { box.append(h('p', 'muted', 'Feedback meter: off (FEEDBACK_MODE=none).')); return box; }
    var shown = state.probe < 0 ? null : L.meterAt(arm.meter, state.step >= 6 ? state.probe : state.probe - 1);
    var left = state.probe < 0 ? arm.meter.reads_budget : L.readsLeft(arm.meter, state.step >= 6 ? state.probe : state.probe - 1);
    box.append(h('p', 'muted', 'Red ko meter me kya dikhta hai (batch of 10 ke baad hi badalta hai)'));
    box.append(h('div', 'meter-row', null, [shown ? pill(shown, 'meter-' + shown.toLowerCase()) : pill('abhi padha nahi', 'wait'),
                                           h('span', 'muted', 'Reads left: ' + (left === null ? '?' : left) + ' of ' + (arm.meter.reads_budget || 3))]));
    var truth = h('div', 'evaluator-box', null, [h('b', null, 'Evaluator only: asli batch score')]);
    var any = false;
    arm.meter.batches.forEach(function (b) {
      if ((b.batch + 1) * 10 <= state.probe + 1 && state.step >= 6) {
        any = true;
        truth.append(h('p', null, 'Batch ' + (b.batch + 1) + ' (probes ' + (b.batch * 10 + 1) + '-' + (b.batch * 10 + 10) + '): ' + Math.round(100 * b.score) + '% probes Blue se nikal gaye; Red ko dikha ' + b.published));
      }
    });
    if (!any) truth.append(h('p', 'muted', 'Pehla batch poora hone par dikhega.'));
    box.append(truth);
    return box;
  }

  function accuracyBox(a) {
    var cls = a.status === 'SAVED' ? 'acc' : 'acc wait';
    return h('div', cls, null, [h('b', null, "Red ka guess (saved matrix)"), h('p', null, a.text), h('small', 'muted', a.label)]);
  }

  function renderPanel(side) {
    var el = $('panel-' + side), arm = data.arms[side];
    el.replaceChildren();
    el.append(h('header', null, null, [h('h2', null, arm.title), pill(arm.policy + (arm.window_continue ? ' + continue' : ''), 'wait')]));
    el.append(h('p', 'scope', side === 'raw'
      ? 'Raw timing. Auth, Blue filter, encryption aur audit abhi bhi ON; sirf timing ka padding nahi hai.'
      : 'Fixed window release; compute cancel nahi hota, peeche chalta hai (opt-in). Meter bhi opt-in.'));
    el.append(h('h3', null, 'Red ke saath kya hota hai'), stepList(side, arm));
    el.append(h('h3', null, 'Red ko mila release time (har probe)'), bars(arm, L.maxRelease(data.arms)));
    el.append(h('p', 'legend-line muted', 'Bar ka rang (hara = Blue ne allow kiya, laal = block) sirf evaluator ko dikhta hai; Red ko sirf lambai dikhti hai.'));
    el.append(h('p', side === 'raw' ? 'timing leak' : 'timing', 'Is recording ka measured summary: ' + arm.timing));
    el.append(meterBox(arm), accuracyBox(data.accuracy[side]));
    el.append(h('p', 'audit', 'Audit: ' + arm.audit.status + (arm.audit.events ? ' (' + arm.audit.events + ' events)' : '') + ' · ' + data.label));
  }

  function renderPlayer() {
    var count = data.sequence.length;
    $('progress').textContent = state.probe < 0 ? 'Press Play' : 'Probe ' + (state.probe + 1) + ' of ' + count + ' · step ' + state.step + ' of ' + L.STEPS;
    $('play').textContent = playing ? '❚❚ Pause' : '▶ Play';
    renderPanel('raw');
    renderPanel('ours');
  }

  // ---- player ---------------------------------------------------------------------------------------------------
  function stop() { playing = false; clearTimeout(timer); }
  function advance() {
    var n = L.next(state, data.sequence.length);
    state = { probe: n.probe, step: n.step };
    renderPlayer();
    return n.done;
  }
  function tick() {
    if (!playing) return;
    if (advance()) { stop(); renderPlayer(); return; }
    timer = setTimeout(tick, L.delay($('speed').value));
  }
  function play() {
    if (playing) { stop(); renderPlayer(); return; }
    if (state.probe >= data.sequence.length - 1 && state.step >= L.STEPS) state = { probe: -1, step: 0 };
    playing = true;
    renderPlayer();
    timer = setTimeout(tick, L.delay($('speed').value));
  }
  function back() {
    stop();
    if (state.step > 1) state = { probe: state.probe, step: state.step - 1 };
    else if (state.probe > 0) state = { probe: state.probe - 1, step: L.STEPS };
    else state = { probe: -1, step: 0 };
    renderPlayer();
  }

  // ---- other screens ----------------------------------------------------------------------------------------------
  function fillList(id, lines) {
    $(id).replaceChildren.apply($(id), lines.map(function (t) { return h('li', null, t); }));
  }
  function renderStatic() {
    $('iso-head').replaceChildren(pill(data.isolation.result, verdictKind(data.isolation.result)), document.createTextNode(' ' + data.isolation.headline));
    fillList('iso-list', data.isolation.details);
    $('iso-when').textContent = data.isolation.recorded_at ? 'Saved evidence, recorded ' + data.isolation.recorded_at + ' (not a fresh Docker check).' : 'NOT RUN';
    $('tamper-head').replaceChildren(pill(data.tamper.result, verdictKind(data.tamper.result)), document.createTextNode(' ' + data.tamper.headline));
    fillList('tamper-list', data.tamper.details);
    $('tamper-when').textContent = data.tamper.recorded_at ? 'Saved evidence, recorded ' + data.tamper.recorded_at + '. A local checkpoint is not an independent witness.' : 'NOT RUN';
    fillList('notstopped', data.not_stopped.map(function (r) { return r.attack + ' [' + r.result + ']: ' + r.why; }));
    fillList('limits', data.limits);
  }

  var POLICIES = [['raw', '#c97b7b'], ['bucket_hard', '#d9b36b'], ['window_hard', '#6aa6c9'], ['window_continue', '#7cc49a']];
  var COHORTS = ['ordinary', 'boundary', 'overflow', 'deadline_near', 'deadline_far'];
  function renderChart() {
    var box = $('chart'), legend = $('legend');
    box.replaceChildren();
    legend.replaceChildren();
    POLICIES.forEach(function (p) {
      var name = (data.chart.filter(function (r) { return r.policy === p[0]; })[0] || {}).label || p[0];
      var sw = h('span', 'swatch'); sw.style.background = p[1];
      legend.append(h('span', 'key', null, [sw, document.createTextNode(' ' + name)]));
    });
    var line = h('div', 'half'); box.append(line);
    COHORTS.forEach(function (cohort) {
      var group = h('div', 'group'), area = h('div', 'area');
      POLICIES.forEach(function (p) {
        var cell = data.chart.filter(function (r) { return r.policy === p[0] && r.cohort === cohort; })[0];
        var saved = cell && cell.status === 'SAVED' && cell.accuracy !== null;
        var bar = h('div', 'cbar' + (saved ? '' : ' missing'), null, saved ? [h('i', null, Math.round(100 * cell.accuracy) + '')] : [h('i', null, 'NR')]);
        bar.style.height = saved ? Math.max(3, 100 * cell.accuracy) + '%' : '14%';
        if (saved) bar.style.background = p[1];
        bar.title = saved ? p[0] + ' ' + cohort + ': ' + (100 * cell.accuracy).toFixed(1) + '% (n=' + cell.n + ')' : p[0] + ' ' + cohort + ': NOT RUN';
        area.append(bar);
      });
      group.append(area, h('span', 'gl', cohort));
      box.append(group);
    });
  }

  // ---- presenter --------------------------------------------------------------------------------------------------
  function applyScreens() {
    document.body.classList.toggle('presenter', presenter);
    $('presenter').setAttribute('aria-pressed', String(presenter));
    $('presenter-nav').hidden = !presenter;
    [1, 2, 3, 4].forEach(function (n) { $('screen-' + n).hidden = presenter && n - 1 !== screen; });
    if (presenter) {
      var s = L.SCREENS[screen];
      $('screen-label').textContent = 'Screen ' + s.id + ' of 4: ' + s.title;
      $('caption').textContent = s.caption;
    }
  }

  // ---- load -------------------------------------------------------------------------------------------------------
  function render() {
    if (data.status === 'NOT RUN') {
      $('sbs-note').textContent = 'NOT RUN: no recorded side-by-side run yet. Run: python -m dashboard.duel_run (about a minute), or use the button.';
      ['play', 'step', 'back', 'reset'].forEach(function (id) { $(id).disabled = true; });
      $('panel-raw').replaceChildren(h('p', 'wait', 'NOT RUN'));
      $('panel-ours').replaceChildren(h('p', 'wait', 'NOT RUN'));
    } else {
      $('sbs-note').textContent = data.note + ' Recorded ' + data.recorded_at + ' · ' + data.label + '.' + (data.status === 'PARTIAL' ? ' PARTIAL recording.' : '');
      renderPlayer();
    }
    renderStatic();
    renderChart();
    applyScreens();
  }

  function load() {
    return fetch('/api/duel').then(function (r) { return r.json(); }).then(function (d) { data = d; render(); })
      .catch(function () { $('sbs-note').textContent = 'Server unavailable; nothing asserted.'; });
  }

  $('play').onclick = play;
  $('step').onclick = function () { stop(); if (data.status !== 'NOT RUN') advance(); };
  $('back').onclick = back;
  $('reset').onclick = function () { stop(); state = { probe: -1, step: 0 }; renderPlayer(); };
  $('speed').onchange = function () { if (playing) { clearTimeout(timer); timer = setTimeout(tick, L.delay($('speed').value)); } };
  $('presenter').onclick = function () { presenter = !presenter; screen = 0; applyScreens(); };
  $('prev').onclick = function () { screen = L.screenIndex(screen, -1); applyScreens(); };
  $('nextscreen').onclick = function () { screen = L.screenIndex(screen, 1); applyScreens(); };
  document.addEventListener('keydown', function (e) {
    if (!presenter) return;
    if (e.key === 'ArrowRight') { screen = L.screenIndex(screen, 1); applyScreens(); }
    if (e.key === 'ArrowLeft') { screen = L.screenIndex(screen, -1); applyScreens(); }
  });
  $('record').onclick = function () {
    $('record').disabled = true;
    fetch('/api/jobs', { method: 'POST', headers: { 'content-type': 'application/json', 'x-demo-ui': '1' }, body: JSON.stringify({ action: 'duel', policy: 'bucket_hard', secret: 'A' }) })
      .then(function (r) { return r.json(); }).then(function (v) {
        $('record-status').textContent = v.reason || (v.status === 'queued' ? 'Queued; reload in about a minute.' : v.status);
        $('record').disabled = false;
      }).catch(function () { $('record-status').textContent = 'Local server unavailable'; $('record').disabled = false; });
  };
  load();
})();
