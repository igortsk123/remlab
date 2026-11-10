// Наши машины без лимита загрузки пробы (владелец 10.11, TG 744; T-20261110-24): заголовок `x-trial-own-key` с ключом
// `TRIAL_OWN_KEY` (значение — только в `.env` сервера и DEV, в git его нет) пропускает адресный лимит (`PRESETS.trialUpload`) и
// суточный потолок сайта (`lib/trial/repo-create.ts`). Очередь (`TRIAL_QUEUE_MAX`) — не лимит, а ёмкость: держит и наших.
// Ключа на сервере нет или он короче 32 знаков — пропуска нет ни у кого. Сравнение — за постоянное время по sha256 (длины
// равны), сам ключ никуда не пишется.
// Браузер заголовок слать не может, поэтому второй путь — адрес (владелец TG 779; T-20261110-28): `TRIAL_OWN_IPS` — адреса
// через запятую, точное совпадение с `clientIp` (тот же адрес, что видит лимитер); пусто — пропуска по адресу нет.

import { createHash } from "node:crypto";
import { clientIp } from "@/lib/ratelimit/http";
import { safeEqual } from "@/lib/safe-equal";

export const TRIAL_OWN_HEADER = "x-trial-own-key";
const MIN_KEY = 32;

const digest = (s: string): string => createHash("sha256").update(s, "utf8").digest("hex");

function ownByKey(headers: Headers, env: NodeJS.ProcessEnv): boolean {
  const want = env.TRIAL_OWN_KEY ?? "";
  const got = headers.get(TRIAL_OWN_HEADER) ?? "";
  if (want.length < MIN_KEY || !got) return false;
  return safeEqual(digest(got), digest(want));
}

function ownByIp(headers: Headers, env: NodeJS.ProcessEnv): boolean {
  const list = (env.TRIAL_OWN_IPS ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (list.length === 0) return false;
  const ip = clientIp(headers);
  return ip !== "local" && list.includes(ip);
}

/** true — запрос с нашей машины: верный ключ в заголовке или адрес из `TRIAL_OWN_IPS`. */
export function isOwnMachine(headers: Headers, env = process.env): boolean {
  return ownByKey(headers, env) || ownByIp(headers, env);
}
