import { describe, expect, it } from "vitest";

// пустышка сборщика веток (T-20261112-78): чистая ветка, тест проходит
describe("mq dummy ok", () => {
  it("passes", () => {
    expect(1 + 1).toBe(2);
  });
});
