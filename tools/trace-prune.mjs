// Ретеншн трейсов: удалить прогоны (+ шаги, ассеты, файлы) старше TRACE_RETENTION_DAYS (дефолт 90).
// Запуск: pnpm trace:prune  (на сервере — из таймера remlab-cleanup, с DATABASE_URL/TRACE_DIR из env).

import postgres from "postgres";
import { promises as fs } from "node:fs";
import path from "node:path";

const days = Number(process.env.TRACE_RETENTION_DAYS || 90);
const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL не задан");
  process.exit(1);
}
const TRACE_DIR = process.env.TRACE_DIR || path.join(process.cwd(), ".data", "traces");

const sql = postgres(url, { max: 1 });
try {
  const old = await sql`
    select id from generation_runs where started_at < now() - make_interval(days => ${days})`;
  for (const r of old) {
    await fs.rm(path.join(TRACE_DIR, r.id), { recursive: true, force: true }).catch(() => {});
  }
  const ids = old.map((r) => r.id);
  if (ids.length) {
    await sql`delete from generation_assets where run_id in ${sql(ids)}`;
    await sql`delete from generation_steps where run_id in ${sql(ids)}`;
    await sql`delete from generation_runs where id in ${sql(ids)}`;
  }
  // Подчистить временные оригиналы сжатия (imagor), если залежались.
  await fs.rm(path.join(TRACE_DIR, "_tmp"), { recursive: true, force: true }).catch(() => {});
  console.log(`trace:prune: удалено прогонов ${ids.length} (старше ${days} дн.)`);
} finally {
  await sql.end();
}
