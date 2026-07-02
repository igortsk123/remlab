import { describe, it, expect } from "vitest";
import { restylePrompt } from "@/lib/prompts/registry";
import { styleProfile as styleProfileSchema } from "@/contracts/style";

// Ключевая гарантия нового флоу: выбор пользователя по объектам + пожелание попадают В ПРОМПТ генерации.
describe("restylePrompt.build (выбор пользователя управляет генерацией)", () => {
  const style = styleProfileSchema.parse({ selectedStyleIds: ["loft"] });

  it("вшивает действия по объектам и пожелание", () => {
    const prompt = restylePrompt.build({
      style,
      brief: { interventionLevel: "budget_update" },
      choices: [
        { label: "Диван", action: "change" },
        { label: "Пол", action: "keep" },
        { label: "Ковёр", action: "remove" },
      ],
      wish: "тёплые бежевые тона и дерево",
    });
    expect(prompt).toContain("Поменять: Диван");
    expect(prompt).toContain("Оставить без изменений: Пол");
    expect(prompt).toContain("Убрать из кадра: Ковёр");
    expect(prompt).toContain("Пожелания пользователя: тёплые бежевые тона и дерево");
    expect(restylePrompt.version).toBe("v2");
  });

  it("без выбора и пожелания — не добавляет пустые секции", () => {
    const prompt = restylePrompt.build({ style, brief: {} });
    expect(prompt).not.toContain("Поменять:");
    expect(prompt).not.toContain("Пожелания пользователя:");
  });
});
