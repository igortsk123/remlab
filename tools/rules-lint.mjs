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
//   RULES-LIMIT      (T-20261127-175/6, Fable 27 § 2) действующих правил (active+trial) больше предела (limits.max_active, 20): новое не пропускаем,
//                    пока одно не слито или не снято
//   RULES-MANUAL     «вручную» (enforcement: только manual) без поля `counter:` — счётчик, который это ручное проверяет (имя, не заглушка; путь
//                    в нём должен существовать); режим warn|error и дата включения ошибки — manual.mode / manual.error_from в конфиге
//   RULES-VIOLATIONS журнал нарушений `.memory_bank/rules/violations.jsonl` ({id,date,what}; запись — `--add-violation P-NNN "что"`): id должен
//                    быть правилом; «вручную» с ≥ manual.max_violations (2) нарушений — ошибка: автопроверка (enforcement ≠ manual) или слить/снять
import { readFileSync, existsSync, readdirSync, appendFileSync } from "node:fs";
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
  limits: { max_active: 20, count_statuses: ["active", "trial"] },
  manual: { mode: "error", max_violations: 2 },
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
  return {
    cfg: {
      ...DEFAULT_CONFIG,
      ...j,
      budget: { ...DEFAULT_CONFIG.budget, ...(j.budget || {}) },
      limits: { ...DEFAULT_CONFIG.limits, ...(j.limits || {}) },
      manual: { ...DEFAULT_CONFIG.manual, ...(j.manual || {}) },
    },
  };
}

// «Вручную» без автоматики: все части enforcement (через ; , +) — manual. Смешанные («manual;script:…») автоматику имеют.
export function isPureManual(enforcement) {
  const parts = (enforcement || "").split(/[;,+]/).map((s) => s.trim()).filter(Boolean);
  return parts.length > 0 && parts.every((p) => /^manual\b/i.test(p));
}

const COUNTER_PLACEHOLDER = /^(—|-|–|нет|none|n\/a|manual|вручную|tbd|todo)$/i;
const PATH_TOKEN = /[\p{L}\p{N}_@.\/-]+\.(?:py|mjs|js|sh|json|jsonl|md|yml|yaml)(?![\p{L}\p{N}_])/gu;

// Счётчик «вручную»: назван (не пусто, не заглушка) и — если ссылается на путь внутри репозитория — путь существует. Возвращает null или причину.
export function counterProblem(counter, root) {
  const c = (counter || "").trim();
  if (!c) return "поле counter: пусто — назови счётчик, который проверяет это ручное правило";
  if (c.length < 4 || COUNTER_PLACEHOLDER.test(c)) return `counter «${c}» — заглушка, назови счётчик (например «rules_guard: просрочено» или «violations.jsonl»)`;
  for (const m of c.matchAll(PATH_TOKEN)) {
    const p = m[0];
    if (p.startsWith("~") || p.startsWith("/") || p.startsWith("http")) continue;
    if (/^violations\.jsonl$/.test(p)) continue; // журнал нарушений — создаётся при первой записи
    if (!existsSync(join(root, p)) && !existsSync(join(root, ".memory_bank", "rules", p))) return `counter ссылается на «${p}», а такого файла в репозитории нет`;
  }
  return null;
}

const VIOLATIONS_FILE = (root) => join(root, ".memory_bank", "rules", "violations.jsonl");

// Журнал нарушений: [{id,date,what}], ошибки разбора — отдельно (строка журнала битая → ошибка линтера, а не молчаливый пропуск)
export function readViolations(root) {
  const f = VIOLATIONS_FILE(root);
  const items = [];
  const bad = [];
  if (!existsSync(f)) return { items, bad };
  read(f).split("\n").forEach((line, i) => {
    if (!line.trim()) return;
    try {
      const o = JSON.parse(line);
      if (!o || typeof o.id !== "string") throw new Error("нет id");
      items.push(o);
    } catch {
      bad.push(i + 1);
    }
  });
  return { items, bad };
}

