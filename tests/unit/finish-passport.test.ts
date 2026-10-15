import { describe, expect, it } from "vitest";

import { DEFAULT_FINISH, finishPassport } from "@/lib/viewer3d/finish-passport";
import { liveApartment } from "@/lib/viewer3d/demo-scene";

// ПАСПОРТ ОТДЕЛКИ (план demo-04): цвета стены и пола живой сцены — из паспорта, тем же красится серверный кадр
// (`services/planner-solver/tests/test_finish_color.py`, ΔE ≤ 5 в калибровке). Чужой цвет или id — значение по умолчанию.

const room = { w: 439, d: 325, title: "Гостиная", openings: [] };
const items = [{ role: "диван", x: 169, y: 78, rot: 0, w: 175, d: 90, h: 85, sku: { msid: "1_1", name: "Диван", price: 1 } }];

describe("паспорт отделки", () => {
  it("карточка поверх набора по умолчанию; неверный цвет — по умолчанию", () => {
    const p = finishPassport({ wall: { id: "paint-sand", colorHex: "#E8E2D6" }, floor: { colorHex: "red" } });
    expect(p.wall).toEqual({ id: "paint-sand", colorHex: "#e8e2d6" });
    expect(p.floor).toEqual(DEFAULT_FINISH.floor);
    expect(p.ceiling).toEqual(DEFAULT_FINISH.ceiling);
  });

  it("живая сцена красит стены и пол цветами паспорта", () => {
    const finish = { wall: { id: "paint-sand", colorHex: "#e8e2d6" }, floor: { id: "oak", colorHex: "#a07850" } };
    const built = liveApartment({ ...room, finish }, items, "https://remont-lab.online/demo/")!;
    const mat = (id: string) => built.catalogue.materials.find((m) => m.id === id);
    expect(mat("paint-sand")?.colorHex).toBe("#e8e2d6");
    expect(mat("oak")?.colorHex).toBe("#a07850");
    const wallOpt = built.catalogue.options.find((o) => o.id === "opt:wall");
    expect(wallOpt?.asset).toMatchObject({ kind: "material", materialId: "paint-sand" });
  });

  it("без паспорта — прежние стены и пол (`paint-white` — запасной материал движка)", () => {
    const built = liveApartment(room, items, "https://remont-lab.online/demo/")!;
    expect(built.catalogue.materials.find((m) => m.id === "paint-white")?.colorHex).toBe(DEFAULT_FINISH.wall.colorHex);
  });
});
