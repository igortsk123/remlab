#!/usr/bin/env node
// ЗАМЕР ПОКРЫТИЯ РАКУРСАМИ (demo-22, критерий приёмки): каждый предмет каждого варианта — ≥ 90 % в кадре и ≥ 90 % не заслонён
// хотя бы в одном виде. Исполняет ТОТ ЖЕ блок CAMFIT страницы (`camCover`), что и подбор (`tools/flat3d/demo-cams.mjs`), по
// ракурсам из данных (`v.cams`). `--explore <id>` — что дало бы этому варианту: объектив шире 78°, точка в дверном проёме,
// третий ракурс (лучшее ДОСТИЖИМОЕ покрытие перебором всех пар/троек кандидатов, без правил кадра) и полный подбор с объективом до 84/90°.
//   node tools/flat3d/demo-cams-cover.mjs <demo-data.json> [--before <старый demo-data.json>] [--explore set11] [--json out.json]
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const html = readFileSync(join(ROOT, "tools/scout/flat215-demo/index.html"), "utf8");
const BLOCK = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const args = process.argv.slice(2);
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : null; };
const file = args[0];
if (!file || file.startsWith("--")) { console.error("нужен путь к demo-data.json"); process.exit(2); }

const FOV_LOOP = "for(const rot of rots)for(const fov of [72,78])";
if (!BLOCK.includes(FOV_LOOP)) { console.error("в CAMFIT не найден перебор объектива — скрипт устарел"); process.exit(2); }
// блок с другим набором объективов (эксперимент `--explore`); по умолчанию — как на странице
const load = (D, fovs) => new Function("D", `${fovs ? BLOCK.replace(FOV_LOOP, `for(const rot of rots)for(const fov of ${JSON.stringify(fovs)})`) : BLOCK}
;return {camPair,camCands,camCover,camUnits,camUnitQ,camRole,camId,CAM_COVER};`)(D);

const itemsOf = (v) => (v.items ?? []).map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 }));
const corners = (W, H, p = 3) => [{ x: p, y: p }, { x: W - p, y: p }, { x: W - p, y: H - p }, { x: p, y: H - p }];
const pct = (x) => `${Math.round(x * 100)}`.padStart(3);

// покрытие предметов парой ракурсов: по каждому — лучший вид, доля в кадре и незаслонённая доля
function cover(api, its, cams, W, H) {
  const cv = cams.map((c) => api.camCover({ ...c, fov: c.fov || 72 }, its, W, H));
  const units = api.camUnits(its), mustOf = new Map();
  units.forEach((u) => u.ids.forEach((i) => mustOf.set(i, u.must)));
  return its.map((it, i) => {
    const q = cv.map((x) => Math.min(x[i].inF, x[i].vis)), k = q.indexOf(Math.max(...q));
    return { id: api.camId(it, i), role: api.camRole(it), must: !!mustOf.get(i), view: cams[k]?.name ?? "—", inF: cv[k][i].inF, vis: cv[k][i].vis,
      q: q[k], ok: q[k] >= api.CAM_COVER - 1e-9 };
  });
}

function report(D, label) {
  const api = load(D), W = D.room.w, H = D.room.d, out = [];
  console.log(`\n## ${label}`);
  for (const v of D.variants ?? []) {
    const its = itemsOf(v), cams = v.cams ?? [];
    if (cams.length < 2) { console.log(`${v.id}: ракурсов в данных нет`); continue; }
    const rows = cover(api, its, cams, W, H), bad = rows.filter((r) => !r.ok), badMust = bad.filter((r) => r.must);
    console.log(`\n### ${v.id} ${v.style ?? ""} — предметов ${rows.length}, ≥ 90 % в одном виде: ${rows.length - bad.length}; ` +
      `не видно обязательных ${badMust.length}, прочих ${bad.length - badMust.length}` +
      ` | ${cams.map((c) => `${c.name} (${c.x},${c.y}) ${c.rot}° fov ${c.fov}`).join(" · ")}`);
    console.log("предмет                  обяз  вид  в кадре  не заслонён  итог");
    for (const r of rows) console.log(`${(r.role + " ").padEnd(24).slice(0, 24)} ${r.must ? " да " : " —  "}  ${r.view.padEnd(3)}  ${pct(r.inF)} %    ${pct(r.vis)} %       ${r.ok ? "OK" : "НЕТ"}`);
    out.push({ id: v.id, style: v.style, items: rows.length, ok: rows.length - bad.length, mustMissing: badMust.map((r) => r.role), optMissing: bad.filter((r) => !r.must).map((r) => r.role), rows });
  }
  return out;
}

