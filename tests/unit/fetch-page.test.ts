import { describe, it, expect } from "vitest";
import { isPrivateHost, looksLikeStub, proxyUrlsFromEnv } from "@/lib/calc/fetch-page";

describe("isPrivateHost — SSRF-guard", () => {
  it("режет localhost и приватные диапазоны", () => {
    for (const h of ["localhost", "127.0.0.1", "10.1.2.3", "172.16.0.1", "172.31.9.9", "192.168.1.1", "169.254.1.1", "0.0.0.0", "::1", "api.internal", "printer.local"]) {
      expect(isPrivateHost(h), h).toBe(true);
    }
  });

  it("публичные хосты пропускает", () => {
    for (const h of ["www.ozon.ru", "leroymerlin.ru", "8.8.8.8", "172.32.0.1"]) {
      expect(isPrivateHost(h), h).toBe(false);
    }
  });
});

describe("looksLikeStub — челлендж/заглушка вместо карточки", () => {
  it("короткий HTML без og-меты и цены → заглушка", () => {
    expect(looksLikeStub("<html><head><style>@font-face{}</style></head><body>Доступ ограничен</body></html>")).toBe(true);
  });

  it("короткий, но с og:title или ценой → не заглушка", () => {
    expect(looksLikeStub(`<meta property="og:title" content="Обои"/>`)).toBe(false);
    expect(looksLikeStub("<body>Цена 2650 ₽</body>")).toBe(false);
  });

  it("большая страница → не заглушка", () => {
    expect(looksLikeStub("<div>товар</div>".repeat(1000))).toBe(false);
  });
});

describe("proxyUrlsFromEnv — список прокси из env", () => {
  it("парсит список, режет мусор, максимум 3", () => {
    expect(proxyUrlsFromEnv("http://u:p@h:1, http://u:p@h:2 ,мусор,http://u:p@h:3,http://u:p@h:4")).toEqual([
      "http://u:p@h:1", "http://u:p@h:2", "http://u:p@h:3",
    ]);
    expect(proxyUrlsFromEnv(undefined)).toEqual([]);
    expect(proxyUrlsFromEnv("")).toEqual([]);
  });
});
