#!/usr/bin/env node
// ОПИСАНИЕ ПРОЁМОВ КОМНАТЫ ДЛЯ СЕРВЕРНОГО КАДРА (план demo-04 п.2). Генератор один — `lib/viewer3d/opening-ir.ts`
// (тот же, что строит окна и двери в браузере); здесь он запускается в Node над комнатой витрины и печатает
// `[{wall, ir}]` — координаты вдоль стены уже в соглашении браузера (`rooms.ts:openingsOnSide`: у north/west отступ
// зеркалится). Ночная сборка кладёт это в `demo-data.json` → `room.openings_ir`, сервер берёт оттуда
// (`tools/scout/opening_ir.py`).
//   node tools/flat3d/opening-ir.mjs room.json        → JSON в stdout
//   … --open                                           → межкомнатные двери распахнуты (эталон теста, /flat)
import { build } from "esbuild";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const res = await build({
  stdin: { contents: 'export { openingIR } from "@/lib/viewer3d/opening-ir";', resolveDir: ROOT, loader: "ts" },
  bundle: true, format: "esm", platform: "node", write: false, alias: { "@": ROOT }, absWorkingDir: ROOT, logLevel: "warning",
});
const { openingIR } = await import("data:text/javascript;base64," + Buffer.from(res.outputFiles[0].text).toString("base64"));

const room = JSON.parse(readFileSync(process.argv[2], "utf8"));
const W = +room.w, D = +room.d, H = +(room.height_cm ?? 270);
const out = [];
for (const o of room.openings ?? []) {
  if (!o.width_cm || !o.wall) continue;
  const len = o.wall === "north" || o.wall === "south" ? W : D;
  const offset = o.wall === "north" || o.wall === "west" ? len - o.offset_cm - o.width_cm : o.offset_cm;
  const kind = ["window", "door", "opening", "balcony"].includes(o.kind) ? o.kind : "door";
  // петли: страница пишет start|end, расстановщик — left|right (оба — от начала отступа); у north/west после зеркала — другой конец
  const atEnd = o.hinge === "end" || o.hinge === "right";
  const mirrored = o.wall === "north" || o.wall === "west";
  const op = { kind, wall: o.wall, offsetCm: offset, widthCm: o.width_cm, hinge: atEnd !== mirrored ? "right" : "left",
    ...(o.into === false || o.swing_cm === 0 ? { swingCm: 0 } : {}),
    ...(o.sill_cm !== undefined ? { sillCm: o.sill_cm } : {}), ...(o.height_cm !== undefined ? { heightCm: o.height_cm } : {}) };
  // серверный кадр — всегда одна комната: двери закрыты, как в живой сцене демо (`viewer.ts:buildShell`, doorsClosed)
  out.push({ wall: o.wall, ir: openingIR(op, { wallHeightCm: H, entrance: !process.argv.includes("--open") }) });
}
process.stdout.write(JSON.stringify(out) + "\n");
