'use strict';
const test = require('node:test');
const assert = require('node:assert');
const L = require('../dashboard/static/sbs_logic.js');

test('player walks 6 steps per probe and ends once', () => {
  let state = { probe: -1, step: 0 }, seen = [];
  for (let i = 0; i < 100; i++) {
    const n = L.next(state, 3);
    state = { probe: n.probe, step: n.step };
    seen.push(n);
    if (n.done) break;
  }
  assert.deepStrictEqual(seen[0], { probe: 0, step: 1, done: false });
  assert.deepStrictEqual(seen[5], { probe: 0, step: 6, done: false });
  assert.deepStrictEqual(seen[6], { probe: 1, step: 1, done: false });
  assert.strictEqual(seen.length, 18);
  assert.deepStrictEqual(seen[17], { probe: 2, step: 6, done: true });
  assert.deepStrictEqual(L.next({ probe: -1, step: 0 }, 0), { probe: -1, step: 0, done: true });
});

test('speed maps to a bounded delay', () => {
  assert.strictEqual(L.delay(1), 1000);
  assert.strictEqual(L.delay(0.25), 4000);
  assert.strictEqual(L.delay(2), 500);
  assert.strictEqual(L.delay(100), 500);
  assert.strictEqual(L.delay('x'), 1000);
});

test('bar widths are proportional and never invent a value', () => {
  assert.strictEqual(L.percent(0.5, 1), 50);
  assert.strictEqual(L.percent(0.001, 1), 1);
  assert.strictEqual(L.percent(null, 1), 0);
  assert.strictEqual(L.percent(0.5, 0), 0);
  assert.strictEqual(L.maxRelease({ a: { requests: [{ red: { release_seconds: 0.2 } }, { red: { release_seconds: 1.1 } }] },
                                    b: { requests: [{ red: { release_seconds: 0.9 } }] } }), 1.1);
});

test('meter reads only count once Red has made them', () => {
  const meter = { reads_budget: 3, reads: [{ after_probe: 10, state: 'STABLE' }, { after_probe: 20, state: 'IMPROVING' }] };
  assert.strictEqual(L.meterAt(meter, 3), null);
  assert.strictEqual(L.meterAt(meter, 9), 'STABLE');
  assert.strictEqual(L.meterAt(meter, 19), 'IMPROVING');
  assert.strictEqual(L.readsLeft(meter, 3), 3);
  assert.strictEqual(L.readsLeft(meter, 9), 2);
  assert.strictEqual(L.readsLeft(meter, 19), 1);
  assert.strictEqual(L.readsLeft(null, 5), null);
});

test('presenter has exactly four screens and clamps', () => {
  assert.strictEqual(L.SCREENS.length, 4);
  assert.strictEqual(L.screenIndex(0, -1), 0);
  assert.strictEqual(L.screenIndex(3, 1), 3);
  assert.strictEqual(L.screenIndex(1, 1), 2);
});
