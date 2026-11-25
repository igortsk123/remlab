// Кадры model-viewer для подбора тона (T-20261124-63, Ш4а; tools/scout/part_material.py). Запуск: node part_material_render.js <spec.json>.
//   spec = { jobs: [{glb, out, orbit, size}], tools: {load_timeout_s, settle_ms, libs_model_viewer, light, chromium_args} } — все числа приходят из rules/part-material.json.
// Один Chromium на все кадры; свет — строка атрибутов model-viewer (neutral, exposure 1, без тени — как на страницах показа). Код возврата 0, если нарисованы все кадры.
const fs = require('fs');

function chromiumOf() {
  for (const name of ['@playwright/test', 'playwright', 'playwright-core']) {
    try { return require(name).chromium; } catch (e) { /* пробуем следующий */ }
  }
  throw new Error('нет пакета playwright (pnpm install)');
}

(async () => {
  const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const T = spec.tools;
  const browser = await chromiumOf().launch({ args: T.chromium_args });
  let bad = 0;
  for (const j of spec.jobs) {
    const S = j.size;
    const page = await browser.newPage({ viewport: { width: S, height: S } });
    try {
      let html = '';
      await page.route('https://models.local/**', (route) => {
        const pn = new URL(route.request().url()).pathname.slice(1);
        if (pn === 'index.html') return route.fulfill({ status: 200, contentType: 'text/html', body: html });
        if (pn !== 'm.glb') return route.abort();
        return route.fulfill({ path: j.glb, headers: { 'access-control-allow-origin': '*', 'content-type': 'model/gltf-binary' } });
      });
      html = `<html><head><script type="module" src="${T.libs_model_viewer}"></script></head><body style="margin:0;background:#fff"><model-viewer id="mv" src="https://models.local/m.glb" ${T.light} camera-orbit="${j.orbit}" style="width:${S}px;height:${S}px"></model-viewer></body></html>`;
      await page.goto('https://models.local/index.html', { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => { const m = document.querySelector('model-viewer'); return m && m.loaded; }, null, { timeout: T.load_timeout_s * 1000 });
      await page.waitForTimeout(T.settle_ms);
      await page.locator('#mv').screenshot({ path: j.out });
      console.log('ok', j.out);
    } catch (e) {
      bad += 1;
      console.log('FAIL', j.out, String(e).slice(0, 200));
    } finally {
      await page.close();
    }
  }
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
