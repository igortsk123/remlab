import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type postgresT from "postgres";

import { bundleOf } from "./_trial-bundle-db";
import { sampleResult } from "./_trial-helpers";

// «Перечитать планировку» на НАСТОЯЩЕЙ Postgres (план trial-reparse-01; T-20261111-02): постановка оператором (ключ воркера, не агент;
// вне суточных лимитов), claim с ИСХОДНЫМ текстом объявления и точными байтами текущей версии, лист под арендой, публикация с `result`
// («та же версия» — только при обоих хэшах), карта перечитанного плана (снятые комнаты, правки агента на новых номерах), нейтральный
// статус агенту, исход для скрипта оператора. Подключается внутрь `describe` файла trial-claim.test.ts (тот чистит таблицы).

type Ctx = {
  pg: ReturnType<typeof postgresT>;
  repo: typeof import("@/lib/trial/repo-worker");
  seed: () => Promise<{ id: string }>;
  row: (id: string) => Promise<Record<string, unknown>>;
  dir: string;
  token: string;
};

const sha = (s: string) => createHash("sha256").update(s).digest("hex");
const PIN = async (): Promise<"exists"> => "exists";
const SKILLS = { workerId: "w-new", rebuilds: true, listing: true, edit: true, reparse: true };
type Lease = { id: string; attempt: number; leaseToken: string };

