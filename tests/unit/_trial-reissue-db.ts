import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type postgresT from "postgres";

import { bundleOf } from "./_trial-bundle-db";
import { sampleResult } from "./_trial-helpers";

// Пересборка готового тура «как есть» на НАСТОЯЩЕЙ Postgres (agent-trial-08; T-20261110-05): список младше N дней, исходник (результат +
// точные байты версии), публикация от той же версии → новая версия и закрепление ТЕКУЩЕЙ витрины; stale / busy / not_ready / expired.
// Подключается внутрь `describe` файла trial-claim.test.ts (тот чистит таблицы).

type Ctx = {
  pg: ReturnType<typeof postgresT>;
  repo: typeof import("@/lib/trial/repo-worker");
  seed: () => Promise<{ id: string }>;
  row: (id: string) => Promise<Record<string, unknown>>;
  dir: string;
  token: string;
};

const sha = (s: string) => createHash("sha256").update(s).digest("hex");
const ids = (id: string) => ({ params: Promise.resolve({ id }) });
const text = (id: string, rev: string) => JSON.stringify(bundleOf(id, { rev }));

async function showcase(demo: string, page: string): Promise<void> {
  await fs.mkdir(path.join(demo, "lib"), { recursive: true });
  await fs.writeFile(path.join(demo, "index.html"), `<html><head></head><body>${page}</body></html>`);
  await fs.writeFile(path.join(demo, "lib", "scene.json"), JSON.stringify({ file: "scene.abc123.js" }));
  await fs.writeFile(path.join(demo, "lib", "scene.abc123.js"), "// scene");
  await fs.writeFile(path.join(demo, "rt-meshes.json"), "{}");
}

