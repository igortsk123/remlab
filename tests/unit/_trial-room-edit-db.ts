import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type postgresT from "postgres";

import { bundleOf } from "./_trial-bundle-db";
import { sampleResult } from "./_trial-helpers";

// Правка комнаты в туре на НАСТОЯЩЕЙ Postgres (план trial-room-edit-01, Е3; T-20261110-36): ключ правки, порог 10 см от последней
// построенной геометрии, «ничего не изменилось» без работы, одна правка на комнату (новая заменяет), ждущая пересборка правки забирает
// новые правки, другая активная — `busy`, устаревшая страница — `stale`, свой суточный лимит, воркер без `edit` таких строк не получает,
// claim отдаёт правки, публикация помечает их построенными, статус страницы — `edit: applying/done`. Подключается внутрь `describe`
// файла trial-claim.test.ts (тот чистит таблицы перед каждым тестом).

type Ctx = {
  pg: ReturnType<typeof postgresT>;
  repo: typeof import("@/lib/trial/repo-worker");
  seed: () => Promise<{ id: string }>;
  dir: string;
  token: string;
};

const KEY = "E".repeat(22);
const sha = (s: string) => createHash("sha256").update(s).digest("hex");
const PIN = async (): Promise<"exists"> => "exists";
const room = (id: string, src: string, x: number, name: string, kind: string, extra: Record<string, unknown> = {}) =>
  ({ id, src_id: src, name, kind, areaM2: 12, bbox: { x, y: 0, w: 400, d: 300 }, contour: [], flags: [], ...extra });
/** Версия данных с планом: гостиная 400×300 и спальня (вторая — с прошлой правкой 420×300, если `edited`). */
const planBundle = (id: string, rev: number, edited = false) => JSON.stringify(bundleOf(id, {
  rev,
  apartment_rooms: [{ id: "living", titleRu: "Гостиная", furniture_state: "ready" }, { id: "bedroom-1", titleRu: "Спальня 1", furniture_state: "ready" }],
  trial: { job_id: id, panels: [{ id: "p0", title: "", rooms: [room("living", "r1", 0, "LIVING ROOM", "living"),
    room("bedroom-1", "r2", 400, edited ? "Спальня 1" : "BEDROOM 1", "bedroom", edited ? { edited: { w: 420, d: 300 } } : {})] }] },
}));

