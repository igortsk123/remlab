import { describe, expect, it, vi } from "vitest";

// Витрина — фикстура: в тестах сеть не трогаем
vi.mock("@/lib/partners/demo-data", async (orig) => ({
  ...(await orig<typeof import("@/lib/partners/demo-data")>()),
  loadDemoRaw: async () => ({ variants: [{ id: "set2", style: "сканди", items: [{ sku: { sid: "112923_1", name: "Диван А (витрина)", price: 51000, url: "https://xf.gdeslon.ru/a", shop: "divan.ru" } }] }] }),
}));

import { GET as GET_MANY, POST } from "@/app/api/collections/route";
import { GET, PATCH } from "@/app/api/collections/[id]/route";
import { currentPrices, priceIndex } from "@/lib/collections/prices";

// Коллекции (план b2b-05): сохранил → открыл по ссылке → те же предметы; цены при открытии — текущие,
// пропавший товар помечен, а не подменён (ADR-0254 п.6).

const body = {
  apartmentId: "flat215", baseVariant: "set2", style: "сканди", lang: "ru",
  items: [{ role: "диван", x: 120, y: 80, rot: 180, w: 200, d: 90, h: 80, sku: { sid: "112923_1", name: "Диван А", price: 50000 } }],
};
const post = (b: unknown) => new Request("http://x/api/collections", { method: "POST", headers: { "content-type": "application/json", "x-forwarded-for": "10.0.0.9" }, body: JSON.stringify(b) });

