import { promises as fs } from "node:fs";
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import postgres from "postgres";
import { TRIAL_BASE, TRIAL_DB, TRIAL_TOKEN } from "./trial-env";

// Проба для агентов (agent-trial-01, T-C; agent-trial-08 — серый тур снят, два языка): загрузка → задание в базе →
// поддельный воркер (ручки `/api/trial/worker/*` с тестовым токеном) двигает шаги и отдаёт результат по фикстуре → «готово»
// и переход в тур `/try/<id>/tour/?lang=…` (сам тур — другая ветка, здесь проверяем адрес). Плюс тексты: ошибка задания,
// «машина занята», масштаб не подтверждён, RU/EN и выбор языка. Отдельный сервер приложения на ТЕСТОВОЙ базе
// (`playwright.config.ts`, TEST_DATABASE_URL — как у юнит-тестов в CI); без неё пропускается.
test.skip(!TRIAL_DB, "нужна TEST_DATABASE_URL");
test.describe.configure({ mode: "serial" }); // воркер в тесте берёт задание из общей очереди — по одному

const FIXTURE = path.join(process.cwd(), "tests/fixtures/trial-result-A.json");
const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(4000, 7)]);
const AUTH = { Authorization: `Bearer ${TRIAL_TOKEN}` };
let pg: ReturnType<typeof postgres>;

test.beforeAll(async () => {
  pg = postgres(TRIAL_DB!, { max: 2, onnotice: () => undefined });
  const dir = path.join(process.cwd(), "db/init");
  await pg.begin(async (tx) => {
    await tx`select pg_advisory_xact_lock(2026110999)`; // тот же замок, что у tests/unit/trial-claim.test.ts
    for (const f of (await fs.readdir(dir)).filter((n) => /^\d{3}-.*\.sql$/.test(n)).sort()) {
      await tx.unsafe(await fs.readFile(path.join(dir, f), "utf8"));
    }
  });
  // хвосты прошлых прогонов не должны попасть воркеру теста раньше своего задания
  await pg`update trial_jobs set status = 'cancelled', finished_at = now(), lease_until = null where status in ('queued', 'running')`;
});
test.afterAll(async () => { await pg?.end(); });

/** Свой адрес на тест: лимит загрузок (3 за 10 мин с адреса) не копится между тестами и повторами. */
const ip = () => `10.9.${Math.floor(Math.random() * 250)}.${Math.floor(Math.random() * 250)}`;
const UP = {
  en: { h1: "Turn a floor plan into a furnished 3D tour in minutes", sizes: "Room sizes from the listing",
    open: "Add room measurements if you have them", button: "Upload a floor plan" },
  ru: { h1: "План квартиры — в 3D\u2011тур с мебелью за несколько минут", sizes: "Размеры комнат из объявления",
    open: "Добавьте размеры комнат, если они есть", button: "Загрузить план" },
};
async function upload(page: Page, listing = "Lounge 3.77 x 4.20 m", lang: "en" | "ru" = "en"): Promise<string> {
  const t = UP[lang];
  await page.setExtraHTTPHeaders({ "x-forwarded-for": ip() });
  await page.goto(lang === "en" ? `${TRIAL_BASE}/try` : `${TRIAL_BASE}/try?lang=ru`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.h1);
  await page.locator('input[type="file"]').setInputFiles({ name: "plan-D.png", mimeType: "image/png", buffer: PNG });
  await expect(page.getByText("plan-D.png")).toBeVisible();
  const sizes = page.getByLabel(t.sizes);
  if (!(await sizes.isVisible())) await page.getByText(t.open).click(); // узкий экран — свёрнуто
  await sizes.fill(listing);
  await page.locator("form").getByRole("button", { name: t.button }).click();
  await page.waitForURL(new RegExp(`/try/[A-Za-z0-9_-]{22}\\?lang=${lang}$`), { timeout: 15_000 }); // язык идёт дальше
  return new URL(page.url()).pathname.split("/").pop()!;
}

async function claim(api: APIRequestContext, id: string) {
  const r = await api.post(`${TRIAL_BASE}/api/trial/worker/claim`, { headers: AUTH, data: { workerId: "e2e-worker", version: "e2e" } });
  expect(r.status()).toBe(200);
  const { job } = (await r.json()) as { job: { id: string; attempt: number; leaseToken: string } | null };
  expect(job?.id).toBe(id);
  return { id, attempt: job!.attempt, leaseToken: job!.leaseToken };
}

const stepState = (page: Page, title: string) => page.getByRole("list", { name: "Progress" }).locator("li", { hasText: title });

