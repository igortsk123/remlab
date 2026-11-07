import { expect, type Page } from "@playwright/test";

// ГЛАВНАЯ ДЕМО БЕЗ ВКЛАДОК СТИЛЕЙ (план home-mix-01 шаг 5, T-20261107-35): вместо ленты `#styleTabs` — переключатель
// «Интерьер / План квартиры» (`#hmView`), строка «<стиль> · рекомендуем · Выбрать другой» (`#hmMix`) и окно выбора `#mixBox`
// (`tools/scout/flat215-demo/index.html:mixOpen`). Проверкам «по каждому стилю» нужны список стилей и смена выбора — здесь.

/** Главная готова: данные, карточка квартиры, стили и строка выбранного варианта. */
export const HOME_READY =
  "typeof homeModel === 'function' && !!D && !!FLAT && homeModel().styles.length > 0 && !!document.getElementById('hmMix')";

export type HomeStyle = { id: string; title: string };

/** Стили главной по порядку (бывшие вкладки): id и название. */
export async function homeStyles(page: Page): Promise<HomeStyle[]> {
  return (await page.evaluate("homeModel().styles.map((s) => ({ id: s.id, title: s.title }))")) as HomeStyle[];
}

/** Основной выбранный стиль квартиры (`homeSel`). */
export async function homeMain(page: Page): Promise<string> {
  return (await page.evaluate("homeSel(homeModel()).selected[0] || ''")) as string;
}

/**
 * Квартира в одном стиле — путь нажатия на стиль в окне «Выбрать другой» (`mixApply`: раскладка, адрес, прокрутка к комнатам,
 * событие). Для обхода КАЖДОГО стиля: в окне есть только варианты с фото нейросети гостиной.
 */
export async function pickStyle(page: Page, id: string): Promise<void> {
  await page.evaluate((s) => (window as unknown as { __mixApply: (ids: string[]) => void }).__mixApply([s]), id);
  await expect.poll(() => homeMain(page)).toBe(id);
}

/**
 * То же через окно выбора стиля всей квартиры: открыть его (`__mixOpen` — кнопки «Выбрать другой» на главной нет с 07.11, владелец
 * TG 514, T-20261107-63) → нажать плитку `at` (номер по порядку в окне, с 0) — окно закрывается, выбор сразу (один выбор, TG 451).
 * Возвращает id выбранного стиля.
 */
export async function pickInWindow(page: Page, at: number): Promise<string> {
  await page.evaluate(() => (window as unknown as { __mixOpen: () => void }).__mixOpen());
  const box = page.locator("#mixBox");
  await expect(box).toHaveClass(/\bon\b/);
  await expect(box.locator(".qz-ph").first()).toBeEnabled({ timeout: 20_000 });   // кадры пришли — плитки нажимаются
  const t = box.locator(".qz-ph").nth(at);
  const id = (await t.getAttribute("data-mx-ph")) ?? "";
  await t.click();
  await expect(box).not.toHaveClass(/\bon\b/);
  return id;
}
