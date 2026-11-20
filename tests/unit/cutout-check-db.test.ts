import { beforeAll, describe, expect, it } from "vitest";
import { sql, type SQL } from "drizzle-orm";

// Транзакции /lab/cutout-check на НАСТОЯЩЕМ Postgres (T-20261119-104). В обычном прогоне пропускается: у тестов проекта нет БД.
// Запуск: поднять пустой pg, применить `db/init/039-cutout-check.sql`, затем
//   CUTOUT_CHECK_PG_URL=postgres://… pnpm vitest run tests/unit/cutout-check-db.test.ts
const url = process.env.CUTOUT_CHECK_PG_URL;

describe.skipIf(!url)("cutout-check: журнал и состояние в Postgres", () => {
  let m: typeof import("@/lib/cutout-check/repo-marks");
  let it_: typeof import("@/lib/cutout-check/repo-items");
  let ex: typeof import("@/lib/cutout-check/repo-export");
  let d: ReturnType<typeof import("@/lib/db").db>;
  let id = 0;
  const run = `t104-${Date.now()}`;
  const one = async <T,>(q: SQL): Promise<T> => ((await d.execute(q)) as unknown as T[])[0]!;
  const press = (p: "ok" | "bad", expected: "ok" | "bad" | null, k: string, gk = "g1") =>
    m.pressMark({ itemId: id, generationKey: gk, press: p, expected, reviewer: "Аня", idemKey: `${k}-${Date.now()}-${Math.random()}` });
  const card = (gk: string) => ({ sku: "1:a", generationKey: gk, position: 0, role: "диван", name: "Диван" });

  beforeAll(async () => {
    process.env.DATABASE_URL = url;
    d = (await import("@/lib/db")).db();
    m = await import("@/lib/cutout-check/repo-marks");
    it_ = await import("@/lib/cutout-check/repo-items");
    ex = await import("@/lib/cutout-check/repo-export");
    await it_.upsertItems(run, [card("g1"), { sku: "1:b", generationKey: "h1", position: 1, role: "комод" }]);
    id = (await one<{ id: number }>(sql`select id from cutout_check_items where run = ${run} and sku = '1:a'`)).id;
  });

  it("«не ок» ставит отметку с именем, повтор снимает; тот же idem_key — одна строка журнала", async () => {
    expect((await press("bad", null, "a")).body).toMatchObject({ item: { mark: "bad", markBy: "Аня" } });
    expect((await press("bad", "bad", "b")).body).toMatchObject({ item: { mark: null } });
    const k = { itemId: id, generationKey: "g1", press: "bad" as const, expected: null, reviewer: "Аня", idemKey: `dup-${Date.now()}` };
    await m.pressMark(k);
    expect((await m.pressMark({ ...k, expected: "bad" })).body).toMatchObject({ duplicate: true });
    expect(await one(sql`select count(*)::int as c from cutout_check_marks where op_id = ${k.idemKey}`)).toEqual({ c: 1 });
  });

  it("другая вкладка успела раньше — 409 и строка журнала applied=false", async () => {
    const r = await press("bad", null, "c"); // в карточке уже «не ок» от прошлого теста, вкладка видела null
    expect(r.http).toBe(409);
    expect(await one(sql`select count(*)::int as c from cutout_check_marks where item_id = ${id} and applied = false and reason = 'state_conflict'`)).toEqual({ c: 1 });
  });

  it("текст: новая версия применяется, старая и повтор op_id — только журнал", async () => {
    const base = { itemId: id, generationKey: "g1", editorId: "ed-1", reviewer: "Аня" };
    expect((await m.saveNote({ ...base, body: "дыра у ножки", seq: 10, opId: `n1-${run}` })).body).toMatchObject({ applied: true });
    expect((await m.saveNote({ ...base, body: "старое", seq: 5, opId: `n2-${run}` })).body).toMatchObject({ applied: false, reason: "older" });
    expect((await m.saveNote({ ...base, body: "дыра у ножки", seq: 10, opId: `n1-${run}` })).body).toMatchObject({ duplicate: true });
    expect(await one(sql`select note from cutout_check_items where id = ${id}`)).toEqual({ note: "дыра у ножки" });
    expect(await one(sql`select count(*)::int as c from cutout_check_marks where item_id = ${id} and kind = 'note'`)).toEqual({ c: 2 });
  });

  it("выгрузка отдаёт «не ок» с текстом и счётчиками; новая вырезка сбрасывает отметку и текст, журнал остаётся", async () => {
    await press("ok", "bad", "d0"); // «вернуть в ок» снимает отметку
    await press("bad", null, "d");
    const e = await ex.exportMarks(run);
    expect(e).toMatchObject({ run, total: 2, bad: 1, ok: 0 });
    expect(e?.marks[0]).toMatchObject({ sku: "1:a", mark: "bad", note: "дыра у ножки", by: "Аня" });
    const before = await one<{ c: number }>(sql`select count(*)::int as c from cutout_check_marks where item_id = ${id}`);
    await it_.upsertItems(run, [card("g2")]);
    expect(await one(sql`select mark, note, generation_key as gk from cutout_check_items where id = ${id}`)).toEqual({ mark: null, note: null, gk: "g2" });
    expect(await one(sql`select count(*)::int as c from cutout_check_marks where item_id = ${id}`)).toEqual(before);
    expect((await press("bad", null, "e", "g1")).http).toBe(409); // вкладка со старой вырезкой — stale
    // повторная заливка той же вырезки отметку не трогает
    await press("bad", null, "f", "g2");
    await it_.upsertItems(run, [card("g2")]);
    expect(await one(sql`select mark from cutout_check_items where id = ${id}`)).toEqual({ mark: "bad" });
  });

  it("счётчики по ролям и страница с фильтром", async () => {
    const { roles, all } = await it_.roleCounts(run);
    expect(all).toMatchObject({ total: 2, checked: 1 });
    expect(roles.map((r) => r.role).sort()).toEqual(["диван", "комод"]);
    expect((await it_.listPage(run, "комод", "todo", 1)).total).toBe(1);
    expect((await it_.listPage(run, null, "bad", 1)).total).toBe(1);
    expect((await it_.listPage(run, "диван", "todo", 1)).total).toBe(0); // диван с «не ок» — уже просмотрен
    expect(await it_.currentRun()).toBe(run);
  });

  it("«просмотрено»: первый показ пишет viewed_at и строку журнала, повтор и чужая вырезка — нет; новая вырезка сбрасывает", async () => {
    const v = (gk: string, op: string) => m.recordView({ itemId: id, generationKey: gk, opId: `${op}-${run}`, reviewer: "Аня" });
    expect((await v("g2", "v1")).body).toMatchObject({ recorded: true });
    expect((await v("g2", "v2")).body).toMatchObject({ recorded: false, reason: "already" });
    expect((await v("g2", "v1")).body).toMatchObject({ recorded: false, reason: "duplicate" });
    expect((await v("g1", "v3")).body).toMatchObject({ recorded: false, reason: "stale" });
    expect(await one(sql`select count(*)::int as c from cutout_check_marks where item_id = ${id} and kind = 'view'`)).toEqual({ c: 1 });
    await it_.upsertItems(run, [card("g3")]);
    expect(await one(sql`select viewed_at from cutout_check_items where id = ${id}`)).toEqual({ viewed_at: null });
  });
});
