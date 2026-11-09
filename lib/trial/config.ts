// Настройки пробы (план agent-trial-01, T-A): всё — env с безопасными значениями по умолчанию (поправки Codex 09.11).

import path from "node:path";

const envInt = (v: string | undefined, dflt: number, max: number): number => {
  const n = Number(v);
  return Number.isInteger(n) && n > 0 ? Math.min(n, max) : dflt;
};

/** Папка файлов пробы: прод — том `remlab-trial` в `/app/data/trial`; локально — `.data/trial`. */
export function trialDir(env = process.env): string {
  return env.TRIAL_DIR || path.join(process.cwd(), ".data", "trial");
}

export const TRIAL_FILE_MAX_BYTES = 15 * 1024 * 1024; // лимит ФАЙЛА; Caddy 16 МБ — внешний заслон на всё тело
export const TRIAL_BODY_MAX_BYTES = 16 * 1024 * 1024; // всё тело multipart (файл + поля + разметка)
export const TRIAL_LISTING_MAX = 5000;
export const TRIAL_RESULT_MAX_BYTES = 2 * 1024 * 1024;
export const TRIAL_BUNDLE_MAX_BYTES = 8 * 1024 * 1024; // данные страницы: живой /demo ≈ 1,3 МБ; Caddy 16 МБ — внешний заслон
export const TRIAL_LEASE_SEC = 60; // heartbeat раз в 10 с продлевает на 60 с
export const TRIAL_WORKER_ALIVE_SEC = 30; // воркер опрашивает раз в 2 с; 30 с тишины — «не на связи»
export const TRIAL_STALE_HOURS = 24; // незавершённое задание старше суток — failed/stale (retention)
export const TRIAL_TOMBSTONE_DAYS = 90; // «надгробие» (410) живёт ещё 90 дней после снятия результата

/** Суточный потолок заданий на весь сайт: 30 × $0,10 = $3 (поправка Codex: не 50). */
export const trialDailyCap = (env = process.env) => envInt(env.TRIAL_DAILY_CAP, 30, 1000);
/** Сколько заданий может ждать в очереди; больше — 503 «busy». */
export const trialQueueMax = (env = process.env) => envInt(env.TRIAL_QUEUE_MAX, 5, 100);
/** Исходный файл — 24 ч после финального статуса, максимум 7 дней (диагностика). */
export const trialFileHours = (env = process.env) => envInt(env.TRIAL_FILE_RETENTION_HOURS, 24, 168);
/** Результат — 30 дней (потом 410). */
export const trialResultDays = (env = process.env) => envInt(env.TRIAL_RESULT_RETENTION_DAYS, 30, 365);

/** «Обустроить» (план agent-trial-08, Р1): пересборок на одно задание за сутки — DEV тратит минуты машины, не деньги. */
export const trialRebuildDaily = (env = process.env) => envInt(env.TRIAL_REBUILD_DAILY, 10, 100);
/** Квота приоритета: пересборки идут раньше новых загрузок, но не больше стольких подряд, пока загрузка ждёт. */
export const trialRebuildQuota = (env = process.env) => envInt(env.TRIAL_REBUILD_QUOTA, 2, 20);
/** Витрина `/demo` в контейнере приложения (docker-compose: `./demo:/srv/demo:ro`) — источник закреплённой страницы тура. */
export const trialDemoDir = (env = process.env): string => env.DEMO_DIR || "/srv/demo";

/** Заголовки всех ответов пробы: ключ ссылки не уходит в Referer и не оседает в кэшах. */
export const TRIAL_HEADERS = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" } as const;
