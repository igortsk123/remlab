#!/usr/bin/env node
// ЗАРАНЕЕ СЖАТЫЕ ФАЙЛЫ ВИТРИНЫ (T-20261110-43/2). Caddy 2.8 сам умеет только zstd/gzip на лету (≈ уровень 3): разметка /demo
// 1,2 МБ уходила ≈ 411 КБ, данные 1,3 МБ — ≈ 161 КБ. brotli 11 — 290 и 99 КБ (−0,7 с до первой карточки на 2 Мбит/с), но
// стоит ~1,8 с процессора на файл — на каждый запрос так нельзя, а при публикации — один раз. Поэтому `publish_demo.sh` перед
// упаковкой зовёт этот скрипт: рядом с каждым текстовым файлом сборки ложатся `<файл>.br` (brotli 11) и `<файл>.gz` (gzip 9),
// Caddy отдаёт их по `file_server { precompressed br gzip }` (свой ETag у каждого — 304 работает).
//
// ГЛАВНЫЙ РИСК — УСТАРЕВШАЯ СЖАТАЯ КОПИЯ: Caddy берёт `.br`, если он есть, не сверяя с исходником. Поэтому:
// - копия получает время изменения исходника; не совпало (исходник переписан) — копия пересоздаётся;
// - копия, чей исходник исчез или перестал подходить (мал, не текст), — убирается (только с нашими расширениями);
// - сжать не вышло — копии этого файла убираются (Caddy сожмёт на лету, как раньше), код выхода 0 и WARN.
// Пишем во временный файл рядом и переименовываем — обрывка под настоящим именем не бывает.
//
//   node tools/scout/precompress.mjs <папка> [--dry] [--selftest]
// Виды сверху (`topsprites/`) и картинки (`img/`) не трогаем: они уже сжаты и приезжают отдельно.
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import os from "node:os";

const TEXT = /\.(html|json|js|mjs|css|svg)$/;
const SKIP_DIRS = new Set(["topsprites", "img"]);
const MIN_BYTES = 1024;
const ENCS = [
  { ext: ".br", make: (b) => zlib.brotliCompressSync(b, { params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 11, [zlib.constants.BROTLI_PARAM_SIZE_HINT]: b.length } }) },
  { ext: ".gz", make: (b) => zlib.gzipSync(b, { level: 9 }) },
];

function* walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) { if (!SKIP_DIRS.has(e.name)) yield* walk(p); }
    else if (e.isFile()) yield p;
  }
}
const fits = (p) => TEXT.test(p) && fs.statSync(p).size >= MIN_BYTES;
const sameTime = (a, b) => Math.abs(a.mtimeMs - b.mtimeMs) < 1;

export function precompress(root, { dry = false, log = console.log } = {}) {
  const out = { made: 0, kept: 0, removed: 0, failed: 0, before: 0, after: 0 };
  const files = [...walk(root)];
  const drop = (p, why) => { if (!dry) fs.rmSync(p, { force: true }); out.removed++; log(`убрана сжатая копия (${why}): ${path.relative(root, p)}`); };
  // 1) копии без подходящего исходника — прочь (только наши: исходник по имени — текстовый)
  for (const p of files) {
    const enc = ENCS.find((e) => p.endsWith(e.ext));
    if (!enc) continue;
    const src = p.slice(0, -enc.ext.length);
    if (!TEXT.test(src)) continue;
    if (!fs.existsSync(src)) drop(p, "исходника нет");
    else if (!fits(src)) drop(p, "исходник не сжимаем");
  }
  // 2) исходники — свежие копии
  for (const src of files) {
    if (!fs.existsSync(src) || !fits(src)) continue;
    const st = fs.statSync(src);
    let raw = null;
    for (const enc of ENCS) {
      const dst = src + enc.ext;
      if (fs.existsSync(dst) && sameTime(fs.statSync(dst), st)) { out.kept++; continue; }
      if (dry) { out.made++; log(`сжал бы: ${path.relative(root, dst)}`); continue; }
      try {
        raw ??= fs.readFileSync(src);
        const z = enc.make(raw);
        const tmp = `${dst}.tmp-${process.pid}`;
        fs.writeFileSync(tmp, z);
        fs.utimesSync(tmp, st.atime, st.mtime);
        fs.renameSync(tmp, dst);
        out.made++; out.before += raw.length; out.after += z.length;
      } catch (e) {
        out.failed++;
        log(`WARN:precompress: ${path.relative(root, src)} — ${String(e && e.message || e).slice(0, 200)}; его сжатые копии убраны (Caddy сожмёт на лету)`);
        for (const x of ENCS) fs.rmSync(src + x.ext, { force: true });
        for (const x of ENCS) fs.rmSync(`${src}${x.ext}.tmp-${process.pid}`, { force: true });
        break;
      }
    }
  }
  return out;
}

