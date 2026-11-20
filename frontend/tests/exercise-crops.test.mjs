// Normalized exercise-crop geometry: no pixel math leaks into stored boxes.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/components/reader/exercise-crops.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const exports = {};
vm.runInNewContext(js, {
  exports,
  require: (name) => {
    if (name === '@/lib/api') return { getAccessToken: () => null };
    if (name === '@/lib/timeout') return { withTimeout: (p) => p };
    throw new Error(`unexpected import ${name}`);
  },
});
const { validBox, normalizeBox, padBox, boxToPixels, boxStyle, overlapRatio } = exports;
// Values come from another VM realm: compare plain JSON copies.
const plain = (value) => JSON.parse(JSON.stringify(value));

// Reversed corners are ordered, out-of-page values clamped.
assert.deepEqual(plain(normalizeBox([0.6, 0.6, 0.4, 0.2])), [0.4, 0.2, 0.6, 0.6]);
assert.deepEqual(plain(normalizeBox([0.1, 0.1, 1.4, 0.4])), [0.1, 0.1, 1, 0.4]);
assert.equal(normalizeBox([0.5, 0.5, 0.5, 0.9]), null);
assert.equal(normalizeBox('nope'), null);
assert.equal(validBox([0.1, 0.1, 0.9, 0.4]), true);
assert.equal(validBox([0.1, 0.1, 0.9, 1.4]), false);

// 1.5% padding never leaves the page.
assert.deepEqual(plain(padBox([0, 0, 1, 0.5], 0.02)), [0, 0, 1, 0.51]);

// The same normalized box maps proportionally to any canvas size => no DPI shift.
const small = boxToPixels([0.1, 0.2, 0.5, 0.6], 1000, 2000);
const large = boxToPixels([0.1, 0.2, 0.5, 0.6], 2000, 4000);
// Padding is applied, so the crop starts slightly before the box (never outside the page).
assert.ok(small.left < 100 && small.top < 400 && small.left + small.width > 500);
assert.ok(small.left >= 0 && small.top >= 0 && small.left + small.width <= 1000);
// Doubling the canvas doubles every pixel value: the stored box never needs recomputing.
for (const key of ['left', 'top', 'width', 'height']) assert.equal(large[key], small[key] * 2);

// A box touching the page edge still produces a non-empty crop.
const edge = boxToPixels([0.999, 0.999, 1, 1], 100, 100);
assert.ok(edge.width >= 1 && edge.height >= 1);
assert.ok(edge.left + edge.width <= 100 && edge.top + edge.height <= 100);

// CSS overlay uses percentages, so the editor works at any zoom.
assert.deepEqual(plain(boxStyle([0.1, 0.2, 0.5, 0.6])),
  { left: '10%', top: '20%', width: '40%', height: '40%' });

// Overlap rule: > 10% of the smaller box is a conflict; touching boxes are not.
assert.equal(overlapRatio([0, 0, 0.5, 0.5], [0.5, 0.5, 1, 1]), 0);
// The small box sits completely inside the large one: fully overlapped.
assert.equal(overlapRatio([0.1, 0.1, 0.9, 0.5], [0.1, 0.3, 0.5, 0.5]), 1);
// A third of the smaller box is covered (0.2 of 0.6 height).
assert.ok(Math.abs(overlapRatio([0.1, 0.1, 0.9, 0.4], [0.1, 0.3, 0.5, 0.6]) - 1 / 3) < 1e-9);
console.log('Exercise crop geometry tests passed');
