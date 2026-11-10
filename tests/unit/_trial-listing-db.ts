import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type postgresT from "postgres";

import { bundleOf } from "./_trial-bundle-db";
import { sampleResult } from "./_trial-helpers";

// «Размеры своими словами» на НАСТОЯЩЕЙ Postgres (agent-trial-08, Р2-текст; T-20261109-33): текст агента принимается уже на v1 (задание
// идёт) — «принято, применим после сборки»; ключ на сервере; повтор request_id без второй работы; новый текст ЗАМЕНЯЕТ ждущий; одна
// активная пересборка на задание (с «Обустроить»); суточный лимит Р1; исходного листа нет — понятный отказ; старый воркер строк `listing`
// не получает; claim после `done` берёт ТЕКУЩУЮ версию (v1→v3 — не «устарело»); текст не виден ни в статусе, ни после пересборки.
// Подключается внутрь `describe` файла trial-claim.test.ts (тот чистит таблицы перед каждым тестом).

type Ctx = {
  pg: ReturnType<typeof postgresT>;
  repo: typeof import("@/lib/trial/repo-worker");
  seed: () => Promise<{ id: string }>;
  row: (id: string) => Promise<Record<string, unknown>>;
  dir: string;
  token: string;
};

const KEY = "L".repeat(22);
const TEXT = "СЕКРЕТ гостиная 4,2 на 3,8; спальня 3×3";
const sha = (s: string) => createHash("sha256").update(s).digest("hex");
const PIN = async (): Promise<"exists"> => "exists";
/** Версия данных «размеров нет»: масштаб не подтверждён (как `trial_bundle.py` при `not_verified`). */
const noSizes = (id: string, rev: number) => JSON.stringify(bundleOf(id, { rev, trial: { job_id: id, scale: "not_verified" } }));

