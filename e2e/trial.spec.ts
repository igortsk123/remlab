import { promises as fs } from "node:fs";
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import postgres from "postgres";
import { TRIAL_BASE, TRIAL_DB, TRIAL_TOKEN } from "./trial-env";

// Проба для агентов (agent-trial-01, T-C): загрузка → задание в базе → поддельный воркер (ручки `/api/trial/worker/*` с
// тестовым токеном) двигает шаги и отдаёт результат по фикстуре → серый тур (холст не пустой). Плюс тексты: ошибка задания,
// «машина занята», масштаб не подтверждён. Отдельный сервер приложения на ТЕСТОВОЙ базе (`playwright.config.ts`,
// TEST_DATABASE_URL — как у юнит-тестов в CI); без неё пропускается.
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
async function upload(page: Page, listing = "Lounge 3.77 x 4.20 m"): Promise<string> {
  await page.setExtraHTTPHeaders({ "x-forwarded-for": `10.9.${Math.floor(Math.random() * 250)}.${Math.floor(Math.random() * 250)}` });
  await page.goto(`${TRIAL_BASE}/try`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Turn a floor plan into a furnished 3D tour in minutes");
  await page.locator('input[type="file"]').setInputFiles({ name: "plan-D.png", mimeType: "image/png", buffer: PNG });
  await expect(page.getByText("plan-D.png")).toBeVisible();
  const sizes = page.getByLabel("Room sizes from the listing");
  if (!(await sizes.isVisible())) await page.getByText("Add room measurements if you have them").click(); // узкий экран — свёрнуто
  await sizes.fill(listing);
  await page.locator("form").getByRole("button", { name: "Upload a floor plan" }).click();
  await page.waitForURL(/\/try\/[A-Za-z0-9_-]{22}$/, { timeout: 15_000 });
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

test("загрузка → задание в базе → шаги → серый тур", async ({ page, request }) => {
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
  await expect(page.getByRole("heading", { name: "Your 3D is ready" })).toBeVisible({ timeout: 10_000 });
  const tour = page.getByTestId("grey-tour");
  await expect(tour).toHaveAttribute("data-ready", "1", { timeout: 20_000 });
  // холст не пустой: доля непрозрачных точек (фон прозрачный — его даёт страница)
  const filled = await tour.locator("canvas").evaluate((c: HTMLCanvasElement) => {
    const t = document.createElement("canvas");
    t.width = 160; t.height = 120;
    const g = t.getContext("2d")!;
    g.drawImage(c, 0, 0, t.width, t.height);
    const d = g.getImageData(0, 0, t.width, t.height).data;
    let n = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i]! > 0) n++;
    return n / (t.width * t.height);
  });
  expect(filled).toBeGreaterThan(0.05);
  await expect(page.getByText("Automatically interpreted floor plan — verify flagged dimensions before marketing use.")).toBeVisible();
  await expect(page.getByText("Scale not verified.")).toHaveCount(0);
  const rooms = page.getByRole("list", { name: "Rooms" });
  await expect(rooms.getByRole("button", { name: /Lounge/ })).toBeVisible();
  await expect(rooms.getByRole("button", { name: /Hall.*size not confirmed/ })).toBeVisible(); // флаг — «?» и причина
  await rooms.getByRole("button", { name: /Lounge/ }).click();
  await expect(rooms.getByRole("button", { name: /Lounge/ })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("tab", { name: "First Floor" }).click();
  await expect(rooms.getByRole("button", { name: /Bedroom 1/ })).toBeVisible();
  await expect(tour).toHaveAttribute("data-ready", "1");
  expect((await pg`select status from trial_jobs where id = ${id}`)[0]!.status).toBe("done");
});

test("масштаб не подтверждён → плашка «Scale not verified»", async ({ page, request }) => {
  const id = await upload(page, "");
  const lease = await claim(request, id);
  const result = JSON.parse(await fs.readFile(FIXTURE, "utf8")) as { scale: Record<string, unknown> };
  result.scale = { status: "not_verified", ppm: null, inliers: 0, n: 0 };
  await finish(request, lease, result);
  await expect(page.getByText("Scale not verified.")).toBeVisible({ timeout: 10_000 });
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
  await expect(page.getByRole("main").getByRole("link", { name: "Upload a floor plan" })).toHaveAttribute("href", "/try");
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
