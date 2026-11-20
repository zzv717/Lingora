// Vocabulary illustration smoke test: authenticated PNG crop, zoom view, failure state.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const { JSDOM } = require('jsdom');
const dom = new JSDOM('<div id="root"></div>', { url: 'https://example.test' });
global.window = dom.window; global.document = dom.window.document; global.navigator = dom.window.navigator;
global.IS_REACT_ACT_ENVIRONMENT = true;
// jsdom has no object URLs; the component only needs a stable string.
const created = [];
global.URL.createObjectURL = () => { const url = `blob:test/${created.length}`; created.push(url); return url; };
global.URL.revokeObjectURL = () => {};
const React = require('react');
const { createRoot } = require('react-dom/client');
const { act } = require('react-dom/test-utils');

const requests = [];
let status = 200;
global.fetch = async (url, options) => {
  requests.push({ url: String(url), options });
  if (status !== 200) return { ok: false, status };
  return { ok: true, status, blob: async () => new global.Blob(['png'], { type: 'image/png' }) };
};

function load(file, extra) {
  const source = fs.readFileSync(file, 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const module = { exports: {} };
  function mocked(name) {
    if (name === '@/lib/api') return { getAccessToken: () => 'test-token' };
    if (extra && extra[name]) return extra[name];
    return require(name);
  }
  vm.runInThisContext(`(function(require,module,exports){${code}\n})`, { filename: file })(mocked, module, module.exports);
  return module.exports;
}

const { VocabPicture } = load('src/components/reader/vocab-picture.tsx');
const container = document.getElementById('root');
const buttons = () => Array.from(container.querySelectorAll('button'));

async function main() {
  const root = createRoot(container);
  await act(async () => root.render(React.createElement(VocabPicture, { bookId: 'book', wordId: 'word', term: 'afraid' })));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

  // The crop is fetched from the authenticated endpoint at high resolution, not inline images.
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/backend/api/v1/books/book/vocabulary/word/picture.png?max_edge=1400');
  assert.equal(requests[0].options.headers.authorization, 'Bearer test-token');
  const image = container.querySelector('img');
  assert.ok(image, 'picture should render');
  assert.match(image.alt, /afraid/);
  assert.equal(image.getAttribute('width'), '1400');

  // Clicking opens the full-size view; Escape closes it.
  await act(async () => buttons()[0].click());
  assert.ok(container.querySelector('[role=dialog]'));
  await act(async () => { window.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape' })); });
  assert.equal(container.querySelector('[role=dialog]'), null);

  // A missing illustration is reported, never replaced with a placeholder image.
  status = 404;
  await act(async () => root.render(React.createElement(VocabPicture, { bookId: 'book', wordId: 'other', term: 'agree' })));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  assert.equal(container.querySelector('img'), null);
  assert.match(container.textContent, /Rasmni yuklab bo'lmadi/);

  await act(async () => root.unmount());
  console.log('Vocabulary picture fetch, zoom and error-state tests passed');
}
main().catch((error) => { console.error(error); process.exit(1); });
