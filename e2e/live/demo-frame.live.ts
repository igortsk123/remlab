import { test, expect } from "@playwright/test";

// КАДРЫ ПО УМОЛЧАНИЮ НЕ ПУСТЫЕ (план demo-03, карта сценариев 2.7–2.8, 2.12). Живой прогон 14.10: второй ракурс сканди
// был абажуром торшера изнутри — в окне это выглядело пустой стеной. Здесь для каждого опубликованного варианта
// снимаем бесплатный черновик (наша 3D-сцена, без модели) теми камерами, что ставит страница, и меряем разброс
// яркости обоих ракурсов: у пустой стены/абажура он маленький. `no_registry` — кадры не попадают в ленту стилей.
// Медленно (~20–40 с на вариант), поэтому отдельный файл и свой срок.

test.setTimeout(8 * 60_000);
const MIN_STD = 25;   // у живой комнаты 55–70 (замер 14.10), у кадра «в абажур» — ниже 20

test("2.7–2.8 оба ракурса каждого варианта не пустые", async ({ page }) => {
  await page.goto("/demo/", { waitUntil: "networkidle" });
  await page.waitForFunction("typeof allVariants === 'function' && allVariants().length > 0");
  const n = await page.evaluate("D.variants.length") as number;
  for (let i = 0; i < n; i++) {
    const t = Date.now();
    const res = await page.evaluate(`(async () => {
      cur = ${i}; load(); cams = null; cams = loadCams();
      const body = Object.assign(payload(), { quality: "draft", async: 1, no_registry: 1 });
      // каждая загрузка — со сроком: зависший запрос должен стать понятной ошибкой, а не восемью минутами тишины
      const within = (p, ms, what) => Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error(what + ": нет ответа за " + ms / 1000 + " с")), ms))]);
      const r = await fetch("/api/render", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(20000) });
      const j = await r.json(); if (!j.job) return { error: j.error || "нет задания" };
      for (let k = 0; k < 100; k++) {
        await new Promise((ok) => setTimeout(ok, 3000));
        const jj = await fetch("/api/job?id=" + j.job, { cache: "no-store", signal: AbortSignal.timeout(15000) }).then((x) => x.json()).catch(() => null);
        if (!jj || jj.status === "running") continue;
        if (!jj.shots) return { error: jj.error || "без кадров" };
        const std = async (url) => { const im = new Image(); im.crossOrigin = "anonymous"; im.src = url + "?t=" + Date.now(); await within(im.decode(), 30000, "картинка " + url);
          const c = document.createElement("canvas"); c.width = 336; c.height = 224; const g = c.getContext("2d");
          g.drawImage(im, 0, 0, 336, 224); const d = g.getImageData(0, 0, 336, 224).data; let s = 0, s2 = 0, m = 0;
          for (let p = 0; p < d.length; p += 4) { const y = 0.299 * d[p] + 0.587 * d[p + 1] + 0.114 * d[p + 2]; s += y; s2 += y * y; m++; }
          return Math.sqrt(s2 / m - (s / m) ** 2); };
        const out = [];
        try { for (const sh of jj.shots) out.push({ cam: sh.camera, std: Math.round(await std(sh.url)), url: sh.url }); }
        catch (e) { return { error: String(e) }; }
        return { shots: out, backend: jj.backend, cams: cams.map((c) => [Math.round(c.x), Math.round(c.y)]) };
      }
      return { error: "не успел за 5 минут" };
    })()`) as { error?: string; shots?: { cam: string; std: number; url: string }[]; backend?: string; cams?: number[][] };
    console.log(`  · вариант ${i}: ${Math.round((Date.now() - t) / 1000)} с, ${res.backend ?? ""}, камеры ${JSON.stringify(res.cams)},`,
      res.error ?? res.shots!.map((s) => `${s.cam} разброс ${s.std}`).join(", "));
    expect(res.error, `вариант ${i}`).toBeUndefined();
    expect(res.shots!.length, `вариант ${i}: два ракурса`).toBeGreaterThanOrEqual(2);
    for (const s of res.shots!) expect(s.std, `вариант ${i} ${s.cam}: ${s.url}`).toBeGreaterThan(MIN_STD);
  }
});

