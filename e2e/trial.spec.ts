import { createHash } from "node:crypto";
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
const GEO = { w: 400, d: 300, title: "Гостиная", openings: [], radiators: [] }; // комната версии данных v1 (Р2-текст)
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
  await page.waitForURL(new RegExp(`/try/[A-Za-z0-9_-]{22}\\?k=[A-Za-z0-9_-]{22}&lang=${lang}$`), { timeout: 15_000 }); // язык и ключ агента (Р1) идут дальше
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

/** Версия данных страницы, как её шлёт конвейер до `result` (без неё тура нет, T-20261110-07). `state` — исход комнаты. */
async function publish(api: APIRequestContext, lease: { id: string; attempt: number; leaseToken: string }, state = "pending",
  scale = "not_verified") {
  const bundle = JSON.stringify({
    trial: { job_id: lease.id, scale }, room: GEO, rooms_geo: { living: GEO },
    apartment_rooms: [{ id: "living", furniture_state: state, furniture_text: state === "pending" ? null : "Size may be approximate." }],
    variants: [{ id: "trial-living", room_id: "living", style: "scandi", items: [], pending: state === "pending", furniture_state: state }],
    feeds: {}, rules: {}, quiz: { questions: [{ id: "style" }] },
  });
  const pub = await api.post(`${TRIAL_BASE}/api/trial/worker/bundle`, {
    headers: AUTH, data: { ...lease, bundle, sha256: createHash("sha256").update(bundle).digest("hex") },
  });
  expect(pub.status()).toBe(200);
  expect(((await pub.json()) as { warning?: string }).warning).toBeUndefined(); // страница тура закреплена (DEMO_DIR — заглушка витрины)
}

// Next срезает косую в конце (`/tour/` → `/tour`); страница тура возвращает её сама (ветка worktree-demo-template, `injectTour`)
const tourUrl = (id: string, lang: string) => new RegExp(`/try/${id}/tour/?\\?lang=${lang}&k=[A-Za-z0-9_-]{22}$`);
// ссылка «Открыть тур» у агента несёт его ключ правки (`tourHref`, Р1); без косой перед `?` — без перехода 308 (T-20261111-23)
const tourHrefRe = (id: string, lang: string) => new RegExp(`^/try/${id}/tour\\?lang=${lang}&k=[A-Za-z0-9_-]{22}$`);

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

  await publish(request, lease, "pending", "listing"); // масштаб подтверждён — окошка размеров нет, переход сам
  await finish(request, lease, JSON.parse(await fs.readFile(FIXTURE, "utf8")));
  const done = page.getByTestId("trial-done");
  await expect(done.getByRole("heading", { name: "Your 3D is ready" })).toBeVisible({ timeout: 10_000 });
  await expect(stepState(page, "3D ready")).toHaveAttribute("data-state", "done");
  await expect(done.getByRole("link", { name: "Open the tour" })).toHaveAttribute("href", tourHrefRe(id, "en"));
  await expect(done.getByText(/rooms$/)).toBeVisible(); // сводка из результата: «Ready in м:сс · N rooms»
  await expect(page.getByText("Scale not verified.")).toHaveCount(0);
  await expect(page.getByTestId("grey-tour")).toHaveCount(0); // серого тура больше нет
  await page.waitForURL(tourUrl(id, "en"), { timeout: 10_000 }); // сам, без нажатия
  await expect(page.locator("body[data-e2e-tour]")).toBeAttached(); // тур открылся: закреплённая копия витрины (заглушка DEMO_DIR)
  expect((await pg`select status from trial_jobs where id = ${id}`)[0]!.status).toBe("done");
});

