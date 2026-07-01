import { describe, it, expect, vi, afterEach } from "vitest";
import { createGeminiProvider } from "@/lib/providers/gemini";

// Юнит-тесты провайдера на замоканном fetch — без сети, гоняются в CI.
// Реальный вызов проверяет tools/smoke-providers.mjs (pnpm smoke:providers).

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

afterEach(() => vi.unstubAllGlobals());

const p = createGeminiProvider("test-key");

describe("gemini provider", () => {
  it("generateText: достаёт текст из ответа", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { candidates: [{ content: { parts: [{ text: "hello" }] } }] }));
    const r = await p.generateText("hi");
    expect(r).toEqual({ ok: true, value: "hello" });
  });

  it("generateImage: достаёт inlineData как картинку", async () => {
    const body = { candidates: [{ content: { parts: [{ inlineData: { mimeType: "image/jpeg", data: "AAA" } }] } }] };
    vi.stubGlobal("fetch", mockFetch(200, body));
    const r = await p.generateImage({ prompt: "room" });
    expect(r).toEqual({ ok: true, value: { mimeType: "image/jpeg", base64: "AAA" } });
  });

  it("HTTP-ошибка → err kind=http со статусом", async () => {
    vi.stubGlobal("fetch", mockFetch(429, {}));
    const r = await p.generateText("hi");
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.error.kind).toBe("http");
      expect(r.error.status).toBe(429);
    }
  });

  it("пустой ответ → err kind=parse", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { candidates: [] }));
    const r = await p.generateImage({ prompt: "room" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error.kind).toBe("parse");
  });

  it("сетевой сбой → err kind=network", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    const r = await p.generateText("hi");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error.kind).toBe("network");
  });
});
