#!/usr/bin/env node
// КАРТА ПРЕДМЕТОВ КАДРА (план demo-14): для позы ракурса и расстановки — какой предмет виден в каждом пикселе. Тот же трассировщик
// лучей, что подбирает точки съёмки (`camMask`, блок CAMFIT страницы демо), та же поза v2 (глаз 135, сдвиг кадра), поэтому карта
// ложится на кадр браузера. Нужна лист-локатору («#N роль» на мебели) и замеру верности цвета (`tools/scout/refs_check.py`).
//   node tools/flat3d/cam-masks.mjs <вход.json> <выход.bin>
// вход: {room:{w,d,openings,height_cm?}, items:[…], cams:[{x,y,rot,fov,pshift?}], w, h, orient?:'portrait'}
// выход: для каждой камеры по порядку — w×h значений Int16 (номер предмета в `items` или −1), little-endian
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const html = readFileSync(join(ROOT, "tools/scout/flat215-demo/index.html"), "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const [inp, out] = process.argv.slice(2);
if (!inp || !out) {
  console.error("нужны <вход.json> <выход.bin>");
  process.exit(2);
}
const job = JSON.parse(readFileSync(inp, "utf8"));
const D = { room: job.room };
const api = new Function("D", `${block}\n;return {camMask, CAM_SHIFT_N};`)(D);
const its = (job.items ?? []).map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 }));
const parts = [];
for (const c of job.cams ?? []) {
  // сдвиг кадра: вертикальный кадр телефона — подобранный `pshift`, альбомный — поза v2 (−0.10 → 0.2 в долях −1…1)
  const sn = job.orient === "portrait" && typeof c.pshift === "number" ? -2 * c.pshift : api.CAM_SHIFT_N;
  const m = api.camMask(c, its, job.room.w, job.room.d, { w: job.w, h: job.h, sn });
  parts.push(Buffer.from(m.item.buffer));
}
writeFileSync(out, Buffer.concat(parts));
console.log(`карта предметов: камер ${parts.length}, ${job.w}×${job.h}`);