async function finish(api: APIRequestContext, lease: { id: string; attempt: number; leaseToken: string }, result: unknown) {
  const r = await api.post(`${TRIAL_BASE}/api/trial/worker/result`, { headers: AUTH, data: { ...lease, result, spentUsd: 0.04 } });
  expect(r.status()).toBe(200);
}

// Next срезает косую в конце (`/tour/` → `/tour`); страница тура возвращает её сама (ветка worktree-demo-template, `injectTour`)
const tourUrl = (id: string, lang: string) => new RegExp(`/try/${id}/tour/?\\?lang=${lang}$`);

test("загрузка → задание в базе → шаги → готово → переход в тур", async ({ page, request }) => {
  const id = await upload(page);
  const [row] = await pg`select status, listing_text, input_mime, input_path from trial_jobs where id = ${id}`;
  expect(row).toMatchObject({ status: "queued", listing_text: "Lounge 3.77 x 4.20 m", input_mime: "image/png" });
  expect(row!.input_path).toMatch(new RegExp(`^${id}\\.png$`));
  await expect(page.getByTestId("trial-wait").getByText("Getting your tour ready")).toBeVisible();
  await expect(stepState(page, "Plan received")).toHaveAttribute("data-state", "done");
  await expect(stepState(page, "Plan received")).toContainText("plan-D.png"); // имя файла, как в образце лендинга
  await expect(stepState(page, "Rooms and sizes read")).toHaveAttribute("data-state", "next"); // в очереди не крутится

  const lease = await claim(request, id);
  for (const stage of ["raster", "labels", "walls"] as const) {
    const r = await request.post(`${TRIAL_BASE}/api/trial/worker/heartbeat`, { headers: AUTH, data: { ...lease, stage } });
    expect(r.status()).toBe(200);
  }
  await expect(stepState(page, "3D ready")).toHaveAttribute("data-state", "run");
  await expect(stepState(page, "Rooms and sizes read")).toHaveAttribute("data-state", "done");
  await expect(page.getByTestId("trial-wait").getByLabel("Time since upload")).toHaveText(/^\d\d:\d\d$/);

  await finish(request, lease, JSON.parse(await fs.readFile(FIXTURE, "utf8")));
  const done = page.getByTestId("trial-done");
  await expect(done.getByRole("heading", { name: "Your 3D is ready" })).toBeVisible({ timeout: 10_000 });
  await expect(stepState(page, "3D ready")).toHaveAttribute("data-state", "done");
  await expect(done.getByRole("link", { name: "Open the tour" })).toHaveAttribute("href", `/try/${id}/tour/?lang=en`);
  await expect(done.getByText(/rooms$/)).toBeVisible(); // сводка из результата: «Ready in м:сс · N rooms»
  await expect(page.getByText("Scale not verified.")).toHaveCount(0);
  await expect(page.getByTestId("grey-tour")).toHaveCount(0); // серого тура больше нет
  await page.waitForURL(tourUrl(id, "en"), { timeout: 10_000 }); // сам, без нажатия
  expect((await pg`select status from trial_jobs where id = ${id}`)[0]!.status).toBe("done");
});

test("масштаб не подтверждён → плашка «Scale not verified» перед переходом", async ({ page, request }) => {
  const id = await upload(page, "");
  const lease = await claim(request, id);
  const result = JSON.parse(await fs.readFile(FIXTURE, "utf8")) as { scale: Record<string, unknown> };
  result.scale = { status: "not_verified", ppm: null, inliers: 0, n: 0 };
  await finish(request, lease, result);
  await expect(page.getByText("Scale not verified.")).toBeVisible({ timeout: 10_000 });
  await page.waitForURL(tourUrl(id, "en"), { timeout: 10_000 });
});

test("по-русски: форма → ожидание → готово → тур на русском", async ({ page, request }) => {
  const id = await upload(page, "Гостиная 3,77 × 4,20 м", "ru");
  await expect(page.locator('[lang="ru"]').first()).toBeAttached();
  const wait = page.getByTestId("trial-wait");
  await expect(wait.getByText("Готовим ваш тур")).toBeVisible();
  await expect(wait.getByLabel("Время с загрузки")).toHaveText(/^\d\d:\d\d$/);
  const step = (title: string) => page.getByRole("list", { name: "Ход работы" }).locator("li", { hasText: title });
  await expect(step("План получен")).toHaveAttribute("data-state", "done");
  await expect(page.getByText("Ждать здесь не обязательно")).toBeVisible();
  const lease = await claim(request, id);
  const r = await request.post(`${TRIAL_BASE}/api/trial/worker/heartbeat`, { headers: AUTH, data: { ...lease, stage: "walls" } });
  expect(r.status()).toBe(200);
  await expect(step("3D готово")).toHaveAttribute("data-state", "run");
  const result = JSON.parse(await fs.readFile(FIXTURE, "utf8")) as { scale: Record<string, unknown> };
  result.scale = { status: "not_verified", ppm: null, inliers: 0, n: 0 };
  await finish(request, lease, result);
  const done = page.getByTestId("trial-done");
  await expect(done.getByRole("heading", { name: "3D готово" })).toBeVisible({ timeout: 10_000 });
  await expect(done.getByText("Масштаб не подтверждён.")).toBeVisible();
  await expect(done.getByRole("link", { name: "Открыть тур" })).toHaveAttribute("href", `/try/${id}/tour/?lang=ru`);
  await page.waitForURL(tourUrl(id, "ru"), { timeout: 10_000 });
});

