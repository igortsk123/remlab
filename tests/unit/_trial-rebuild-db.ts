import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type postgresT from "postgres";

import { bundleOf } from "./_trial-bundle-db";
import { sampleResult, withOneRowStats } from "./_trial-helpers";

// «Обустроить» на НАСТОЯЩЕЙ Postgres (agent-trial-08, Р1; T-20261109-27): ключ правки, повтор request_id, устаревшая версия (при нажатии и
// перед публикацией), одна активная, суточный лимит, аренда (потеря, перехват, исчерпание), одна новая версия, накопленные комнаты,
// приоритет с квотой, публичное состояние без ключа. Подключается внутрь `describe` файла trial-claim.test.ts (тот чистит таблицы).

type Ctx = {
  pg: ReturnType<typeof postgresT>;
  repo: typeof import("@/lib/trial/repo-worker");
  seed: () => Promise<{ id: string }>;
  row: (id: string) => Promise<Record<string, unknown>>;
  dir: string;
  token: string;
};

const KEY = "K".repeat(22);
const sha = (s: string) => createHash("sha256").update(s).digest("hex");
const geo = { w: 400, d: 300, title: "Комната", openings: [], radiators: [] };
const awaiting = (rid: string) => ({ id: rid, furniture_state: "awaiting_check", furniture_text: "Размеры не подтверждены" });
/** Версия «все цели ждут проверки»: гостиная и спальня в `awaiting_check`, кухня не обставляется. */
const waitingBundle = (id: string, n = 1) => JSON.stringify(bundleOf(id, {
  rev: n, rooms_geo: { living: geo, "bedroom-1": geo },
  apartment_rooms: [awaiting("living"), awaiting("bedroom-1"), { id: "kitchen-1", furniture_state: "not_furnished", furniture_text: "Кухня" }],
  variants: ["living", "bedroom-1"].map((r) => ({ id: `${r}-wait`, room_id: r, style: "scandi", items: [], pending: false, furniture_state: "awaiting_check" })),
}));
/** Итог пересборки: обе комнаты с мебелью. */
const furnishedBundle = (id: string, tag = "a") => JSON.stringify(bundleOf(id, {
  tag, rooms_geo: { living: geo, "bedroom-1": geo },
  apartment_rooms: ["living", "bedroom-1"].map((r) => ({ id: r, furniture_state: "ready", furniture_text: null, approx_consent: true })),
  variants: ["living", "bedroom-1"].map((r) => ({ id: `${r}-s`, room_id: r, style: "scandi", items: [{ role: "диван", x: 1, y: 1 }], pending: false,
    furniture_state: "ready" })),
}));
const PIN = async (): Promise<"exists"> => "exists";

