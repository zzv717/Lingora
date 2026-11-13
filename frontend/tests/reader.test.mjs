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

// PDF.js viewport conversion must undo rotation and nonzero crop-box origin.
const geomSource = fs.readFileSync(new URL('../src/lib/ocr-geometry.ts', import.meta.url), 'utf8');
const geomJs = ts.transpileModule(geomSource, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const geomExports = {};
vm.runInNewContext(geomJs, { exports: geomExports });
const { default: pdfjs } = await import('pdfjs-dist/legacy/build/pdf.js');
// Minimal in-memory PDF; exercises real PDF.js page viewport transforms.
function pdfBytes(rotation) {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 700 900] /CropBox [20 30 620 830] /Rotate ${rotation} /Resources << >> /Contents 4 0 R >>`,
    '<< /Length 0 >>\nstream\n\nendstream',
  ];
  let pdf = '%PDF-1.4\n'; const offsets = [0];
  objects.forEach((obj, i) => { offsets.push(Buffer.byteLength(pdf)); pdf += `${i + 1} 0 obj\n${obj}\nendobj\n`; });
  const start = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets.slice(1)) pdf += `${String(offset).padStart(10, '0')} 00000 n \n`;
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF`;
  return new Uint8Array(Buffer.from(pdf));
}
for (const rotation of [0, 90, 180, 270]) {
  const viewBox = [20, 30, 620, 830];
  const doc = await pdfjs.getDocument({ data: pdfBytes(rotation) }).promise;
  const page = await doc.getPage(1);
  const viewport = page.getViewport({ scale: 2 });
  const corners = [[120, 630], [180, 590]].map(([x,y]) => viewport.convertToViewportPoint(x,y));
  const box = { x0: Math.min(...corners.map(p=>p[0])), y0: Math.min(...corners.map(p=>p[1])),
    x1: Math.max(...corners.map(p=>p[0])), y1: Math.max(...corners.map(p=>p[1])) };
  assert.deepEqual(Array.from(geomExports.ocrBoxToPdf(box, viewport, page.view)), [100, 200, 160, 240]);
  await doc.destroy();
}
console.log('OCR crop and rotation geometry tests passed');
const timeoutSource = fs.readFileSync(new URL('../src/lib/timeout.ts', import.meta.url), 'utf8');
const timeoutJs = ts.transpileModule(timeoutSource, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const timeoutExports = {};
vm.runInNewContext(timeoutJs, { exports: timeoutExports, setTimeout, clearTimeout });
assert.equal(await timeoutExports.withTimeout(Promise.resolve('ok'), 50, 'timeout'), 'ok');
await assert.rejects(timeoutExports.withTimeout(new Promise(() => {}), 5, 'timeout'), /timeout/);
console.log('Bounded loading timeout tests passed');
