// Файлы данных страницы задания на томе (план agent-trial-08, задача А). Папка `<TRIAL_DIR>/<id>/`, файлы `bundle-<версия>.json` НЕИЗМЕНЯЕМЫЕ;
// какая версия текущая — знает только строка `trial_jobs.bundle_version` (манифест). Имя строится здесь из числа и id, прошедшего TOKEN_RE:
// ни пути, ни имени снаружи не приходит, симлинк не разыменовывается. Папка заданий — том пробы, не `/opt/remlab/demo` (там `rsync --delete`).

import { randomBytes } from "node:crypto";
import { constants, promises as fs } from "node:fs";
import path from "node:path";
import { TOKEN_RE } from "@/lib/token";

const NAME_RE = /^bundle-([1-9][0-9]{0,8})\.json$/;
const TMP_RE = /^\.bundle-.*\.tmp$/;
const STALE_TMP_MS = 3_600_000;

export const bundleName = (version: number): string => `bundle-${version}.json`;

/** Папка задания или null, если id не годится (`../`, чужой формат). */
export function bundleDir(dir: string, id: string): string | null {
  if (!TOKEN_RE.test(id)) return null;
  const base = path.resolve(dir);
  const full = path.resolve(base, id);
  return path.dirname(full) === base ? full : null;
}

/** Папка задания без симлинков: настоящая папка → путь, иначе null. */
async function realDir(dir: string, id: string): Promise<string | null> {
  const d = bundleDir(dir, id);
  if (!d) return null;
  const st = await fs.lstat(d).catch(() => null);
  return st?.isDirectory() ? d : null;
}

/** Записать версию целиком: временный файл → fsync → rename. Читатель видит файл только целым; неудача — исключение наверх. */
export async function writeBundle(dir: string, id: string, version: number, json: string): Promise<void> {
  const d = bundleDir(dir, id);
  if (!d) throw new Error("bad_job_id");
  await fs.mkdir(d, { recursive: true });
  if (!(await realDir(dir, id))) throw new Error("bundle_dir_not_a_directory");
  const tmp = path.join(d, `.bundle-${version}.${randomBytes(6).toString("hex")}.tmp`);
  const h = await fs.open(tmp, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o640);
  try {
    await h.writeFile(json, "utf8");
    await h.sync();
  } finally {
    await h.close();
  }
  await fs.rename(tmp, path.join(d, bundleName(version)));
}

/** Текст версии; нет файла, симлинк, не обычный файл — null. */
export async function readBundle(dir: string, id: string, version: number): Promise<string | null> {
  const d = await realDir(dir, id);
  if (!d || !Number.isInteger(version) || version <= 0) return null;
  let h: fs.FileHandle;
  try {
    h = await fs.open(path.join(d, bundleName(version)), constants.O_RDONLY | constants.O_NOFOLLOW);
  } catch {
    return null;
  }
  try {
    return (await h.stat()).isFile() ? await h.readFile("utf8") : null;
  } finally {
    await h.close();
  }
}

/** Убрать версии старше `keepFrom` и забытые временные файлы. Вспомогательно: ошибка не мешает публикации. */
export async function pruneBundles(dir: string, id: string, keepFrom: number, now = Date.now()): Promise<void> {
  const d = await realDir(dir, id);
  if (!d) return;
  for (const n of await fs.readdir(d).catch(() => [] as string[])) {
    const full = path.join(d, n);
    const m = NAME_RE.exec(n);
    const old = m ? Number(m[1]) < keepFrom : TMP_RE.test(n) && ((await fs.lstat(full).catch(() => null))?.mtimeMs ?? now) < now - STALE_TMP_MS;
    if (old) await fs.rm(full, { force: true }).catch(() => undefined);
  }
}

/** Удалить папку задания целиком (срок хранения). Симлинк на месте папки не разыменовывается: убирается сам. */
export async function removeBundles(dir: string, id: string, rm: typeof fs.rm = fs.rm): Promise<void> {
  const d = bundleDir(dir, id);
  if (d) await rm(d, { recursive: true, force: true });
}
