import { describe, expect, it } from "vitest";

import { metrikaSafeUrl } from "@/lib/metrika";

// КЛЮЧИ ПОКУПАТЕЛЯ НЕ УХОДЯТ В МЕТРИКУ (план demo-05 п.7): `s`, `c`, `coll` — доступ к чужой подборке/корзине/коллекции;
// в пути (T-20261018-20) — `/e/<id>` смета, `/p/<id>/…` проект, `/go/<eid>/<iid>` переход из сметы.

describe("metrikaSafeUrl", () => {
  it("значения s, c, coll заменены на *, остальное как было", () => {
    expect(metrikaSafeUrl("/flat?s=AbC123&demo=set1&utm_source=ya")).toBe("/flat?s=*&demo=set1&utm_source=ya");
    expect(metrikaSafeUrl("/flat?c=tok1&coll=tok2&flat=215")).toBe("/flat?c=*&coll=*&flat=215");
  });

  it("полный адрес (реферер) и якорь сохраняются", () => {
    expect(metrikaSafeUrl("https://remont-lab.online/flat?coll=x9#plan")).toBe("https://remont-lab.online/flat?coll=*#plan");
  });

  it("повторённый параметр — оба значения скрыты", () => {
    expect(metrikaSafeUrl("/flat?s=a&s=b")).toBe("/flat?s=*&s=*");
  });

  it("без ключей адрес не меняется ни на символ (в т.ч. кодировка)", () => {
    for (const u of ["/", "", "/flat?demo=set1&lang=en", "/calc/remont?area=50%2C5", "/flat?session=1&cc=2"]) {
      expect(metrikaSafeUrl(u)).toBe(u);
    }
  });

  it("пустое значение не превращается в *", () => {
    expect(metrikaSafeUrl("/flat?s=&demo=1")).toBe("/flat?s=&demo=1");
  });

  it("ключ в пути: /e/<id>, /p/<id>/…, /go/<eid>/<iid> → *", () => {
    const id = "3f2b9c1e-7d4a-4e8b-9a61-0c5d2e8f1a77";
    expect(metrikaSafeUrl(`/e/${id}`)).toBe("/e/*");
    expect(metrikaSafeUrl(`/e/${id}/`)).toBe("/e/*/");
    expect(metrikaSafeUrl(`/e/${id}?saved=1&utm_source=ya`)).toBe("/e/*?saved=1&utm_source=ya");
    expect(metrikaSafeUrl(`/e/${id}#plan`)).toBe("/e/*#plan");
    expect(metrikaSafeUrl(`/p/${id}/preview`)).toBe("/p/*/preview");
    expect(metrikaSafeUrl(`/go/${id}/item-7`)).toBe("/go/*/*");
    expect(metrikaSafeUrl(`/go/${id}`)).toBe("/go/*");
  });

  it("полный адрес (реферер) с ключом в пути и в параметрах", () => {
    expect(metrikaSafeUrl("https://remont-lab.online/e/abc-123?err=1")).toBe("https://remont-lab.online/e/*?err=1");
    expect(metrikaSafeUrl("https://remont-lab.online/e/abc?c=tok#x")).toBe("https://remont-lab.online/e/*?c=*#x");
    expect(metrikaSafeUrl("http://localhost:3000/p/xyz/paywall")).toBe("http://localhost:3000/p/*/paywall");
  });

  it("ключ только в пути — параметры не перекодируются", () => {
    expect(metrikaSafeUrl("/e/abc?area=50%2C5&q=a+b")).toBe("/e/*?area=50%2C5&q=a+b");
  });

  it("публичные и похожие пути не меняются", () => {
    for (const u of [
      "/e", "/e/", "/p", "/go/", "/calc/remont", "/embed/pik/215", "/lab", "/estimate/abc", "/flat/e/abc",
      "https://remont-lab.online", "https://remont-lab.online/", "https://ya.ru/?r=/e/abc", "/flat?next=/e/abc", "/e/*",
    ]) {
      expect(metrikaSafeUrl(u)).toBe(u);
    }
  });

  it("текст функции работает сам по себе — так он вставлен в скрипт старта счётчика (app/layout.tsx)", () => {
    const inline = new Function(`return (${metrikaSafeUrl.toString()});`)() as (u: string) => string;
    for (const u of [
      "/flat?s=AbC&demo=set1", "https://remont-lab.online/flat?coll=x#a", "/flat?demo=1", "",
      "/e/abc-123", "https://remont-lab.online/e/abc?c=t#x", "/p/xyz/preview", "/go/a/b", "/calc/remont", "/constructor",
    ]) {
      expect(inline(u)).toBe(metrikaSafeUrl(u));
    }
    expect(inline("/e/abc")).toBe("/e/*");
  });
});
