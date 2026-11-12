// СБОРКА СТРАНИЦЫ ДЕМО И ТУРА (T-20261112-90, план tour-page-split-01 вариант А): исходник `tools/scout/flat215-demo/index.html`
// не меняется — в папку витрины кладётся СЖАТАЯ копия. Почти половина исходника — комментарии (~610 из 1325 КБ), и телефон на
// медленной связи ~2,4 с ждал HTML первого экрана (замер T-83). Здесь каждый `<script>` и `<style>` по отдельности проходит esbuild:
// пробелы и комментарии убираются, синтаксис упрощается, ИМЕНА НЕ МЕНЯЮТСЯ (на глобальные функции ссылаются `onclick` разметки,
// прогрев `tools/ops/demo-warm.mjs` и обходы `demo-walk`), границы блоков те же (порядок исполнения классических скриптов прежний).
// Комментарии разметки `<!-- -->` убираются тоже. Кириллица — как есть (`charset: utf8`), без `\uXXXX`.
// ИСТОЧНИК ПОТОКА РАКУРСОВ (ловушка CAMFIT, критика Codex 12.11): запасной подбор ракурсов в Web Worker (`index.html:camWorker`)
// раньше искал блок `// CAMFIT START/END` в тексте собственной страницы — в сжатой копии комментариев нет, и поток молча не заводился
// бы. Теперь блок берёт сборка из исходника и кладёт отдельным файлом `lib/camfit.<хеш>.js` (сжатым), имя — полем `camfit` в
// `lib/scene.json` (тот же манифест, что у движка и корзины; тур закрепляет файл вместе с ним — `lib/trial/tour-bundle.ts:pinRelease`).
// Страница качает файл только когда понадобился поток. Метки в исходнике остаются: по ним читают тесты и сборочные скрипты ракурсов.
// Ошибка разбора любого блока — громко `WARN:page_minify` и копия как есть (страница работает, только тяжелее).
//   node tools/scout/page_build.mjs <исходник index.html> <папка витрины>     # пишет <папка>/index.html и <папка>/lib/camfit.*.js
import { transformSync } from "esbuild";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

export const CAMFIT_A = "// CAMFIT START", CAMFIT_Z = "// CAMFIT END";
const JS = { loader: "js", minifyWhitespace: true, minifySyntax: true, minifyIdentifiers: false, legalComments: "none", charset: "utf8",
  logLevel: "silent" };
const CSS = { loader: "css", minifyWhitespace: true, minifySyntax: true, legalComments: "none", charset: "utf8", logLevel: "silent" };

const js = (code) => transformSync(code, JS).code.trimEnd();

/** Блок CAMFIT исходника — тот же срез, что читают тесты и сборка (`tools/flat3d/demo-cams.mjs`): от метки START до метки END. */
export function camfitBlock(html) {
  const a = html.indexOf(CAMFIT_A), z = html.indexOf(CAMFIT_Z);
  if (a < 0 || z <= a) throw new Error("в исходнике нет блока CAMFIT START/END");
  return html.slice(a, z);
}

/** Сжать страницу: каждый `<script>`/`<style>` — esbuild, комментарии разметки — прочь. → { html, blocks } или исключение. */
export function minifyPage(html) {
  const out = [];
  let i = 0, blocks = 0;
  const re = /<(script|style)>([\s\S]*?)<\/\1>/g;
  const markup = (s) => s.replace(/<!--[\s\S]*?-->/g, "");
  for (let m; (m = re.exec(html));) {
    out.push(markup(html.slice(i, m.index)));
    const [whole, tag, body] = m;
    let code;
    try {
      code = tag === "script" ? js(body) : transformSync(body, CSS).code.trimEnd();
    } catch (e) {
      const line = html.slice(0, m.index).split("\n").length;
      throw new Error(`<${tag}> со строки ${line}: ${String(e && e.message || e).split("\n")[0]}`);
    }
    // `</script` внутри кода закрыл бы блок раньше времени — в исходнике его нет, но проверяем выход, а не надеемся
    if (new RegExp(`</${tag}`, "i").test(code)) throw new Error(`<${tag}>: в сжатом коде встретилось </${tag}`);
    out.push(`<${tag}>${code}</${tag}>`);
    blocks++;
    i = m.index + whole.length;
  }
  out.push(markup(html.slice(i)));
  return { html: out.join(""), blocks };
}

const writeAtomic = (p, text) => { const t = `${p}.${process.pid}.tmp`; writeFileSync(t, text); renameSync(t, p); };

/** Файл потока ракурсов: сжатый блок CAMFIT → `lib/camfit.<хеш12>.js`, имя — в `lib/scene.json` (поле `camfit`). → имя файла. */
export function writeCamfit(src, outDir) {
  const lib = join(outDir, "lib");
  mkdirSync(lib, { recursive: true });
  const code = js(camfitBlock(src)) + "\n";
  const id = createHash("sha256").update(code).digest("hex").slice(0, 12), file = `camfit.${id}.js`;
  writeAtomic(join(lib, file), code);
  const manPath = join(lib, "scene.json");
  const man = existsSync(manPath) ? JSON.parse(readFileSync(manPath, "utf8")) : {};
  man.camfit = { file, build: id, bytes: Buffer.byteLength(code) };
  writeAtomic(manPath, JSON.stringify(man) + "\n");
  // как у движка и корзины (`build-scene-bundle.mjs`): кроме нынешнего — два последних (страница, открытая до публикации, ещё найдёт свой)
  const old = readdirSync(lib).filter((f) => /^camfit\.[0-9a-f]{12}\.js$/.test(f) && f !== file)
    .sort((a, b) => statSync(join(lib, b)).mtimeMs - statSync(join(lib, a)).mtimeMs);
  for (const f of old.slice(2)) unlinkSync(join(lib, f));
  return file;
}

/** Сборка страницы в папку витрины. → строка итога для журнала сборки (WARN — при отказе сжатия). */
export function buildPage(srcPath, outDir) {
  const src = readFileSync(srcPath, "utf8");
  mkdirSync(outDir, { recursive: true });
  const notes = [];
  try {
    const f = writeCamfit(src, outDir);
    notes.push(`поток ракурсов: lib/${f}`);
  } catch (e) {
    notes.push(`WARN:page_camfit: файл потока ракурсов не собрался (${String(e && e.message || e).slice(0, 160)}) — запасной подбор ракурсов будет в главном потоке`);
  }
  let html = src, line;
  try {
    const r = minifyPage(src);
    html = r.html;
    line = `страница сжата: ${Math.round(Buffer.byteLength(src) / 1024)} → ${Math.round(Buffer.byteLength(html) / 1024)} КБ, блоков ${r.blocks}`;
  } catch (e) {
    line = `WARN:page_minify: страница не сжалась (${String(e && e.message || e).slice(0, 200)}) — в витрину идёт исходник как есть`;
  }
  writeAtomic(join(outDir, "index.html"), html);
  return [line, ...notes].join("\n");
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const [src, out] = process.argv.slice(2);
  if (!src || !out) { console.error("usage: node tools/scout/page_build.mjs <index.html> <папка витрины>"); process.exit(2); }
  console.log(buildPage(src, out));
}
