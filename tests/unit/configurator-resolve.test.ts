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
    for (const id of ["living-floor", "kitchen-units", "kitchen-appliances", "bathroom-tiles", "bathroom-floor"]) {
      const slot = apartment.slots.find((s) => s.id === id);
      expect(slot, id).toBeTruthy();
      const opts = optionsForSlot(apartment, catalogue, slot!);
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
