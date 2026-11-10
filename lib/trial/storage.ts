// Файлы пробы на томе (план agent-trial-01, T-A). В базе — ТОЛЬКО имя `<id>.<ext>` (CHECK в `db/init/022-trial-jobs.sql`);
// путь собирается здесь и только из имени, прошедшего ту же проверку: «../», абсолютный путь и симлинк не проходят.
// Наружу файлы не отдаются никогда — только воркеру DEV по Bearer и текущей аренде.

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
  const full = inputPath(dir, name);
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
