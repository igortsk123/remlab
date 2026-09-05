// Раскладка уроков из anti-patterns.md по lessons/*.md (дословно) + карта + новый anti-patterns.md.
// Запуск: node split-lessons.mjs [--write]
import fs from 'node:fs';
import path from 'node:path';
import { readOld, parseLessons, recKey, numVal, firstWords, PART_A_LINES } from './parse.mjs';
import { TOPICS, TOPIC_ORDER, score } from './topics.mjs';

const MB = '/home/pakar/igor/remlab/.memory_bank';
const SRC = path.join(MB, 'anti-patterns.md');
const OUT_DIR = path.join(MB, 'lessons');
const SCRATCH = '/tmp/claude-1000/-home-pakar-igor-remlab/f593eb26-ea9b-4bdb-b7d3-a012811bdf1e/scratchpad/lessons';
const DATE = '2026-09-05';
const WRITE = process.argv.includes('--write');

// ---------- ручной проход: строка источника → тема (+смежные) ----------
// Формат: [from, to, 'topic', ['also', ...]] — позже перекрывает раньше.
const MANUAL = [
  [131, 155, 'devops'], [140, 140, 'devops', ['mesh']], [145, 145, 'devops', ['mesh']], [148, 148, 'devops', ['mesh']], [153, 153, 'devops', ['mesh']],
  [157, 157, 'mesh'], [159, 159, 'devops', ['mesh']], [162, 162, 'mesh', ['memory']], [165, 165, 'layout'], [166, 166, 'layout', ['devops', 'viz']], [169, 169, 'viz'],
  [171, 172, 'devops'], [173, 177, 'estimate'], [178, 178, 'devops'], [179, 181, 'estimate'], [182, 182, 'catalog'], [183, 183, 'devops'], [184, 184, 'estimate'],
  [185, 185, 'memory', ['estimate']], [186, 186, 'estimate'], [187, 187, 'memory'], [188, 188, 'estimate'], [189, 189, 'devops'],
  [193, 194, 'viz'], [195, 197, 'catalog'], [198, 198, 'devops'], [201, 201, 'layout'], [202, 202, 'memory'], [203, 203, 'devops'], [204, 206, 'viz'], [207, 207, 'catalog'],
  [210, 210, 'devops', ['catalog']], [211, 212, 'catalog'], [213, 213, 'devops'], [214, 214, 'layout'], [215, 215, 'devops'], [216, 216, 'catalog', ['layout']],
  [217, 217, 'layout', ['devops']], [218, 219, 'layout'], [220, 220, 'devops', ['memory']], [221, 222, 'layout'], [223, 223, 'devops'], [224, 224, 'layout'], [225, 225, 'layout', ['viz']],
  [226, 228, 'layout'], [229, 229, 'catalog'], [230, 230, 'viz', ['layout']], [231, 232, 'layout'], [233, 234, 'viz'],
  [237, 237, 'devops'], [238, 238, 'memory'], [239, 255, 'viz'], [252, 252, 'viz', ['memory']], [256, 256, 'catalog', ['viz']], [257, 257, 'viz'], [258, 258, 'devops', ['viz']],
  [259, 261, 'viz'], [262, 262, 'catalog', ['viz']], [263, 272, 'viz'], [273, 273, 'catalog', ['viz']], [274, 329, 'viz'], [296, 296, 'viz', ['layout']], [316, 316, 'viz', ['catalog']], [329, 329, 'viz', ['mesh']],
  [330, 330, 'mesh'], [331, 331, 'mesh', ['viz']], [332, 332, 'mesh'], [333, 335, 'viz'], [336, 337, 'layout'], [338, 338, 'viz'], [339, 339, 'layout'], [340, 342, 'viz'],
  [343, 347, 'catalog'], [348, 348, 'devops', ['catalog']], [349, 349, 'catalog'], [350, 350, 'viz'], [351, 351, 'devops', ['memory']], [352, 372, 'catalog'], [353, 353, 'catalog', ['memory']],
  [373, 373, 'memory', ['catalog']], [377, 377, 'catalog'], [379, 379, 'viz', ['memory']], [381, 401, 'layout'], [393, 393, 'layout', ['devops']], [403, 403, 'devops'], [405, 405, 'catalog'],
  [407, 411, 'layout'], [413, 413, 'catalog'], [416, 424, 'estimate'], [427, 430, 'layout'], [433, 433, 'devops'], [436, 441, 'layout'], [441, 441, 'layout', ['devops']],
  [450, 451, 'layout'], [452, 452, 'catalog', ['layout']], [453, 463, 'layout'], [463, 463, 'layout', ['catalog']], [464, 464, 'devops'], [466, 466, 'layout', ['catalog']], [467, 467, 'layout', ['catalog', 'devops']],
  [468, 468, 'catalog'], [469, 470, 'layout'], [471, 471, 'devops'], [473, 474, 'layout'], [475, 475, 'layout', ['devops']], [476, 483, 'layout'], [486, 486, 'devops', ['layout']],
  [490, 503, 'layout'], [504, 504, 'devops'], [505, 505, 'layout', ['devops']], [506, 506, 'catalog', ['layout']], [507, 516, 'layout'], [512, 512, 'layout', ['catalog']], [517, 517, 'catalog'],
  [520, 520, 'layout', ['devops']], [521, 522, 'catalog'], [523, 523, 'memory', ['catalog']], [524, 524, 'layout'], [527, 538, 'layout'], [542, 542, 'layout'], [543, 543, 'layout', ['demo']],
  [544, 544, 'layout', ['devops']], [545, 545, 'devops'], [546, 551, 'layout'], [552, 552, 'layout', ['memory']], [555, 555, 'devops', ['catalog']], [556, 565, 'layout'], [566, 566, 'catalog'], [567, 567, 'layout'],
  [570, 579, 'catalog'], [575, 576, 'catalog', ['mesh']], [580, 581, 'mesh', ['catalog']], [582, 582, 'catalog', ['layout']], [583, 583, 'catalog', ['mesh']], [584, 585, 'catalog'], [586, 586, 'catalog', ['mesh']],
  [587, 588, 'catalog'], [589, 589, 'catalog', ['mesh']], [590, 593, 'catalog'], [594, 594, 'devops', ['catalog']], [595, 596, 'mesh'], [597, 597, 'devops'], [598, 598, 'devops', ['catalog']], [599, 599, 'mesh'],
  [603, 603, 'mesh', ['devops']], [606, 609, 'mesh'], [612, 615, 'devops'], [617, 617, 'mesh', ['devops']], [621, 625, 'catalog'], [629, 634, 'mesh'], [636, 636, 'demo', ['viz']],
  [641, 648, 'mesh'], [653, 653, 'catalog'], [663, 663, 'estimate', ['catalog']], [672, 672, 'catalog'], [676, 676, 'estimate', ['catalog']], [678, 678, 'mesh'], [682, 682, 'catalog', ['memory', 'demo']],
  [688, 688, 'mesh'], [691, 691, 'devops', ['mesh']], [694, 694, 'devops', ['demo']], [698, 698, 'devops'], [702, 702, 'memory', ['catalog']], [705, 705, 'memory'], [708, 708, 'catalog'],
  [713, 713, 'mesh', ['devops']], [716, 716, 'devops', ['demo']], [718, 718, 'devops'], [720, 720, 'memory', ['catalog']], [721, 721, 'memory'], [723, 723, 'catalog'],
  [728, 728, 'mesh'], [732, 732, 'mesh', ['catalog']], [735, 735, 'devops', ['mesh']], [739, 739, 'mesh'], [742, 755, 'demo'], [758, 777, 'mesh'], [770, 770, 'mesh', ['memory']], [775, 775, 'memory', ['mesh']],
  [784, 784, 'memory'], [786, 786, 'demo'], [789, 789, 'demo', ['devops']], [791, 798, 'demo'], [804, 804, 'demo', ['layout']], [808, 808, 'demo'], [813, 818, 'mesh'],
  [825, 862, 'demo'], [850, 850, 'demo', ['mesh']], [868, 906, 'mesh'], [908, 908, 'catalog'], [912, 912, 'mesh', ['catalog']], [915, 915, 'mesh'], [918, 918, 'mesh', ['catalog']], [921, 921, 'catalog'],
  [926, 933, 'mesh'], [939, 947, 'catalog'], [952, 962, 'mesh'], [967, 967, 'devops'], [972, 972, 'devops', ['memory']], [985, 1002, 'mesh'], [1008, 1008, 'memory', ['mesh']], [1014, 1020, 'mesh'],
  [1028, 1028, 'mesh', ['memory']], [1037, 1037, 'devops'], [1042, 1042, 'mesh'], [1048, 1072, 'devops'],
];

