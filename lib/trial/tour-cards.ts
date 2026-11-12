// Снимки карточек комнат тура на томе (T-20261112-29). Папка `<TRIAL_DIR>/<id>/cards/`: файлы `<sha16>.jpg` (по содержимому, не
// меняются — отдаются навсегда) и `index.json` — карта «ключ расстановки → файл». Страница получает карту вместе с HTML
// (`tour-page.ts:injectTour`), поэтому новая версия данных для снимков не нужна и открытая страница не перезагружается.
// Уходят вместе с папкой задания при очистке по сроку.

import { createHash, randomBytes } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

import { CARD_FILE_RE, CARD_KEY_RE } from "@/contracts/trial-cards";
import { jobDir, readRegular } from "@/lib/trial/tour-files";

/** Сколько ключей держит карта: у тура до ~20 вариантов, правки агента добавляют новые — старые вытесняются первыми. */
export const CARD_INDEX_MAX = 300;
const INDEX = "index.json";
const JPEG_MAGIC = Buffer.from([0xff, 0xd8, 0xff]);

const cardsDir = (dir: string, id: string): string => path.join(jobDir(dir, id), "cards");

/** Карта задания: только корректные ключи и имена; нет файла или он битый — пусто (страница снимет сама, как раньше). */
export async function readCardIndex(dir: string, id: string): Promise<Record<string, string>> {
  const raw = await readRegular(path.join(cardsDir(dir, id), INDEX));
  if (!raw) return {};
  try {
    const j = JSON.parse(raw.toString("utf8")) as unknown;
    if (!j || typeof j !== "object" || Array.isArray(j)) return {};
    const out: Record<string, string> = {};
    for (const [k, f] of Object.entries(j as Record<string, unknown>)) {
      if (CARD_KEY_RE.test(k) && typeof f === "string" && CARD_FILE_RE.test(f)) out[k] = f;
    }
    return out;
  } catch {
    return {};
  }
}

/** Карта для страницы: ключ → адрес внутри тура (`cards/<файл>`). */
export async function pageCards(dir: string, id: string): Promise<Record<string, string>> {
  const m = await readCardIndex(dir, id);
  return Object.fromEntries(Object.entries(m).map(([k, f]) => [k, `cards/${f}`]));
}

/** Файл снимка (имя уже проверено `tourTarget`). */
export async function readCard(dir: string, id: string, file: string): Promise<Buffer | null> {
  return CARD_FILE_RE.test(file) ? readRegular(path.join(cardsDir(dir, id), file)) : null;
}

async function writeAtomic(file: string, data: Buffer | string): Promise<void> {
  const tmp = `${file}.${randomBytes(6).toString("hex")}.tmp`;
  await fs.writeFile(tmp, data, { mode: 0o640 });
  await fs.rename(tmp, file);
}

export type CardsWrite = { ok: true; written: number; index: number } | { ok: false; error: "not_found" | "not_jpeg" };

/** Положить снимки: только в существующую настоящую папку задания (симлинк — нет); файл — по содержимому, повтор не переписывается;
 *  карта — слиянием, подменой файла (читатель видит старую или новую целиком). */
export async function writeCards(dir: string, id: string, cards: ReadonlyArray<{ key: string; jpg: Buffer }>): Promise<CardsWrite> {
  const st = await fs.lstat(jobDir(dir, id)).catch(() => null);
  if (!st?.isDirectory()) return { ok: false, error: "not_found" };
  if (cards.some((c) => c.jpg.length < 100 || !c.jpg.subarray(0, 3).equals(JPEG_MAGIC))) return { ok: false, error: "not_jpeg" };
  const cd = cardsDir(dir, id);
  await fs.mkdir(cd, { recursive: true });
  const cst = await fs.lstat(cd);
  if (!cst.isDirectory()) return { ok: false, error: "not_found" };
  let written = 0;
  const add: Record<string, string> = {};
  for (const c of cards) {
    const file = `${createHash("sha256").update(c.jpg).digest("hex").slice(0, 16)}.jpg`;
    const full = path.join(cd, file);
    if (!(await fs.lstat(full).catch(() => null))) {
      await writeAtomic(full, c.jpg);
      written += 1;
    }
    add[c.key] = file;
  }
  const old = await readCardIndex(dir, id);
  for (const k of Object.keys(add)) delete old[k];          // переснятые ключи — в конец (свежие)
  const all = Object.entries({ ...old, ...add });
  const index = Object.fromEntries(all.slice(Math.max(0, all.length - CARD_INDEX_MAX)));
  await writeAtomic(path.join(cd, INDEX), JSON.stringify(index));
  return { ok: true, written, index: Object.keys(index).length };
}