// Записать нарушение правила: id должен быть действующим правилом. → {count, max, manual, over}
export function addViolation(root, id, what, today) {
  root = resolve(root);
  const f = join(root, ".memory_bank", "rules", `${id}.md`);
  if (!P_ID.test(id) || !existsSync(f)) throw new Error(`правила ${id} нет в .memory_bank/rules/`);
  const fm = parseFrontmatter(read(f));
  if (!["active", "trial"].includes(fm.rule_status || "")) throw new Error(`${id}: rule_status «${fm.rule_status}» — нарушение записывается только действующему правилу`);
  if (!what || !what.trim()) throw new Error("нужно описание нарушения (что именно, где)");
  appendFileSync(VIOLATIONS_FILE(root), JSON.stringify({ id, date: today || todayISO(), what: what.trim() }) + "\n");
  const { cfg } = loadConfig(root);
  const count = readViolations(root).items.filter((x) => x.id === id).length;
  const manual = isPureManual(fm.enforcement);
  return { count, max: cfg.manual.max_violations, manual, over: manual && count >= cfg.manual.max_violations };
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

// Директор по шапке плана: первая строка «Директор: <машина> …» в .memory_bank/plan-zadach.md (имя машины — первое слово).
export function planDirector(root) {
  const f = join(root, ".memory_bank", "plan-zadach.md");
  if (!existsSync(f)) return null;
  const m = read(f).match(/^Директор:\s*([\p{L}\p{N}_-]+)/mu);
  return m ? m[1].toLowerCase() : null;
}

// Строки с упоминанием «директор» + имя машины — не то, что в шапке плана. Исторические/оговорённые строки пропускаются.
const STALE_MARK = /устарел|снят[оа]?\b|было\b|раньше|прежн|истори|до \d{1,2}\.\d{2}|если\b|подхват|вместо/i;
export function staleDirectorLines(text, machines, director) {
  const out = [];
  const names = machines.map((x) => x.toLowerCase());
  const alt = names.map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  if (!alt) return out;
  const a = new RegExp(`директор[^.;\\n]{0,30}?(?:—|–|-|:|=|на|у)\\s*\`?(${alt})\\b`, "i");
  const b = new RegExp(`\\b(${alt})\\b\`?\\s*(?:—|–|-|=)\\s*(?:новый\\s+)?директор`, "i");
  text.split("\n").forEach((line, i) => {
    const m = line.match(a) || line.match(b);
    if (!m || m[1].toLowerCase() === director) return;
    // оговорка («устарело», «было», «до 23.11»…) — только рядом с упоминанием: длинная строка правила её чужим словом не гасится
    const near = line.slice(Math.max(0, m.index - 50), m.index + m[0].length + 40);
    if (STALE_MARK.test(near)) return;
    out.push({ line: i + 1, said: m[1].toLowerCase(), text: line.trim().slice(0, 110) });
  });
  return out;
}

const minSet = (s, withDay) => {
  const set = new Set([...s.matchAll(/(\d+)\s*мин/g)].map((m) => Number(m[1])));
  if (withDay) for (const m of s.matchAll(/(?:днём|днем|ночью)\s*(\d+)/g)) set.add(Number(m[1]));
  return set;
};

function staleWarnings(root, rules, cfg) {
  const out = [];
  const machines = cfg.stale?.machines || [];
  const director = planDirector(root);
  const gone = (r) => ["superseded", "retired"].includes(r.fm.rule_status || "");
  if (machines.length && director) {
    const files = rules.filter((r) => !gone(r)).map((r) => ({ rel: `rules/${r.file}`, full: join(root, ".memory_bank", "rules", r.file) }));
    files.push({ rel: "CLAUDE.md", full: join(root, "CLAUDE.md") });
    const rd = join(root, ".claude", "rules");
    if (existsSync(rd)) for (const n of readdirSync(rd).filter((x) => x.endsWith(".md")).sort()) files.push({ rel: `.claude/rules/${n}`, full: join(rd, n) });
    for (const f of files) {
      if (!existsSync(f.full)) continue;
      for (const x of staleDirectorLines(read(f.full), machines, director))
        out.push(`RULES-STALE ${f.rel}:${x.line} — директор «${x.said}», а в шапке plan-zadach.md «Директор: ${director}»: «${x.text}»`);
    }
  }
  for (const r of rules) {
    if (gone(r)) continue;
    const trig = r.fm.trigger || "";
    const title = (read(join(root, ".memory_bank", "rules", r.file)).match(/^# .*$/m) || [""])[0];
    const tm = minSet(title, false);
    const gm = minSet(trig, true);
    if (tm.size && gm.size && [...gm].some((n) => !tm.has(n)))
      out.push(`RULES-STALE rules/${r.file} — trigger «${trig}» называет минуты {${[...gm].join(",")}}, в заголовке {${[...tm].join(",")}}`);
  }
  return out;
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

  // 3б) T-20261127-175/6 (Fable 27 § 2): предел числа действующих, счётчик у «вручную», журнал нарушений
  {
    const counted = rules.filter((r) => cfg.limits.count_statuses.includes(r.fm.rule_status || ""));
    if (counted.length > cfg.limits.max_active)
      errors.push(`RULES-LIMIT действующих правил (${cfg.limits.count_statuses.join("+")}) ${counted.length} > ${cfg.limits.max_active}: новое не пропускается, пока одно не слито или не снято`);
    const mm = cfg.manual;
    const manualAsError = mm.mode === "warn" && mm.error_from && today >= mm.error_from ? true : mm.mode !== "warn";
    const viol = readViolations(root);
    for (const n of viol.bad) errors.push(`RULES-VIOLATIONS violations.jsonl:${n} — строка не разбирается (нужен JSON {id,date,what})`);
    const byRule = new Map();
    for (const v of viol.items) {
      if (!byId.has(v.id)) errors.push(`RULES-VIOLATIONS violations.jsonl — нарушение несуществующего правила ${v.id}`);
      else byRule.set(v.id, (byRule.get(v.id) || 0) + 1);
    }
    for (const r of counted) {
      if (!isPureManual(r.fm.enforcement)) continue;
      const why = counterProblem(r.fm.counter, root);
      if (why) {
        const when = !manualAsError && mm.error_from ? ` — режим warn, станет ошибкой с ${mm.error_from}` : "";
        (manualAsError ? errors : warnings).push(`RULES-MANUAL ${r.file} — «вручную» без счётчика: ${why}${when}`);
      }
      const nv = byRule.get(r.fm.id) || 0;
      if (nv >= mm.max_violations)
        errors.push(`RULES-VIOLATIONS ${r.file} — «вручную» нарушено ${nv} раз (предел ${mm.max_violations}): сделать автопроверку (enforcement ≠ manual, с ссылкой на код) или слить/снять правило`);
    }
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
    // всегда-в-контексте индекс держит только действующие; снятые (superseded/retired) — история в реестре (свод 23.11)
    const gone = ["superseded", "retired"].includes(byId.get(id).fm.rule_status || "");
    if (existsSync(opIdx) && !opRows.has(id) && !gone) errors.push(`RULES-INDEX ${id} — нет строки в .claude/rules/00-operating-index.md`);
    if (existsSync(opIdx) && opRows.has(id) && gone) warnings.push(`RULES-INDEX ${id} — снятое правило в 00-operating-index.md (держать только действующие)`);
  }
  for (const id of regRows.keys()) if (!byId.has(id)) errors.push(`RULES-INDEX ${id} — строка в rules/INDEX.md, а файла правила нет`);
  for (const id of opRows) if (!byId.has(id)) errors.push(`RULES-INDEX ${id} — строка в 00-operating-index.md, а файла правила нет`);
  for (const [id, st] of regRows) {
    const r = byId.get(id);
    if (r && st !== (r.fm.rule_status || "")) errors.push(`RULES-INDEX ${id} — статус в rules/INDEX.md «${st}» ≠ в файле «${r.fm.rule_status}»`);
  }

  // 6б) устаревшие имена и числа (T-20261123-23, п.3; только предупреждения): машина-директор в тексте правил — как в шапке плана;
  // минуты в trigger — те же, что в заголовке правила (P-020: «5/30» в заголовке, «15 мин» в trigger)
  for (const w of staleWarnings(root, rules, cfg)) warnings.push(w);

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
  const vi = args.indexOf("--add-violation"); // --add-violation P-NNN "что нарушено" → строка в violations.jsonl (T-175/6)
  const positional = args.filter(
    (a, i) => !a.startsWith("--") && !(i > 0 && args[i - 1] === "--today") && !(vi >= 0 && (i === vi + 1 || i === vi + 2))
  );
  const root = resolve(positional[0] ?? process.cwd());
  if (vi >= 0) {
    try {
      const r = addViolation(root, args[vi + 1] || "", args[vi + 2] || "", ti >= 0 ? args[ti + 1] : undefined);
      console.log(`[rules-lint] записано: ${args[vi + 1]} — нарушений ${r.count}${r.manual ? ` из ${r.max} допустимых при «вручную»` : ""}`);
      if (r.over) console.log(`[rules-lint] ⚠ предел достигнут: сделать автопроверку или слить/снять ${args[vi + 1]} (иначе --check упадёт)`);
      process.exit(0);
    } catch (e) {
      console.log(`[rules-lint] ✗ ${e.message}`);
      process.exit(2);
    }
  }
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
