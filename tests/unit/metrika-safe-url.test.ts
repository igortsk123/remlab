import { describe, expect, it } from "vitest";

import { metrikaSafeUrl } from "@/lib/metrika";

// КЛЮЧИ ПОКУПАТЕЛЯ НЕ УХОДЯТ В МЕТРИКУ (план demo-05 п.7): `s`, `c`, `coll` — доступ к чужой подборке/корзине/коллекции.

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

  it("текст функции работает сам по себе — так он вставлен в скрипт старта счётчика (app/layout.tsx)", () => {
    const inline = new Function(`return (${metrikaSafeUrl.toString()});`)() as (u: string) => string;
    for (const u of ["/flat?s=AbC&demo=set1", "https://remont-lab.online/flat?coll=x#a", "/flat?demo=1", ""]) {
      expect(inline(u)).toBe(metrikaSafeUrl(u));
    }
  });
});
