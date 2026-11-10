import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type postgresT from "postgres";

import { bundleOf } from "./_trial-bundle-db";
import { sampleResult } from "./_trial-helpers";

// Окна и двери агента на плане тура на НАСТОЯЩЕЙ Postgres (план trial-room-edit-01, Е4; T-20261110-39): миграция 029 повторяется,
// одна строка на проём (новая заменяет), изменённое меньше 1 см — `unchanged` без работы, вторая панель ложится в ждущую пересборку,
// отказы (ключ, `stale`, чужой проём / вне плана, `busy`, лимит суток, больше 120 правок — откат всей транзакции), claim `edit` отдаёт
// правки проёмов, публикация помечает их построенными, перевыпуск тура их получает. Подключается внутрь `describe` trial-claim.test.ts.

type Ctx = {
  pg: ReturnType<typeof postgresT>;
  repo: typeof import("@/lib/trial/repo-worker");
  seed: () => Promise<{ id: string }>;
  dir: string;
  token: string;
};

const KEY = "F".repeat(22);
const sha = (s: string) => createHash("sha256").update(s).digest("hex");
const PIN = async (): Promise<"exists"> => "exists";
const room = (id: string, x: number, w: number) => ({ id, src_id: id, name: id, kind: "bedroom", areaM2: 12, bbox: { x, y: 0, w, d: 400 },
  contour: [], flags: [] });
/** Две панели: p0 — гостиная и спальня с окном и дверью между ними; p1 — одна спальня без проёмов. */
const planBundle = (id: string) => JSON.stringify(bundleOf(id, {
  rev: 1,
  apartment_rooms: [{ id: "living", titleRu: "Гостиная", furniture_state: "ready" }],
  trial: { job_id: id, panels: [
    { id: "p0", title: "", rooms: [room("living", 0, 500), room("bedroom-1", 510, 300)],
      openings: [{ kind: "window", c: [250, 0], widthCm: 150, exterior: true }, { kind: "door", c: [505, 200], widthCm: 80, exterior: false }] },
    { id: "p1", title: "", rooms: [room("bedroom-2", 0, 400)], openings: [] }] },
}));

