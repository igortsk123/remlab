import { describe, expect, it } from "vitest";
import { camsSigOf } from "@/contracts/trial-photos";
import { AUTO_RULES, pickAutoRooms, variantSig } from "@/lib/trial/auto-photos-pick";
import { photoMeta } from "@/lib/trial/repo-photo";
import type { TrialPhotoIn } from "@/contracts/trial";

// Отбор комнат автофото (T-20261112-115 Ф2): чистая функция по данным тура — порядок, активный вариант как у тура без выбора человека,
// отказы с кодом, потолок комнат; подпись варианта устойчива к порядку и шуму, подпись поз совпадает с подписью заказа страницы.

const cams = [{ name: "C2", x: 300, y: 10, rot: -40, fov: 84, pose: 3 }, { name: "C1", x: 10.4, y: 20, rot: 136, fov: 90, pose: 3, pshift: 0.1 }];
const it2 = (x: number) => [{ role: "диван", x, y: 1, sku: { msid: "1_a" } }, { role: "стол 2", x: 5, y: 5, sku: { msid: "1_b" } }];
const v = (room: string, style: string, over: Record<string, unknown> = {}) => ({ id: `${room}-${style}`, room_id: room, style_id: style,
  items: it2(100), decor: [], cams, ...over });
const bundle = (over: Record<string, unknown> = {}) => ({
  rooms_geo: Object.fromEntries(["living", "b1", "b2", "b3", "b4", "b5", "b6", "k"].map((r) => [r, { w: 400, d: 300 }])),
  apartment_rooms: [["k", "kitchen"], ["b1", "bedroom"], ["living", "living"], ["b2", "bedroom"], ["b3", "bedroom"], ["b4", "bedroom"],
    ["b5", "bedroom"], ["b6", "bedroom"]].map(([id, kind]) => ({ id, kind, furniture_state: "ready", photo_ok: true })),
  trial: { panels: [{ rooms: [["b1", 9], ["b2", 15], ["b3", 12], ["b4", 11], ["b5", 10], ["b6", 8], ["living", 20]].map(([id, a]) => ({ id, areaM2: a })) }] },
  variants: [v("living", "scandi", { mine: true }), v("living", "modern"), v("living", "scandi"), ...["b1", "b2", "b3", "b4", "b5", "b6"].map((r) => v(r, "modern")),
    v("k", "modern")],
  ...over,
});

describe("отбор комнат автофото", () => {
  it("гостиная первой, спальни по площади, не больше 5; кухня без права не снимается; лишняя — max_rooms", () => {
    const { picks, refused } = pickAutoRooms(bundle());
    expect(picks.map((p) => [p.roomId, p.ord, p.style])).toEqual([["living", 0, "modern"], ["b2", 1, "modern"], ["b3", 2, "modern"],
      ["b4", 3, "modern"], ["b5", 4, "modern"]]);
    expect(refused).toEqual([{ room: "b1", code: "max_rooms" }, { room: "b6", code: "max_rooms" }]);
    expect(picks[0]!.cams.map((c) => c.name)).toEqual(["C2", "C1"]);
    expect(AUTO_RULES).toMatchObject({ max_rooms: 5, reserve_rub: 10, tour_cap_rub: 50, daily_cap_rub: 500, daily_warn_rub: 400 });
  });

  it("активный стиль — первый по порядку тура (коллекция `mine` не в счёт); нет точного — карта замен; нет и её — отказ", () => {
    const b = bundle({ variants: [v("living", "modern"), v("living", "scandi"), v("b1", "scandi"), v("b2", "loft")],
      room_style_fallback: { b2: { modern: ["japandi", "loft"] } } });
    const { picks, refused } = pickAutoRooms(b);
    expect(picks.map((p) => [p.roomId, p.variantId])).toEqual([["living", "living-modern"], ["b2", "b2-loft"]]);
    expect(refused).toContainEqual({ room: "b1", code: "no_active_variant" });
  });

  it("без мебели и без двух ракурсов — отказы с кодом; данных нет — пусто", () => {
    const b = bundle({ variants: [v("living", "modern", { items: [] }), v("b2", "modern", { cams: [cams[0]] })] });
    expect(pickAutoRooms(b).refused).toEqual(expect.arrayContaining([{ room: "living", code: "no_furniture" }, { room: "b2", code: "no_cams" }]));
    expect(pickAutoRooms(null)).toEqual({ picks: [], refused: [] });
  });

  it("подпись варианта: порядок предметов и шум < 0,5 см — та же; сдвиг 2 см, товар, размер комнаты — другая", () => {
    const geo = { w: 400, d: 300 };
    const base = variantSig(v("b1", "modern"), geo);
    expect(base).toMatch(/^v1-[0-9a-f]{32}$/);
    expect(variantSig(v("b1", "modern", { items: [...it2(100.3)].reverse() }), geo)).toBe(base);
    expect(variantSig(v("b1", "modern", { items: it2(102) }), geo)).not.toBe(base);
    expect(variantSig(v("b1", "modern", { items: [{ ...it2(100)[0], sku: { msid: "1_z" } }, it2(100)[1]] }), geo)).not.toBe(base);
    expect(variantSig(v("b1", "modern"), { w: 410, d: 300 })).not.toBe(base);
  });

  it("подпись поз задачи = подписи заказа страницы с теми же позами", () => {
    const [p] = pickAutoRooms(bundle()).picks;
    const page = photoMeta({ room_id: "living", views: [], room: { w: 400, d: 300 }, items: [{ role: "диван" }], cams } as unknown as TrialPhotoIn);
    expect(p!.camsSig).toBe(page.camsSig);
    expect(p!.camsSig).toBe(camsSigOf(cams));
    expect(p!.camsSig).toBe("C1:10,20,136,90,3;C2:300,10,-40,84,3");
  });
});