// Р2-текст (T-20261109-33): размеров нет — у агента окошко «напишите размеры», в тур сам не уводим; текст принимается и после `done`
test("масштаб не подтверждён → окошко «размеры словами», без автоперехода; текст принят, в статусе его нет", async ({ page, request }) => {
  const id = await upload(page, "");
  const lease = await claim(request, id);
  const result = JSON.parse(await fs.readFile(FIXTURE, "utf8")) as { scale: Record<string, unknown> };
  result.scale = { status: "not_verified", ppm: null, inliers: 0, n: 0 };
  await publish(request, lease, "awaiting_check");
  await finish(request, lease, result);
  const box = page.getByTestId("trial-sizes");
  await expect(box.getByText("We couldn't find the room sizes")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Scale not verified.")).toHaveCount(0); // окошко говорит то же своими словами
  await page.waitForTimeout(3500); // дольше паузы автоперехода (2,5 с)
  expect(new URL(page.url()).pathname).toBe(`/try/${id}`);
  await box.getByLabel("Room sizes").fill("Lounge 4.2 x 3.8 m, bedroom 3 x 3 m");
  await box.getByRole("button", { name: "Send sizes" }).click();
  await expect(box.getByTestId("trial-sizes-state")).toHaveText("Applying your sizes…"); // задание уже done — ждёт воркер
  const [rb] = await pg`select kind, status, listing_text from trial_rebuilds where job_id = ${id}`;
  expect(rb).toMatchObject({ kind: "listing", status: "queued", listing_text: "Lounge 4.2 x 3.8 m, bedroom 3 x 3 m" });
  const st = await (await request.get(`${TRIAL_BASE}/api/trial/${id}`)).text();
  expect(st).toContain('"listing":"applying"');
  expect(st).not.toContain("Lounge 4.2");
  await page.getByTestId("trial-done").getByRole("link", { name: "Open the tour" }).click();
  await page.waitForURL(tourUrl(id, "en"), { timeout: 10_000 });
  await pg`update trial_rebuilds set status = 'failed', listing_text = null where job_id = ${id}`; // воркера листинга в e2e нет
});

test("текст на v1, пока задание идёт: «принято, применим после сборки» → после done «применяем»", async ({ page, request }) => {
  const id = await upload(page, "");
  const lease = await claim(request, id);
  await publish(request, lease);
  const box = page.getByTestId("trial-sizes");
  await expect(box.getByText("We couldn't find the room sizes")).toBeVisible({ timeout: 10_000 });
  await box.getByLabel("Room sizes").fill("living room 4.2 x 3.8");
  await box.getByRole("button", { name: "Send sizes" }).click();
  await expect(box.getByTestId("trial-sizes-state")).toHaveText("Got it. We'll apply the sizes once the plan is built.");
  expect((await pg`select status from trial_jobs where id = ${id}`)[0]!.status).toBe("running");
  await finish(request, lease, JSON.parse(await fs.readFile(FIXTURE, "utf8")));
  await expect(box.getByTestId("trial-sizes-state")).toHaveText("Applying your sizes…", { timeout: 10_000 });
  await pg`update trial_rebuilds set status = 'failed', listing_text = null where job_id = ${id}`;
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
  await publish(request, lease, "awaiting_check");
  await finish(request, lease, result);
  const done = page.getByTestId("trial-done");
  await expect(done.getByRole("heading", { name: "3D готово" })).toBeVisible({ timeout: 10_000 });
  await expect(done.getByTestId("trial-sizes").getByText("Не нашли размеры комнат")).toBeVisible(); // Р2-текст: окошко агенту
  await expect(done.getByLabel("Размеры комнат")).toHaveAttribute("placeholder", /гостиная 4,8 на 3,6/);
  await expect(done.getByRole("button", { name: "Отправить размеры" })).toBeDisabled(); // пустой текст не отправить
  await expect(done.getByRole("link", { name: "Открыть тур" })).toHaveAttribute("href", tourHrefRe(id, "ru"));
  await done.getByRole("link", { name: "Открыть тур" }).click();
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

// T-20261110-07: тур без версии данных не открывался никогда — агент видел белую страницу «not ready»
test("серый тур: пока версии нет — тур «готовится»; версия «только стены» → тур открывается", async ({ page, request }) => {
  const id = await upload(page, "", "ru");
  const lease = await claim(request, id);
  const k = new URL(page.url()).searchParams.get("k")!;
  const tour = `${TRIAL_BASE}/try/${id}/tour/?lang=ru&k=${k}`;
  const early = await request.get(tour);
  expect(early.status()).toBe(404);
  expect(await early.text()).toContain("Тур ещё готовится");
  await publish(request, lease, "awaiting_check");                         // как у плана без гостиной: комната ждёт проверки
  await finish(request, lease, JSON.parse(await fs.readFile(FIXTURE, "utf8")));
  await expect(page.getByTestId("trial-done").getByRole("link", { name: "Открыть тур" })).toBeVisible({ timeout: 10_000 });
  await page.goto(tour);
  await expect(page.locator("body[data-e2e-tour]")).toBeAttached();
  // данные: страница агента — по cookie-пропуску (закреплённая страница грузит их без ключа); чужой запрос без ключа — 403 (T-20261112-40)
  expect((await page.request.get(`${TRIAL_BASE}/try/${id}/tour/demo-data.json`)).status()).toBe(200);
  expect((await request.get(`${TRIAL_BASE}/try/${id}/tour/demo-data.json`)).status()).toBe(403);
});

// T-20261112-40 (план trial-buyer-gate-01, владелец 12.11 TG 1778–1780): ссылка покупателя не работает, пока агент не подтвердил планировку
test("ссылка покупателя: до «Подтвердить планировку» — «Ссылка не активирована», данных нет; после — тот же адрес открывает тур",
  async ({ page, browser, request }) => {
    const id = await upload(page, "", "ru");
    const k = new URL(page.url()).searchParams.get("k")!;
    const lease = await claim(request, id);
    await publish(request, lease, "awaiting_check");
    await finish(request, lease, JSON.parse(await fs.readFile(FIXTURE, "utf8")));
    const buyerUrl = `${TRIAL_BASE}/try/${id}/tour/?quiz=1&lang=ru`;
    const buyer = await browser.newContext();                       // покупатель — свой браузер, без cookie агента
    const bp = await buyer.newPage();
    const r0 = await bp.goto(buyerUrl);
    expect(r0?.status()).toBe(403);
    await expect(bp.getByRole("heading", { name: "Ссылка не активирована, обратитесь к вашему менеджеру" })).toBeVisible();
    await expect(bp.locator("body[data-e2e-tour]")).toHaveCount(0);
    for (const p of ["demo-data.json", ""]) expect((await request.get(`${TRIAL_BASE}/try/${id}/tour/${p}`)).status()).toBe(403);
    expect((await request.get(`${TRIAL_BASE}/api/trial/${id}/result`)).status()).toBe(403);
    expect((await request.get(`${TRIAL_BASE}/api/trial/${id}/bundle`)).status()).toBe(403);
    const en = await request.get(`${TRIAL_BASE}/try/${id}/tour/?lang=en`);
    expect(await en.text()).toContain("This link isn’t active yet — please contact your agent");
    // агент по своей ссылке — тур; в ТОМ ЖЕ браузере ссылка покупателя — по-прежнему заглушка (cookie открывает только данные)
    await page.goto(`${TRIAL_BASE}/try/${id}/tour/?lang=ru&k=${k}`);
    await expect(page.locator("body[data-e2e-tour]")).toBeAttached();
    expect((await page.request.get(`${TRIAL_BASE}/try/${id}/tour/demo-data.json`)).status()).toBe(200);
    expect((await page.goto(buyerUrl))?.status()).toBe(403);
    // «Подтвердить планировку» агентом
    const ver = ((await (await request.get(`${TRIAL_BASE}/try/${id}/tour/version.json`)).json()) as { bundle: number }).bundle;
    const c = await request.post(`${TRIAL_BASE}/api/trial/${id}/confirm`,
      { data: { k, request_id: `e2e-gate-${id.slice(0, 8)}`, base_version: ver, rooms_ok: [] } });
    expect(c.status()).toBe(202);
    const r1 = await bp.goto(buyerUrl);
    expect(r1?.status()).toBe(200);
    await expect(bp.locator("body[data-e2e-tour]")).toBeAttached();
    expect((await request.get(`${TRIAL_BASE}/try/${id}/tour/demo-data.json`)).status()).toBe(200);
    expect((await request.get(`${TRIAL_BASE}/api/trial/${id}/result`)).status()).toBe(200);
    await buyer.close();
    await pg`update trial_rebuilds set status = 'failed' where job_id = ${id} and status in ('queued', 'running')`; // воркера пересборки в e2e нет
  });

test("задание закрыто без версии данных → «не получилось собрать тур» без перехода; адрес тура — страница, не «not ready»", async ({ page, request }) => {
  const id = await upload(page);
  const lease = await claim(request, id);
  await finish(request, lease, JSON.parse(await fs.readFile(FIXTURE, "utf8")));
  await expect(page.getByRole("heading", { name: "We couldn't build this tour" })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/couldn't build a 3D tour from this plan/)).toBeVisible();
  await page.waitForTimeout(3500); // дольше паузы автоперехода (2,5 с)
  expect(new URL(page.url()).pathname).toBe(`/try/${id}`);
  await expect(page.getByRole("main").getByRole("link", { name: "Upload a floor plan" })).toHaveAttribute("href", "/try?lang=en");
  const k = new URL(page.url()).searchParams.get("k")!;
  // покупателю тур не подтверждён — «не активирована» (T-20261112-40); агенту по ключу — «не получилось собрать»
  expect((await request.get(`${TRIAL_BASE}/try/${id}/tour/?lang=en`)).status()).toBe(403);
  const r = await page.goto(`${TRIAL_BASE}/try/${id}/tour/?lang=en&k=${k}`);
  expect(r?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "We couldn't build this tour" })).toBeVisible();
  await expect(page.getByText("not ready")).toHaveCount(0);
  await page.getByRole("link", { name: "Upload page" }).click();
  await page.waitForURL(new RegExp(`/try/${id}\\?k=${k}&lang=en$`));       // ключ агента едет обратно на страницу задания
  const miss = await request.get(`${TRIAL_BASE}/try/${"Z".repeat(22)}/tour/?lang=ru`);
  expect(miss.status()).toBe(404);
  expect(await miss.text()).toContain("Тур не найден");
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