describe("коллекции", () => {
  // v3 (demo-16 шаг 2): комната и стиль обязательны и сверяются с квартирой и опубликованным вариантом; v1/v2 — как раньше
  it("v3: комната квартиры и стиль варианта; чужая комната, другой стиль и v3 без комнаты — 400; v2 без комнаты — гостиная", async () => {
    // свой адрес: шесть сохранений подряд не должны съесть лимит соседних тестов
    const post = (b: unknown) => new Request("http://x/api/collections", { method: "POST", headers: { "content-type": "application/json", "x-forwarded-for": "10.0.3.33" }, body: JSON.stringify(b) });
    const v3 = { ...body, schemaVersion: 3, roomId: "living", styleId: "scandi" };
    const ok = await POST(post(v3));
    expect(ok.status).toBe(200);
    const { id } = (await ok.json()) as { id: string };
    const c = ((await (await GET(new Request(`http://x/api/collections/${id}`), { params: Promise.resolve({ id }) })).json()) as { collection: Record<string, unknown> }).collection;
    expect(c).toMatchObject({ schemaVersion: 3, roomId: "living", styleId: "scandi" });
    const err = async (b: unknown) => ((await (await POST(post(b))).json()) as { error: string }).error;
    expect(await err({ ...v3, roomId: "attic" })).toBe("unknown_room");
    expect(await err({ ...v3, roomId: "kitchen" })).toBe("variant_mismatch");        // гостиная витрины не может быть кухней
    expect(await err({ ...v3, styleId: "loft" })).toBe("variant_mismatch");
    const { roomId: _r, ...noRoom } = v3;
    expect((await POST(post(noRoom))).status).toBe(400);
    const old = await POST(post({ ...body, schemaVersion: 2 }));
    const oid = ((await old.json()) as { id: string }).id;
    const oc = ((await (await GET(new Request(`http://x/api/collections/${oid}`), { params: Promise.resolve({ id: oid }) })).json()) as { collection: Record<string, unknown> }).collection;
    expect(oc.roomId).toBe("living");
  });

  // ЧТЕНИЕ ПАЧКОЙ (demo-19 А1): по одному запросу на коллекцию страница упиралась в лимит чтений, и часть избранного считалась
  // «без цены»; пачка отдаёт те же публичные снимки, несуществующих в ответе нет, номера проверяются
  it("пачка: те же снимки, что по одному; несуществующих нет; без хеша секрета; повторы убираются", async () => {
    const ids: string[] = [];
    const post = (b: unknown) => new Request("http://x/api/collections", { method: "POST", headers: { "content-type": "application/json", "x-forwarded-for": "10.0.7.9" }, body: JSON.stringify(b) });
    for (let k = 0; k < 3; k++) ids.push(((await (await POST(post({ ...body, items: [{ ...body.items[0], x: 100 + k }] }))).json()) as { id: string }).id);
    const ghost = "A".repeat(22);
    const many = (q: string) => GET_MANY(new Request(`http://x/api/collections?ids=${q}`, { headers: { "x-forwarded-for": "10.0.7.1" } }));
    const r = await many([...ids, ids[0], ghost].join(","));
    expect(r.status).toBe(200);
    const j = (await r.json()) as { ok: boolean; collections: Record<string, unknown>[] };
    expect(j.collections.map((c) => c.id).sort()).toEqual([...ids].sort());
    const one = ((await (await GET(new Request(`http://x/api/collections/${ids[1]}`), { params: Promise.resolve({ id: ids[1]! }) })).json()) as { collection: unknown }).collection;
    expect(j.collections.find((c) => c.id === ids[1])).toEqual(one);
    expect(JSON.stringify(j)).not.toContain("editHash");
    expect(j.collections[0]!.current).toMatchObject({ "112923_1": { price: 51000, unavailable: false } });
  });

  it("пачка: мусор, пусто и больше 25 номеров — 400; лимит чтений — на запрос, а не на коллекцию", async () => {
    const many = (q: string | null, ip = "10.0.7.2") => GET_MANY(new Request(`http://x/api/collections${q === null ? "" : `?ids=${q}`}`, { headers: { "x-forwarded-for": ip } }));
    expect((await many(null)).status).toBe(400);
    expect((await many("")).status).toBe(400);
    expect((await many("../etc,passwd")).status).toBe(400);
    const id = (k: number) => String(k).padStart(22, "B");
    expect((await many(Array.from({ length: 26 }, (_, k) => id(k)).join(","))).status).toBe(400);
    expect((await many(Array.from({ length: 25 }, (_, k) => id(k)).join(","))).status).toBe(200);
    // 200 коллекций браузера = 8 пачек — укладываются в лимит; по одной было бы 200 запросов при лимите 60/мин
    for (let k = 0; k < 8; k++) expect((await many(Array.from({ length: 25 }, (_, n) => id(k * 25 + n)).join(","), "10.0.7.3")).status).toBe(200);
  });

  it("сохранение → ссылка → тот же снимок", async () => {
    const r = await POST(post(body));
    expect(r.status).toBe(200);
    const { id } = (await r.json()) as { id: string };
    const g = await GET(new Request(`http://x/api/collections/${id}`), { params: Promise.resolve({ id }) });
    const { collection } = (await g.json()) as { collection: { items: { x: number; sku: { sid: string } }[]; partnerId: string } };
    expect(collection.items[0]).toMatchObject({ x: 120, sku: { sid: "112923_1" } });
    expect(collection.partnerId).toBe("demo");
  });

  it("товар — только из витрины: чужой sid отклонён, название/ссылку/цену подставляет сервер", async () => {
    expect((await POST(post({ ...body, items: [{ ...body.items[0], sku: { sid: "999_fake", name: "x" } }] }))).status).toBe(400);
    const r = await POST(post({ ...body, items: [{ ...body.items[0], sku: { sid: "112923_1", name: "ПОДМЕНА", url: "https://evil.example/", price: 1 } }] }));
    const { id } = (await r.json()) as { id: string };
    const g = await GET(new Request(`http://x/api/collections/${id}`), { params: Promise.resolve({ id }) });
    const { collection } = (await g.json()) as { collection: { items: { sku: { name: string; url: string; price: number } }[] } };
    expect(collection.items[0]!.sku).toMatchObject({ name: "Диван А (витрина)", url: "https://xf.gdeslon.ru/a", price: 51000 });
  });

  it("имя в избранном: секрет редактирования выдаётся при сохранении, хеш наружу не уходит, переименовать — только с секретом (demo-15)", async () => {
    const r = await POST(post({ ...body, displayName: "Сканди #1" }));
    const { id, editToken } = (await r.json()) as { id: string; editToken: string };
    expect(editToken).toMatch(/^[A-Za-z0-9_-]{22}$/);
    const read = async () => ((await (await GET(new Request(`http://x/api/collections/${id}`), { params: Promise.resolve({ id }) })).json()) as
      { collection: Record<string, unknown> }).collection;
    const c0 = await read();
    expect(c0.displayName).toBe("Сканди #1");
    expect(c0).not.toHaveProperty("editHash");
    expect(JSON.stringify(c0)).not.toContain(editToken);
    const patch = (b: unknown) => PATCH(new Request(`http://x/api/collections/${id}`, { method: "PATCH", headers: { "content-type": "application/json", "x-forwarded-for": "10.0.0.9" },
      body: JSON.stringify(b) }), { params: Promise.resolve({ id }) });
    expect((await patch({ displayName: "Чужое", editToken: "A".repeat(22) })).status).toBe(403);   // неверный секрет
    expect((await read()).displayName).toBe("Сканди #1");
    expect((await patch({ displayName: "  Гостиная мечты  ", editToken })).status).toBe(200);
    expect((await read()).displayName).toBe("Гостиная мечты");
    expect((await patch({ displayName: "", editToken })).status).toBe(400);                          // пустое имя — не имя
  });

  it("коллекция без секрета (сохранена до demo-15) не переименовывается", async () => {
    const { collectionRepo } = await import("@/modules/collections/repository");
    const row = await collectionRepo().create("demo", { ...body, schemaVersion: 1, roomId: "living", lang: "ru", decor: [], cams: [], developerOptions: {},
      items: body.items.map((i) => ({ ...i, sku: { sid: i.sku.sid, name: i.sku.name } })) });
    const res = await PATCH(new Request(`http://x/api/collections/${row.id}`, { method: "PATCH", headers: { "content-type": "application/json", "x-forwarded-for": "10.0.0.9" },
      body: JSON.stringify({ displayName: "x", editToken: "B".repeat(22) }) }), { params: Promise.resolve({ id: row.id }) });
    expect(res.status).toBe(403);
  });

  it("чужая квартира, мусор и слишком большое тело — отказ", async () => {
    expect((await POST(post({ ...body, apartmentId: "ghost" }))).status).toBe(400);
    expect((await POST(post({ ...body, items: [] }))).status).toBe(400);
    const big = { sid: "1_1", name: "я".repeat(200), url: "https://a.ru/" + "a".repeat(580) };
    const huge = { ...body, items: Array.from({ length: 60 }, () => ({ ...body.items[0], sku: big })),
      decor: Array.from({ length: 30 }, () => ({ role: "ваза", sku: big })) };
    expect((await POST(post(huge))).status).toBe(413);
  });

  it("текущие цены: из витрины; нет в витрине — помечен, старая цена не выдаётся за текущую", () => {
    const idx = priceIndex({ variants: [{ items: [{ sku: { sid: "1_a", name: "А", price: 1000, price_at: "2026-10-13" } }] }], feeds: { диван: [{ sid: "1_b", name: "Б", price: 500 }] } });
    const cur = currentPrices(["1_a", "1_b", "1_gone"], idx);
    expect(cur["1_a"]).toMatchObject({ price: 1000, priceAt: "2026-10-13", unavailable: false, name: "А" });
    expect(cur["1_b"]!.price).toBe(500);
    expect(cur["1_gone"]).toEqual({ price: null, priceAt: null, unavailable: true });
    expect(currentPrices(["1_a"], null)["1_a"]).toMatchObject({ unavailable: false, temporarilyUnavailable: true }); // витрина не ответила — не «пропал»
  });

  it("фото товара — только путь витрины или картинка магазина", () => {
    const idx = priceIndex([{ sid: "1_a", name: "А", price: 1, img: "img/a.webp" }, { sid: "1_b", name: "Б", price: 1, img: "//imgng.gdeslon.ru/x/big.jpg" },
      { sid: "1_c", name: "В", price: 1, img: "javascript:alert(1)" }, { sid: "1_d", name: "Г", price: 1, img: "img/\"><script>" }]);
    const cur = currentPrices(["1_a", "1_b", "1_c", "1_d"], idx);
    expect([cur["1_a"]!.img, cur["1_b"]!.img, cur["1_c"]!.img, cur["1_d"]!.img]).toEqual(["img/a.webp", "//imgng.gdeslon.ru/x/big.jpg", null, null]);
  });
  it("картинка коллекции (demo-03, 2.13): только наш путь кадра, один раз", async () => {
    expect((await POST(post({ ...body, shot: "https://evil.example/t.gif" }))).status).toBe(400);
    const r = await POST(post({ ...body, shot: "/test/share/frames/scene3d-1-C1.jpg" }));
    const { id: withShot } = (await r.json()) as { id: string };
    const patch = (id: string, shot: string) => PATCH(new Request(`http://x/api/collections/${id}`, { method: "PATCH",
      headers: { "content-type": "application/json", "x-forwarded-for": "10.0.0.9" }, body: JSON.stringify({ shot }) }), { params: Promise.resolve({ id }) });
    expect((await patch(withShot, "/test/share/frames/other.jpg")).status).toBe(409);          // уже есть — не переписать
    const { id } = (await (await POST(post(body))).json()) as { id: string };
    expect((await patch(id, "/etc/passwd")).status).toBe(400);
    expect((await patch(id, "/test/share/frames/scene3d-2-C1.jpg")).status).toBe(200);
    expect((await patch(id, "/test/share/frames/scene3d-3-C1.jpg")).status).toBe(409);         // второй раз — нет
    const g = await GET(new Request(`http://x/api/collections/${id}`), { params: Promise.resolve({ id }) });
    expect(((await g.json()) as { collection: { shot: string } }).collection.shot).toBe("/test/share/frames/scene3d-2-C1.jpg");
  });
  it("картинка коллекции — только кадр того же состояния расстановки (demo-02)", async () => {
    const st = "s1-" + "a".repeat(32);
    const { id } = (await (await POST(post({ ...body, stateId: st }))).json()) as { id: string };
    const patch = (shot: string, stateId?: string) => PATCH(new Request(`http://x/api/collections/${id}`, { method: "PATCH",
      headers: { "content-type": "application/json", "x-forwarded-for": "10.0.0.9" }, body: JSON.stringify({ shot, stateId }) }), { params: Promise.resolve({ id }) });
    expect((await patch("/test/share/frames/x.jpg", "s1-" + "b".repeat(32))).status).toBe(409);   // чужое состояние
    expect((await patch("/test/share/frames/x.jpg")).status).toBe(409);                           // без номера — нельзя
    expect((await patch("/test/share/frames/x.jpg", st)).status).toBe(200);
  });
  // demo-06: коллекция v2 хранит выбор пола; неизвестная группа/вариант и вариант по умолчанию отбрасываются; v1 — без выбора
  it("коллекция v2: пол застройщика — канонически, v1 читается без выбора", async () => {
    const save = async (extra: Record<string, unknown>) => {
      const { id } = (await (await POST(post({ ...body, ...extra }))).json()) as { id: string };
      const g = await GET(new Request(`http://x/api/collections/${id}`), { params: Promise.resolve({ id }) });
      return ((await g.json()) as { collection: { developerOptions: Record<string, string> } }).collection.developerOptions;
    };
    expect(await save({ schemaVersion: 2, stateId: "s2-" + "c".repeat(32),
      developerOptions: { flooring: "parquet-herringbone", nope: "x1", kitchen: "zz" } })).toEqual({ flooring: "parquet-herringbone" });
    expect(await save({ schemaVersion: 2, developerOptions: { flooring: "laminate-oak-light" } })).toEqual({});
    expect(await save({})).toEqual({});
  });
});
