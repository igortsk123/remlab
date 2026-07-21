import { describe, it, expect, vi, afterEach } from "vitest";
import { aiExtractSpec } from "@/lib/calc/link-parse-ai";

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

const okFetch = (content: unknown) =>
  vi.fn(async () => ({ ok: true, json: async () => ({ choices: [{ message: { content: JSON.stringify(content) } }] }) }));

describe("aiExtractSpec — ИИ-фолбэк OpenAI", () => {
  it("без ключа OPENAI_API_KEY → {} (тихо)", async () => {
    vi.stubEnv("OPENAI_API_KEY", "");
    expect(await aiExtractSpec("текст страницы", "oboi", ["rollWidthM"])).toEqual({});
  });

  it("берёт только валидные числовые нужные поля; null/строку/лишнее — отбрасывает", async () => {
    vi.stubEnv("OPENAI_API_KEY", "sk-test");
    vi.stubGlobal("fetch", okFetch({ rollWidthM: 1.06, rollLengthM: null, rapportM: "нет", pricePerRollRub: 2650, tileLengthMm: 300 }));
    const out = await aiExtractSpec("текст", "oboi", ["rollWidthM", "rollLengthM", "rapportM", "pricePerRollRub"]);
    expect(out).toEqual({ rollWidthM: 1.06, pricePerRollRub: 2650 });
  });

  it("ошибка сети → {} (без падения)", async () => {
    vi.stubEnv("OPENAI_API_KEY", "sk-test");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("net"); }));
    expect(await aiExtractSpec("t", "plitka", ["tileLengthMm"])).toEqual({});
  });
});
