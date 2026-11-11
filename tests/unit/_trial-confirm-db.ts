import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type postgresT from "postgres";

import { bundleOf } from "./_trial-bundle-db";
import { sampleResult } from "./_trial-helpers";

// «Подтвердить планировку» на НАСТОЯЩЕЙ Postgres (план trial-confirm-plan-01 § «Тесты»; T-20261111-16): миграция 032 повторяется и не
// подтверждает черновики повторно; черновик не ставит пересборку, не тратит суточный лимит и не попадает в claim ни одного вида; кнопка —
// ровно одна пересборка `edit` (и пустая), повтор `request_id` — тот же ответ, конкурирующая — `busy`, устаревшая — `stale`; публикация
// помечает построенными только правки своей пересборки (черновик, пришедший во время сборки, остаётся черновиком); галочки «размеры верны»
// → `dimsOk` в claim; ход по комнатам с оценкой времени, пульс воркера, замеры на публикации; `GET edits` / `GET rebuild-status`;
// черновики проёмов; лимит черновиков. Подключается внутрь `describe` trial-claim.test.ts (тот чистит таблицы перед каждым тестом).

type Ctx = {
  pg: ReturnType<typeof postgresT>;
  repo: typeof import("@/lib/trial/repo-worker");
  seed: () => Promise<{ id: string }>;
  dir: string;
  token: string;
};

const KEY = "C".repeat(22);
const sha = (s: string) => createHash("sha256").update(s).digest("hex");
const PIN = async (): Promise<"exists"> => "exists";
const room = (id: string, src: string, x: number, kind: string) =>
  ({ id, src_id: src, name: id.toUpperCase(), kind, areaM2: 12, bbox: { x, y: 0, w: 400, d: 300 }, contour: [], flags: [] });
/** Гостиная (фото можно) и две спальни (у второй фото нельзя — масштаб не подтверждён), дверь между гостиной и спальнёй. */
const planBundle = (id: string, rev = 1) => JSON.stringify(bundleOf(id, {
  rev,
  apartment_rooms: [{ id: "living", titleRu: "Гостиная", furniture_state: "ready", photo_ok: true },
    { id: "bedroom-1", titleRu: "Спальня 1", furniture_state: "ready", photo_ok: true },
    { id: "bedroom-2", titleRu: "Спальня 2", furniture_state: "awaiting_check", photo_ok: false }],
  trial: { job_id: id, panels: [{ id: "p0", title: "", rooms: [room("living", "r1", 0, "living"), room("bedroom-1", "r2", 400, "bedroom"),
    room("bedroom-2", "r3", 800, "bedroom")],
  openings: [{ kind: "door", c: [400, 150], widthCm: 80, exterior: false }] }] },
}));

