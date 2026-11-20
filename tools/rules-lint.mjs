#!/usr/bin/env node
// rules-lint — линтер реестра правил работы P-NNN (план rules-registry-01, шаг 5; T-20261120-148/3).
// Project-owned, без зависимостей (Node >= 18, ESM). Тест: tests/rules-lint.test.mjs (`node --test`).
// Вызывается: отдельно (`node tools/rules-lint.mjs [--check] [root]`), из tools/memory-project-audit.mjs (категория RULES-*)
// и из CI-шага «memory-project-audit». Пороги, словари и режимы — ДАННЫМИ: .memory_bank/rules/lint-config.json.
//
// Категории (error → exit 1; warning → печатается):
//   RULES-ID         id не P-NNN, не совпадает с именем файла, дубль id
//   RULES-STATUS     rule_status вне словаря плана / status вне словаря аудита памяти
//   RULES-APPROVAL   у active нет approval_ref (TG-номер или `legacy:<источник>`)
//   RULES-SUPERSEDE  supersedes/superseded_by ведут на несуществующее P, цикл, superseded без superseded_by, ссылки несогласованы
//   RULES-TRIAL      trial с истёкшим review_after (или без него); (warning) active с истёкшим review_after
//   RULES-INDEX      P нет в rules/INDEX.md или в .claude/rules/00-operating-index.md, лишние строки, статус в INDEX ≠ файлу
//   RULES-BUDGET     постоянный слой (CLAUDE.md + .memory_bank/INDEX.md + .claude/rules/*.md без paths:) > лимита;
//                    режим error|warn и дата включения ошибки — в конфиге; с MEMORY.md авто-памяти — отдельное предупреждение
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";

const todayISO = () => new Date().toISOString().slice(0, 10);
const DEFAULT_CONFIG = {
  rule_status_vocab: ["active", "trial", "suspended", "superseded", "retired"],
  status_vocab: ["draft", "working", "stable", "stale", "deprecated", "archived"],
  budget: {
    limit_kb: 20,
    without_memory: { mode: "error" },
    with_memory: { mode: "warn" },
    memory_md_candidates: [],
  },
};
const P_ID = /^P-\d{3}$/;
// основание правила: TG-номер (допустимо «TG tamara 842»), номер ADR или `legacy:<источник>`
const APPROVAL = /\bTG\b[^;,\n]*\d|\bADR-\d{3,4}\b|\blegacy:\S/i;

const read = (f) => readFileSync(f, "utf8").replace(/^﻿/, "").replace(/\r\n/g, "\n");