function manualFor(line) {
  let t = null, also = [];
  for (const [a, b, topic, al] of MANUAL) if (line >= a && line <= b) { t = topic; also = al || []; }
  return { t, also };
}

// ---------- разбор ----------
const old = readOld(path.join(SCRATCH, 'anti-patterns.HEAD.md')); // снимок git HEAD: рабочий файл уже переписан
const { sections, records } = parseLessons(old.partB, { lineOffset: old.partBOffset });

// якорь сортировки для б/н без диапазона: последний явный номер перед заголовком секции
let lastExplicit = 0;
const sectionAnchor = new Map();
for (const r of records) {
  if (!sectionAnchor.has(r.section)) sectionAnchor.set(r.section, lastExplicit);
  if (r.num && !r.inferred && /^\d+$/.test(r.num)) lastExplicit = Number(r.num); // предыдущий по файлу, не максимум
}
const sectionByTitle = new Map(sections.map(s => [s.title, s]));

let disputed = 0, changed = 0;
for (const r of records) {
  const sc = score(r);
  const m = manualFor(r.line);
  r.also_numbers = r.also.slice(); // из парсера: вторые номера в строке (218+219, 223+224)
  r.auto = sc.top; r.margin = sc.margin;
  r.topic = m.t || sc.top; r.also = m.also.filter(t => t !== r.topic); // смежные темы
  if (sc.margin < 2) disputed++;
  if (m.t && m.t !== sc.top) changed++;
  const sec = sectionByTitle.get(r.section);
  if (r.num) r.sort = numVal(r.num);
  else if (r.overflow) r.sort = sec.range[1] + 0.9;
  else r.sort = sectionAnchor.get(r.section) + 0.5;
}
// дубли номеров
const byNum = new Map();
for (const r of records) {
  const ks = r.num ? [r.num] : [];
  for (const k of ks) { if (!byNum.has(k)) byNum.set(k, []); byNum.get(k).push(r); }
}
for (const [k, rs] of byNum) if (rs.length > 1) rs.forEach((r, i) => { r.dup = String.fromCharCode(97 + i); });

