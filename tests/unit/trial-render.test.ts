import { describe, expect, it } from "vitest";
import { trialPhotoIn, trialRenderIn } from "@/contracts/trial";
import { askRender, reduceSource, renderPayload, type RenderSend } from "@/lib/trial/repo-render";

// Рендер «Сделать фото» из тура (T-20261117-19/1): контракт тела, вырезка данных для сервиса кадров, проверки до сервиса, отказы с кодом и сроком.
// Данные задания и сервис кадров подменены — Postgres и сети нет.

const sku = (sid: string) => ({ sid, msid: sid, name: `Товар ${sid}`, w: 100, d: 50, h: 80, img: `img/${sid}.jpg` });
const bundle = {
  apartment_id: "a1", build: "b1", room: { w: 400, d: 300 }, rules: { soft_roles: ["плед"], other: "x".repeat(2000) },
  rooms_geo: { living: { w: 400, d: 300 }, "bedroom-1": { w: 300, d: 300 } },
  apartment_rooms: [{ id: "living", photo_ok: true }, { id: "bedroom-1", photo_ok: false }],
  variants: [
    { id: "v1", room_id: "living", style: "сканди", items: [{ role: "диван", x: 1, y: 1, w: 100, d: 50, h: 80, sku: sku("s1") }], decor: [{ role: "шторы", sku: sku("c1") }], cams: [] },
    { id: "v2", room_id: "living", style: "лофт", items: [{ role: "стул", x: 1, y: 1, w: 40, d: 40, h: 80, sku: sku("s2") }], decor: [] },
  ],
  sets: [{ items: [sku("swap1")] }],
};
const json = JSON.stringify(bundle);
const load = async () => ({ version: 1, json });
const REQ = { mode: "render" as const, v: 1 as const, variant_id: "v1", room_id: "living", room: { w: 400, d: 300 } };

describe("рендер из тура: контракт тела", () => {
  it("принимает минимальный заказ и полный (предметы, две позы), лишнее отбрасывает", () => {
    expect(trialRenderIn.safeParse(REQ).success).toBe(true);
    const full = trialRenderIn.parse({ ...REQ, items: [{ role: "диван", sid: "s1", x: 1, y: 2, rot: 90, extra: 1 }],
      cams: [{ name: "C1", x: 1, y: 2, rot: 3, fov: 90 }, { name: "C2", x: 4, y: 5, rot: 6, fov: 90, pose: 3, pshift: -0.04 }], hack: "x" });
    expect(full).not.toHaveProperty("hack");
    expect(full.items?.[0]).not.toHaveProperty("extra");
  });
  it("отклоняет чужую версию, кривой номер варианта, не-число, одну позу, лишние предметы", () => {
    expect(trialRenderIn.safeParse({ ...REQ, v: 2 }).success).toBe(false);
    expect(trialRenderIn.safeParse({ ...REQ, variant_id: "../x" }).success).toBe(false);
    expect(trialRenderIn.safeParse({ ...REQ, items: [{ role: "диван", sid: "s1", x: "1", y: 2 }] }).success).toBe(false);
    expect(trialRenderIn.safeParse({ ...REQ, cams: [{ name: "C1", x: 1, y: 2, rot: 3, fov: 90 }] }).success).toBe(false);
    expect(trialRenderIn.safeParse({ ...REQ, items: Array.from({ length: 41 }, () => ({ role: "а", sid: "s1", x: 1, y: 1 })) }).success).toBe(false);
  });
  it("заказ фото нейросети (без mode) не принимается как рендер и по-прежнему разбирается своей схемой", () => {
    const old = { room_id: "living", views: [{ camera: "C1", id: "a".repeat(64) }, { camera: "C2", id: "b".repeat(64) }], room: { w: 400, d: 300 },
      items: [{ role: "диван" }], render_key: "e".repeat(32) };
    expect(trialRenderIn.safeParse(old).success).toBe(false);
    expect(trialPhotoIn.safeParse(old).success).toBe(true);
    expect(trialPhotoIn.parse(old)).toHaveProperty("render_key");           // «Улучшить из рендера» проходит к сервису как есть
  });
});