// 2.13 (план demo-03): карточка «Моя коллекция» была без фото. Меняем предмет (кадра такой расстановки ещё нет) →
// сердечко «В избранное» → страница снимает черновик в фоне и прикрепляет его к коллекции на сервере. Одна коллекция
// за ночь — без ПДн и без номера менеджера, в отчёт застройщику не попадает.
test("2.13 сохранённая коллекция получает картинку", async ({ page }) => {
  test.setTimeout(4 * 60_000);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/demo/", { waitUntil: "networkidle" });
  await page.waitForFunction("typeof allVariants === 'function' && allVariants().length > 0");
  await page.locator("#tab-room").click();
  await page.locator("button[data-swap]").first().click();
  await page.locator("#shotbody [data-rep]").first().click();
  await page.locator("#sheet .mini:has-text('Заменить')").first().click();
  const t = Date.now();
  // сохранение — сердечком в шапке окна с именем (demo-15: кнопки «Сохранить коллекцию» больше нет)
  await page.locator("#vFav").click();
  await page.locator("#favOk").click();
  await expect(page.locator("#vFav.on")).toBeVisible();
  const cid = await page.evaluate(() => (JSON.parse(localStorage.getItem("remlab-favorites") || "[]")[0] || {}).collectionId as string);
  expect(cid).toMatch(/^[A-Za-z0-9_-]{22}$/);
  await expect.poll(async () => (await page.request.get(`/api/collections/${cid}`).then((r) => r.json()) as { collection: { shot?: string } }).collection.shot ?? "",
    { timeout: 180_000, intervals: [5_000] }).toMatch(/^\/test\/share\/frames\//);
  console.log(`  · картинка коллекции за ${Math.round((Date.now() - t) / 1000)} с`);
});

// 2.12: из конструктора — «Готово — посмотреть в окне» → окно варианта в 3D с изменениями, конструктор закрылся (demo-09).
// 2.7–2.8 и 2.13 — серверный черновик остаётся картинкой коллекции (demo-09 п.6), поэтому его ракурсы проверяем по-прежнему.
test("2.12 фото с изменениями из конструктора", async ({ page }) => {
  test.setTimeout(4 * 60_000);
  await page.goto("/demo/?live=force", { waitUntil: "networkidle" });
  await page.waitForFunction("typeof allVariants === 'function' && allVariants().length > 0");
  await page.locator("#tab-room").click();
  await page.locator("button[data-swap]").first().click();
  // «План» v3 — просмотр; редактор — по «Изменить план» (demo-02, ADR-0299)
  await page.locator('[data-vm="plan"]').click();
  await page.locator("#vCta").click();
  await expect(page.locator("#cons")).toBeVisible();
  const pos = await page.evaluate(`(() => { const r = stage.getBoundingClientRect(); const it = items.find(i => /^столик/.test(i.role));
    return { x: r.left + PAD + it.x * S, y: r.top + PAD + it.y * S }; })()`) as { x: number; y: number };
  await page.mouse.move(pos.x, pos.y); await page.mouse.down();
  for (let k = 1; k <= 8; k++) await page.mouse.move(pos.x - 3 * k, pos.y + 2 * k);
  await page.mouse.up();
  const t = Date.now();
  await page.locator("#consShot").click();                // demo-02: из конструктора — в окно с живой сценой
  await expect(page.locator("#shot .livecv, #shot .shotwrap img.vmain").first()).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("#cons")).toBeHidden();
  expect(await page.evaluate("VW.mode")).toBe("walk");
  console.log(`  · окно с изменениями из конструктора за ${Math.round((Date.now() - t) / 1000)} с`);
});
