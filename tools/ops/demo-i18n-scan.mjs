// ПАРЫ RU/EN В КОДЕ СТРАНИЦЫ ДЕМО (T-20261112-116, владелец TG 1341: «всегда, когда добавляется функционал, проходить контроль,
// чтобы всё было переведено; сразу нормально, а не работа над ошибками»). Страница `tools/scout/flat215-demo/index.html` переводит
// показ двумя способами: пара прямо в коде (`EN?'…':'…'`, `T('рус','eng')`, `['рус','eng']`, `{ru:…, en:…}`) или словарь слоя
// показа (`var ROLE/STYLE/ROOM/EX/ATTR` + шаблоны `P`, функция `tr` — её и вызываем). Здесь — каждая строка кода с кириллицей:
// служебная (ключ словаря, сравнение, поиск/замена, консоль) / с парой / переводится словарём / БЕЗ ПАРЫ. Строки без пары, что были
// до сторожа, — в списке долга `tools/scout/data/demo-i18n-debt.json` (только уменьшается); новая строка без пары — красный
// `pnpm test` (`tests/unit/demo-i18n.test.ts`).
//   node tools/ops/demo-i18n-scan.mjs [страница] [--debt|--check]   — сводка; `--debt` переписывает список долга (только после
//   разбора); `--check` — rc 1 на новой строке без пары и на кириллице в переводах словаря (шаг CI, prepush)
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
export const PAGE = resolve(ROOT, "tools/scout/flat215-demo/index.html");
export const DEBT = resolve(ROOT, "tools/scout/data/demo-i18n-debt.json");
const CYR = /[А-Яа-яЁё]/;

/** Переводчик слоя показа страницы — тот же код (`var ROLE=` … `function tr`), без DOM. → {tr, dicts} */
export function translator(html) {
  const a = html.indexOf("  var ROLE={"), z = html.indexOf("  var busy=false;", a);
  if (a < 0 || z < 0) throw new Error("в странице не найден словарь показа (var ROLE … var busy)");
  const ctx = { window: {} };
  vm.createContext(ctx);
  vm.runInContext(html.slice(a, z) + "\nthis.tr=tr; this.D={ROLE,STYLE,ROOM,EX,ATTR};", ctx);
  return { tr: (s) => ctx.tr(s), dicts: ctx.D };
}

