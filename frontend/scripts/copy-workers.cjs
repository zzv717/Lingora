const fs = require('fs');
const path = require('path');
fs.mkdirSync('public/ocr', { recursive: true });
fs.copyFileSync('node_modules/pdfjs-dist/build/pdf.worker.min.js', 'public/pdf.worker.min.js');
fs.copyFileSync('node_modules/tesseract.js/dist/worker.min.js', 'public/ocr/worker.min.js');
for (const file of ['tesseract-core-lstm.wasm.js', 'tesseract-core-simd-lstm.wasm.js']) {
  fs.copyFileSync(path.join('node_modules/tesseract.js-core', file), path.join('public/ocr', file));
}
fs.copyFileSync('node_modules/@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz', 'public/ocr/eng.traineddata.gz');
console.log('PDF and offline English OCR worker assets copied');
