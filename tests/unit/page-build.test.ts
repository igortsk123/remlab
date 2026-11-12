import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

// СБОРКА СТРАНИЦЫ ДЕМО (T-20261112-90, `tools/scout/page_build.mjs`): в витрину — сжатая копия исходника; блок ракурсов для потока —
// отдельным файлом `lib/camfit.<хеш>.js` (страница больше не ищет его по меткам-комментариям в своём тексте — в сжатой их нет).
type PB = {
  minifyPage: (html: string) => { html: string; blocks: number };
  camfitBlock: (html: string) => string;
  writeCamfit: (src: string, out: string) => string;
  buildPage: (src: string, out: string) => string;
};
type It = { role: string; x: number; y: number; rot: number; w: number; d: number };
type Fx = { room: { w: number; d: number }; variants: { id: string; items: It[] }[] };
type Msg = { id: number; r: { level?: number; cams?: unknown[]; err?: string } };

const SRC = "tools/scout/flat215-demo/index.html";
const html = readFileSync(SRC, "utf8");
let M: PB, min: string, root: string;

beforeAll(async () => {
  M = (await import(pathToFileURL(resolve("tools/scout/page_build.mjs")).href)) as PB;
  min = M.minifyPage(html).html;
  root = mkdtempSync(join(tmpdir(), "page-build-"));
});
afterAll(() => rmSync(root, { recursive: true, force: true }));

const tags = (s: string, t: string) => (s.match(new RegExp(`<${t}>`, "g")) ?? []).length;

describe("сжатие страницы при сборке", () => {
  it("комментариев и меток нет, блоки те же, страница меньше вдвое с лишним", () => {
    // в исходнике блок начинается с начала строки (слово «<script>» встречается и в комментариях — их не считаем)
    expect(tags(min, "script")).toBe((html.match(/^<script>/gm) ?? []).length);
    expect(tags(min, "style")).toBe((html.match(/^<style>/gm) ?? []).length);
    expect(min).not.toContain("// CAMFIT START");
    expect(min).not.toContain("<!--");
    expect(Buffer.byteLength(min)).toBeLessThan(Buffer.byteLength(html) * 0.65);
    expect(min).toContain("Загружаем модели");                         // кириллица как есть, не \uXXXX
  });

  it("имена не меняются: обработчики разметки и функции прогрева на месте", () => {
    const handlers = new Set([...html.matchAll(/\son[a-z]+="([A-Za-z_$][\w$]*)\(/g)].map((m) => m[1]!));
    const warm = ["allVariants", "roomGeoOf", "roomIdOf", "pubStateOf", "shotCamOk", "camAng", "pickVariant", "makePhoto", "devCanon",
      "camWorker", "camWorkerSrc", "sceneManifest"];
    for (const n of [...handlers, ...warm]) expect(min, n).toMatch(new RegExp(`function ${n.replace("$", "\\$")}\\(|\\b${n}=`));
  });

  it("страница не читает свой текст: поток ракурсов — из файла сборки", () => {
    expect(html).not.toMatch(/\[\.\.\.document\.scripts\]/);
    const cw = html.slice(html.indexOf("// CAMWORK START"), html.indexOf("// CAMWORK END"));
    expect(cw).toContain("m.camfit");
    expect(cw).toContain("fetch('lib/'+f)");
  });

  it("сломанный блок — WARN и исходник как есть, а не битая страница", () => {
    const bad = "<html><head><script>function a(){</script></head><body><!-- x --></body></html>";
    const src = join(root, "bad.html"), out = join(root, "bad-out");
    writeFileSync(src, bad);
    const line = M.buildPage(src, out);
    expect(line).toMatch(/^WARN:page_minify/);
    expect(line).toContain("WARN:page_camfit");
    expect(readFileSync(join(out, "index.html"), "utf8")).toBe(bad);
  });
});

describe("файл блока ракурсов для потока", () => {
  it("рядом с движком: имя в lib/scene.json, прежние поля манифеста целы", () => {
    const out = join(root, "out");
    mkdirSync(join(out, "lib"), { recursive: true });
    writeFileSync(join(out, "lib", "scene.json"), JSON.stringify({ file: "scene.abc.js", basket: { file: "basket.def.js" } }));
    const line = M.buildPage(SRC, out);
    expect(line).toMatch(/^страница сжата: \d+ → \d+ КБ/);
    const man = JSON.parse(readFileSync(join(out, "lib", "scene.json"), "utf8")) as Record<string, { file: string }>;
    expect(man.file).toBe("scene.abc.js");
    expect(man.basket!.file).toBe("basket.def.js");
    expect(man.camfit!.file).toMatch(/^camfit\.[0-9a-f]{12}\.js$/);
    expect(readdirSync(join(out, "lib"))).toContain(man.camfit!.file);
    expect(readFileSync(join(out, "index.html"), "utf8")).toBe(min);
  });

  it("поток со СЖАТЫМ блоком отвечает той же парой, что с исходным", () => {
    const out = join(root, "cf");
    const file = M.writeCamfit(html, out);
    const packed = readFileSync(join(out, "lib", file), "utf8");
    expect(packed).not.toContain("// CAMFIT");
    const cw = html.slice(html.indexOf("// CAMWORK START"), html.indexOf("// CAMWORK END"));
    const srcOf = new Function(`${cw.slice(cw.indexOf("function camWorkerSrc"), cw.indexOf("const CAMW="))};return camWorkerSrc;`)() as
      (b: string) => string;
    const fx = JSON.parse(readFileSync("tests/fixtures/demo-layouts-neo-0711.json", "utf8")) as Fx;
    const run = (block: string): Msg => {
      const out: Msg[] = [];
      const on = new Function("postMessage", `let onmessage; ${srcOf(block)}; return onmessage;`)((m: Msg) => out.push(m)) as
        (e: { data: unknown }) => void;
      const its = fx.variants[0]!.items.map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 }));
      on({ data: { D: { room: fx.room } } });
      on({ data: { id: 1, rid: "living", geo: fx.room, its } });
      return out[0]!;
    };
    const a = run(M.camfitBlock(html)), b = run(packed);
    expect(a.r.err).toBeUndefined();
    expect(b.r.err).toBeUndefined();
    expect(b.r).toEqual(a.r);
    expect(b.r.cams).toHaveLength(2);
  });
});
