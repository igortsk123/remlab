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


// Режим «свет сайта» (spec.site): тот же three.js и те же числа света, что у просмотрщика сайта (lib/viewer3d/viewer.ts + window-light.ts:LIGHT):
// RoomEnvironment + полусфера + солнце + подсветка, Neutral tone mapping. Лист показывает то, что видит покупатель (T-20261123-37, директор).
async function renderSite(browser, it, spec, rep) {
  const { viewer, site } = spec;
  const ctx = await browser.newContext({ viewport: { width: viewer.width, height: viewer.height } });
  try {
    const page = await ctx.newPage();
    let html = '';
    page.on('console', (m) => { if (m.type() === 'error') rep.notes.push('console.error: ' + m.text().slice(0, 120)); });
    await page.route('https://models.local/**', (route) => {
      const pn = new URL(route.request().url()).pathname.slice(1);
      if (pn === 'index.html') return route.fulfill({ status: 200, contentType: 'text/html', body: html });
      if (pn !== 'm.glb') return route.abort();
      return route.fulfill({ path: it.glb, headers: { 'access-control-allow-origin': '*', 'content-type': 'model/gltf-binary' } });
    });
    html = `<html><head><script type="importmap">{"imports":{"three":"${site.libs.three}","three/addons/":"${site.libs.three_addons}"}}</script></head><body style="margin:0;background:#fff"><canvas id="c" width="${viewer.width}" height="${viewer.height}" style="width:${viewer.width}px;height:${viewer.height}px;display:block"></canvas>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
const L = ${JSON.stringify(site.light)}, FOV = ${JSON.stringify(site.fov)};
const r = new THREE.WebGLRenderer({ canvas: document.getElementById('c'), antialias: true, preserveDrawingBuffer: true });
r.setSize(${viewer.width}, ${viewer.height}, false); r.outputColorSpace = THREE.SRGBColorSpace; r.toneMapping = THREE.NeutralToneMapping; r.toneMappingExposure = L.exposure;
const sc = new THREE.Scene(); sc.background = new THREE.Color(0xffffff);
const pm = new THREE.PMREMGenerator(r); sc.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture; sc.environmentIntensity = L.env;
sc.add(new THREE.HemisphereLight(L.hemiSky, L.hemiGround, L.hemi));
const sun = new THREE.DirectionalLight(L.sunColor, L.sun); sun.position.set(...L.sunPos); sc.add(sun);
const fill = new THREE.DirectionalLight(L.fillColor, L.fill); fill.position.set(...L.fillPos); sc.add(fill);
const loader = new GLTFLoader(); loader.setMeshoptDecoder(MeshoptDecoder);
loader.load('https://models.local/m.glb', (g) => {
  sc.add(g.scene);
  const box = new THREE.Box3().setFromObject(g.scene); const c = box.getCenter(new THREE.Vector3()); const rad = box.getBoundingSphere(new THREE.Sphere()).radius;
  const cam = new THREE.PerspectiveCamera(FOV, 1, 0.01, 100);
  window.__shot = (th, polar, k) => {
    const d = rad / Math.sin(THREE.MathUtils.degToRad(FOV / 2)) * k, t = THREE.MathUtils.degToRad(th), p = THREE.MathUtils.degToRad(polar);
    cam.position.set(c.x + d * Math.sin(p) * Math.sin(t), c.y + d * Math.cos(p), c.z + d * Math.sin(p) * Math.cos(t)); cam.lookAt(c); r.render(sc, cam);
  };
  window.__clay = (cl) => g.scene.traverse((o) => { if (o.isMesh) { o.material = new THREE.MeshStandardMaterial({ color: 0xffffff, metalness: cl.metallic, roughness: cl.roughness }); } });
  window.__ready = true;
}, undefined, (e) => { window.__err = String(e); });
</script></body></html>`;
    await page.goto('https://models.local/index.html', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => window.__ready || window.__err, null, { timeout: viewer.load_timeout_s * 1000 });
    const err = await page.evaluate(() => window.__err);
    if (err) throw new Error('загрузка модели: ' + err);
    fs.mkdirSync(`${spec.out}/${it.id}`, { recursive: true });
    const shoot = async (suffix) => {
      for (const o of it.orbits) {
        const [th, polar, rad] = o.orbit.split(' ').map((x) => parseFloat(x));
        await page.evaluate(([a, b, k]) => window.__shot(a, b, k), [th, polar, (rad / 100) * site.distance_k]);
        await page.waitForTimeout(viewer.settle_ms);
        await page.locator('#c').screenshot({ path: `${spec.out}/${it.id}/${o.tag}${suffix}.png` });
        if (!suffix) rep.tags.push(o.tag);
      }
    };
    await shoot('');
    rep.ok = rep.tags.length === it.orbits.length;
    if (spec.clay && rep.ok) { await page.evaluate((cl) => window.__clay(cl), spec.clay); await shoot('.clay'); }
  } finally {
    await ctx.close();
  }
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
        if (spec.site) { await renderSite(browser, it, spec, rep); continue; }
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
