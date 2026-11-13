import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/lib/reader-utils.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const exports = {};
vm.runInNewContext(js, { exports });
const { overlayRect, fitScale, chooseLesson, trustedBlank } = exports;
const geometry = { width: 600, height: 800, scale: 1, rotation: 0 };
const b = [100, 200, 160, 240];
for (const [rotation, left, top] of [[0,100,200], [90,560,100], [180,440,560], [270,200,440]]) {
  const r = overlayRect(b, { ...geometry, rotation });
  assert.equal(r.left, left); assert.equal(r.top, top);
}
const scaled = overlayRect(b, { ...geometry, scale: 1.5, rotation: 90 });
assert.equal(scaled.left, 840); assert.equal(scaled.top, 150);
assert.equal(scaled.width, 60); assert.equal(scaled.height, 90);
assert.equal(trustedBlank({ bbox: b }), false); // legacy proportional estimate
assert.equal(trustedBlank({ bbox: b, geometry: 'native_chars' }), true);
assert.equal(trustedBlank({ bbox: null, geometry: 'native_chars' }), false);
assert.equal(fitScale(624, 824, 600, 800, 1), 1);
assert.equal(fitScale(624, 424, 600, 800, 1), 0.5);
assert.equal(fitScale(624, 424, 600, 800, 2), 1);
const lessons = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
const progress = { a: { last_visited_at: '2026-01-01' }, b: { last_visited_at: '2026-03-01' }, c: { locked: true, last_visited_at: '2026-05-01' } };
assert.equal(chooseLesson(lessons, progress, null).id, 'b');
assert.equal(chooseLesson(lessons, progress, 'a').id, 'a');
assert.equal(chooseLesson(lessons, progress, 'c').id, 'b');
assert.equal(chooseLesson(lessons, {}, null).id, 'a');
console.log('Reader geometry and resume selection tests passed');
