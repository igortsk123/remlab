import { describe, it, expect } from "vitest";
import { estimateRepo } from "@/modules/estimate/repository";
import { estimate as estimateSchema } from "@/contracts/estimate";

// Удаление сметы (in-memory реализация): только своя сессия, чужая/несуществующая → false.
describe("EstimateRepository.delete", () => {
  const mk = (id: string, sessionId: string) => {
    const now = new Date().toISOString();
    return estimateSchema.parse({ id, sessionId, title: "Смета", source: "calc", items: [], createdAt: now, updatedAt: now });
  };

  it("удаляет свою смету; чужую и несуществующую — нет", async () => {
    const repo = estimateRepo();
    await repo.create(mk("del-e1", "del-s1"));
    await repo.create(mk("del-e2", "del-s2"));

    expect(await repo.delete("del-e2", "del-s1")).toBe(false); // чужая сессия
    expect(await repo.get("del-e2")).not.toBeNull();

    expect(await repo.delete("del-e1", "del-s1")).toBe(true);
    expect(await repo.get("del-e1")).toBeNull();

    expect(await repo.delete("нет-такой", "del-s1")).toBe(false);
  });
});