export function rebuildDbTests(c: () => Ctx): void {
  describe("«Обустроить»: очередь пересборок", () => {
    const W = () => import("@/lib/trial/repo-rebuild-worker");
    /** Задание `done` с версией 1, где все цели ждут проверки; ключ правки — KEY (или без ключа — старое задание). */
    const doneJob = async (withKey = true) => {
      const { id } = await c().seed();
      const a = (await c().repo.claim(`w-${id}`))!;
      const f = { id, attempt: a.attempt, leaseToken: a.leaseToken };
      const { publishBundle } = await import("@/lib/trial/repo-bundle");
      await publishBundle(f, waitingBundle(id), sha(waitingBundle(id)), c().dir, PIN);
      await c().repo.acceptResult(f, JSON.stringify(sampleResult()), "r".repeat(64));
      if (withKey) {
        const { editKeyHash } = await import("@/lib/trial/edit-key");
        await c().pg`update trial_jobs set edit_key_hash = ${editKeyHash(KEY)} where id = ${id}`;
      }
      return id;
    };
    const ask = async (id: string, body: Record<string, unknown>, headers: Record<string, string> = {}) => {
      const { POST } = await import("@/app/api/trial/[id]/rebuild/route");
      const r = await POST(new Request(`http://app/api/trial/${id}/rebuild`, { method: "POST", headers, body: JSON.stringify(body) }),
        { params: Promise.resolve({ id }) });
      return { status: r.status, body: (await r.json()) as Record<string, unknown> };
    };
    const body = (over: Record<string, unknown> = {}) => ({ k: KEY, request_id: "req-00000001", base_version: 1, rooms: "all", ...over });
    const ROUTES = {
      claim: () => import("@/app/api/trial/worker/claim/route"),
      "rebuild/heartbeat": () => import("@/app/api/trial/worker/rebuild/heartbeat/route"),
      "rebuild/publish": () => import("@/app/api/trial/worker/rebuild/publish/route"),
      "rebuild/fail": () => import("@/app/api/trial/worker/rebuild/fail/route"),
    };
    const worker = async (path_: keyof typeof ROUTES, b: unknown) => {
      const mod = await ROUTES[path_]();
      const r = await mod.POST(new Request("http://app/x", { method: "POST", headers: { authorization: `Bearer ${c().token}` }, body: JSON.stringify(b) }));
      return { status: r.status, body: (await r.json()) as Record<string, unknown> };
    };
    const lease = (r: { id: string; attempt: number; leaseToken: string }) => ({ id: r.id, attempt: r.attempt, leaseToken: r.leaseToken });
    const view = async (id: string) => (await (await import("@/lib/trial/repo-public")).jobView(id)) as Record<string, unknown>;

    it("миграция повторяется без ошибки; ключ в базе — только хэш, наружу не выходит", async () => {
      const text = await fs.readFile(path.join(process.cwd(), "db/init/024-trial-rebuilds.sql"), "utf8");
      await c().pg.unsafe(text);
      await c().pg.unsafe(text);
      const { newEditKey } = await import("@/lib/trial/edit-key");
      const { key, hash } = newEditKey();
      expect(key).toMatch(/^[A-Za-z0-9_-]{22}$/);
      expect(hash).toMatch(/^[0-9a-f]{64}$/);
      const id = await doneJob();
      const row = await c().row(id);
      expect(JSON.stringify(row)).not.toContain(KEY);
      const v = await view(id);
      expect(JSON.stringify(v)).not.toMatch(/edit|K{22}/);
      expect(v).toMatchObject({ rebuild: null, rebuildError: null });
    });

    it("право: без ключа, чужой ключ, старое задание без ключа — 403; нет задания — 404; чужой сайт — 403", async () => {
      const id = await doneJob();
      expect((await ask(id, body({ k: "Z".repeat(22) }))).status).toBe(403);
      expect((await ask(id, { ...body(), k: undefined })).status).toBe(400);
      const old = await doneJob(false);
      expect(await ask(old, body())).toMatchObject({ status: 403, body: { error: "forbidden" } });
      expect((await ask("A".repeat(22), body())).status).toBe(404);
      expect((await ask(id, body(), { origin: "https://evil.test" })).status).toBe(403);
      expect(await c().pg`select * from trial_rebuilds`).toHaveLength(0);
    });

    it("постановка: 202; повтор request_id — та же строка (и после смены версии); вторая другая — busy; устаревшая — stale с версией", async () => {
      const id = await doneJob();
      const first = await ask(id, body());
      expect(first).toMatchObject({ status: 202, body: { ok: true, repeated: false, rebuild: { status: "queued" } } });
      const again = await ask(id, body());
      expect(again.body).toMatchObject({ repeated: true, rebuild: { id: (first.body.rebuild as { id: string }).id } });
      expect(await ask(id, body({ request_id: "req-00000002" }))).toMatchObject({ status: 409, body: { error: "busy" } });
      await c().pg`update trial_jobs set bundle_version = 2 where id = ${id}`;
      expect((await ask(id, body())).body).toMatchObject({ repeated: true });
      await c().pg`update trial_rebuilds set status = 'done'`;
      expect(await ask(id, body({ request_id: "req-00000003" }))).toMatchObject({ status: 409, body: { error: "stale", version: 2 } });
      expect(await c().pg`select * from trial_rebuilds`).toHaveLength(1);
    });

    it("два одновременных нажатия разными request_id — одна пересборка; комнаты проверяются по версии; лимит в сутки", async () => {
      const id = await doneJob();
      const two = await Promise.all([ask(id, body({ request_id: "req-aaaaaaa1" })), ask(id, body({ request_id: "req-aaaaaaa2" }))]);
      expect(two.map((x) => x.status).sort()).toEqual([202, 409]);
      await c().pg`update trial_rebuilds set status = 'done'`;
      expect(await ask(id, body({ request_id: "req-bbbbbbb1", rooms: ["kitchen-1"] }))).toMatchObject({ status: 422, body: { error: "bad_rooms" } });
      expect((await ask(id, body({ request_id: "req-bbbbbbb2", rooms: ["bedroom-1"] }))).status).toBe(202);
      await c().pg`update trial_rebuilds set status = 'done'`;
      process.env.TRIAL_REBUILD_DAILY = "2";
      expect(await ask(id, body({ request_id: "req-bbbbbbb3" }))).toMatchObject({ status: 429, body: { error: "rebuild_limit" } });
      delete process.env.TRIAL_REBUILD_DAILY;
      const notDone = (await c().seed()).id;
      await c().pg`update trial_jobs set edit_key_hash = (select edit_key_hash from trial_jobs where id = ${id}) where id = ${notDone}`;
      expect(await ask(notDone, body())).toMatchObject({ status: 409, body: { error: "not_ready" } });
    });

    it("воркер: claim (накопленные комнаты + результат из базы) → одна новая версия; задание остаётся done; повтор — repeated", async () => {
      const id = await doneJob();
      await c().pg`update trial_jobs set released_rooms = '["bedroom-1"]'::jsonb where id = ${id}`;
      await ask(id, body({ rooms: ["living"] }));
      const w = await W();
      const r = (await w.claimRebuild("w9"))!;
      expect(r).toMatchObject({ jobId: id, attempt: 1, baseVersion: 1, result: { version: 1, units: "cm" } });
      expect([...r.rooms].sort()).toEqual(["bedroom-1", "living"]);
      expect(await view(id)).toMatchObject({ status: "done", rebuild: "running" });
      expect(await w.heartbeatRebuild(lease(r))).toMatchObject({ leaseUntil: expect.any(String) });
      const text = furnishedBundle(id);
      const pubBody = { ...lease(r), jobId: id, bundle: text, sha256: sha(text) };
      expect(await worker("rebuild/publish", pubBody)).toMatchObject({ status: 200, body: { ok: true, version: 3, repeated: false } });
      expect(await c().row(id)).toMatchObject({ status: "done", bundle_version: 3, result_version: 3, released_rooms: ["bedroom-1", "living"] });
      expect(await worker("rebuild/publish", pubBody)).toMatchObject({ status: 200, body: { version: 3, repeated: true } });
      expect((await fs.readdir(path.join(c().dir, id))).filter((n) => n.startsWith("bundle-")).sort()).toEqual(["bundle-3.json"]); // хранится 2: 2..3
      expect(await view(id)).toMatchObject({ rebuild: null, bundleVersion: 3 });
      const { latestBundle } = await import("@/lib/trial/repo-bundle");
      const got = await latestBundle(id, c().dir);
      expect(typeof got === "object" && JSON.parse(got.json).tag).toBe("a");
    });

    it("устарела перед публикацией — ничего не пишем, пересборка failed/stale, страница видит код", async () => {
      const id = await doneJob();
      await ask(id, body());
      const r = (await (await W()).claimRebuild("w9"))!;
      await c().pg`update trial_jobs set bundle_version = 2, result_version = 3 where id = ${id}`;
      const text = furnishedBundle(id);
      expect(await worker("rebuild/publish", { ...lease(r), jobId: id, bundle: text, sha256: sha(text) }))
        .toMatchObject({ status: 409, body: { error: "stale" } });
      expect(await c().row(id)).toMatchObject({ bundle_version: 2, result_version: 3, released_rooms: [] });
      expect((await fs.readdir(path.join(c().dir, id))).filter((n) => n.startsWith("bundle-"))).toEqual(["bundle-1.json"]);
      expect(await view(id)).toMatchObject({ rebuild: "failed", rebuildError: "stale" });
    });

    it("аренда: просрочена — heartbeat/publish отказ; перехват даёт попытку 2; старая не пишет; исчерпана — failed/lease_lost", async () => {
      const id = await doneJob();
      await ask(id, body());
      const w = await W();
      const a = (await w.claimRebuild("w1"))!;
      await c().pg`update trial_rebuilds set lease_until = now() - interval '1 second'`;
      expect(await w.heartbeatRebuild(lease(a))).toBeNull();
      expect((await worker("rebuild/heartbeat", lease(a))).status).toBe(409);
      const b = (await w.claimRebuild("w2"))!;
      expect(b.attempt).toBe(2);
      const text = furnishedBundle(id);
      expect((await worker("rebuild/publish", { ...lease(a), jobId: id, bundle: text, sha256: sha(text) })).status).toBe(409);
      expect((await worker("rebuild/publish", { ...lease(b), jobId: "B".repeat(22), bundle: text, sha256: sha(text) })).body)
        .toMatchObject({ error: "wrong_job" });
      await c().pg`update trial_rebuilds set lease_until = now() - interval '1 second'`;
      expect(await w.claimRebuild("w3")).toBeNull();
      expect(await view(id)).toMatchObject({ rebuild: "failed", rebuildError: "lease_lost" });
      expect(await c().row(id)).toMatchObject({ bundle_version: 1 });
    });

    it("сбой у воркера: повторяемый — снова в очереди; занят — попытку не тратит; иначе failed с кодом", async () => {
      const id = await doneJob();
      await ask(id, body());
      const w = await W();
      const a = (await w.claimRebuild("w1"))!;
      expect(await worker("rebuild/fail", { ...lease(a), code: "waiting_capacity", retryable: true })).toMatchObject({ body: { status: "queued" } });
      const b = (await w.claimRebuild("w1"))!;
      expect(b.attempt).toBe(1);
      expect(await worker("rebuild/fail", { ...lease(b), code: "pipeline_error", retryable: true })).toMatchObject({ body: { status: "queued" } });
      const d = (await w.claimRebuild("w1"))!;
      expect(await worker("rebuild/fail", { ...lease(d), code: "timeout", retryable: false })).toMatchObject({ body: { status: "failed" } });
      expect(await view(id)).toMatchObject({ rebuild: "failed", rebuildError: "timeout" });
      expect((await worker("rebuild/fail", { ...lease(d), code: "timeout", retryable: false })).status).toBe(409);
    });

    it("один claimRebuild — ровно одна пересборка в running, и при плане Nested Loop со статистикой одной строки (T-20261109-37)", async () => {
      const queued = async (n: number) => {
        const ids: string[] = [];
        for (let i = 0; i < n; i++) {
          const { id } = await c().seed();
          await c().pg`update trial_jobs set status = 'done' where id = ${id}`;
          await c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version, created_at)
            values (${`rb${i}-${id}`}, ${id}, ${`req-${id}`}, '["*"]'::jsonb, 1, now() - make_interval(secs => ${n - i}))`;
          ids.push(`rb${i}-${id}`);
        }
        return ids;
      };
      let ids: string[] = [];
      const r = await withOneRowStats(c().pg, ["trial_rebuilds", "trial_jobs"], () => queued(1), async () => {
        ids = await queued(4);
        return (await W()).claimRebuild("w1");
      });
      expect(r?.id).toBe(ids[0]);
      expect((await c().pg`select id from trial_rebuilds where status = 'running'`).map((x) => x.id)).toEqual([ids[0]]);
    });

    it("приоритет с квотой: пересборки раньше загрузки, но не больше двух подряд, пока она ждёт; старый воркер их не видит", async () => {
      const jobs = [await doneJob(), await doneJob(), await doneJob()];
      for (const id of jobs) await ask(id, body());
      const upload = (await c().seed()).id;
      const claimVia = (rebuilds: boolean) => worker("claim", { workerId: "wq", rebuilds });
      const one = await claimVia(true);
      const two = await claimVia(true);
      expect([one.body.rebuild, two.body.rebuild].every(Boolean)).toBe(true);
      const three = await claimVia(true);
      expect(three.body).toMatchObject({ job: { id: upload } });
      expect((await claimVia(true)).body.rebuild).toMatchObject({ jobId: expect.any(String) });
      await c().pg`update trial_rebuilds set status = 'queued', lease_until = null, attempt = 0 where status = 'running'`;
      const old = await worker("claim", { workerId: "old" });
      expect(old.body.rebuild).toBeUndefined();
    });
  });
}
