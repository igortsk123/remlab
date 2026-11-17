import { describe, expect, it } from "vitest";

import { accentCarrier, ACCENT_CARRIERS, resolveAccentSide } from "@/lib/configurator/accent";
import { fromDemoVariant } from "@/lib/configurator/fromDemo";
import { accentWallFor } from "@/lib/viewer3d/finish-textures";

// T-20261117-16 (владелец TG 1438): лофт — акцентная кирпичная стена. Какая стена — по предмету сцены, не по ID комнаты:
// спальня — за изголовьем кровати, гостиная — за диваном, нет дивана — за ТВ. Паспорт по стилю — данные (`finish-cc0.json`).

const at = (role: string, roomId = "r1") => ({ roomId, kind: "furniture", photoRole: role, slotId: `${role}#0`, placement: { x: 100, y: 100, rot: 0 } });

describe("предмет, за которым акцент (behind-focal)", () => {
  it("порядок из данных: кровать → диван → ТВ", () => {
    expect([...ACCENT_CARRIERS]).toEqual(["кровать", "диван", "тв"]);
  });
  it("спальня — кровать, даже если в комнате есть и диван", () => {
    expect(accentCarrier([at("диван"), at("кровать")], "r1", "behind-focal")?.photoRole).toBe("кровать");
  });
  it("гостиная — диван; нет дивана — ТВ-тумба; ничего нет — нет акцента", () => {
    expect(accentCarrier([at("тв-тумба"), at("диван")], "r1", "behind-focal")?.photoRole).toBe("диван");
    expect(accentCarrier([at("тв-тумба"), at("столик")], "r1", "behind-focal")?.photoRole).toBe("тв-тумба");
    expect(accentCarrier([at("столик")], "r1", "behind-focal")).toBeUndefined();
  });
  it("только предметы этой комнаты", () => {
    expect(accentCarrier([at("кровать", "r2")], "r1", "behind-focal")).toBeUndefined();
  });
  it("прежний якорь «за диваном» кровати не берёт", () => {
    expect(accentCarrier([at("кровать")], "r1", "behind-sofa")).toBeUndefined();
    expect(accentCarrier([at("диван")], "r1", "behind-sofa")?.photoRole).toBe("диван");
  });
  it("сторона — по спинке предмета (изголовье кровати у стены)", () => {
    const room = { id: "r1", kind: "bedroom", titleRu: "", titleEn: "", x: 0, y: 0, w: 300, d: 400, heightCm: 270, openings: [] } as never;
    expect(resolveAccentSide(room, { x: 150, y: 40, rot: 0 })).toBe("south");
  });
});

describe("стиль → акцентная стена (данные)", () => {
  it("лофт — кирпич со своей расцветкой, остальные стили — без акцента", () => {
    const loft = accentWallFor("лофт");
    expect(loft?.anchor).toBe("behind-focal");
    expect(loft?.material.id).toBe("finish-accent-brick");
    expect(loft?.material.tintMean).toBeUndefined();          // карта цветная: паспорт её не красит
    expect(loft?.material.tileCm).toEqual([240, 120]);
    expect(accentWallFor("ЛОФТ")?.material.id).toBe("finish-accent-brick");
    for (const s of ["сканди", "современный", "минимализм", "джапанди", "неоклассика", undefined]) expect(accentWallFor(s)).toBeUndefined();
  });

  const data = (style: string) => ({
    room: { w: 439, d: 325, title: "Гостиная", height_cm: 270, openings: [] },
    variants: [{ id: "v", title: style, style, items: [
      { role: "диван", x: 200, y: 280, rot: 180, w: 200, d: 90, sku: { name: "Диван", price: 20000, sid: "112923_1", img: "img/a.jpg" } },
    ] }],
  });
  const CTX = { apartmentId: "flat215", partnerId: "demo", currency: "RUB" as const, basePrice: 9_578_200 };
  const wallAccent = (style: string) => {
    const r = fromDemoVariant(data(style), "v", CTX)!;
    const wall = r.apartment.slots.find((s) => s.kind === "surface" && s.surface === "wall")!;
    const opt = r.catalogue.options.find((o) => o.id === wall.defaultOptionId)!;
    return { opt, mats: r.catalogue.materials };
  };
  it("вариант-лофт: у стен паспорта акцент «за главным предметом» с материалом-кирпичом в каталоге", () => {
    const { opt, mats } = wallAccent("лофт");
    expect(opt.asset.kind === "material" && opt.asset.accent).toEqual({ materialId: "finish-accent-brick", anchor: "behind-focal" });
    expect(mats.some((m) => m.id === "finish-accent-brick")).toBe(true);
  });
  it("вариант другого стиля — без акцента", () => {
    const { opt } = wallAccent("сканди");
    expect(opt.asset.kind === "material" && opt.asset.accent).toBeFalsy();
  });
});
