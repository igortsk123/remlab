// Health-ответ (regression-net §12.1; план b2b-09, ADR-0266): кроме версии — живые проверки. База
// недоступна → `ok:false` и 503 (сайт без базы не работает: деплой-смоук откатит такой выпуск, сторож
// на сервере пришлёт тревогу). Витрина демо — состояние «degraded», не провал: страница живёт со старыми данными.

import { sql } from "drizzle-orm";
import { db } from "@/lib/db";
import { loadDemoRaw } from "@/lib/partners/demo-data";
import { traceWriteFailures } from "@/lib/trace/failures";

export type Check = "ok" | "fail" | "skipped";
export type Health = {
  ok: boolean;
  service: "remlab";
  version: string;
  ts: string;
  traceWriteFailures: number;
  checks: { db: Check; showcase: Check };
};

export function buildHealth(now: Date = new Date(), checks: Health["checks"] = { db: "skipped", showcase: "skipped" }): Health {
  return {
    ok: checks.db !== "fail",
    service: "remlab",
    version: process.env.APP_VERSION ?? "dev",
    ts: now.toISOString(),
    traceWriteFailures: traceWriteFailures(),
    checks,
  };
}

const withTimeout = <T,>(p: Promise<T>, ms: number) =>
  Promise.race([p, new Promise<never>((_, rej) => setTimeout(() => rej(new Error("timeout")), ms))]);

export async function dbCheck(): Promise<Check> {
  if (!process.env.DATABASE_URL) return "skipped";
  try {
    await withTimeout(db().execute(sql`select 1`), 2_000);
    return "ok";
  } catch {
    return "fail";
  }
}

export async function showcaseCheck(src = "/demo/demo-data.json"): Promise<Check> {
  if (!process.env.DATABASE_URL) return "skipped"; // локально и в тестах витрины нет
  const raw = await loadDemoRaw(src).catch(() => null);
  return raw && Array.isArray((raw as { variants?: unknown }).variants) ? "ok" : "fail";
}