export function roomEditDbTests(c: () => Ctx): void {
  describe("правка комнаты в туре", () => {
    const W = () => import("@/lib/trial/repo-rebuild-worker");
    const doneJob = async () => {
      const { id } = await c().seed();
      const a = (await c().repo.claim(`w-${id}`))!;
      const f = { id, attempt: a.attempt, leaseToken: a.leaseToken };
      const { publishBundle } = await import("@/lib/trial/repo-bundle");
      await publishBundle(f, planBundle(id, 1), sha(planBundle(id, 1)), c().dir, PIN);
      await c().repo.acceptResult(f, JSON.stringify(sampleResult()), "r".repeat(64));
      const { editKeyHash } = await import("@/lib/trial/edit-key");
      await c().pg`update trial_jobs set edit_key_hash = ${editKeyHash(KEY)} where id = ${id}`;
      return id;
    };
    const send = async (id: string, b: Record<string, unknown>) => {
      const { POST } = await import("@/app/api/trial/[id]/room-edit/route");
      const r = await POST(new Request(`http://app/api/trial/${id}/room-edit`, { method: "POST", body: JSON.stringify(b) }),
        { params: Promise.resolve({ id }) });
      return { status: r.status, body: (await r.json()) as Record<string, unknown> };
    };
    const body = (over: Record<string, unknown> = {}) => ({ k: KEY, request_id: "edit-0000001", base_version: 1, room: "bedroom-1",
      name: "Спальня 1", w_cm: 400, d_cm: 300, ...over });
    const edits = (id: string) => c().pg`select room_key, name, kind, w_cm, d_cm, built, anchor from trial_room_edits where job_id = ${id}`;
    const rebuilds = (id: string) => c().pg`select kind, status, base_version from trial_rebuilds where job_id = ${id} order by created_at`;
    const view = async (id: string) => (await (await import("@/lib/trial/repo-public")).jobView(id)) as Record<string, unknown>;

    it("миграция 028 повторяется; правка площади → 202, правка в таблице, пересборка `edit`, статус «пересобираю»", async () => {
      const text = await fs.readFile(path.join(process.cwd(), "db/init/028-trial-room-edits.sql"), "utf8");
      await c().pg.unsafe(text);
      await c().pg.unsafe(text);
      const id = await doneJob();
      const r = await send(id, body({ w_cm: 460, d_cm: 345 }));
      expect(r).toMatchObject({ status: 202, body: { ok: true, repeated: false, unchanged: false, edit: { status: "queued" } } });
      expect(await edits(id)).toEqual([{ room_key: "p0|r2", name: "BEDROOM 1", kind: "bedroom", w_cm: 460, d_cm: 345, built: false,
        anchor: { x: 0.75, y: 0.5 } }]);
      expect(await rebuilds(id)).toEqual([{ kind: "edit", status: "queued", base_version: 1 }]);
      expect(await view(id)).toMatchObject({ roomEdit: "applying", roomEditError: null, rebuild: null, listing: null });
      expect(await send(id, body({ w_cm: 460, d_cm: 345 }))).toMatchObject({ status: 202, body: { repeated: true } });
    });

    it("порог 10 см: < 10 по обеим осям и то же имя — 200 `unchanged`, без работы; одна ось ≥ 10 — меняется только она", async () => {
      const id = await doneJob();
      expect(await send(id, body({ w_cm: 409, d_cm: 291 }))).toMatchObject({ status: 200, body: { unchanged: true, edit: null } });
      expect(await rebuilds(id)).toEqual([]);
      expect(await send(id, body({ request_id: "edit-0000002", w_cm: 409, d_cm: 320 }))).toMatchObject({ status: 202 });
      expect((await edits(id))[0]).toMatchObject({ w_cm: 400, d_cm: 320 });
    });

    it("имя: новое — вид по имени («Кабинет» → other, «Гостиная» → living); подпись страницы = имя не меняли", async () => {
      const id = await doneJob();
      await send(id, body({ name: "Кабинет" }));
      expect((await edits(id))[0]).toMatchObject({ name: "Кабинет", kind: "other", w_cm: null, d_cm: null });
      await send(id, body({ request_id: "edit-0000002", name: "Гостиная" }));
      expect((await edits(id))[0]).toMatchObject({ name: "Гостиная", kind: "living" });
      expect(await edits(id)).toHaveLength(1);                       // одна правка на комнату: новая заменила
      expect(await rebuilds(id)).toEqual([{ kind: "edit", status: "queued", base_version: 1 }]);   // поехала с ждущей
    });

    it("порог — от ПОСЛЕДНЕЙ построенной геометрии (прошлая правка), не от прочитанной", async () => {
      const { id } = await c().seed();
      const a = (await c().repo.claim(`w-${id}`))!;
      const f = { id, attempt: a.attempt, leaseToken: a.leaseToken };
      const { publishBundle } = await import("@/lib/trial/repo-bundle");
      await publishBundle(f, planBundle(id, 1, true), sha(planBundle(id, 1, true)), c().dir, PIN);
      await c().repo.acceptResult(f, JSON.stringify(sampleResult()), "r".repeat(64));
      const { editKeyHash } = await import("@/lib/trial/edit-key");
      await c().pg`update trial_jobs set edit_key_hash = ${editKeyHash(KEY)} where id = ${id}`;
      expect(await send(id, body({ w_cm: 425, d_cm: 300 }))).toMatchObject({ status: 200, body: { unchanged: true } });
      expect(await send(id, body({ request_id: "edit-0000002", w_cm: 400, d_cm: 300 }))).toMatchObject({ status: 202 });
      expect((await edits(id))[0]).toMatchObject({ w_cm: null, d_cm: null });   // вернули к прочитанному — правки размера нет
    });

    it("отказы: чужой ключ 403, устарела 409 stale (+версия), нет комнаты 422, идёт «Обустроить» 409 busy, лимит 429", async () => {
      const id = await doneJob();
      expect((await send(id, body({ k: "X".repeat(22) }))).status).toBe(403);
      expect(await send(id, body({ base_version: 2 }))).toMatchObject({ status: 409, body: { error: "stale", version: 1 } });
      expect(await send(id, body({ room: "kitchen-9" }))).toMatchObject({ status: 422, body: { error: "bad_room" } });
      expect((await send(id, body({ w_cm: 10 }))).status).toBe(400);
      await c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version) values ('rb-busy', ${id}, 'req-busy0001', '["*"]', 1)`;
      expect(await send(id, body({ w_cm: 500 }))).toMatchObject({ status: 409, body: { error: "busy" } });
      await c().pg`update trial_rebuilds set status = 'done' where id = 'rb-busy'`;
      const { TRIAL_ROOM_EDIT_LIMITS } = await import("@/lib/trial/upload-limits");
      for (let i = 0; i < TRIAL_ROOM_EDIT_LIMITS.day; i++) {
        await c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version, kind, status)
          values (${`rb-e${i}`}, ${id}, ${`req-e${String(i).padStart(6, "0")}`}, '[]', 1, 'edit', 'done')`;
      }
      expect(await send(id, body({ w_cm: 500 }))).toMatchObject({ status: 429, body: { error: "edit_limit" } });
      expect(await edits(id)).toEqual([]);
    });

    it("воркер: без `edit` строк не получает; с `edit` — правки в claim (и у «Обустроить»), публикация → built, статус done", async () => {
      const id = await doneJob();
      await send(id, body({ w_cm: 460, d_cm: 345 }));
      const w = await W();
      expect(await w.claimRebuild("w1", true)).toBeNull();
      const got = (await w.claimRebuild("w1", { listing: true, edit: true }))!;
      expect(got).toMatchObject({ kind: "edit", jobId: id, baseVersion: 1,
        edits: [{ panel: "p0", srcId: "r2", anchor: { x: 0.75, y: 0.5 }, name: "BEDROOM 1", kind: "bedroom", wCm: 460, dCm: 345, built: false }] });
      const out = JSON.stringify(bundleOf(id, { tag: "edited" }));
      const pub = await w.publishRebuild({ id: got.id, attempt: got.attempt, leaseToken: got.leaseToken, jobId: id }, out, sha(out), c().dir, PIN);
      expect(pub).toMatchObject({ repeated: false });
      expect((await edits(id))[0]).toMatchObject({ built: true });
      expect(await view(id)).toMatchObject({ roomEdit: "done", bundleVersion: (pub as { version: number }).version });
    });
  });
}
