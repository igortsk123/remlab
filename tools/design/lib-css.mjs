// ОБЩЕЕ ДЛЯ ВЫГРУЗКИ В ФИГМУ (план design-01-figma-export, п.1): CSS демо-страницы как данные.
// Читает `tools/scout/flat215-demo/index.html`, достаёт ВСЕ блоки <style> (их три) и разбирает их в правила
// { selector, media[], decls:[{prop,value,line}], line } с номерами строк исходного файла. Продукт не меняет.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
export const SRC_REL = "tools/scout/flat215-demo/index.html";
export const SRC = resolve(ROOT, SRC_REL);

export function readSrc() { return readFileSync(SRC, "utf8"); }

/** Блоки <style> с позициями: [{ css, start (смещение текста CSS), line (строка тега <style>) }] */
export function styleBlocks(html = readSrc()) {
  const out = []; const re = /<style>([\s\S]*?)<\/style>/g; let m;
  while ((m = re.exec(html))) {
    const start = m.index + "<style>".length;
    out.push({ css: m[1], start, line: html.slice(0, m.index).split("\n").length });
  }
  return out;
}

/** Весь CSS страницы одной строкой — ДОСЛОВНО, в порядке блоков (для кита и снимков) */
export function allCss(html = readSrc()) { return styleBlocks(html).map((b) => b.css).join("\n"); }

const lineAt = (html, off) => { let n = 1; for (let i = 0; i < off; i++) if (html.charCodeAt(i) === 10) n++; return n; };

/** Разбор CSS в правила. Комментарии вырезаются с сохранением длины (номера строк не плывут). */
export function parseRules(html = readSrc()) {
  // таблица «смещение → строка» один раз
  const nl = []; for (let i = 0; i < html.length; i++) if (html.charCodeAt(i) === 10) nl.push(i);
  const lineOf = (off) => { let lo = 0, hi = nl.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (nl[mid] < off) lo = mid + 1; else hi = mid; } return lo + 1; };
  const rules = [];
  for (const b of styleBlocks(html)) {
    const css = b.css.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, " "));
    const stack = []; // контекст @media/@container/@keyframes
    let i = 0, buf = "", bufStart = 0;
    while (i < css.length) {
      const ch = css[i];
      if (ch === "{") {
        const head = buf.trim(); const headOff = b.start + bufStart + (buf.length - buf.trimStart().length);
        if (head.startsWith("@")) { stack.push(head); buf = ""; bufStart = i + 1; i++; continue; }
        // правило: читаем тело до парной }
        let j = i + 1, depth = 1; while (j < css.length && depth) { if (css[j] === "{") depth++; else if (css[j] === "}") depth--; j++; }
        const body = css.slice(i + 1, j - 1); const bodyOff = b.start + i + 1;
        const decls = []; let k = 0;
        for (const part of splitDecls(body)) {
          const p = part.text; const c = p.indexOf(":"); if (c < 0) { k += part.len; continue; }
          const prop = p.slice(0, c).trim(); const value = p.slice(c + 1).trim().replace(/\s*!important$/, "");
          if (prop) decls.push({ prop, value, important: /!important\s*$/.test(p), line: lineOf(bodyOff + part.off + (p.length - p.trimStart().length)) });
        }
        const inKeyframes = stack.some((s) => s.startsWith("@keyframes"));
        rules.push({ selector: head.replace(/\s+/g, " "), media: stack.filter((s) => !s.startsWith("@keyframes")), keyframes: inKeyframes, decls, line: lineOf(headOff) });
        i = j; buf = ""; bufStart = i; continue;
      }
      if (ch === "}") { stack.pop(); buf = ""; bufStart = i + 1; i++; continue; }
      if (ch === ";" && !buf.trim().startsWith("@")) { buf = ""; bufStart = i + 1; i++; continue; }
      if (ch === ";") { buf = ""; bufStart = i + 1; i++; continue; }
      buf += ch; i++;
    }
  }
  return rules;
}

// делит тело правила по «;», не разрывая скобки (url(), var(), clamp())
function splitDecls(body) {
  const out = []; let depth = 0, start = 0;
  for (let i = 0; i <= body.length; i++) {
    const ch = body[i];
    if (ch === "(") depth++; else if (ch === ")") depth--;
    if ((ch === ";" && depth === 0) || i === body.length) { out.push({ text: body.slice(start, i), off: start, len: i - start + 1 }); start = i + 1; }
  }
  return out;
}

/** Переменные :root (все объявления, с медиа-условием) */
export function rootVars(rules) {
  const out = [];
  for (const r of rules) if (r.selector === ":root") for (const d of r.decls) if (d.prop.startsWith("--")) out.push({ name: d.prop.slice(2), value: d.value, media: r.media, line: d.line });
  return out;
}

/** Строки, где селектор объявлен (точное вхождение в списке селекторов правила либо его начало) */
export function selectorLines(rules, sel) {
  const norm = (s) => s.replace(/\s+/g, " ").trim();
  const want = norm(sel); const hits = [];
  for (const r of rules) {
    if (r.keyframes) continue;
    const parts = r.selector.split(",").map(norm);
    if (parts.some((p) => p === want || p.startsWith(want + ":") || p.startsWith(want + "[") || p.startsWith(want + " ") || p.startsWith(want + "."))) hits.push(r.line);
  }
  return [...new Set(hits)].sort((a, b) => a - b);
}
export { lineAt };
