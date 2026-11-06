#!/usr/bin/env node
// АУДИТ ЦВЕТОВ ДЛЯ ВОПРОСА 3 ОПРОСА-ЗНАКОМСТВА (onb-02 Т2/Т4, ADR-0330). Только чтение сборки витрины (`demo-data.json`).
// По 5 опубликованным стилям: предметы набора (`variants[].items/decor[].sku`) → 4 семейства цвета (словарь и пороги —
// `tools/scout/rules/quiz.json` `palettes`), доля семейства в стиле, и для каждого предмета — в какие семейства его можно
// перекрасить цветами той же модели (лента роли по `msid` — то же правило, что `index.html:colourFam`).
//   node tools/ops/quiz-colour-audit.mjs --data ~/scout-scenes/flat215-demo/demo-data.json [--items] [--dist] [--json out.json]
// `--dist` — перебор всех сочетаний ответов (1–2 фото × 0–2 цвета) правилом `quizPick`: как часто стиль попадает в тройку.
import { createHash } from "node:crypto";
import { readFileSync, statSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// QUIZPICK — чистые функции подбора живут в странице демо (onb-03 перенёс блок дословно): аудит берёт их оттуда же, что и тест
// `tests/unit/quiz-pick.test.ts` и цепочка `tools/scout/tests_chain.py`, — одна копия правила на всех
const QUIZ_PAGE = fileURLToPath(new URL("../scout/flat215-demo/index.html", import.meta.url));
const QUIZ_SRC = readFileSync(QUIZ_PAGE, "utf8");
const { quizColourOf, quizStyleColours, quizPick, quizSim, quizMainFam } = new Function(
  `${QUIZ_SRC.slice(QUIZ_SRC.indexOf("// QUIZPICK START"), QUIZ_SRC.indexOf("// QUIZPICK END"))};return {quizColourOf,quizStyleColours,quizPick,quizSim,quizMainFam};`,
)();

const HERE = fileURLToPath(new URL(".", import.meta.url));
const ROLE_FEED = (role) => String(role || "").replace(/\s+\d+$/, "");
const STYLE_IDS = { "сканди": "scandi", "современный": "modern", "минимализм": "minimal", "лофт": "loft", "неоклассика": "neoclassic", "джапанди": "japandi" };

function args(argv) {
  const a = { data: "", rule: `${HERE}../scout/rules/quiz.json`, items: false, dist: false, json: "" };
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i];
    if (k === "--data") a.data = argv[++i];
    else if (k === "--rule") a.rule = argv[++i];
    else if (k === "--items") a.items = true;
    else if (k === "--dist") a.dist = true;
    else if (k === "--json") a.json = argv[++i];
  }
  if (!a.data) { console.error("нужен --data <demo-data.json>"); process.exit(2); }
  return a;
}

// цвета модели в ленте роли — копия правила `index.html:colourFam` (та же модель `msid`, только с фото, первым — сам товар)
function colourFam(D, sku, role) {
  if (!sku || !sku.name) return [];
  const m = sku.msid || sku.sid || sku.name, feed = (D.feeds && D.feeds[ROLE_FEED(role)]) || [];
  const same = feed.filter((p) => p.img && (p.msid || p.sid || p.name) === m), seen = new Set([sku.name]);
  const out = [same.find((p) => p.name === sku.name) || sku];
  same.forEach((p) => { if (!seen.has(p.name)) { seen.add(p.name); out.push(p); } });
  return out.length > 1 ? out : [];
}

function styleIdOf(v) { return v.style_id || STYLE_IDS[String(v.style || "").trim().toLowerCase()] || ""; }

function audit(D, rule) {
  const pal = rule.palettes, fams = pal.families;
  const incomplete = new Set((D.incomplete_styles || []).map((x) => STYLE_IDS[x.style] || x.style));
  const styles = [];
  for (const v of D.variants || []) {
    if (v.mine || v.cid || (v.room_id && v.room_id !== "living")) continue;
    const id = styleIdOf(v); if (!id || incomplete.has(id) || styles.some((s) => s.id === id)) continue;
    const rows = [];
    for (const x of [...(v.items || []), ...(v.decor || [])]) {
      const sku = x.sku; if (!sku || !sku.name) continue;
      const c = quizColourOf(sku, pal), main = quizMainFam(c);
      const src = String(sku.colour_en || "").trim() && main && quizColourOf({ colour_en: sku.colour_en }, pal)[main] ? "colour_en"
        : main && quizColourOf({ name: sku.name }, pal)[main] ? "name" : main ? "swatch" : "—";
      const fam = colourFam(D, sku, x.role);
      const reach = new Set(fam.slice(1).map((p) => quizMainFam(quizColourOf(p, pal))).filter((f) => f && f !== main));
      rows.push({ role: x.role, name: sku.name, colour_en: sku.colour_en || "", swatch: sku.swatch || "", main, src, colours: fam.length, reach: [...reach] });
    }
    const share = quizStyleColours(v, pal);
    const recolour = Object.fromEntries(fams.map((f) => [f, rows.filter((r) => r.reach.includes(f)).length]));
    styles.push({ id, title: v.title || v.style, variant: v.id, items: rows.length, noColour: rows.filter((r) => !r.main).length,
      swatch: rows.filter((r) => r.swatch).length, multi: rows.filter((r) => r.colours > 1).length, share, recolour, rows });
  }
  return { styles, incomplete: [...incomplete] };
}

