import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type postgresT from "postgres";

import { bundleOf } from "./_trial-bundle-db";
import { sampleResult } from "./_trial-helpers";

// Фото нейросети из тура на НАСТОЯЩЕЙ Postgres (agent-trial-08 § «Правило фото»; T-20261109-34): право по `photo_ok` последней версии,
// размеры страницы = данным, суточный предел на задание (и под гонкой двух нажатий), отказ сервиса кадров — без строки счёта, ручка —
// чужой сайт / кривое тело. Сервис кадров подменён (`send`): платных вызовов нет. Подключается внутрь `describe` trial-claim.test.ts.

type Ctx = {
  pg: ReturnType<typeof postgresT>;
  repo: typeof import("@/lib/trial/repo-worker");
  seed: () => Promise<{ id: string }>;
  dir: string;
};

const sha = (s: string) => createHash("sha256").update(s).digest("hex");
const geo = { w: 400, d: 300, title: "Комната", openings: [], radiators: [] };
const PIN = async (): Promise<"exists"> => "exists";
const VIEWS = [{ camera: "C1", id: "a".repeat(64) }, { camera: "C2", id: "b".repeat(64) }];
const order = (over: Record<string, unknown> = {}) => ({ room_id: "living", views: VIEWS, room: { w: 400, d: 300 },
  items: [{ role: "диван", x: 1, y: 1, msid: "1_a", img: "https://shop.example/a.jpg", price: 100 }], quality: "draft", ...over });
type Sent = { payload: Record<string, unknown>; ip: string }[];