export function openingEditDbTests(c: () => Ctx): void {
  describe("окна и двери в туре", () => {
    const W = () => import("@/lib/trial/repo-rebuild-worker");
    const doneJob = async () => {
      const { id } = await c().seed();
      const a = (await c().repo.claim(`w-${id}`))!;
      const f = { id, attempt: a.attempt, leaseToken: a.leaseToken };
      const { publishBundle } = await import("@/lib/trial/repo-bundle");
      await publishBundle(f, planBundle(id), sha(planBundle(id)), c().dir, PIN);
      await c().repo.acceptResult(f, JSON.stringify(sampleResult()), "r".repeat(64));
      const { editKeyHash } = await import("@/lib/trial/edit-key");
      await c().pg`update trial_jobs set edit_key_hash = ${editKeyHash(KEY)} where id = ${id}`;
      return id;
    };
    const send = async (id: string, b: Record<string, unknown>) => {
      const { POST } = await import("@/app/api/trial/[id]/opening-edit/route");
      const r = await POST(new Request(`http://app/api/trial/${id}/opening-edit`, { method: "POST", body: JSON.stringify(b) }),
        { params: Promise.resolve({ id }) });
      return { status: r.status, body: (await r.json()) as Record<string, unknown> };
    };
    const op = (over: Record<string, unknown> = {}) => ({ key: "s1", kind: "door", c: [505, 200], w_cm: 80, removed: true, ...over });
    const body = (over: Record<string, unknown> = {}) => ({ k: KEY, request_id: "open-0000001", base_version: 1, panel: "p0", ops: [op()], ...over });
    const rows = (id: string) => c().pg`select op_key, panel, src_idx, src_c, kind, c, width_cm, removed, built from trial_opening_edits
      where job_id = ${id} order by op_key`;
    const rebuilds = (id: string) => c().pg`select kind, status, base_version from trial_rebuilds where job_id = ${id} order by created_at`;
    const view = async (id: string) => (await (await import("@/lib/trial/repo-public")).jobView(id)) as Record<string, unknown>;

    it("миграция 029 повторяется; снять ложную дверь → 202, строка, пересборка `edit`, «пересобираю»; повтор request_id — без второй", async () => {
      const text = await fs.readFile(path.join(process.cwd(), "db/init/029-trial-opening-edits.sql"), "utf8");
      await c().pg.unsafe(text);
      await c().pg.unsafe(text);
      const id = await doneJob();
      expect(await send(id, body())).toMatchObject({ status: 202, body: { ok: true, repeated: false, unchanged: false, edit: { status: "queued" } } });
      expect(await rows(id)).toEqual([{ op_key: "p0|s1", panel: "p0", src_idx: 1, src_c: [505, 200], kind: "door", c: [505, 200], width_cm: 80,
        removed: true, built: false }]);
      expect(await rebuilds(id)).toEqual([{ kind: "edit", status: "queued", base_version: 1 }]);
      expect(await view(id)).toMatchObject({ roomEdit: "applying", rebuild: null });
      expect(await send(id, body())).toMatchObject({ status: 202, body: { repeated: true } });
      expect(await rebuilds(id)).toHaveLength(1);
    });

    it("ничего не изменилось (< 1 см, тот же тип) — 200 `unchanged`, без работы; новая правка того же проёма заменяет строку", async () => {
      const id = await doneJob();
      expect(await send(id, body({ ops: [op({ removed: false, c: [505.5, 200] })] }))).toMatchObject({ status: 200,
        body: { unchanged: true, edit: null } });
      expect(await rebuilds(id)).toEqual([]);
      await send(id, body({ ops: [op({ removed: false, kind: "window", w_cm: 120 })] }));
      await send(id, body({ request_id: "open-0000002", ops: [op({ removed: false, kind: "door", c: [505, 300], w_cm: 90 })] }));
      expect(await rows(id)).toMatchObject([{ op_key: "p0|s1", kind: "door", c: [505, 300], width_cm: 90, removed: false }]);
      expect(await rebuilds(id)).toHaveLength(1);                  // вторая правка поехала с ждущей пересборкой
    });

    it("две панели по очереди: новый проём второй панели ложится в ту же ждущую пересборку", async () => {
      const id = await doneJob();
      await send(id, body());
      expect(await send(id, body({ request_id: "open-0000002", panel: "p1", ops: [op({ key: "uNEWDOOR1", c: [400, 200], removed: false })] })))
        .toMatchObject({ status: 202 });
      expect((await rows(id)).map((r) => [r.op_key, r.src_idx, r.src_c])).toEqual([["p0|s1", 1, [505, 200]], ["p1|uNEWDOOR1", null, null]]);
      expect(await rebuilds(id)).toHaveLength(1);
    });

    it("отказы: чужой ключ 403, устарела 409 stale, нет проёма / вне плана / нет панели 422, идёт «Обустроить» 409 busy, лимит 429", async () => {
      const id = await doneJob();
      expect((await send(id, body({ k: "X".repeat(22) }))).status).toBe(403);
      expect(await send(id, body({ base_version: 2 }))).toMatchObject({ status: 409, body: { error: "stale", version: 1 } });
      expect(await send(id, body({ ops: [op({ key: "s5" })] }))).toMatchObject({ status: 422, body: { error: "bad_opening" } });
      expect(await send(id, body({ ops: [op({ key: "uFARAWAY1", c: [2000, 0], removed: false })] }))).toMatchObject({ status: 422,
        body: { error: "bad_opening" } });
      expect(await send(id, body({ panel: "p9" }))).toMatchObject({ status: 422, body: { error: "bad_opening" } });
      expect((await send(id, body({ ops: [op({ w_cm: 10 })] }))).status).toBe(400);
      await c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version) values ('rb-busy', ${id}, 'req-busy0001', '["*"]', 1)`;
      expect(await send(id, body())).toMatchObject({ status: 409, body: { error: "busy" } });
      await c().pg`update trial_rebuilds set status = 'done' where id = 'rb-busy'`;
      const { TRIAL_ROOM_EDIT_LIMITS } = await import("@/lib/trial/upload-limits");
      for (let i = 0; i < TRIAL_ROOM_EDIT_LIMITS.day; i++) {
        await c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version, kind, status)
          values (${`rb-e${i}`}, ${id}, ${`req-e${String(i).padStart(6, "0")}`}, '[]', 1, 'edit', 'done')`;
      }
      expect(await send(id, body())).toMatchObject({ status: 429, body: { error: "edit_limit" } });
      expect(await rows(id)).toEqual([]);
    });

    it("больше 120 правок на задание — 422 too_many, вся порция откатывается", async () => {
      const id = await doneJob();
      for (let i = 0; i < 119; i++) {
        await c().pg`insert into trial_opening_edits (job_id, op_key, panel, kind, c, width_cm, request_id)
          values (${id}, ${`p1|uFILL${String(i).padStart(4, "0")}`}, 'p1', 'door', '[100, 0]', 80, ${`fill-${String(i).padStart(6, "0")}`})`;
      }
      const two = [op({ key: "uNEWDOOR1", c: [100, 400], removed: false }), op({ key: "uNEWDOOR2", c: [300, 400], removed: false })];
      expect(await send(id, body({ ops: two }))).toMatchObject({ status: 422, body: { error: "too_many" } });
      expect(await rows(id)).toHaveLength(119);
      expect(await rebuilds(id)).toEqual([]);
    });

    it("воркер: claim `edit` отдаёт правки проёмов (ключ без панели), публикация → built, перевыпуск их получает", async () => {
      const id = await doneJob();
      await send(id, body({ ops: [op(), op({ key: "uNEWWIN01", kind: "window", c: [810, 200], w_cm: 120, removed: false })] }));
      const w = await W();
      const got = (await w.claimRebuild("w1", { listing: true, edit: true }))!;
      expect(got).toMatchObject({ kind: "edit", jobId: id, edits: [], openingEdits: expect.arrayContaining([
        { panel: "p0", key: "s1", srcIdx: 1, srcC: [505, 200], kind: "door", c: [505, 200], widthCm: 80, removed: true, built: false },
        { panel: "p0", key: "uNEWWIN01", srcIdx: null, srcC: null, kind: "window", c: [810, 200], widthCm: 120, removed: false, built: false }]) });
      const out = JSON.stringify(bundleOf(id, { tag: "edited" }));
      await w.publishRebuild({ id: got.id, attempt: got.attempt, leaseToken: got.leaseToken, jobId: id }, out, sha(out), c().dir, PIN);
      expect((await rows(id)).every((r) => r.built)).toBe(true);
      expect(await view(id)).toMatchObject({ roomEdit: "done" });
      const { reissueSource } = await import("@/lib/trial/repo-reissue");
      expect(await reissueSource(id, c().dir)).toMatchObject({ jobId: id, openingEdits: expect.arrayContaining([
        expect.objectContaining({ key: "s1", removed: true, built: true })]) });
    });
  });
}
