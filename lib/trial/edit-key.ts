// Ключ правки агента (план agent-trial-08, Р1): случайный, создаётся вместе с заданием, отдаётся ОДИН раз — в ответе загрузки
// (дальше он живёт только в ссылке агента `?k=`). В базе — sha256 (`trial_jobs.edit_key_hash`): утечка базы ключей не даёт.
// Ссылка покупателя и публичные ответы (`jobView`, страница ожидания, тур) ключа не содержат.

import { createHash } from "node:crypto";
import { safeEqual } from "@/lib/safe-equal";
import { randomToken, TOKEN_RE } from "@/lib/token";

export const editKeyHash = (key: string): string => createHash("sha256").update(key, "utf8").digest("hex");

export function newEditKey(): { key: string; hash: string } {
  const key = randomToken();
  return { key, hash: editKeyHash(key) };
}

/** Ключ правки из адреса чтения (`?k=`, T-20261111-16: `edits`, `rebuild-status`); null — нет или не того вида. */
export function editKeyParam(req: Request): string | null {
  const k = new URL(req.url).searchParams.get("k");
  return k !== null && TOKEN_RE.test(k) ? k : null;
}

/** Ключ из ссылки подходит к заданию. Нет хэша (старое задание) — правки нет ни у кого. */
export function editKeyMatches(key: string, hash: string | null): boolean {
  return !!hash && TOKEN_RE.test(key) && safeEqual(editKeyHash(key), hash);
}
