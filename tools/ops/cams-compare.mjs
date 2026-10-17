// СРАВНЕНИЕ ТОЧЕК СЪЁМКИ «БЫЛО / СТАЛО» ДЛЯ ВЛАДЕЛЬЦА (план demo-12) — БЕСПЛАТНО: живая 3D-сцена страницы демо снимает обе точки
// каждого варианта прежним подбором (углы) и новым (пара, `?cams=pair`), альбомный кадр компьютера и вертикальный телефона;
// рядом — метрики кадра по маске (`camStats` блока CAMFIT). Пишет `/tmp/cams-compare/` и выкладывает на прод в
// `/test/scene-look/cams/`. Нейросеть не зовётся.
//   node tools/ops/cams-compare.mjs            # снять и выложить
//   node tools/ops/cams-compare.mjs --local    # только снять в /tmp/cams-compare
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const BASE = process.env.DEMO_BASE ?? "https://remont-lab.online";
const OUT = "/tmp/cams-compare";
const LOCAL = process.argv.includes("--local");
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const rows = {};
let failed = 0;
try {
  for (const [algo, q] of [["было", ""], ["стало", "&cams=pair"]]) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    await page.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
    await page.goto(`${BASE}/demo/?live=force&lang=ru${q}`, { waitUntil: "load", timeout: 120000 });
    await page.waitForFunction("typeof D !== 'undefined' && !!D && !!FLAT && allVariants().length > 0", null, { timeout: 90000 });
    const on = await page.evaluate("typeof CAM_PAIR_ON !== 'undefined' && CAM_PAIR_ON");
    if ((algo === "стало") !== on) throw new Error(`страница не в том режиме подбора (${algo}: CAM_PAIR_ON=${on}) — прод старый?`);
    const n = await page.evaluate("allVariants().length");
    for (let i = 0; i < n; i++) {
      const r = await page.evaluate(async (i) => {
        pickVariant(i); openLiveWindow(); if (VW.mode !== "walk") vwMode("walk");
        for (let k = 0; k < 600 && !(LIVE.scene && LIVE.state === "ready"); k++) await new Promise((ok) => setTimeout(ok, 300));
        if (!LIVE.scene || !LIVE.scene.capture) return { error: "3D не открылась" };
        cams = loadCams();
        await LIVE.scene.update(clone(items), liveDecor());
        const poses = cams.slice(0, 2).map(camPoseOf), url = (b) => new Promise((ok) => { const fr = new FileReader(); fr.onload = () => ok(fr.result); fr.readAsDataURL(b); });
        const land = await LIVE.scene.capture(poses, 1536, 1117), port = await LIVE.scene.capture(poses, 1117, 1536);
        const st = cams.slice(0, 2).map((c) => { const s = camStats(c, items, D.room.w, D.room.d), p = camStats(c, items, D.room.w, D.room.d, { w: 64, h: 88, sn: typeof camPoseOf(c).pshift === "number" ? -2 * camPoseOf(c).pshift : CAM_SHIFT_N });
          return { x: Math.round(c.x), y: Math.round(c.y), rot: Math.round(c.rot || 0), fov: c.fov || 72, pshift: camPoseOf(c).pshift,
            ceil: s.ceil, floor: s.floor, empty: s.empty, nearWall: s.nearWall, fore: s.fore, seen: camSeen(c, items, s).size, pFloor: p.floor, pCeil: p.ceil }; });
        return { style: allVariants()[i].style, items: items.length, land: await Promise.all(land.frames.map(url)), port: await Promise.all(port.frames.map(url)), st };
      }, i);
      if (r.error) { failed += 1; console.log(`  ${algo} вариант ${i}: ${r.error}`); continue; }
      const files = {};
      for (const [kind, list] of [["land", r.land], ["port", r.port]])
        list.forEach((d, k) => { const f = `${r.style}-${algo === "было" ? "old" : "new"}-${kind}-C${k + 1}.jpg`; writeFileSync(`${OUT}/${f}`, Buffer.from(d.split(",")[1], "base64")); (files[kind] ||= []).push(f); });
      (rows[r.style] ||= {})[algo] = { st: r.st, files, items: r.items };
      console.log(`  ${algo} ${r.style}: ${r.st.map((s, k) => `C${k + 1} (${s.x},${s.y}) ${s.rot}° пусто ${s.empty.toFixed(2)} край ${s.nearWall.toFixed(2)} видно ${s.seen}`).join(" · ")}`);
    }
    await page.close();
  }
} finally {
  await browser.close();
}
const f2 = (x) => (typeof x === "number" ? x.toFixed(2) : "—");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const block = (style) => ["было", "стало"].map((algo) => {
  const r = rows[style]?.[algo]; if (!r) return "";
  const img = (f) => `<a href="${esc(f)}" target="_blank"><img src="${esc(f)}" loading="lazy" alt="${esc(style)} ${esc(algo)}"></a>`;
  const met = r.st.map((s, k) => `<li>Вид ${k + 1}: точка (${s.x}, ${s.y}), взгляд ${s.rot}°, объектив ${s.fov}° · пустая стена ${f2(s.empty)} · потолок ${f2(s.ceil)} · пол ${f2(s.floor)} · стена у края ${f2(s.nearWall)} · мебель вплотную ${f2(s.fore)} · предметов целиком ${s.seen} из ${r.items}${s.pshift !== undefined ? ` · телефон: сдвиг ${s.pshift}, пол ${f2(s.pFloor)} / потолок ${f2(s.pCeil)}` : ""}</li>`).join("");
  return `<div class="alg"><h3>${algo === "было" ? "Было — угол и противоположный угол" : "Стало — пара подбирается вместе"}</h3><div class="land">${r.files.land.map(img).join("")}</div>`
    + `<div class="port">${r.files.port.map(img).join("")}</div><ul>${met}</ul></div>`;
}).join("");
const page = `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Точки съёмки</title>
<style>:root{--ink:#2b2622;--muted:#6f665e;--line:#e6dfd6;--bg:#faf7f2;--card:#fff}@media(prefers-color-scheme:dark){:root{--ink:#eee7df;--muted:#b3a99e;--line:#3a332d;--bg:#1d1a17;--card:#26221e}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:0 auto;padding:20px 16px 60px}h1{font-size:24px;margin:0 0 6px}
.lead{color:var(--muted)}section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:0 0 16px}h2{margin:0 0 8px;text-transform:capitalize}h3{font-size:16px;margin:10px 0 6px}
.land,.port{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}.land img{width:min(520px,100%)}.port img{width:min(200px,45%)}img{border-radius:8px;display:block}ul{color:var(--muted);font-size:14px;padding-left:18px}</style></head><body><main>
<h1>Точки съёмки: было и стало</h1><p class="lead">Живая 3D-сцена демо, без нейросети. Сверху — кадр компьютера (оба вида), ниже — вертикальный кадр телефона. «Стало» — новый подбор пары (план demo-12); на сайте он включится после вашего «ок», вместе с пересъёмкой фото.</p>
${Object.keys(rows).map((st) => `<section><h2>${esc(st)}</h2>${block(st)}</section>`).join("")}</main></body></html>`;
writeFileSync(`${OUT}/index.html`, page);
if (!LOCAL) {
  execFileSync("ssh", ["-o", "BatchMode=yes", "root@89.167.127.0", "mkdir -p /opt/remlab/test/scene-look/cams"]);
  execFileSync("bash", ["-c", `scp -q ${OUT}/*.jpg ${OUT}/index.html root@89.167.127.0:/opt/remlab/test/scene-look/cams/`]);
  console.log("выложено: https://remont-lab.online/test/scene-look/cams/");
}
console.log(`сравнение точек: вариантов ${Object.keys(rows).length}, не вышло ${failed} → ${OUT}`);
if (failed) process.exitCode = 1;
