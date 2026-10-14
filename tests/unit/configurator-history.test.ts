import { describe, expect, it } from "vitest";

import { emptyHistory, HISTORY_LIMIT, record, redo, undo } from "@/lib/configurator/history";

describe("отмена/возврат в конфигураторе (flat3d-sims-ux)", () => {
  it("действие → отмена → возврат", () => {
    let h = record(emptyHistory<number>(), 1); // было 1, стало 2
    const u = undo(h, 2)!;
    expect(u.value).toBe(1);
    h = u.h;
    const r = redo(h, 1)!;
    expect(r.value).toBe(2);
    expect(r.h.future).toEqual([]);
  });

  it("новое действие после отмены сбрасывает «вперёд»", () => {
    const u = undo(record(emptyHistory<number>(), 1), 2)!;
    const h = record(u.h, 1); // после отмены сделали другое действие
    expect(h.future).toEqual([]);
    expect(redo(h, 3)).toBeNull();
  });

  it("пустая история — отменять и возвращать нечего", () => {
    expect(undo(emptyHistory<number>(), 0)).toBeNull();
    expect(redo(emptyHistory<number>(), 0)).toBeNull();
  });

  it("помнит не больше предела", () => {
    let h = emptyHistory<number>();
    for (let i = 0; i < HISTORY_LIMIT + 10; i++) h = record(h, i);
    expect(h.past).toHaveLength(HISTORY_LIMIT);
    expect(h.past[0]).toBe(10);
  });
});
