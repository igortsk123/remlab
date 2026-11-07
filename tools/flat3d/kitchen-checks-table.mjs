#!/usr/bin/env node
// ТАБЛИЦА ПРОВЕРОК ПРИМЕРОВ КУХОНЬ (план onb-09, T-20261105-18): паспорта `data/partners/kitchen-examples/{ru,uk}.json` →
// `kitchenSpecFromExample` → `checkKitchen`: модули, треугольник (стороны, сумма), проходы, вентканал. Тот же код, что в
// продукте (собираем esbuild для node). Вывод — markdown в stdout, `--json <файл>` — ещё и данные.
//   node tools/flat3d/kitchen-checks-table.mjs [--room 311] [--json out.json]
import { build as esbuild } from "esbuild";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const args = process.argv.slice(2);
const arg = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const ROOM = Number(arg("--room", "311"));
const JSON_OUT = arg("--json");

const res = await esbuild({
  stdin: {
    contents: `import { kitchenSpecFromExample } from "@/lib/viewer3d/kits/kitchen-from-example";
import { checkKitchen } from "@/lib/viewer3d/kits/kitchen-checks";
import { kitchenLayout } from "@/lib/viewer3d/kits/kitchen-layout";
import { kitchenExamplesFile } from "@/contracts/kitchen-example";
import ru from "@/data/partners/kitchen-examples/ru.json";
import uk from "@/data/partners/kitchen-examples/uk.json";
export function run(room) {
  return [ru, uk].flatMap((f) => kitchenExamplesFile.parse(f).examples).map((e) => {
    const spec = kitchenSpecFromExample(e, { roomDepthCm: room });
    const lay = kitchenLayout(spec);
    return { id: e.id, spec, report: checkKitchen(spec), fillers: lay.fillers, sinkW: lay.slots[lay.sink]?.w, hobW: lay.slots[lay.hob]?.w,
      upper: lay.upperSlots && lay.upperSlots.map((u) => u.w).join("/") + (spec.features.includes("hood") ? " + вытяжка над варочной" : "") };
  });
}`,
    resolveDir: ROOT, loader: "ts",
  },
  bundle: true, format: "esm", platform: "node", write: false, alias: { "@": ROOT }, logLevel: "warning", absWorkingDir: ROOT,
});
// временная папка сборки убирается сразу после импорта (T-20261107-13: в /tmp их скопилось 7, 7,7 МБ)
const tmpDir = mkdtempSync(join(tmpdir(), "kitchen-table-"));
const tmp = join(tmpDir, "run.mjs");
let run;
try {
  writeFileSync(tmp, res.outputFiles[0].text);
  ({ run } = await import(pathToFileURL(tmp).href));
} finally {
  rmSync(tmpDir, { recursive: true, force: true });
}
const rows = run(ROOM);

const where = { front: "перед", "behind-island": "за островом", "leg-end": "торец плеча" };
const lines = [
  `Глубина комнаты ${ROOM} см; холодильник без колонны — отдельный 70 см вплотную у свободного конца (допущение).`,
  "",
  "| паспорт | модули низ (линия · плечо) / верх | холодильник | треугольник: мойка–варочная / варочная–холод. / холод.–мойка, сумма | проходы | вентканал | итог |",
  "|---|---|---|---|---|---|---|",
];
for (const r of rows) {
  const t = r.report.triangle;
  const tri = t.sides
    ? `${t.sides.sinkHob} / ${t.sides.hobFridge} / ${t.sides.fridgeSink}, Σ ${t.sumCm} — ${t.ok ? "проходит" : t.problems.join("; ")}`
    : t.problems.join("; ");
  const fill = r.fillers.length ? ` + добор ${r.fillers.map((f) => f.w).join("/")}` : "";
  const up = r.upper ? ` / верх ${r.upper}` : " / верх поровну";
  const mods = `${(r.spec.modulesCm ?? []).join("/")}${r.spec.legModulesCm ? ` · ${r.spec.legModulesCm.join("/")}` : ""}${fill}${up}`;
  const fridge = r.spec.features.includes("fridge") ? "в колонне" : r.spec.fridgeAtCm !== undefined ? `отдельный, s=${r.spec.fridgeAtCm}${r.spec.fridgeAssumed ? " (допущение)" : ""}` : "—";
  const aisles = r.report.aisles.map((a) => `${where[a.where]} ${a.gapCm}/${a.needCm}${a.ok ? "" : " ✗"}`).join(", ");
  const vent = r.report.vent ? `${r.report.vent.distanceCm} см${r.report.vent.ok ? "" : " ⚠"}` : "не задан";
  const warn = r.report.warnings.length ? ` · ⚠ ${r.report.warnings.join("; ")}` : "";
  const verdict = `${r.report.ok ? "ОК" : `нет: ${r.report.problems.join("; ")}`}${warn}`;
  lines.push(`| ${r.id} | ${mods} | ${fridge} | ${tri} | ${aisles} | ${vent} | ${verdict} |`);
}
console.log(lines.join("\n"));
if (JSON_OUT) writeFileSync(JSON_OUT, JSON.stringify(rows, null, 1) + "\n");
