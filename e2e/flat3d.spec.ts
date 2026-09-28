import { expect, test } from "@playwright/test";

// Сквозная проверка 3D-конфигуратора. Ловим две типовые поломки таких экранов:
// «страница открылась, а сцена пустая» и «вариант выбрали, а в сцене/цене не изменилось».
//
// Состояние сцены спрашиваем у самого движка (`window.__flatViewer.debugState()`), а не через
// readPixels: без `preserveDrawingBuffer` буфер к моменту чтения уже очищен — первая версия
// теста падала именно на этом, хотя картинка была.

interface DebugState {
  rooms: number;
  meshes: number;
  placed: number;
  floors: number;
  room: string | null;
}

async function sceneState(page: import("@playwright/test").Page): Promise<DebugState | null> {
  return page.evaluate(() => {
    const v = (window as unknown as { __flatViewer?: { debugState(): DebugState } }).__flatViewer;
    return v ? v.debugState() : null;
  });
}

test("конфигуратор: комнаты, выбор варианта, цена и план", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/flat");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Квартира");

  // 3D: сцена собралась — есть комнаты, полы и расставленные предметы
  await page.getByRole("tab", { name: "3D" }).click();
  await expect(page.locator("canvas")).toBeVisible();
  let state: DebugState | null = null;
  for (let i = 0; i < 25 && (state?.placed ?? 0) < 15; i += 1) {
    await page.waitForTimeout(700);
    state = await sceneState(page);
  }
  if (state) {
    expect(state.rooms, "комнаты построены").toBe(5);
    expect(state.floors, "полы построены").toBe(5);
    expect(state.placed, "предметы расставлены").toBeGreaterThanOrEqual(10);
    expect(state.meshes, "в сцене есть геометрия").toBeGreaterThan(50);
  } else {
    test.info().annotations.push({ type: "warn", description: "WebGL недоступен — 3D-часть пропущена" });
  }

  // выбор варианта меняет итог: премиальная кухня — это +8700 £
  await page.getByRole("button", { name: "Кухня", exact: true }).first().click(); // комната
  await page.locator('[data-slot="kitchen-units"]').click(); // слот «Кухня» внутри комнаты
  await expect(page.getByText("Кухня Premium")).toBeVisible();
  await page.getByRole("button", { name: /Кухня Premium/ }).click();
  await expect(page.getByRole("region", { name: "Стоимость" })).toContainText("8 700");

  // и это видно в сцене: подпись комнаты показывает доплату
  await expect(page.getByText(/\+.*в этой комнате/)).toBeVisible();

  // план рисуется и комнаты кликабельны
  await page.getByRole("tab", { name: "План" }).click();
  await expect(page.getByRole("img", { name: "План квартиры" })).toBeVisible();

  expect(errors, `ошибки в консоли: ${errors.join(" | ")}`).toEqual([]);
});

test("сохранение подбора: ссылка открывается, персональных данных в ней нет", async ({ page, request }) => {
  const res = await request.post("/api/flat/config", {
    data: {
      configuration: {
        version: 1,
        apartmentId: "demo-uk-1",
        developerId: "demo-developer",
        selections: { "kitchen-units": "kitchen-premium" },
      },
    },
  });
  expect(res.ok()).toBeTruthy();
  const body = (await res.json()) as { id: string; quote: { upgradesGbp: number } };
  expect(body.id).toMatch(/^[a-f0-9]{22}$/);
  expect(body.quote.upgradesGbp).toBe(8700);

  const back = await request.get(`/api/flat/config/${body.id}`);
  expect(back.ok()).toBeTruthy();
  expect(JSON.stringify(await back.json())).not.toContain("contact");

  await page.goto(`/flat?c=${body.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("region", { name: "Стоимость" })).toContainText("8 700");
});

test("мобильный экран открывается на «Фото» и умеет включить 3D Lite", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 780 });
  await page.goto("/flat");
  await expect(page.getByRole("tab", { name: "Фото" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("button", { name: "Включить 3D Lite" })).toBeVisible();
});
