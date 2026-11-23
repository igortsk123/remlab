// Съёмка листа «со всех сторон» (T-20261123-27/1; tools/assets/sides_sheet.py). Запуск: node tools/assets/sides_sheet.js <spec.json>.
// Одна модель загружается ОДИН раз, вид меняется камерой; один Chromium на все товары. Все числа (свет, размер, ожидание, адреса библиотек) — в spec.json,
// который собирает sides_sheet.py из data/flat3d/sides-sheet.json; в коде чисел съёмки нет.
//   spec = { out, light:{environment_image, exposure, shadow_intensity}, viewer:{width,height,settle_ms,load_timeout_s}, libs:{model_viewer, meshopt_decoder},
//            chromium_args, items:[{id, glb, orbits:[{tag, orbit}]}] }
//   → <out>/<id>/<tag>.png (белый фон) и <out>/items.json {id: {ok, seconds, tags, notes}}. Код возврата 0, если нарисованы все виды всех товаров.
const fs = require('fs');

function chromiumOf() {
  for (const name of ['@playwright/test', 'playwright', 'playwright-core']) {
    try { return require(name).chromium; } catch (e) { /* пробуем следующий */ }
  }
  throw new Error('нет пакета playwright (pnpm install)');
}

async function renderItems(chromium, spec) {
  const { viewer, light, libs } = spec;
  const report = {};
  const browser = await chromium.launch({ args: spec.chromium_args });
  try {
    for (const it of spec.items) {
      const t0 = Date.now();
      const rep = { ok: false, tags: [], notes: [] };
      report[it.id] = rep;
      let ctx = null;
      try {
        ctx = await browser.newContext({ viewport: { width: viewer.width, height: viewer.height } });
        const page = await ctx.newPage();
        let html = '';
        page.on('console', (m) => { if (m.type() === 'error') rep.notes.push('console.error: ' + m.text().slice(0, 120)); });
        await page.route('https://models.local/**', (route) => {
          const pn = new URL(route.request().url()).pathname.slice(1);
          if (pn === 'index.html') return route.fulfill({ status: 200, contentType: 'text/html', body: html });
          if (pn !== 'm.glb') return route.abort();
          return route.fulfill({ path: it.glb, headers: { 'access-control-allow-origin': '*', 'content-type': 'model/gltf-binary' } });
        });
        const first = it.orbits[0].orbit;
        html = `<html><head><script type="module" src="${libs.model_viewer}"></script><script>customElements.whenDefined("model-viewer").then(c=>{c.meshoptDecoderLocation="${libs.meshopt_decoder}"});</script></head><body style="margin:0;background:#fff"><model-viewer id="mv" src="https://models.local/m.glb" environment-image="${light.environment_image}" exposure="${light.exposure}" shadow-intensity="${light.shadow_intensity}" camera-orbit="${first}" interaction-prompt="none" style="width:${viewer.width}px;height:${viewer.height}px;background:#fff;--poster-color:#fff"></model-viewer></body></html>`;
        await page.goto('https://models.local/index.html', { waitUntil: 'domcontentloaded' });
        await page.waitForFunction(() => { const m = document.querySelector('model-viewer'); return m && m.loaded; }, null, { timeout: viewer.load_timeout_s * 1000 });
        fs.mkdirSync(`${spec.out}/${it.id}`, { recursive: true });
        for (const o of it.orbits) {
          await page.evaluate((orb) => { const m = document.querySelector('model-viewer'); m.cameraOrbit = orb; if (m.jumpCameraToGoal) m.jumpCameraToGoal(); }, o.orbit);
          await page.waitForTimeout(viewer.settle_ms);
          await page.locator('#mv').screenshot({ path: `${spec.out}/${it.id}/${o.tag}.png` });
          rep.tags.push(o.tag);
        }
        rep.ok = rep.tags.length === it.orbits.length;
        if (spec.clay && rep.ok) {                  // «глина»: те же виды с белым материалом без текстур — по ней форма (тень) отделяется от тона (T-20261123-37)
          await page.evaluate(async (c) => {
            const m = document.querySelector('model-viewer');
            for (const mat of m.model.materials) {
              const pbr = mat.pbrMetallicRoughness;
              pbr.setBaseColorFactor([1, 1, 1, 1]); pbr.setMetallicFactor(c.metallic); pbr.setRoughnessFactor(c.roughness);
              if (pbr.baseColorTexture) pbr.baseColorTexture.setTexture(null);
              if (pbr.metallicRoughnessTexture) pbr.metallicRoughnessTexture.setTexture(null);
              if (mat.setEmissiveFactor) mat.setEmissiveFactor([0, 0, 0]);
            }
          }, spec.clay);
          for (const o of it.orbits) {
            await page.evaluate((orb) => { const m = document.querySelector('model-viewer'); m.cameraOrbit = orb; if (m.jumpCameraToGoal) m.jumpCameraToGoal(); }, o.orbit);
            await page.waitForTimeout(viewer.settle_ms);
            await page.locator('#mv').screenshot({ path: `${spec.out}/${it.id}/${o.tag}.clay.png` });
          }
        }
      } catch (e) {
        rep.notes.push(String(e).slice(0, 200));
      } finally {
        if (ctx) await ctx.close();
        rep.seconds = Math.round((Date.now() - t0) / 100) / 10;
      }
    }
  } finally {
    await browser.close();
  }
  fs.mkdirSync(spec.out, { recursive: true });
  fs.writeFileSync(`${spec.out}/items.json`, JSON.stringify(report, null, 1));
  return report;
}

(async () => {
  const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const rep = await renderItems(chromiumOf(), spec);
  const bad = Object.keys(rep).filter((k) => !rep[k].ok);
  console.log(bad.length ? `не нарисованы: ${bad.join(',')}` : `ok ${Object.keys(rep).length}`);
  process.exit(bad.length ? 1 : 0);
})();
