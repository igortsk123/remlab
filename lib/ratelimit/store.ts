// Хранилище счётчиков частоты (план b2b-01). DATABASE_URL → Postgres (переживает перезапуск
// приложения и считает одинаково при нескольких процессах), иначе память процесса (локально/тесты).

import { sql } from "drizzle-orm";
import { db } from "@/lib/db";

export interface CounterStore {
  /** +1 к счётчику окна; возвращает значение ПОСЛЕ увеличения. */
  hit(key: string, windowStart: Date): Promise<number>;
  /** Удалить окна, начавшиеся раньше `before`. */
  prune(before: Date): Promise<void>;
}

export class MemoryCounterStore implements CounterStore {
  private readonly counts = new Map<string, { start: number; count: number }>();
  async hit(key: string, windowStart: Date): Promise<number> {
    const k = `${key}|${windowStart.getTime()}`;
    const cur = this.counts.get(k) ?? { start: windowStart.getTime(), count: 0 };
    cur.count += 1;
    this.counts.set(k, cur);
    return cur.count;
  }
  async prune(before: Date): Promise<void> {
    for (const [k, v] of this.counts) if (v.start < before.getTime()) this.counts.delete(k);
  }
}

class PgCounterStore implements CounterStore {
  async hit(key: string, windowStart: Date): Promise<number> {
    const rows = await db().execute<{ count: number }>(sql`
      insert into rate_limits (key, window_start, count) values (${key}, ${windowStart.toISOString()}, 1)
      on conflict (key, window_start) do update set count = rate_limits.count + 1
      returning count`);
    return Number(rows[0]?.count ?? 0);
  }
  async prune(before: Date): Promise<void> {
    await db().execute(sql`delete from rate_limits where window_start < ${before.toISOString()}`);
  }
}

const g = globalThis as unknown as { __remlabCounterStore?: CounterStore };

export function counterStore(): CounterStore {
  if (!g.__remlabCounterStore) {
    g.__remlabCounterStore = process.env.DATABASE_URL ? new PgCounterStore() : new MemoryCounterStore();
  }
  return g.__remlabCounterStore;
}
