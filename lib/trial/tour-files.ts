// Файлы тура пробы на томе (план agent-trial-08). Закреплённая версия витрины — общая папка `tour/_releases/<версия>/`,
// какая версия у задания — файл `<id>/release` в папке задания. Данные задания читает ТОЛЬКО `readTourData` (хранилище — у ветки данных).

import { constants, promises as fs } from "node:fs";
import path from "node:path";

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

/** Текущий `demo-data.json` задания. Единственное место чтения данных: при вливании ветки данных заменяется на `bundle-N.json` по манифесту. */
export const readTourData = (dir: string, id: string): Promise<Buffer | null> =>
  readRegular(path.join(jobDir(dir, id), "demo-data.json"));
