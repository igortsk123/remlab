// ЧАСТЬ Б demo-20 (T-20261022-01, владелец 22.10): язык не открывает вариант; на сенсорном экране тап по полу не двигает камеру
// (с мышью — ведёт туда), тап у края поворачивает; после замены ТВ-тумбы и стула — без контура, подсказка гаснет за ~2 с, камера
// подошла; «Сделать реалистичнее» — сразу «Фото» с «Улучшаю… N %», готовое встаёт само (сервер кадров подменён — платного нет);
// у двери нет зелёной щели. Снимки 375×667 и 1440×900 — в <outdir>.
//   node tools/ops/demo-walk/part-b-check.cjs https://remont-lab.online <outdir> [375|1440]
// Локальная страница поверх прода — прокси (страница и `lib/` из рабочей копии, остальное с прода): база http://localhost:<порт>
const path = require("path"), fs = require("fs");
const pw = require(path.resolve("node_modules/.pnpm/playwright@1.51.1/node_modules/playwright"));
const BASE = process.argv[2] || "http://localhost:3106", OUT = process.argv[3], ONLY = +(process.argv[4] || 0);
fs.mkdirSync(OUT, { recursive: true });
const R = []; const ok = (n, c, i) => { R.push((c ? "OK  " : "FAIL") + " " + n + (i !== undefined ? " — " + i : "")); console.log(R[R.length - 1]); };
const VPS = [{ w: 375, h: 667, phone: true }, { w: 1440, h: 900, phone: false }].filter((v) => !ONLY || v.w === ONLY);
async function open(b, vp, q) {
  const ctx = await b.newContext({ viewport: { width: vp.w, height: vp.h }, deviceScaleFactor: 1, isMobile: vp.phone, hasTouch: vp.phone, locale: "ru-RU" });
  const p = await ctx.newPage(); p.errs = []; p.on("pageerror", (e) => p.errs.push(String(e).slice(0, 200)));
  await p.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
  await p.goto(BASE + "/demo/" + (q || ""), { waitUntil: "load", timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&allVariants().length>0&&document.querySelectorAll('#styleTabs [data-style]').length>0", null, { timeout: 90000 });
  await p.waitForTimeout(2500);
  return p;
}
async function openWindow(p) {
  await p.click("#hmRooms [data-swap]");
  await p.waitForTimeout(1500);
  await p.evaluate("vwMode('walk')");   // у варианта с реалистичным фото окно открывается в «Фото»
  await p.waitForFunction("LIVE.state==='ready'&&!!LIVE.scene", null, { timeout: 120000 });
  await p.waitForTimeout(1500);
}
const pose = (p) => p.evaluate("LIVE.scene.pose()");
async function replace(p, role) {
  const k = await p.evaluate((role) => items.findIndex((i) => i.role.startsWith(role)), role);
  if (k < 0) return null;
  await p.evaluate((k) => openPicker(items[k]), k);
  await p.waitForTimeout(400);
  const t0 = Date.now();
  await p.evaluate(() => { window.__tl = { on: 0, off: 0 }; const t = document.getElementById("toast");
    if (t && !t.__mo) { t.__mo = new MutationObserver(() => { const now = performance.now();
      if (!t.hidden && !t.classList.contains("out") && !window.__tl.on) window.__tl.on = now;
      if (t.hidden && window.__tl.on && !window.__tl.off) window.__tl.off = now; });
      t.__mo.observe(t, { attributes: true, attributeFilter: ["hidden", "class"] }); } });
  await p.locator("#grid .card:not(.cur) .acts button").first().click();
  await p.waitForTimeout(300);
  const toast = await p.evaluate(() => { const t = document.getElementById("toast"); return !!t && !t.hidden && !t.classList.contains("out"); });
  await p.waitForFunction("LIVE.state==='ready'", null, { timeout: 60000 });
  return { k, t0, toast };
}
(async () => {
  const b = await pw.chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  try {
    for (const vp of VPS) {
      const tag = vp.w + "x" + vp.h;
      // Б1 — язык на вкладке «Современный»
      {
        const p = await open(b, vp, "?lang=ru");
        const tab = await p.evaluate(() => { const t = [...document.querySelectorAll("#styleTabs [data-style]")].find((x) => /соврем/i.test(x.textContent)); return t && t.dataset.style; });
        await p.click(`#styleTabs [data-style="${tab}"]`); await p.waitForTimeout(600);
        await p.evaluate(() => window.scrollTo(0, 300)); await p.waitForTimeout(300);
        const y0 = await p.evaluate("Math.round(scrollY)");
        await p.evaluate(() => document.querySelector('#langSw [data-lang="en"]').click());
        await p.waitForURL(/lang=en/, { timeout: 30000 });
        await p.waitForFunction("typeof D!=='undefined'&&!!D&&document.querySelectorAll('#styleTabs [data-style]').length>0", null, { timeout: 90000 });
        await p.waitForTimeout(4000);
        const st = await p.evaluate(() => ({ open: document.getElementById("shot").classList.contains("on"), tab: (document.querySelector("#styleTabs .hm-tab.on") || {}).dataset?.style, y: Math.round(scrollY), url: location.search + location.hash }));
        ok(`${tag} Б1: смена языка на «Современном» — окно не открыто, вкладка та же`, !st.open && st.tab === tab, JSON.stringify({ ...st, y0 }));
        ok(`${tag} Б1: прокрутка вернулась (±80: английский текст выше другой высоты)`, Math.abs(st.y - y0) <= 80, `было ${y0}, стало ${st.y}`);
        await p.screenshot({ path: `${OUT}/${tag}-lang-en.png` });
        await p.context().close();
      }
      // Б6 — тап по полу; Б4/Б5 — замены
      {
        const p = await open(b, vp, "?lang=ru&live=force");
        await openWindow(p);
        if (vp.phone) { await p.evaluate("vwSheet(0)"); await p.waitForTimeout(800); }   // шторка вниз — палец по сцене, а не по списку
        const cv = await p.evaluate(() => { const r = LIVE.canvas.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; });
        // пол: точка у нижнего края холста по центру — проверяем, что это не предмет
        let tapPt = null;
        for (const fy of [0.9, 0.85, 0.8, 0.75, 0.7]) for (const fx of [0.5, 0.4, 0.6, 0.3, 0.7]) {
          const x = cv.x + cv.w * fx, y = cv.y + cv.h * fy;
          if (!tapPt && (await p.evaluate(([x, y]) => document.elementFromPoint(x, y) === LIVE.canvas && LIVE.scene.pick(x, y) < 0, [x, y]))) tapPt = { x, y };
        }
        ok(`${tag} Б6: точка пола на холсте найдена`, !!tapPt, JSON.stringify(tapPt));
        const a = await pose(p);
        if (vp.phone) await p.touchscreen.tap(tapPt.x, tapPt.y); else await p.mouse.click(tapPt.x, tapPt.y);
        await p.waitForTimeout(2000);
        const c = await pose(p), moved = Math.hypot(c.x - a.x, c.y - a.y);
        if (vp.phone) ok(`${tag} Б6: сенсорный экран — тап по полу камеру не двигает`, moved < 1, `сдвиг ${moved.toFixed(1)} см`);
        else ok(`${tag} Б6: мышь — тап по полу ведёт туда`, moved > 20, `сдвиг ${moved.toFixed(1)} см`);
        // поворот тапом по краю остаётся
        const y1 = (await pose(p)).yaw;
        const edgeY = await p.evaluate(([x, y0, h]) => { for (let f = 0.5; f > 0.1; f -= 0.05) { const e = document.elementFromPoint(x, y0 + h * f); if (e === LIVE.canvas) return y0 + h * f; } return y0 + h * 0.5; }, [cv.x + cv.w * 0.95, cv.y, cv.h]);
        const hitEl = await p.evaluate(([x, y]) => { const e = document.elementFromPoint(x, y); return e ? (e.id || e.className || e.tagName) : ""; }, [cv.x + cv.w * 0.95, edgeY]);
        if (vp.phone) await p.touchscreen.tap(cv.x + cv.w * 0.95, edgeY); else await p.mouse.click(cv.x + cv.w * 0.95, edgeY);
        await p.waitForTimeout(800);
        const y2 = (await pose(p)).yaw;
        ok(`${tag} Б6: тап у края — поворот на 30°`, Math.abs(((y2 - y1 + 540) % 360) - 180) > 20, `${y1}° → ${y2}°, под пальцем: ${hitEl}`);
        // замены: ТВ-тумба и стул
        for (const role of ["тв-тумба", "стул"]) {
          await p.evaluate(() => { const c = cams || loadCams(); LIVE.scene.setPhotoPose(camPoseOf(c[0])); });   // как после «со стороны двери»
          await p.evaluate("vwMode('walk')"); await p.waitForTimeout(600);
          const r = await replace(p, role);
          if (!r) { ok(`${tag} ${role}: есть в варианте`, false); continue; }
          await p.waitForTimeout(900);   // переход камеры 0,6–1,4 с
          const s = await p.evaluate((k) => { const it = items[k], t = document.getElementById("toast"), pz = LIVE.scene.pose();
            const half = Math.max(it.w, it.d) / 2;
            return { sel: VW.sel, framed: LIVE.framed, toast: !!t && !t.hidden && !t.classList.contains("out"), text: t && t.textContent,
              dist: Math.round(Math.hypot(pz.x - it.x, pz.y - it.y) - Math.min(it.w, it.d) / 2), w: it.w, d: it.d, h: it.h, half }; }, r.k);
          await p.waitForTimeout(Math.max(0, 1400 - (Date.now() - r.t0)));
          await p.screenshot({ path: `${OUT}/${tag}-after-${role === "стул" ? "chair" : "tv"}.png` });
          ok(`${tag} Б4 ${role}: после замены выделения нет`, s.sel == null, JSON.stringify({ sel: s.sel }));
          ok(`${tag} Б5 ${role}: камера у предмета`, s.dist <= 260, JSON.stringify({ framed: s.framed, distToItemCm: s.dist, w: s.w, d: s.d, h: s.h }));
          await p.waitForFunction("(()=>{const t=document.getElementById('toast');return !t||t.hidden;})()", null, { timeout: 4000 }).catch(() => {});
          const tl = await p.evaluate(() => window.__tl), goneMs = tl.on && tl.off ? Math.round(tl.off - tl.on) : -1;
          const gone = await p.evaluate(() => { const t = document.getElementById("toast"); return !t || t.hidden; });
          ok(`${tag} Б4 ${role}: подсказка «${s.text}» погасла за ~2 с`, r.toast && gone && (goneMs < 0 || goneMs < 2600), JSON.stringify({ shownAt03: r.toast, goneMs }));
        }
        ok(`${tag}: без ошибок страницы`, !p.errs.length, p.errs.join(" | "));
        await p.context().close();
      }
      // Б3 — «Сделать реалистичнее»: сервер кадров подменён (платного запроса нет) — 3 опроса «рисуется», потом готово
      {
        const p = await open(b, vp, "?lang=ru&live=force");
        let polls = 0, img = "";
        await p.route(/\/api\/render\/frame/, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "f" + Date.now() }) }));
        await p.route(/\/api\/render(\?|$)/, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ job: "fake-b3" }) }));
        await p.route(/\/api\/job/, (r) => r.fulfill({ status: 200, contentType: "application/json",
          body: JSON.stringify(++polls <= 3 ? { status: "running", eta: 20 } : { status: "done", shots: [{ url: img, camera: "C1" }, { url: img, camera: "C2" }] }) }));
        await openWindow(p);
        img = await p.evaluate(() => (shots.find((x) => x.quality === "realistic" && x.url) || shots[0]).url);
        await replace(p, "диван"); await replace(p, "столик"); await replace(p, "тв-тумба"); await p.waitForTimeout(1500);
        const pre = await p.evaluate(() => ({ mode: VW.mode, photoTab: !document.querySelector('#shot [data-vm="photo"]').hidden }));
        await p.click("#vCta"); await p.waitForTimeout(2500);
        const mid = await p.evaluate(() => { const o = document.querySelector("#shot .vphwait"), ph = document.querySelector('#shot [data-vm="photo"]');
          const r = o && o.getBoundingClientRect(); return { mode: VW.mode, photoTab: !!ph && !ph.hidden, overlay: o ? o.querySelector("b").textContent : "", ow: r ? Math.round(r.width) : 0, oh: r ? Math.round(r.height) : 0 }; });
        await p.screenshot({ path: `${OUT}/${tag}-b3-wait.png` });
        ok(`${tag} Б3: старт фото — сразу вкладка «Фото» и «Улучшаю… N %» на весь кадр`, !pre.photoTab && mid.photoTab && mid.mode === "photo" && /^Улучшаю… \d+ %$/.test(mid.overlay) && mid.ow > vp.w * 0.5,
          JSON.stringify({ pre, mid }));
        await p.waitForFunction("!VJ.job", null, { timeout: 60000 });
        await p.waitForTimeout(1500);
        const fin = await p.evaluate(() => ({ mode: VW.mode, real: vwRealShots().length, overlay: !!document.querySelector("#shot .vphwait"),
          main: (document.querySelector("#shot .vmain") || {}).src || "" }));
        await p.screenshot({ path: `${OUT}/${tag}-b3-done.png` });
        ok(`${tag} Б3: готово — снимок в «Фото» сам, ход работы убран`, fin.mode === "photo" && fin.real > 0 && !fin.overlay, JSON.stringify({ ...fin, main: fin.main.slice(-40), polls }));
        ok(`${tag} Б3: без ошибок страницы`, !p.errs.length, p.errs.join(" | "));
        await p.context().close();
      }
      // Б6 — дверь: встаём перед ней в 1,3 м и смотрим на неё
      {
        const p = await open(b, vp, "?lang=ru&live=force");
        await openWindow(p);
        const door = await p.evaluate(() => { const o = (D.room.openings || []).find((x) => x.kind === "door"); if (!o) return null;
          const g = wallSeg(o.wall, +o.offset_cm || 0, +o.width_cm), n = { south: [0, 1], north: [0, -1], west: [1, 0], east: [-1, 0] }[o.wall];
          const mx = (g.x1 + g.x2) / 2, my = (g.y1 + g.y2) / 2, x = mx + n[0] * 130, y = my + n[1] * 130;
          const rot = Math.atan2(-n[0], n[1]) * 180 / Math.PI;
          LIVE.scene.setPhotoPose({ x, y, rot, fov: 72, pose: 2 }); LIVE.scene.start(); return { wall: o.wall, x, y, rot }; });
        await p.waitForTimeout(1500);
        const shot = `${OUT}/${tag}-door.png`;
        await p.screenshot({ path: shot });
        const green = await p.evaluate(async () => { const c = LIVE.canvas, w = c.width, h = c.height;
          const t = document.createElement("canvas"); t.width = w; t.height = h; const x = t.getContext("2d");
          LIVE.scene.start(); await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
          const blob = await LIVE.scene.exportFrame(w, h, "image/png"); const im = await createImageBitmap(blob); x.drawImage(im, 0, 0);
          const d = x.getImageData(Math.round(w * 0.2), 0, Math.round(w * 0.6), h).data; let n = 0;
          for (let i = 0; i < d.length; i += 4) if (d[i + 1] > 70 && d[i + 1] > d[i] + 18 && d[i + 1] > d[i + 2] + 18) n++;
          return n; });
        ok(`${tag} Б6: у двери нет зелёной щели`, green < 30, `зелёных пикселей в середине кадра: ${green}, дверь ${JSON.stringify(door)}`);
        await p.context().close();
      }
    }
  } finally { await b.close(); }
  fs.writeFileSync(`${OUT}/result.txt`, R.join("\n") + "\n");
  console.log(R.filter((x) => x.startsWith("FAIL")).length ? "ЕСТЬ FAIL" : "ВСЁ OK");
})();
