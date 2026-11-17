// ПРОБА T-20261117-02, шаг 2: three-gpu-pathtracer в headless Chromium (программный WebGL, видеокарты нет). 0 ₽.
//   node pt_run.mjs <папка gltf сцены> <камера> <ширина> <высота> <сэмплы> <выход.png> [ключ=значение ...(sun env fill exp bounces)] [timeout_min=20]
import { createRequire } from 'module';
import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const require = createRequire('/home/pakar/igor/remlab/package.json');
const { chromium } = require('/home/pakar/igor/remlab/node_modules/.pnpm/playwright@1.51.1/node_modules/playwright');
const here = path.dirname(fileURLToPath(import.meta.url));
const [dir, cam, w, h, samples, out, ...rest] = process.argv.slice(2);
const extra = Object.fromEntries(rest.map((s) => s.split('=')));
const timeoutMin = +(extra.timeout_min || 20);
delete extra.timeout_min;

const types = { '.html': 'text/html', '.json': 'application/json', '.glb': 'model/gltf-binary' };
const srv = http.createServer((req, res) => {
  const u = req.url.split('?')[0];
  const f = u === '/' || u === '/pt.html' ? path.join(here, 'pt.html') : path.join(dir, u);
  if (!fs.existsSync(f) || !fs.statSync(f).isFile()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' });
  fs.createReadStream(f).pipe(res);
});
await new Promise((r) => srv.listen(0, '127.0.0.1', r));
const port = srv.address().port;

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl', '--disable-gpu-sandbox'],
});
const page = await browser.newPage({ viewport: { width: +w, height: +h } });
page.on('console', (m) => console.log('[page]', m.text()));
let pageErr = null;
page.on('pageerror', (e) => { pageErr = String(e); console.log('[pageerror]', pageErr); });
const qs = new URLSearchParams({ cam, w, h, samples, ...extra }).toString();
const t0 = Date.now();
await page.goto(`http://127.0.0.1:${port}/pt.html?${qs}`);
let last = -1;
while (true) {
  await new Promise((r) => setTimeout(r, 5000));
  const st = await page.evaluate(() => ({ done: window.__done, err: window.__err, s: window.__samples || 0, sec: window.__sec || 0, ready: !!window.__ready }));
  if (st.s !== last) { console.log(`образцов ${st.s} · ${st.sec.toFixed ? st.sec.toFixed(0) : st.sec} с (всего ${((Date.now() - t0) / 1000).toFixed(0)} с)`); last = st.s; }
  if (pageErr && !st.ready) { console.log('страница упала до старта, выходим'); break; }
  if (st.err) { console.log('ОШИБКА страницы:', st.err); break; }
  if (st.done) { break; }
  if ((Date.now() - t0) / 60000 > timeoutMin) { console.log(`ТАЙМАУТ ${timeoutMin} мин, образцов ${st.s}`); break; }
}
const png = await page.evaluate(() => window.__png || null);
if (png) { fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true }); fs.writeFileSync(out, Buffer.from(png.split(',')[1], 'base64')); console.log('записан', out); }
console.log('итого', ((Date.now() - t0) / 1000).toFixed(0), 'с');
await browser.close();
srv.close();
