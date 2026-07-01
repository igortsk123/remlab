// Клиент БД (postgres.js + Drizzle), ленивый синглтон. Подключение только при первом обращении.

import postgres from "postgres";
import { drizzle, type PostgresJsDatabase } from "drizzle-orm/postgres-js";
import * as schema from "@/db/schema";

type Db = PostgresJsDatabase<typeof schema>;

const g = globalThis as unknown as { __remlabDb?: Db };

export function db(): Db {
  if (!g.__remlabDb) {
    const url = process.env.DATABASE_URL;
    if (!url) throw new Error("DATABASE_URL is not set");
    g.__remlabDb = drizzle(postgres(url, { max: 5 }), { schema });
  }
  return g.__remlabDb;
}
