import { promises as fs } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type postgresT from "postgres";

import { sampleResult } from "./_trial-helpers";

// Чертёж агента (T-20261112-52) на НАСТОЯЩЕЙ Postgres: миграция 033 повторяется, проверка имени превью; ручка воркера
// `POST /api/trial/worker/<id>/source` (Bearer, только WEBP, нет задания — 404, тур снят — 410); отдача из тура только по ключу агента
// (`app/try/[id]/tour/[[...path]]/route.ts` целиком: без ключа 404); сроки: продлили тур — исходник не удалён, превью уходит с результатом,
// превью-сирота убирается. Подключается внутрь `describe` trial-claim.test.ts (тот чистит таблицы и папку перед каждым тестом).

type Ctx = {
  pg: ReturnType<typeof postgresT>;
  repo: typeof import("@/lib/trial/repo-worker");
  seed: () => Promise<{ id: string }>;
  row: (id: string) => Promise<Record<string, unknown>>;
  dir: string;
  token: string;
};

const KEY = "S".repeat(22);
const WEBP = Buffer.concat([Buffer.from("RIFF\x10\x00\x00\x00WEBPVP8 ", "latin1"), Buffer.alloc(64, 7)]);

export function sourceDbTests(c: () => Ctx): void {
  describe("чертёж агента", () => {
    const done = async () => {
      const { id } = await c().seed();
      const a = (await c().repo.claim(`w-${id}`))!;
      await c().repo.acceptResult({ id, attempt: a.attempt, leaseToken: a.leaseToken }, JSON.stringify(sampleResult()), "r".repeat(64));
      const { editKeyHash } = await import("@/lib/trial/edit-key");
      await c().pg`update trial_jobs set edit_key_hash = ${editKeyHash(KEY)} where id = ${id}`;
      return id;
    };
    const post = async (id: string, body: unknown, auth = true) => {
      const { POST } = await import("@/app/api/trial/worker/[id]/source/route");
      return POST(new Request(`http://app/api/trial/worker/${id}/source`, { method: "POST", body: JSON.stringify(body),
        headers: { "content-type": "application/json", ...(auth ? { authorization: `Bearer ${c().token}` } : {}) } }),
      { params: Promise.resolve({ id }) });
    };
    const tour = async (id: string, rel: string[], q = "") => {
      const { GET } = await import("@/app/try/[id]/tour/[[...path]]/route");
      return GET(new Request(`http://app/try/${id}/tour/${rel.join("/")}${q}`), { params: Promise.resolve({ id, path: rel }) });
    };
    const b64 = WEBP.toString("base64");

    it("миграция 033 повторяется; база не примет кривое имя превью", async () => {
      const sqlText = await fs.readFile(path.join(process.cwd(), "db/init/033-trial-preview.sql"), "utf8");
      await c().pg.unsafe(sqlText);
      await c().pg.unsafe(sqlText);
      const id = await done();
      await expect(c().pg`update trial_jobs set preview_path = '../x.src.webp' where id = ${id}`).rejects.toThrow();
      await expect(c().pg`update trial_jobs set preview_path = ${`${id}.png`} where id = ${id}`).rejects.toThrow();
    });

    it("воркер кладёт превью: Bearer, только WEBP, нет задания — 404, тур снят — 410; агент видит, покупатель — нет", async () => {
      const id = await done();
      expect((await post(id, { id, webp: b64 }, false)).status).toBe(401);
      expect((await post(id, { id, webp: Buffer.from("%PDF-1.4 xxxxxxxxxxxx").toString("base64") })).status).toBe(415);
      expect((await post("N".repeat(22), { id: "N".repeat(22), webp: b64 })).status).toBe(404);
      expect((await post(id, { id: "N".repeat(22), webp: b64 })).status).toBe(404);
      expect((await post(id, { id, webp: b64 })).status).toBe(200);
      expect((await c().row(id)).preview_path).toBe(`${id}.src.webp`);
      expect(Buffer.from(await fs.readFile(path.join(c().dir, `${id}.src.webp`))).equals(WEBP)).toBe(true);
      const own = await tour(id, ["source"], `?k=${KEY}`);
      expect(own.status).toBe(200);
      expect(own.headers.get("content-type")).toBe("image/webp");
      expect((await tour(id, ["source", "file"], `?k=${KEY}`)).headers.get("content-type")).toBe("image/png");
      expect((await tour(id, ["source"])).status).toBe(404);
      expect((await tour(id, ["source", "file"])).status).toBe(404);
      await c().pg`update trial_jobs set result_expires_at = now() - interval '1 minute' where id = ${id}`;
      expect((await post(id, { id, webp: b64 })).status).toBe(410);
    });

    it("продлили тур (результат живёт дольше срока файла) → исходник и превью не удалены; снят тур — уходят вместе с ним", async () => {
      const id = await done();
      await post(id, { id, webp: b64 });
      const { trialRetention } = await import("@/lib/trial/retention");
      const { db } = await import("@/lib/db");
      const run = () => db().transaction((tx) => trialRetention(tx, new Date(), { ...process.env, TRIAL_KEEP_SOURCE_FOR_TOUR: undefined }));
      await c().pg`update trial_jobs set expires_at = now() - interval '1 minute', result_expires_at = now() + interval '10 days' where id = ${id}`;
      await run();
      expect((await c().row(id)).input_path).toBe(`${id}.png`);             // по умолчанию держим, пока жив тур
      expect((await tour(id, ["source", "file"], `?k=${KEY}`)).status).toBe(200);
      await c().pg`update trial_jobs set result_expires_at = now() - interval '1 minute' where id = ${id}`;
      await run();
      expect(await c().row(id)).toMatchObject({ status: "expired", input_path: null, preview_path: null });
      expect((await fs.readdir(c().dir)).filter((n) => n.startsWith(id))).toEqual([]);
      expect((await tour(id, ["source"], `?k=${KEY}`)).status).toBe(410);
    });

    it("исходник снят по своему сроку (переключатель 0) — «Открыть файл» 410, превью живо до конца тура", async () => {
      const id = await done();
      await post(id, { id, webp: b64 });
      const { trialRetention } = await import("@/lib/trial/retention");
      const { db } = await import("@/lib/db");
      await c().pg`update trial_jobs set expires_at = now() - interval '1 minute' where id = ${id}`;
      await db().transaction((tx) => trialRetention(tx, new Date(), { ...process.env, TRIAL_KEEP_SOURCE_FOR_TOUR: "0" }));
      expect((await c().row(id)).input_path).toBeNull();
      expect((await tour(id, ["source", "file"], `?k=${KEY}`)).status).toBe(410);
      expect((await tour(id, ["source"], `?k=${KEY}`)).status).toBe(200);
    });

    it("превью без строки (сирота старше часа) — убирается; своё — нет", async () => {
      const id = await done();
      await post(id, { id, webp: b64 });
      const orphan = path.join(c().dir, `${"O".repeat(22)}.src.webp`);
      await fs.writeFile(orphan, WEBP);
      const old = new Date(Date.now() - 2 * 3_600_000);
      for (const f of [orphan, path.join(c().dir, `${id}.src.webp`)]) await fs.utimes(f, old, old);
      const { runRetention } = await import("@/modules/retention/run");
      await runRetention();
      const names = await fs.readdir(c().dir);
      expect(names).toContain(`${id}.src.webp`);
      expect(names).not.toContain(`${"O".repeat(22)}.src.webp`);
    });
  });
}
