import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type postgresT from "postgres";

import { sampleResult } from "./_trial-helpers";

// Промежуточные версии данных страницы на НАСТОЯЩЕЙ Postgres (agent-trial-08, задача А; T-20261109-21): аренда, манифест, 304/404/410, сроки.
// Подключается внутрь `describe` файла trial-claim.test.ts: тот чистит `trial_jobs` перед каждым тестом, отдельный файл шёл бы параллельно с ним.

type Ctx = {
  pg: ReturnType<typeof postgresT>;
  repo: typeof import("@/lib/trial/repo-worker");
  seed: () => Promise<{ id: string }>;
  row: (id: string) => Promise<Record<string, unknown>>;
  expire: (id: string) => Promise<unknown>;
  dir: string;
  token: string;
};

const geo = { w: 400, d: 300, title: "Гостиная", openings: [{ kind: "door", wall: "south", offset_cm: 10, width_cm: 80 }], radiators: [] };
export const bundleOf = (id: string, over: Record<string, unknown> = {}): Record<string, unknown> => ({
  trial: { job_id: id }, room: geo, rooms_geo: { living: geo }, apartment_rooms: [{ id: "living", furniture_state: "pending", furniture_text: null }],
  variants: [{ id: "trial-living", room_id: "living", style: "scandi", items: [], pending: true, furniture_state: "pending" }],
  feeds: {}, rules: {}, quiz: { questions: [{ id: "style" }] }, ...over,
});
const PIN_OK = async (): Promise<"exists"> => "exists"; // закрепление страницы — своим тестом ниже
const sha = (s: string) => createHash("sha256").update(s).digest("hex");
const ids = (id: string) => ({ params: Promise.resolve({ id }) });

