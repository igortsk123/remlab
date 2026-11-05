import { spawnSync } from "node:child_process";

import { describe, expect, it } from "vitest";

// БЕЗОПАСНАЯ МИГРАЦИЯ ДЕВ-БД (onb-12 ч.2): `tools/ops/db-migrate-safe.sh` — пауза кронов → дамп → SQL одной транзакцией с
// проверкой → снятие паузы всегда → журнал. Самопроверка идёт на заглушках psql/pg_dump и временном замке: базу не трогает.

describe("db-migrate-safe.sh", () => {
  it("самопроверка: порядок шагов, откат при ошибке, пауза снимается всегда, отказы ввода", () => {
    const r = spawnSync("bash", ["tools/ops/db-migrate-safe.sh", "selftest"], { encoding: "utf8", timeout: 60_000 });
    expect(r.stdout + r.stderr).toMatch(/db-migrate-safe selftest: ошибок 0/);
    expect(r.status).toBe(0);
  }, 70_000);
});