console.log(`записей ${records.length}; спорных по эвристике ${disputed}; ручных перекрытий не совпавших с авто ${changed}`);

// ---------- CSV ----------
const csv = ['line;num;key_in_map;inferred;dup;also_numbers;topic;file;also_topics;auto_topic;margin;section;first_words'];
for (const r of records.slice().sort((a, b) => a.line - b.line)) {
  const key = r.num ? r.num + (r.dup || '') : 'б/н';
  csv.push([r.line, r.num ?? '', key, r.inferred ? 'inferred' : (r.overflow ? 'overflow' : ''), r.dup ? 'dup' : '', r.also_numbers.join('+'), r.topic, TOPICS[r.topic].file, r.also.join('+'), r.auto, r.margin, r.section.replace(/;/g, ','), firstWords(r.text, 70).replace(/;/g, ',')].join(';'));
}
fs.writeFileSync(path.join(SCRATCH, 'lessons-map.csv'), csv.join('\n') + '\n');

// ---------- файлы по темам ----------
const perTopic = Object.fromEntries(TOPIC_ORDER.map(t => [t, []]));
for (const r of records) perTopic[r.topic].push(r);
const isSourceKb = (r) => r.section.startsWith('Уроки source-KB') && !r.num; // только 5 безномерных бюллетеней свода

