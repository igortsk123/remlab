// Подписанные (signed) ссылки на ассеты трейса. Цель: владелец открывает картинку по ссылке в
// браузере, НЕ раскрывая админ-токен (его нельзя светить в чат/URL). Подпись — HMAC-SHA256 от id+exp
// на ключе TRACE_ADMIN_TOKEN (отдельный секрет не заводим; HMAC односторонний — токен из ссылки не
// восстановить). Ссылка ограничена по времени (TTL). Токен не задан (dev) → доступ открыт, без подписи.

import { createHmac, timingSafeEqual } from "node:crypto";

const DEFAULT_TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 дней

function ttlMs(): number {
  const raw = Number(process.env.TRACE_ASSET_TTL_MS);
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_TTL_MS;
}

function signingKey(): string | null {
  return process.env.TRACE_ADMIN_TOKEN || null;
}

function hmac(id: string, exp: number, secret: string): string {
  return createHmac("sha256", secret).update(`${id}.${exp}`).digest("hex");
}

// Суффикс запроса для ссылки: "?exp=..&sig=.." или "" если подпись не нужна (dev, токен не задан).
export function signAssetQuery(id: string, now: number): string {
  const secret = signingKey();
  if (!secret) return "";
  const exp = now + ttlMs();
  return `?exp=${exp}&sig=${hmac(id, exp, secret)}`;
}

// Проверка подписи из asset-роута. Токен не задан (dev) → true. Иначе: exp не просрочен и sig совпал.
export function verifyAssetSig(id: string, expRaw: string | null, sigRaw: string | null, now: number): boolean {
  const secret = signingKey();
  if (!secret) return true;
  if (!expRaw || !sigRaw) return false;
  const exp = Number(expRaw);
  if (!Number.isInteger(exp) || exp < now) return false;
  const expected = hmac(id, exp, secret);
  const a = Buffer.from(expected, "utf8");
  const b = Buffer.from(sigRaw, "utf8");
  return a.length === b.length && timingSafeEqual(a, b);
}
