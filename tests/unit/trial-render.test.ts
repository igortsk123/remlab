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
  it("товар — `sid` (/demo) или пара `msid`+`name` (тур); оба сразу, ни одного, `msid` без имени — отказ (T-20261117-20/3)", () => {
    const it = (o: object) => trialRenderIn.safeParse({ ...REQ, items: [{ role: "диван", x: 1, y: 2, ...o }] }).success;
    expect(it({ sid: "s1" })).toBe(true);
    expect(it({ msid: "m1", name: "Диван" })).toBe(true);
    expect(it({ sid: "s1", msid: "m1", name: "Диван" })).toBe(false);
    expect(it({})).toBe(false);
    expect(it({ msid: "m1" })).toBe(false);
    expect(it({ name: "Ковёр" })).toBe(true);                      // заглушка без модели: `msid` нет — ключ имя
    expect(it({ msid: "m1", name: "" })).toBe(false);
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
  it("тур: карточки без sid — по паре (msid, name); разные карточки одной пары попадают в срез обе (сервер откажет), одинаковые — один раз", () => {
    const mk = (msid: string, name: string, extra: object = {}) => ({ msid, name, w: 100, d: 50, h: 80, price: 1, ...extra });
    const tour = { apartment_id: "a1", build: "b1", room: { w: 400, d: 300 }, rules: {}, rooms_geo: { living: { w: 400, d: 300 } },
      variants: [{ id: "v1", room_id: "living", items: [{ role: "диван", x: 1, y: 1, sku: mk("m1", "Диван А", { colour: "серый" }) }], decor: [{ role: "шторы", sku: mk("m3", "Шторы") }] },
                 { id: "v2", room_id: "living", items: [{ role: "диван", x: 1, y: 1, sku: mk("m1", "Диван А", { colour: "красный" }) }] }],
      feeds: { диван: [mk("m1", "Диван А", { colour: "серый" }), mk("m9", "Диван Б")] } };
    const src = reduceSource(JSON.stringify(tour), { variant_id: "v1", room_id: "living", items: [{ role: "диван", msid: "m9", name: "Диван Б", x: 1, y: 1 }] })!;
    const skus = src._skus as { msid: string; name: string; colour?: string }[];
    expect(skus.filter((s) => s.msid === "m9")).toHaveLength(1);                         // товар замены — из ленты тура
    expect(skus.filter((s) => s.msid === "m3")).toHaveLength(1);                         // декор варианта
    const sofa = skus.filter((s) => s.msid === "m1" && s.name === "Диван А");
    expect(sofa).toHaveLength(1);                                                         // v1 и лента: одна и та же карточка — один раз
    const amb = reduceSource(JSON.stringify(tour), { variant_id: "v1", room_id: "living", items: [{ role: "диван", msid: "m1", name: "Диван А", x: 1, y: 1 }] })!;
    expect((amb._skus as { msid: string }[]).filter((s) => s.msid === "m1")).toHaveLength(2);   // заказ называет пару с двумя разными карточками — в срез обе: сервис увидит и откажет `bad_item`
    expect(JSON.stringify(src)).not.toContain('"sid"');                                   // sid наружу не выходит: его в данных тура нет
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
