import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/lib/lesson-plan.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const exports = {};
vm.runInNewContext(js, { exports, URLSearchParams });
const { suggestLessons, validPlan, planUrl } = exports;
const options = [
  { id: 'a', progress: { locked: false, status: 'completed', last_visited_at: '2026-01-01' } },
  { id: 'b', progress: { locked: false, status: 'not_started', last_visited_at: null } },
  { id: 'c', progress: { locked: false, status: 'in_progress', last_visited_at: '2026-02-01' } },
  { id: 'd', progress: { locked: true, status: 'in_progress', last_visited_at: '2026-03-01' } },
];
const array = (a) => Array.from(a);
assert.deepEqual(array(suggestLessons(options, 2)), ['c', 'b']);
assert.deepEqual(array(suggestLessons(options, 1)), ['c']);
assert.deepEqual(array(suggestLessons(options, 5)), ['c', 'b', 'a']);
assert.deepEqual(array(suggestLessons([], 2)), []);
assert.deepEqual(array(validPlan('b,d,b,x,c', options, { d: { locked: true } })), ['b', 'c']);
assert.deepEqual(array(validPlan(null, options, {})), []);
const url = planUrl('book', 'b', ['b', 'c']);
const parsed = new URL(url, 'https://example.test');
assert.equal(parsed.pathname, '/reader/book');
assert.equal(parsed.searchParams.get('lesson'), 'b');
assert.equal(parsed.searchParams.get('plan'), 'b,c');
console.log('Lesson selection, recommendation and plan validation tests passed');
