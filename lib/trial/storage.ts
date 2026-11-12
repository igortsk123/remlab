// Файлы пробы на томе (план agent-trial-01, T-A). В базе — ТОЛЬКО имя `<id>.<ext>` (CHECK в `db/init/022-trial-jobs.sql`);
// путь собирается здесь и только из имени, прошедшего ту же проверку: «../», абсолютный путь и симлинк не проходят.
// Кому отдаются: воркеру DEV по Bearer и текущей аренде; агенту — его же файл и превью чертежа во вкладке тура «План квартиры», только по
// ключу его ссылки `?k=` (T-20261112-52, `lib/trial/tour-source.ts`). Покупателю (без ключа) — никогда.

import { constants, promises as fs } from "node:fs";
import path from "node:path";

export type TrialMime = "image/jpeg" | "image/png" | "image/webp" | "image/avif" | "application/pdf";

const EXT: Record<TrialMime, string> = {
  "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/avif": "avif", "application/pdf": "pdf",
};
export const INPUT_NAME_RE = /^[A-Za-z0-9_-]{22}\.(jpg|png|webp|avif|pdf)$/;
/** AVIF (T-20261110-38: планы с сайтов застройщиков, «Этажи»): ISO BMFF `ftyp` с брендом avif/avis; в PNG переводит воркер. */
const AVIF_BRANDS = new Set(["avif", "avis"]);

/** Тип по первым байтам (тип от клиента не слушаем). Нужно ≥ 12 байт; не узнали — null. */
export function sniffMime(head: Buffer): TrialMime | null {
  if (head.length >= 3 && head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) return "image/jpeg";
  if (head.length >= 8 && head.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return "image/png";
  if (head.length >= 12 && head.subarray(0, 4).toString("latin1") === "RIFF" && head.subarray(8, 12).toString("latin1") === "WEBP") return "image/webp";
  if (head.length >= 5 && head.subarray(0, 5).toString("latin1") === "%PDF-") return "application/pdf";
  if (head.length >= 12 && head.subarray(4, 8).toString("latin1") === "ftyp" && AVIF_BRANDS.has(head.subarray(8, 12).toString("latin1"))) {
    return "image/avif";
  }
  return null;
}

export function inputName(id: string, mime: TrialMime): string {
  return `${id}.${EXT[mime]}`;
}

/** Полный путь по имени из базы; кривое имя (traversal, чужое расширение) — null. */
export function inputPath(dir: string, name: string | null): string | null {
  if (!name || !INPUT_NAME_RE.test(name)) return null;
  const base = path.resolve(dir);
  const full = path.resolve(base, name);
  return path.dirname(full) === base ? full : null;
}

/** Открыть файл задания на чтение: только обычный файл, симлинк не разыменовываем (O_NOFOLLOW). */
export async function openInput(dir: string, name: string | null): Promise<{ handle: fs.FileHandle; size: number } | null> {
  return openRegular(inputPath(dir, name));
}

/** Превью чертежа (T-20261112-52): `<id>.src.webp` рядом с файлом задания; имя — то же правило, что CHECK `db/init/033-trial-preview.sql`. */
export const PREVIEW_NAME_RE = /^[A-Za-z0-9_-]{22}\.src\.webp$/;
export const PREVIEW_MAX_BYTES = 3 * 1024 * 1024; // = tools/floorplan/worker.py:SOURCE_MAX
export const previewName = (id: string) => `${id}.src.webp`;

/** Полный путь превью по имени из базы; кривое имя — null. */
export function previewPath(dir: string, name: string | null): string | null {
  if (!name || !PREVIEW_NAME_RE.test(name)) return null;
  const base = path.resolve(dir);
  const full = path.resolve(base, name);
  return path.dirname(full) === base ? full : null;
}

/** Записать превью подменой (читатель не видит половину файла). → имя для базы. */
export async function writePreview(dir: string, id: string, data: Buffer): Promise<string> {
  const name = previewName(id);
  const full = previewPath(dir, name);
  if (!full) throw new Error("bad preview name");
  await fs.mkdir(path.dirname(full), { recursive: true });
  const tmp = `${full}.${process.pid}.part`;
  await fs.writeFile(tmp, data, { mode: 0o600 });
  await fs.rename(tmp, full);
  return name;
}

/** Открыть превью на чтение — как `openInput` (без симлинков, только обычный файл). */
export async function openPreview(dir: string, name: string | null): Promise<{ handle: fs.FileHandle; size: number } | null> {
  return openRegular(previewPath(dir, name));
}

async function openRegular(full: string | null): Promise<{ handle: fs.FileHandle; size: number } | null> {
  if (!full) return null;
  let handle: fs.FileHandle;
  try {
    handle = await fs.open(full, constants.O_RDONLY | constants.O_NOFOLLOW);
  } catch {
    return null;
  }
  const st = await handle.stat();
  if (!st.isFile()) {
    await handle.close();
    return null;
  }
  return { handle, size: st.size };
}

/** Удалить файл задания: нет файла — тоже успех; иначе ошибка наверх (строку не трогаем, повторим). */
export async function removeInput(dir: string, name: string, rm: typeof fs.rm = fs.rm): Promise<void> {
  const full = inputPath(dir, name);
  if (!full) return; // кривое имя в базе: удалять нечего и нельзя — ссылку снимет вызывающий
  await rm(full, { force: true });
}
