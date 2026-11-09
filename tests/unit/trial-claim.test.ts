import { promises as fs } from "node:fs";
import path from "node:path";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import type postgresT from "postgres";

import { bundleDbTests } from "./_trial-bundle-db";
import { rebuildDbTests } from "./_trial-rebuild-db";
import { png, sampleResult } from "./_trial-helpers";

// Очередь пробы на НАСТОЯЩЕЙ Postgres (agent-trial-01, T-A; поправки Codex 09.11): гонки claim, ограждение аренды
// (reclaim против старых heartbeat/result/fail, ABA с тем же worker_id, граница истечения, исчерпание попыток), повтор
// result, конкурентный допуск в очередь, ошибка БД при записи, публичный вид без секретов, ручки целиком, сроки хранения.
// Гоняется только при TEST_DATABASE_URL (CI — сервис postgres; локально — временный контейнер), иначе пропускается.
const URL = process.env.TEST_DATABASE_URL;
const DIR = path.join(process.cwd(), ".vitest", `trial-db-${process.pid}`);
const TOKEN = "w".repeat(40);

type Lib = {
  repo: typeof import("@/lib/trial/repo-worker");
  create: typeof import("@/lib/trial/repo-create");
  pub: typeof import("@/lib/trial/repo-public");
  token: typeof import("@/lib/token");
};
let L: Lib;
let pg: ReturnType<typeof postgresT>;

const ENV_KEYS = ["TRIAL_QUEUE_MAX", "TRIAL_DAILY_CAP"] as const;
const lsDir = async () => (await fs.readdir(DIR).catch(() => [] as string[])).sort();
const row = async (id: string) => (await pg`select * from trial_jobs where id = ${id}`)[0]!;
const expire = (id: string, sec = 1) => pg`update trial_jobs set lease_until = now() - make_interval(secs => ${sec}) where id = ${id}`;

async function seed(listing = "SECRET-LISTING 4.0 x 3.0") {
  const id = L.token.randomToken();
  const partPath = path.join(DIR, `${id}.part`);
  await fs.writeFile(partPath, png(100));
  const v = await L.create.commitUpload({ partPath, mime: "image/png", bytes: 100, inputHash: "h".repeat(64), listing }, id, DIR);
  return { id, v };
}