test("задание не удалось → понятный текст и путь назад", async ({ page, request }) => {
  const id = await upload(page);
  const lease = await claim(request, id);
  const r = await request.post(`${TRIAL_BASE}/api/trial/worker/fail`, {
    headers: AUTH, data: { ...lease, code: "no_plan", retryable: false, detail: "e2e: no walls found" },
  });
  expect(r.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "We couldn't build this tour" })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/couldn't find a floor plan in this file/)).toBeVisible();
  await expect(page.getByText("e2e: no walls found")).toHaveCount(0); // подробности — только в базе
  await expect(page.getByRole("main").getByRole("link", { name: "Upload a floor plan" })).toHaveAttribute("href", "/try?lang=en");
});

test("машина не на связи → «busy right now», задание ждёт", async ({ page }) => {
  await pg`update trial_workers set last_seen = now() - interval '1 hour'`;
  const id = await upload(page);
  await expect(page.getByText(/Our 3D machine is busy right now/)).toBeVisible({ timeout: 10_000 });
  await expect(stepState(page, "Rooms and sizes read")).toHaveAttribute("data-state", "next");
  await pg`update trial_jobs set status = 'cancelled', finished_at = now() where id = ${id}`;
});

test("лендинг: тексты макета, «See an example» ведёт к примеру, образец ожидания не нажимается", async ({ page }) => {
  await page.goto(`${TRIAL_BASE}/try`);
  await expect(page.getByRole("heading", { name: "What you get for each listing" })).toBeAttached();
  await page.locator("form").getByRole("link", { name: "See an example" }).click();
  await expect(page).toHaveURL(/\/try#example$/);
  await expect(page.locator("#example")).toBeInViewport();
  await expect(page.locator("#waiting [inert]")).toHaveCount(1); // почта в образце — картинка, не поле
  await page.locator("form").getByRole("button", { name: "Upload a floor plan" }).click(); // без файла — подсказка, не запрос
  await expect(page.locator("form").getByRole("alert")).toHaveText("Please choose a floor plan file first.");
});

test("ключ ссылки неизвестен → «We can't find this tour»", async ({ page }) => {
  await page.goto(`${TRIAL_BASE}/try/${"Z".repeat(22)}`);
  await expect(page.getByRole("heading", { name: "We can't find this tour" })).toBeVisible();
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
});

// Язык браузера — через locale контекста: заголовок accept-language поверх setExtraHTTPHeaders Chromium перебивает своим.
test.describe("русский браузер", () => {
test.use({ locale: "ru-RU" });
test("язык: браузер → переключатель → сохранённый выбор главнее браузера", async ({ page }) => {
  await page.goto(`${TRIAL_BASE}/try`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(UP.ru.h1); // язык браузера
  await page.locator("form").getByRole("button", { name: UP.ru.button }).click();
  await expect(page.locator("form").getByRole("alert")).toHaveText("Сначала выберите файл с планом.");
  const sw = page.getByTestId("trial-lang");
  await expect(sw).toHaveText(/^Русский\s*·\s*English$/);
  await sw.getByRole("link", { name: "English" }).click();
  await page.waitForURL(/\/try\?lang=en$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(UP.en.h1);
  await expect(page.getByRole("banner").getByRole("link", { name: "Example" })).toHaveAttribute("href", "/try?lang=en#example");
  // снова без языка в адресе: браузер русский, но человек выбрал English — открывается English
  await page.goto(`${TRIAL_BASE}/try`);
  await page.waitForURL(/\/try\?lang=en$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(UP.en.h1);
  await page.goto(`${TRIAL_BASE}/try/${"Z".repeat(22)}`);
  await page.waitForURL(new RegExp(`/try/Z{22}\\?lang=en$`));
  await expect(page.getByRole("heading", { name: "We can't find this tour" })).toBeVisible();
  await page.goto(`${TRIAL_BASE}/try/${"Z".repeat(22)}?lang=ru`); // адрес главнее сохранённого
  await expect(page.getByRole("heading", { name: "Тур не найден" })).toBeVisible();
});
});
