import { describe, it, expect, beforeAll } from "vitest";
import { repo } from "@/modules/store/repository";
import { runAnalyze, runGenerate } from "@/modules/generation-job";
import { project as projectSchema } from "@/contracts/project";
import { styleProfile as styleProfileSchema } from "@/contracts/style";

// Интеграция ядра flow на фейковом ИИ: проект с фото → runPreview → превью+идеи+каталог+бюджет.
const PNG_DATA_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

beforeAll(() => {
  process.env.REMLAB_FAKE_AI = "1";
});

describe("flow pipeline (fake AI)", () => {
  it("runAnalyze+runGenerate заполняют разбор, превью, идеи, каталог и бюджет", async () => {
    const now = new Date().toISOString();
    const p = projectSchema.parse({
      id: "test-project-1",
      sessionId: "s1",
      title: "Гостиная",
      status: "style_done",
      createdAt: now,
      updatedAt: now,
      brief: { roomType: "living_room", goal: "refresh", interventionLevel: "refresh", budgetBand: "30_70" },
      photos: [{ id: "ph1", mimeType: "image/png", dataUrl: PNG_DATA_URL }],
      styleProfile: styleProfileSchema.parse({ selectedStyleIds: ["scandinavian"] }),
    });
    await repo().create(p);

    // Этап 1 — разбор фото на объекты (до выбора пользователя).
    const analysis = await runAnalyze("test-project-1");
    expect(analysis).not.toBeNull();
    expect(analysis!.summary.length).toBeGreaterThan(0);
    expect(analysis!.objects.length).toBeGreaterThan(0);

    // Этап 2 — генерация по выбору (в тесте берём дефолт = предложение модели).
    const result = await runGenerate("test-project-1");
    expect(result).not.toBeNull();
    expect(result!.status).toBe("preview_ready");
    expect(result!.previewImage).toBeTruthy();
    expect(result!.ideas.length).toBeGreaterThanOrEqual(3);

    // каталог: есть и товары, и материалы; часть заблокирована.
    const kinds = new Set(result!.items.map((i) => i.kind));
    expect(kinds.has("product")).toBe(true);
    expect(kinds.has("material")).toBe(true);
    expect(result!.items.some((i) => i.locked)).toBe(true);
    expect(result!.items.some((i) => !i.locked)).toBe(true);

    // бюджет посчитан из диапазона банда.
    expect(result!.budget!.maxRub).toBeGreaterThan(result!.budget!.minRub);
  });
});
