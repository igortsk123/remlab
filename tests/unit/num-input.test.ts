import { describe, it, expect } from "vitest";
import { parseNum } from "@/components/calc/NumInput";

describe("parseNum — дробный ввод (. и ,)", () => {
  it("точка и запятая → число", () => {
    expect(parseNum("1.2")).toBe(1.2);
    expect(parseNum("1,2")).toBe(1.2);
    expect(parseNum("10,05")).toBe(10.05);
    expect(parseNum("2.5")).toBe(2.5);
    expect(parseNum("0")).toBe(0);
  });
  it("промежуточный/пустой ввод → undefined (не сбрасывает набор)", () => {
    expect(parseNum("")).toBeUndefined();
    expect(parseNum(".")).toBeUndefined();
    expect(parseNum("1,")).toBe(1); // «1,» уже валидное число 1, продолжение набора не теряется в UI
    expect(parseNum("1.")).toBe(1);
  });
  it("мусор/отрицательное → undefined", () => {
    expect(parseNum("abc")).toBeUndefined();
    expect(parseNum("-3")).toBeUndefined();
  });
});