export function listingDbTests(c: () => Ctx): void {
  describe("«Размеры своими словами»: текст агента", () => {
    const W = () => import("@/lib/trial/repo-rebuild-worker");
    /** Задание идёт, опубликовано `versions` версий данных (v1 — результат чтения), ключ правки — KEY. */
    const runningJob = async (versions = 1) => {
      const { id } = await c().seed();
      const a = (await c().repo.claim(`w-${id}`))!;
      const f = { id, attempt: a.attempt, leaseToken: a.leaseToken };
      const { publishBundle } = await import("@/lib/trial/repo-bundle");
      for (let n = 1; n <= versions; n++) await publishBundle(f, noSizes(id, n), sha(noSizes(id, n)), c().dir, PIN);
      const { editKeyHash } = await import("@/lib/trial/edit-key");
      await c().pg`update trial_jobs set edit_key_hash = ${editKeyHash(KEY)} where id = ${id}`;
      return { id, f };
    };
    const finish = async (f: { id: string; attempt: number; leaseToken: string }) => {
      await c().repo.acceptResult(f, JSON.stringify(sampleResult()), "r".repeat(64));
    };
    const send = async (id: string, body: Record<string, unknown>) => {
      const { POST } = await import("@/app/api/trial/[id]/listing/route");
      const r = await POST(new Request(`http://app/api/trial/${id}/listing`, { method: "POST", body: JSON.stringify(body) }),
        { params: Promise.resolve({ id }) });
      return { status: r.status, body: (await r.json()) as Record<string, unknown> };
    };
    const body = (over: Record<string, unknown> = {}) => ({ k: KEY, request_id: "txt-00000001", text: TEXT, ...over });
    const view = async (id: string) => (await (await import("@/lib/trial/repo-public")).jobView(id)) as Record<string, unknown>;
    const rebuilds = (id: string) => c().pg`select kind, status, request_id, listing_text, base_version from trial_rebuilds where job_id = ${id}`;
    const claimVia = async (b: Record<string, unknown>) => {
      const { POST } = await import("@/app/api/trial/worker/claim/route");
      const r = await POST(new Request("http://app/x", { method: "POST", headers: { authorization: `Bearer ${c().token}` }, body: JSON.stringify(b) }));
      return (await r.json()) as Record<string, unknown>;
    };

    it("миграция 025 повторяется; на v1 (задание идёт) — 202 «принято»; окошко звать; текста нет ни в статусе, ни в ответе", async () => {
      const text = await fs.readFile(path.join(process.cwd(), "db/init/025-trial-listing-text.sql"), "utf8");
      await c().pg.unsafe(text);
      await c().pg.unsafe(text);
      const { id } = await runningJob();
      expect(await view(id)).toMatchObject({ status: "running", askSizes: true, listing: null });
      const r = await send(id, body());
      expect(r).toMatchObject({ status: 202, body: { ok: true, repeated: false, replaced: false, listing: { status: "queued" } } });
      expect(JSON.stringify(r.body)).not.toContain("СЕКРЕТ");
      const v = await view(id);
      expect(v).toMatchObject({ listing: "accepted", listingError: null, rebuild: null });
      expect(JSON.stringify(v)).not.toContain("СЕКРЕТ");
      expect(await rebuilds(id)).toEqual([{ kind: "listing", status: "queued", request_id: "txt-00000001", listing_text: TEXT, base_version: 1 }]);
    });

    it("отказы: до v1 — not_ready; без ключа/чужой — 403/400; пусто и длинно — 400; задание не удалось — not_ready", async () => {
      const { id } = await runningJob(); // первым: claim берёт старейшее задание очереди
      const { id: early } = await c().seed();
      const { editKeyHash } = await import("@/lib/trial/edit-key");
      await c().pg`update trial_jobs set edit_key_hash = ${editKeyHash(KEY)} where id = ${early}`;
      expect(await send(early, body())).toMatchObject({ status: 409, body: { error: "not_ready" } });
      expect((await send(id, body({ k: "Z".repeat(22) }))).status).toBe(403);
      expect((await send(id, { ...body(), k: undefined })).status).toBe(400);
      expect((await send(id, body({ text: "   " }))).status).toBe(400);
      expect((await send(id, body({ text: "а".repeat(2001) }))).status).toBe(400);
      expect(await send(id, body({ text: "а".repeat(2000) }))).toMatchObject({ status: 202 });
      await c().pg`update trial_jobs set status = 'failed' where id = ${id}`;
      expect(await send(id, body({ request_id: "txt-00000009" }))).toMatchObject({ status: 409, body: { error: "not_ready" } });
    });

    it("повтор request_id — та же строка; новый текст заменяет ждущий (не склеивает); второй строки нет", async () => {
      const { id } = await runningJob();
      const first = await send(id, body());
      expect((await send(id, body())).body).toMatchObject({ repeated: true, listing: first.body.listing });
      const two = await send(id, body({ request_id: "txt-00000002", text: "кухня 10 м²" }));
      expect(two).toMatchObject({ status: 202, body: { replaced: true, listing: first.body.listing } });
      expect(await rebuilds(id)).toEqual([expect.objectContaining({ request_id: "txt-00000002", listing_text: "кухня 10 м²" })]);
    });

    it("одна активная на задание: текст при идущем «Обустроить» — busy; «Обустроить» при ждущем тексте — busy; лимит в сутки", async () => {
      const { id, f } = await runningJob();
      await finish(f);
      await c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version) values ('rb1', ${id}, 'furnish-01', '["*"]', 1)`;
      expect(await send(id, body())).toMatchObject({ status: 409, body: { error: "busy" } });
      await c().pg`update trial_rebuilds set status = 'done' where id = 'rb1'`;
      expect((await send(id, body())).status).toBe(202);
      const { askRebuild } = await import("@/lib/trial/repo-rebuild");
      expect(await askRebuild(id, { k: KEY, request_id: "furnish-02", base_version: 1, rooms: "all" }, c().dir))
        .toMatchObject({ ok: false, error: "busy" });
      await c().pg`update trial_rebuilds set status = 'done' where job_id = ${id}`;
      process.env.TRIAL_REBUILD_DAILY = "2";
      expect(await send(id, body({ request_id: "txt-00000003" }))).toMatchObject({ status: 429, body: { error: "rebuild_limit" } });
      delete process.env.TRIAL_REBUILD_DAILY;
    });

    it("исходного листа нет — source_gone (загрузить заново)", async () => {
      const { id, f } = await runningJob();
      await finish(f);
      await c().pg`update trial_jobs set input_path = null where id = ${id}`;
      expect(await send(id, body())).toMatchObject({ status: 409, body: { error: "source_gone" } });
    });

    it("воркер: до done не берёт; старый воркер не видит; после done (v3) — claim с текущей версией; публикация; текст стёрт", async () => {
      const { id, f } = await runningJob();
      await send(id, body());
      const w = await W();
      expect(await w.claimRebuild("w1", true)).toBeNull(); // задание ещё идёт: текст ждёт сборки
      await w.exhaustRebuilds();
      expect(await view(id)).toMatchObject({ listing: "accepted" }); // ждущий текст не «устарел», пока задание идёт
      const { publishBundle } = await import("@/lib/trial/repo-bundle");
      for (const n of [2, 3]) await publishBundle(f, noSizes(id, n), sha(noSizes(id, n)), c().dir, PIN);
      await finish(f);
      expect(await view(id)).toMatchObject({ status: "done", bundleVersion: 3, listing: "applying" });
      expect((await claimVia({ workerId: "old", rebuilds: true })).rebuild ?? null).toBeNull(); // старый воркер — без `listing`
      const got = (await claimVia({ workerId: "new", rebuilds: true, listing: true })).rebuild as Record<string, unknown>;
      expect(got).toMatchObject({ jobId: id, kind: "listing", listingText: TEXT, baseVersion: 3 });
      const lease = { id: got.id as string, attempt: got.attempt as number, leaseToken: got.leaseToken as string };
      const out = JSON.stringify(bundleOf(id, { rev: 9, trial: { job_id: id, scale: "listing" } }));
      expect(await w.publishRebuild({ ...lease, jobId: id }, out, sha(out), c().dir, PIN)).toMatchObject({ version: 5, repeated: false });
      expect(await rebuilds(id)).toEqual([expect.objectContaining({ status: "done", listing_text: null })]);
      expect(await view(id)).toMatchObject({ listing: "done", bundleVersion: 5 });
    });

    it("задание не удалось — ждущий текст снимается (stale), текст стёрт; сбой воркера source_gone виден странице", async () => {
      const { id, f } = await runningJob();
      await send(id, body());
      await c().pg`update trial_jobs set status = 'failed' where id = ${id}`;
      await (await W()).exhaustRebuilds();
      expect(await rebuilds(id)).toEqual([expect.objectContaining({ status: "failed", listing_text: null })]);
      expect(await view(id)).toMatchObject({ listing: "failed", listingError: "stale" });
      const two = await runningJob();
      await send(two.id, body());
      await finish(two.f);
      const w = await W();
      const got = (await w.claimRebuild("w1", true))!;
      expect(await w.failRebuild({ id: got.id, attempt: got.attempt, leaseToken: got.leaseToken, code: "source_gone", retryable: false }))
        .toBe("failed");
      expect(await view(two.id)).toMatchObject({ listing: "failed", listingError: "source_gone" });
      expect(f.id).toBe(id);
    });
  });
}
