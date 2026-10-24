import { describe, it, expect, vi, afterEach } from "vitest";
import { aiExtractSpec } from "@/lib/calc/link-parse-ai";

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.restoreAllMocks(); });

const okFetch = (content: unknown) =>
  vi.fn(async (_url: string, _init?: RequestInit) => ({ ok: true, json: async () => ({ choices: [{ message: { content: JSON.stringify(content) } }] }) }));

// ИИ-ДОЧИТКА ПОЛЕЙ ТОВАРА — ЧЕРЕЗ ШЛЮЗ VERCEL (T-20261023-12): прямой ключ OpenAI пуст и пополняться не будет. Запрос уходит
// на шлюз с ключом шлюза и моделью `openai/gpt-4o-mini`; любая неудача — {} и строка в лог (не молча).
describe("aiExtractSpec — ИИ-фолбэк через шлюз Vercel", () => {
  it("без ключа шлюза → {} и строка в лог; в сеть не ходит", async () => {
    vi.stubEnv("VERCEL_AI_GATEWAY_KEY", "");
    const f = vi.fn(); vi.stubGlobal("fetch", f);
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(await aiExtractSpec("текст страницы", "oboi", ["rollWidthM"])).toEqual({});
    expect(f).not.toHaveBeenCalled();
    expect(String(log.mock.calls[0]?.join(" "))).toMatch(/\[link-parse-ai\].*VERCEL_AI_GATEWAY_KEY/);
  });

  it("зовёт шлюз (не api.openai.com) ключом шлюза, модель openai/gpt-4o-mini, JSON и температура 0", async () => {
    vi.stubEnv("VERCEL_AI_GATEWAY_KEY", "gw-test");
    vi.stubEnv("OPENAI_API_KEY", "");
    const f = okFetch({ rollWidthM: 1.06 }); vi.stubGlobal("fetch", f);
    expect(await aiExtractSpec("текст", "oboi", ["rollWidthM"])).toEqual({ rollWidthM: 1.06 });
    const [url, init] = f.mock.calls[0]!;
    expect(url).toBe("https://ai-gateway.vercel.sh/v1/chat/completions");
    expect((init!.headers as Record<string, string>).Authorization).toBe("Bearer gw-test");
    const body = JSON.parse(String(init!.body));
    expect(body.model).toBe("openai/gpt-4o-mini");
    expect(body.temperature).toBe(0);
    expect(body.response_format).toEqual({ type: "json_object" });
    expect(body.messages[0].content[0].text).toContain("rollWidthM");
  });

  it("берёт только валидные числовые нужные поля; null/строку/лишнее — отбрасывает", async () => {
    vi.stubEnv("VERCEL_AI_GATEWAY_KEY", "gw-test");
    vi.stubGlobal("fetch", okFetch({ rollWidthM: 1.06, rollLengthM: null, rapportM: "нет", pricePerRollRub: 2650, tileLengthMm: 300 }));
    const out = await aiExtractSpec("текст", "oboi", ["rollWidthM", "rollLengthM", "rapportM", "pricePerRollRub"]);
    expect(out).toEqual({ rollWidthM: 1.06, pricePerRollRub: 2650 });
  });

  it("шлюз без денег (HTTP 402) → {} и строка в лог с кодом и моделью", async () => {
    vi.stubEnv("VERCEL_AI_GATEWAY_KEY", "gw-test");
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 402, json: async () => ({}) })));
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(await aiExtractSpec("t", "plitka", ["tileLengthMm"])).toEqual({});
    expect(String(log.mock.calls[0]?.join(" "))).toMatch(/\[link-parse-ai\] http http_402 \(model=openai\/gpt-4o-mini\)/);
  });

  it("ошибка сети → {} (без падения) и строка в лог", async () => {
    vi.stubEnv("VERCEL_AI_GATEWAY_KEY", "gw-test");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("net"); }));
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(await aiExtractSpec("t", "plitka", ["tileLengthMm"])).toEqual({});
    expect(log).toHaveBeenCalled();
  });

  it("EXTRACT_MODEL — другая модель шлюза", async () => {
    vi.stubEnv("VERCEL_AI_GATEWAY_KEY", "gw-test");
    vi.stubEnv("EXTRACT_MODEL", "openai/gpt-4.1-mini");
    const f = okFetch({}); vi.stubGlobal("fetch", f);
    await aiExtractSpec("t", "kraska", ["packVolumeL"]);
    expect(JSON.parse(String(f.mock.calls[0]![1]!.body)).model).toBe("openai/gpt-4.1-mini");
  });
});
