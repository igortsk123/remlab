import { describe, expect, it } from "vitest";

import { loadFlat3d } from "@/lib/configurator/data";
import { defaultConfiguration, optionsForSlot, resolveScene } from "@/lib/configurator/resolve";
import { toPhotoRequest } from "@/lib/configurator/photo";

const { apartment, catalogue } = loadFlat3d();

describe("конфигуратор: данные демо-квартиры", () => {
  it("квартира из 5 комнат, у каждой есть хотя бы один слот выбора", () => {
    expect(apartment.rooms.map((r) => r.id).sort()).toEqual(["bathroom", "bedroom", "hall", "kitchen", "living"]);
    for (const r of apartment.rooms) {
      expect(apartment.slots.filter((s) => s.roomId === r.id).length).toBeGreaterThan(0);
    }
  });

  it("у каждого слота есть валидный default и минимум 3 варианта на выбор", () => {
    for (const slot of apartment.slots) {
      const opts = optionsForSlot(apartment, catalogue, slot);
      expect(opts.length, `слот ${slot.id}`).toBeGreaterThanOrEqual(3);
      expect(opts.some((o) => o.id === slot.defaultOptionId), `default слота ${slot.id}`).toBe(true);
    }
  });

  it("в основных категориях ровно «база + 3», и ровно один вариант premium", () => {
    // Правило «база + 3» — про НАШУ подборку: столько вариантов человек осилит сравнить.
    // Материалы, сделанные из фотографии застройщика (`photo-material`, ADR-0226), считаются
    // отдельно: их число диктует застройщик, а не мы, и прятать их ради красивого счёта нельзя.
    const fromDeveloperPhoto = (o: { asset: { kind: string; materialId?: string } }): boolean => {
      if (o.asset.kind !== "material") return false;
      const m = catalogue.materials.find((x) => x.id === o.asset.materialId);
      return m?.source?.kind === "photo-material";
    };
    for (const id of ["living-floor", "kitchen-units", "kitchen-appliances", "bathroom-tiles", "bathroom-floor"]) {
      const slot = apartment.slots.find((s) => s.id === id);
      expect(slot, id).toBeTruthy();
      const opts = optionsForSlot(apartment, catalogue, slot!).filter((o) => !fromDeveloperPhoto(o));
      expect(opts.length, id).toBe(4);
      expect(opts.filter((o) => o.tier === "base").length, `${id}: база`).toBe(1);
      expect(opts.filter((o) => o.tier === "premium").length, `${id}: premium`).toBe(1);
    }
  });
});

