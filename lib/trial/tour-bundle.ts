// Запись тура пробы (план agent-trial-08): закрепить версию витрины за заданием. Чтение и отдача — `lib/trial/tour.ts`.

import { promises as fs } from "node:fs";
import { createHash, randomBytes } from "node:crypto";
import path from "node:path";

import { trialDemoDir, trialDir } from "@/lib/trial/config";
import { validId } from "@/lib/trial/http";
import { tourTarget } from "@/lib/trial/tour";
import { RELEASE_RE, jobDir, jobRelease, releaseDir } from "@/lib/trial/tour-files";

async function write(file: string, data: Buffer | string): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, data);
}

type SceneManifest = { file: string; basket?: { file: string }; camfit?: { file: string } };

/** Файлы витрины, которые закрепляет тур, по `lib/scene.json`. То же правило читает проверка «демо = туры»
 *  (`tools/ops/demo-release-hash.mjs`, T-20261112-92) — менять вместе. `camfit` — блок ракурсов (T-20261112-90), у старых витрин нет. */
export function releaseFiles(man: SceneManifest): string[] {
  return ["index.html", "lib/scene.json", `lib/${man.file}`, ...(man.basket ? [`lib/${man.basket.file}`] : []),
    ...(man.camfit ? [`lib/${man.camfit.file}`] : []), "rt-meshes.json"];
}

/** Имя закреплённой витрины: sha256 по «путь \0 содержимое» файлов в порядке `releaseFiles`, первые 32 знака. */
export function releaseName(files: Array<[string, Buffer]>): string {
  const hash = createHash("sha256");
  for (const [rel, body] of files) hash.update(rel).update("\0").update(body);
  return hash.digest("hex").slice(0, 32);
}

/**
 * Закрепить текущую витрину: копия `index.html`, `lib/scene.json`, файлов из него и `rt-meshes.json` в
 * `tour/_releases/<хеш содержимого>/`. Одинаковое содержимое — одна копия (меняется только при новой выкладке),
 * появляется атомарно (папка `.part-*` → rename), поэтому страница не бывает наполовину скопированной.
 */
export async function pinRelease(demoDir: string, dir = trialDir()): Promise<string> {
  const rels = releaseFiles(JSON.parse(await fs.readFile(path.join(demoDir, "lib", "scene.json"), "utf8")) as SceneManifest);
  const files: Array<[string, Buffer]> = [];
  for (const rel of rels) {
    if (rel !== "index.html" && !tourTarget(rel.split("/"))) throw new Error(`pinRelease: файл вне списка: ${rel}`);
    files.push([rel, await fs.readFile(path.join(demoDir, rel))]);
  }
  const name = releaseName(files);
  const target = releaseDir(dir, name);
  try { await fs.access(target); return name; } catch { /* копии ещё нет */ }
  const part = `${target}.part-${randomBytes(6).toString("hex")}`;
  for (const [rel, body] of files) await write(path.join(part, rel), body);
  try {
    await fs.rename(part, target);
  } catch (e) {
    // соседний процесс успел первым — его копия того же содержимого; наша `.part-*` остаётся мусором без вреда
    const code = (e as NodeJS.ErrnoException).code;
    if (code !== "ENOTEMPTY" && code !== "EEXIST") throw e;
  }
  return name;
}

/** Закрепить версию страницы за заданием. Файл лежит в папке задания и уходит вместе с ней при очистке. */
export async function pinJobRelease(id: string, release: string, dir = trialDir()): Promise<void> {
  if (!validId(id) || !RELEASE_RE.test(release)) throw new Error("bad id or release");
  await write(path.join(jobDir(dir, id), "release"), `${release}\n`);
}

/** Закрепить, ТОЛЬКО если у задания ещё нет версии: жёсткая ссылка не заменяет существующий файл, поэтому гонка двух публикаций
 *  даёт один `release` (вторая получает EEXIST → "exists"). → true — закрепили мы. */
async function pinJobReleaseOnce(id: string, release: string, dir: string): Promise<boolean> {
  if (!validId(id) || !RELEASE_RE.test(release)) throw new Error("bad id or release");
  const d = jobDir(dir, id);
  const tmp = path.join(d, `.release.${randomBytes(6).toString("hex")}.tmp`);
  await write(tmp, `${release}\n`);
  try {
    await fs.link(tmp, path.join(d, "release"));
    return true;
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "EEXIST") return false;
    throw e;
  } finally {
    await fs.rm(tmp, { force: true }).catch(() => undefined);
  }
}

/** Принята версия данных задания — страница тура должна открываться: нет `<id>/release` → закрепить текущую витрину
 *  (`DEMO_DIR`, на проде `/srv/demo`). Уже есть — ничего (повторная публикация, пересборка). Ошибка — исключение наверх. */
export async function ensureJobRelease(id: string, dir = trialDir(), demoDir = trialDemoDir()): Promise<"pinned" | "exists"> {
  if (await jobRelease(dir, id)) return "exists";
  const name = await pinRelease(demoDir, dir);
  return (await pinJobReleaseOnce(id, name, dir)) ? "pinned" : "exists";
}

/** Пересборка «как есть» (оператор, T-20261110-05): закрепить за заданием ТЕКУЩУЮ витрину, заменив прежнюю (подменой файла —
 *  читатель видит старую или новую запись, не половину). Прежняя копия `_releases/<хеш>` остаётся — её держат другие туры.
 *  → { release: новая, previous: прежняя или null }. */
export async function repinJobRelease(id: string, dir = trialDir(), demoDir = trialDemoDir()): Promise<{ release: string; previous: string | null }> {
  if (!validId(id)) throw new Error("bad id");
  const previous = await jobRelease(dir, id);
  const release = await pinRelease(demoDir, dir);
  const d = jobDir(dir, id);
  const tmp = path.join(d, `.release.${randomBytes(6).toString("hex")}.tmp`);
  await write(tmp, `${release}\n`);
  await fs.rename(tmp, path.join(d, "release"));
  return { release, previous };
}

/** Пересборка агентом («Обустроить», «Перечитать»; T-20261112-92): новая версия данных — на ТЕКУЩЕЙ витрине, как у перевыпуска.
 *  Раньше (`ensureJobRelease`) тур оставался на витрине первой сборки: новые данные на старой странице. → "pinned" — витрина сменилась,
 *  "exists" — была та же. */
export async function repinCurrentRelease(id: string, dir = trialDir(), demoDir = trialDemoDir()): Promise<"pinned" | "exists"> {
  const r = await repinJobRelease(id, dir, demoDir);
  return r.previous === r.release ? "exists" : "pinned";
}

/** Положить данные задания атомарно (страница не увидит половину JSON). Временная запись до вливания ветки данных — для проверок и фикстур. */
export async function writeTourData(id: string, data: string, dir = trialDir()): Promise<void> {
  if (!validId(id)) throw new Error("bad id");
  const d = jobDir(dir, id);
  const tmp = path.join(d, `demo-data.json.part-${randomBytes(6).toString("hex")}`);
  await write(tmp, data);
  await fs.rename(tmp, path.join(d, "demo-data.json"));
}
