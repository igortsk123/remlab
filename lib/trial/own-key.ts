// Наши машины без лимита загрузки пробы (владелец 10.11, TG 744; T-20261110-24): заголовок `x-trial-own-key` с ключом
// `TRIAL_OWN_KEY` (значение — только в `.env` сервера и DEV, в git его нет) пропускает адресный лимит (`PRESETS.trialUpload`) и
// суточный потолок сайта (`lib/trial/repo-create.ts`). Очередь (`TRIAL_QUEUE_MAX`) — не лимит, а ёмкость: держит и наших.
// Ключа на сервере нет или он короче 32 знаков — пропуска нет ни у кого. Сравнение — за постоянное время по sha256 (длины
// равны), сам ключ никуда не пишется.

import { createHash } from "node:crypto";
import { safeEqual } from "@/lib/safe-equal";

export const TRIAL_OWN_HEADER = "x-trial-own-key";
const MIN_KEY = 32;

const digest = (s: string): string => createHash("sha256").update(s, "utf8").digest("hex");

/** true — запрос с нашей машины (верный ключ в заголовке). */
export function isOwnMachine(headers: Headers, env = process.env): boolean {
  const want = env.TRIAL_OWN_KEY ?? "";
  const got = headers.get(TRIAL_OWN_HEADER) ?? "";
  if (want.length < MIN_KEY || !got) return false;
  return safeEqual(digest(got), digest(want));
}