// временное — на диске, как у остальных селфтестов (T-20261107-13): REMLAB_TMP → ~/remlab-scratch/tmp → в CI RUNNER_TEMP → системная
function tmpRoot() {
  const scratch = path.join(os.homedir(), "remlab-scratch");
  const d = process.env.REMLAB_TMP || (fs.existsSync(scratch) ? path.join(scratch, "tmp") : process.env.RUNNER_TEMP || os.tmpdir());
  fs.mkdirSync(d, { recursive: true });
  return d;
}

function selftest() {
  const d = fs.mkdtempSync(path.join(tmpRoot(), "precompress-selftest."));
  const ok = (c, m) => { if (!c) { console.log("FAIL", m); process.exitCode = 1; } else console.log("ok  ", m); };
  try {
    fs.mkdirSync(path.join(d, "lib")); fs.mkdirSync(path.join(d, "img")); fs.mkdirSync(path.join(d, "topsprites"));
    const big = "<p>витрина</p>".repeat(400);
    fs.writeFileSync(path.join(d, "index.html"), big);
    fs.writeFileSync(path.join(d, "lib", "scene.abc.js"), "var x=1;".repeat(300));
    fs.writeFileSync(path.join(d, "small.json"), "{}");
    fs.writeFileSync(path.join(d, "img", "a.svg"), "<svg/>".repeat(500));
    fs.writeFileSync(path.join(d, "topsprites", "t.json"), "{}".repeat(900));
    fs.writeFileSync(path.join(d, "old.html.br"), "мусор");            // исходника нет — убрать
    fs.writeFileSync(path.join(d, "mesh.glb.gz"), "чужое");            // не наше (исходник не текст) — не трогать
    const q = () => {};
    let r = precompress(d, { log: q });
    ok(r.made === 4 && r.failed === 0, `первый проход: 4 копии (html, js × br/gz), сделано ${r.made}`);
    ok(zlib.brotliDecompressSync(fs.readFileSync(path.join(d, "index.html.br"))).toString() === big, ".br распаковывается в исходник");
    ok(zlib.gunzipSync(fs.readFileSync(path.join(d, "index.html.gz"))).toString() === big, ".gz распаковывается в исходник");
    ok(!fs.existsSync(path.join(d, "small.json.br")), "файл < 1 КБ не сжимаем");
    ok(!fs.existsSync(path.join(d, "img", "a.svg.br")) && !fs.existsSync(path.join(d, "topsprites", "t.json.br")), "img/ и topsprites/ не трогаем");
    ok(!fs.existsSync(path.join(d, "old.html.br")) && fs.existsSync(path.join(d, "mesh.glb.gz")), "сирота убрана, чужой .gz цел");
    r = precompress(d, { log: q });
    ok(r.made === 0 && r.kept === 4, `второй проход без правок — ничего не пересжато (kept ${r.kept})`);
    const big2 = "<p>новая</p>".repeat(400);
    fs.writeFileSync(path.join(d, "index.html"), big2);
    const t = new Date(Date.now() + 5000); fs.utimesSync(path.join(d, "index.html"), t, t);
    r = precompress(d, { log: q });
    ok(r.made === 2 && zlib.brotliDecompressSync(fs.readFileSync(path.join(d, "index.html.br"))).toString() === big2, "исходник переписан — копии новые");
    fs.rmSync(path.join(d, "lib", "scene.abc.js"));
    r = precompress(d, { log: q });
    ok(r.removed === 2 && !fs.existsSync(path.join(d, "lib", "scene.abc.js.br")), "исходник удалён — его копии убраны");
    fs.writeFileSync(path.join(d, "index.html"), "x");
    r = precompress(d, { log: q });
    ok(!fs.existsSync(path.join(d, "index.html.br")) && !fs.existsSync(path.join(d, "index.html.gz")), "исходник стал мал — копии убраны");
  } finally { fs.rmSync(d, { recursive: true, force: true }); }
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname);
if (isMain) {
  const args = process.argv.slice(2);
  if (args.includes("--selftest")) selftest();
  else {
    const dir = args.find((a) => !a.startsWith("--"));
    if (!dir || !fs.statSync(dir).isDirectory()) { console.error("использование: node tools/scout/precompress.mjs <папка> [--dry] [--selftest]"); process.exit(2); }
    const t0 = Date.now();
    const r = precompress(dir, { dry: args.includes("--dry") });
    const k = (n) => Math.round(n / 1024);
    console.log(`precompress: сжато ${r.made}, свежих ${r.kept}, убрано ${r.removed}, сбоев ${r.failed}` +
      (r.made && !args.includes("--dry") ? ` · ${k(r.before)} КБ → ${k(r.after)} КБ` : "") + ` · ${Date.now() - t0} мс`);
  }
}
