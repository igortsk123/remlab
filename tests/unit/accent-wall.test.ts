import { describe, expect, it } from "vitest";

import { resolveAccentSide } from "@/lib/configurator/accent";

// demo-07: акцентная стена «за диваном» — по направлению спинки (rot 0 — лицом в +y), спорное — ближняя стена
describe("акцентная стена за диваном", () => {
  const room = { id: "living", kind: "living", titleRu: "", titleEn: "", x: 0, y: 0, w: 439, d: 325, heightCm: 270, openings: [] } as never;
  it("спинка к стене по повороту", () => {
    expect(resolveAccentSide(room, { x: 200, y: 50, rot: 0 })).toBe("south");
    expect(resolveAccentSide(room, { x: 200, y: 280, rot: 180 })).toBe("north");
    expect(resolveAccentSide(room, { x: 40, y: 160, rot: 90 })).toBe("west");
    expect(resolveAccentSide(room, { x: 400, y: 160, rot: 270 })).toBe("east");
  });
  it("переставили диван — акцент переезжает", () => {
    expect(resolveAccentSide(room, { x: 200, y: 50, rot: 0 })).not.toBe(resolveAccentSide(room, { x: 200, y: 280, rot: 180 }));
  });
});
