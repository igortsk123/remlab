// Файлы фото тура на томе (T-20261112-115 Ф1): папка `<TRIAL_DIR>/<id>/photos/`, имя — по содержимому (`<sha16>.jpg`, миниатюра
// `<sha16>.t.jpg`), файл не меняется — отдаётся навсегда. Уходят вместе с папкой задания по сроку тура (`bundle.ts:removeBundles`).
// Пишет только завершение заказа (`repo-photo-done.ts`), читает тур (`tour.ts`, адрес `photos/<файл>` за воротами покупателя).

import { createHash, randomBytes } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

import { PHOTO_FILE_RE } from "@/contracts/trial-photos";
import { sniffMime } from "@/lib/trial/storage";
import { jobDir, readRegular } from "@/lib/trial/tour-files";

const EXT = { "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp" } as const;
type PhotoMime = keyof typeof EXT;
export const PHOTO_TYPES: Record<string, PhotoMime> = { jpg: "image/jpeg", png: "image/png", webp: "image/webp" };

const photosDir = (dir: string, id: string): string => path.join(jobDir(dir, id), "photos");

/** Картинка ли это и какого вида (по первым байтам); остальное — null. */
export function photoMime(buf: Buffer): PhotoMime | null {
  const m = buf.length >= 100 ? sniffMime(buf.subarray(0, 16)) : null;
  return m && m in EXT ? (m as PhotoMime) : null;
}

/** Имя файла по содержимому: `<sha16>[.t].<ext>`. */
export const photoName = (buf: Buffer, mime: PhotoMime, thumb = false): string =>
  `${createHash("sha256").update(buf).digest("hex").slice(0, 16)}${thumb ? ".t" : ""}.${EXT[mime]}`;

export type PhotoWrite = { ok: true; names: string[] } | { ok: false; error: "not_found" | "not_image" | "write_failed" };

/** Положить файлы: только в существующую настоящую папку задания (симлинк — нет); готовый файл не переписывается; после записи —
 *  проверка, что каждый файл на месте и того же размера (иначе `write_failed`: строку `done` не ставим). Порядок имён = порядок входа. */
export async function writePhotos(dir: string, id: string, files: ReadonlyArray<{ buf: Buffer; thumb?: boolean }>): Promise<PhotoWrite> {
  const st = await fs.lstat(jobDir(dir, id)).catch(() => null);
  if (!st?.isDirectory()) return { ok: false, error: "not_found" };
  const typed = files.map((f) => ({ ...f, mime: photoMime(f.buf) }));
  if (typed.some((f) => !f.mime)) return { ok: false, error: "not_image" };
  const pd = photosDir(dir, id);
  await fs.mkdir(pd, { recursive: true });
  if (!(await fs.lstat(pd)).isDirectory()) return { ok: false, error: "not_found" };
  const names: string[] = [];
  for (const f of typed) {
    const name = photoName(f.buf, f.mime!, f.thumb);
    const full = path.join(pd, name);
    if (!(await fs.lstat(full).catch(() => null))) {
      const tmp = `${full}.${randomBytes(6).toString("hex")}.tmp`;
      await fs.writeFile(tmp, f.buf, { mode: 0o640 });
      await fs.rename(tmp, full);
    }
    const got = await fs.lstat(full).catch(() => null);
    if (!got?.isFile() || got.size !== f.buf.length) return { ok: false, error: "write_failed" };
    names.push(name);
  }
  return { ok: true, names };
}

/** Файл фото тура (имя уже проверено `tourTarget`). */
export async function readPhoto(dir: string, id: string, file: string): Promise<Buffer | null> {
  return PHOTO_FILE_RE.test(file) ? readRegular(path.join(photosDir(dir, id), file)) : null;
}
