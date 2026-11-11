import { describe, expect, it } from "vitest";

import { ETA_DEFAULT, etaOf, stageEst } from "@/lib/trial/rebuild-eta";

// Оценка таймера «Подтвердить планировку» (T-20261111-16): замеры этого тура важнее средних, нулевая стадия (прежняя сцена) не в счёт,
// хвост = publish_s − стадии; по комнате — когда готова её стадия.
describe("оценка времени пересчёта", () => {
  it("нет замеров — запас; есть только чужие — среднее; свой — последний ненулевой", () => {
    expect(stageEst([], [])).toEqual(ETA_DEFAULT);
    expect(stageEst([], [{ v1_s: 10, publish_s: 50 }, { v1_s: 20, publish_s: 60 }])).toEqual({ ...ETA_DEFAULT, v1: 15, tail: 40 });
    const own: Record<string, number>[] = [{ v1_s: 12, living_s: 0, bedrooms_s: 40, publish_s: 80 }, { v1_s: 30, living_s: 70, publish_s: 200 }];
    expect(stageEst(own, [{ v1_s: 99 }])).toEqual({ v1: 12, living: 70, bedrooms: 40, tail: 28 });
  });

  it("всего и по комнатам: гостиная — после своей стадии, спальня — после спален, прочие — к итогу", () => {
    const est = { v1: 10, living: 50, bedrooms: 40, tail: 20 };
    expect(etaOf(est, [{ id: "bedroom-1", kind: "bedroom" }])).toEqual({ eta_s: 70, room_eta_s: { "bedroom-1": 50 } });
    expect(etaOf(est, [{ id: "living", kind: "living" }, { id: "bedroom-2", kind: "bedroom" }, { id: "kitchen", kind: "other" }]))
      .toEqual({ eta_s: 120, room_eta_s: { living: 60, "bedroom-2": 100, kitchen: 120 } });
    expect(etaOf(est, [])).toEqual({ eta_s: 30, room_eta_s: {} });
  });
});