describe.skipIf(!URL)("очередь пробы (real postgres)", () => {
  beforeAll(async () => {
    process.env.DATABASE_URL = URL;
    process.env.TRIAL_DIR = DIR;
    process.env.TRIAL_WORKER_TOKEN = TOKEN;
    const postgres = (await import("postgres")).default;
    pg = postgres(URL!, { max: 2, onnotice: () => undefined });
    // прод-схема целиком, кроме 002 (таблицу projects параллельно создаёт pg-repository.test — гонка create if not exists)
    const initDir = path.join(process.cwd(), "db/init");
    await pg.begin(async (tx) => {
      await tx`select pg_advisory_xact_lock(2026110999)`;
      for (const f of (await fs.readdir(initDir)).filter((n) => /^\d{3}-.*\.sql$/.test(n) && !n.startsWith("002-")).sort()) {
        await tx.unsafe(await fs.readFile(path.join(initDir, f), "utf8"));
      }
    });
    L = {
      repo: await import("@/lib/trial/repo-worker"),
      create: await import("@/lib/trial/repo-create"),
      pub: await import("@/lib/trial/repo-public"),
      token: await import("@/lib/token"),
    };
  });

  beforeEach(async () => {
    await pg`delete from trial_jobs`;
    await pg`delete from trial_workers`;
    await pg`delete from rate_limits where key like 'trial%'`;
    await fs.rm(DIR, { recursive: true, force: true });
    await fs.mkdir(DIR, { recursive: true });
    for (const k of ENV_KEYS) delete process.env[k];
  });

  afterAll(async () => {
    await pg?.end();
    await fs.rm(DIR, { recursive: true, force: true });
    delete process.env.DATABASE_URL;
  });

  it("два одновременных claim → одно задание; 20 claim на 5 заданий → 5 разных, без дублей", async () => {
    process.env.TRIAL_QUEUE_MAX = "50";
    const { id } = await seed();
    const two = await Promise.all([L.repo.claim("w1"), L.repo.claim("w2")]);
    expect(two.filter(Boolean).map((j) => j!.id)).toEqual([id]);
    await pg`delete from trial_jobs`;
    for (let i = 0; i < 5; i++) await seed();
    const got = (await Promise.all(Array.from({ length: 20 }, (_, i) => L.repo.claim(`w${i}`)))).filter(Boolean);
    expect(got).toHaveLength(5);
    expect(new Set(got.map((j) => j!.id)).size).toBe(5);
    expect(got.every((j) => j!.attempt === 1 && j!.leaseToken.length >= 30)).toBe(true);
  });

  it("просроченная аренда возвращается: attempt 2, новый токен; старый heartbeat — потерян", async () => {
    const { id } = await seed();
    const a = (await L.repo.claim("w1"))!;
    await expire(id);
    const b = (await L.repo.claim("w2"))!;
    expect(b).toMatchObject({ id, attempt: 2 });
    expect(b.leaseToken).not.toBe(a.leaseToken);
    expect(await L.repo.heartbeat({ id, attempt: a.attempt, leaseToken: a.leaseToken, stage: "raster" })).toBeNull();
    expect(await L.repo.heartbeat({ id, attempt: b.attempt, leaseToken: b.leaseToken, stage: "raster" })).not.toBeNull();
  });

  it("граница истечения: аренда ещё жива — не забрать, heartbeat продлевает; на миг истекла — забрать, heartbeat не оживляет", async () => {
    const { id } = await seed();
    const a = (await L.repo.claim("w1"))!;
    await pg`update trial_jobs set lease_until = now() + interval '2 seconds' where id = ${id}`;
    expect(await L.repo.claim("w2")).toBeNull();
    const hb = await L.repo.heartbeat({ id, attempt: 1, leaseToken: a.leaseToken, stage: "labels" });
    expect(new Date(hb!.leaseUntil).getTime()).toBeGreaterThan(Date.now() + 50_000);
    await pg`update trial_jobs set lease_until = now() - interval '1 millisecond' where id = ${id}`;
    expect(await L.repo.heartbeat({ id, attempt: 1, leaseToken: a.leaseToken, stage: "walls" })).toBeNull();
    expect((await row(id)).stage).toBe("labels");
    expect((await L.repo.claim("w2"))?.attempt).toBe(2);
  });

  it("reclaim одновременно со старыми heartbeat/result/fail — старые отвергнуты, задание у нового", async () => {
    const { id } = await seed();
    const a = (await L.repo.claim("w1"))!;
    await expire(id);
    const old = { id, attempt: a.attempt, leaseToken: a.leaseToken };
    const res = JSON.stringify(sampleResult());
    const [b, hb, rs, fl] = await Promise.all([
      L.repo.claim("w2"), L.repo.heartbeat({ ...old, stage: "walls" }), L.repo.acceptResult(old, res, "x".repeat(64)),
      L.repo.failJob({ ...old, code: "pipeline_error", retryable: false }),
    ]);
    expect(b?.attempt).toBe(2);
    expect([hb, rs, fl]).toEqual([null, "lease_lost", "lease_lost"]);
    expect(await row(id)).toMatchObject({ status: "running", attempt: 2, worker_id: "w2", result: null });
  });

  it("ABA: тот же worker_id забрал задание снова — запросы прошлой аренды отвергнуты в любой комбинации", async () => {
    const { id } = await seed();
    const a = (await L.repo.claim("same"))!;
    await expire(id);
    const b = (await L.repo.claim("same"))!;
    for (const f of [{ attempt: 1, leaseToken: a.leaseToken }, { attempt: 2, leaseToken: a.leaseToken }, { attempt: 1, leaseToken: b.leaseToken }]) {
      expect(await L.repo.heartbeat({ id, ...f, stage: "walls" })).toBeNull();
      expect(await L.repo.acceptResult({ id, ...f }, "{}", "y".repeat(64))).toBe("lease_lost");
    }
    expect(await L.repo.heartbeat({ id, attempt: 2, leaseToken: b.leaseToken, stage: "walls" })).not.toBeNull();
  });

  it("исчерпание попыток: ровно два claim; третий — нет, задание failed/lease_lost, страница видит код", async () => {
    const { id } = await seed();
    await L.repo.claim("w1"); await expire(id);
    await L.repo.claim("w1"); await expire(id);
    expect(await L.repo.claim("w1")).toBeNull();
    const r = await row(id);
    expect(r).toMatchObject({ status: "failed", error_code: "lease_lost", attempt: 2 });
    expect(r.expires_at).not.toBeNull();
    const v = await L.pub.jobView(id);
    expect(v !== "expired" && v?.errorCode).toBe("lease_lost");
  });

  it("повтор того же result после потерянного ответа — 200 (again), другой результат — 409", async () => {
    const { id } = await seed();
    const a = (await L.repo.claim("w1"))!;
    const f = { id, attempt: 1, leaseToken: a.leaseToken };
    expect(await L.repo.acceptResult(f, '{"a":1}', "1".repeat(64))).toBe("ok");
    expect(await L.repo.acceptResult(f, '{"a":1}', "1".repeat(64))).toBe("again");
    expect(await L.repo.acceptResult(f, '{"a":2}', "2".repeat(64))).toBe("lease_lost");
    expect(await row(id)).toMatchObject({ status: "done", stage: "done", result_version: 1, result: { a: 1 } });
  });

  it("fail: повторяемый → в очередь с паузой; waiting_capacity попытку не тратит; последняя попытка/неповторяемый → failed", async () => {
    const { id } = await seed();
    let a = (await L.repo.claim("w1"))!;
    expect(await L.repo.failJob({ id, attempt: 1, leaseToken: a.leaseToken, code: "waiting_capacity", retryable: true, retryAfterSec: 1 }))
      .toBe("queued");
    expect(await row(id)).toMatchObject({ status: "queued", attempt: 0, lease_token: null, error_code: null });
    expect(await L.repo.claim("w1")).toBeNull(); // пауза ещё не вышла
    await pg`update trial_jobs set next_run_at = now() where id = ${id}`;
    a = (await L.repo.claim("w1"))!;
    expect(a.attempt).toBe(1);
    expect(await L.repo.failJob({ id, attempt: 1, leaseToken: a.leaseToken, code: "vlm_error", retryable: true, detail: "429 from gateway" }))
      .toBe("queued");
    await pg`update trial_jobs set next_run_at = now() where id = ${id}`;
    a = (await L.repo.claim("w1"))!;
    expect(await L.repo.failJob({ id, attempt: 2, leaseToken: a.leaseToken, code: "vlm_error", retryable: true })).toBe("failed");
    expect(await row(id)).toMatchObject({ status: "failed", error_code: "vlm_error" });
    const { id: id2 } = await seed();
    const c = (await L.repo.claim("w1"))!;
    expect(await L.repo.failJob({ id: id2, attempt: 1, leaseToken: c.leaseToken, code: "pdf_unreadable", retryable: false })).toBe("failed");
  });

  it("heartbeat: шаги с временем от прода, тот же шаг не дублируется; потраченное не уменьшается", async () => {
    const { id } = await seed();
    const a = (await L.repo.claim("w1"))!;
    const f = { id, attempt: 1, leaseToken: a.leaseToken };
    await L.repo.heartbeat({ ...f, stage: "raster" });
    await L.repo.heartbeat({ ...f, stage: "raster", spentUsd: 0.03 });
    await L.repo.heartbeat({ ...f, stage: "labels", spentUsd: 0.01 });
    const r = await row(id);
    expect((r.stages as { stage: string }[]).map((s) => s.stage)).toEqual(["raster", "labels"]);
    expect(Number(r.spent_usd)).toBeCloseTo(0.03);
  });

  it("конкурентная постановка не пробивает лимит очереди 5; отказанным — ни .part, ни файла", async () => {
    process.env.TRIAL_QUEUE_MAX = "5";
    const out = await Promise.all(Array.from({ length: 12 }, () => seed()));
    expect(out.filter((o) => o.v === "ok")).toHaveLength(5);
    expect(out.filter((o) => o.v === "busy")).toHaveLength(7);
    const names = await lsDir();
    expect(names).toHaveLength(5);
    expect(names.every((n) => n.endsWith(".png"))).toBe(true);
    expect((await pg`select count(*)::int as n from trial_jobs`)[0]!.n).toBe(5);
  });

  it("суточный потолок заданий (TRIAL_DAILY_CAP) — под тем же замком", async () => {
    process.env.TRIAL_QUEUE_MAX = "50";
    process.env.TRIAL_DAILY_CAP = "3";
    const out = await Promise.all(Array.from({ length: 6 }, () => seed()));
    expect(out.filter((o) => o.v === "ok")).toHaveLength(3);
    expect(out.filter((o) => o.v === "daily_cap")).toHaveLength(3);
    expect(await L.create.admissionPrecheck()).toBe("daily_cap");
  });

  it("ошибка БД при записи — исключение, на диске ни .part, ни файла", async () => {
    const g = globalThis as unknown as { __remlabDb?: unknown };
    const saved = g.__remlabDb;
    const postgres = (await import("postgres")).default;
    const { drizzle } = await import("drizzle-orm/postgres-js");
    g.__remlabDb = drizzle(postgres("postgres://x:y@127.0.0.1:1/none", { max: 1, connect_timeout: 2 }));
    try {
      await expect(seed()).rejects.toThrow();
    } finally {
      g.__remlabDb = saved;
    }
    expect(await lsDir()).toEqual([]);
  });

  it("публичный вид: без пути файла, текста, аренды, воркера, деталей ошибки; очередь — тем же условием, что claim", async () => {
    process.env.TRIAL_QUEUE_MAX = "50";
    const ids = [];
    for (let i = 0; i < 3; i++) ids.push((await seed()).id);
    const ahead = async (id: string) => { const v = await L.pub.jobView(id); return v === "expired" ? -1 : v?.queueAhead; };
    expect([await ahead(ids[0]!), await ahead(ids[1]!), await ahead(ids[2]!)]).toEqual([0, 1, 2]);
    const a = (await L.repo.claim("worker-secret-id"))!;
    expect([await ahead(ids[0]!), await ahead(ids[1]!), await ahead(ids[2]!)]).toEqual([null, 0, 1]);
    await L.repo.failJob({ id: a.id, attempt: 1, leaseToken: a.leaseToken, code: "pipeline_error", retryable: false, detail: "DETAIL-SECRET" });
    const v = await L.pub.jobView(a.id);
    const s = JSON.stringify(v);
    for (const bad of ["SECRET-LISTING", ".png", a.leaseToken, "worker-secret-id", "DETAIL-SECRET", "h".repeat(64)]) expect(s).not.toContain(bad);
    expect(v).toMatchObject({ status: "failed", errorCode: "pipeline_error", workerAlive: false });
  });

  it("ручки целиком: загрузка → вид → claim → файл → heartbeat → result → GET с ETag/304", async () => {
    const { POST: upload } = await import("@/app/api/trial/route");
    const { GET: view } = await import("@/app/api/trial/[id]/route");
    const { GET: result } = await import("@/app/api/trial/[id]/result/route");
    const { POST: claimR } = await import("@/app/api/trial/worker/claim/route");
    const { POST: hbR } = await import("@/app/api/trial/worker/heartbeat/route");
    const { POST: resR } = await import("@/app/api/trial/worker/result/route");
    const { GET: input } = await import("@/app/api/trial/worker/[id]/input/route");
    const auth = { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" };
    const jpost = (fn: (r: Request) => Promise<Response>, body: unknown) =>
      fn(new Request("http://app/x", { method: "POST", headers: auth, body: JSON.stringify(body) }));
    const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

    const fd = new FormData();
    const bytes = png(2048);
    fd.append("listing", "SECRET-LISTING");
    fd.append("consent", "yes");
    fd.append("file", new Blob([new Uint8Array(bytes)]), "plan.png");
    const up = await upload(new Request("http://app/api/trial", { method: "POST", body: fd, headers: { "x-forwarded-for": "9.9.9.1" } }));
    expect(up.status).toBe(201);
    expect(up.headers.get("referrer-policy")).toBe("no-referrer");
    const { id } = (await up.json()) as { id: string };
    expect(id).toMatch(L.token.TOKEN_RE);

    const v = await view(new Request("http://app/x"), ctx(id));
    expect(v.status).toBe(200);
    expect(v.headers.get("cache-control")).toBe("private, no-store");
    expect(((await v.json()) as { job: { status: string } }).job.status).toBe("queued");
    expect((await view(new Request("http://app/x"), ctx("../../etc/passwd"))).status).toBe(404);
    expect((await view(new Request("http://app/x"), ctx(L.token.randomToken()))).status).toBe(404);

    const c = await jpost(claimR, { workerId: "dev-1", version: "t08" });
    const job = ((await c.json()) as { job: { id: string; attempt: number; leaseToken: string; listingText: string } }).job;
    expect(job).toMatchObject({ id, attempt: 1, listingText: "SECRET-LISTING" });
    const vAlive = (await (await view(new Request("http://app/x"), ctx(id))).json()) as { job: { workerAlive: boolean; status: string } };
    expect(vAlive.job).toMatchObject({ workerAlive: true, status: "running" });

    const inReq = (lease: string, att = 1) => new Request("http://app/x", { headers: { authorization: `Bearer ${TOKEN}`, "x-trial-attempt": String(att), "x-trial-lease": lease } });
    const file = await input(inReq(job.leaseToken), ctx(id));
    expect(file.status).toBe(200);
    expect(file.headers.get("content-type")).toBe("image/png");
    expect(Buffer.from(await file.arrayBuffer()).equals(bytes)).toBe(true);
    expect((await input(inReq("z".repeat(32)), ctx(id))).status).toBe(409);

    const lease = { id, attempt: 1, leaseToken: job.leaseToken };
    expect((await jpost(hbR, { ...lease, stage: "walls" })).status).toBe(200);
    expect((await jpost(hbR, { ...lease, stage: "done" })).status).toBe(400);
    expect((await jpost(resR, { ...lease, result: { version: 1 } })).status).toBe(422);
    const huge = sampleResult({ flags: [], timings: Object.fromEntries(Array.from({ length: 200_000 }, (_, i) => [`k${i}`, i])) });
    expect((await jpost(resR, { ...lease, result: huge })).status).toBe(413);
    expect((await jpost(resR, { ...lease, result: sampleResult() })).status).toBe(200);
    const again = await jpost(resR, { ...lease, result: sampleResult() });
    expect(await again.json()).toMatchObject({ ok: true, repeated: true });
    expect((await jpost(resR, { ...lease, result: sampleResult({ costUsd: 0.05 }) })).status).toBe(409);

    const r1 = await result(new Request("http://app/x"), ctx(id));
    expect(r1.status).toBe(200);
    expect(r1.headers.get("etag")).toBe('"v1"');
    expect(((await r1.json()) as { result: { version: number } }).result.version).toBe(1);
    expect((await result(new Request("http://app/x", { headers: { "if-none-match": '"v1"' } }), ctx(id))).status).toBe(304);
  });

  it("загрузка: полная очередь — 503 ДО чтения тела; 4-я загрузка с адреса за 10 минут — 429", async () => {
    const { POST: upload } = await import("@/app/api/trial/route");
    const mk = (ip: string) => {
      const fd = new FormData();
      fd.append("consent", "yes");
      fd.append("file", new Blob([new Uint8Array(png(300))]), "p.png");
      return new Request("http://app/api/trial", { method: "POST", body: fd, headers: { "x-forwarded-for": ip } });
    };
    process.env.TRIAL_QUEUE_MAX = "1";
    expect((await upload(mk("9.9.9.2"))).status).toBe(201);
    const busy = await upload(mk("9.9.9.3"));
    expect(busy.status).toBe(503);
    expect(await busy.json()).toMatchObject({ error: "busy" });
    expect((await lsDir()).filter((n) => n.endsWith(".part"))).toEqual([]);
    process.env.TRIAL_QUEUE_MAX = "50";
    expect((await upload(mk("9.9.9.4"))).status).toBe(201);
    expect((await upload(mk("9.9.9.4"))).status).toBe(201);
    expect((await upload(mk("9.9.9.4"))).status).toBe(201);
    expect((await upload(mk("9.9.9.4"))).status).toBe(429);
    const foreign = new Request("http://app/api/trial", { method: "POST", headers: { origin: "https://evil.example", host: "app" } });
    expect((await upload(foreign)).status).toBe(403);
  });

  it("сроки: файл удалён — результат жив; затем результат → 410; ошибка unlink → ссылка остаётся и удаляется в следующий раз", async () => {
    const { runRetention } = await import("@/modules/retention/run");
    const { trialRetention } = await import("@/lib/trial/retention");
    const { db } = await import("@/lib/db");
    const { GET: result } = await import("@/app/api/trial/[id]/result/route");
    const { GET: view } = await import("@/app/api/trial/[id]/route");
    const ctx = (id: string) => ({ params: Promise.resolve({ id }) });
    process.env.TRIAL_QUEUE_MAX = "50";
    const { id } = await seed();
    const a = (await L.repo.claim("w1"))!;
    await L.repo.acceptResult({ id, attempt: 1, leaseToken: a.leaseToken }, JSON.stringify(sampleResult()), "r".repeat(64));
    const r0 = await row(id);
    const hrs = (new Date(r0.expires_at).getTime() - new Date(r0.finished_at).getTime()) / 3_600_000;
    const days = (new Date(r0.result_expires_at).getTime() - new Date(r0.finished_at).getTime()) / 86_400_000;
    expect([Math.round(hrs), Math.round(days)]).toEqual([24, 30]);

    await pg`update trial_jobs set expires_at = now() - interval '1 minute' where id = ${id}`;
    const failing = (async () => { throw new Error("EACCES"); }) as unknown as typeof fs.rm;
    const k = await db().transaction((tx) => trialRetention(tx, new Date(), process.env, failing));
    expect(k.find((x) => x.kind === "trial_files")).toMatchObject({ deleted: 0, kept: 1 });
    expect((await row(id)).input_path).not.toBeNull();
    expect(await lsDir()).toEqual([`${id}.png`]);

    await runRetention();
    const r1 = await row(id);
    expect(r1.input_path).toBeNull();
    expect(r1.input_deleted_at).not.toBeNull();
    expect(await lsDir()).toEqual([]);
    expect((await result(new Request("http://app/x"), ctx(id))).status).toBe(200);

    await pg`update trial_jobs set result_expires_at = now() - interval '1 minute' where id = ${id}`;
    await runRetention();
    expect((await result(new Request("http://app/x"), ctx(id))).status).toBe(410);
    expect((await view(new Request("http://app/x"), ctx(id))).status).toBe(410);
    expect(await row(id)).toMatchObject({ status: "expired", result: null, listing_text: null, input_hash: null });
  });

  it("сроки: зависшее задание → failed/stale; сироты .part и файлы без записи старше часа — удалены, свежие и свои — нет", async () => {
    const { runRetention } = await import("@/modules/retention/run");
    process.env.TRIAL_QUEUE_MAX = "50";
    const { id: stale } = await seed();
    const { id: live } = await seed();
    await pg`update trial_jobs set created_at = now() - interval '25 hours' where id = ${stale}`;
    const old = new Date(Date.now() - 2 * 3_600_000);
    const orphanPart = path.join(DIR, `${"P".repeat(22)}.part`), orphanFile = path.join(DIR, `${"O".repeat(22)}.jpg`);
    const freshPart = path.join(DIR, `${"F".repeat(22)}.part`);
    for (const f of [orphanPart, orphanFile, freshPart]) await fs.writeFile(f, "x");
    for (const f of [orphanPart, orphanFile, path.join(DIR, `${live}.png`)]) await fs.utimes(f, old, old);
    const res = await runRetention();
    expect(res?.find((r) => r.kind === "trial_stale")?.deleted).toBe(1);
    expect(res?.find((r) => r.kind === "trial_orphans")?.deleted).toBe(2);
    expect(await row(stale)).toMatchObject({ status: "failed", error_code: "stale" });
    expect(await lsDir()).toEqual([`${"F".repeat(22)}.part`, `${live}.png`, `${stale}.png`].sort());
  });

  it("база не примет кривое имя файла (traversal мимо кода)", async () => {
    await expect(pg`insert into trial_jobs (id, input_path, input_mime, input_bytes) values ('x', '../../etc/passwd', 'image/png', 1)`)
      .rejects.toThrow();
  });

  bundleDbTests(() => ({ pg, repo: L.repo, seed, row, expire, dir: DIR, token: TOKEN }));
  rebuildDbTests(() => ({ pg, repo: L.repo, seed, row, dir: DIR, token: TOKEN }));
});
