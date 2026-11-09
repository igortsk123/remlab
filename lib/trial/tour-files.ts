// Файлы тура пробы на томе (план agent-trial-08). Закреплённая версия витрины — общая папка `tour/_releases/<версия>/`,
// какая версия у задания — файл `<id>/release` в папке задания. Данные задания читает ТОЛЬКО `readTourData` (хранилище — у ветки данных).

import { constants, promises as fs } from "node:fs";
import path from "node:path";
import type { LatestBundle } from "@/lib/trial/repo-bundle";

export const RELEASE_RE = /^[a-f0-9]{16,64}$/;

export const jobDir = (dir: string, id: string): string => path.join(dir, id);
export const releaseDir = (dir: string, release: string): string => path.join(dir, "tour", "_releases", release);

/** Только обычный файл, симлинк не разыменовываем (как `lib/trial/storage.ts:openInput`). */
export async function readRegular(full: string): Promise<Buffer | null> {
  let handle: fs.FileHandle;
  try {
    handle = await fs.open(full, constants.O_RDONLY | constants.O_NOFOLLOW);
  } catch {
    return null;
  }
  try {
    const st = await handle.stat();
    return st.isFile() ? await handle.readFile() : null;
  } finally {
    await handle.close();
  }
}

/** Версия страницы задания из файла `<id>/release`; кривая запись — как нет бандла. */
export async function jobRelease(dir: string, id: string): Promise<string | null> {
  const raw = await readRegular(path.join(jobDir(dir, id), "release"));
  const name = raw ? raw.toString("utf8").trim() : "";
  return RELEASE_RE.test(name) ? name : null;
}

/** Данные страницы задания: последняя опубликованная версия по манифесту (`latestBundle`, `bundle-N.json`) — её номер уходит в ETag
 *  (страница отправляет его как `base_version` кнопки «Обустроить»); версий нет — запасной `demo-data.json` (фикстуры, ручная выкладка). */
export async function readTourData(dir: string, id: string, latest: (id: string, dir: string) => Promise<LatestBundle>): Promise<{ body: Buffer; version: number } | null> {
  const got = await latest(id, dir);
  if (typeof got === "object") return { body: Buffer.from(got.json, "utf8"), version: got.version };
  const old = await readRegular(path.join(jobDir(dir, id), "demo-data.json"));
  return old ? { body: old, version: 0 } : null;
}