export function bundleDbTests(c: () => Ctx): void {
  describe("данные страницы задания", () => {
    const pub = (await_: { id: string; attempt: number; leaseToken: string }, n = 1) => {
      const json = JSON.stringify(bundleOf(await_.id, { rev: n }));
      return import("@/lib/trial/repo-bundle").then((m) => m.publishBundle(await_, json, sha(json), c().dir, PIN_OK));
    };
    const started = async () => {
      const { id } = await c().seed();
      const a = (await c().repo.claim("w1"))!;
      return { id, attempt: 1, leaseToken: a.leaseToken };
    };
    const listing = (id: string) => fs.readdir(path.join(c().dir, id)).catch(() => [] as string[]);
    const get = async (id: string, headers: Record<string, string> = {}) => {
      const { GET } = await import("@/app/api/trial/[id]/bundle/route");
      return GET(new Request("http://app/x", { headers }), ids(id));
    };
    const post = async (body: unknown, auth = `Bearer ${c().token}`) => {
      const { POST } = await import("@/app/api/trial/worker/bundle/route");
      return POST(new Request("http://app/x", { method: "POST", headers: { authorization: auth }, body: JSON.stringify(body) }));
    };

    it("миграция повторяется без ошибки, поля на месте", async () => {
      const text = await fs.readFile(path.join(process.cwd(), "db/init/023-trial-bundle.sql"), "utf8");
      await c().pg.unsafe(text);
      await c().pg.unsafe(text);
      const got = await c().pg`select column_name from information_schema.columns where table_name = 'trial_jobs' and column_name like 'bundle_%'`;
      expect(got.map((r) => r.column_name).sort()).toEqual(["bundle_hash", "bundle_version"]);
    });

    it("пустая → с мебелью: версия растёт, задание идёт; итог не сбрасывает данные страницы", async () => {
      const f = await started();
      expect(await pub(f, 1)).toEqual({ version: 1, repeated: false, release: "exists" });
      expect(await pub(f, 2)).toEqual({ version: 2, repeated: false, release: "exists" });
      expect(await c().row(f.id)).toMatchObject({ status: "running", bundle_version: 2, result_version: 2 });
      await c().repo.acceptResult(f, JSON.stringify(sampleResult()), "r".repeat(64));
      expect(await c().row(f.id)).toMatchObject({ status: "done", bundle_version: 2, result_version: 3 });
      expect(JSON.parse(await (await get(f.id)).text())).toMatchObject({ rev: 2 });
    });

    it("версии неизменяемые: прежняя цела, старше двух убрана", async () => {
      const f = await started();
      for (const n of [1, 2, 3]) await pub(f, n);
      expect((await listing(f.id)).sort()).toEqual(["bundle-2.json", "bundle-3.json"]);
      expect(JSON.parse(await fs.readFile(path.join(c().dir, f.id, "bundle-2.json"), "utf8"))).toMatchObject({ rev: 2 });
    });

    it("повтор того же содержимого — без новой версии и без файла", async () => {
      const f = await started();
      await pub(f, 1);
      expect(await pub(f, 1)).toEqual({ version: 1, repeated: true, release: "exists" });
      expect(await listing(f.id)).toEqual(["bundle-1.json"]);
      expect(await c().row(f.id)).toMatchObject({ bundle_version: 1, result_version: 1 });
    });

    it("чужая аренда: старый токен после перехвата, просроченная, задание завершено — отказ и ни одного файла", async () => {
      const f = await started();
      await c().expire(f.id);
      expect(await pub(f, 1)).toBe("lease_lost");
      expect(await listing(f.id)).toEqual([]);
      const b = (await c().repo.claim("w2"))!;
      expect(await pub(f, 2)).toBe("lease_lost");
      const g = { id: f.id, attempt: 2, leaseToken: b.leaseToken };
      expect(await pub(g, 3)).toEqual({ version: 1, repeated: false, release: "exists" });
      expect(await pub(f, 4)).toBe("lease_lost");
      expect(await listing(f.id)).toEqual(["bundle-1.json"]);
      await c().repo.acceptResult(g, JSON.stringify(sampleResult()), "r".repeat(64));
      expect(await pub(g, 5)).toBe("lease_lost");
      expect(await c().row(f.id)).toMatchObject({ bundle_version: 1 });
    });

    it("одновременные публикации: номера разные, манифест — на последней", async () => {
      const f = await started();
      const out = await Promise.all([1, 2, 3].map((n) => pub(f, n)));
      const nums = out.map((o) => (o === "lease_lost" ? 0 : o.version)).sort();
      expect(nums).toEqual([1, 2, 3]);
      expect(await c().row(f.id)).toMatchObject({ bundle_version: 3, result_version: 3 });
    });

    it("файл не записался — версия прежняя, новая публикация проходит", async () => {
      const f = await started();
      await fs.writeFile(path.join(c().dir, f.id), "занято файлом");
      await expect(pub(f, 1)).rejects.toThrow();
      expect(await c().row(f.id)).toMatchObject({ bundle_version: 0, result_version: 0 });
      await fs.rm(path.join(c().dir, f.id));
      expect(await pub(f, 1)).toEqual({ version: 1, repeated: false, release: "exists" });
    });

    it("чтение: нет задания / ещё нет данных — 404, версия и 304, заголовки, неисправный id", async () => {
      const f = await started();
      expect((await get("A".repeat(22))).status).toBe(404);
      expect((await get("../../etc")).status).toBe(404);
      const none = await get(f.id);
      expect([none.status, (await none.json()).error]).toEqual([404, "not_ready"]);
      await pub(f, 1);
      const r = await get(f.id);
      expect(r.status).toBe(200);
      expect(r.headers.get("etag")).toBe('"v1"');
      expect(r.headers.get("cache-control")).toBe("private, no-store");
      expect(r.headers.get("x-robots-tag")).toContain("noindex");
      const same = await get(f.id, { "if-none-match": '"v1"' });
      expect([same.status, await same.text()]).toEqual([304, ""]);
      await pub(f, 2);
      expect((await get(f.id, { "if-none-match": '"v1"' })).status).toBe(200);
    });

    it("единая функция чтения: не готово, версия + текст, снято по сроку", async () => {
      const { latestBundle } = await import("@/lib/trial/repo-bundle");
      const f = await started();
      expect(await latestBundle("../x", c().dir)).toBe("not_ready");
      expect(await latestBundle("A".repeat(22), c().dir)).toBe("not_ready");
      expect(await latestBundle(f.id, c().dir)).toBe("not_ready");
      await pub(f, 1);
      await pub(f, 2);
      const got = await latestBundle(f.id, c().dir);
      expect(got !== "not_ready" && got !== "expired" && [got.version, JSON.parse(got.json).rev]).toEqual([2, 2]);
      await c().repo.acceptResult(f, JSON.stringify(sampleResult()), "r".repeat(64));
      await c().pg`update trial_jobs set result_expires_at = now() - interval '1 minute' where id = ${f.id}`;
      expect(await latestBundle(f.id, c().dir)).toBe("expired");
    });

    it("симлинк на месте файла версии не читается", async () => {
      const f = await started();
      await pub(f, 1);
      const p = path.join(c().dir, f.id, "bundle-1.json");
      await fs.rm(p);
      await fs.symlink("/etc/hostname", p);
      expect((await get(f.id)).status).toBe(404);
    });

    it("ручка воркера: токен, аренда, хеш, форма, чужое задание, размер", async () => {
      const f = await started();
      const text = JSON.stringify(bundleOf(f.id));
      const ok = { ...f, bundle: text, sha256: sha(text) };
      expect((await post(ok, "Bearer wrong")).status).toBe(401);
      expect((await post({ ...ok, sha256: "0".repeat(64) })).status).toBe(422);
      expect((await post({ ...ok, leaseToken: "x".repeat(40) })).status).toBe(409);
      const other = JSON.stringify(bundleOf("B".repeat(22)));
      expect(await (await post({ ...ok, bundle: other, sha256: sha(other) })).json()).toMatchObject({ error: "wrong_job" });
      const noVariants = JSON.stringify(bundleOf(f.id, { variants: [] }));
      expect(await (await post({ ...ok, bundle: noVariants, sha256: sha(noVariants) })).json()).toMatchObject({ error: "invalid_bundle" });
      const big = JSON.stringify(bundleOf(f.id, { pad: "x".repeat(8 * 1024 * 1024) }));
      expect((await post({ ...ok, bundle: big, sha256: sha(big) })).status).toBe(413);
      expect(await listing(f.id)).toEqual([]);
      expect(await (await post(ok)).json()).toMatchObject({ ok: true, version: 1, repeated: false });
    });

    it("первая принятая версия закрепляет страницу тура (один раз); сбой закрепления — warning, версия данных не теряется", async () => {
      const demo = path.join(c().dir, "..", `demo-${process.pid}`);
      await fs.mkdir(path.join(demo, "lib"), { recursive: true });
      await fs.writeFile(path.join(demo, "index.html"), "<html><head></head><body>tour</body></html>");
      await fs.writeFile(path.join(demo, "lib", "scene.json"), JSON.stringify({ file: "scene.abc123.js" }));
      await fs.writeFile(path.join(demo, "lib", "scene.abc123.js"), "// scene");
      await fs.writeFile(path.join(demo, "rt-meshes.json"), "{}");
      const { publishBundle } = await import("@/lib/trial/repo-bundle");
      const { ensureJobRelease } = await import("@/lib/trial/tour-bundle");
      const pin = (id: string, d?: string) => ensureJobRelease(id, d, demo);
      const text = (id: string, n: number) => JSON.stringify(bundleOf(id, { rev: n }));
      const f = await started();
      expect(await publishBundle(f, text(f.id, 1), sha(text(f.id, 1)), c().dir, pin)).toMatchObject({ version: 1, release: "pinned" });
      const rel = (await fs.readFile(path.join(c().dir, f.id, "release"), "utf8")).trim();
      expect(rel).toMatch(/^[a-f0-9]{32}$/);
      expect(await publishBundle(f, text(f.id, 2), sha(text(f.id, 2)), c().dir, pin)).toMatchObject({ version: 2, release: "exists" });
      expect((await fs.readFile(path.join(c().dir, f.id, "release"), "utf8")).trim()).toBe(rel);

      const g = await started();
      const boom = async (): Promise<never> => { throw new Error("no showcase"); };
      expect(await publishBundle(g, text(g.id, 1), sha(text(g.id, 1)), c().dir, boom)).toMatchObject({ version: 1, release: "failed" });
      expect(await c().row(g.id)).toMatchObject({ bundle_version: 1 });
      process.env.DEMO_DIR = path.join(demo, "missing");
      const t2 = text(g.id, 2);
      const viaRoute = await post({ ...g, bundle: t2, sha256: sha(t2) });
      expect(await viaRoute.json()).toMatchObject({ ok: true, version: 2, warning: "release_pin_failed" });
      process.env.DEMO_DIR = demo;
      const t3 = text(g.id, 3);
      expect(await (await post({ ...g, bundle: t3, sha256: sha(t3) })).json()).toEqual({ ok: true, version: 3, repeated: false });
      expect((await fs.readFile(path.join(c().dir, g.id, "release"), "utf8")).trim()).toBe(rel);
      delete process.env.DEMO_DIR;
      await fs.rm(demo, { recursive: true, force: true });
    });

    it("срок: папка удаляется, 410; неудача удаления — повтор уборкой сирот; папка живого задания цела", async () => {
      const { db } = await import("@/lib/db");
      const { trialRetention } = await import("@/lib/trial/retention");
      const f = await started();
      await pub(f, 1);
      await c().repo.acceptResult(f, JSON.stringify(sampleResult()), "r".repeat(64));
      await c().pg`update trial_jobs set expires_at = now() - interval '1 minute' where id = ${f.id}`;
      const live = await started();
      await pub(live, 1);
      // файл по своему сроку (по умолчанию держим, пока жив тур, — `_trial-source-db.ts`)
      await db().transaction((tx) => trialRetention(tx, new Date(), { ...process.env, TRIAL_KEEP_SOURCE_FOR_TOUR: "0" }));
      expect((await c().row(f.id)).input_path).toBeNull();
      expect((await get(f.id)).status).toBe(200);

      await c().pg`update trial_jobs set result_expires_at = now() - interval '1 minute' where id = ${f.id}`;
      expect((await get(f.id)).status).toBe(410);
      const failing = (async () => { throw new Error("EACCES"); }) as unknown as typeof fs.rm;
      const first = await db().transaction((tx) => trialRetention(tx, new Date(), process.env, failing));
      expect(first.find((x) => x.kind === "trial_bundles")).toMatchObject({ deleted: 0, kept: 1 });
      expect(await c().row(f.id)).toMatchObject({ status: "expired", bundle_version: 0, bundle_hash: null });
      expect(await listing(f.id)).toEqual(["bundle-1.json"]);
      expect((await get(f.id)).status).toBe(410);

      const later = new Date(Date.now() + 2 * 3_600_000); // уборка сирот берёт папки старше часа
      await c().pg`update trial_jobs set created_at = now() where id = ${live.id}`;
      await db().transaction((tx) => trialRetention(tx, later));
      expect(await listing(f.id)).toEqual([]);
      expect(await listing(live.id)).toEqual(["bundle-1.json"]);
    });
  });
}
