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
let fail = false, pictureFail = false;
let response = { verdicts: [{ index: 0, correct: true, explanation_uz: 'Izoh' }] };
let topicResponse;
let pictureResponse = { locations: [{ index: 0, picture: { page: 2, bbox: [100, 100, 300, 300] } }] };
const mockApi = { getAccessToken: () => 'test-token', post: async (url, body) => { calls.push({ url, body }); if (fail || (pictureFail && url.endsWith('/vision-topic/pictures'))) throw new Error('Provayder ishlamadi'); return url === '/tutor/translate' ? { translation: 'Olma' } : url.endsWith('/vision-topic/preview') ? topicResponse : url.endsWith('/vision-topic/pictures') ? pictureResponse : response; } };
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
const selector = { PictureSelector: ({ onSave }) => React.createElement('button', { onClick: () => onSave({ page: 1, bbox: [20, 30, 200, 300] }) }, 'Mock crop save') };
const autoPictures = load('src/components/reader/auto-picture-locations.ts', { './pdf-picture-crops': mockPictures });
const preview = load('src/components/reader/preview-exercise.tsx', { './translator': translator, './pdf-picture-crops': mockPictures, './picture-selector': selector, './auto-picture-locations': autoPictures });
const { VisionMapPreview } = load('src/components/reader/vision-map-preview.tsx', { './preview-exercise': preview, './pdf-picture-crops': mockPictures, './auto-picture-locations': autoPictures });
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
  assert.equal(button('Rasmlarni avtomatik topish').disabled, true);
  assert.equal(calls.filter((c) => c.url.endsWith('/pictures')).length, 0); // restored previews do not send pages without consent
  await click([...container.querySelectorAll('label')].find((l) => l.textContent.includes('mashq matnlarini tashqi AI xizmatiga qayta')).querySelector('input'));
  pictureFail = true;
  await click(button('Rasmlarni avtomatik topish'));
  assert.match(container.textContent, /Rasm qidirish to'xtadi/);
  assert.equal(JSON.parse(localStorage.getItem(topicKey)).answers[0][0], 'a apple');
  pictureFail = false;
  await click(button('Rasmlarni avtomatik topish'));
  const saved = JSON.parse(localStorage.getItem(topicKey));
  assert.equal(saved.answers[0][0], 'a apple');
  assert.deepEqual(saved.result.exercises[0].questions[0].picture, { page: 2, bbox: [100, 100, 300, 300] });
  assert.equal(calls.at(-1).url, '/books/book/vision-topic/pictures');
  assert.deepEqual(calls.at(-1).body.page_numbers, [1, 2]);
  assert.equal(calls.at(-1).body.questions[0].answer, undefined);
  await click(button("Rasmni o'zgartirish"));
  await click(button('Mock crop save'));
  const manuallySaved = JSON.parse(localStorage.getItem(topicKey));
  assert.equal(manuallySaved.answers[0][0], 'a apple');
  assert.deepEqual(manuallySaved.result.exercises[0].questions[0].picture, { page: 1, bbox: [20, 30, 200, 300] });
  assert.deepEqual(manuallySaved.result.exercises[0].questions[0].evidence_pages, [2, 1]);
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
  // A fresh consented scan performs the dedicated number-to-picture pass automatically.
  identity = 'scan-user';
  localStorage.setItem('lingora.vision-map.scan-user.book', localStorage.getItem('lingora.vision-map.user1.book'));
  topicResponse = JSON.parse(JSON.stringify(result));
  pictureResponse = { locations: [{ index: 0, picture: { page: 2, bbox: [100, 100, 300, 300] } }] };
  fail = false; root = createRoot(container);
  await act(async () => root.render(React.createElement(VisionMapPreview, { bookId: 'book', pageCount: 2 })));
  const topicInput = [...container.querySelectorAll('label')].find((l) => l.textContent.includes('Mavzu PDF sahifalari')).querySelector('input');
  await act(async () => { Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(topicInput, '1, 2'); topicInput.dispatchEvent(new window.Event('input', { bubbles: true })); });
  assert.equal(button('Mavzu sahifalarini sinash').disabled, true);
  await click([...container.querySelectorAll('label')].find((l) => l.textContent.includes('ko\'pi bilan 5 qo\'shimcha')).querySelector('input'));
  const callsBeforeScan = calls.length;
  await click(button('Mavzu sahifalarini sinash'));
  assert.deepEqual(calls.slice(callsBeforeScan).map((c) => c.url), ['/books/book/vision-topic/preview', '/books/book/vision-topic/pictures']);
  assert.equal(container.querySelectorAll('figure img').length, 1);
  assert.match(container.textContent, /1 ta rasm topildi/);
  assert.equal(calls.at(-1).body.questions[0].answer, undefined);
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
  assert.ok(pictureHelpers.validPicture(question, [1, 2]));
  for (const picture of [{ page: 1, bbox: [100, 100, 300, 300] }, { page: 2, bbox: [300, 100, 100, 300] }, { page: 2, bbox: [0, 0, 1001, 10] }, { page: 2, bbox: [0, 0, NaN, 10] }]) {
    assert.equal(pictureHelpers.validPicture({ ...question, picture }, [1, 2]), null);
  }
  root = createRoot(container);
  await act(async () => root.render(React.createElement(preview.PreviewExercise, { bookId: 'book', ex: { ...exercise, instruction: 'Look at the pictures', questions: [question, { ...question, number: '3', picture: null }] }, pages: [1, 2], answers: ['', ''], onChange: () => {}, defaultShowPage: true })));
  assert.equal(container.querySelector('[data-testid=pdf]').textContent, 'PDF page 2');
  assert.equal(container.querySelectorAll('figure img').length, 1);
  assert.match(container.querySelector('figure img').getAttribute('alt'), /2-savol/);
  assert.ok(!container.querySelector('figure').className.includes('border'));
  assert.doesNotMatch(container.textContent, /alohida rasm joyi aniqlanmagan/);
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
  const realSelector = load('src/components/reader/picture-selector.tsx', { '@/lib/timeout': { withTimeout: (p) => p }, 'pdfjs-dist': fakePdf });
  assert.deepEqual(realSelector.selectionBox({ x: 400, y: 300 }, { x: 100, y: 50 }), [100, 50, 400, 300]);
  assert.equal(realSelector.selectionBox({ x: 100, y: 100 }, { x: 102, y: 102 }), null);
  let selected = null;
  root = createRoot(container);
  await act(async () => { root.render(React.createElement(realSelector.PictureSelector, { bookId: 'book', pages: [2], initialPage: 2, onSave: (r) => { selected = r; }, onCancel: () => {} })); await new Promise((resolve) => setTimeout(resolve, 20)); });
  const area = container.querySelector('canvas').parentElement;
  area.getBoundingClientRect = () => ({ left: 10, top: 20, width: 200, height: 400 });
  area.setPointerCapture = () => {};
  const pointer = (type, x, y) => { const e = new window.Event(type, { bubbles: true }); Object.assign(e, { clientX: x, clientY: y, pointerId: 1 }); area.dispatchEvent(e); };
  await act(async () => { pointer('pointerdown', 30, 60); pointer('pointerup', 110, 220); });
  assert.equal(button("Rasmni qo'shish").disabled, false);
  await click(button("Rasmni qo'shish"));
  assert.deepEqual(selected, { page: 2, bbox: [100, 100, 500, 500] });
  await act(async () => root.unmount());
  // Bounded pass, no overwrites, duplicate/out-of-scope rejection, cancellation and provider failure.
  const baseQ = { number: '1', prompt: '...', options: [], evidence_pages: [2] };
  const makeEx = (i) => ({ ...exercise, number: String(i), questions: [baseQ] });
  const many = { sampled_pages: [1, 2], exercises: Array.from({ length: 7 }, (_, i) => makeEx(i)) };
  pictureResponse = { locations: [{ index: 0, picture: { page: 2, bbox: [10, 10, 50, 50] } }] };
  let progress = 0, before = calls.length;
  let outcome = await autoPictures.autoLocatePictures('book', many, { isCurrent: () => true, onUpdate: () => progress++ });
  assert.equal(calls.length - before, 5); assert.equal(outcome.added, 5); assert.equal(outcome.remaining, 2); assert.equal(progress, 5);
  assert.equal(many.exercises[0].questions[0].picture, undefined);
  const manualPicture = { page: 2, bbox: [100, 100, 200, 200] };
  const partial = { sampled_pages: [1, 2], exercises: [{ ...makeEx(1), questions: [{ ...baseQ, picture: manualPicture }, { ...baseQ, number: '2' }] }] };
  pictureResponse = { locations: [{ index: 0, picture: { page: 2, bbox: [10, 10, 50, 50] } }, { index: 1, picture: { page: 2, bbox: [20, 20, 60, 60] } }] };
  outcome = await autoPictures.autoLocatePictures('book', partial, { isCurrent: () => true, onUpdate: () => {} });
  assert.deepEqual(outcome.result.exercises[0].questions[0].picture, manualPicture);
  assert.deepEqual(outcome.result.exercises[0].questions[1].picture.bbox, [20, 20, 60, 60]);
  pictureResponse = { locations: [{ index: 0, picture: { page: 1, bbox: [10, 10, 50, 50] } }, { index: 0, picture: { page: 2, bbox: [10, 10, 50, 50] } }] };
  outcome = await autoPictures.autoLocatePictures('book', { ...many, exercises: [makeEx(1)] }, { isCurrent: () => true, onUpdate: () => {} });
  assert.equal(outcome.added, 0);
  before = calls.length;
  outcome = await autoPictures.autoLocatePictures('book', many, { isCurrent: () => false, onUpdate: () => { throw Error('cancelled'); } });
  assert.equal(calls.length, before); assert.equal(outcome.cancelled, true);
  fail = true; before = calls.length;
  outcome = await autoPictures.autoLocatePictures('book', many, { isCurrent: () => true, onUpdate: () => {} });
  assert.equal(calls.length - before, 1); assert.equal(outcome.failed, true); assert.equal(outcome.remaining, 6);
  assert.equal(autoPictures.isPictureExercise({ ...makeEx(1), instruction: 'Write', depends_on_picture: true, questions: [{ ...baseQ, prompt: 'A sentence' }] }, [2]), true);
  console.log('Vision preview local persistence, consent, automatic localization, feedback, translator and picture selection smoke tests passed');
}
main().catch((e) => { console.error(e); process.exitCode = 1; });
