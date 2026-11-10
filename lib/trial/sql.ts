// Общие куски SQL очереди пробы (план agent-trial-01, T-A). Условие «можно забрать» — ОДНО на claim и на счёт
// `queueAhead` страницы (поправка Codex: позицию не храним, считаем тем же условием и порядком).

import { sql, type SQL } from "drizzle-orm";
import { db } from "@/lib/db";
import { trialFileHours, trialResultDays } from "@/lib/trial/config";

/** Время в ISO-8601 UTC (строки драйвера `2026-11-09 13:12:00+00` Date разбирает не везде). */
export const iso = (col: SQL): SQL => sql`to_char(${col} at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')`;

/** Задание можно отдать воркеру: в очереди и пора, или аренда истекла; попытки не исчерпаны; файл на месте. */
export const claimable = (t: SQL): SQL => sql`(((${t}.status = 'queued' and ${t}.next_run_at <= now())
  or (${t}.status = 'running' and ${t}.lease_until < now()))
  and ${t}.attempt < ${t}.max_attempts and ${t}.input_path is not null)`;

/** Поля финального статуса: сроки файла и результата (оба 30 дн., `lib/trial/config.ts`) считаются от него. Пересборки срок не продлевают. */
export const terminalSet = (env = process.env): SQL => sql`finished_at = now(), lease_until = null,
  expires_at = now() + make_interval(hours => ${trialFileHours(env)}::int),
  result_expires_at = now() + make_interval(days => ${trialResultDays(env)}::int)`;

/** Строки запроса как массив (postgres-js отдаёт массив-результат). */
export async function rows<T>(q: SQL): Promise<T[]> {
  return (await db().execute(q)) as unknown as T[];
}

/** jsonb из драйвера: объект или (на всякий случай) строка. */
export const jsonOf = <T>(v: unknown): T => (typeof v === "string" ? (JSON.parse(v) as T) : (v as T));
