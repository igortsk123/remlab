import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type postgresT from "postgres";

import { bundleOf } from "./_trial-bundle-db";
import { sampleResult } from "./_trial-helpers";

// Автофото тура на НАСТОЯЩЕЙ Postgres (T-20261112-115 Ф2, план tour-auto-photos-01; `db/init/036-trial-auto-photos.sql`): публикация
// подтверждённой пересборки той же транзакцией ставит партию с версией и задачи по комнатам (гостиная, спальни по площади, активный стиль,
// C1/C2); повтор подтверждения без правок — 0 новых задач, с правкой одной комнаты — только она; не подтверждение — ничего; потолки тура и
// суток, предупреждение; аренда партии исполнителем, заказ класса `auto` только по своей задаче (квота людей не тронута, второй заказ той же
// задачи — отказ, отказ сервиса кадров — резерв вернулся), готовое фото закрывает задачу; сменилась версия — партия не снимается.
// Сервис кадров подменён (`send`): платных вызовов нет. Подключается внутрь `describe` trial-claim.test.ts (тот чистит таблицы перед тестом).

type Ctx = {
  pg: ReturnType<typeof postgresT>;
  repo: typeof import("@/lib/trial/repo-worker");
  seed: () => Promise<{ id: string }>;
  dir: string;
  token: string;
};

const KEY = "D".repeat(22);
const sha = (s: string) => createHash("sha256").update(s).digest("hex");
const PIN = async (): Promise<"exists"> => "exists";
const cams = (x: number) => [{ name: "C1", x, y: 20, rot: 136, fov: 90, pose: 3, pshift: 0.005 }, { name: "C2", x: x + 100, y: 200, rot: -40, fov: 84, pose: 3 }];
const item = (role: string, x: number) => ({ role, x, y: 50, rot: 0, w: 200, d: 90, h: 80, sku: { msid: `1_${role}`, sid: `1_${role}` } });
const variant = (room: string, style: string, over: Record<string, unknown> = {}) => ({ id: `${room}-${style}`, room_id: room, style,
  style_id: style, title: style, items: [item("диван", 100), item("стол", 300)], decor: [], cams: cams(10), room_size: { w: 400, d: 300 }, ...over });
const geo = { w: 400, d: 300, title: "Комната", openings: [], radiators: [] };
const pRoom = (id: string, kind: string, areaM2: number, x: number) => ({ id, src_id: `s-${id}`, name: id, kind, areaM2,
  bbox: { x, y: 0, w: 400, d: 300 }, contour: [], flags: [] });
const ROOMS = [["kitchen-1", "kitchen", 9], ["bedroom-1", "bedroom", 12], ["living", "living", 20], ["bedroom-2", "bedroom", 15],
  ["bedroom-3", "bedroom", 14], ["bedroom-4", "bedroom", 10], ["bedroom-5", "bedroom", 8]] as const;
/** Тур после подтверждения: гостиная, пять спален (у 3-й нет права на фото, у 4-й — ракурсов, у 5-й — мебели), кухня; стили scandi/modern. */
const tourBundle = (id: string, over: Record<string, unknown> = {}, bed1: Record<string, unknown> = {}) => JSON.stringify(bundleOf(id, {
  rooms_geo: Object.fromEntries(ROOMS.map(([r]) => [r, geo])),
  apartment_rooms: ROOMS.map(([r, kind]) => ({ id: r, kind, furniture_state: kind === "kitchen" ? "not_furnished" : "ready",
    photo_ok: kind !== "kitchen" && r !== "bedroom-3" })),
  variants: ["scandi", "modern"].flatMap((s) => ROOMS.filter(([, k]) => k !== "kitchen").map(([r]) => variant(r, s,
    r === "bedroom-4" ? { cams: [] } : r === "bedroom-5" ? { items: [] } : r === "bedroom-1" && s === "scandi" ? bed1 : {}))),
  trial: { job_id: id, panels: [{ id: "p0", title: "", rooms: ROOMS.map(([r, k, a], i) => pRoom(r, k, a, i * 400)), openings: [] }] },
  ...over,
}));

