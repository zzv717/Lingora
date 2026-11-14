// Component smoke test with mocked API/PDF; does not substitute for a browser or real provider test.
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
const ui = { Button: ({ children, variant, size, ...props }) => React.createElement('button', props, children) };
let fail = false;
let response = { verdicts: [{ index: 0, correct: true, explanation_uz: 'Izoh' }] };
const mockApi = { post: async (url, body) => { calls.push({ url, body }); if (fail) throw new Error('Provayder ishlamadi'); return response; } };
function load(file, extra) {
  const source = fs.readFileSync(file, 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const module = { exports: {} };
  function mocked(name) {
    if (name === '@/lib/api') return mockApi;
    if (name === '@/components/ui') return ui;
    if (name === '@/lib/auth') return { useAuth: () => ({ me: { id: identity } }) };
    if (name === './pdf-viewer') return { PdfViewer: ({ pageNumber }) => React.createElement('div', { 'data-testid': 'pdf' }, `PDF page ${pageNumber}`) };
    if (extra && extra[name]) return extra[name];
    return require(name);
  }
  vm.runInThisContext(`(function(require,module,exports){${code}\n})`, { filename: file })(mocked, module, module.exports);
  return module.exports;
}
const preview = load('src/components/reader/preview-exercise.tsx');
const { VisionMapPreview } = load('src/components/reader/vision-map-preview.tsx', { './preview-exercise': preview });
const topic = { title: 'Articles', page_start: 1, page_end: 2, evidence_pages: [1], content_types: ['exercise'], uncertainty: '' };
const result = { sampled_pages: [1, 2], provider: 'mock', model: 'test', warnings: [], theory: [], exercises: [
  { number: '1', instruction: 'Look', exercise_type: 'other', context: '', uncertainty: '', evidence_pages: [2],
    questions: [{ number: '2', prompt: '...', options: [], evidence_pages: [2] }] }] };
localStorage.setItem('lingora.vision-map.user1.book', JSON.stringify({ topics: [topic], sampled_pages: [1], total_pages: 2, title: '', author: '', warnings: [], provider: 'mock', model: 'test' }));
const topicKey = `lingora.vision-topic.user1.book.${encodeURIComponent(JSON.stringify(['Articles', 1, 2, [1]]))}`;
localStorage.setItem(topicKey, JSON.stringify({ result, answers: [['old']] }));
const container = document.getElementById('root');
const buttons = () => Array.from(container.querySelectorAll('button'));
const button = (text) => buttons().find((b) => b.textContent.includes(text));
async function click(element) { assert.ok(element); await act(async () => element.click()); }
async function main() {
  let root = createRoot(container);
  await act(async () => root.render(React.createElement(VisionMapPreview, { bookId: 'book', pageCount: 2 })));
  assert.equal(container.querySelector('textarea').value, 'old');
  await click(button('Asl PDF'));
  assert.equal(container.querySelector('[data-testid=pdf]').textContent, 'PDF page 2');
  let text = container.querySelector('textarea');
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(text, 'an apple');
    text.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
  assert.equal(JSON.parse(localStorage.getItem(topicKey)).answers[0][0], 'an apple');
  assert.equal(button('AI bilan tekshirish').disabled, true);
  const labels = [...container.querySelectorAll('label')];
  const consent = labels.find((l) => l.textContent.includes('ushbu mashq javoblarim')).querySelector('input');
  await click(consent);
  await click(button('AI bilan tekshirish'));
  assert.deepEqual(calls[0].body.page_numbers, [1, 2]);
  assert.equal(calls[0].body.consent_to_provider, true);
  assert.equal(calls[0].body.questions[0].answer, 'an apple');
  assert.match(container.textContent, /AI: to'g'ri/);
  assert.match(container.textContent, /To'g'ri: 1 · Xato: 0 · Noaniq: 0 · Javob berilmagan: 0/);
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(text, 'a apple');
    text.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
  assert.doesNotMatch(container.textContent, /AI: to'g'ri/);
  assert.equal(container.querySelector('[aria-label="Mashq natijasi"]'), null);
  await act(async () => root.unmount());
  root = createRoot(container);
  await act(async () => root.render(React.createElement(VisionMapPreview, { bookId: 'book', pageCount: 2 })));
  assert.equal(container.querySelector('textarea').value, 'a apple');
  assert.equal(button('AI bilan tekshirish').disabled, true); // consent is not remembered
  const newConsent = [...container.querySelectorAll('label')].find((l) => l.textContent.includes('ushbu mashq javoblarim')).querySelector('input');
  await click(newConsent);
  fail = true;
  await click(button('AI bilan tekshirish'));
  assert.match(container.textContent, /Provayder ishlamadi/);
  assert.equal(JSON.parse(localStorage.getItem(topicKey)).answers[0][0], 'a apple');
  window.confirm = () => true;
  await click(button("mahalliy ma'lumotlarini o'chirish"));
  assert.equal(localStorage.getItem(topicKey), null);
  assert.equal(container.querySelector('textarea'), null);
  await act(async () => root.unmount());
  identity = 'user2'; root = createRoot(container);
  await act(async () => root.render(React.createElement(VisionMapPreview, { bookId: 'book', pageCount: 2 })));
  assert.equal(container.querySelector('textarea'), null);
  await act(async () => root.unmount());
  // Count answered correct/wrong/uncertain separately from an unanswered item.
  fail = false;
  response = { verdicts: [true, false, null, false].map((correct, index) => ({ index, correct, explanation_uz: '' })) };
  const exercise = { ...result.exercises[0], questions: Array.from({ length: 4 }, (_, i) => ({ number: String(i + 1), prompt: '', options: [], evidence_pages: [2] })) };
  function SummaryHarness() {
    const [values, setValues] = React.useState(['one', 'two', 'three', '']);
    return React.createElement(preview.PreviewExercise, { bookId: 'book', ex: exercise, pages: [1, 2], answers: values, onChange: setValues });
  }
  root = createRoot(container);
  await act(async () => root.render(React.createElement(SummaryHarness)));
  assert.equal(container.querySelector('[aria-label="Mashq natijasi"]'), null);
  await click([...container.querySelectorAll('label')].find((l) => l.textContent.includes('ushbu mashq javoblarim')).querySelector('input'));
  await click(button('AI bilan tekshirish'));
  const summary = container.querySelector('[aria-label="Mashq natijasi"]');
  assert.match(summary.textContent, /To'g'ri: 1 · Xato: 1 · Noaniq: 1 · Javob berilmagan: 1/);
  assert.match(summary.textContent, /Jami: 4 ta savol/);
  assert.match(container.textContent, /Javob kiritilmagan/);
  await act(async () => root.unmount());
  console.log('Vision preview local persistence, image viewer, consent, feedback and summary smoke tests passed');
}
main().catch((e) => { console.error(e); process.exitCode = 1; });
