// Ворота ссылки покупателя (план trial-buyer-gate-01, T-20261112-40; владелец 12.11 TG 1778–1780): тур задания с ключом агента
// (`trial_jobs.edit_key_hash`) без ключа не открывается, пока агент не нажал «Подтвердить планировку» (`repo-confirm.ts:askConfirm`).
// Покупателю — заглушка «Ссылка не активирована, обратитесь к вашему менеджеру» (`tour-stub.ts`, вид `inactive`), данных тура нет.
// «Подтверждено» — ОДНА точка правды: есть строка подтверждения в `trial_rebuilds` (`kind = 'edit'`, `progress.confirm`) — та же, по
// которой страница агента показывает время подтверждения (`repo-plan-status.ts:editsView`); статус пересборки не важен: открыто с нажатия.
// Старое задание без ключа (подтвердить некому) — открыто, как раньше.
//
// Кто проходит до подтверждения: ключ агента в адресе (`?k=`, сверка по хэшу); Bearer воркера DEV (снимки карточек
// `tools/scout/trial_cards.mjs`); данные и снимки страницы агента — ещё по cookie-пропуску (`readPass`, не сам ключ): закреплённая
// страница тура грузит `demo-data.json` без ключа (`index.html`, строка 10), пропуск выдаёт страница, открытая с верным `k`
// (старым закреплённым копиям перевыпуск не нужен). Саму СТРАНИЦУ cookie не открывает:
// владелец, открывший ссылку агента, в том же браузере видит у ссылки покупателя заглушку.

import { createHmac } from "node:crypto";
import { sql } from "drizzle-orm";
import { safeEqual } from "@/lib/safe-equal";
import { workerAuth } from "@/lib/trial/auth";
import { editKeyMatches } from "@/lib/trial/edit-key";
import { rows } from "@/lib/trial/sql";
import { TOKEN_RE } from "@/lib/token";

export type TourAccess = { keyHash: string | null; confirmed: boolean };
/** Чем пришёл запрос: ключ из адреса, пропуск из cookie (`readPass`), Bearer воркера. */
export type TourCreds = { urlKey: string | null; cookieKey: string | null; worker: boolean };
export type TourGate = { access: (id: string) => Promise<TourAccess | undefined>; creds: TourCreds; secure?: boolean };
export const OPEN: GateVerdict = { open: true, pass: null };
/** open — отдаём (иначе заглушка / 403); pass — ещё и выдать странице агента cookie-пропуск на данные (`keyCookie`). */
export type GateVerdict = { open: boolean; pass: string | null };

/** Подтверждение строки пересборки — тот же признак, что у `repo-plan-status.ts` (флаг пишет только `askConfirm`, воркер мёржит `||`). */
export const CONFIRMED_SQL = sql`exists (select 1 from trial_rebuilds r where r.job_id = j.id and r.kind = 'edit'
  and r.progress @> '{"confirm": true}'::jsonb)`;

export async function tourAccess(id: string): Promise<TourAccess | undefined> {
  const [r] = await rows<{ edit_key_hash: string | null; confirmed: boolean }>(sql`select j.edit_key_hash, ${CONFIRMED_SQL} as confirmed
      from trial_jobs j where j.id = ${id}`);
  return r ? { keyHash: r.edit_key_hash, confirmed: r.confirmed } : undefined;
}

/** Решение ворот. `page` — сама страница тура (по cookie не открывается); иначе данные / снимки карточек / API данных. */
export async function gateCheck(g: TourGate, id: string, page: boolean): Promise<GateVerdict> {
  const a = await g.access(id);
  if (!a || !a.keyHash) return OPEN;
  const c = g.creds;
  if (c.urlKey && editKeyMatches(c.urlKey, a.keyHash)) return { open: true, pass: page && !a.confirmed ? readPass(id, a.keyHash) : null };
  if (a.confirmed || c.worker) return OPEN;
  if (!page && c.cookieKey && safeEqual(c.cookieKey, readPass(id, a.keyHash))) return OPEN;
  return { open: false, pass: null };
}

export const KEY_COOKIE = "trial_tk";
const COOKIE_DAYS = 30;                          // как срок результата (`config.ts:trialResultDays`): дольше тур не живёт
const PASS_RE = /^[A-Za-z0-9_-]{43}$/;

/** Пропуск на ЧТЕНИЕ данных тура (Codex 12.11: не сам ключ правки — утечка cookie не даёт правок): HMAC хэша ключа по id задания.
 *  Отдельного секрета не нужно — хэш знает только сервер; сменится ключ — пропуск недействителен. */
export const readPass = (id: string, keyHash: string): string =>
  createHmac("sha256", keyHash).update(`tour-read|${id}`).digest("base64url");

/** Пропуск из заголовка Cookie (только правильной формы). */
export function cookieKey(header: string | null): string | null {
  for (const part of (header ?? "").split(";")) {
    const [n, ...v] = part.trim().split("=");
    if (n === KEY_COOKIE) {
      const k = v.join("=");
      return PASS_RE.test(k) ? k : null;
    }
  }
  return null;
}

/** Set-Cookie пропуска агента (`readPass`): только адреса этого тура, без доступа скриптам. */
export const keyCookie = (id: string, pass: string, secure: boolean): string =>
  `${KEY_COOKIE}=${pass}; Path=/try/${id}/tour; Max-Age=${COOKIE_DAYS * 86400}; HttpOnly; SameSite=Lax${secure ? "; Secure" : ""}`;

/** Ворота из запроса: `?k=` (только правильной формы), cookie-пропуск, Bearer воркера. */
export function requestGate(req: Request, access = tourAccess): TourGate {
  const k = new URL(req.url).searchParams.get("k");
  return { access, secure: isSecure(req),
    creds: { urlKey: k !== null && TOKEN_RE.test(k) ? k : null, cookieKey: cookieKey(req.headers.get("cookie")),
      worker: workerAuth(req.headers) === "ok" } };
}

/** API данных задания (`/api/trial/<id>/bundle`, `/result`, Codex 12.11 п.6 — иначе обход ворот тура): тот же закон, без cookie
 *  (её путь — только тур). true — отдавать. */
export async function apiOpen(req: Request, id: string): Promise<boolean> {
  return (await gateCheck(requestGate(req), id, false)).open;
}

/** Запрос пришёл по https (прямо или за Caddy). */
export const isSecure = (req: Request): boolean =>
  new URL(req.url).protocol === "https:" || (req.headers.get("x-forwarded-proto") ?? "").split(",")[0]?.trim() === "https";
