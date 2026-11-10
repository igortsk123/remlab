// Звать ли агента написать размеры словами (план agent-trial-08, Р2-текст): размеров нет — масштаб `not_verified` (опоры не нашли) или
// `area` (по общей площади, примерный), — или в данных есть комнаты, ждущие проверки размера (`awaiting_check`). Комнаты при `area` в «ждут»
// не переводим — меняется только показ окошка. Читаем опубликованную версию данных страницы (`trial_bundle.py`: `trial.scale`,
// `apartment_rooms[].furniture_state`); версия неизменна — ответ запоминаем по (задание, версия), опрос раз в 1,5 с файл не перечитывает.

import { readBundle } from "@/lib/trial/bundle";
import { trialDir } from "@/lib/trial/config";

const ASK_SCALES = new Set(["not_verified", "area"]);
const MEMO_MAX = 500;
const memo = new Map<string, boolean>();

type BundleBits = { trial?: { scale?: unknown }; apartment_rooms?: { furniture_state?: unknown }[] };

/** Масштаб результата (`floorplanResult.scale.status`) зовёт агента? */
export const scaleAsks = (status: unknown): boolean => ASK_SCALES.has(String(status));

/** По тексту данных страницы: true — окошко «размеры своими словами» нужно. Битые данные — false (окошко не мешает туру). */
export function asksSizes(json: string): boolean {
  try {
    const d = JSON.parse(json) as BundleBits;
    if (scaleAsks(d.trial?.scale)) return true;
    return (d.apartment_rooms ?? []).some((r) => r.furniture_state === "awaiting_check");
  } catch {
    return false;
  }
}

/** Версия 0 (ещё не публиковали) или нет файла — false. */
export async function sizeAsk(id: string, version: number, dir = trialDir()): Promise<boolean> {
  if (version < 1) return false;
  const key = `${dir}\n${id}\n${version}`;
  const hit = memo.get(key);
  if (hit !== undefined) return hit;
  const json = await readBundle(dir, id, version);
  if (json === null) return false;
  const ask = asksSizes(json);
  if (memo.size >= MEMO_MAX) memo.delete(memo.keys().next().value as string);
  memo.set(key, ask);
  return ask;
}
