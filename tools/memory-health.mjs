#!/usr/bin/env node
// memory-health — краткая сводка «работает ли механизм точности памяти» (кит v1.9; пилот sup2 27–28.09).
//
//   node tools/memory-health.mjs [--since YYYY-MM-DD]          — сводка на один экран
//   node tools/memory-health.mjs --log-verify <док> --claims N --mismatch M --fixed F --reason code|drift|rotation|backtest|eval [--note "…"]
//                                                              — строка в журнал сверок (зовёт /memory-check, этап 1.6)
//
// Источники: .memory_bank/changelog/verify-log.tsv (сверки, в git), code-touch-hint.log (подсказки хука, локально),
// drift-report.log (эксперимент --drift-report, локально), memory-eval.log (замеры «с памятью / без», в git),
// git-история строк `last_verified:` (механическая сверка: дату двигали без записи сверки?), шапки core/*.md.
import { readFileSync, appendFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const root = process.cwd();
const CH = join(root, ".memory_bank", "changelog");
const VLOG = join(CH, "verify-log.tsv");
const VHEAD = "date\tdoc\treason\tclaims\tmismatch\tfixed\tnote\n";
const REASONS = new Set(["code", "drift", "rotation", "backtest", "eval"]);
const args = process.argv.slice(2);
const arg = (k) => {
  const i = args.indexOf(k);
  return i >= 0 ? args[i + 1] : undefined;
};
const today = () => new Date().toISOString().slice(0, 10);
const lines = (f) => (existsSync(f) ? readFileSync(f, "utf8").split(/\r?\n/).filter((l) => l.trim()) : []);

if (args[0] === "--log-verify") {
  const doc = args[1];
  const n = (k) => Number(arg(k) ?? NaN);
  const reason = arg("--reason");
  const [c, mm, fx] = [n("--claims"), n("--mismatch"), n("--fixed")];
  // Целые ≥ 0 и исправлено ≤ найдено ≤ утверждений — иначе сводка «сколько ловим» врёт.
  if (!doc || !REASONS.has(reason) || [c, mm, fx].some((x) => !Number.isInteger(x) || x < 0) || fx > mm || mm > c) {
    console.error("использование: --log-verify <док> --claims N --mismatch M --fixed F --reason code|drift|rotation|backtest|eval [--note …]\n  N, M, F — целые ≥ 0, F ≤ M ≤ N");
    process.exit(2);
  }
  if (!existsSync(VLOG)) appendFileSync(VLOG, VHEAD);
  const note = (arg("--note") || "").replace(/[\t\n]/g, " ");
  appendFileSync(VLOG, [today(), doc, reason, n("--claims"), n("--mismatch"), n("--fixed"), note].join("\t") + "\n");
  console.log(`записано: ${doc} — утверждений ${n("--claims")}, расхождений ${n("--mismatch")}, исправлено ${n("--fixed")} (${reason})`);
  process.exit(0);
}

const firstVerify = (lines(VLOG)[1] || "").split("\t")[0];
const since = arg("--since") || (/^\d{4}-\d{2}-\d{2}$/.test(firstVerify) ? firstVerify : new Date(Date.now() - 14 * 864e5).toISOString().slice(0, 10));
const inRange = (d) => d >= since;
const days = Math.max(1, Math.round((Date.now() - Date.parse(since)) / 864e5) + 1);
const out = [];
out.push(`Точность памяти — сводка с ${since} (${days} дн.)`);

// 1) Правки кода и подсказки хука (одна строка на первую правку файла в сессии; «-» — файл памятью не описан)
const edits = lines(join(CH, "code-touch-hint.log")).map((l) => l.split("\t")).filter((c) => c[0] && inRange(c[0].slice(0, 10)));
const hints = edits.filter((c) => c[3] && c[3] !== "-");
{
  const byDay = {};
  for (const c of hints) byDay[c[0].slice(0, 10)] = (byDay[c[0].slice(0, 10)] || 0) + 1;
  const trend = Object.keys(byDay).sort().map((d) => `${d.slice(8, 10)}.${d.slice(5, 7)} — ${byDay[d]}`).join(", ");
  const pct = edits.length ? Math.round((hints.length / edits.length) * 100) : 0;
  out.push(
    `• Правки файлов кода: ${edits.length} (сессий ${new Set(edits.map((c) => c[1])).size}); описаны в памяти — подсказка агенту: ${hints.length} (${pct}%)` +
      (trend ? ` · по дням: ${trend}` : "")
  );
}

// 2) Сверки verify: по источникам — сколько сверено, в скольких нашлись расхождения (точность сигнала), исправлено
const ver = lines(VLOG).slice(1).map((l) => l.split("\t")).filter((c) => inRange(c[0]));
{
  const rname = { code: "изменённый код", drift: "дрейф", rotation: "ротация", backtest: "бэктест", eval: "замер" };
  const by = {};
  for (const c of ver) {
    const b = (by[c[2]] ||= { n: 0, hit: 0, mm: 0, fx: 0 });
    b.n++;
    b.hit += Number(c[4]) > 0 ? 1 : 0;
    b.mm += Number(c[4]) || 0;
    b.fx += Number(c[5]) || 0;
  }
  const tot = Object.values(by).reduce((s, b) => ({ n: s.n + b.n, mm: s.mm + b.mm, fx: s.fx + b.fx }), { n: 0, mm: 0, fx: 0 });
  out.push(`• Сверено документов с кодом: ${tot.n} · расхождений найдено ${tot.mm}, исправлено ${tot.fx}, ждут исправления ${tot.mm - tot.fx}`);
  for (const [r, b] of Object.entries(by))
    out.push(`    ${rname[r] || r}: сверено ${b.n}, с расхождениями ${b.hit} (${Math.round((b.hit / b.n) * 100)}% — точность сигнала), расхождений ${b.mm}`);
}
{
  // Дату сверки двигали в git — сколько раз и без записи в журнал сверок?
  // --relative: пути от корня проекта; T00:00:00 — без времени git берёт текущее время суток.
  const r = spawnSync("git", ["-C", root, "log", "--relative", `--since=${since}T00:00:00`,
    "-p", "-U0", "--format=@@%cs", "--", ".memory_bank", ".claude/rules"], {
    encoding: "utf8",
    maxBuffer: 256 * 1024 * 1024,
  });
  const bumps = [];
  let date = null, file = null;
  for (const l of (r.stdout || "").split("\n")) {
    if (l.startsWith("@@") && !l.startsWith("@@ ")) date = l.slice(2);
    else if (l.startsWith("diff --git ")) file = (l.match(/ b\/(.+)$/) || [])[1];
    else if (file && l.startsWith("+last_verified:") && !file.includes("completed_plans/")) bumps.push({ date, doc: file.replace(/^\.memory_bank\//, "") });
  }
  const logged = new Set(ver.map((c) => `${c[0]}|${c[1].replace(/^\.memory_bank\//, "")}`));
  const unlogged = bumps.filter((b) => !logged.has(`${b.date}|${b.doc}`));
  out.push(
    `• Дата сверки сдвигалась (git): ${bumps.length} раз в ${new Set(bumps.map((b) => b.doc)).size} документах` +
      (unlogged.length ? ` · ⚠ без записи сверки: ${unlogged.length} (${[...new Set(unlogged.map((b) => b.doc))].slice(0, 4).join(", ")}${unlogged.length > 4 ? "…" : ""})` : " · все с записью сверки")
  );
}

// 3) Дрейф (эксперимент --drift-report)
{
  const dr = lines(join(CH, "drift-report.log")).map((l) => l.split(" ")).filter((c) => inRange(c[0]));
  if (dr.length) {
    const kv = (c) => Object.fromEntries(c.slice(2).map((x) => x.split("=")));
    const a = kv(dr[0]), b = kv(dr[dr.length - 1]);
    const heads = new Set(dr.map((c) => c[1])).size; // повторные прогоны одного коммита — не новые наблюдения
    out.push(`• Дрейф (эксперимент, коммитов ${heads}): код изменён после сверки у ${b.drift} доков, названия задеты у ${b.sym} (в начале: ${a.drift} / ${a.sym})`);
  } else out.push("• Дрейф (эксперимент): прогонов нет");
}

// 4) Давно не сверялись
{
  const dir = join(root, ".memory_bank", "core");
  const ign = new Set(lines(join(root, ".memory_bank", "_kit", "no-anchor-ignore.txt")).map((l) => l.replace(/#.*/, "").trim()).filter(Boolean));
  const lv = [];
  for (const f of (existsSync(dir) ? readdirSync(dir) : []).filter((x) => x.endsWith(".md") && x !== "README.md" && x !== "_template.md")) {
    if (ign.has(`core/${f}`)) continue;
    const m = readFileSync(join(dir, f), "utf8").match(/^last_verified:\s*(\d{4}-\d{2}-\d{2})/m);
    if (m) lv.push({ f, d: m[1] });
  }
  lv.sort((x, y) => x.d.localeCompare(y.d));
  const old = lv.filter((x) => (Date.now() - Date.parse(x.d)) / 864e5 > 14);
  out.push(`• Сводки о коде: ${lv.length}; не сверялись > 14 дней: ${old.length}${lv[0] ? ` · самая давняя — core/${lv[0].f} (${lv[0].d})` : ""}`);
}

// 5) Замеры «с памятью / без» (tools/memory-eval)
{
  const ev = lines(join(CH, "memory-eval.log")).slice(1).map((l) => l.split("\t"));
  if (ev.length) {
    // колонки: date commit pairs cost_mem cost_nomem crit_mem crit_nomem minor_mem minor_nomem questions note
    const f = (c) => `${c[0]}: ${c[3]} $ / ${c[4]} $, критичных ${c[5]} / ${c[6]}, некритичных ${c[7]} / ${c[8]}`;
    out.push(`• Замер «с памятью / без памяти» (сессия из 10 вопросов): ${ev.length > 1 ? `первый ${f(ev[0])}; последний ${f(ev[ev.length - 1])}` : f(ev[0])}`);
  } else out.push("• Замер «с памятью / без»: ещё не было (python3 tools/memory-eval/eval.py)");
}
if (ver.length < 5 || edits.length < 20 || days < 3)
  out.push(`⚠ Данных мало (сверок ${ver.length}, правок ${edits.length}, дней ${days}) — выводы о тренде рано.`);
{
  // Исходная точка — первая строка журнала замеров проекта (tools/memory-eval), если он есть.
  const ev0 = lines(join(CH, "memory-eval.log")).slice(1)[0];
  if (ev0) out.push(`Исходная точка: замер ${ev0.split("\t")[0]} (${(ev0.split("\t")[10] || "").slice(0, 80)}).`);
}
console.log(out.join("\n"));