export function reissueDbTests(c: () => Ctx): void {
  describe("пересборка «как есть» (оператор)", () => {
    const demo = () => path.join(c().dir, "..", `demo-reissue-${process.pid}`);
    /** Готовый тур: версия 1 закреплена на витрине «старая страница», задание `done`. */
    const doneTour = async () => {
      const { id } = await c().seed();
      const a = (await c().repo.claim(`w-${id}`))!;
      const f = { id, attempt: a.attempt, leaseToken: a.leaseToken };
      await showcase(demo(), "старая страница");
      const { publishBundle } = await import("@/lib/trial/repo-bundle");
      const { ensureJobRelease } = await import("@/lib/trial/tour-bundle");
      const v1 = text(id, "old");
      await publishBundle(f, v1, sha(v1), c().dir, (j, d) => ensureJobRelease(j, d, demo()));
      await c().repo.acceptResult(f, JSON.stringify(sampleResult()), "r".repeat(64));
      return { id, v1 };
    };
    const call = async (method: "GET" | "POST", id: string, body?: unknown, auth = true) => {
      const mod = await import("@/app/api/trial/worker/reissue/[id]/route");
      const req = new Request(`http://app/api/trial/worker/reissue/${id}`, {
        method, headers: auth ? { authorization: `Bearer ${c().token}` } : {}, ...(body ? { body: JSON.stringify(body) } : {}),
      });
      const r = await (method === "GET" ? mod.GET(req, ids(id)) : mod.POST(req, ids(id)));
      return { status: r.status, body: (await r.json()) as Record<string, unknown> };
    };
    const list = async (days: string, auth = true) => {
      const { GET } = await import("@/app/api/trial/worker/reissue/route");
      const r = await GET(new Request(`http://app/api/trial/worker/reissue?days=${days}`, { headers: auth ? { authorization: `Bearer ${c().token}` } : {} }));
      return { status: r.status, body: (await r.json()) as { ok: boolean; jobs?: { id: string; version: number }[] } };
    };
    const release = async (id: string) => (await fs.readFile(path.join(c().dir, id, "release"), "utf8")).trim();
    const post = (id: string, base: number, json: string) => call("POST", id, { baseVersion: base, bundle: json, sha256: sha(json) });

    it("список младше N дней → исходник (точные байты) → новая версия от той же базы и новая витрина; старая копия витрины цела", async () => {
      process.env.DEMO_DIR = demo();
      try {
        const { id, v1 } = await doneTour();
        const { id: old } = await doneTour();
        await c().pg`update trial_jobs set created_at = now() - interval '10 days' where id = ${old}`;
        expect((await list("7")).body.jobs!.map((j) => j.id)).toEqual([id]);
        expect((await list("30")).body.jobs!.map((j) => j.id).sort()).toEqual([id, old].sort());
        const src = await call("GET", id);
        expect(src).toMatchObject({ status: 200, body: { ok: true, jobId: id, version: 1, bundle: v1 } });
        expect((src.body.result as { panels: unknown[] }).panels).toHaveLength(1);

        const before = await release(id);
        await showcase(demo(), "новая страница");                       // выкладка сменила витрину
        const v2 = text(id, "new");
        const pub = await post(id, 1, v2);                              // номер — общий счётчик задания (`result` занял 2)
        expect(pub).toMatchObject({ status: 200, body: { ok: true, version: 3, repeated: false, previous: before } });
        const after = await release(id);
        expect(after).not.toBe(before);
        expect(pub.body.release).toBe(after);
        const page = (r: string) => fs.readFile(path.join(c().dir, "tour", "_releases", r, "index.html"), "utf8");
        expect(await page(after)).toContain("новая страница");
        expect(await page(before)).toContain("старая страница");      // её держат другие туры
        expect(await c().row(id)).toMatchObject({ status: "done", bundle_version: 3, result_version: 3, bundle_hash: sha(v2) });
        expect(await fs.readFile(path.join(c().dir, id, "bundle-3.json"), "utf8")).toBe(v2);
        // те же байты ещё раз — версии нет, витрина та же; другие туры не тронуты
        expect(await post(id, 3, v2)).toMatchObject({ status: 200, body: { version: 3, repeated: true, release: after, previous: after } });
        expect(await c().row(old)).toMatchObject({ bundle_version: 1 });
      } finally {
        delete process.env.DEMO_DIR;
        await fs.rm(demo(), { recursive: true, force: true });
      }
    });

    it("отказы: устаревшая база — stale; идёт «Обустроить» — busy; не готов / нет файла версии / срок / нет — тур не тронут", async () => {
      process.env.DEMO_DIR = demo();
      try {
        const { id } = await doneTour();
        const v2 = text(id, "new");
        expect(await post(id, 7, v2)).toMatchObject({ status: 409, body: { error: "stale" } });
        await c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version) values (${"R".repeat(22)}, ${id}, 'req-00000001', '["*"]'::jsonb, 1)`;
        expect(await call("GET", id)).toMatchObject({ status: 409, body: { error: "busy" } });
        expect(await post(id, 1, v2)).toMatchObject({ status: 409, body: { error: "busy" } });
        await c().pg`update trial_rebuilds set status = 'done' where job_id = ${id}`;
        await c().pg`update trial_jobs set result_expires_at = now() - interval '1 minute' where id = ${id}`;
        expect(await call("GET", id)).toMatchObject({ status: 410, body: { error: "expired" } });
        expect(await post(id, 1, v2)).toMatchObject({ status: 410 });
        expect((await list("7")).body.jobs).toEqual([]);
        expect(await c().row(id)).toMatchObject({ bundle_version: 1 });
        const { id: lost } = await doneTour();                          // задание готово, а файла версии на сервере нет
        await fs.rename(path.join(c().dir, lost, "bundle-1.json"), path.join(c().dir, lost, "moved.json"));
        expect(await call("GET", lost)).toMatchObject({ status: 409, body: { error: "no_bundle" } });
        const { id: fresh } = await c().seed();                         // после doneTour: тот берёт голову очереди
        expect(await call("GET", fresh)).toMatchObject({ status: 409, body: { error: "not_ready" } });
        expect(await call("GET", "N".repeat(22))).toMatchObject({ status: 404 });
        expect(await call("GET", id, undefined, false)).toMatchObject({ status: 401 });
        expect((await list("7", false)).status).toBe(401);
        expect((await list("0")).status).toBe(400);
        expect((await list("x")).status).toBe(400);
      } finally {
        delete process.env.DEMO_DIR;
        await fs.rm(demo(), { recursive: true, force: true });
      }
    });

    it("версия проверяется как у воркера (чужое задание — 422); витрину не закрепить — версия принята, warning", async () => {
      process.env.DEMO_DIR = demo();
      try {
        const { id } = await doneTour();
        expect(await post(id, 1, text("O".repeat(22), "x"))).toMatchObject({ status: 422, body: { error: "wrong_job" } });
        process.env.DEMO_DIR = path.join(demo(), "missing");
        const v2 = text(id, "new");
        expect(await post(id, 1, v2)).toMatchObject({ status: 200, body: { version: 3, release: "failed", warning: "release_pin_failed" } });
        expect(await c().row(id)).toMatchObject({ bundle_version: 3 });
      } finally {
        delete process.env.DEMO_DIR;
        await fs.rm(demo(), { recursive: true, force: true });
      }
    });
  });
}
