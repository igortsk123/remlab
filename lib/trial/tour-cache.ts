// Кэш тура пробы (T-20261110-43, П1 «скорость открытия»): повторное открытие — без повторной загрузки страницы и данных.
// Браузер хранит ответ, но перед показом сверяет метку (`no-cache` + ETag): не изменилось — 304 без тела, изменилось — новое тело.
// Страница с ключом агента `k` в адресе — как раньше, не хранится (ключ не оседает в кэше браузера: адрес — ключ записи кэша).
// Метка сжатого ответа: Caddy (`encode`) дописывает к ней `-zstd`/`-gzip` и снимает суффикс со входящего If-None-Match сам.

import { createHash } from "node:crypto";

/** Хранить, но сверять каждый раз: свежесть та же, что у no-store, — сеть тратит только 304. */
export const REVALIDATE = "private, no-cache";
/** Файлы с хешем содержимого в имени (`lib/scene.<хеш>.js`, `lib/basket.<хеш>.js` — `tools/flat3d/build-scene-bundle.mjs`): не меняются никогда. */
export const IMMUTABLE = "private, max-age=31536000, immutable";

/** Метка по содержимому: одинаковое тело — одна метка (страница тура: релиз витрины + id + версия тура + песочница — всё внутри тела). */
export const contentTag = (body: Uint8Array | string): string =>
  `"h${createHash("sha256").update(body).digest("base64url").slice(0, 22)}"`;

/** Метка сжатого представления: у каждого сжатия своя (`"h…-br"`), как Caddy делает `-zstd`/`-gzip` (RFC 9110 §8.8.3). */
export const encodedTag = (tag: string, enc: string): string => `${tag.slice(0, -1)}-${enc}"`;

/** If-None-Match совпал с меткой: список через запятую, `*`, слабая форма `W/` — слабое сравнение (RFC 9110 §13.1.2, для 304 так и
 *  положено); суффикс сжатия (`-br`; `-zstd`/`-gzip` Caddy снимает сам) — то же тело. */
export function tagMatches(ifNoneMatch: string | null | undefined, tag: string): boolean {
  if (!ifNoneMatch) return false;
  return ifNoneMatch.split(",").some((t) => {
    const s = t.trim();
    return s === "*" || s.replace(/^W\//, "").replace(/-(?:br|zstd|gzip)"$/, '"') === tag;
  });
}
