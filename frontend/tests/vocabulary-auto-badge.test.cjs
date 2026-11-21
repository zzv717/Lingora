// Lug'at screen, rendered for real in jsdom: unit 6 words come back with an "auto" badge.
//
// The screenshot path is unavailable in this sandbox (no browser binary can be downloaded),
// so the screen is rendered through React with the API mocked at the fetch boundary. That
// still proves the exact thing that was reported: a machine-translated word shows the AI
// badge, not the red "Tarjima yo'q".
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const { JSDOM } = require('jsdom');

const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'https://example.test' });
global.window = dom.window;
global.document = dom.window.document;
global.navigator = dom.window.navigator;
global.IS_REACT_ACT_ENVIRONMENT = true;
global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
global.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
global.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
global.requestAnimationFrame = (cb) => setTimeout(cb, 0);

const React = require('react');
const { createRoot } = require('react-dom/client');
const { act } = require('react-dom/test-utils');

// ---- the API, as the seeded backend answers it ----
const WORDS = [
  ['advantage', 'noun', 'An advantage is something that helps you.', 'afzallik', 'auto', false],
  ['cause', 'verb', 'To cause is to make something happen.', "sabab bo'lmoq", 'auto', false],
  ['choice', 'noun', 'A choice is a decision between two or more things.', 'tanlov', 'auto', false],
  ['community', 'noun', 'A community is a group of people who live together.', 'jamoa', 'auto', false],
  ['dead', 'adjective', 'When someone is dead, they are not alive.', "o'lgan", 'auto', false],
  ['distance', 'noun', 'Distance is the amount of space between two things.', 'masofa', 'auto', false],
  ['escape', 'verb', 'To escape is to get away from a place.', 'qochib qutulmoq', 'auto', false],
  ['face', 'verb', 'To face something is to deal with it.', 'yuzlanmoq', 'auto', false],
  ['follow', 'verb', 'To follow is to go after someone.', 'ergashmoq', 'auto', false],
  ['fright', 'noun', 'Fright is a feeling of being scared.', '', '', true],
];

const responses = {
  '/books': [{ id: 'book-1', title: '4000 Essential English Words 1', status: 'ready', page_count: 44 }],
  '/vocabulary/stats': { learning: 0, mastered: 0, due: 0, total: 10 },
  '/books/book-1/structure': { book_id: 'book-1', chapters: [], lessons: [], lessons_progress: {}, coverage: { pages_needing_ocr: 0 } },
  '/books/book-1/vocabulary': [],
  '/books/book-1/status': null,
  '/books/book-1/vocabulary/units': {
    book_id: 'book-1', total: 10, translated: 9, untranslated: 1, auto_translated: 9,
    vocabulary_note_uz: '',
    units: [{
      id: 'unit-6', unit: 6, number: 6, title: 'Choices', unit_title: 'Choices', lesson_id: null,
      page_start: 39, page_end: 44, confidence: 0.93, count: 10, translated_count: 9, auto_count: 9,
      entries: WORDS.map(([word, pos, definition, translation, status, needs], i) => ({
        id: `w-${i}`, word, part_of_speech: pos, definition, example: `The ${word} mattered.`,
        translation_uz: translation, alt_translations: [], translation_status: status,
        status, needs_translation: needs, unit_id: 'unit-6', position: i + 1, page: 39,
        source: 'vision', picture_page: null, picture_bbox: null,
      })),
    }],
  },
};

const calls = [];
global.fetch = async (url, options = {}) => {
  const path = String(url).replace('/backend/api/v1', '');
  calls.push(path);
  const body = responses[path] ?? [];
  return {
    ok: true, status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
    headers: { get: () => 'application/json' },
  };
};

let ui = null;

function load(file, extra = {}) {
  const source = fs.readFileSync(file, 'utf8');
  const code = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const module = { exports: {} };
  function mocked(name) {
    if (name === 'next/link') {
      return function Link({ href, children, ...rest }) { return React.createElement('a', { href, ...rest }, children); };
    }
    if (name === 'next/navigation') return { useRouter: () => ({ push() {}, replace() {} }), usePathname: () => '/vocabulary' };
    if (name === '@/components/nav') return { TopBar: ({ title }) => React.createElement('header', null, title) };
    if (name === '@/components/reader/vocab-picture') return { VocabPicture: () => null };
    if (name === '@/components/reader/vision-vocabulary') return { VisionVocabulary: () => null };
    if (name === "@/lib/api") {
      // The real client is tiny; it is re-implemented here so the screen runs unmodified.
      const call = (method) => async (path, data) => {
        const response = await global.fetch(`/backend/api/v1${path}`, {
          method, body: data === undefined ? undefined : JSON.stringify(data),
        });
        return response.json();
      };
      return { get: call("GET"), post: call("POST"), patch: call("PATCH"), del: call("DELETE"),
               ApiErr: class ApiErr extends Error {} };
    }
    if (name === "@/lib/types") return {};
    if (name === "@/components/ui") return ui;
    if (extra[name]) return extra[name];
    return require(name);
  }
  vm.runInThisContext(`(function(require,module,exports){${code}\n})`, { filename: file })(mocked, module, module.exports);
  return module.exports;
}

// The toast context is part of the UI kit; rendering the screen needs its provider.
ui = load("src/components/ui.tsx");
const { ToastProvider } = ui;
const { default: VocabularyPage } = load('src/app/(app)/vocabulary/page.tsx');

(async () => {
  const container = dom.window.document.getElementById('root');
  const root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(ToastProvider, null, React.createElement(VocabularyPage)));
  });
  // Let the fetches resolve, then open the unit (sections start collapsed).
  await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
  const toggles = [...container.querySelectorAll('button[aria-expanded="false"]')];
  assert.ok(toggles.length, 'the unit section must render collapsed');
  await act(async () => { toggles[0].dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })); });
  await act(async () => { await new Promise((r) => setTimeout(r, 50)); });

  const text = container.textContent;
  assert.match(text, /6-unit · Choices/, 'the unit heading shows the number and the real title');
  assert.match(text, /39-44 bet/, 'the page range is the unit range, not a single page');
  assert.match(text, /9 tarjima qilingan/);
  assert.match(text, /afzallik/, 'a machine translation is displayed');
  assert.match(text, /qochib qutulmoq/);
  // 9 words carry the AI badge, and only the one without any translation is red.
  const badges = [...container.querySelectorAll('span')].filter((s) => s.textContent === 'auto');
  assert.equal(badges.length, 9, `expected 9 "auto" badges, got ${badges.length}`);
  const red = [...container.querySelectorAll('span')].filter((s) => (s.textContent || '').includes("Tarjima yo'q"));
  assert.equal(red.length, 1, `only the untranslated word may be red, got ${red.length}`);
  assert.doesNotMatch(text, /Tarjima tekshirilmagan/, 'the old "not in tests" sentence is gone');
  // The header must agree with what is on screen.
  assert.match(text, /10 ta so'z · 9 tasi o'zbekchada · 1 tasi tarjimasiz/);
  assert.match(text, /Tarjimasiz so'zlarni tarjima qilish \(1\)/);

  console.log('Vocabulary screen: 9 "auto" badges, 1 red word, unit 6 title and range correct');
  console.log('API calls:', calls.filter((c) => c.includes('units') || c === '/books').join(', '));
  process.exit(0);
})().catch((error) => { console.error(error); process.exit(1); });