function renderTopic(t) {
  const T = TOPICS[t];
  const recs = perTopic[t].filter(r => !isSourceKb(r)).sort((a, b) => a.sort - b.sort || a.line - b.line);
  const kb = perTopic[t].filter(isSourceKb).sort((a, b) => a.line - b.line);
  const out = [];
  out.push('---', 'tier: 2', `topic: ${T.slug}`, `scope: ${T.scope}`, 'tier1: ../core/lessons.md', `updated: ${DATE}`, 'importance: med', 'source: manual', 'status: stable', '---', '');
  out.push(`# Уроки: ${T.title}`, '');
  out.push(`> Дословный перенос из \`../anti-patterns.md\` (${DATE}, Фаза 4b плана \`plans/memory-bank-audit-2026-09.md\`).`);
  out.push('> Строка `### из «…»` — исходная секция (провенанс переноса). Номера, пропуски, дубли и правило');
  out.push('> записи нового урока — `README.md` в этой папке; живые правила — `../core/lessons.md`.');
  let prev = null;
  const emit = (list) => {
    for (const r of list) {
      if (r.section !== prev) { out.push('', `### из «${r.section}»`); prev = r.section; }
      out.push('', r.text);
    }
  };
  emit(recs);
  if (kb.length) { out.push('', '## Source-KB (свод 2026-08-10, MASTER-source-kb)'); prev = null; emit(kb); }
  out.push('');
  return out.join('\n');
}

// ---------- README ----------
const esc = (t) => t.replace(/\|/g, '\\|');
function compressRanges(nums) { // nums: отсортированные целые
  const out = [];
  let s = null, p = null;
  for (const n of nums) {
    if (s === null) { s = p = n; continue; }
    if (n === p + 1) { p = n; continue; }
    out.push(s === p ? `${s}` : `${s}–${p}`); s = p = n;
  }
  if (s !== null) out.push(s === p ? `${s}` : `${s}–${p}`);
  return out.join(', ');
}

