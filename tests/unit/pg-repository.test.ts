import { describe, it, expect, beforeAll, afterAll } from "vitest";

// Интеграция PgRepository против реальной Postgres. Гоняется только при заданном TEST_DATABASE_URL
// (локально — временный контейнер; в CI — сервис postgres). Иначе пропускается.
const URL = process.env.TEST_DATABASE_URL;

describe.skipIf(!URL)("PgRepository (real postgres)", () => {
  beforeAll(async () => {
    process.env.DATABASE_URL = URL;
    const postgres = (await import("postgres")).default;
    const sql = postgres(URL!, { max: 1 });
    await sql`create table if not exists projects (
      id text primary key, session_id text not null, data jsonb not null,
      created_at timestamptz not null default now(), updated_at timestamptz not null default now())`;
    await sql`create index if not exists projects_session_idx on projects (session_id)`;
    await sql.end();
  });

  afterAll(() => {
    delete process.env.DATABASE_URL;
  });

  it("create → get → update → listBySession", async () => {
    const { PgRepository } = await import("@/modules/store/pg-repository");
    const { project: projectSchema } = await import("@/contracts/project");
    const r = new PgRepository();
    const now = new Date().toISOString();
    const sid = `sess-${now}`;
    const p = projectSchema.parse({
      id: `pg-${now}`, sessionId: sid, title: "Гостиная", status: "style_done",
      createdAt: now, updatedAt: now, brief: { roomType: "living_room" },
    });

    await r.create(p);
    expect((await r.get(p.id))?.id).toBe(p.id);

    const upd = await r.update(p.id, { paid: true, status: "paid" });
    expect(upd?.paid).toBe(true);

    const list = await r.listBySession(sid);
    expect(list.some((x) => x.id === p.id && x.paid)).toBe(true);
  });
});