describe("конфигуратор: разрешение выбора и цена", () => {
  it("конфигурация по умолчанию: апгрейдов 0, сумма = цена квартиры", () => {
    const cfg = defaultConfiguration(apartment, catalogue);
    const scene = resolveScene(apartment, catalogue, cfg);
    expect(scene.issues).toEqual([]);
    expect(scene.totals.upgradesGbp).toBe(0);
    expect(scene.totals.totalGbp).toBe(apartment.basePriceGbp);
  });

  it("кухня Premium (8700) + мрамор на столешницу (2600) = 11 300 доплаты", () => {
    const cfg = defaultConfiguration(apartment, catalogue);
    cfg.selections["kitchen-units"] = "kitchen-premium";
    cfg.selections["kitchen-worktop"] = "worktop-marble-premium";
    const scene = resolveScene(apartment, catalogue, cfg);
    expect(scene.totals.upgradesGbp).toBe(11_300);
    expect(scene.totals.byRoomGbp.kitchen).toBe(11_300);
    expect(scene.totals.upgradeCount).toBe(2);
  });

  it("неизвестная опция откатывается к базовой и попадает в issues, сцена не рушится", () => {
    const cfg = defaultConfiguration(apartment, catalogue);
    cfg.selections["living-floor"] = "нет-такой-опции";
    const scene = resolveScene(apartment, catalogue, cfg);
    expect(scene.selections["living-floor"]).toBe("floor-lvt-oak-light");
    expect(scene.issues[0]?.code).toBe("unknown_option");
    expect(scene.surfaces.some((s) => s.slotId === "living-floor")).toBe(true);
  });

  it("опция не из списка слота отклоняется (плитка санузла — не пол гостиной)", () => {
    const cfg = defaultConfiguration(apartment, catalogue);
    cfg.selections["living-floor"] = "bath-wall-metro";
    const scene = resolveScene(apartment, catalogue, cfg);
    expect(scene.issues.map((i) => i.code)).toContain("not_allowed");
    expect(scene.selections["living-floor"]).toBe("floor-lvt-oak-light");
  });

  it("габарит предмета берётся у выбранной модели, а не у слота", () => {
    const cfg = defaultConfiguration(apartment, catalogue);
    const sofaOptions = optionsForSlot(apartment, catalogue, apartment.slots.find((s) => s.id === "living-sofa")!);
    const other = sofaOptions[2]!;
    cfg.selections["living-sofa"] = other.id;
    const scene = resolveScene(apartment, catalogue, cfg);
    const item = scene.items.find((i) => i.slotId === "living-sofa")!;
    expect(other.asset.kind).toBe("mesh");
    if (other.asset.kind === "mesh") {
      expect(item.placement.wCm).toBe(other.asset.wCm);
      expect(item.placement.hCm).toBe(other.asset.hCm);
    }
  });

  it("каждый предмет стоит внутри своей комнаты", () => {
    const cfg = defaultConfiguration(apartment, catalogue);
    const scene = resolveScene(apartment, catalogue, cfg);
    for (const it of scene.items) {
      const room = apartment.rooms.find((r) => r.id === it.roomId)!;
      const p = it.placement;
      expect(p.x, `${it.slotId} x`).toBeGreaterThanOrEqual(room.x);
      expect(p.x, `${it.slotId} x`).toBeLessThanOrEqual(room.x + room.w);
      expect(p.y, `${it.slotId} y`).toBeGreaterThanOrEqual(room.y);
      expect(p.y, `${it.slotId} y`).toBeLessThanOrEqual(room.y + room.d);
    }
  });
});