function combos(list, max) {
  const out = [[]];
  for (let k = 1; k <= max; k++) {
    const rec = (start, acc) => { if (acc.length === k) { out.push(acc.slice()); return; } for (let i = start; i < list.length; i++) { acc.push(list[i]); rec(i + 1, acc); acc.pop(); } };
    rec(0, []);
  }
  return out;
}

function dist(rule, styles) {
  const ids = styles.map((s) => s.id), sc = Object.fromEntries(styles.map((s) => [s.id, s.share]));
  const photoSets = combos(ids, 2).filter((p) => p.length), colourSets = combos(rule.palettes.families, 2);
  const hit = Object.fromEntries(ids.map((i) => [i, 0])), third = Object.fromEntries(ids.map((i) => [i, 0]));
  let total = 0;
  for (const p of photoSets) for (const c of colourSets) {
    const r = quizPick(rule, { photos: p, colours: c }, ids, sc); total++;
    r.forEach((id) => { hit[id]++; if (!p.includes(id)) third[id]++; });
  }
  return { total, photoSets: photoSets.length, colourSets: colourSets.length,
    pct: Object.fromEntries(ids.map((i) => [i, Math.round((hit[i] / total) * 1000) / 10])), added: third };
}

function main() {
  const a = args(process.argv);
  const raw = readFileSync(a.data), D = JSON.parse(raw.toString("utf8")), rule = JSON.parse(readFileSync(a.rule, "utf8"));
  const sha = createHash("sha256").update(raw).digest("hex").slice(0, 12), mtime = statSync(a.data).mtime.toISOString();
  const A = audit(D, rule), fams = rule.palettes.families, pct = (x) => `${Math.round(x * 100)} %`;
  console.log(`данные: ${a.data} · изменён ${mtime} · sha256 ${sha} · правило ${rule.version}`);
  console.log(`стилей в витрине: ${A.styles.length}; исключены (incomplete_styles): ${A.incomplete.join(", ") || "—"}\n`);
  console.log(`стиль        | предм | без цвета | swatch | >1 цвета | ${fams.map((f) => f.padEnd(6)).join(" | ")} | перекрасить в ${fams.join("/")}`);
  for (const s of A.styles) {
    console.log(`${s.id.padEnd(12)} | ${String(s.items).padStart(5)} | ${String(s.noColour).padStart(9)} | ${String(s.swatch).padStart(6)} | ${String(s.multi).padStart(8)} | ` +
      `${fams.map((f) => pct(s.share[f]).padEnd(6)).join(" | ")} | ${fams.map((f) => s.recolour[f]).join("/")}`);
  }
  if (a.items) for (const s of A.styles) {
    console.log(`\n== ${s.id}`);
    for (const r of s.rows) console.log(`  ${r.role.padEnd(15)} ${(r.main || "—").padEnd(6)} ${r.src.padEnd(9)} цветов ${String(r.colours).padStart(2)} → ${r.reach.join(",") || "—"} | ${r.colour_en || r.swatch || ""} | ${r.name.slice(0, 60)}`);
  }
  console.log("\nближе всего палитре (доля, тройка):");
  for (const f of fams) console.log(`  ${f.padEnd(6)}: ${A.styles.slice().sort((x, y) => y.share[f] - x.share[f]).slice(0, 3).map((s) => `${s.id} ${pct(s.share[f])}`).join(", ")}`);
  let D2 = null;
  if (a.dist) {
    D2 = dist(rule, A.styles);
    console.log(`\nраспределение итогов: ${D2.photoSets} наборов фото × ${D2.colourSets} наборов цветов = ${D2.total}`);
    for (const id of Object.keys(D2.pct)) console.log(`  ${id.padEnd(12)} в тройке ${String(D2.pct[id]).padStart(5)} % · добавлен как «похожий» ${D2.added[id]} раз`);
    const bad = Object.entries(D2.pct).filter(([, p]) => p < 5 || p > 80);
    console.log(bad.length ? `  ⚠ вне 5–80 %: ${bad.map(([i, p]) => `${i} ${p} %`).join(", ")} — правило переделать` : "  ok: каждый стиль 5–80 % троек");
  }
  if (a.json) writeFileSync(a.json, JSON.stringify({ data: a.data, mtime, sha, rule: rule.version, ...A, dist: D2 }, null, 1));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();

export { quizColourOf, quizStyleColours, quizPick, quizSim, audit, dist };
