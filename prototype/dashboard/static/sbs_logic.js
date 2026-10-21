'use strict';
/* Pure helpers for the side-by-side step player (no DOM). Tested with node. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.sbsLogic = factory();
})(this, function () {
  var STEPS = 6;
  var SPEEDS = [0.25, 0.5, 1, 1.5, 2];

  // state: {probe, step}; probe -1 = not started. Returns the next state plus done=true at the very end.
  function next(state, count) {
    if (!count) return { probe: -1, step: 0, done: true };
    if (state.probe < 0) return { probe: 0, step: 1, done: false };
    if (state.step < STEPS) {
      var last = state.probe + 1 >= count && state.step + 1 === STEPS;  // reaching the final step ends playback now
      return { probe: state.probe, step: state.step + 1, done: last };
    }
    if (state.probe + 1 < count) return { probe: state.probe + 1, step: 1, done: false };
    return { probe: state.probe, step: STEPS, done: true };
  }
  function delay(speed) {
    var s = Math.min(2, Math.max(0.25, Number(speed) || 1));
    return Math.round(1000 / s);
  }
  function percent(value, max) {
    if (typeof value !== 'number' || !(value >= 0) || !(max > 0)) return 0;
    return Math.max(1, Math.min(100, Math.round(100 * value / max)));
  }
  // Meter reads Red has made up to and including this probe (after_probe is 1-based).
  function readsSoFar(meter, probe) {
    if (!meter || !Array.isArray(meter.reads)) return [];
    return meter.reads.filter(function (r) { return r.state && r.after_probe <= probe + 1; });
  }
  function readsLeft(meter, probe) {
    if (!meter) return null;
    return Math.max(0, (meter.reads_budget || 3) - readsSoFar(meter, probe).length);
  }
  function meterAt(meter, probe) {
    var seen = readsSoFar(meter, probe);
    return seen.length ? seen[seen.length - 1].state : null;
  }
  function maxRelease(arms) {
    var max = 0;
    Object.keys(arms).forEach(function (name) {
      arms[name].requests.forEach(function (r) { if (r.red.release_seconds > max) max = r.red.release_seconds; });
    });
    return max;
  }
  // Four presenter screens, in order.
  var SCREENS = [
    { id: 1, title: 'Same attack, two outcomes', caption: 'Left: time se leak hota hai. Right: har reply ek hi fixed time par.' },
    { id: 2, title: 'Isolation and audit', caption: 'Red Blue tak nahi pahunch sakta; log badla to turant pakda jata hai.' },
    { id: 3, title: 'Measured comparison', caption: 'Red ka guess 50% ke paas matlab: usse farak pata nahi chala.' },
    { id: 4, title: 'Limits', caption: 'Ye kya nahi rokta, wo bhi saaf likha hai.' }
  ];
  function screenIndex(current, delta) {
    return Math.min(SCREENS.length - 1, Math.max(0, current + delta));
  }
  return { STEPS: STEPS, SPEEDS: SPEEDS, next: next, delay: delay, percent: percent, readsSoFar: readsSoFar,
           readsLeft: readsLeft, meterAt: meterAt, maxRelease: maxRelease, SCREENS: SCREENS, screenIndex: screenIndex };
});
