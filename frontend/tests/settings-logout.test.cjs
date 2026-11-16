// Settings logout smoke test using the real AuthProvider with a mocked API.
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
let profileFails = false, logoutFails = false;
const redirects = [], requests = [];
const me = { id: 'u1', email: 'test@example.com', full_name: 'Test' };
const profile = { daily_goal_minutes: 20, vocab_pass_score: 80, vocabulary_gating: true };
const api = {
  getAccessToken: () => localStorage.getItem('lingora.access'),
  clearTokens: () => { localStorage.removeItem('lingora.access'); localStorage.removeItem('lingora.refresh'); },
  storeTokens: () => {}, ApiErr: class extends Error {},
  api: async (path) => path === '/auth/me' ? me : profile,
  get: async (path) => { if (profileFails && path === '/auth/me/profile') throw Error('offline'); return path === '/auth/me/profile' ? profile : path === '/me/plan' ? { plan: 'free', max_books: 3, ai_calls_per_day: 0, ai_calls_today: 0, ai_configured: true } : me; },
  post: async (path, body) => { requests.push({ path, body }); if (logoutFails && path === '/auth/logout') throw Error('offline'); return {}; },
  del: async () => { throw Error('account deletion must not run'); }, patch: async () => {},
};
const ui = {
  Button: ({ children, variant, size, loading, ...props }) => React.createElement('button', { ...props, disabled: loading || props.disabled }, children),
  Card: ({ children }) => React.createElement('section', null, children),
  Badge: ({ children }) => React.createElement('span', null, children),
  Input: ({ label, ...props }) => React.createElement('label', null, label, React.createElement('input', props)),
  Modal: ({ open, children }) => open ? React.createElement('div', null, children) : null,
  Spinner: () => React.createElement('span', null, 'loading'),
  useToast: () => ({ toast: () => {} }),
};
function load(file, extra = {}) {
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const module = { exports: {} };
  const mocked = (name) => {
    if (name === './api' || name === '@/lib/api') return api;
    if (name === '@/components/ui') return ui;
    if (name === '@/components/nav') return { TopBar: () => React.createElement('header', null, 'Sozlamalar') };
    if (name === '@/lib/theme') return { useTheme: () => ({ theme: 'dark', setTheme: () => {} }) };
    if (name === 'next/navigation') return { useRouter: () => ({ replace: (path) => redirects.push(path) }) };
    if (extra[name]) return extra[name];
    return require(name);
  };
  vm.runInThisContext(`(function(require,module,exports){${code}\n})`, { filename: file })(mocked, module, module.exports);
  return module.exports;
}
const auth = load('src/lib/auth.tsx');
const Settings = load('src/app/(app)/settings/page.tsx', { '@/lib/auth': auth }).default;
const container = document.getElementById('root');
async function mount() {
  localStorage.setItem('lingora.access', 'access'); localStorage.setItem('lingora.refresh', 'refresh');
  localStorage.setItem('lingora.vision-topic.u1.book', 'saved answers');
  const root = createRoot(container);
  await act(async () => { root.render(React.createElement(auth.AuthProvider, null, React.createElement(Settings))); await new Promise((resolve) => setTimeout(resolve, 0)); });
  return root;
}
async function main() {
  let root = await mount();
  assert.match(container.textContent, /Profil/);
  const logout = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Hisobdan chiqish');
  assert.ok(logout);
  await act(async () => logout.click());
  assert.deepEqual(requests.at(-1), { path: '/auth/logout', body: { refresh_token: 'refresh' } });
  assert.equal(localStorage.getItem('lingora.access'), null);
  assert.equal(localStorage.getItem('lingora.refresh'), null);
  assert.equal(localStorage.getItem('lingora.vision-topic.u1.book'), 'saved answers');
  assert.equal(redirects.at(-1), '/login');
  await act(async () => root.unmount());
  // If profile loading or the logout network request fails, local logout remains accessible.
  profileFails = true; logoutFails = true;
  root = await mount();
  assert.match(container.textContent, /loading/);
  const offlineLogout = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Hisobdan chiqish');
  assert.ok(offlineLogout);
  await act(async () => offlineLogout.click());
  assert.equal(localStorage.getItem('lingora.access'), null);
  assert.equal(localStorage.getItem('lingora.refresh'), null);
  assert.equal(localStorage.getItem('lingora.vision-topic.u1.book'), 'saved answers');
  assert.equal(redirects.at(-1), '/login');
  await act(async () => root.unmount());
  // Even without a local refresh token, call logout so the server can revoke its cookie.
  profileFails = false; logoutFails = false;
  root = await mount();
  localStorage.removeItem('lingora.refresh');
  const cookieLogout = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Hisobdan chiqish');
  await act(async () => cookieLogout.click());
  assert.deepEqual(requests.at(-1), { path: '/auth/logout', body: {} });
  assert.equal(localStorage.getItem('lingora.access'), null);
  await act(async () => root.unmount());
  console.log('Settings logout, offline fallback and saved-answer preservation tests passed');
}
main().catch((e) => { console.error(e); process.exitCode = 1; });