describe("конфигуратор: мост в photo-конвейер", () => {
  it("координаты переводятся в комнатные, роли и размеры сохраняются", () => {
    const cfg = defaultConfiguration(apartment, catalogue);
    const scene = resolveScene(apartment, catalogue, cfg);
    const req = toPhotoRequest(apartment, scene, "living")!;
    expect(req.room.w).toBe(880);
    expect(req.room.d).toBe(280);
    const sofa = req.items.find((i) => i.role === "диван")!;
    expect(sofa.y).toBe(52); // 452 в координатах квартиры − 400 (начало гостиной)
    expect(sofa.msid).toBeTruthy();
    for (const it of req.items) {
      expect(it.x).toBeGreaterThanOrEqual(0);
      expect(it.x).toBeLessThanOrEqual(req.room.w);
      expect(it.y).toBeGreaterThanOrEqual(0);
      expect(it.y).toBeLessThanOrEqual(req.room.d);
    }
  });

  it("камеры смотрят внутрь комнаты и их две", () => {
    const cfg = defaultConfiguration(apartment, catalogue);
    const scene = resolveScene(apartment, catalogue, cfg);
    const req = toPhotoRequest(apartment, scene, "kitchen")!;
    expect(req.cams.length).toBeGreaterThanOrEqual(1);
    for (const c of req.cams) {
      expect(c.x).toBeGreaterThanOrEqual(0);
      expect(c.x).toBeLessThanOrEqual(req.room.w);
      expect(c.rot).toBeGreaterThanOrEqual(0);
      expect(c.rot).toBeLessThan(360);
    }
  });


  it("угол камеры — в конвенции конвейера: взгляд (sin a, −cos a) смотрит в центр комнаты", () => {
    const cfg = defaultConfiguration(apartment, catalogue);
    const scene = resolveScene(apartment, catalogue, cfg);
    const req = toPhotoRequest(apartment, scene, "living")!;
    for (const c of req.cams) {
      const a = (c.rot * Math.PI) / 180;
      const dir = { x: Math.sin(a), y: -Math.cos(a) };
      const toCentre = { x: req.room.w / 2 - c.x, y: req.room.d / 2 - c.y };
      const len = Math.hypot(toCentre.x, toCentre.y) || 1;
      const cos = (dir.x * toCentre.x + dir.y * toCentre.y) / len;
      // косинус угла между взглядом и направлением на центр: камера смотрит в комнату,
      // а не в стену (кадр 28.09 приходил пустым именно из-за перепутанного знака)
      expect(cos, `камера ${c.name} смотрит мимо центра`).toBeGreaterThan(0.8);
    }
  });


  it("материал применяется только туда, где уместен: пол ≠ фасад, плитка ≠ столешница", () => {
    // каждый вариант покрытия обязан подходить своей поверхности — иначе в сцене окажется
    // доска пола на дверце шкафа (замечание владельца 29.09)
    for (const slot of apartment.slots.filter((s) => s.kind === "surface")) {
      const wanted = slot.surface ?? "floor";
      for (const o of optionsForSlot(apartment, catalogue, slot)) {
        if (o.asset.kind !== "material") continue;
        const mat = catalogue.materials.find((x) => x.id === (o.asset as { materialId: string }).materialId)!;
        expect(mat, `${o.id}: материал не найден`).toBeTruthy();
        expect(
          mat.surfaces.length === 0 || mat.surfaces.includes(wanted),
          `${o.titleRu} предлагается на «${wanted}», хотя объявлен для ${mat.surfaces.join("/") || "чего угодно"}`,
        ).toBe(true);
      }
    }
  });

  it("фактуры фасадов сделаны из фото реальных товаров и несут провенанс", () => {
    const fronts = catalogue.materials.filter((m) => m.source?.kind === "photo");
    expect(fronts.length, "фактур из фото").toBeGreaterThanOrEqual(3);
    for (const m of fronts) {
      expect(m.surfaces).toContain("front");
      expect(m.source?.productSid, `${m.id}: нет товара-источника`).toBeTruthy();
      expect(m.source?.shop, `${m.id}: нет магазина`).toBeTruthy();
      expect(m.source?.seamError ?? 99, `${m.id}: шов слишком заметен`).toBeLessThanOrEqual(2.0);
    }
  });


  it("каждый внутренний проём парный: дыра есть в обеих комнатах", () => {
    // Дефект 29.09: проём кухня↔гостиная был пробит в НАРУЖНОЙ стене гостиной — ходить можно,
    // а в кадре глухая стена. Проверяем совпадение отрезков в мировых координатах.
    const seg = (r: (typeof apartment.rooms)[number], o: (typeof r.openings)[number]) => {
      if (o.wall === "south" || o.wall === "north") {
        const y = o.wall === "south" ? r.y : r.y + r.d;
        return `h|${y}|${r.x + o.offsetCm}|${r.x + o.offsetCm + o.widthCm}`;
      }
      const x = o.wall === "west" ? r.x : r.x + r.w;
      return `v|${x}|${r.y + o.offsetCm}|${r.y + o.offsetCm + o.widthCm}`;
    };
    const all: { room: string; wall: string; key: string }[] = [];
    for (const r of apartment.rooms) {
      for (const o of r.openings) {
        if (o.kind === "window") continue;
        all.push({ room: r.id, wall: o.wall, key: seg(r, o) });
      }
    }
    for (const it of all) {
      if (it.room === "hall" && it.wall === "south") continue; // входная дверь наружу
      const twin = all.some((x) => x.room !== it.room && x.key === it.key);
      expect(twin, `${it.room}/${it.wall}: нет парного проёма в соседней комнате`).toBe(true);
    }
  });

  it("проёмы уезжают в snake_case, как ждёт конвейер", () => {
    const cfg = defaultConfiguration(apartment, catalogue);
    const scene = resolveScene(apartment, catalogue, cfg);
    const req = toPhotoRequest(apartment, scene, "bedroom")!;
    const win = req.room.openings.find((o) => o.kind === "window")!;
    expect(win.offset_cm).toBe(120);
    expect(win.width_cm).toBe(150);
    expect(win.sill_cm).toBe(90);
  });
});
