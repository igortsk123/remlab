#!/usr/bin/env node
// ПРОБА БЕЗ СТРАНИЦЫ: «Сделать фото» = рендер (T-20261117-19/1, план `photo-render-first-01`).
// Заказ рендера по снимку расстановки варианта /demo → ожидание → два кадра на диск → (по флагу) «Улучшить» по ним. Печатает времена
// от заказа до обоих кадров (холодный и повтор того же хеша = из кэша) и таблицу этапов очереди.
//   node tools/ops/render-photo-probe.mjs --base http://127.0.0.1:8611 --variants set1,bedroom-1-loft --out <НОВАЯ папка> [--repeat 1] [--improve N]
//     --base      сервис кадров (DEV: http://127.0.0.1:8600; прод: https://remont-lab.online/api — оба принимают /render/cycles)
//     --variants  номера вариантов данных витрины через запятую (гостиная: set1…; спальня: bedroom-1-loft…)
//     --repeat    повторить заказ того же состояния: должен прийти `cached: true` мгновенно
//     --improve   «Улучшить» по готовой паре для первых N вариантов — ПЛАТНО (нейросеть), не больше 4 за прогон; 0 — не звать
//   Без зависимостей (node ≥ 20). Состояние — предметы и позы варианта как есть (страница шлёт то же + свои правки).
import fs from "node:fs";
import path from "node:path";

const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > 0 ? process.argv[i + 1] : d; };
const BASE = (arg("base", "http://127.0.0.1:8600")).replace(/\/+$/, "");
const OUT = arg("out"), VARIANTS = (arg("variants", "set1,bedroom-1-loft")).split(",").filter(Boolean);
const REPEAT = Number(arg("repeat", "1")), IMPROVE = Math.min(4, Number(arg("improve", "0")));
if (!OUT) { console.error("нужен --out <НОВАЯ папка>"); process.exit(2); }
if (fs.existsSync(OUT)) { console.error(`папка ${OUT} уже есть: нужна новая (старые снимки не затираем)`); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });

const base = BASE.endsWith("/api") ? BASE : BASE;     // DEV отвечает на /render/cycles, прод — на /api/render/cycles
const P = (p) => (BASE.endsWith("/api") ? BASE + p : BASE + p.replace(/^\/api/, ""));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function jpost(p, body) {
  const r = await fetch(P(p), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  return { status: r.status, retry: r.headers.get("retry-after"), body: await r.json().catch(() => null) };
}
async function jget(p) { const r = await fetch(P(p)); return { status: r.status, body: await r.json().catch(() => null) }; }

async function orderAndWait(id, tag) {
  const t0 = Date.now();
  const o = await jpost("/api/render/cycles", { v: 1, variant_id: id });
  if (o.status !== 200) { console.log(`${tag} ${id}: заказ отклонён ${o.status} ${JSON.stringify(o.body)}`); return null; }
  const seen = new Map();
  let v;
  for (;;) {
    v = (await jget("/api/job?id=" + o.body.job)).body;
    if (!v) { console.log(`${tag} ${id}: задание пропало`); return null; }
    const k = `${v.status}/${v.stage || ""}`;
    if (!seen.has(k)) seen.set(k, ((Date.now() - t0) / 1000).toFixed(1));
    if (v.status === "done" || v.status === "error") break;
    await sleep(2000);
  }
  const sec = (Date.now() - t0) / 1000;
  console.log(`${tag} ${id}: ${v.status} за ${sec.toFixed(1)} с · cached=${o.body.cached} deduped=${o.body.deduped} · хеш ${o.body.scene_hash.slice(0, 12)} · этапы(с): ${[...seen].map(([k, t]) => `${k}@${t}`).join(" ")}`);
  if (v.status === "error") { console.log("  ошибка:", v.code, v.error); return null; }
  if (v.timing) console.log("  время внутри:", JSON.stringify(v.timing));
  return { ...v, order: o.body, sec };
}

const rows = [];
for (const id of VARIANTS) {
  const first = await orderAndWait(id, "холод");
  if (!first) { rows.push({ id, ok: false }); continue; }
  for (const f of first.frames) {
    const r = await fetch(P(f.url));
    fs.writeFileSync(path.join(OUT, `${id}.${f.camera}.jpg`), Buffer.from(await r.arrayBuffer()));
  }
  let again = null;
  for (let i = 0; i < REPEAT; i++) again = await orderAndWait(id, "повтор");
  rows.push({ id, ok: true, sec: first.sec, repeatSec: again?.sec, key: first.key, frames: first.frames.map((f) => `${f.camera} ${f.w}×${f.h}`).join(", ") });
}
console.log("\nИТОГ (время от заказа до обоих кадров):");
for (const r of rows) console.log(r.ok ? `  ${r.id}: ${r.sec.toFixed(1)} с; повтор того же хеша ${r.repeatSec?.toFixed(2) ?? "—"} с; кадры ${r.frames}` : `  ${r.id}: НЕ ВЫШЛО`);

if (IMPROVE > 0) {
  console.log(`\n«Улучшить» (платно, ${IMPROVE} шт.): рендер → нейросеть тем же конвейером`);
  for (const r of rows.filter((x) => x.ok).slice(0, IMPROVE)) {
    const t0 = Date.now();
    const o = await jpost("/api/render", { render_key: r.key, async: 1, quality: "realistic", room: { w: 1, d: 1 }, items: [{ role: "x" }] });
    if (o.status !== 200) { console.log(`  ${r.id}: заказ улучшения отклонён ${o.status} ${JSON.stringify(o.body)}`); continue; }
    let v;
    for (;;) {
      v = (await jget("/api/job?id=" + o.body.job)).body;
      // готовое улучшение (конвейер нейросети) — без поля status: есть shots/url; ошибка — error
      if (!v || v.status === "done" || v.status === "error" || v.error || v.shots || v.url) break;
      await sleep(5000);
    }
    const sec = ((Date.now() - t0) / 1000).toFixed(0);
    console.log(`  ${r.id}: ${v?.error ? "ОШИБКА " + v.error : "готово"} за ${sec} с · вход: ${JSON.stringify(v?.input ?? null)}`);
    // кадры улучшения приходят встроенными (FRAME_INLINE: `frames` = имя файла → base64) либо по адресу
    if (v?.shots) for (const s of v.shots) {
      const name = String(s.url).split("/").pop();
      if (v.frames?.[name]) fs.writeFileSync(path.join(OUT, `${r.id}.improved.${s.camera}.jpg`), Buffer.from(v.frames[name], "base64"));
      else if (/^https?:/.test(s.url) || String(s.url).startsWith("/api/")) {
        const img = await fetch(String(s.url).startsWith("http") ? s.url : P(s.url));
        if (img.ok) fs.writeFileSync(path.join(OUT, `${r.id}.improved.${s.camera}.jpg`), Buffer.from(await img.arrayBuffer()));
      }
    }
  }
}
console.log("\nкадры:", OUT);
