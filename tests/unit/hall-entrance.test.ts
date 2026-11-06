import { describe, expect, it } from "vitest";

import { entranceOf, type Opening } from "@/contracts/apartment";
import { openings as demoOpenings } from "@/lib/configurator/fromDemo";
import { closedLeaf } from "@/lib/viewer3d/openings";
import apartment from "@/data/flat3d/apartment.json";

// ВХОД — ДАННЫЕ ЭКЗЕМПЛЯРА (hall-demo-01 этап 1, T-20261106-72): входная дверь помечена `isEntrance`, а не угадана как
// «южная стена прихожей». Тот же флаг читает солвер (`planner/hall_checks.py:entrance`, тесты `test_hall_rules.py`).

const door = (wall: Opening["wall"], offsetCm: number, isEntrance?: boolean): Opening => ({
  kind: "door", wall, offsetCm, widthCm: 90, ...(isEntrance ? { isEntrance } : {}),
});

describe("вход в квартиру", () => {
  it("флаг — вход, порядок проёмов роли не играет; без флага у прихожей — южная стена, у других — нет", () => {
    const ops = [door("west", 160), door("south", 31), door("east", 20, true)];
    for (const perm of [ops, [...ops].reverse(), [ops[2]!, ops[0]!, ops[1]!]]) {
      expect(entranceOf({ kind: "hall", openings: perm })).toEqual({ flagged: true });
    }
    expect(entranceOf({ kind: "hall", openings: [door("west", 160), door("south", 31)] })).toEqual({ flagged: false, fallbackWall: "south" });
    expect(entranceOf({ kind: "living", openings: [door("south", 31)] })).toEqual({ flagged: false });
  });

  it("закрыто полотно входа по флагу, а не вся южная стена; без флага — прежняя стена", () => {
    const east = door("east", 20, true), south = door("south", 31);
    const ent = entranceOf({ kind: "hall", openings: [east, south] });
    const opts = { entranceWall: ent.fallbackWall };
    expect(closedLeaf(east, "east", opts)).toBe(true);
    expect(closedLeaf(south, "south", opts)).toBe(false);
    expect(closedLeaf(south, "south", { entranceWall: "south" })).toBe(true);
    expect(closedLeaf(south, "south", { doorsClosed: true })).toBe(true);
  });

  it("флаг витрины (`is_entrance`) доходит до проёма конфигуратора", () => {
    const got = demoOpenings({ openings: [
      { kind: "door", wall: "south", offset_cm: 31, width_cm: 90, swing_cm: 0, is_entrance: true },
      { kind: "door", wall: "west", offset_cm: 160, width_cm: 85, swing_cm: 0 },
    ] });
    expect(got.map((o) => o.isEntrance === true)).toEqual([true, false]);
  });

  it("прихожая квартиры 3D: ровно одна входная дверь — южная (как было по эвристике)", () => {
    const hall = apartment.rooms.find((r) => r.kind === "hall")!;
    const ent = (hall.openings as { wall: string; isEntrance?: boolean }[]).filter((o) => o.isEntrance === true);
    expect(ent.map((o) => o.wall)).toEqual(["south"]);
  });
});
