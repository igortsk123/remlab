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

    // ── T-20261112-115 Ф1: фото у тура — что снималось, завершение, чтение, ворота ──
    const CAMS = [{ name: "C2", x: 300, y: 50, rot: 200, fov: 60, pose: 3 }, { name: "C1", x: 10.4, y: 20, rot: 30, fov: 72, pose: 3,
      crop: { "1.333": { x: 0, y: 0.1, w: 1, h: 0.8, keep: ["sofa"] } } }];
    const meta = { stateId: "s2-" + "a".repeat(32), variant_id: "living-v1", style: "сканди", cams: CAMS };
    const JPG = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.alloc(300, 9)]);
    const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(300, 3)]);
    const KEY = "P".repeat(22);
    const keyed = async (id: string) => {
      const { editKeyHash } = await import("@/lib/trial/edit-key");
      await c().pg`update trial_jobs set edit_key_hash = ${editKeyHash(KEY)} where id = ${id}`;
    };
    const confirmTour = (id: string) => c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version, kind, progress)
        values (${"R" + id.slice(1)}, ${id}, 'req-confirm-1', '[]'::jsonb, 1, 'edit', '{"confirm": true}'::jsonb)`;
    const done = async (id: string, body: unknown, headers: Record<string, string> = { authorization: "Bearer " + "w".repeat(40) }) => {
      const { POST } = await import("@/app/api/trial/worker/[id]/photo/route");
      const r = await POST(new Request(`http://app/api/trial/worker/${id}/photo`, { method: "POST",
        headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(body) }), { params: Promise.resolve({ id }) });
      return { status: r.status, body: (await r.json()) as Record<string, unknown> };
    };
    const shotsBody = (job = "dj-1") => ({ draft_job: job, status: "done", shots: [
      { camera: "C1", img: JPG.toString("base64"), thumb: PNG.toString("base64") }, { camera: "C2", img: PNG.toString("base64") }] });
    const list = async (id: string, q = "") => {
      const { GET } = await import("@/app/api/trial/[id]/photos/route");
      const r = await GET(new Request(`http://app/api/trial/${id}/photos${q}`), { params: Promise.resolve({ id }) });
      return { status: r.status, body: (await r.json()) as { ok: boolean; shots?: Record<string, unknown>[]; error?: string } };
    };
    const tourFile = async (id: string, rel: string[], headers: Record<string, string> = {}) => {
      const { GET } = await import("@/app/try/[id]/tour/[[...path]]/route");
      return GET(new Request(`http://app/try/${id}/tour/${rel.join("/")}`, { headers }), { params: Promise.resolve({ id, path: rel }) });
    };

    it("миграция 034 повторяется; база держит статус, источник и «готово только с файлами»", async () => {
      const text = await fs.readFile(path.join(process.cwd(), "db/init/034-trial-photo-urls.sql"), "utf8");
      await c().pg.unsafe(text);
      await c().pg.unsafe(text);
      const id = await doneJob();
      // старая строка (до Ф1) — без статуса, и это законно
      await c().pg`insert into trial_photos (id, job_id, room_id, draft_job, status) values ('old1', ${id}, 'living', 'dj-old', null)`;
      await expect(c().pg`insert into trial_photos (id, job_id, room_id, status) values ('x1', ${id}, 'living', 'ready')`).rejects.toThrow();
      await expect(c().pg`insert into trial_photos (id, job_id, room_id, source) values ('x2', ${id}, 'living', 'robot')`).rejects.toThrow();
      await expect(c().pg`insert into trial_photos (id, job_id, room_id, status) values ('x3', ${id}, 'living', 'done')`).rejects.toThrow();
      expect((await c().pg`select status from trial_photos where id = 'old1'`)[0]!.status).toBeNull();
      await c().pg`insert into trial_photos (id, job_id, room_id) values ('x4', ${id}, 'living')`;
      expect((await c().pg`select status from trial_photos where id = 'x4'`)[0]!.status).toBe("queued");
    });

    it("заказ пишет, что снималось: вариант, стиль, состояние, позы с углом и их подпись; кто — агент по ключу, иначе покупатель", async () => {
      const id = await doneJob();
      await keyed(id);
      const sent: Sent = [];
      await ask(id, order(meta), sent);
      const [p] = await c().pg`select status, source, state_id, variant_id, style, quality, cams, cams_sig, draft_job from trial_photos where job_id = ${id}`;
      expect(p).toMatchObject({ status: "queued", source: "buyer", state_id: meta.stateId, variant_id: "living-v1", style: "сканди",
        quality: "realistic", draft_job: "dj-1", cams_sig: "C1:10,20,30,72,3;C2:300,50,200,60,3" });
      expect((p!.cams as { name: string }[]).map((x) => x.name)).toEqual(["C1", "C2"]);
      // ручка: `?k=` агента → agent; чужой ключ → buyer; кривые позы — без поз, заказ проходит
      const { POST } = await import("@/app/api/trial/[id]/photo/route");
      const { photoMeta } = await import("@/lib/trial/repo-photo");
      const { trialPhotoIn } = await import("@/contracts/trial");
      expect(photoMeta(trialPhotoIn.parse(order({ cams: [{ name: "C9", x: 1, y: 1 }], stateId: "../x" })))).toMatchObject({ cams: null, camsSig: null, stateId: null });
      const src = async (q: string) => {
        await c().pg`delete from trial_photos where job_id = ${id}`;
        const r = await POST(new Request(`http://app/api/trial/${id}/photo${q}`, { method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify(order(meta)) }), { params: Promise.resolve({ id }) });
        return { status: r.status, source: (await c().pg`select source from trial_photos where job_id = ${id}`)[0]?.source };
      };
      // сервис кадров в тесте недоступен — бронь снимается; источник проверяем на брони до вызова: подменяем сеть
      const realFetch = globalThis.fetch;
      globalThis.fetch = (async () => new Response(JSON.stringify({ job: "dj-9" }), { status: 200 })) as typeof fetch;
      try {
        expect(await src(`?k=${KEY}`)).toEqual({ status: 200, source: "agent" });
        expect(await src(`?k=${"Q".repeat(22)}`)).toEqual({ status: 200, source: "buyer" });
        expect(await src("")).toEqual({ status: 200, source: "buyer" });
      } finally {
        globalThis.fetch = realFetch;
      }
    });

    it("завершение: Bearer или внутренний ключ; файлы в папку тура, проверка, потом done; повтор безвреден; сбой — failed", async () => {
      const id = await doneJob();
      await ask(id, order(meta), []);
      expect((await done(id, shotsBody(), {})).status).toBe(401);
      expect((await done(id, shotsBody(), { authorization: "Bearer nope" })).status).toBe(401);
      expect((await done(id, shotsBody("dj-unknown"))).status).toBe(404);
      expect((await done("N".repeat(22), shotsBody())).status).toBe(404);
      expect((await done(id, { ...shotsBody(), shots: [{ camera: "C1", img: Buffer.from("%PDF-1.4" + "x".repeat(200)).toString("base64") }] }))
        .status).toBe(415);
      expect((await c().pg`select status from trial_photos where job_id = ${id}`)[0]!.status).toBe("queued");
      const prev = process.env.INTERNAL_API_TOKEN;
      process.env.INTERNAL_API_TOKEN = "i".repeat(40);
      try {
        expect(await done(id, shotsBody(), { "x-internal-token": "i".repeat(40) })).toMatchObject({ status: 200, body: { status: "done", repeated: false } });
      } finally {
        if (prev === undefined) delete process.env.INTERNAL_API_TOKEN; else process.env.INTERNAL_API_TOKEN = prev;
      }
      const [p] = await c().pg`select status, shots, done_at from trial_photos where job_id = ${id}`;
      const shots = p!.shots as { camera: string; file: string; thumb: string }[];
      expect(p!.status).toBe("done");
      expect(shots.map((s) => s.camera)).toEqual(["C1", "C2"]);
      expect(shots[0]!.file).toMatch(/^[a-f0-9]{16}\.jpg$/);
      expect(shots[0]!.thumb).toMatch(/^[a-f0-9]{16}\.t\.png$/);
      expect(shots[1]!.thumb).toBe(shots[1]!.file);
      expect(await fs.readFile(path.join(c().dir, id, "photos", shots[0]!.file))).toEqual(JPG);
      expect(await done(id, shotsBody())).toMatchObject({ status: 200, body: { repeated: true } });
      expect(await done(id, { draft_job: "dj-1", status: "failed", code: "no_credits" })).toMatchObject({ status: 200, body: { repeated: true } });
      expect((await c().pg`select status from trial_photos where job_id = ${id}`)[0]!.status).toBe("done");   // готовое не сбивается
      // другой заказ — сбой с кодом
      await ask(id, order(meta), [], { status: 200, body: { job: "dj-2" } });
      expect(await done(id, { draft_job: "dj-2", status: "failed", code: "no_credits" })).toMatchObject({ status: 200, body: { status: "failed" } });
      expect((await c().pg`select status, fail_code from trial_photos where draft_job = 'dj-2'`)[0]).toEqual({ status: "failed", fail_code: "no_credits" });
      // тур снят по сроку — 410
      await c().pg`update trial_jobs set result_expires_at = now() - interval '1 minute' where id = ${id}`;
      expect((await done(id, shotsBody())).status).toBe(410);
    });

    it("чтение: только done, адреса внутри тура; ворота как у тура — до подтверждения только ключ агента, после — всем", async () => {
      const id = await doneJob();
      await keyed(id);
      await ask(id, order(meta), []);
      await ask(id, order(meta), [], { status: 200, body: { job: "dj-2" } });       // не готово — не отдаётся
      await done(id, shotsBody());
      const agent = await list(id, `?k=${KEY}`);
      expect(agent.status).toBe(200);
      expect(agent.body.shots).toHaveLength(1);
      const s = agent.body.shots![0]!;
      expect(s).toMatchObject({ quality: "realistic", room_id: "living", variant_id: "living-v1", style: "сканди", stateId: meta.stateId, source: "buyer" });
      expect((s.cams as { name: string; fov: number }[]).map((x) => [x.name, x.fov])).toEqual([["C1", 72], ["C2", 60]]);
      const shots = s.shots as { camera: string; url: string; thumb: string }[];
      expect(shots[0]!.url).toMatch(new RegExp(`^/try/${id}/tour/photos/[a-f0-9]{16}\\.jpg$`));
      expect(typeof s.ts).toBe("number");
      // до подтверждения: нет ключа, чужой ключ — отказ; файл фото — тоже закрыт без ключа
      expect(await list(id)).toMatchObject({ status: 403, body: { error: "not_active" } });
      expect((await list(id, `?k=${"Q".repeat(22)}`)).status).toBe(403);
      const rel = shots[0]!.url.split("/tour/")[1]!.split("/");
      expect((await tourFile(id, rel)).status).toBe(403);
      // агент по cookie-пропуску (так грузит картинки страница агента) — открыт
      const { readPass } = await import("@/lib/trial/buyer-gate");
      const h = (await c().pg`select edit_key_hash from trial_jobs where id = ${id}`)[0]!.edit_key_hash as string;
      const withPass = await tourFile(id, rel, { cookie: `trial_tk=${readPass(id, h)}` });
      expect(withPass.status).toBe(200);
      expect(withPass.headers.get("content-type")).toBe("image/jpeg");
      expect(Buffer.from(await withPass.arrayBuffer())).toEqual(JPG);
      // после «Подтвердить планировку» — покупатель по ссылке без ключа
      await confirmTour(id);
      expect((await list(id)).body.shots).toHaveLength(1);
      expect((await tourFile(id, rel)).status).toBe(200);
      expect((await tourFile(id, ["photos", "0123456789abcdef.jpg"])).status).toBe(404);
      expect((await tourFile(id, ["photos", "..", "bundle-1.json"])).status).toBe(404);
      // нет задания — 404, снято по сроку — 410
      expect((await list("N".repeat(22))).status).toBe(404);
      await c().pg`update trial_jobs set result_expires_at = now() - interval '1 minute' where id = ${id}`;
      expect((await list(id)).status).toBe(410);
    });
  });
}
