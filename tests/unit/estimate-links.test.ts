import { describe, it, expect } from "vitest";
import { domainFromUrl, resolveTarget, type LinkRoute } from "@/lib/estimate/links";

describe("estimate links", () => {
  it("домен без www", () => {
    expect(domainFromUrl("https://www.ozon.ru/product/123")).toBe("ozon.ru");
    expect(domainFromUrl("https://leroymerlin.ru/cat")).toBe("leroymerlin.ru");
    expect(domainFromUrl("не ссылка")).toBeNull();
  });

  it("без маршрута — отдаём прямую ссылку (реф догонит позже)", () => {
    expect(resolveTarget("https://ozon.ru/p/1", [])).toBe("https://ozon.ru/p/1");
  });

  it("с маршрутом — подставляем реф-шаблон", () => {
    const routes: LinkRoute[] = [
      { domain: "ozon.ru", network: "gdeslon", urlTemplate: "https://ref/?to={url}", priority: 1, active: true },
    ];
    expect(resolveTarget("https://ozon.ru/p/1", routes)).toBe("https://ref/?to=" + encodeURIComponent("https://ozon.ru/p/1"));
  });

  it("несколько маршрутов — берём активный с макс. приоритетом", () => {
    const routes: LinkRoute[] = [
      { domain: "ozon.ru", network: "a", urlTemplate: "https://a/{url}", priority: 1, active: true },
      { domain: "ozon.ru", network: "b", urlTemplate: "https://b/{url}", priority: 5, active: true },
      { domain: "ozon.ru", network: "c", urlTemplate: "https://c/{url}", priority: 9, active: false },
    ];
    expect(resolveTarget("https://ozon.ru/x", routes)).toContain("https://b/");
  });
});