function renderReadme() {
  const allNums = new Map(); // num(string) → [{r, host?}]
  for (const r of records) {
    if (r.num) { if (!allNums.has(r.num)) allNums.set(r.num, []); allNums.get(r.num).push({ r }); }
    for (const a of r.also_numbers || []) { if (!allNums.has(a)) allNums.set(a, []); allNums.get(a).push({ r, host: r.num }); }
  }
  const ints = [...allNums.keys()].filter(k => /^\d+$/.test(k)).map(Number).sort((a, b) => a - b);
  const max = ints[ints.length - 1];
  const missing = []; for (let n = 1; n <= max; n++) if (!allNums.has(String(n))) missing.push(n);
  const dupNums = [...allNums.entries()].filter(([k, v]) => v.length > 1 && v.every(x => !x.host));

  const L = [];
  L.push('# Уроки — карта номеров', '');
  L.push(`Уроки проекта (1–${max} и записи без номера) перенесены ${DATE} из \`../anti-patterns.md\` ДОСЛОВНО в восемь`);
  L.push('тематических файлов этой папки (Фаза 4b плана `plans/memory-bank-audit-2026-09.md`). Текст записей не менялся,');
  L.push('не сжимался и не перенумеровывался; строка `### из «…»` внутри файла — исходная секция (дата переноса).');
  L.push('Живые правила по темам — `../core/lessons.md` (Tier 1); код-антипаттерны (§1–7, M1–M5) остались в `../anti-patterns.md`.', '');

  L.push('## Файлы по темам', '', '| Файл | Тема | Записей |', '|---|---|---:|');
  for (const t of TOPIC_ORDER) L.push(`| \`${TOPICS[t].file}\` | ${TOPICS[t].title} | ${perTopic[t].length} |`);
  L.push(`| | **Итого** | **${records.length}** |`, '');

  L.push('## Как записать новый урок', '');
  L.push(`- **Следующий номер: ${max + 1}.** Номер берётся отсюда и сразу двигается здесь же (\`${max + 1}\` → \`${max + 2}\`).`);
  L.push('- Формат: `**N. Заголовок** — ситуация → пробовали → почему не сработало → правило` (одна запись — один абзац).');
  L.push('- Куда: в конец файла своей темы `lessons/<тема>.md` (под заголовком `## Новые (после 2026-09-05)` — завести при первой записи).');
  L.push('- Затем при необходимости — одна строка в `../core/lessons.md` (Tier 1, ≤3 КБ: только живые правила, не пересказ).');
  L.push('- Пропущенные номера (ниже) НЕ переиспользовать; дубли не создавать — проверь этот список перед выдачей номера.', '');

  L.push('## Пропуски, дубли, особенности', '');
  L.push(`- **Пропуски** (номер не существует, утерян при прошлых сводах; не выдумывать): ${compressRanges(missing)}.`);
  L.push('- **Дубли** (один номер — два разных текста; оба сохранены, в карте помечены `a`/`b`):');
  for (const [k, v] of dupNums.sort((a, b) => numVal(a[0]) - numVal(b[0]))) {
    L.push(`  - **${k}**: ` + v.map(({ r }) => `${r.dup} → \`${TOPICS[r.topic].file}\` («${firstWords(r.text, 60)}»${r.inferred ? ', номер выведен по диапазону секции' : ''})`).join('; '));
  }
  L.push('  - Секция «Уроки 308–312 (28–29.08…)» на деле содержит сжатые копии уроков 328–331 + один без пары (pyflakes/удалённая петля);');
  L.push('    настоящие 308–312 — в секции «Уроки 303–307». Обе версии сохранены.');
  L.push('  - Секции 343–345, 347–348, 349–354, 353–358, 357–360 пересекаются: короткие и полные версии одних и тех же уроков 01.09');
  L.push('    (например, б/н «Сервис держит СТАРЫЙ код» ↔ 350; «Частичная локальная копия» ↔ 351). Сохранены обе.');
  const alsoRecs = records.filter(r => (r.also_numbers || []).length);
  L.push(`- **Два урока в одной строке** (запись одна, номера оба): ${alsoRecs.map(r => `${r.num}+${r.also_numbers.join('+')}`).join(', ')}; строки 219 и 224 обрезаны при прошлом переносе.`);
  L.push(`- **Номер выведен по порядку в диапазоне заголовка секции** (в источнике записи без номера; помечены \`inferred\` в CSV): ${compressRanges([...new Set(records.filter(r => r.inferred).map(r => Number(r.num)))].sort((a, b) => a - b))}.`);
  L.push(`- **Записи без номера** (${records.filter(r => !r.num).length}): архив июля (13), source-KB (5), «Ситуационные каноны» (6) — в заголовках секций нет диапазона;`);
  L.push('  ещё 9 — переполнение диапазона секции (записей больше, чем номеров в заголовке). Список — внизу. Две последние («ручной приём…»,');
  L.push('  «ресурсы группы…») обрезаны при переносе 02.09; полный текст — в git `core/lessons.md` @ 3e8f991.');
  L.push('- Записи 208–213 физически стояли под заголовком «Уроки source-KB» — провенанс сохранён как есть.', '');

  // Карта № → файл
  L.push('## Карта № → файл', '', '| № | Файл | Пометка |', '|---|---|---|');
  const keys = [...allNums.keys()].sort((a, b) => numVal(a) - numVal(b));
  let i = 0;
  while (i < keys.length) {
    const k = keys[i]; const v = allNums.get(k);
    if (v.length === 1 && !v[0].host && /^\d+$/.test(k) && !v[0].r.inferred) {
      // ищем ряд простых записей с тем же файлом
      let j = i; const f = v[0].r.topic;
      while (j + 1 < keys.length) {
        const k2 = keys[j + 1]; const v2 = allNums.get(k2);
        if (!/^\d+$/.test(k2) || Number(k2) !== Number(keys[j]) + 1 || v2.length !== 1 || v2[0].host || v2[0].r.inferred || v2[0].r.topic !== f) break;
        j++;
      }
      if (j > i + 1) { L.push(`| ${k}–${keys[j]} | \`${TOPICS[f].file}\` | |`); i = j + 1; continue; }
    }
    for (const { r, host } of v) {
      const notes = [];
      if (host) notes.push(`в одной строке с ${host}`);
      if (r.dup) notes.push(`dup ${r.dup}: «${esc(firstWords(r.text, 45))}»`);
      if (r.inferred) notes.push('номер выведен по диапазону секции');
      L.push(`| ${k} | \`${TOPICS[r.topic].file}\` | ${notes.join('; ')} |`);
    }
    i++;
  }
  L.push('');

  // Индекс тема → номера
  L.push('## Индекс тема → номера (many-to-many)', '');
  L.push('Основные — урок лежит в этом файле; смежные — лежит в другом файле, но относится и к этой теме.', '');
  for (const t of TOPIC_ORDER) {
    const prim = new Set(), sec = new Set();
    for (const r of records) {
      const ns = [];
      if (r.num && /^\d+$/.test(r.num)) ns.push(Number(r.num));
      for (const a of r.also_numbers || []) ns.push(Number(a));
      if (r.topic === t) ns.forEach(n => prim.add(n)); else if (r.also.includes(t)) ns.forEach(n => sec.add(n));
    }
    const primArr = [...prim].sort((a, b) => a - b), secArr = [...sec].sort((a, b) => a - b);
    const bisPrim = records.filter(r => r.topic === t && r.num && !/^\d+$/.test(r.num)).map(r => r.num);
    const unnumPrim = records.filter(r => r.topic === t && !r.num).length;
    L.push(`- **${TOPICS[t].title}** (\`${TOPICS[t].file}\`): ${compressRanges(primArr)}${bisPrim.length ? ', ' + bisPrim.join(', ') : ''}${unnumPrim ? `; б/н: ${unnumPrim}` : ''}.` + (secArr.length ? ` Смежные: ${compressRanges(secArr)}.` : ''));
  }
  L.push('');

  // Записи без номера
  L.push('## Записи без номера', '', '| Файл | Секция-источник | Первые слова | Пометка |', '|---|---|---|---|');
  for (const r of records.filter(r => !r.num).sort((a, b) => a.line - b.line)) {
    L.push(`| \`${TOPICS[r.topic].file}\` | ${esc(r.section.slice(0, 48))}${r.section.length > 48 ? '…' : ''} | ${esc(firstWords(r.text, 70))} | ${r.overflow ? 'переполнение диапазона' : ''} |`);
  }
  L.push('');
  L.push(`_Скрипты переноса и проверки (parse/split/verify) — вне банка; карта в CSV — \`lessons-map.csv\` рядом со скриптами. Сгенерировано ${DATE}._`, '');
  return L.join('\n');
}