export function photoDbTests(c: () => Ctx): void {
  describe("фото из тура", () => {
    /** Задание `done`, последняя версия: гостиная с доверием к размерам, спальня — без. */
    const doneJob = async (photoOk = true) => {
      const { id } = await c().seed();
      const a = (await c().repo.claim(`w-${id}`))!;
      const f = { id, attempt: a.attempt, leaseToken: a.leaseToken };
      const json = JSON.stringify(bundleOf(id, { rooms_geo: { living: geo, "bedroom-1": geo },
        apartment_rooms: [{ id: "living", furniture_state: "ready", furniture_text: null, photo_ok: photoOk },
          { id: "bedroom-1", furniture_state: "ready", furniture_text: null, photo_ok: false }] }));
      const { publishBundle } = await import("@/lib/trial/repo-bundle");
      await publishBundle(f, json, sha(json), c().dir, PIN);
      await c().repo.acceptResult(f, JSON.stringify(sampleResult()), "r".repeat(64));
      return id;
    };
    const ask = async (id: string, body: Record<string, unknown>, sent: Sent, reply = { status: 200, body: { job: "dj-1" } as Record<string, unknown> | null },
      env: Record<string, string> = {}) => {
      const { askPhoto } = await import("@/lib/trial/repo-photo");
      const { trialPhotoIn } = await import("@/contracts/trial");
      const send = async (payload: Record<string, unknown>, ip: string) => { sent.push({ payload, ip }); return reply; };
      return askPhoto(id, trialPhotoIn.parse(body), "10.0.0.7", send, c().dir, env as NodeJS.ProcessEnv);
    };
    const count = async (id: string) => (await c().pg`select count(*)::int as n from trial_photos where job_id = ${id}`)[0]!.n as number;

    it("миграция повторяется без ошибки", async () => {
      const text = await fs.readFile(path.join(process.cwd(), "db/init/026-trial-photos.sql"), "utf8");
      await c().pg.unsafe(text);
      await c().pg.unsafe(text);
    });

    it("комната с доверием → заказ в сервис кадров: реалистичное, в фон, метка задания, без полей магазина и без слов страницы", async () => {
      const id = await doneJob();
      const sent: Sent = [];
      expect(await ask(id, order({ trial: "Z".repeat(22), cost_label: "demo", no_registry: 0 }), sent)).toEqual({ ok: true, job: "dj-1" });
      expect(sent).toHaveLength(1);
      const p = sent[0]!.payload;
      expect(p).toMatchObject({ quality: "realistic", async: 1, trial: id, no_registry: 1, room_id: "living", views: VIEWS });
      expect(p.cost_label).toBeUndefined();
      expect((p.items as Record<string, unknown>[])[0]).toEqual({ role: "диван", x: 1, y: 1, msid: "1_a" });
      expect(sent[0]!.ip).toBe("10.0.0.7");
      expect(await c().pg`select room_id, draft_job from trial_photos where job_id = ${id}`).toEqual([{ room_id: "living", draft_job: "dj-1" }]);
    });

    it("без доверия, чужая комната, другие размеры, нет версии — отказ кодом и без заказа", async () => {
      const sent: Sent = [];
      const id = await doneJob(false);
      expect(await ask(id, order(), sent)).toMatchObject({ ok: false, status: 403, error: "photo_not_allowed" });
      const ok = await doneJob();
      expect(await ask(ok, order({ room_id: "bedroom-1" }), sent)).toMatchObject({ ok: false, status: 403, error: "photo_not_allowed" });
      expect(await ask(ok, order({ room_id: "kitchen-1" }), sent)).toMatchObject({ ok: false, status: 403, error: "photo_not_allowed" });
      expect(await ask(ok, order({ room: { w: 410, d: 300 } }), sent)).toMatchObject({ ok: false, status: 409, error: "stale" });
      expect(await ask(ok, order({ room: { w: 400.6, d: 299.5 } }), sent)).toMatchObject({ ok: true });   // ±1 см — те же размеры
      const { id: fresh } = await c().seed();
      expect(await ask(fresh, order(), sent)).toMatchObject({ ok: false, status: 409, error: "not_ready" });
      expect(sent).toHaveLength(1);
    });

    it("суточный предел на задание: N заказов, дальше 429 без вызова сервиса; старше суток не считается; гонка двух — не проскакивает", async () => {
      const id = await doneJob();
      const sent: Sent = [];
      const env = { TRIAL_PHOTO_DAILY: "2" };
      for (let i = 0; i < 2; i++) expect((await ask(id, order(), sent, undefined, env)).ok).toBe(true);
      expect(await ask(id, order(), sent, undefined, env)).toMatchObject({ ok: false, status: 429, error: "photo_limit" });
      expect(sent).toHaveLength(2);
      await c().pg`update trial_photos set created_at = now() - interval '25 hours' where job_id = ${id}`;
      const both = await Promise.all([ask(id, order(), sent, undefined, env), ask(id, order(), sent, undefined, env),
        ask(id, order(), sent, undefined, env)]);
      expect(both.filter((r) => r.ok)).toHaveLength(2);
      expect(both.filter((r) => !r.ok && r.error === "photo_limit")).toHaveLength(1);
      expect(await count(id)).toBe(4);
    });

    it("отказ сервиса кадров (нет денег, его предел, нет связи) — его код наружу, строки счёта нет; снятый результат — 410", async () => {
      const id = await doneJob();
      const sent: Sent = [];
      expect(await ask(id, order(), sent, { status: 402, body: { code: "no_credits", error: "нет денег" } }))
        .toMatchObject({ ok: false, status: 402, error: "no_credits", message: "нет денег" });
      expect(await ask(id, order(), sent, { status: 429, body: { code: "photo_limit", error: "предел" } }))
        .toMatchObject({ ok: false, status: 429, error: "photo_limit" });
      expect(await ask(id, order(), sent, { status: 503, body: null })).toMatchObject({ ok: false, status: 503, error: "draft_failed" });
      expect(await ask(id, order(), sent, { status: 200, body: { ok: true } })).toMatchObject({ ok: false, status: 502, error: "draft_failed" });
      expect(await count(id)).toBe(0);
      await c().pg`update trial_jobs set result_expires_at = now() - interval '1 minute' where id = ${id}`;
      expect(await ask(id, order(), sent)).toMatchObject({ ok: false, status: 410 });
    });

    it("ручка: чужой сайт — 403, кривое тело (1 кадр, нет комнаты) — 400, кривой id — 404, нет данных — 409, без доверия — 403 кодом", async () => {
      const { POST } = await import("@/app/api/trial/[id]/photo/route");
      const call = async (id: string, body: unknown, headers: Record<string, string> = {}) => {
        const r = await POST(new Request(`http://app/api/trial/${id}/photo`, { method: "POST", headers: { "content-type": "application/json", ...headers },
          body: JSON.stringify(body) }), { params: Promise.resolve({ id }) });
        return { status: r.status, body: (await r.json()) as Record<string, unknown> };
      };
      const id = await doneJob(false);
      expect((await call(id, order(), { origin: "https://evil.test" })).status).toBe(403);
      expect((await call(id, order({ views: VIEWS.slice(0, 1) }))).status).toBe(400);
      expect((await call(id, { ...order(), room_id: undefined })).status).toBe(400);
      expect((await call("bad", order())).status).toBe(404);
      expect(await call("A".repeat(22), order())).toMatchObject({ status: 409, body: { code: "not_ready" } });
      expect(await call(id, order())).toMatchObject({ status: 403, body: { ok: false, code: "photo_not_allowed" } });
      expect(await count(id)).toBe(0);
    });
  });
}
