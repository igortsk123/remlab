import { describe, expect, it } from "vitest";

import { loadFlat3d } from "@/lib/configurator/data";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { checkPlacement, corners, overlaps, type Box } from "@/lib/configurator/placement";

const { apartment, catalogue } = loadFlat3d();
const scene = resolveScene(apartment, catalogue, defaultConfiguration(apartment, catalogue));
const roleOf = (slotId: string): string | undefined =>
  apartment.slots.find((s) => s.id === slotId)?.photoRole ?? undefined;
const boxes: Box[] = scene.items.map((i) => ({
  slotId: i.slotId,
  x: i.placement.x,
  y: i.placement.y,
  rot: i.placement.rot,
  wCm: i.placement.wCm,
  dCm: i.placement.dCm,
  role: roleOf(i.slotId),
  flat: (i.placement.elevCm ?? 0) > 40 || (i.asset.kind === "kit" && i.asset.kit === "rug"),
}));
const sofa = boxes.find((b) => b.slotId === "living-sofa")!;

describe("проверка места для мебели", () => {
  it("два одинаковых прямоугольника пересекаются, разнесённые — нет", () => {
    const a = corners({ x: 0, y: 0, rot: 0, wCm: 100, dCm: 60 });
    expect(overlaps(a, corners({ x: 20, y: 0, rot: 0, wCm: 100, dCm: 60 }))).toBe(true);
    expect(overlaps(a, corners({ x: 300, y: 0, rot: 0, wCm: 100, dCm: 60 }))).toBe(false);
  });

  it("повёрнутый предмет считается по УГЛАМ, а не по осевой коробке", () => {
    const a = corners({ x: 0, y: 0, rot: 45, wCm: 200, dCm: 20 });
    // точка у самого угла осевой коробки, но далеко от повёрнутого прямоугольника
    expect(overlaps(a, corners({ x: 90, y: -90, rot: 0, wCm: 20, dCm: 20 }))).toBe(false);
  });

  it("на месте по умолчанию всё стоит законно", () => {
    // встроенное (кухня, шкаф, санузел) не двигается и намеренно стоит в стену и у двери —
    // проверка места для него не применяется
    const movable = boxes.filter(
      (b) => apartment.slots.find((s) => s.id === b.slotId)?.kind === "furniture",
    );
    for (const b of movable) {
      const res = checkPlacement({ apartment, boxes, slotId: b.slotId, next: b });
      expect(res.ok, `${b.slotId}: ${res.reason ?? ""} ${res.withSlotId ?? ""}`).toBe(true);
    }
  });

  it("за стену комнаты выйти нельзя", () => {
    const res = checkPlacement({ apartment, boxes, slotId: sofa.slotId, next: { ...sofa, x: sofa.x + 900 } });
    expect(res.ok).toBe(false);
    expect(res.reason).toBe("outside-room");
  });

  it("на другой предмет встать нельзя", () => {
    const other = boxes.find((b) => b.slotId === "living-armchair")!;
    const res = checkPlacement({
      apartment,
      boxes,
      slotId: sofa.slotId,
      next: { ...sofa, x: other.x, y: other.y },
    });
    expect(res.ok).toBe(false);
    expect(res.reason).toBe("overlap");
  });

  it("ковёр можно класть под мебель", () => {
    const rug = boxes.find((b) => b.role === "ковёр");
    const armchair = boxes.find((b) => b.slotId === "living-armchair");
    if (!rug || !armchair) return;
    // ставим ковёр ровно под кресло — по геометрии они пересекаются, но это законно
    const res = checkPlacement({
      apartment,
      boxes,
      slotId: rug.slotId,
      next: { ...rug, x: armchair.x, y: armchair.y },
    });
    expect(res.ok, `ковёр: ${res.reason ?? ""}`).toBe(true);
  });

  it("стул может заезжать под обеденный стол", () => {
    const chair = boxes.find((b) => b.role === "стул");
    const table = boxes.find((b) => b.role === "стол обеденный");
    if (!chair || !table) return;
    const res = checkPlacement({ apartment, boxes, slotId: chair.slotId, next: { ...chair, x: table.x, y: table.y } });
    expect(res.ok, `стул: ${res.reason ?? ""} ${res.withSlotId ?? ""}`).toBe(true);
  });
});