// ЧТО ДОСТИЖИМО: лучшая пара / тройка по битам покрытия (все кандидаты, без правил кадра) и полный подбор с объективом шире
function explore(D, vid) {
  const v = (D.variants ?? []).find((x) => x.id === vid);
  if (!v) { console.log(`--explore: варианта ${vid} нет`); return null; }
  const W = D.room.w, H = D.room.d, its = itemsOf(v), res = { id: vid, runs: [] };
  console.log(`\n## ${vid} ${v.style ?? ""} — что дают объектив шире, точка в проёме, третий ракурс`);
  for (const fovs of [[72, 78], [72, 78, 84], [72, 78, 84, 90]]) {
    const api = load(D, fovs), units = api.camUnits(its);
    const must = units.map((u, k) => (u.must ? k : -1)).filter((k) => k >= 0);
    const base = api.camCands(its, W, H, corners(W, H)), door = api.camCands(its, W, H, corners(W, H), true);
    for (const [nm, all] of [["углы и стены", base], ["+ точка в дверном проёме", base.concat(door)]]) {
      const Q = all.map((c) => { const cv = api.camCover(c, its, W, H); return units.map((u) => api.camUnitQ(cv, u)); });
      const miss = (sel) => must.filter((k) => !sel.some((n) => Q[n][k] >= 1 - 1e-9));
      let p2 = null, p3 = null;
      for (let a = 0; a < all.length; a++) for (let b = a + 1; b < all.length; b++) {
        if (all[a].k === all[b].k) continue;
        const m = miss([a, b]).length; if (!p2 || m < p2.m) p2 = { m, s: [a, b] };
      }
      // тройка: к лучшим парам (до 300) — третий кандидат (полный перебор троек на тысячу кандидатов слишком долог)
      if (p2.m > 0) {
        let tried = 0;
        outer: for (let a = 0; a < all.length; a++) for (let b = a + 1; b < all.length; b++) {
          if (all[a].k === all[b].k || miss([a, b]).length !== p2.m) continue;
          for (let c = 0; c < all.length; c++) { const m = miss([a, b, c]).length; if (!p3 || m < p3.m) p3 = { m, s: [a, b, c] }; }
          if ((p3 && p3.m === 0) || ++tried >= 300) break outer;
        }
      }
      const names = (s) => miss(s).map((k) => units[k].role).join(", ") || "—";
      const desc = (s) => s.map((n) => `(${Math.round(all[n].x)},${Math.round(all[n].y)}) ${all[n].rot}° ${all[n].fov}°${all[n].door ? " проём" : ""}`).join(" + ");
      const row = { fovs: fovs.join("/"), set: nm, cands: all.length, pairMissing: names(p2.s), pair: desc(p2.s), tripleMissing: p3 ? names(p3.s) : "—", triple: p3 ? desc(p3.s) : "" };
      res.runs.push(row);
      console.log(`объектив ${row.fovs}°, ${nm}: кандидатов ${all.length}; лучшая ПАРА — не видно обязательных: ${row.pairMissing} [${row.pair}]` +
        (p3 ? `; ТРОЙКА — ${row.tripleMissing} [${row.triple}]` : ""));
    }
    if (fovs.length > 2) {
      const pr = api.camPair(its, W, H, corners(W, H));
      const rows = cover(api, its, pr.cams, W, H), bad = rows.filter((r) => !r.ok);
      console.log(`  полный подбор с объективом до ${fovs.at(-1)}°: ${pr.how}; ${pr.cams.map((c) => `${c.name} ${c.fov}°`).join(" + ")}; ` +
        `не видно: ${bad.map((r) => `${r.role}${r.must ? "*" : ""}`).join(", ") || "—"}`);
      res.runs.push({ fovs: fovs.join("/"), set: "полный подбор", how: pr.how, missing: bad.map((r) => r.role), cams: pr.cams.map(({ name, x, y, rot, fov }) => ({ name, x, y, rot, fov })) });
    }
  }
  return res;
}

const D = JSON.parse(readFileSync(file, "utf8"));
const out = { after: report(D, `ракурсы ${file}`) };
if (opt("--before")) out.before = report(JSON.parse(readFileSync(opt("--before"), "utf8")), `ДО: ракурсы ${opt("--before")}`);
if (opt("--explore")) out.explore = explore(D, opt("--explore"));
if (opt("--json")) writeFileSync(opt("--json"), JSON.stringify(out, null, 1));
