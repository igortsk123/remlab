import { describe, expect, it } from "vitest";
import { landingText } from "@/components/trial/landing-text";
import { langFromAccept, parseLang, ruPlural, TEXT, tourHref, withLang } from "@/lib/trial/i18n";

// Язык страниц пробы (agent-trial-08, П): выбор как у `/demo` (адрес → сохранённый → браузер → рынок UK), язык держится
// в адресе через форму → ожидание → тур; словари двух языков одной формы.

/** Все строки словаря (функции — на пробном значении), путь → текст. */
function leaves(v: unknown, path = ""): Map<string, string> {
  const out = new Map<string, string>();
  if (typeof v === "string") out.set(path, v);
  else if (typeof v === "function") out.set(path, String((v as (x: number) => string)(2)));
  else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) for (const [p, s] of leaves(x, `${path}.${k}`)) out.set(p, s);
  return out;
}

describe("выбор языка", () => {
  it("адрес: только ru|en", () => {
    expect(parseLang("ru")).toBe("ru");
    expect(parseLang("en")).toBe("en");
    expect(parseLang("de")).toBeNull();
    expect(parseLang(undefined)).toBeNull();
  });

  it("браузер: первый поддерживаемый по весу; неизвестный — язык рынка (EN)", () => {
    expect(langFromAccept("ru-RU,ru;q=0.9,en-US;q=0.8")).toBe("ru");
    expect(langFromAccept("en-GB,en;q=0.9,ru;q=0.8")).toBe("en");
    expect(langFromAccept("de-DE,ru;q=0.7,en;q=0.5")).toBe("ru");
    expect(langFromAccept("en;q=0.4,ru;q=0.8")).toBe("ru");
    expect(langFromAccept("de-DE,fr")).toBe("en");
    expect(langFromAccept("ru;q=0")).toBe("en");
    expect(langFromAccept(null)).toBe("en");
    expect(langFromAccept("")).toBe("en");
  });
});

describe("язык в адресе", () => {
  it("ссылка задания из ответа загрузки и шапки — с языком, остальное сохраняется", () => {
    expect(withLang("/try/AbC", "ru")).toBe("/try/AbC?lang=ru");
    expect(withLang("/try?lang=en", "ru")).toBe("/try?lang=ru");
    expect(withLang("/try?x=1#faq", "en")).toBe("/try?x=1&lang=en#faq");
  });

  it("тур — тот же язык", () => {
    expect(tourHref("AbC_-1", "ru")).toBe("/try/AbC_-1/tour/?lang=ru");
    expect(tourHref("AbC_-1", "en")).toBe("/try/AbC_-1/tour/?lang=en");
  });
});

describe("словари", () => {
  it("у двух языков одни и те же строки, ни одной пустой; русские — по-русски", () => {
    for (const [en, ru] of [[TEXT.en, TEXT.ru], [landingText("en"), landingText("ru")]] as const) {
      const a = leaves(en), b = leaves(ru);
      expect([...b.keys()]).toEqual([...a.keys()]);
      for (const [k, v] of b) {
        if (a.get(k) !== "") expect(v, k).not.toBe("");
      }
    }
    expect(TEXT.ru.done.title).toBe("3D готово");
    expect(TEXT.ru.done.scaleTitle).toBe("Масштаб не подтверждён.");
    expect(landingText("ru").hero.h1).toMatch(/[а-я]/);
  });

  it("русское число комнат", () => {
    expect([1, 2, 5, 11, 21, 22, 25].map((n) => TEXT.ru.done.rooms(n))).toEqual(
      ["1 комната", "2 комнаты", "5 комнат", "11 комнат", "21 комната", "22 комнаты", "25 комнат"]);
    expect(TEXT.en.done.rooms(1)).toBe("1 room");
    expect(ruPlural(14, "a", "b", "c")).toBe("c");
  });
});
