import { expect, test } from "@playwright/test";

// Встраивание демо на сайт застройщика (b2b-07, ADR-0283): чужая/неизвестная квартира — 404; своя — страница с
// разрешением показа рамкой только себе и доменам партнёра (в CI витрины нет — допустимо «временно недоступно» 503);
// загрузчик для сайта застройщика отдаётся и проверяет источник сообщений.
test("встраивание: неизвестная квартира — 404, своя — CSP frame-ancestors, загрузчик на месте", async ({ request }) => {
  expect((await request.get("/embed/demo/nope")).status()).toBe(404);
  expect((await request.get("/embed/nobody/flat215")).status()).toBe(404);
  const ok = await request.get("/embed/demo/flat215");
  expect([200, 503]).toContain(ok.status());
  if (ok.status() === 200) {
    expect(ok.headers()["content-security-policy"]).toMatch(/^frame-ancestors 'self'/);
    expect(await ok.text()).toContain('<base href="/demo/">');
  }
  const js = await request.get("/embed.js");
  expect(js.status()).toBe(200);
  const src = await js.text();
  expect(src).toContain("e.source !== f.contentWindow");
  expect(src).toContain('e.origin !== ORIGIN');
});
