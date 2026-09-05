#!/usr/bin/env node
// split-decisions.mjs — разрезает .memory_bank/decisions.md на индекс + тома по блокам номеров.
// Запуск: node split-decisions.mjs [--apply] [--root /path] [--today YYYY-MM-DD] [--next 0180]
// Без --apply — только отчёт (dry-run). Тела ADR переносятся байт в байт; меняется только строка заголовка.
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";

const args = process.argv.slice(2);
const flag = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const APPLY = args.includes("--apply");
const ROOT = flag("--root", process.cwd());
const TODAY = flag("--today", new Date().toISOString().slice(0, 10));
const NEXT_START = parseInt(flag("--next", "0"), 10); // первый свободный номер для дублей (0 = max+1)
const MB = join(ROOT, ".memory_bank");
const SRC = flag("--src", join(MB, "decisions.md"));
const OUT = join(MB, "decisions.md");
const sha = (s) => createHash("sha256").update(s).digest("hex").slice(0, 16);

const raw = readFileSync(SRC, "utf8");
const lines = raw.split("\n");
const h2 = [];
lines.forEach((l, i) => { if (/^## /.test(l)) h2.push(i); });
const preamble = lines.slice(0, h2[0]).join("\n");
const recs = h2.map((start, k) => {
  const end = k + 1 < h2.length ? h2[k + 1] : lines.length;
  const heading = lines[start];
  const body = lines.slice(start + 1, end).join("\n");
  return { order: k, heading, body };
});

// --- id / date / title ---
const reA = /^## \[(\d{4}-\d{2}-\d{2})\]\s*(.*)$/;          // [дата] Название — ADR-NNNN (…)
const reB = /^## ADR-(\d{4})\s*—\s*(.*)$/;                  // ADR-NNNN — дата — Название | ADR-NNNN — Название (дата)
for (const r of recs) {
  let m;
  if ((m = r.heading.match(reB))) {
    r.id = m[1];
    let rest = m[2];
    let d = rest.match(/^(\d{4}-\d{2}-\d{2})\s*—\s*(.*)$/);
    if (d) { r.date = d[1]; r.title = d[2]; }
    else {
      const d2 = rest.match(/\((\d{4}-\d{2}-\d{2})\)\s*$/) || rest.match(/(\d{4}-\d{2}-\d{2})/);
      r.date = d2 ? d2[1] : null;
      r.title = rest.replace(/\s*\((\d{4}-\d{2}-\d{2})\)\s*$/, "").trim();
    }
    r.fmt = "B";
  } else if ((m = r.heading.match(reA))) {
    r.date = m[1];
    const rest = m[2];
    const ids = [...rest.matchAll(/ADR-(\d{4})/g)].map((x) => x[1]);
    r.id = ids.length ? ids[ids.length - 1] : "0000";
    // убрать хвост « — ADR-NNNN…» из названия
    r.title = rest.replace(/\s*—\s*ADR-\d{4}.*$/, "").replace(/\s*\(ADR-\d{4}[^)]*\)\s*$/, "").trim();
    r.fmt = "A";
  } else {
    r.id = "0000"; r.date = null; r.title = r.heading.replace(/^## /, ""); r.fmt = "?";
  }
  r.title = r.title.replace(/\s+/g, " ").trim();
}
// даты-пробелы: взять из тела (**Дата:**) или предыдущей записи
let prevDate = "2026-07-01";
for (const r of recs) {
  if (!r.date) {
    const bm = r.body.match(/\*\*Дата:\*\*\s*(\d{4}-\d{2}-\d{2})/) || r.body.match(/\((\d{4}-\d{2}-\d{2})\)/) || r.body.match(/(\d{4}-\d{2}-\d{2})/);
    r.date = bm ? bm[1] : prevDate; r.dateGuessed = !bm;
  }
  prevDate = r.date;
}

// --- дубли: первый сохраняет номер, следующие получают новые ---
const seen = new Map();
const maxId = Math.max(...recs.map((r) => parseInt(r.id, 10)));
let next = NEXT_START || maxId + 1;
const renumbered = [];
for (const r of recs) {
  if (r.id === "0000") { r.newId = "0000"; continue; }
  if (!seen.has(r.id)) { seen.set(r.id, r); r.newId = r.id; continue; }
  r.newId = String(next++).padStart(4, "0");
  r.legacyOf = r.id;
  renumbered.push(r);
}

// --- тема по словарю ---
const TOPICS = [
  ["инфра", /deploy|деплой|docker|compose|caddy|exit-fi|hetzner|swap|\btls|arm64|git-workflow|github|\bci\b|автодеплой|vds|секрет|\benv\b|права проекта|autopilot|\bкит\b|хук|скрипты проекта|прод-схем|бэкап|публикация на прод/i],
  ["смета", /смет|калькулят|плитк|обо[ия]|краск|ламинат|проём|расчёт|лаборатор|сохранял|ссылк|парсинг|чтение ссылок|сопутк|материал|NumInput|FindCheaper/i],
  ["реклама", /директ|реклам|кампани|минус-слов|ставк|\bлид|tg-бот|найдём дешевле|семантик|автопилот/i],
  ["каталог", /каталог|фид|гдеслон|наличи|товар|обогащен|цен[аы] из|артикул|api гдеслона|nonton|footprint|размер|честност|роль товара|стиль товара|медиа товара|фото товар|hd-фото|карточк/i],
  ["меши", /меш|salad|hunyuan|trellis|нод[аы]|пул|тариф|batch|приёмник|dino|образ hunyuan|3d-модел|3d подставл|ориентац|сторож денег|очеред|транспорт|стопор/i],
  ["расстановка", /расстанов|зон|солвер|шаблон|канон|доктрин|ярус|дверь|ковёр|диван|обеденн|фокус-стен|ось|свод №|рефери|аудит юли|экзамен|residual|режимн|модификатор|проход|входная зона|посадк|галере/i],
  ["визуализация", /визуализац|рендер|кадр|демо|панорам|генерац|gpt-image|inpaint|вырезк|фон|маск|scene3d|растеризатор|затенение|крапин|проплешин|set-of-mark|подсказка модели|топвью|планировщик|конструктор|цвет меш|перепокраск|экспозиц/i],
  ["стили-сеты", /сет|стил|паспорт|витрин|подтип|судь[яи]|композиц|ценов/i],
  ["память-процесс", /память|memory|блокнот|adr|план|процесс|codex|рефери принят|батч-дисциплин|платное|пробной парти|публикац|владельц/i],
  ["трейсинг", /трейсинг|observab|posthog|sentry|лог|метрик|наблюдаем|дайджест|telegram/i],
  ["kb-знания", /source kb|kb\b|книг|датасет|3d-front|holodeck|политика чисел|судьи раскладок/i],
  ["данные", /бд|postgres|pgvector|схем|миграц|drizzle|zod|store|in-memory|модел[ьи] placement|контракт|поле|hung/i],
  ["продукт", /пивот|стек проекта|концепц|бизнес|freemium|affiliate|stage 1|продуктов|навигац|разделы|фейков|провайдер ии|gemini|llm-канал|ai gateway/i],
];
const OVERRIDES = JSON.parse(flag("--overrides", "{}"));
for (const r of recs) {
  const probe = r.title + " " + r.body.slice(0, 400);
  const hits = TOPICS.map(([t, re]) => [t, (probe.match(re) || []).length]).filter((x) => x[1] > 0);
  // приоритет: совпадение в заголовке
  const titleHits = TOPICS.filter(([t, re]) => re.test(r.title)).map((x) => x[0]);
  r.topic = titleHits[0] || (hits.sort((a, b) => b[1] - a[1])[0] || ["прочее"])[0];
  if (OVERRIDES[r.newId]) r.topic = OVERRIDES[r.newId];
}
if (args.includes("--list")) { for (const r of recs) console.log(`${r.newId}\t${r.topic}\t${r.title.slice(0, 95)}`); }
// --- отменяет / уточняет ---
for (const r of recs) {
  const m = [...r.body.matchAll(/(отменяет|заменяет|superseded|уточняет|расширяет|дополняет|доп\. к|откат)\s*(?:ADR-)?(\d{4})/gi)];
  r.rel = [...new Set(m.map((x) => `${x[1].toLowerCase()} ADR-${x[2]}`))].filter((s) => !s.endsWith(`ADR-${r.newId}`)).slice(0, 3);
}

// --- тома ---
const vol = (id) => { const n = parseInt(id, 10); return n <= 50 ? "0001-0050" : n <= 100 ? "0051-0100" : n <= 150 ? "0101-0150" : "0151-0200"; };
const byVol = new Map();
for (const r of recs) { const v = vol(r.newId); if (!byVol.has(v)) byVol.set(v, []); byVol.get(v).push(r); }
for (const list of byVol.values()) list.sort((a, b) => parseInt(a.newId, 10) - parseInt(b.newId, 10) || a.order - b.order);

// --- отчёт ---
console.log(`записей: ${recs.length}; уникальных id до: ${seen.size + (recs.some((r) => r.id === "0000") ? 1 : 0)}; дублей: ${renumbered.length}; max id: ${String(maxId).padStart(4, "0")}`);
console.log(`формат A: ${recs.filter((r) => r.fmt === "A").length}, B: ${recs.filter((r) => r.fmt === "B").length}, ?: ${recs.filter((r) => r.fmt === "?").length}; дата угадана: ${recs.filter((r) => r.dateGuessed).length}`);
for (const r of renumbered) console.log(`  дубль ADR-${r.legacyOf} → ADR-${r.newId}: ${r.title.slice(0, 70)}`);
for (const [v, list] of byVol) console.log(`  том ${v}: ${list.length}`);
const topicCount = {}; for (const r of recs) topicCount[r.topic] = (topicCount[r.topic] || 0) + 1;
console.log("темы:", JSON.stringify(topicCount));
for (const r of recs.filter((r) => r.topic === "прочее")) console.log(`  прочее: ADR-${r.newId} ${r.title.slice(0, 80)}`);
for (const r of recs.filter((r) => r.dateGuessed)) console.log(`  дата угадана: ADR-${r.newId} ${r.title.slice(0, 60)} → ${r.date}`);
const hashBefore = sha(recs.map((r) => r.body).join("\n "));
console.log("sha тел (до):", hashBefore);

if (!APPLY) { console.log("dry-run: файлы не записаны"); process.exit(0); }

// --- запись томов ---
mkdirSync(join(MB, "decisions"), { recursive: true });
const volMeta = { "0001-0050": "historical", "0051-0100": "historical", "0101-0150": "historical", "0151-0200": "supporting" };
for (const [v, list] of byVol) {
  const [a, b] = v.split("-");
  const lastDate = list.map((r) => r.date).sort().pop();
  const fm = `---
tier: 2
topic: decisions-${v}
scope: Полные тексты ADR-${a}…${b} — читать по номеру из decisions.md (индекс)
tier1: ../decisions.md
updated: ${lastDate}
importance: high
source: manual
status: stable
source_of_truth: ${volMeta[v]}
last_verified: ${TODAY}
review_after: ""
---

# Решения — том ADR-${a}…${b}

> Полные тексты решений, перенесены дословно из \`decisions.md\` ${TODAY} (менялась только строка
> заголовка: единый формат \`ADR-NNNN — дата — название\`). Навигация и «действующие решения по
> темам» — в \`../decisions.md\`. Новое решение дописывать в ТЕКУЩИЙ том (см. \`README.md\`).

`;
  const parts = list.map((r) => {
    const legacy = r.legacyOf ? `\n> **Legacy-номер:** до ${TODAY} эта запись шла под номером ADR-${r.legacyOf} (дубль с другим решением); ссылки на ADR-${r.legacyOf} в текстах до этой даты могут относиться к ней.\n` : "";
    return `## ADR-${r.newId} — ${r.date} — ${r.title}${legacy}\n${r.body}`;
  });
  writeFileSync(join(MB, "decisions", `adr-${v}.md`), fm + parts.join("\n"));
}

// --- индекс ---
const topicsOrder = ["продукт", "смета", "реклама", "каталог", "меши", "визуализация", "расстановка", "стили-сеты", "kb-знания", "данные", "инфра", "трейсинг", "память-процесс", "прочее"];
const topicLine = (t) => {
  const ids = recs.filter((r) => r.topic === t).map((r) => `ADR-${r.newId}`);
  return ids.length ? `- **${t}** (${ids.length}): ${ids.join(", ")}` : null;
};
const blocks = [...byVol.entries()].map(([v, list]) => {
  const [a, b] = v.split("-");
  const rows = list.map((r) => {
    const rel = r.rel.length ? ` · ${r.rel.join("; ")}` : "";
    const leg = r.legacyOf ? ` · (быв. ADR-${r.legacyOf})` : "";
    return `- **ADR-${r.newId}** · ${r.date} · ${r.topic} · ${r.title}${leg}${rel}`;
  });
  return `### ADR-${a}…${b} — том [[decisions-${v}]] (\`decisions/adr-${v}.md\`)\n\n${rows.join("\n")}`;
});
const ra = new Date(TODAY); ra.setDate(ra.getDate() + 90);
const index = `---
tier: 1
topic: decisions
scope: ADR-лог — индекс решений с обоснованием и влиянием; полные тексты в decisions/ (тома по номерам)
tier2: decisions/README.md
updated: ${TODAY}
importance: high
source: manual
status: stable
source_of_truth: canonical
last_verified: ${TODAY}
review_after: ${ra.toISOString().slice(0, 10)}
---

# Decisions — индекс ADR

> **Как читать.** Одна строка на решение: номер · дата · тема · название · связи. Полный текст —
> в томе по номеру: \`decisions/adr-0001-0050.md\`, \`adr-0051-0100.md\`, \`adr-0101-0150.md\`,
> \`adr-0151-0200.md\` (текущий). Новое решение: следующий свободный номер (см. \`decisions/README.md\`),
> полный текст — в текущий том, строка — сюда в блок и в «По темам». Номера не переиспользуются;
> отменённое решение не стирается, а помечается новым ADR со словом «отменяет ADR-NNNN».
> Реструктуризация ${TODAY}: тексты перенесены дословно, 7 дублей номеров получили новые номера
> (помечены «быв. ADR-…»).

## По темам (какие решения действуют)

${topicsOrder.map(topicLine).filter(Boolean).join("\n")}

## Хронологический список по томам

${blocks.join("\n\n")}
`;
writeFileSync(OUT, index);

// --- README тома ---
writeFileSync(join(MB, "decisions", "README.md"), `# decisions/ — тома ADR (полные тексты)

Индекс и «по темам» — \`../decisions.md\` (canonical). Здесь — дословные тексты по блокам номеров:

| Том | Номера | Статус |
|-----|--------|--------|
| \`adr-0001-0050.md\` | ADR-0000…0050 | закрыт (historical) |
| \`adr-0051-0100.md\` | ADR-0051…0100 | закрыт (historical) |
| \`adr-0101-0150.md\` | ADR-0101…0150 | закрыт (historical) |
| \`adr-0151-0200.md\` | ADR-0151…0200 | **текущий** — новые записи сюда |

**Новое решение:** (1) номер = последний в индексе + 1 (никогда не переиспользовать; проверка —
\`node tools/memory-project-audit.mjs\`); (2) в текущий том — \`## ADR-NNNN — YYYY-MM-DD — Название\`
и тело по схеме Решение/Почему/Альтернативы/Влияет на; (3) в \`../decisions.md\` — строка в блок
тома и номер в «По темам». Когда текущий том заполнится до 0200 — завести \`adr-0201-0250.md\`.

**Legacy:** 7 записей ${TODAY} перенумерованы (дубли номеров), у них в теле пометка «Legacy-номер».
Полные тексты ранних ADR-0001…0006/0013/0014 из \`docs/DECISIONS.md\` — приложение в конце
\`adr-0001-0050.md\`.
`);

// --- проверка после ---
const after = [];
for (const v of byVol.keys()) {
  const t = readFileSync(join(MB, "decisions", `adr-${v}.md`), "utf8");
  const ls = t.split("\n"); const hs = []; ls.forEach((l, i) => { if (/^## ADR-/.test(l)) hs.push(i); });
  hs.forEach((s, k) => {
    const e = k + 1 < hs.length ? hs[k + 1] : ls.length;
    let body = ls.slice(s + 1, e).join("\n");
    body = body.replace(/^> \*\*Legacy-номер:\*\*[^\n]*\n\n/, "");
    after.push({ id: ls[s].match(/ADR-(\d{4})/)[1], body });
  });
}
const byId = new Map(recs.map((r) => [r.newId, r]));
let mismatch = 0;
for (const a of after) { const r = byId.get(a.id); if (!r || r.body !== a.body) { mismatch++; console.log("MISMATCH", a.id); } }
console.log(`после: записей в томах ${after.length}, уникальных id ${new Set(after.map((a) => a.id)).size}, несовпадений тел: ${mismatch}`);
console.log(`индекс: ${Buffer.byteLength(index)} байт`);
