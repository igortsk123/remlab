import { beforeAll, describe, expect, it } from "vitest";
import { sql, type SQL } from "drizzle-orm";

// Транзакции /lab/mesh-check на НАСТОЯЩЕМ Postgres (T-20261112-118, Codex 12.11 просил integration). В обычном прогоне пропускается:
// у тестов проекта нет БД. Запуск: поднять пустой pg, применить `tools/apply-db-init.sh`, затем
//   MESH_CHECK_PG_URL=postgres://… pnpm vitest run tests/unit/mesh-check-db.test.ts
const url = process.env.MESH_CHECK_PG_URL;

describe.skipIf(!url)("mesh-check: журнал и состояние в Postgres", () => {
  let m: typeof import("@/lib/mesh-audit/repo-marks");
  let n: typeof import("@/lib/mesh-audit/repo-notes");
  let items: typeof import("@/lib/mesh-audit/repo-items");
  let d: ReturnType<typeof import("@/lib/db").db>;
  let id = 0;
  const one = async <T,>(q: SQL): Promise<T> => ((await d.execute(q)) as unknown as T[])[0]!;
  const press = (p: "ok" | "bad", expected: "ok" | "bad" | null, k: string, gk = "g1") =>
    m.pressMark({ itemId: id, generationKey: gk, press: p, expected, reviewer: "Аня", idemKey: `${k}-${Date.now()}` });

  beforeAll(async () => {
    process.env.DATABASE_URL = url;
    d = (await import("@/lib/db")).db();
    m = await import("@/lib/mesh-audit/repo-marks");
    n = await import("@/lib/mesh-audit/repo-notes");
    items = await import("@/lib/mesh-audit/repo-items");
    const sku = `t118:${Date.now()}`;
    await items.upsertItems([{ sku, generationKey: "g1", role: "диван", modelPath: "x/model.glb" }]);
    id = (await one<{ id: number }>(sql`select id from mesh_audit_items where sku = ${sku}`)).id;
  });

  it("«ок», повтор снимает; тот же idem_key — одна строка журнала", async () => {
    expect((await press("ok", null, "a")).body).toMatchObject({ item: { mark: "ok", markBy: "Аня" } });
    expect((await press("ok", "ok", "b")).body).toMatchObject({ item: { mark: null } });
    const k = { itemId: id, generationKey: "g1", press: "ok" as const, expected: null, reviewer: "Аня", idemKey: `dup-${Date.now()}` };
    await m.pressMark(k);
    expect((await m.pressMark({ ...k, expected: "ok" })).body).toMatchObject({ duplicate: true });
    expect(await one(sql`select count(*)::int as c from mesh_audit_marks where idem_key = ${k.idemKey}`)).toEqual({ c: 1 });
  });

  it("комментарий: новая версия применяется, старая и повтор op_id — только журнал", async () => {
    const base = { itemId: id, generationKey: "g1", editorId: "ed-1", reviewer: "Аня" };
    expect((await n.saveNote({ ...base, body: " ножки пропали ", seq: 2000, opId: `o1-${id}` })).body).toMatchObject({ applied: true });
    expect((await n.saveNote({ ...base, body: "старое", seq: 1999, opId: `o0-${id}` })).body).toMatchObject({ applied: false, reason: "older" });
    expect((await n.saveNote({ ...base, body: " ножки пропали ", seq: 2000, opId: `o1-${id}` })).body).toMatchObject({ duplicate: true });
    expect(await one(sql`select note, note_seq::int as s from mesh_audit_items where id = ${id}`)).toEqual({ note: " ножки пропали ", s: 2000 });
  });

  it("«брак» — решение с именем и текстом; повтор — отмена решения, строка отмены остаётся", async () => {
    const r = await press("bad", "ok", "c");
    expect(r.http).toBe(200);
    expect(r.body).toMatchObject({ item: { mark: "bad", status: "redo_requested", manualAttempts: 1 } });
    expect(await one(sql`select reviewer, comment from mesh_audit_decisions where item_id = ${id}`)).toEqual({ reviewer: "Аня", comment: "ножки пропали" });
    expect((await press("bad", "bad", "d")).body).toMatchObject({ item: { mark: null, status: "open", manualAttempts: 0 } });
    expect(await one(sql`select count(*)::int as c from mesh_audit_cancellations where item_id = ${id}`)).toEqual({ c: 1 });
  });

  it("переделка уже в волне: снятие «брака» снимает отметку, очередь не трогает", async () => {
    await press("bad", null, "e");
    await d.execute(sql`update mesh_audit_items set status = 'redo_queued' where id = ${id}`);
    const r = await press("bad", "bad", "f");
    expect(r.body).toMatchObject({ reason: "queued_kept", item: { mark: null, status: "redo_queued" } });
  });

  it("старая вкладка и чужая вкладка — 409, но нажатие в журнале (applied=false)", async () => {
    expect((await press("ok", null, "g", "g0")).body).toMatchObject({ code: "stale" });
    expect((await press("ok", "ok", "h")).body).toMatchObject({ code: "state_conflict" });
    expect(await one(sql`select count(*)::int as c from mesh_audit_marks where item_id = ${id} and not applied`)).toEqual({ c: 2 });
  });

  it("новое поколение — карточка снова «не проверена», журналы и карточка с отметками не снимаются", async () => {
    await press("ok", null, "i");
    const { sku } = await one<{ sku: string }>(sql`select sku from mesh_audit_items where id = ${id}`);
    await items.upsertItems([{ sku, generationKey: "g2", role: "диван", modelPath: "x/model.glb" }]);
    expect(await one(sql`select mark, note, note_seq from mesh_audit_items where id = ${id}`)).toEqual({ mark: null, note: null, note_seq: null });
    expect(await items.retireItems([sku])).toBe(0);
  });
});
