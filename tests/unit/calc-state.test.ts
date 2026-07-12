import { describe, it, expect } from "vitest";
import { addRoom, duplicateRoom, emptyProject, removeRoom, renameRoom } from "@/lib/calc/state";

let counter = 0;
const mkId = () => `id${++counter}`;
const NOW = "2026-07-12T00:00:00.000Z";

describe("calc state — CRUD комнат", () => {
  it("emptyProject создаёт одну «Комната 1»", () => {
    const p = emptyProject("oboi", mkId, NOW);
    expect(p.kind).toBe("oboi");
    expect(p.rooms).toHaveLength(1);
    expect(p.rooms[0]!.name).toBe("Комната 1");
  });

  it("addRoom добавляет «Комната 2»", () => {
    const p1 = addRoom(emptyProject("plitka", mkId, NOW), mkId, NOW);
    expect(p1.rooms).toHaveLength(2);
    expect(p1.rooms[1]!.name).toBe("Комната 2");
  });

  it("renameRoom меняет имя комнаты", () => {
    const p0 = emptyProject("kraska", mkId, NOW);
    const p1 = renameRoom(p0, p0.rooms[0]!.id, "Спальня", NOW);
    expect(p1.rooms[0]!.name).toBe("Спальня");
  });

  it("removeRoom удаляет комнату по id", () => {
    const p0 = addRoom(emptyProject("laminat", mkId, NOW), mkId, NOW);
    const id = p0.rooms[0]!.id;
    const p1 = removeRoom(p0, id, NOW);
    expect(p1.rooms.some((r) => r.id === id)).toBe(false);
    expect(p1.rooms).toHaveLength(1);
  });

  it("duplicateRoom вставляет копию рядом с исходной", () => {
    const p0 = emptyProject("oboi", mkId, NOW);
    const p1 = duplicateRoom(p0, p0.rooms[0]!.id, mkId, NOW);
    expect(p1.rooms).toHaveLength(2);
    expect(p1.rooms[1]!.name).toContain("копия");
  });
});
