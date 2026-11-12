import { describe, expect, it } from "vitest";

// пустышка сборщика веток (T-20261112-78): заведомо падающий тест
describe("mq dummy fail", () => {
  it("fails on purpose", () => {
    expect(1 + 1).toBe(3);
  });
});