// ---------- новый anti-patterns.md ----------
function renderAntiPatterns() {
  const a = old.partA.slice();
  const i = a.findIndex(l => l.startsWith('updated:'));
  a[i] = `updated: ${DATE}`;
  const tail = [
    '## Уроки по темам',
    '',
    `Секции «Архив уроков…» и «Уроки N–M…» (уроки 1–413 и записи без номера) перенесены ${DATE} ДОСЛОВНО в`,
    '`lessons/` (Фаза 4b плана `plans/memory-bank-audit-2026-09.md`); карта номеров, пропуски и дубли —',
    '`lessons/README.md`; живые правила по темам — `core/lessons.md`. Новый урок — по правилу из README.',
    '',
  ];
  for (const t of TOPIC_ORDER) tail.push(`- \`lessons/${TOPICS[t].file}\` — ${TOPICS[t].title} — записей: ${perTopic[t].length}`);
  tail.push('');
  return a.join('\n') + '\n' + tail.join('\n');
}

// ---------- запись ----------
const files = {};
for (const t of TOPIC_ORDER) files[path.join(OUT_DIR, TOPICS[t].file)] = renderTopic(t);
files[path.join(OUT_DIR, 'README.md')] = renderReadme();
const ap = renderAntiPatterns();

for (const [f, c] of Object.entries(files)) console.log(`${path.relative(MB, f)}: ${Buffer.byteLength(c)} Б, записей ${perTopic[TOPIC_ORDER.find(t => TOPICS[t].file === path.basename(f))]?.length ?? '-'}`);
console.log(`anti-patterns.md: ${Buffer.byteLength(ap)} Б`);

if (WRITE) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  for (const [f, c] of Object.entries(files)) fs.writeFileSync(f, c);
  fs.writeFileSync(SRC, ap);
  console.log('записано');
} else {
  fs.mkdirSync(path.join(SCRATCH, 'preview'), { recursive: true });
  for (const [f, c] of Object.entries(files)) fs.writeFileSync(path.join(SCRATCH, 'preview', path.basename(f)), c);
  fs.writeFileSync(path.join(SCRATCH, 'preview', 'anti-patterns.md'), ap);
  console.log('preview → scratchpad/lessons/preview/');
}