export function parseFrontmatter(text) {
  if (!text.startsWith("---\n")) return {};
  const end = text.indexOf("\n---", 4);
  if (end < 0) return {};
  const fm = {};
  for (const line of text.slice(4, end).split("\n")) {
    const m = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (m) fm[m[1]] = m[2].trim().replace(/^["']|["']$/g, "");
  }
  return fm;
}

const ids = (v) => (v || "").split(/[\s,;]+/).filter(Boolean);

function loadConfig(root) {
  const f = join(root, ".memory_bank", "rules", "lint-config.json");
  if (!existsSync(f)) return { cfg: DEFAULT_CONFIG, note: "lint-config.json нет — значения по умолчанию" };
  const j = JSON.parse(read(f));
  return { cfg: { ...DEFAULT_CONFIG, ...j, budget: { ...DEFAULT_CONFIG.budget, ...(j.budget || {}) } } };
}

// Постоянный слой в байтах: что уходит в каждую сессию без запроса.
export function layerBytes(root) {
  const parts = [];
  const add = (rel, full) => {
    if (existsSync(full)) parts.push({ rel, b: Buffer.byteLength(read(full), "utf8") });
  };
  add("CLAUDE.md", join(root, "CLAUDE.md"));
  add(".memory_bank/INDEX.md", join(root, ".memory_bank", "INDEX.md"));
  const rd = join(root, ".claude", "rules");
  if (existsSync(rd))
    for (const n of readdirSync(rd).sort().filter((x) => x.endsWith(".md"))) {
      const text = read(join(rd, n));
      const head = text.startsWith("---") ? text.slice(0, text.indexOf("\n---", 3) + 1) : "";
      if (/^paths:/m.test(head)) continue;
      parts.push({ rel: `.claude/rules/${n}`, b: Buffer.byteLength(text, "utf8") });
    }
  return parts;
}

function memoryMdBytes(cfg, root) {
  const cands = [process.env.RULES_LINT_MEMORY_MD, ...(cfg.budget.memory_md_candidates || [])].filter(Boolean);
  for (const c of cands) {
    const p = c.replace(/^~(?=\/)/, homedir());
    if (existsSync(p)) return Buffer.byteLength(read(p), "utf8");
  }
  return null;
}

// opts: { today, memoryMd: bytes|null|undefined (undefined — искать по конфигу) }
export function lintRules(root, opts = {}) {
  root = resolve(root);
  const today = opts.today || todayISO();
  const errors = [];
  const warnings = [];
  const notes = [];
  const rulesDir = join(root, ".memory_bank", "rules");
  if (!existsSync(rulesDir)) return { ok: true, skipped: "нет .memory_bank/rules", errors, warnings, notes, count: 0 };
  const { cfg, note } = loadConfig(root);
  if (note) notes.push(note);

  // ---- читаем P-файлы
  const rules = [];
  for (const n of readdirSync(rulesDir).sort()) {
    if (!/^P-.*\.md$/.test(n)) continue;
    const fm = parseFrontmatter(read(join(rulesDir, n)));
    rules.push({ file: n, name: n.slice(0, -3), fm });
  }

  // 1) id
  const seen = new Map();
  for (const r of rules) {
    const id = r.fm.id || "";
    if (!P_ID.test(id)) errors.push(`RULES-ID ${r.file} — id «${id || "—"}» не формата P-NNN`);
    else if (id !== r.name) errors.push(`RULES-ID ${r.file} — id ${id} не совпадает с именем файла`);
    if (id) {
      if (seen.has(id)) errors.push(`RULES-ID ${r.file} — дубль id ${id} (уже в ${seen.get(id)})`);
      else seen.set(id, r.file);
    }
  }
  const byId = new Map(rules.filter((r) => P_ID.test(r.fm.id || "")).map((r) => [r.fm.id, r]));

  // 2) словари; 3) approval_ref; 5) trial
  for (const r of rules) {
    const f = r.fm;
    const rs = f.rule_status || "";
    if (!cfg.rule_status_vocab.includes(rs))
      errors.push(`RULES-STATUS ${r.file} — rule_status «${rs || "—"}» вне словаря {${cfg.rule_status_vocab.join(", ")}}`);
    if (!cfg.status_vocab.includes(f.status || ""))
      errors.push(`RULES-STATUS ${r.file} — status «${f.status || "—"}» вне словаря аудита памяти {${cfg.status_vocab.join(", ")}}`);
    if (rs === "active" && !APPROVAL.test(f.approval_ref || ""))
      errors.push(`RULES-APPROVAL ${r.file} — у active нет approval_ref (TG-номер или legacy:<источник>)`);
    if (rs === "trial") {
      if (!f.review_after) errors.push(`RULES-TRIAL ${r.file} — trial без review_after (срок пробы обязателен)`);
      else if (f.review_after < today) errors.push(`RULES-TRIAL ${r.file} — срок пробы истёк (${f.review_after} < ${today}): включить как active, продлить или снять`);
    }
    if (rs === "active" && f.review_after && f.review_after < today)
      warnings.push(`RULES-TRIAL ${r.file} — review_after ${f.review_after} истёк — пересмотреть правило`);
  }

  // 4) supersedes / superseded_by
  const next = new Map(); // A → B: A заменено B
  const edge = (a, b) => {
    if (!next.has(a)) next.set(a, new Set());
    next.get(a).add(b);
  };
  for (const r of rules) {
    const id = r.fm.id;
    const by = ids(r.fm.superseded_by);
    const sup = ids(r.fm.supersedes);
    for (const x of [...by, ...sup])
      if (!byId.has(x)) errors.push(`RULES-SUPERSEDE ${r.file} — ссылка на несуществующее ${x}`);
    for (const b of by) {
      edge(id, b);
      const back = byId.get(b);
      if (back && !ids(back.fm.supersedes).includes(id))
        errors.push(`RULES-SUPERSEDE ${r.file} — superseded_by ${b}, но у ${b} нет supersedes: ${id}`);
    }
    for (const a of sup) {
      edge(a, id);
      const back = byId.get(a);
      if (back && !ids(back.fm.superseded_by).includes(id))
        errors.push(`RULES-SUPERSEDE ${r.file} — supersedes ${a}, но у ${a} нет superseded_by: ${id}`);
    }
    if (r.fm.rule_status === "superseded" && !by.length)
      errors.push(`RULES-SUPERSEDE ${r.file} — rule_status superseded без superseded_by`);
    if (by.includes(id) || sup.includes(id)) errors.push(`RULES-SUPERSEDE ${r.file} — ссылка на себя`);
  }
  {
    const state = new Map(); // 1 — в стеке, 2 — готово
    const stack = [];
    const reported = new Set();
    const dfs = (n) => {
      state.set(n, 1);
      stack.push(n);
      for (const m of next.get(n) || []) {
        if (state.get(m) === 1) {
          const cyc = [...stack.slice(stack.indexOf(m)), m];
          const key = [...cyc.slice(0, -1)].sort().join(",");
          if (!reported.has(key)) {
            reported.add(key);
            errors.push(`RULES-SUPERSEDE цикл замен: ${cyc.join(" → ")}`);
          }
        } else if (!state.get(m)) dfs(m);
      }
      stack.pop();
      state.set(n, 2);
    };
    for (const n of [...next.keys()].sort()) if (!state.get(n)) dfs(n);
  }

  // 6) индексы
  const regIdx = join(rulesDir, "INDEX.md");
  const opIdx = join(root, ".claude", "rules", "00-operating-index.md");
  const regRows = new Map();
  if (existsSync(regIdx)) {
    for (const line of read(regIdx).split("\n")) {
      const m = line.match(/^\|\s*\[(P-\d{3})\]\([^)]*\)\s*\|\s*[^|]*\|\s*([^|]*?)\s*\|/);
      if (m) regRows.set(m[1], m[2]);
    }
  } else errors.push("RULES-INDEX .memory_bank/rules/INDEX.md — файла нет");
  const opRows = new Set();
  if (existsSync(opIdx)) {
    for (const line of read(opIdx).split("\n")) {
      const m = line.match(/^(P-\d{3})\s·\s/);
      if (m) opRows.add(m[1]);
    }
  } else errors.push("RULES-INDEX .claude/rules/00-operating-index.md — файла нет");
  for (const id of byId.keys()) {
    if (existsSync(regIdx) && !regRows.has(id)) errors.push(`RULES-INDEX ${id} — нет строки в .memory_bank/rules/INDEX.md`);
    if (existsSync(opIdx) && !opRows.has(id)) errors.push(`RULES-INDEX ${id} — нет строки в .claude/rules/00-operating-index.md`);
  }
  for (const id of regRows.keys()) if (!byId.has(id)) errors.push(`RULES-INDEX ${id} — строка в rules/INDEX.md, а файла правила нет`);
  for (const id of opRows) if (!byId.has(id)) errors.push(`RULES-INDEX ${id} — строка в 00-operating-index.md, а файла правила нет`);
  for (const [id, st] of regRows) {
    const r = byId.get(id);
    if (r && st !== (r.fm.rule_status || "")) errors.push(`RULES-INDEX ${id} — статус в rules/INDEX.md «${st}» ≠ в файле «${r.fm.rule_status}»`);
  }

  // 7) бюджет постоянного слоя
  const layer = layerBytes(root);
  const total = layer.reduce((s, x) => s + x.b, 0);
  const limit = Math.round(cfg.budget.limit_kb * 1024);
  const kb = (b) => (b / 1024).toFixed(1);
  const top = [...layer].sort((a, b) => b.b - a.b).slice(0, 4).map((x) => `${x.rel} ${kb(x.b)}`).join(", ");
  const wm = cfg.budget.without_memory || {};
  const modeNow = wm.mode === "warn" && wm.error_from && today >= wm.error_from ? "error" : wm.mode || "error";
  let budget = { layerBytes: total, limit, mode: modeNow, memoryBytes: null };
  if (total > limit) {
    const when = modeNow === "warn" && wm.error_from ? ` — режим warn, станет ошибкой с ${wm.error_from}` : "";
    const msg = `RULES-BUDGET постоянный слой (CLAUDE.md + INDEX.md + .claude/rules без paths:) ${kb(total)}KB > ${cfg.budget.limit_kb}KB (${top})${when}`;
    (modeNow === "error" ? errors : warnings).push(msg);
  }
  const mem = opts.memoryMd !== undefined ? opts.memoryMd : memoryMdBytes(cfg, root);
  if (mem != null) {
    budget.memoryBytes = mem;
    const lw = Math.round((cfg.budget.with_memory?.limit_kb ?? cfg.budget.limit_kb) * 1024);
    if (total + mem > lw)
      warnings.push(`RULES-BUDGET слой вместе с MEMORY.md авто-памяти ${kb(total + mem)}KB (MEMORY.md ${kb(mem)}KB) > ${kb(lw)}KB — ужать MEMORY.md (шаг 4 плана rules-registry-01)`);
  }
  notes.push(`правил: ${rules.length}; слой ${kb(total)}KB из ${cfg.budget.limit_kb}KB${mem != null ? `; с MEMORY.md ${kb(total + mem)}KB` : "; MEMORY.md не найден (в CI нормально)"}`);
  return { ok: errors.length === 0, errors, warnings, notes, count: rules.length, budget };
}

// ---------- CLI ----------
const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const args = process.argv.slice(2);
  const ti = args.indexOf("--today");
  const positional = args.filter((a, i) => !a.startsWith("--") && !(i > 0 && args[i - 1] === "--today"));
  const root = resolve(positional[0] ?? process.cwd());
  const res = lintRules(root, { today: ti >= 0 ? args[ti + 1] : undefined });
  console.log(`[rules-lint] root=${root}`);
  if (res.skipped) {
    console.log(`[rules-lint] пропуск: ${res.skipped}`);
    process.exit(0);
  }
  for (const n of res.notes) console.log(`[rules-lint] ${n}`);
  if (res.warnings.length) {
    console.log(`[rules-lint] ⚠ предупреждений: ${res.warnings.length}`);
    for (const w of res.warnings) console.log("  ~ " + w);
  }
  if (res.ok) {
    console.log("[rules-lint] ✓ ошибок нет");
    process.exit(0);
  }
  console.log(`[rules-lint] ✗ ошибок: ${res.errors.length}`);
  for (const e of res.errors) console.log("  - " + e);
  process.exit(1);
}