// ВНУТРЕННИЕ ПРИЧИНЫ (T-20261112-116/2): аргумент этих функций и значение этих полей на экран не идут — консоль и ключ события
// (`liveOff(why)` → `LIVE.why`, `console.info`, `liveWhyKey` → латинский ключ). Строка в них, в том числе склейкой «'…'+n+'…'», —
// служебная. Чтобы правило не спрятало надпись, `internalLeaks` валит проверку, если параметр функции или поле попадут в DOM.
export const INTERNAL_CALLS = ["liveOff"];
export const INTERNAL_FIELDS = ["LIVE.why"];
const DOM_WRITE = /\.(innerHTML|outerHTML|textContent|innerText|title|placeholder|alt)\s*[+]?=(?!=)|\.(setAttribute|insertAdjacentHTML|insertAdjacentText|append|prepend|replaceChildren)\s*\(/;

/** Попадает ли «внутренняя причина» на экран? → [описание] (пусто — нет). Неизвестное имя в списке — тоже ошибка (список устарел). */
export function internalLeaks(html) {
  const out = [], found = new Set();
  for (const m of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)) {
    const sf = ts.createSourceFile("page.js", m[1], ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
    const visit = (n) => {
      if (ts.isFunctionDeclaration(n) && n.name && INTERNAL_CALLS.includes(n.name.text) && n.body) {
        found.add(n.name.text);
        const arg = n.parameters[0] && n.parameters[0].name.getText();
        const look = (x) => {
          const t = x.getText();
          if ((ts.isExpressionStatement(x) || ts.isVariableStatement(x)) && DOM_WRITE.test(t) && arg && new RegExp(`\\b${arg}\\b`).test(t)) out.push(`${n.name.text}: параметр «${arg}» уходит в DOM — ${t.slice(0, 120)}`);
          ts.forEachChild(x, look);
        };
        look(n.body);
      }
      if (ts.isExpressionStatement(n) && DOM_WRITE.test(n.getText())) for (const f of INTERNAL_FIELDS) if (n.getText().includes(f)) out.push(`${f} уходит в DOM — ${n.getText().slice(0, 120)}`);
      ts.forEachChild(n, visit);
    };
    visit(sf);
  }
  for (const f of INTERNAL_CALLS) if (!found.has(f)) out.push(`служебной функции ${f} в странице нет — убрать из INTERNAL_CALLS`);
  return out;
}

const norm = (s) => s.replace(/\s+/g, " ").trim();
const lat = (x) => /^['"`]/.test(x.getText()) && !CYR.test(x.getText()) && /[A-Za-z]/.test(x.getText());

/** Строки кода с кириллицей по видам. → {cats: {вид: число}, unpaired: [{text, line}]} */
export function scan(html) {
  const { tr, dicts } = translator(html), ATTR = dicts.ATTR;
  const cats = {}, unpaired = [];
  const add = (c) => { cats[c] = (cats[c] || 0) + 1; };
  for (const m of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)) {
    const base = html.slice(0, m.index + m[0].indexOf(">") + 1).split("\n").length;
    const sf = ts.createSourceFile("page.js", m[1], ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
    const classify = (n, text) => {
      let p = n.parent;
      while (p && (ts.isTemplateSpan(p) || ts.isTemplateExpression(p))) { n = p; p = p.parent; }
      if (ts.isPropertyAssignment(p) && p.name === n) return add("ключ");
      if (ts.isBinaryExpression(p) && /^[!=]==?$/.test(p.operatorToken.getText())) return add("сравнение");
      // внутренняя причина: подняться по склейке «+», скобкам и ветке «?:» до вызова или присваивания (см. INTERNAL_CALLS)
      let q = n, up = p;
      while (up && ((ts.isBinaryExpression(up) && up.operatorToken.kind === ts.SyntaxKind.PlusToken) || ts.isParenthesizedExpression(up)
        || (ts.isConditionalExpression(up) && up.condition !== q))) { q = up; up = up.parent; }
      if (up && ts.isCallExpression(up) && up.arguments.includes(q)
        && (INTERNAL_CALLS.includes(up.expression.getText()) || /^console\.\w+$/.test(up.expression.getText()))) return add("служебное");
      if (up && ts.isBinaryExpression(up) && up.operatorToken.kind === ts.SyntaxKind.EqualsToken && up.right === q
        && INTERNAL_FIELDS.includes(up.left.getText())) return add("служебное");
      if (ts.isCaseClause(p)) return add("сравнение");
      if (ts.isCallExpression(p)) {
        const f = p.expression.getText();
        if (/\.(test|startsWith|endsWith|includes|indexOf|lastIndexOf|match|matchAll|replace|replaceAll|split|has|get|set|delete|search|getItem|setItem)$|^console\.|^(RegExp|new RegExp)$/.test(f)) return add("служебное");
        if (p.arguments.length >= 2 && p.arguments.some((x) => x !== n && lat(x))) return add("пара");
      }
      if (ts.isNewExpression(p) && /RegExp/.test(p.expression.getText())) return add("служебное");
      if (ts.isConditionalExpression(p) && p.condition !== n) {
        const other = p.whenTrue === n ? p.whenFalse : p.whenTrue;
        if (/\bEN\b|LANG|lang|_EN\b|En\b/.test(p.condition.getText()) || !CYR.test(other.getText())) return add("пара");
      }
      if (ts.isArrayLiteralExpression(p) && p.elements.some((x) => x !== n && lat(x))) return add("пара");
      if (ts.isPropertyAssignment(p) && p.initializer === n && ts.isObjectLiteralExpression(p.parent)
        && p.parent.properties.some((q) => q !== p && q.name && /^en|en$|En$/.test(q.name.getText().replace(/['"]/g, "")))) return add("пара");
      if (tr(norm(text))) return add("словарь");
      // разметка: слой показа переводит каждый текстовый узел и подписи title/aria-label/placeholder/alt отдельно — так и сверяем
      if (/[<>]/.test(text)) {
        const attrs = [...text.matchAll(/(?:title|aria-label|placeholder|alt)="([^"]*)"/g)].map((x) => x[1]);
        const nodes = text.replace(/(?:title|aria-label|placeholder|alt)="[^"]*"/g, "").replace(/^[^<>]*>/, "").replace(/<[^>]*$/, "")
          .split(/<[^>]*>/);
        const segs = [...nodes, ...attrs].map(norm).filter((s) => CYR.test(s));
        if (segs.length && segs.every((s) => tr(s) || ATTR[s])) return add("словарь");
      }
      add("без пары");
      unpaired.push({ text: norm(text).slice(0, 160), line: base + sf.getLineAndCharacterOfPosition(n.getStart()).line });
    };
    const visit = (n) => {
      let text = null;
      if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n) || ts.isTemplateHead(n) || ts.isTemplateMiddle(n) || ts.isTemplateTail(n)) text = n.text;
      if (text && CYR.test(text) && norm(text)) classify(n, text);
      ts.forEachChild(n, visit);
    };
    visit(sf);
  }
  // разметка страницы вне скриптов: текст узлов и подписи — тем же словарём
  const markup = html.replace(/<!--[\s\S]*?-->|<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/g, (m) => m.replace(/[^\n]/g, " "));
  const lineOf = (i) => markup.slice(0, i).split("\n").length;
  const check = (s, i, attr) => {
    s = norm(s);
    if (!CYR.test(s)) return;
    if (tr(s) || (attr && ATTR[s])) return add("словарь");
    add("без пары");
    unpaired.push({ text: s.slice(0, 160), line: lineOf(i) });
  };
  for (const m of markup.matchAll(/>([^<>]+)</g)) check(m[1], m.index, false);
  for (const m of markup.matchAll(/(?:title|aria-label|placeholder|alt)="([^"]*)"/g)) check(m[1], m.index, true);
  return { cats, unpaired };
}

/** Переводы словаря показа — латиницей (английская сторона пары без кириллицы). → [ключ, …] с кириллицей в переводе */
export function cyrillicInDicts(html) {
  const { dicts } = translator(html), bad = [];
  for (const [name, d] of Object.entries(dicts)) for (const [k, v] of Object.entries(d)) if (CYR.test(String(v))) bad.push(`${name}['${k}']`);
  return bad;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const page = process.argv.slice(2).find((a) => !a.startsWith("--")) || PAGE;
  const html = readFileSync(page, "utf8"), { cats, unpaired } = scan(html);
  const uniq = [...new Set(unpaired.map((u) => u.text))].sort();
  console.log(`строк с кириллицей: ${JSON.stringify(cats)}; без пары уникальных: ${uniq.length}`);
  if (process.argv.includes("--debt")) {
    writeFileSync(DEBT, JSON.stringify({ _note: "Строки страницы демо без пары RU/EN, бывшие до сторожа T-20261112-116. Список только " +
      "уменьшается: переведённую строку убрать (`node tools/ops/demo-i18n-scan.mjs --debt`); новую сюда не добавлять — дать пару в коде или словаре.",
    strings: uniq }, null, 1) + "\n");
    console.log(`список долга записан: ${DEBT}`);
  }
  // `--check` — то же, что `tests/unit/demo-i18n.test.ts`, отдельной командой: CI-шаг с ней prepush запускает при правке страницы
  if (process.argv.includes("--check")) {
    const debt = new Set(JSON.parse(readFileSync(DEBT, "utf8")).strings);
    const fresh = unpaired.filter((u) => !debt.has(u.text)), dict = cyrillicInDicts(html), leaks = internalLeaks(html);
    for (const u of fresh) console.log(`FAIL без пары RU/EN: строка ${u.line} «${u.text}» — дать пару (EN?'…':'…', T(ru,en)) или строку в словарь показа`);
    for (const k of dict) console.log(`FAIL кириллица в английском переводе словаря: ${k}`);
    for (const k of leaks) console.log(`FAIL внутренняя причина на экране: ${k}`);
    const gone = [...debt].filter((s) => !uniq.includes(s)).length;
    if (gone) console.log(`долг можно уменьшить на ${gone} (переведено): node tools/ops/demo-i18n-scan.mjs --debt`);
    process.exit(fresh.length || dict.length || leaks.length ? 1 : 0);
  }
}