export function reparseDbTests(c: () => Ctx): void {
  describe("«Перечитать планировку» (оператор)", () => {
    const W = () => import("@/lib/trial/repo-rebuild-worker");
    /** Готовый тур: версия 1 опубликована, результат принят (seed кладёт текст объявления «SECRET-LISTING 4.0 x 3.0»). */
    const doneTour = async () => {
      const { id } = await c().seed();
      const a = (await c().repo.claim(`w-${id}`))!;
      const f = { id, attempt: a.attempt, leaseToken: a.leaseToken };
      const v1 = JSON.stringify(bundleOf(id, { rev: "old" }));
      const { publishBundle } = await import("@/lib/trial/repo-bundle");
      await publishBundle(f, v1, sha(v1), c().dir, PIN);
      const res = JSON.stringify(sampleResult());
      await c().repo.acceptResult(f, res, sha(res));
      return { id, v1, res };
    };
    const call = async (method: "GET" | "POST", url: string, body?: unknown, auth = true) => {
      const mod = await import("@/app/api/trial/worker/reparse/route");
      const req = new Request(`http://app${url}`, { method, headers: auth ? { authorization: `Bearer ${c().token}` } : {},
        ...(body ? { body: JSON.stringify(body) } : {}) });
      const r = await (method === "GET" ? mod.GET(req) : mod.POST(req));
      return { status: r.status, body: (await r.json()) as Record<string, unknown> };
    };
    const ask = (jobId: string, requestId = "reparse-0001", auth = true) => call("POST", "/api/trial/worker/reparse", { jobId, requestId }, auth);
    const claimVia = async (b: Record<string, unknown>) => {
      const { POST } = await import("@/app/api/trial/worker/claim/route");
      const r = await POST(new Request("http://app/x", { method: "POST", headers: { authorization: `Bearer ${c().token}` }, body: JSON.stringify(b) }));
      return ((await r.json()) as { rebuild?: Record<string, unknown> | null }).rebuild ?? null;
    };
    const leaseOf = (g: Record<string, unknown>): Lease => ({ id: g.id as string, attempt: g.attempt as number, leaseToken: g.leaseToken as string });
    const view = async (id: string) => (await (await import("@/lib/trial/repo-public")).jobView(id)) as Record<string, unknown>;
    const publish = async (b: Record<string, unknown>) => {
      const { POST } = await import("@/app/api/trial/worker/rebuild/publish/route");
      const r = await POST(new Request("http://app/x", { method: "POST", headers: { authorization: `Bearer ${c().token}` }, body: JSON.stringify(b) }));
      return { status: r.status, body: (await r.json()) as Record<string, unknown> };
    };
    /** Тур с поставленной и взятой пересборкой `reparse`. */
    const leased = async () => {
      const t = await doneTour();
      await ask(t.id);
      const got = (await claimVia(SKILLS))!;
      return { ...t, got, lease: leaseOf(got) };
    };

    it("миграции 025/028/031 повторяются и при живой строке reparse (набор видов один во всех трёх)", async () => {
      const { id } = await doneTour();
      expect((await ask(id)).status).toBe(202);
      for (const f of ["025-trial-listing-text.sql", "028-trial-room-edits.sql", "031-trial-reparse.sql"]) {
        await c().pg.unsafe(await fs.readFile(path.join(process.cwd(), "db/init", f), "utf8"));
      }
      expect(await c().pg`select kind, status, base_version from trial_rebuilds where job_id = ${id}`)
        .toEqual([{ kind: "reparse", status: "queued", base_version: 1 }]);
    });

    it("постановка: только ключ воркера; повтор — та же строка; busy / not_ready / source_gone / expired / 404", async () => {
      const { id } = await doneTour();
      expect((await ask(id, "reparse-0001", false)).status).toBe(401);
      const first = await ask(id);
      expect(first).toMatchObject({ status: 202, body: { ok: true, repeated: false, rebuild: { status: "queued" } } });
      expect((await ask(id)).body).toMatchObject({ repeated: true, rebuild: first.body.rebuild });
      expect(await ask(id, "reparse-0002")).toMatchObject({ status: 409, body: { error: "busy" } });
      await c().pg`update trial_rebuilds set status = 'done' where job_id = ${id}`;
      await c().pg`update trial_jobs set input_path = null where id = ${id}`;
      expect(await ask(id, "reparse-0003")).toMatchObject({ status: 410, body: { error: "source_gone" } });
      await c().pg`update trial_jobs set result_expires_at = now() - interval '1 minute' where id = ${id}`;
      expect(await ask(id, "reparse-0004")).toMatchObject({ status: 410, body: { error: "expired" } });
      expect((await ask("Z".repeat(22))).status).toBe(404);
      expect((await call("POST", "/api/trial/worker/reparse", { jobId: id, requestId: "x" })).status).toBe(400);
      const { id: running } = await c().seed();
      expect(await ask(running)).toMatchObject({ status: 409, body: { error: "not_ready" } });
    });

    it("вне суточного лимита агента: «перечитать» не тратит его ни у «Обустроить», ни у текста", async () => {
      const { id } = await doneTour();
      for (const n of [1, 2, 3]) await c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version, kind, status)
        values (${`rp${n}`}, ${id}, ${`reparse-000${n}`}, '[]', 1, 'reparse', 'done')`;
      process.env.TRIAL_REBUILD_DAILY = "1";
      const { editKeyHash } = await import("@/lib/trial/edit-key");
      await c().pg`update trial_jobs set edit_key_hash = ${editKeyHash("K".repeat(22))} where id = ${id}`;
      const { askListing } = await import("@/lib/trial/repo-listing");
      expect(await askListing(id, { k: "K".repeat(22), request_id: "txt-00000001", text: "кухня 3 на 4" }))
        .toMatchObject({ ok: true, repeated: false });
      delete process.env.TRIAL_REBUILD_DAILY;
    });

    it("claim: только воркеру с reparse; исходный текст объявления, вид листа, точные байты текущей версии; база — версия на claim", async () => {
      const { id, v1 } = await doneTour();
      await ask(id);
      expect(await claimVia({ ...SKILLS, reparse: undefined })).toBeNull();
      expect(await claimVia({ ...SKILLS, edit: false })).toBeNull(); // reparse — только вместе с правками агента
      // перевыпуск между постановкой и claim: база — то, что на странице сейчас
      await c().pg`update trial_jobs set bundle_version = 1 where id = ${id}`;
      const got = (await claimVia(SKILLS))!;
      expect(got).toMatchObject({ jobId: id, kind: "reparse", listingText: "SECRET-LISTING 4.0 x 3.0", inputMime: "image/png",
        baseVersion: 1, bundle: v1, edits: [], openingEdits: [] });
      const { GET } = await import("@/app/api/trial/worker/rebuild/[id]/input/route");
      const l = leaseOf(got);
      const r = await GET(new Request("http://app/x", { headers: { authorization: `Bearer ${c().token}`, "x-trial-attempt": String(l.attempt),
        "x-trial-lease": l.leaseToken } }), { params: Promise.resolve({ id: l.id }) });
      expect(r.status).toBe(200); // лист — под арендой reparse
      expect(await view(id)).toMatchObject({ tourUpdate: "applying", rebuild: null, listing: null, roomEdit: null });
    });

    it("публикация: новый result вместе с версией; та же страница и тот же result — без новой версии; новый result — новая версия", async () => {
      const { id, lease } = await leased();
      const out = JSON.stringify(bundleOf(id, { rev: "new" }));
      const res2 = sampleResult({ scale: { status: "listing", ppm: 41.5, inliers: 1, n: 1 } });
      const pub = { ...lease, jobId: id, bundle: out, sha256: sha(out), result: res2, reparse: { released: [], rooms: [], openings: [] } };
      const r = await publish(pub);
      expect(r).toMatchObject({ status: 200, body: { ok: true, repeated: false } });
      const v = r.body.version as number;
      const [j] = await c().pg`select result_hash, bundle_version from trial_jobs where id = ${id}`;
      expect(j).toEqual({ result_hash: sha(JSON.stringify(res2)), bundle_version: v });
      expect(await view(id)).toMatchObject({ tourUpdate: null, bundleVersion: v });
      // второй проход тем же кодом: страница и result те же → `same`, версии нет
      await ask(id, "reparse-0002");
      const two = leaseOf((await claimVia(SKILLS))!);
      expect((await publish({ ...pub, ...two })).body).toMatchObject({ ok: true, repeated: true, version: v });
      // страница та же, а канон другой → всё равно новая версия (иначе страница и result разошлись бы)
      await ask(id, "reparse-0003");
      const three = leaseOf((await claimVia(SKILLS))!);
      const res3 = sampleResult({ scale: { status: "verified", ppm: 40, inliers: 3, n: 3 } });
      expect((await publish({ ...pub, ...three, result: res3 })).body).toMatchObject({ ok: true, repeated: false, version: v + 1 });
    });

    it("карта: снятые комнаты заменяются новыми id; правки комнат и проёмов — на новые номера (обмен номерами двух правок)", async () => {
      const { id, lease } = await leased();
      await c().pg`update trial_jobs set released_rooms = '["bedroom-2", "living"]' where id = ${id}`;
      for (const [src, name] of [["r1", "Гостиная"], ["r2", "Спальня"]] as const) {
        await c().pg`insert into trial_room_edits (job_id, room_key, panel, src_id, anchor, name, kind, built, request_id)
          values (${id}, ${`p0|${src}`}, 'p0', ${src}, '{"x":0.5,"y":0.5}', ${name}, 'living', true, ${`re-${src}-0001`})`;
      }
      await c().pg`insert into trial_opening_edits (job_id, op_key, panel, src_idx, src_c, kind, c, width_cm, built, request_id)
        values (${id}, 'p0|s3', 'p0', 3, '[10, 20]', 'door', '[12, 20]', 80, true, 'oe-00000001')`;
      const out = JSON.stringify(bundleOf(id, { rev: "map" }));
      const map = {
        released: ["bedroom-1", "living"],
        rooms: [{ panel: "p0", from: "r1", to: "r2", anchor: { x: 0.2, y: 0.3 } }, { panel: "p0", from: "r2", to: "r1", anchor: { x: 0.7, y: 0.6 } }],
        openings: [{ panel: "p0", key: "s3", to: "s1", srcIdx: 1, srcC: [11, 21], c: [13, 21] }],
      };
      expect((await publish({ ...lease, jobId: id, bundle: out, sha256: sha(out), reparse: map })).status).toBe(200);
      expect((await c().row(id)).released_rooms).toEqual(["bedroom-1", "living"]);
      expect(await c().pg`select room_key, src_id, name, anchor from trial_room_edits where job_id = ${id} order by room_key`).toEqual([
        { room_key: "p0|r1", src_id: "r1", name: "Спальня", anchor: { x: 0.7, y: 0.6 } },
        { room_key: "p0|r2", src_id: "r2", name: "Гостиная", anchor: { x: 0.2, y: 0.3 } },
      ]);
      expect(await c().pg`select op_key, src_idx, src_c, c from trial_opening_edits where job_id = ${id}`)
        .toEqual([{ op_key: "p0|s1", src_idx: 1, src_c: [11, 21], c: [13, 21] }]);
    });

    it("карта и result — только у reparse: у «Обустроить» — result_unexpected, ничего не записано", async () => {
      const { id } = await doneTour();
      await c().pg`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version) values ('rbF', ${id}, 'furnish-01', '["*"]', 1)`;
      const got = (await claimVia(SKILLS))!;
      expect(got.kind).toBe("furnish");
      const out = JSON.stringify(bundleOf(id, { rev: "f" }));
      expect(await publish({ ...leaseOf(got), jobId: id, bundle: out, sha256: sha(out), reparse: { released: [], rooms: [], openings: [] } }))
        .toMatchObject({ status: 422, body: { error: "result_unexpected" } });
      expect((await c().row(id)).bundle_version).toBe(1);
    });

    it("сбой сторожа: тур прежний, агенту — ничего (без кода); оператору — код и разбор по id пересборки", async () => {
      const { id, lease } = await leased();
      const w = await W();
      expect(await w.failRebuild({ ...lease, code: "regress", retryable: false, detail: "p0/Спальня: площадь 12.0 → 7.0" })).toBe("failed");
      expect(await view(id)).toMatchObject({ tourUpdate: null, rebuild: null, rebuildError: null, bundleVersion: 1 });
      const st = await call("GET", `/api/trial/worker/reparse?id=${lease.id}`);
      expect(st).toMatchObject({ status: 200, body: { ok: true, jobId: id, status: "failed", error: "regress",
        detail: "p0/Спальня: площадь 12.0 → 7.0", version: null } });
      expect((await call("GET", `/api/trial/worker/reparse?id=${lease.id}`, undefined, false)).status).toBe(401);
      expect((await call("GET", "/api/trial/worker/reparse?id=nope")).status).toBe(404);
    });

    it("исходник пробного прогона: результат, байты версии, правки, исходный текст и вид листа (самого листа нет)", async () => {
      const { id, v1 } = await doneTour();
      const { GET } = await import("@/app/api/trial/worker/reparse/[id]/route");
      const get = async (auth = true) => {
        const r = await GET(new Request("http://app/x", { headers: auth ? { authorization: `Bearer ${c().token}` } : {} }),
          { params: Promise.resolve({ id }) });
        return { status: r.status, body: (await r.json()) as Record<string, unknown> };
      };
      expect((await get(false)).status).toBe(401);
      expect(await get()).toMatchObject({ status: 200, body: { ok: true, jobId: id, version: 1, bundle: v1, listingText: "SECRET-LISTING 4.0 x 3.0",
        inputMime: "image/png", hasSource: true, released: [], edits: [], openingEdits: [] } });
      await c().pg`update trial_jobs set released_rooms = '["living"]' where id = ${id}`;
      expect((await get()).body.released).toEqual(["living"]);
    });
  });
}