export function autoPhotoDbTests(c: () => Ctx): void {
  describe("автофото тура после подтверждения", () => {
    const W = () => import("@/lib/trial/repo-rebuild-worker");
    const A = () => import("@/lib/trial/auto-photos-lease");
    const doneJob = async () => {
      const { id } = await c().seed();
      const a = (await c().repo.claim(`w-${id}`))!;
      const f = { id, attempt: a.attempt, leaseToken: a.leaseToken };
      const { publishBundle } = await import("@/lib/trial/repo-bundle");
      const json = tourBundle(id, { rev: 0 });
      await publishBundle(f, json, sha(json), c().dir, PIN);
      await c().repo.acceptResult(f, JSON.stringify(sampleResult()), "r".repeat(64));
      const { editKeyHash } = await import("@/lib/trial/edit-key");
      await c().pg`update trial_jobs set edit_key_hash = ${editKeyHash(KEY)} where id = ${id}`;
      return id;
    };
    let n = 0;
    const version = async (id: string) => (await c().pg`select bundle_version from trial_jobs where id = ${id}`)[0]!.bundle_version as number;
    /** Кнопка «Подтвердить» (или старая правка без подтверждения) → воркер собирает `out` → публикация. */
    const publish = async (id: string, out: string, confirm = true) => {
      if (confirm) {
        const { askConfirm } = await import("@/lib/trial/repo-confirm");
        const r = await askConfirm(id, { k: KEY, request_id: `req-${String(++n).padStart(8, "0")}`, base_version: await version(id), rooms_ok: [] },
          c().dir);
        expect(r.ok).toBe(true);
      } else {
        await c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version, kind) values (${`rb-${++n}`}, ${id},
          ${`req-${String(n).padStart(8, "0")}`}, '["*"]'::jsonb, ${await version(id)}, 'furnish')`;
      }
      const w = await W();
      const g = (await w.claimRebuild("w1", { edit: true }))!;
      const r = await w.publishRebuild({ id: g.id, attempt: g.attempt, leaseToken: g.leaseToken, jobId: id }, out, sha(out), c().dir, PIN);
      expect(r).toMatchObject({ repeated: expect.any(Boolean) });
      return g.id;
    };
    const batches = (id: string) => c().pg`select id, rebuild_id, bundle_version, status, tasks, reserved_rub::float8 as rub, refused, warn
      from trial_photo_batches where job_id = ${id} order by created_at, id`;
    const tasks = (id: string) => c().pg`select id, room_id, variant_id, style, ord, status, reserve_rub::float8 as rub, photo_id, fail_code,
      jsonb_array_length(cams) as cams from trial_photo_tasks where job_id = ${id} order by created_at, ord`;

    it("миграция 036 повторяется без ошибки", async () => {
      const text = await fs.readFile(path.join(process.cwd(), "db/init/036-trial-auto-photos.sql"), "utf8");
      await c().pg.unsafe(text);
      await c().pg.unsafe(text);
    });

    it("подтверждение → партия той же транзакцией: версия, гостиная и спальни по площади, активный стиль, C1/C2, резерв 10 ₽; отказы с кодом", async () => {
      const id = await doneJob();
      const rb = await publish(id, tourBundle(id, { rev: 1 }));
      const v = await version(id);
      const [b] = await batches(id);
      expect(b).toMatchObject({ rebuild_id: rb, bundle_version: v, status: "queued", tasks: 3, rub: 30, warn: null });
      expect(b!.refused).toEqual([{ room: "bedroom-4", code: "no_cams" }, { room: "bedroom-5", code: "no_furniture" }]);
      expect((await tasks(id)).map((t) => [t.room_id, t.variant_id, t.style, t.ord, t.status, t.rub, t.cams])).toEqual([
        ["living", "living-scandi", "scandi", 0, "reserved", 10, 2], ["bedroom-2", "bedroom-2-scandi", "scandi", 1, "reserved", 10, 2],
        ["bedroom-1", "bedroom-1-scandi", "scandi", 2, "reserved", 10, 2]]);
    });

    it("повторное подтверждение без правок — партия пустая, 0 новых задач; правка одной спальни — только она", async () => {
      const id = await doneJob();
      await publish(id, tourBundle(id, { rev: 1 }));
      await publish(id, tourBundle(id, { rev: 1 }));                                 // та же сборка — та же версия
      await publish(id, tourBundle(id, { rev: 2 }));                                 // новая версия, расстановки те же
      expect((await batches(id)).map((b) => [b.status, b.tasks])).toEqual([["queued", 3], ["empty", 0], ["empty", 0]]);
      expect(await tasks(id)).toHaveLength(3);
      await publish(id, tourBundle(id, { rev: 3 }, { items: [item("диван", 140), item("стол", 300)] }));
      const b = await batches(id);
      expect([b[3]!.status, b[3]!.tasks]).toEqual(["queued", 1]);
      expect((await tasks(id)).slice(3).map((t) => t.room_id)).toEqual(["bedroom-1"]);
    });

    it("пересборка без подтверждения (Обустроить) автофото не ставит", async () => {
      const id = await doneJob();
      await publish(id, tourBundle(id, { rev: 1 }), false);
      expect(await batches(id)).toEqual([]);
    });

    it("потолок тура (за всё время) и суток на все туры; предупреждение на пороге", async () => {
      const id = await doneJob();
      const { enqueueAutoPhotos } = await import("@/lib/trial/auto-photos-queue");
      const { AUTO_RULES } = await import("@/lib/trial/auto-photos-pick");
      const { db } = await import("@/lib/db");
      const run = (rb: string, json: string, rules = AUTO_RULES) =>
        db().transaction((tx) => enqueueAutoPhotos(tx, { jobId: id, version: 1, rebuildId: rb, json }, rules));
      const r1 = await run("rb-cap-1", tourBundle(id, { rev: 1 }), { ...AUTO_RULES, tour_cap_rub: 25 });
      expect(r1).toMatchObject({ tasks: 2, reservedRub: 20 });
      expect(r1!.refused).toContainEqual({ room: "bedroom-1", code: "tour_cap" });
      // факт меньше резерва — в потолке факт: место освобождается под изменённую комнату
      await c().pg`update trial_photo_tasks set photo_id = 'p1', status = 'done', spent_rub = 5 where job_id = ${id}`;
      const r2 = await run("rb-cap-2", tourBundle(id, { rev: 2 }), { ...AUTO_RULES, tour_cap_rub: 25 });
      expect(r2).toMatchObject({ tasks: 1 });
      // сутки: у этого тура связано 5 + 5 + 10 = 20 ₽, другой тур — 470 ₽: следующая задача 10 ₽ ровно влезает в 500 (≥ 400 —
      // предупреждение), следующая — отказ daily_cap
      const other = await doneJob();
      await c().pg`insert into trial_photo_batches (id, job_id, rebuild_id, bundle_version, status) values ('ob', ${other}, 'orb', 1, 'done')`;
      await c().pg`insert into trial_photo_tasks (id, batch_id, job_id, room_id, variant_id, style, ord, variant_sig, cams, cams_sig, reserve_rub, status)
        values ('ot', 'ob', ${other}, 'living', 'v', 's', 0, 'sig', '[]'::jsonb, 'c', 470, 'reserved')`;
      const big = { ...AUTO_RULES, tour_cap_rub: 1000 };
      expect(await run("rb-cap-3", tourBundle(id, { rev: 3 }, { items: [item("диван", 160)] }), big)).toMatchObject({ tasks: 1, warn: "daily_warn" });
      const r4 = await run("rb-cap-4", tourBundle(id, { rev: 4 }, { items: [item("диван", 180)] }), big);
      expect(r4).toMatchObject({ tasks: 0, warn: null });
      expect(r4!.refused).toContainEqual({ room: "bedroom-1", code: "daily_cap" });
      expect((await batches(id)).at(-1)).toMatchObject({ status: "empty" });
      // задача, сорвавшаяся до заказа (номера фото нет), денег не держит — место в сутках вернулось
      await c().pg`update trial_photo_tasks set status = 'failed', photo_id = null where id = 'ot'`;
      expect(await run("rb-cap-5", tourBundle(id, { rev: 5 }, { items: [item("диван", 200)] }), big)).toMatchObject({ tasks: 1 });
    });

    it("исполнитель: аренда партии → заказ auto по своей задаче (квота людей не тронута) → готово закрывает задачу; повтор — отказ", async () => {
      const id = await doneJob();
      await publish(id, tourBundle(id, { rev: 1 }));
      const a = await A();
      const [got, none] = await Promise.all([a.claimAutoBatch("dev-1"), a.claimAutoBatch("dev-2")]);
      const b = got ?? none;
      expect([got, none].filter(Boolean)).toHaveLength(1);
      expect(b).toMatchObject({ jobId: id, bundleVersion: await version(id), tourPath: `/try/${id}/tour`, attempt: 1 });
      expect(b!.tasks.map((t) => t.roomId)).toEqual(["living", "bedroom-2", "bedroom-1"]);
      expect(b!.tasks[0]!.cams.map((x) => x.name)).toEqual(["C1", "C2"]);
      const lease = { batchId: b!.batchId, leaseToken: b!.leaseToken };
      const [t0, t1, t2] = b!.tasks;
      expect(await a.markAutoTask({ ...lease, taskId: t0!.id, status: "shooting" })).toMatchObject({ ok: true, status: "shooting" });
      expect(await a.markAutoTask({ ...lease, leaseToken: "x".repeat(24), taskId: t0!.id, status: "shooting" })).toEqual({ ok: false, error: "lease_lost" });

      const { askPhoto } = await import("@/lib/trial/repo-photo");
      const { trialPhotoIn } = await import("@/contracts/trial");
      const sent: Record<string, unknown>[] = [];
      const send = (reply: { status: number; body: Record<string, unknown> | null }) =>
        async (p: Record<string, unknown>) => { sent.push(p); return reply; };
      const order = (room: string, task?: string) => trialPhotoIn.parse({ room_id: room, views: [{ camera: "C1", id: "a".repeat(64) },
        { camera: "C2", id: "b".repeat(64) }], room: { w: 400, d: 300 }, items: [{ role: "диван" }], variant_id: `${room}-scandi`,
        stateId: "s1-" + "0".repeat(32), ...(task ? { auto_task: task } : {}) });
      const env = { TRIAL_PHOTO_DAILY: "1" } as unknown as NodeJS.ProcessEnv;
      const ok = { status: 200, body: { job: "dj-auto-1" } };
      expect(await askPhoto(id, order("living"), "", send(ok), c().dir, env, "auto")).toMatchObject({ ok: false, error: "auto_task_required" });
      expect(await askPhoto(id, order("living", t1!.id), "", send(ok), c().dir, env, "auto")).toMatchObject({ ok: false, error: "auto_task_busy" });
      expect(await askPhoto(id, order("living", t0!.id), "", send(ok), c().dir, env, "auto")).toEqual({ ok: true, job: "dj-auto-1" });
      expect(sent.at(-1)).toMatchObject({ trial: id, trial_class: "auto", quality: "realistic" });
      expect(sent.at(-1)).not.toHaveProperty("auto_task");
      expect(await askPhoto(id, order("living", t0!.id), "", send(ok), c().dir, env, "auto")).toMatchObject({ ok: false, error: "auto_task_busy" });
      // квота людей (1 в сутки здесь) не уменьшилась от автофото
      expect(await askPhoto(id, order("living"), "", send({ status: 200, body: { job: "dj-human" } }), c().dir, env, "buyer"))
        .toEqual({ ok: true, job: "dj-human" });
      // отказ сервиса кадров — задача failed, номер фото снят (резерв вернулся)
      expect(await askPhoto(id, order("bedroom-2", t1!.id), "", send({ status: 402, body: { code: "no_credits" } }), c().dir, env, "auto"))
        .toMatchObject({ ok: false, error: "no_credits" });
      let ts = await tasks(id);
      expect(ts.find((t) => t.id === t0!.id)).toMatchObject({ status: "ordered" });
      expect(ts.find((t) => t.id === t1!.id)).toMatchObject({ status: "failed", fail_code: "no_credits", photo_id: null });
      const [photo] = await c().pg`select source, state_id from trial_photos where draft_job = 'dj-auto-1'`;
      expect(photo).toMatchObject({ source: "auto", state_id: "s1-" + "0".repeat(32) });
      // готовое фото → задача done; факт → в потолок
      const { finishPhoto } = await import("@/lib/trial/repo-photo-done");
      await finishPhoto(id, { draft_job: "dj-auto-1", status: "failed", code: "gen_failed" }, c().dir);
      ts = await tasks(id);
      expect(ts.find((t) => t.id === t0!.id)).toMatchObject({ status: "failed", fail_code: "gen_failed" });
      expect(await a.markAutoTask({ ...lease, taskId: t0!.id, spent_rub: 5.2 })).toMatchObject({ ok: true });
      expect(await a.markAutoTask({ ...lease, taskId: t2!.id, spent_rub: 5 })).toEqual({ ok: false, error: "bad_transition" });
      expect(await a.markAutoTask({ ...lease, taskId: t0!.id, status: "skipped", code: "variant_mismatch" })).toEqual({ ok: false, error: "bad_transition" });
      // закрыть партию: незаказанная → abandoned; повтор — lease_lost
      expect(await a.finishAutoBatch(lease)).toEqual({ ok: true, abandoned: 1 });
      expect(await a.finishAutoBatch(lease)).toEqual({ ok: false, error: "lease_lost" });
      expect((await batches(id))[0]).toMatchObject({ status: "done" });
      expect(await a.claimAutoBatch("dev-1")).toBeNull();
    });

    it("версия тура ушла дальше до съёмки — партия закрыта stale_version, задачи skipped; истёкшая аренда → попытка 2 → после 3 — failed", async () => {
      const id = await doneJob();
      await publish(id, tourBundle(id, { rev: 1 }));
      await publish(id, tourBundle(id, { rev: 2 }), false);                         // Обустроить: версия +1, автофото нет
      const a = await A();
      expect(await a.claimAutoBatch("dev-1")).toBeNull();
      expect((await batches(id))[0]).toMatchObject({ status: "done" });
      expect((await tasks(id)).every((t) => t.status === "skipped" && t.fail_code === "stale_version")).toBe(true);

      const id2 = await doneJob();
      await publish(id2, tourBundle(id2, { rev: 1 }));
      const expire = () => c().pg`update trial_photo_batches set lease_until = now() - interval '1 second' where job_id = ${id2}`;
      const b1 = (await a.claimAutoBatch("dev-1"))!;
      await expire();
      const b2 = (await a.claimAutoBatch("dev-2"))!;
      expect([b2.batchId, b2.attempt, b2.leaseToken === b1.leaseToken]).toEqual([b1.batchId, 2, false]);
      expect(await a.markAutoTask({ batchId: b1.batchId, leaseToken: b1.leaseToken, taskId: b1.tasks[0]!.id, status: "shooting" }))
        .toEqual({ ok: false, error: "lease_lost" });
      await expire();
      await a.claimAutoBatch("dev-3");
      await expire();
      expect(await a.claimAutoBatch("dev-4")).toBeNull();
      expect((await batches(id2))[0]).toMatchObject({ status: "failed" });
      expect((await tasks(id2)).every((t) => t.status === "failed" && t.fail_code === "lease_lost")).toBe(true);
    });

    it("тур не готов (TOUR_READY) — партия обратно в очередь без траты попытки, не раньше паузы; срочная/догон; много возвратов — failed", async () => {
      const id = await doneJob();
      await publish(id, tourBundle(id, { rev: 1 }));
      const a = await A();
      const b1 = (await a.claimAutoBatch("dev-1"))!;
      expect(b1.urgency).toBe("urgent");
      await a.markAutoTask({ batchId: b1.batchId, leaseToken: b1.leaseToken, taskId: b1.tasks[0]!.id, status: "shooting" });
      expect(await a.releaseAutoBatch({ batchId: b1.batchId, leaseToken: b1.leaseToken, code: "tour_not_ready" })).toEqual({ ok: true, status: "queued" });
      expect(await a.releaseAutoBatch({ batchId: b1.batchId, leaseToken: b1.leaseToken, code: "tour_not_ready" })).toEqual({ ok: false, error: "lease_lost" });
      expect(await a.claimAutoBatch("dev-1")).toBeNull();                               // пауза retry_s ещё не прошла
      expect((await tasks(id)).map((t) => t.status)).toEqual(["reserved", "reserved", "reserved"]);
      await c().pg`update trial_photo_batches set next_run_at = now() where job_id = ${id}`;
      const b2 = (await a.claimAutoBatch("dev-1"))!;
      expect([b2.batchId, b2.attempt, b2.urgency, b2.tasks.length]).toEqual([b1.batchId, 1, "urgent", 3]);
      // истёкшая аренда (съёмщик упал) — следующая выдача уже догон; старая партия — тоже догон
      await c().pg`update trial_photo_batches set lease_until = now() - interval '1 second' where job_id = ${id}`;
      expect((await a.claimAutoBatch("dev-2"))!.urgency).toBe("catchup");
      await c().pg`update trial_photo_batches set releases = 30 where job_id = ${id}`;
      const [cur] = await c().pg`select lease_token from trial_photo_batches where job_id = ${id}`;
      expect(await a.releaseAutoBatch({ batchId: b1.batchId, leaseToken: cur!.lease_token as string, code: "tour_not_ready" }))
        .toEqual({ ok: true, status: "failed" });
      expect((await tasks(id)).every((t) => t.status === "failed" && t.fail_code === "tour_not_ready")).toBe(true);
    });

    it("ручки исполнителя — только Bearer воркера; claim по ручке отдаёт партию", async () => {
      const id = await doneJob();
      await publish(id, tourBundle(id, { rev: 1 }));
      const claim = await import("@/app/api/trial/worker/photos/claim/route");
      const req = (auth?: string) => new Request("http://app/api/trial/worker/photos/claim", { method: "POST",
        headers: { "content-type": "application/json", ...(auth ? { authorization: auth } : {}) }, body: JSON.stringify({ workerId: "dev-1" }) });
      expect((await claim.POST(req())).status).toBe(401);
      expect((await claim.POST(req("Bearer wrong"))).status).toBe(401);
      const r = await claim.POST(req(`Bearer ${c().token}`));
      expect(r.status).toBe(200);
      const body = (await r.json()) as { batch: { jobId: string; tasks: unknown[] } };
      expect(body.batch.jobId).toBe(id);
      expect(body.batch.tasks).toHaveLength(3);
      const task = await import("@/app/api/trial/worker/photos/task/route");
      const bad = await task.POST(new Request("http://app/x", { method: "POST", headers: { authorization: `Bearer ${c().token}` },
        body: JSON.stringify({ batchId: "b".repeat(22), leaseToken: "t".repeat(24), taskId: "x".repeat(22), status: "failed" }) }));
      expect(bad.status).toBe(400);                                                  // отказ без кода — не принимаем
    });
  });
}
