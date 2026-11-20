// Lesson-prep workflow smoke test: one consent, one scan, instant topic switching.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const { JSDOM } = require('jsdom');
const dom = new JSDOM('<div id="root"></div>', { url: 'https://example.test' });
global.window = dom.window; global.document = dom.window.document; global.navigator = dom.window.navigator;
global.localStorage = dom.window.localStorage; global.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react');
const { createRoot } = require('react-dom/client');
const { act } = require('react-dom/test-utils');

const calls = [];
let identity = 'user1';
let mapResponse;
let topicResponse;
let failTopic = false;
const ui = {
  Button: ({ children, variant, size, ...props }) => React.createElement('button', props, children),
  Spinner: () => React.createElement('span', { 'data-testid': 'spinner' }),
};
const mockApi = { post: async (url, body) => {
  calls.push({ url, body });
  if (url.endsWith('/vision-map/preview')) return mapResponse;
  if (url.endsWith('/vision-topic/preview')) { if (failTopic) throw new Error('Provayder ishlamadi'); return topicResponse; }
  throw new Error(`unexpected ${url}`);
} };
const preview = { PreviewExercise: ({ ex }) => React.createElement('div', { 'data-testid': 'exercise' }, ex.instruction) };

function load(file, extra) {
  const source = fs.readFileSync(file, 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const module = { exports: {} };
  function mocked(name) {
    if (name === '@/lib/api') return mockApi;
    if (name === '@/components/ui') return ui;
    if (name === '@/lib/auth') return { useAuth: () => ({ me: { id: identity } }) };
    if (name === './preview-exercise') return preview;
    if (extra && extra[name]) return extra[name];
    return require(name);
  }
  vm.runInThisContext(`(function(require,module,exports){${code}\n})`, { filename: file })(mocked, module, module.exports);
  return module.exports;
}

const workflow = load('src/components/reader/lesson-vision-workflow.tsx');

// ---- page parsing ----
assert.deepEqual(workflow.parsePages('1, 2, 3', 115), [1, 2, 3]);
assert.deepEqual(workflow.parsePages('1-3, 5', 115), [1, 2, 3, 5]);
assert.deepEqual(workflow.parsePages('3', 10), [3]);
assert.equal(workflow.parsePages('1-6', 115), null);        // more than five pages
assert.equal(workflow.parsePages('1-5, 10', 115), null);    // over the per-call page limit
assert.equal(workflow.parsePages('1, 1', 115), null);       // duplicates
assert.equal(workflow.parsePages('0, 1', 115), null);       // out of range
assert.equal(workflow.parsePages('abc', 115), null);        // not a page number

// ---- render with a locally saved scan ----
const topicA = { title: 'Revision I', page_start: 16, page_end: 16, evidence_pages: [16], content_types: ['exercise'], uncertainty: '' };
const topicB = { title: 'Plurals', page_start: 17, page_end: 18, evidence_pages: [17, 18], content_types: ['theory'], uncertainty: '' };
const topicC = { title: 'Articles', page_start: 19, page_end: 20, evidence_pages: [19], content_types: ['exercise'], uncertainty: '' };
const map = { sampled_pages: [1, 2, 3], total_pages: 115, partial: true, title: '', author: '', warnings: [],
  provider: 'gemini', model: 'gemini-3.5-flash-lite', topics: [topicA, topicB, topicC] };
const topicKey = (topic) => `lingora.vision-topic.user1.book.${encodeURIComponent(JSON.stringify([topic.title, topic.page_start, topic.page_end, topic.evidence_pages]))}`;
const exercise = (instruction, pages) => ({ number: '1', instruction, exercise_type: 'other', context: '', uncertainty: '', evidence_pages: pages, questions: [] });
const savedA = { result: { topic: 'Revision I', sampled_pages: [1, 2, 3], provider: 'gemini', model: 'm', warnings: [], theory: [],
  exercises: [exercise('Fill-in-the-blank, Plurals', [16])] }, answers: [[]] };
localStorage.setItem('lingora.vision-map.user1.book', JSON.stringify(map));
localStorage.setItem(topicKey(topicA), JSON.stringify(savedA));
topicResponse = { topic: 'Plurals', sampled_pages: [1, 2, 3], provider: 'gemini', model: 'm', warnings: [], theory: [],
  exercises: [exercise('Multiple Choice: Mashqlar', [17, 18])] };

const container = document.getElementById('root');
const buttons = () => Array.from(container.querySelectorAll('button'));
const button = (text) => buttons().find((b) => b.textContent.includes(text));
const consent = () => Array.from(container.querySelectorAll('label')).find((l) => l.textContent.includes('barcha mashg')).querySelector('input');
async function click(element) { assert.ok(element, 'element to click'); await act(async () => element.click()); }

async function main() {
  let root = createRoot(container);
  await act(async () => root.render(React.createElement(workflow.LessonVisionWorkflow, { bookId: 'book', pageCount: 115 })));

  // Single input, prefilled default pages, one consent, one CTA.
  assert.equal(container.querySelectorAll('input[type=checkbox]').length, 1);
  assert.equal(container.querySelector('input[placeholder="Misol: 1-5, 10"]').value, '1, 2, 3');
  assert.equal(button('Sahifalarni tahlil qilish va Mashqlarni yaratish').disabled, true);
  assert.match(container.textContent, /gemini-3\.5-flash-lite/);
  assert.match(container.textContent, /\| 3 \/ 115 sahifa/);
  assert.match(container.textContent, /Aniqlangan mavzular va Mashqlar/);
  // The first chip is active and its locally saved exercises are visible without any request.
  assert.equal(buttons().find((b) => b.getAttribute('role') === 'tab').getAttribute('aria-selected'), 'true');
  assert.match(container.textContent, /Fill-in-the-blank, Plurals/);
  assert.match(container.textContent, /Sahifalar: 16-16/);
  assert.deepEqual(calls, []);

  // Switching to an uncached topic with no consent asks for the checkbox instead of sending pages.
  await click(button('Plurals'));
  assert.match(container.textContent, /rozilik katakchasini belgilang/);
  assert.deepEqual(calls, []);

  // One consent, then the switch creates the exercises with the scanned pages, preferring stored topics.
  await click(consent());
  await click(button('Mashqlarni tayyorlash'));
  assert.deepEqual(calls.map((c) => c.url), ['/books/book/vision-topic/preview']);
  assert.deepEqual(calls[0].body.page_numbers, [1, 2, 3]);
  assert.equal(calls[0].body.topic, 'Plurals');
  assert.equal(calls[0].body.consent_images_to_provider, true);
  assert.match(container.textContent, /Multiple Choice: Mashqlar/);

  // Going back to the first topic is instant: it reuses the stored preview.
  await click(button('Revision I'));
  assert.equal(calls.length, 1);
  assert.match(container.textContent, /Fill-in-the-blank, Plurals/);

  // A failure on the provider surfaces an Uzbek message and keeps the screen usable.
  failTopic = true;
  topicResponse = { ...topicResponse, topic: 'Articles' };
  await click(button('Articles'));
  await click(button('Qayta urinish'));
  assert.match(container.textContent, /Provayder ishlamadi/);
  failTopic = false;
  await click(button('Qayta urinish'));
  assert.equal(calls.at(-1).url, '/books/book/vision-topic/preview');
  assert.match(container.textContent, /Multiple Choice: Mashqlar/);
  assert.equal(calls.at(-1).body.topic, 'Articles');

  // Re-scanning replaces the topic list and prepares the first topic again.
  mapResponse = { ...map, sampled_pages: [4, 5], topics: [topicB] };
  window.confirm = () => true;
  const pagesInput = container.querySelector('input[placeholder="Misol: 1-5, 10"]');
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(pagesInput, '4-5');
    pagesInput.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
  const before = calls.length;
  await click(button('Sahifalarni tahlil qilish va Mashqlarni yaratish'));
  assert.equal(calls[before].url, '/books/book/vision-map/preview');
  assert.deepEqual(calls[before].body.page_numbers, [4, 5]);
  const after = calls.slice(before);
  assert.equal(after.filter((c) => c.url.endsWith('/vision-topic/preview')).length, 1);
  assert.equal(after.at(-1).body.topic, 'Plurals');
  assert.match(container.textContent, /2 \/ 115 sahifa/);

  // Invalid page text never reaches the provider.
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(pagesInput, '1-9');
    pagesInput.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
  const invalidBefore = calls.length;
  await click(button('Sahifalarni tahlil qilish va Mashqlarni yaratish'));
  assert.equal(calls.length, invalidBefore);
  assert.match(container.textContent, /Ko'pi bilan 5 ta takrorlanmagan sahifa kiriting/);

  // Storage is scoped per user.
  await act(async () => root.unmount());
  identity = 'user2';
  root = createRoot(container);
  await act(async () => root.render(React.createElement(workflow.LessonVisionWorkflow, { bookId: 'book', pageCount: 115 })));
  assert.doesNotMatch(container.textContent, /Aniqlangan mavzular va Mashqlar/);
  await act(async () => root.unmount());
  console.log('Lesson vision workflow single-consent, single-scan and instant topic switch tests passed');
}
main().catch((error) => { console.error(error); process.exit(1); });
