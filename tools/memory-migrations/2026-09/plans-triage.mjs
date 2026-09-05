#!/usr/bin/env node
// plans-triage.mjs — таблица триажа планов и применение манифеста архивации.
// node plans-triage.mjs                 → таблица (dry-run), TSV в stdout
// node plans-triage.mjs --apply m.tsv   → архивирует по манифесту (slug \t action \t reason [\t superseded_by])
import { readFileSync, writeFileSync, readdirSync, existsSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, basename } from "node:path";

const ROOT = "/home/pakar/igor/remlab";
const MB = join(ROOT, ".memory_bank");
const TODAY = "2026-09-05";
const args = process.argv.slice(2);
const APPLY = args.includes("--apply");
const manifestPath = APPLY ? args[args.indexOf("--apply") + 1] : null;
const days = (d) => (d && /^\d{4}-\d{2}-\d{2}$/.test(d) ? Math.round((new Date(TODAY) - new Date(d)) / 864e5) : null);
const fm = (txt) => { const m = txt.match(/^---\n([\s\S]*?)\n---/); const o = {}; if (m) for (const l of m[1].split("\n")) { const k = l.match(/^([\w-]+):\s*(.*)$/); if (k) o[k[1]] = k[2].replace(/^"|"$/g, ""); } return o; };
const gitDate = (rel) => { try { return execFileSync("git", ["-C", ROOT, "log", "-1", "--format=%cs", "--", rel], { encoding: "utf8" }).trim(); } catch { return ""; } };

const plans = readdirSync(join(MB, "plans")).filter((n) => n.endsWith(".md") && !["README.md", "_template.md"].includes(n));
// контент-доки, где [[slug]] должны резолвиться (аудит): всё вне SKIP_DIRS и plans/
const SKIP = new Set(["_intake", "completed_plans", "archive", "changelog", "_secrets", "plans", "_kit"]);
const content = [];
(function walk(d) { for (const n of readdirSync(d, { withFileTypes: true })) { const p = join(d, n.name); if (n.isDirectory()) { if (!SKIP.has(n.name)) walk(p); } else if (n.name.endsWith(".md")) content.push(p); } })(MB);
const masters = plans.filter((n) => n.startsWith("MASTER-"));
const masterText = Object.fromEntries(masters.map((m) => [m, readFileSync(join(MB, "plans", m), "utf8")]));

const TRACK = (s) => /mesh|viz|layout|zones|sets|seating|template|solver|occupancy|entry|canon|orient|topview|photo-improve|adaptive|living-room|ergonomics|inventory|referee|exam|demo|mask|design-order|catalog|stock|gdeslon|enrich|scalab|room-size/.test(s) ? "мебель" : /calc|ads|estimate|pricing|lead|sub-e|room-measurement|unified-measure|sub-ml|deploy|cost-first/.test(s) ? "смета/инфра" : "прочее";

const rows = plans.map((n) => {
  const rel = `.memory_bank/plans/${n}`;
  const txt = readFileSync(join(MB, "plans", n), "utf8");
  const f = fm(txt);
  const slug = n.replace(/\.md$/, "");
  const age = days(f.updated) ?? days(gitDate(rel));
  const hasPause = /pause_reason:|## Пауза|\*\*Пауза/.test(txt);
  const inMasters = masters.filter((m) => m !== n && masterText[m].includes(slug));
  const linkedFrom = content.filter((p) => readFileSync(p, "utf8").includes(`[[${slug}]]`)).map((p) => p.replace(MB + "/", ""));
  return { n, slug, status: f.status || "", updated: f.updated || "", created: f.created || "", title: f.title ? "y" : "-", age, hasPause, inMasters, linkedFrom, track: TRACK(slug), goal: (txt.match(/## Цель\s*\n+([^\n]+)/) || [, ""])[1].slice(0, 90) };
});

function propose(r) {
  if (r.n.startsWith("MASTER-")) return "MASTER?";
  if (r.status === "cancelled") return "ARCHIVE:cancelled";
  if (r.status === "in_progress") return r.age <= 14 ? "KEEP" : "CHECK:in_progress>14д";
  if (r.status === "partial") return r.hasPause ? "KEEP" : r.age <= 14 ? "KEEP+pause" : "ARCHIVE:paused-no-trigger";
  if (r.status === "draft") return r.age <= 30 ? "KEEP" : "ARCHIVE:stale-draft";
  return "CHECK:status=" + r.status;
}

if (!APPLY) {
  console.log(["slug", "status", "updated", "age", "pause", "track", "in_masters", "linked_from", "proposal", "goal"].join("\t"));
  for (const r of rows.sort((a, b) => a.status.localeCompare(b.status) || (b.age ?? 0) - (a.age ?? 0)))
    console.log([r.slug, r.status, r.updated, r.age, r.hasPause ? "y" : "-", r.track, r.inMasters.map((m) => m.replace("MASTER-", "").replace(".md", "")).join(",") || "-", r.linkedFrom.length ? r.linkedFrom.length + ":" + r.linkedFrom.map((p) => basename(p)).slice(0, 3).join(",") : "-", propose(r), r.goal].join("\t"));
  console.log("\n# без title: " + rows.filter((r) => r.title === "-").map((r) => r.slug).join(", "));
  console.log("# без created: " + rows.filter((r) => !r.created).map((r) => r.slug).join(", "));
  process.exit(0);
}

// --- apply ---
const man = readFileSync(manifestPath, "utf8").split("\n").filter((l) => l.trim() && !l.startsWith("#")).map((l) => l.split("\t"));
mkdirSync(join(MB, "archive", "plans"), { recursive: true });
const archived = [];
for (const [slug, action, reason, sup] of man) {
  if (!action.startsWith("ARCHIVE")) continue;
  const src = join(MB, "plans", slug + ".md"); const dst = join(MB, "archive", "plans", slug + ".md");
  if (!existsSync(src)) { console.log("нет файла:", slug); continue; }
  if (existsSync(dst)) { console.log("уже в архиве:", slug); continue; }
  let txt = readFileSync(src, "utf8");
  txt = txt.replace(/^---\n([\s\S]*?)\n---/, (m, body) => `---\n${body}\narchived: ${TODAY}\narchived_by: memory-bank-audit-2026-09\narchive_reason: ${reason}${sup ? `\nsuperseded_by: ${sup}` : ""}\n---`);
  execFileSync("git", ["-C", ROOT, "mv", `.memory_bank/plans/${slug}.md`, `.memory_bank/archive/plans/${slug}.md`]);
  writeFileSync(dst, txt);
  archived.push(slug);
}
// перепись [[slug]] в контент-доках
let fixed = 0;
for (const p of content) {
  let t = readFileSync(p, "utf8"); const o = t;
  for (const slug of archived) t = t.split(`[[${slug}]]`).join(`\`archive/plans/${slug}.md\``);
  if (t !== o) { writeFileSync(p, t); fixed++; }
}
console.log(`архивировано: ${archived.length}; контент-доков с переписанными ссылками: ${fixed}`);
