#!/usr/bin/env node
// РАКУРСЫ ОКНА ВАРИАНТА — В ДАННЫЕ ВИТРИНЫ (план demo-05 п.8). Окно демо выбирает два ракурса правилами страницы (блок
// CAMFIT в `tools/scout/flat215-demo/index.html`, `camPair`), а /flat их не знал — режим «Фото» там был пустым текстом.
// Скрипт исполняет ТОТ ЖЕ блок страницы по каждому варианту и пишет `v.cams = [C1, C2]` (+ `v.cam_level`) в demo-data.json:
// одна функция — один выбор для окна и для /flat. Зовёт сборка демо (`flat215_demo.py`) перед записью данных.
// С demo-22 у каждого вида — окно превью `crop[<пропорция>] = {x,y,w,h,keep}` (доли кадра) и у варианта — отчёт покрытия
// `cam_cover` (что из мебели не видно ни в одном виде и почему); тот же отчёт печатается в лог сборки.
// ОДНА ПАРА НА ВСЕ СТИЛИ (demo-31, владелец 02.11): данные с одной расстановкой на все варианты (`D.one_layout`, ставит
// `flat215_demo.py`) — пара подбирается ОДИН раз по мебели всех вариантов (`camPairAll`: точка годна, если чиста в каждом, ключ —
// худший), у всех вариантов те же точки (x, y, rot, fov); окно превью и сдвиг телефона — по мебели своего варианта. Ставит
// `D.cams_shared` — страница по нему не пересчитывает точки после замены товара (`index.html:defaultCams`).
//   node tools/flat3d/demo-cams.mjs <demo-data.json>        дописать ракурсы на месте
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const html = readFileSync(join(ROOT, "tools/scout/flat215-demo/index.html"), "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const file = process.argv[2];
if (!file) {
  console.error("нужен путь к demo-data.json");
  process.exit(2);
}
const D = JSON.parse(readFileSync(file, "utf8"));
// блок страницы читает D.room (двери для правила «не у двери») — отдаём те же данные
const api = new Function("D", `${block}\n;return {camPair, camPairAll};`)(D);
const W = D.room.w;
const H = D.room.d;
const p = 3; // как `camPad()` страницы и клэмп сервера
const corners = [{ x: p, y: p }, { x: W - p, y: p }, { x: W - p, y: H - p }, { x: p, y: H - p }];
let n = 0;
const vars = D.variants ?? [];
const itsOf = (v) => (v.items ?? []).map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 }));
const shared = !!D.one_layout && vars.length > 1;
const all = shared ? api.camPairAll(vars.map(itsOf), W, H, corners) : null;
if (shared) console.log(`одна пара на ${vars.length} вариантов: ${all.how}`);
D.cams_shared = shared;
for (const [vi, v] of vars.entries()) {
  const pr = shared ? { ...all, ...(all.per?.[vi] ?? {}) } : api.camPair(itsOf(v), W, H, corners);
  v.cams = pr.cams.map((c) => ({ name: c.name, x: Math.round(c.x), y: Math.round(c.y), rot: Math.round(c.rot || 0), fov: c.fov || 72, pose: 2,
    // подбор парой (demo-12, ADR-0304, по умолчанию с 17.10) несёт сдвиг вертикального кадра телефона
    ...(typeof c.pshift === "number" ? { pshift: c.pshift } : {}), ...(c.crop ? { crop: c.crop } : {}) }));
  v.cam_level = pr.level;
  v.cam_cover = { covered: (pr.covered ?? []).length, missing: (pr.missing ?? []).map((m) => ({ id: m.id, role: m.role, must: m.must, reason: m.reason })) };
  console.log(`${v.id}: ${pr.how ?? ""}${(pr.missing ?? []).length ? ` — не видно: ${pr.missing.map((m) => `${m.role} (${m.reason})`).join(", ")}` : ""}`);
  n += 1;
}
writeFileSync(file, JSON.stringify(D, null, 1));
console.log(`ракурсы окна в данных: вариантов ${n} (${(D.variants ?? []).map((v) => `${v.id} ступень ${v.cam_level}`).join(", ")})`);
