import { expect, type Page } from "@playwright/test";

// ОКНО ВАРИАНТА В ЖИВЫХ ПРОВЕРКАХ — ОБЩИЙ ВХОД (T-20261119-115/2, разбор «почему 7 ночей красные»).
// Что поменялось на странице, а проверки остались прежними (`tools/scout/flat215-demo/index.html`):
//  • «Фото» — это и рендер Blender, и улучшенное нейросетью (`vwIsPhoto`, T-20261117-20/2): окно варианта, у которого есть любой кадр
//    рендера, открывается в «Фото» (`openLiveWindow`), а не в «3D». Отфильтровать только `quality === 'realistic'` значило оставить
//    рендер — окно оставалось в «Фото», живая сцена не запускалась, ожидание `LIVE.state === 'ready'` кончалось таймаутом;
//  • главная кнопка шторки (`vwCtaKind`): «Сделать фото» — только в «3D» и только пока фото расстановки нет; «Улучшить фото» — в «Фото»,
//    пока показан рендер без улучшения; на малом телефоне это значок (`vico`), подпись — в `title`/`aria-label`;
//  • «Сделать фото» в «3D» — два нажатия: первое открывает окошки ракурсов («Снять эти ракурсы»), второе заказывает рендер (`vwPickCta`).
// Заказы рендера идут в `/api/render/cycles` — проверки их подменяют (`routeCycles`): ни заказа, ни расхода на проде не возникает.

/** Живая сцена построена и показана. */
export const LIVE_READY = "!!LIVE.scene && LIVE.state === 'ready'";

/** Окно варианта — в «3D», сцена готова. Заказ рендера и «Улучшить» нужны из «3D», пины и геометрия сцены — только там. */
export async function enter3D(page: Page, timeout = 120_000): Promise<void> {
  await page.evaluate("if (VW.mode !== 'walk') vwMode('walk')");
  await page.waitForFunction(LIVE_READY, null, { timeout });
}

/** Подпись главной кнопки шторки: на малом телефоне — `title`/`aria-label` значка (текста нет), иначе — текст кнопки. */
export async function ctaLabel(page: Page): Promise<string> {
  return (await page.evaluate(() => {
    const c = document.getElementById("vCta");
    return c ? (c.getAttribute("aria-label") || c.title || c.innerText || "").trim() : "";
  })) as string;
}

/** Заказ рендера, пойманный подменой: тело запроса (без `check`). */
export type CyclesOrders = unknown[];

/**
 * `/api/render/cycles` без обращения к проду: вопрос «готово ли» (`check`, его задаёт окно варианта без фото — `vwPeekCached`) — «нет»
 * (у настоящего варианта прод может отдать кэш заготовки, и окно уйдёт в «Фото» — тест «варианта без фото» зависел бы от данных ночи);
 * заказ — подменённое задание, тело — в `orders`.
 */
export async function routeCycles(page: Page, orders: CyclesOrders = []): Promise<CyclesOrders> {
  await page.route(/\/api\/render\/cycles(\?.*)?$/, async (r) => {
    if (r.request().method() !== "POST") return r.continue();
    let b: { check?: boolean } = {};
    try { b = JSON.parse(r.request().postData() || "{}") as { check?: boolean }; } catch { /* не JSON */ }
    if (b.check) return r.fulfill({ json: { cached: false, status: "none" } });
    orders.push(b);
    return r.fulfill({ json: { job: "t115-render-" + Date.now(), status: "queued", queue: 0, eta: 25 } });
  });
  return orders;
}

/** Ответы `/api/job` подменённого фото по этапам (задание рендера: `status`/`frames`; «Улучшить» — прежний ответ `shots`). */
export type PhotoStage = "render-run" | "render-done" | "improve-run" | "improve-done";
export const FAKE_FRAMES = ["/demo/img/og.jpg", "/demo/img/og.jpg?v=2"];
export function photoJob(stage: PhotoStage): unknown {
  switch (stage) {
    case "render-run": return { status: "running", percent: 40, eta: 20, eta_range: [15, 30] };
    case "render-done": return { status: "done", key: "c".repeat(64), frames: FAKE_FRAMES.map((url, i) => ({ camera: `C${i + 1}`, url, id: String(i + 1).repeat(64) })) };
    case "improve-run": return { status: "running", eta: 30 };
    case "improve-done": return { shots: FAKE_FRAMES.map((url, i) => ({ camera: `C${i + 1}`, url })), backend: "fake" };
  }
}

/**
 * Окно варианта БЕЗ фото: убираем из реестра все фото (рендер и улучшенное), открываем окно — «3D», сцена готова, кнопка «Сделать фото».
 * (`shots` — глобал страницы; `vwIsPhoto` — её же предикат «это фото»). Кэш заготовки не подмешивается — см. `routeCycles`.
 */
export async function openWithoutPhoto(page: Page): Promise<void> {
  await page.evaluate("shots = shots.filter((x) => !vwIsPhoto(x)); openLiveWindow()");
  await enter3D(page);
}

/** «Сделать фото» из «3D»: два нажатия — «Снять эти ракурсы», затем заказ (`vwPickCta`); подпись между ними проверяется. */
export async function orderRender(page: Page): Promise<void> {
  const cta = page.locator("#vCta");
  await expect(cta).toBeVisible();
  expect(await ctaLabel(page)).toMatch(/Сделать фото/);
  await cta.click();
  await expect.poll(() => ctaLabel(page)).toMatch(/Снять эти ракурсы/);
  await cta.click();
}
