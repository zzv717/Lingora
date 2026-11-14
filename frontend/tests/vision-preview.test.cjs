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
let topicResponse;
const mockApi = { getAccessToken: () => 'test-token', post: async (url, body) => { calls.push({ url, body }); if (fail) throw new Error('Provayder ishlamadi'); return url === '/tutor/translate' ? { translation: 'Olma' } : url.endsWith('/vision-topic/preview') ? topicResponse : response; } };
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
const translator = load('src/components/reader/translator.tsx');
const pictureHelpers = load('src/components/reader/pdf-picture-crops.ts', { '@/lib/timeout': { withTimeout: (p) => p } });
const mockPictures = { validPicture: pictureHelpers.validPicture, usePdfPictureCrops: (_book, questions, pages) => ({ pictures: Object.fromEntries(questions.flatMap((q, i) => pictureHelpers.validPicture(q, pages) ? [[i, 'data:image/png;base64,abc']] : [])), error: '' }) };
const preview = load('src/components/reader/preview-exercise.tsx', { './translator': translator, './pdf-picture-crops': mockPictures });
const mergePictures = load('src/components/reader/merge-picture-regions.ts', { './pdf-picture-crops': mockPictures });
const { VisionMapPreview } = load('src/components/reader/vision-map-preview.tsx', { './preview-exercise': preview, './merge-picture-regions': mergePictures });
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
  assert.equal(container.querySelector('[data-testid=pdf]').textContent, 'PDF page 2');
  await click(button('PDF ni yashirish'));
  assert.equal(container.querySelector('[data-testid=pdf]'), null);
  await click(button("Asl sahifada ko'rish"));
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
  topicResponse = JSON.parse(JSON.stringify(result));
  topicResponse.exercises[0].questions[0].picture = { page: 2, bbox: [100, 100, 300, 300] };
  assert.equal(button('Rasm joylarini aniqlash').disabled, true);
  await click([...container.querySelectorAll('label')].find((l) => l.textContent.includes('sahifalarni tashqi AI xizmatiga qayta')).querySelector('input'));
  await click(button('Rasm joylarini aniqlash'));
  const saved = JSON.parse(localStorage.getItem(topicKey));
  assert.equal(saved.answers[0][0], 'a apple');
  assert.deepEqual(saved.result.exercises[0].questions[0].picture, { page: 2, bbox: [100, 100, 300, 300] });
  assert.equal(calls.at(-1).url, '/books/book/vision-topic/preview');
  assert.deepEqual(calls.at(-1).body.page_numbers, [1, 2]);
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
  assert.equal(container.querySelector('[role=progressbar]').getAttribute('aria-valuenow'), '3');
  await click(button("Ko'rsatmani tarjima qilish"));
  const translatorInput = [...container.querySelectorAll('textarea')][0];
  assert.equal(translatorInput.value, 'Look');
  assert.equal(button('Tarjima qilish').disabled, true);
  const translationConsent = [...container.querySelectorAll('label')].find((l) => l.textContent.includes('Faqat yuqoridagi matn')).querySelector('input');
  await click(translationConsent);
  await click(button('Tarjima qilish'));
  assert.equal(calls.at(-1).url, '/tutor/translate');
  assert.equal(calls.at(-1).body.text, 'Look');
  assert.equal(calls.at(-1).body.direction, 'en-uz');
  assert.equal(calls.at(-1).body.consent_text_to_provider, true);
  assert.match(container.textContent, /Olma/);
  assert.equal(container.querySelector('[aria-label="Mashq natijasi"]').textContent.includes("To'g'ri: 1"), true);
  await click(container.querySelector('[aria-label="Tarjima yo\'nalishini almashtirish"]'));
  assert.doesNotMatch(container.textContent, /Olma/);
  await click(button('Tarjima qilish'));
  assert.equal(calls.at(-1).body.direction, 'uz-en');
  await act(async () => root.unmount());
  function ChoiceHarness() {
    const [values, setValues] = React.useState(['']);
    return React.createElement(preview.PreviewExercise, { bookId: 'book', ex: { ...exercise, exercise_type: 'multiple_choice', questions: [{ number: '1', prompt: 'Choose', options: ['A) apple', 'B) orange'], evidence_pages: [2] }] }, pages: [2], answers: values, onChange: setValues });
  }
  root = createRoot(container);
  await act(async () => root.render(React.createElement(ChoiceHarness)));
  await click(button('B) orange'));
  assert.equal(container.querySelector('textarea').value, 'B) orange');
  assert.equal(button('B) orange').getAttribute('aria-pressed'), 'true');
  assert.equal(container.querySelector('[role=progressbar]').getAttribute('aria-valuenow'), '1');
  await act(async () => root.unmount());
  const question = { number: '2', prompt: '...', options: [], evidence_pages: [2], picture: { page: 2, bbox: [100, 100, 300, 300] } };
  const oldEx = { ...exercise, questions: [{ ...question, picture: null }] };
  const newEx = { ...oldEx, questions: [question] };
  const merged = mergePictures.mergePictureRegions([oldEx], [newEx], [1, 2]);
  assert.equal(merged.added, 1);
  assert.equal(merged.exercises[0].questions[0].picture.page, 2);
  assert.equal(oldEx.questions[0].picture, null);
  assert.equal(mergePictures.mergePictureRegions([oldEx, oldEx], [newEx], [1, 2]).added, 0);
  assert.equal(mergePictures.mergePictureRegions([oldEx], [{ ...newEx, instruction: 'Different' }], [1, 2]).added, 0);
  assert.equal(mergePictures.mergePictureRegions([oldEx], [{ ...newEx, questions: [question, question] }], [1, 2]).added, 0);
  assert.ok(pictureHelpers.validPicture(question, [1, 2]));
  for (const picture of [{ page: 1, bbox: [100, 100, 300, 300] }, { page: 2, bbox: [300, 100, 100, 300] }, { page: 2, bbox: [0, 0, 1001, 10] }, { page: 2, bbox: [0, 0, NaN, 10] }]) {
    assert.equal(pictureHelpers.validPicture({ ...question, picture }, [1, 2]), null);
  }
  root = createRoot(container);
  await act(async () => root.render(React.createElement(preview.PreviewExercise, { bookId: 'book', ex: { ...exercise, instruction: 'Look at the pictures', questions: [question, { ...question, number: '3', picture: null }] }, pages: [1, 2], answers: ['', ''], onChange: () => {}, defaultShowPage: true })));
  assert.equal(container.querySelector('[data-testid=pdf]').textContent, 'PDF page 2');
  assert.equal(container.querySelectorAll('figure img').length, 1);
  assert.match(container.querySelector('figure img').getAttribute('alt'), /2-savol/);
  assert.match(container.textContent, /alohida rasm joyi aniqlanmagan/);
  await act(async () => root.unmount());
  // Exercise the real PDF crop hook with mocked PDF.js and canvas: coordinates are from the original page.
  const draws = []; let pdfLoads = 0;
  window.HTMLCanvasElement.prototype.getContext = function () { return { drawImage: (...args) => draws.push(args) }; };
  window.HTMLCanvasElement.prototype.toDataURL = () => 'data:image/png;base64,real-crop';
  const fakePdf = { GlobalWorkerOptions: {}, getDocument: (opts) => {
    pdfLoads++; assert.equal(opts.httpHeaders.authorization, 'Bearer test-token');
    return { promise: Promise.resolve({ numPages: 2, getPage: async (n) => {
      assert.equal(n, 2);
      return { getViewport: ({ scale }) => ({ width: 600 * scale, height: 800 * scale }), render: () => ({ promise: Promise.resolve(), cancel() {} }) };
    } }), destroy: async () => {} };
  } };
  const realPictures = load('src/components/reader/pdf-picture-crops.ts', { '@/lib/timeout': { withTimeout: (p) => p }, 'pdfjs-dist': fakePdf });
  function CropHarness({ q }) { const state = realPictures.usePdfPictureCrops('book', [q], [1, 2]); return React.createElement('div', null, state.pictures[0] || state.error); }
  root = createRoot(container);
  await act(async () => { root.render(React.createElement(CropHarness, { q: question })); await new Promise((resolve) => setTimeout(resolve, 20)); });
  assert.match(container.textContent, /real-crop/);
  assert.equal(pdfLoads, 1);
  assert.deepEqual(draws[0].slice(1), [120, 160, 240, 320, 0, 0, 240, 320]);
  await act(async () => root.unmount());
  console.log('Vision preview local persistence, image viewer, consent, feedback, summary, translator, choice and picture smoke tests passed');
}
main().catch((e) => { console.error(e); process.exitCode = 1; });
