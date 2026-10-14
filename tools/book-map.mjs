#!/usr/bin/env node
// Карта книги о продукте ↔ банк памяти (план book-memory-sync, ADR-0273). Находит в `guides/product-book.md`
// абзацы «Сегодня» (курсив, начинается словом «Сегодня»), связывает каждый с планами по упоминаниям `slug` и
// сообщает:
//   BOOK-STALE  — абзац ссылается только на закрытые планы (completed) → его надо переписать или снять;
//   BOOK-ORPHAN — абзац без ссылки на план → непонятно, какой план его закроет;
//   BOOK-UNKNOWN — ссылка на план, которого нет ни в plans/, ни в completed_plans/, ни в archive/plans/.
// Пишет `guides/product-book-map.json` (глава → абзацы «Сегодня» → планы и их статусы).
//   node tools/book-map.mjs            # отчёт + карта
//   node tools/book-map.mjs --check    # код 1, если есть BOOK-STALE (для свода памяти)
//   node tools/book-map.mjs --changed  # что поменяли в книге с прошлого свода (человек → банк)
//   node tools/book-map.mjs --mark     # отметка «книга разобрана» на HEAD
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const MB = path.join(ROOT, ".memory_bank");
const BOOK = path.join(MB, "guides", "product-book.md");
const OUT = path.join(MB, "guides", "product-book-map.json");

/** slug → статус по frontmatter; папка тоже говорит: completed_plans — закрыт, archive — снят. */
export function planIndex(mb = MB) {
  const idx = new Map();
  for (const [dir, dflt] of [["plans", null], ["completed_plans", "completed"], ["archive/plans", "archived"]]) {
    const d = path.join(mb, dir);
    if (!existsSync(d)) continue;
    for (const f of readdirSync(d)) {
      if (!f.endsWith(".md") || f === "README.md" || f.startsWith("_")) continue;
      const txt = readFileSync(path.join(d, f), "utf8");
      const st = (txt.match(/^status:\s*(\S+)/m) || [])[1] || dflt || "unknown";
      idx.set(f.replace(/\.md$/, ""), dflt === "archived" ? "archived" : st);
    }
  }
  return idx;
}

/** Абзацы «Сегодня» с главами и упомянутыми планами (по префиксам slug: `b2b-06` находит b2b-06-…). */
export function todayParagraphs(md, slugs) {
  const out = [];
  let chapter = "";
  const lines = md.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const h = lines[i].match(/^#{1,3}\s+(.+)/);
    if (h) chapter = h[1].trim();
    if (!/^\*Сегодня/.test(lines[i])) continue;   // без \b: в JS он не видит границ кириллицы
    let para = lines[i];
    let j = i;
    while (!/\*\s*$/.test(lines[j]) && j + 1 < lines.length && lines[j + 1].trim() !== "") para += " " + lines[++j];
    const refs = [...para.matchAll(/`([a-z0-9][a-z0-9-]+)`/g)].map((m) => m[1]);
    const plans = [...new Set(refs.flatMap((r) => slugs.filter((s) => s === r || s.startsWith(r + "-"))))];
    out.push({ line: i + 1, chapter, text: para.slice(1, 160), refs: [...new Set(refs)], plans });
    i = j;
  }
  return out;
}

export function verdicts(paras, idx) {
  return paras.map((p) => {
    const st = p.plans.map((s) => ({ slug: s, status: idx.get(s) }));
    const live = st.filter((x) => !["completed", "archived", "cancelled"].includes(x.status));
    const planRefs = p.refs.filter((r) => /^(b2b|conv)-\d/.test(r));   // имена планов очереди; `demo-uk` — файл, не план
    let v = "ok";
    if (!p.plans.length) v = planRefs.length ? "BOOK-UNKNOWN" : "BOOK-ORPHAN";
    else if (!live.length) v = "BOOK-STALE";
    return { ...p, plans: st, verdict: v };
  });
}

// ЧЕЛОВЕК → БАНК (book-memory-sync п.2): что владелец поменял в книге с прошлого свода. Отметка — хеш коммита в
// `guides/product-book.checked`; `--changed` печатает изменённые абзацы, `--mark` ставит отметку на HEAD.
const STAMP = path.join(MB, "guides", "product-book.checked");
function changed() {
  const since = existsSync(STAMP) ? readFileSync(STAMP, "utf8").trim() : "";
  if (!since) { console.log("[book-map] отметки свода нет — запусти с --mark после первого разбора"); return; }
  const out = execFileSync("git", ["-C", ROOT, "diff", "--unified=0", `${since}..HEAD`, "--", BOOK], { encoding: "utf8" });
  const add = out.split("\n").filter((l) => l.startsWith("+") && !l.startsWith("+++")).map((l) => l.slice(1)).filter((l) => l.trim());
  console.log(`[book-map] строк книги изменено с ${since.slice(0, 7)}: ${add.length}`);
  for (const l of add.slice(0, 200)) console.log("  + " + l.slice(0, 200));
}
function mark() {
  const head = execFileSync("git", ["-C", ROOT, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();
  writeFileSync(STAMP, head + "\n");
  console.log(`[book-map] отметка свода: ${head.slice(0, 7)}`);
}

function main() {
  if (process.argv.includes("--changed")) return changed();
  if (process.argv.includes("--mark")) return mark();
  const idx = planIndex();
  const rows = verdicts(todayParagraphs(readFileSync(BOOK, "utf8"), [...idx.keys()]), idx);
  writeFileSync(OUT, JSON.stringify({ generated: new Date().toISOString().slice(0, 10), paragraphs: rows }, null, 1) + "\n");
  const by = rows.reduce((a, r) => ((a[r.verdict] = (a[r.verdict] || 0) + 1), a), {});
  console.log(`[book-map] абзацев «Сегодня»: ${rows.length}; ${JSON.stringify(by)}`);
  for (const r of rows.filter((x) => x.verdict !== "ok")) {
    console.log(`  ${r.verdict} guides/product-book.md:${r.line} [${r.chapter}] ${r.plans.map((p) => `${p.slug}=${p.status}`).join(", ") || r.refs.join(",") || "—"}`);
  }
  if (process.argv.includes("--check") && by["BOOK-STALE"]) process.exit(1);
}

if (import.meta.url === `file://${process.argv[1]}`) main();
