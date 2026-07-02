import { describe, it, expect, beforeAll } from "vitest";
import { repo } from "@/modules/store/repository";
import { runPreview } from "@/modules/generation-job";
import { traceStore } from "@/lib/trace/store";
import { project as projectSchema } from "@/contracts/project";
import { styleProfile as styleProfileSchema } from "@/contracts/style";

// Трейсинг (ADR-0013): один прогон превью пишет run + шаги + ассеты, у проекта есть «номер генерации».
const PNG_DATA_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

beforeAll(() => {
  process.env.REMLAB_FAKE_AI = "1";
});

describe("pipeline tracing (fake AI)", () => {
  it("runPreview создаёт прогон с шагами и номером генерации", async () => {
    const now = new Date().toISOString();
    const p = projectSchema.parse({
      id: "trace-project-1",
      sessionId: "s-trace",
      title: "Гостиная",
      status: "style_done",
      createdAt: now,
      updatedAt: now,
      brief: { roomType: "living_room", goal: "refresh", interventionLevel: "refresh", budgetBand: "30_70" },
      photos: [{ id: "ph1", mimeType: "image/png", dataUrl: PNG_DATA_URL }],
      styleProfile: styleProfileSchema.parse({ selectedStyleIds: ["scandinavian"] }),
    });
    await repo().create(p);

    const result = await runPreview("trace-project-1");
    expect(result).not.toBeNull();
    expect(result!.generationSeq).toBeGreaterThan(0);
    expect(result!.traceRunId).toBeTruthy();

    // Разбор по номеру: прогон найден, есть все три шага (analyze, restyle, ideas), выход у restyle.
    const run = await traceStore().getRunBySeq(result!.generationSeq!);
    expect(run).not.toBeNull();
    expect(run!.status).toBe("ok");

    const steps = await traceStore().getStepsByRun(run!.id);
    const names = steps.map((s) => s.stepName);
    expect(names).toContain("analyze");
    expect(names).toContain("restyle");
    expect(names).toContain("ideas");
    // Каждый шаг знает свою модель и промпт (для сравнения тестов).
    expect(steps.every((s) => s.model.length > 0)).toBe(true);
    expect(steps.find((s) => s.stepName === "restyle")!.promptId).toBe("restyle");

    // Ассеты: есть вход и выход (картинки сохранены на диск, ссылки в БД).
    const assets = await traceStore().getAssetsByRun(run!.id);
    expect(assets.some((a) => a.role === "input")).toBe(true);
    expect(assets.some((a) => a.role === "output")).toBe(true);
  });
});
