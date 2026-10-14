import { describe, expect, it } from "vitest";

import { firstGatewayImage, firstGatewayText } from "@/lib/providers/gateway";

// Gemini через шлюз Vercel (ADR-0277): картинка приходит в message.images data-URL'ом, текст — в content.
describe("ответ шлюза", () => {
  it("достаёт картинку из data URL и текст", () => {
    const r = { choices: [{ message: { content: "ok", images: [{ type: "image_url", image_url: { url: "data:image/png;base64,QUJD" } }] } }] };
    expect(firstGatewayImage(r)).toEqual({ mimeType: "image/png", base64: "QUJD" });
    expect(firstGatewayText(r)).toBe("ok");
  });
  it("пустой ответ — null, а не мусор", () => {
    expect(firstGatewayImage({ choices: [{ message: { content: "" } }] })).toBeNull();
    expect(firstGatewayText({ choices: [{ message: { content: "" } }] })).toBeNull();
  });
});