export function confirmDbTests(c: () => Ctx): void {
  describe("«Подтвердить планировку»", () => {
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
    const post = async (route: "room-edit" | "opening-edit" | "confirm", id: string, b: Record<string, unknown>) => {
      const mod = route === "room-edit" ? await import("@/app/api/trial/[id]/room-edit/route")
        : route === "opening-edit" ? await import("@/app/api/trial/[id]/opening-edit/route") : await import("@/app/api/trial/[id]/confirm/route");
      const r = await mod.POST(new Request(`http://app/api/trial/${id}/${route}`, { method: "POST", body: JSON.stringify(b) }),
        { params: Promise.resolve({ id }) });
      return { status: r.status, body: (await r.json()) as Record<string, unknown> };
    };
    const get = async (route: "edits" | "rebuild-status", id: string, k = KEY) => {
      const mod = route === "edits" ? await import("@/app/api/trial/[id]/edits/route") : await import("@/app/api/trial/[id]/rebuild-status/route");
      const r = await mod.GET(new Request(`http://app/api/trial/${id}/${route}?k=${k}`), { params: Promise.resolve({ id }) });
      return { status: r.status, body: (await r.json()) as Record<string, unknown> };
    };
    let n = 0;
    const rq = () => `req-${String(++n).padStart(8, "0")}`;
    const draft = (over: Record<string, unknown> = {}) => ({ k: KEY, request_id: rq(), base_version: 1, room: "bedroom-1", name: "Спальня 1",
      w_cm: 460, d_cm: 345, draft: true, ...over });
    const confirm = (over: Record<string, unknown> = {}) => ({ k: KEY, request_id: rq(), base_version: 1, rooms_ok: [], ...over });
    const edits = (id: string) => c().pg`select room_key, w_cm, d_cm, built, confirmed_at is not null as confirmed, draft, rebuild_id, dims_ok
      from trial_room_edits where job_id = ${id} order by room_key`;
    const rebuilds = (id: string) => c().pg`select id, kind, status from trial_rebuilds where job_id = ${id} order by created_at`;
    const lease = (g: { id: string; attempt: number; leaseToken: string }, id: string) => ({ id: g.id, attempt: g.attempt, leaseToken: g.leaseToken, jobId: id });

    it("миграция 032: прежние правки подтверждены; повтор файла черновик не подтверждает", async () => {
      const id = await doneJob();
      const file = path.join(process.cwd(), "db/init/032-trial-plan-confirm.sql");
      // как на проде до 032: колонок нет, строка правки старого пути
      await c().pg.unsafe(`alter table trial_room_edits drop column confirmed_at, drop column rebuild_id, drop column draft, drop column dims_ok;
        alter table trial_opening_edits drop column confirmed_at, drop column rebuild_id, drop column draft; alter table trial_rebuilds drop column progress;`);
      await c().pg`insert into trial_room_edits (job_id, room_key, panel, src_id, anchor, name, kind, built, request_id)
        values (${id}, 'p0|r1', 'p0', 'r1', '{"x":0.1,"y":0.5}', 'Гостиная', 'living', true, 'legacy-0001')`;
      await c().pg.unsafe(await fs.readFile(file, "utf8"));
      expect(await edits(id)).toMatchObject([{ room_key: "p0|r1", confirmed: true, dims_ok: false }]);
      expect(await post("room-edit", id, draft())).toMatchObject({ status: 200, body: { ok: true, draft: true, edit: null } });
      await c().pg.unsafe(await fs.readFile(file, "utf8"));
      expect((await edits(id))[1]).toMatchObject({ room_key: "p0|r2", confirmed: false });
    });

    it("3 черновика подряд: ни одной пересборки, лимит суток не тратится; ни один вид claim черновик не берёт", async () => {
      const id = await doneJob();
      expect(await post("room-edit", id, draft())).toMatchObject({ status: 200, body: { draft: true } });
      expect(await post("room-edit", id, draft({ room: "bedroom-2", name: "Кабинет" }))).toMatchObject({ status: 200 });
      expect(await post("room-edit", id, draft({ w_cm: 470 }))).toMatchObject({ status: 200 });   // та же комната — та же строка
      expect(await rebuilds(id)).toEqual([]);
      expect(await edits(id)).toHaveLength(2);
      const w = await W();
      for (const kind of ["furnish", "listing", "reparse", "edit"]) {
        await c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version, kind, listing_text)
          values (${`rb-${kind}`}, ${id}, ${`rq-${kind}-0001`}, '["*"]', 1, ${kind}, ${kind === "listing" ? "4 x 3" : null})`;
        const got = (await w.claimRebuild("w1", { listing: true, edit: true, reparse: true }))!;
        expect(got, kind).toMatchObject({ kind, edits: [], openingEdits: [] });
        await c().pg`update trial_rebuilds set status = 'done' where id = ${got.id}`;
      }
    });

    it("кнопка: ровно одна пересборка, черновики подтверждены под неё; повтор — тот же ответ; вторая — busy; устарела — stale", async () => {
      const id = await doneJob();
      await post("room-edit", id, draft());
      expect(await post("confirm", id, confirm({ base_version: 2 }))).toMatchObject({ status: 409, body: { error: "stale", version: 1 } });
      const b = confirm();
      const r = await post("confirm", id, b);
      expect(r).toMatchObject({ status: 202, body: { ok: true, repeated: false, rebuild: { status: "queued" }, confirmed: { rooms: 1, openings: 0 } } });
      const rid = (r.body.rebuild as { id: string }).id;
      expect(await rebuilds(id)).toEqual([{ id: rid, kind: "edit", status: "queued" }]);
      expect(await edits(id)).toMatchObject([{ room_key: "p0|r2", w_cm: 460, confirmed: true, built: false, rebuild_id: rid }]);
      expect(await post("confirm", id, b)).toMatchObject({ status: 202, body: { repeated: true, rebuild: { id: rid }, confirmed: { rooms: 1 } } });
      expect(await post("confirm", id, confirm())).toMatchObject({ status: 409, body: { error: "busy" } });
      expect(await rebuilds(id)).toHaveLength(1);
      const got = (await (await W()).claimRebuild("w1", { edit: true }))!;
      expect(got).toMatchObject({ kind: "edit", confirm: true, edits: [{ srcId: "r2", wCm: 460, built: false, dimsOk: false }] });
    });

    it("пустое подтверждение — тоже одна пересборка (пересчёт фото-права); повтор — тот же ответ", async () => {
      const id = await doneJob();
      const b = confirm();
      const r = await post("confirm", id, b);
      expect(r).toMatchObject({ status: 202, body: { confirmed: { rooms: 0, openings: 0 } } });
      expect(await post("confirm", id, b)).toMatchObject({ status: 202, body: { repeated: true, rebuild: r.body.rebuild } });
      expect(await rebuilds(id)).toHaveLength(1);
      expect((await get("rebuild-status", id)).body).toMatchObject({ rebuild: { status: "queued", total: 0, done: 0, etaS: expect.any(Number) } });
    });

    it("публикация не теряет правку, пришедшую во время пересборки: она остаётся черновиком, свои — built", async () => {
      const id = await doneJob();
      await post("room-edit", id, draft());
      await post("confirm", id, confirm());
      const w = await W();
      const g = (await w.claimRebuild("w1", { edit: true }))!;
      // во время сборки: черновик той же комнаты (у подтверждённой строки — в `draft`) и новой комнаты
      expect(await post("room-edit", id, draft({ w_cm: 500 }))).toMatchObject({ status: 200, body: { draft: true } });
      expect(await post("room-edit", id, draft({ room: "living", name: "Зал" }))).toMatchObject({ status: 200 });
      const out = JSON.stringify(bundleOf(id, { tag: "built" }));
      expect(await w.publishRebuild(lease(g, id), out, sha(out), c().dir, PIN)).toMatchObject({ repeated: false });
      const e = await edits(id);
      expect(e.find((x) => x.room_key === "p0|r2")).toMatchObject({ w_cm: 460, built: true, confirmed: true, draft: { w_cm: 500 } });
      expect(e.find((x) => x.room_key === "p0|r1")).toMatchObject({ built: false, confirmed: false });
      expect((await w.editsOf(id)).map((x) => [x.srcId, x.wCm, x.built])).toEqual([["r2", 460, true]]);
    });

    it("старая страница (без `draft`): как раньше — сразу пересборка; правка подтверждена под неё, публикация → built", async () => {
      const id = await doneJob();
      const r = await post("room-edit", id, { ...draft(), draft: undefined });
      expect(r).toMatchObject({ status: 202, body: { edit: { status: "queued" } } });
      expect(await edits(id)).toMatchObject([{ confirmed: true, rebuild_id: (r.body.edit as { id: string }).id, built: false }]);
      const w = await W();
      const g = (await w.claimRebuild("w1", { edit: true }))!;
      expect(g.confirm).toBeUndefined();
      const out = JSON.stringify(bundleOf(id, { tag: "legacy" }));
      await w.publishRebuild(lease(g, id), out, sha(out), c().dir, PIN);
      expect(await edits(id)).toMatchObject([{ built: true }]);
    });

    it("галочки «размеры верны»: новая строка без правки; у комнаты без права на фото — правка пересборки, у прочих — без пересчёта", async () => {
      const id = await doneJob();
      expect(await post("confirm", id, confirm({ rooms_ok: ["kitchen-9"] }))).toMatchObject({ status: 422, body: { error: "bad_rooms" } });
      const r = await post("confirm", id, confirm({ rooms_ok: ["bedroom-1", "bedroom-2"] }));
      const rid = (r.body.rebuild as { id: string }).id;
      expect(await edits(id)).toMatchObject([
        { room_key: "p0|r2", w_cm: null, dims_ok: true, built: true, confirmed: true },
        { room_key: "p0|r3", w_cm: null, dims_ok: true, built: false, rebuild_id: rid }]);
      expect((await get("rebuild-status", id)).body).toMatchObject({ rebuild: { rooms: { "bedroom-2": "queued" }, total: 1 } });
      const got = (await (await W()).claimRebuild("w1", { edit: true }))!;
      expect(got.edits?.map((e) => [e.srcId, e.dimsOk, e.built])).toEqual([["r2", true, true], ["r3", true, false]]);
      expect((await get("edits", id)).body).toMatchObject({ roomsOk: ["bedroom-1", "bedroom-2"], drafts: 0 });
    });

    it("ход: оценка времени по замерам прошлых пересборок, пульс воркера — комнаты и «N из M», публикация — все готовы + замеры", async () => {
      const id = await doneJob();
      await c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version, kind, status, finished_at, progress)
        values ('rb-past', ${id}, 'past-00000001', '[]', 1, 'edit', 'done', now(),
          '{"timings": {"v1_s": 10, "living_s": 0, "bedrooms_s": 50, "publish_s": 90}}')`;
      await post("room-edit", id, draft());
      await post("confirm", id, confirm());
      const s0 = (await get("rebuild-status", id)).body.rebuild as Record<string, unknown>;
      // спальня: стены 10 + спальни 50 = 60; всего: 10 + 50 + хвост (90 − 10 − 0 − 50 = 30) = 90 (гостиная не правлена)
      expect(s0).toMatchObject({ status: "queued", rooms: { "bedroom-1": "queued" }, done: 0, total: 1, etaS: 90, roomEtaS: { "bedroom-1": 60 } });
      expect(s0.elapsedS).toEqual(expect.any(Number));
      const w = await W();
      const g = (await w.claimRebuild("w1", { edit: true }))!;
      const { POST: hb } = await import("@/app/api/trial/worker/rebuild/heartbeat/route");
      const beat = await hb(new Request("http://app/x", { method: "POST", headers: { authorization: `Bearer ${c().token}` },
        body: JSON.stringify({ id: g.id, attempt: g.attempt, leaseToken: g.leaseToken, progress: { rooms: { "bedroom-1": "building" }, done: 0, total: 1 } }) }));
      expect(beat.status).toBe(200);
      expect((await get("rebuild-status", id)).body.rebuild).toMatchObject({ status: "running", rooms: { "bedroom-1": "building" }, etaS: 90 });
      const out = planBundle(id, 2);                                 // новая версия — с тем же планом (дальше правим ту же комнату)
      await w.publishRebuild({ ...lease(g, id), timings: { v1_s: 12, bedrooms_s: 40, publish_s: 80 } }, out, sha(out), c().dir, PIN);
      expect((await get("rebuild-status", id)).body.rebuild).toMatchObject({ status: "done", rooms: { "bedroom-1": "ready" }, done: 1, total: 1 });
      // следующая оценка — по свежему замеру этого тура: 12 + 40 + (80 − 12 − 40 = 28) = 80
      const ver = (await get("edits", id)).body.version as number;
      expect(await post("room-edit", id, draft({ base_version: ver, w_cm: 500 }))).toMatchObject({ status: 200 });
      expect(await post("confirm", id, confirm({ base_version: ver }))).toMatchObject({ status: 202 });
      expect((await get("rebuild-status", id)).body.rebuild).toMatchObject({ status: "queued", etaS: 80, roomEtaS: { "bedroom-1": 52 } });
    });

    it("GET edits: черновики поверх плана (новая комната и изменение подтверждённой), чужой ключ — 403; GET rebuild-status без пересборок", async () => {
      const id = await doneJob();
      expect((await get("rebuild-status", id)).body).toEqual({ ok: true, version: 1, rebuild: null });
      await post("room-edit", id, draft());
      await post("opening-edit", id, { k: KEY, request_id: rq(), base_version: 1, panel: "p0", draft: true,
        ops: [{ key: "s0", kind: "door", c: [400, 150], w_cm: 80, removed: true }] });
      const v = (await get("edits", id)).body;
      expect(v).toMatchObject({ ok: true, version: 1, drafts: 2, confirmedAt: null,
        rooms: [{ room: "bedroom-1", srcId: "r2", w_cm: 460, d_cm: 345 }], openings: [{ panel: "p0", key: "s0", removed: true }] });
      expect((await get("edits", id, "X".repeat(22))).status).toBe(403);
      expect((await get("edits", id, "bad")).status).toBe(403);
    });

    it("черновик проёма: без пересборки; вернули как было — черновик снят; новый свой проём, снятый до подтверждения, — строки нет", async () => {
      const id = await doneJob();
      const ops = (o: Record<string, unknown>[]) => ({ k: KEY, request_id: rq(), base_version: 1, panel: "p0", draft: true, ops: o });
      expect(await post("opening-edit", id, ops([{ key: "s0", kind: "door", c: [400, 150], w_cm: 120, removed: false }])))
        .toMatchObject({ status: 200, body: { draft: true } });
      expect(await post("opening-edit", id, ops([{ key: "uNEWWIN01", kind: "window", c: [100, 0], w_cm: 120, removed: false }])))
        .toMatchObject({ status: 200 });
      expect(await rebuilds(id)).toEqual([]);
      expect(await post("opening-edit", id, ops([{ key: "s0", kind: "door", c: [400, 150], w_cm: 80, removed: false },
        { key: "uNEWWIN01", kind: "window", c: [100, 0], w_cm: 120, removed: true }]))).toMatchObject({ status: 200, body: { unchanged: true } });
      expect(await c().pg`select op_key from trial_opening_edits where job_id = ${id}`).toEqual([]);
    });

    it("лимит черновиков: сверх — 429 draft_limit, порция откатывается; кнопка подтверждает все", async () => {
      const id = await doneJob();
      const { TRIAL_ROOM_EDIT_LIMITS } = await import("@/lib/trial/upload-limits");
      for (let i = 0; i < TRIAL_ROOM_EDIT_LIMITS.drafts; i++) {
        await c().pg`insert into trial_opening_edits (job_id, op_key, panel, kind, c, width_cm, request_id)
          values (${id}, ${`p0|uFILL${String(i).padStart(4, "0")}`}, 'p0', 'door', '[100, 0]', 80, ${`fill-${String(i).padStart(6, "0")}`})`;
      }
      expect(await post("room-edit", id, draft())).toMatchObject({ status: 429, body: { error: "draft_limit" } });
      expect(await edits(id)).toEqual([]);
      expect(await post("confirm", id, confirm())).toMatchObject({ status: 202, body: { confirmed: { rooms: 0, openings: TRIAL_ROOM_EDIT_LIMITS.drafts } } });
    });
  });
}
