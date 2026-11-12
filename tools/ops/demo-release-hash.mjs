#!/usr/bin/env node
// ОЖИДАЕМАЯ ВИТРИНА ТУРОВ (T-20261112-92): имя, под которым `lib/trial/tour-bundle.ts:pinRelease` закрепит ТЕКУЩУЮ витрину /demo, —
// посчитанное по тем же файлам и тому же правилу (`releaseFiles` + `releaseName`; менять вместе, равенство — `tests/unit/
// tour-release-hash.test.ts`). Проверка «демо = туры» (`tools/ops/tour-reissue.sh`): у каждого перевыпущенного тура `release` из
// ответа сервера должен быть равен этому имени — тогда страница и движок тура те же байты, что /demo.
//   node tools/ops/demo-release-hash.mjs --url https://remont-lab.online/demo/   # по файлам, которые прод отдаёт сейчас
//   node tools/ops/demo-release-hash.mjs --dir ~/scout-scenes/flat215-demo        # по папке сборки
// Вывод — имя (32 знака) одной строкой; сбой — код 1 и причина в stderr.
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

/** = `tour-bundle.ts:releaseFiles` */
export function releaseFiles(man) {
  return ["index.html", "lib/scene.json", `lib/${man.file}`, ...(man.basket ? [`lib/${man.basket.file}`] : []),
    ...(man.camfit ? [`lib/${man.camfit.file}`] : []), "rt-meshes.json"];
}

/** = `tour-bundle.ts:releaseName` */
export function releaseName(files) {
  const hash = createHash("sha256");
  for (const [rel, body] of files) hash.update(rel).update("\0").update(body);
  return hash.digest("hex").slice(0, 32);
}

/** `get(rel) → Buffer` — откуда брать файл (папка или адрес). → имя витрины. */
export async function expectedRelease(get) {
  const man = JSON.parse((await get("lib/scene.json")).toString("utf8"));
  const files = [];
  for (const rel of releaseFiles(man)) files.push([rel, await get(rel)]);
  return releaseName(files);
}

export const fromDir = (dir) => (rel) => readFile(join(dir, rel));

export function fromUrl(base, fetchImpl = fetch) {
  const root = base.endsWith("/") ? base : `${base}/`;
  const bust = Date.now();
  return async (rel) => {
    // без кэша и без сжатия на стороне сервера: нужны байты файла, как их читает pinRelease из DEMO_DIR
    const r = await fetchImpl(`${root}${rel}?v=${bust}`, { headers: { "Accept-Encoding": "identity", "Cache-Control": "no-cache" } });
    if (!r.ok) throw new Error(`${rel}: HTTP ${r.status}`);
    return Buffer.from(await r.arrayBuffer());
  };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const [k, v] = process.argv.slice(2);
  const get = k === "--dir" && v ? fromDir(v) : k === "--url" && v ? fromUrl(v) : null;
  if (!get) {
    console.error("нужно --url <адрес витрины> или --dir <папка витрины>");
    process.exit(2);
  }
  expectedRelease(get).then((n) => console.log(n), (e) => {
    console.error(`demo-release-hash: ${e instanceof Error ? e.message : String(e)}`);
    process.exit(1);
  });
}