describe("рендер из тура: данные для сервиса кадров", () => {
  it("вырезает один вариант и его товары, ещё нужные заказу (замена), без лишних правил и наборов", () => {
    const src = reduceSource(json, { variant_id: "v1", room_id: "living", items: [{ role: "диван", sid: "swap1", x: 1, y: 1 }] })!;
    const variants = src.variants as { id: string; items: unknown[] }[];
    expect(variants[0]?.id).toBe("v1");
    expect((src._skus as { sid: string }[]).map((s) => s.sid).sort()).toEqual(["c1", "s1", "swap1"]);
    expect(src.rules).toEqual({ soft_roles: ["плед"] });
    expect(src.rooms_geo).toEqual({ living: { w: 400, d: 300 } });
    expect(variants[1]).toEqual({ id: "v2", room_id: "living", items: [{ role: "стул" }] });          // роли чужих вариантов — для проверки роли, без товаров
    expect(JSON.stringify(src).length).toBeLessThan(json.length);
  });
  it("нет варианта — null; битые данные — null", () => {
    expect(reduceSource(json, { variant_id: "нет", room_id: "living" })).toBeNull();
    expect(reduceSource("{", { variant_id: "v1", room_id: "living" })).toBeNull();
  });
  it("тело сервису: без mode, с номером тура и данными", () => {
    const p = renderPayload("t".repeat(22), trialRenderIn.parse(REQ), { a: 1 });
    expect(p).toMatchObject({ v: 1, variant_id: "v1", trial: "t".repeat(22), source_data: { a: 1 } });
    expect(p).not.toHaveProperty("mode");
  });
});

describe("рендер из тура: заказ", () => {
  const ok: RenderSend = async () => ({ status: 200, body: { job: "j-1", kind: "render", eta: 600 } });
  const id = "t".repeat(22);
  it("принят: данные задания срезаны и ушли сервису, брони и квоты фото нейросети нет", async () => {
    const sent: Record<string, unknown>[] = [];
    const r = await askRender(id, trialRenderIn.parse(REQ), "10.0.0.7", async (p, ip) => { sent.push({ ...p, ip }); return ok(p, ip); }, load);
    expect(r).toMatchObject({ ok: true, status: 200, body: { job: "j-1" } });
    expect(sent[0]).toMatchObject({ trial: id, variant_id: "v1", ip: "10.0.0.7" });
  });
  it("проверка хеша (check): ответ без задания принимается, флаг уходит сервису; без check такой ответ — отказ", async () => {
    const chk: RenderSend = async () => ({ status: 200, body: { check: true, scene_hash: "a".repeat(64), cached: false } });
    const sent: Record<string, unknown>[] = [];
    const r = await askRender(id, trialRenderIn.parse({ ...REQ, check: true }), "", async (p, ip) => { sent.push(p); return chk(p, ip); }, load);
    expect(r).toMatchObject({ ok: true, body: { scene_hash: "a".repeat(64), cached: false } });
    expect(sent[0]).toMatchObject({ check: true });
    expect(await askRender(id, trialRenderIn.parse(REQ), "", chk, load)).toMatchObject({ ok: false });
  });
  it("нет доверия к размерам комнаты — 403 до сервиса; размеры не совпали — 409; срок вышел — 410; не готово — 409", async () => {
    const never: RenderSend = async () => { throw new Error("сервис не должен вызываться"); };
    expect(await askRender(id, trialRenderIn.parse({ ...REQ, room_id: "bedroom-1", variant_id: "v1" }), "", never, load)).toMatchObject({ ok: false, status: 403, error: "photo_not_allowed" });
    expect(await askRender(id, trialRenderIn.parse({ ...REQ, room: { w: 999, d: 300 } }), "", never, load)).toMatchObject({ ok: false, status: 409, error: "stale" });
    expect(await askRender(id, trialRenderIn.parse(REQ), "", never, async () => "expired")).toMatchObject({ ok: false, status: 410 });
    expect(await askRender(id, trialRenderIn.parse(REQ), "", never, async () => "not_ready")).toMatchObject({ ok: false, status: 409, error: "not_ready" });
  });
  it("неизвестный вариант — 404 с парой RU/EN до сервиса", async () => {
    const r = await askRender(id, trialRenderIn.parse({ ...REQ, variant_id: "v9" }), "", async () => { throw new Error("нет"); }, load);
    expect(r).toMatchObject({ ok: false, status: 404, error: "unknown_variant" });
    expect(r.ok === false && r.message && r.messageEn).toBeTruthy();
  });
  it("отказ сервиса — его код, текст пары и срок повтора как есть; молчание сервиса — 503 render_unavailable", async () => {
    const busy: RenderSend = async () => ({ status: 503, retryAfter: 120, body: { code: "render_busy", error: "Очередь заполнена", error_en: "Queue full", retry_after: 120 } });
    expect(await askRender(id, trialRenderIn.parse(REQ), "", busy, load)).toMatchObject({ ok: false, status: 503, error: "render_busy", message: "Очередь заполнена", messageEn: "Queue full", retryAfter: 120 });
    const silent: RenderSend = async () => ({ status: 503, body: null });
    expect(await askRender(id, trialRenderIn.parse(REQ), "", silent, load)).toMatchObject({ ok: false, status: 503, error: "render_unavailable" });
    const snapshotNo: RenderSend = async () => ({ status: 422, body: { code: "bad_item", error: "Товара нет", error_en: "No product" } });
    expect(await askRender(id, trialRenderIn.parse(REQ), "", snapshotNo, load)).toMatchObject({ ok: false, status: 422, error: "bad_item" });
  });
});
