import { describe, it, expect } from "vitest";
import { styleResultRepo } from "@/modules/style/repository";

// Без DATABASE_URL фабрика отдаёт in-memory реализацию — её и проверяем
// (Pg-вариант покрыт тем же интерфейсом; интеграционно — на проде).

describe("styleResultRepo — результат игры «узнай свой вкус»", () => {
  it("пустая сессия → null", async () => {
    expect(await styleResultRepo().get("nobody")).toBeNull();
  });

  it("upsert сохраняет стиль, повторная игра перезаписывает", async () => {
    const repo = styleResultRepo();
    await repo.upsert("s1", "japandi");
    expect((await repo.get("s1"))?.style).toBe("japandi");
    await repo.upsert("s1", "loft");
    expect((await repo.get("s1"))?.style).toBe("loft");
  });

  it("сессии изолированы: чужой стиль не виден", async () => {
    const repo = styleResultRepo();
    await repo.upsert("s2", "scandi");
    expect((await repo.get("s3"))).toBeNull();
  });
});
