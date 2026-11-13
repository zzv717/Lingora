// Run after `npm run build`. The backend URL is supplied only when Next starts,
// so this also catches accidentally baking the URL into the production build.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import http from "node:http";
import { once } from "node:events";

const backend = http.createServer(async (req, res) => {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (req.url === "/api/v1/auth/login" && req.method === "POST") {
    assert.deepEqual(JSON.parse(Buffer.concat(chunks)), { email: "ali@example.com", password: "Parol12345" });
    res.writeHead(200, { "content-type": "application/json", "set-cookie": "lingora_refresh=token; HttpOnly; Path=/" });
    res.end(JSON.stringify({ access_token: "access", refresh_token: "refresh" }));
  } else if (req.url === "/api/v1/books/1/file?download=true" && req.headers.range === "bytes=0-3") {
    res.writeHead(206, { "content-type": "application/pdf", "content-range": "bytes 0-3/8" });
    res.end("%PDF");
  } else if (req.url === "/api/v1/auth/me" && req.headers.authorization === "Bearer access") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ email: "ali@example.com" }));
  } else if (req.url === "/api/v1/missing") {
    res.writeHead(404, { "content-type": "application/json" });
    res.end('{"detail":"Not Found"}');
  } else {
    res.writeHead(500);
    res.end(`Unexpected upstream request: ${req.method} ${req.url}`);
  }
});
backend.listen(0, "127.0.0.1");
await once(backend, "listening");
const backendPort = backend.address().port;
const frontend = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "-H", "127.0.0.1", "-p", "0"], {
  env: { ...process.env, BACKEND_URL: `http://127.0.0.1:${backendPort}/`, NEXT_TELEMETRY_DISABLED: "1" },
  stdio: ["ignore", "pipe", "pipe"],
});
let output = "";
frontend.stderr.on("data", (chunk) => { output += chunk; });
try {
  const port = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Next did not start: ${output}`)), 30000);
    frontend.on("exit", (code) => reject(new Error(`Next exited (${code}): ${output}`)));
    frontend.stdout.on("data", (chunk) => {
      output += chunk;
      const match = output.match(/127\.0\.0\.1:(\d+)/);
      if (match && output.includes("Ready")) { clearTimeout(timer); resolve(Number(match[1])); }
    });
  });
  const base = `http://127.0.0.1:${port}`;
  assert.equal((await fetch(`${base}/login`)).status, 200);
  const login = await fetch(`${base}/backend/api/v1/auth/login`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: "ali@example.com", password: "Parol12345" }),
  });
  assert.equal(login.status, 200);
  assert.equal((await login.json()).access_token, "access");
  assert.match(login.headers.get("set-cookie"), /lingora_refresh=token/);
  const me = await fetch(`${base}/backend/api/v1/auth/me`, { headers: { authorization: "Bearer access" } });
  assert.equal((await me.json()).email, "ali@example.com");
  const file = await fetch(`${base}/backend/api/v1/books/1/file?download=true`, { headers: { range: "bytes=0-3" } });
  assert.equal(file.status, 206);
  assert.equal(file.headers.get("content-range"), "bytes 0-3/8");
  assert.equal(await file.text(), "%PDF");
  assert.equal((await fetch(`${base}/backend/api/v1/missing`)).status, 404);
  await new Promise((resolve) => backend.close(resolve));
  const unavailable = await fetch(`${base}/backend/api/v1/auth/me`);
  assert.equal(unavailable.status, 502);
  assert.equal((await unavailable.json()).error.code, "BACKEND_UNAVAILABLE");
  console.log("Production proxy tests passed");
} finally {
  frontend.kill();
  backend.close();
}
