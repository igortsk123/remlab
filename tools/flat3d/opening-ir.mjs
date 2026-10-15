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
  stdin: { contents: 'export { openingIR, viewRooms, wallRects } from "@/lib/viewer3d/opening-ir"; export { windowView } from "@/lib/viewer3d/window-views"; export { wallFixturesIR, ceilingLampIR } from "@/lib/viewer3d/fixtures-ir"; export { finishPassport } from "@/lib/viewer3d/finish-passport";',
    resolveDir: ROOT, loader: "ts" },
  bundle: true, format: "esm", platform: "node", write: false, alias: { "@": ROOT }, absWorkingDir: ROOT, logLevel: "warning",
});
const { openingIR, viewRooms, wallRects, windowView, wallFixturesIR, ceilingLampIR, finishPassport } = await import("data:text/javascript;base64," + Buffer.from(res.outputFiles[0].text).toString("base64"));

const room = JSON.parse(readFileSync(process.argv[2], "utf8"));
const W = +room.w, D = +room.d, H = +(room.height_cm ?? 270);
// вид из окна — по карточке квартиры (`room.window_view`, ночная сборка); плоскость вида не выходит за концы стены и
// середину простенка — места считаются по проёмам той же стены, как в браузере (`openings.ts:buildOpenings`)
const { id: viewId, view } = windowView(room.window_view);
const out = [];
const prepared = [];
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
  prepared.push({ op, len });
}
for (const { op, len } of prepared) {
  const same = prepared.filter((p) => p.op.wall === op.wall).map((p) => p.op);
  const room0 = viewRooms(same, len)[same.indexOf(op)];
  // серверный кадр — всегда одна комната: двери закрыты, как в живой сцене демо (`viewer.ts:buildShell`, doorsClosed)
  out.push({ wall: op.wall, ir: openingIR(op, { wallHeightCm: H, entrance: !process.argv.includes("--open"),
    view: { assetId: viewId, horizon01: view.horizon01, aspect: view.aspect }, viewRoomLo: room0.lo, viewRoomHi: room0.hi }) });
}
// --finish: готовый паспорт отделки (карточка квартиры поверх набора по умолчанию) — им же красит серверный кадр
if (process.argv.includes("--finish")) {
  process.stdout.write(JSON.stringify(finishPassport(room.finish)) + "\n");
  process.exit(0);
}
// --fixtures: плинтус и карниз по стенам (куски стены — та же `wallRects`, что у браузера) и светильник комнаты (demo-04 п.6)
if (process.argv.includes("--fixtures")) {
  const fx = [];
  for (const side of ["south", "north", "west", "east"]) {
    const same = prepared.filter((p) => p.op.wall === side).map((p) => p.op);
    const len = side === "north" || side === "south" ? W : D;
    const wins = same.filter((o) => o.kind === "window" || o.kind === "balcony").map((o) => openingIR(o, { wallHeightCm: H }).cut);
    fx.push({ wall: side, boxes: wallFixturesIR(wallRects(len, H, same), wins, H) });
  }
  fx.push({ wall: "room", boxes: ceilingLampIR(W, D, H) });
  process.stdout.write(JSON.stringify(fx) + "\n");
} else {
  process.stdout.write(JSON.stringify(out) + "\n");
}
