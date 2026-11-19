import { describe, expect, it } from "vitest";
import { ItemsBody } from "@/lib/cutout-check/body";
import { countMarks, isChecked, L, noteVerdict, parseFilter, planPress } from "@/lib/cutout-check/rules";
import { checkHref } from "@/components/lab/CutoutCheckNav";

// Правила /lab/cutout-check (T-20261119-104): нажатия, версии текста, фильтры, входы заливки, надписи парой RU/EN.

const item = (mark: string | null, gk = "g1") => ({ generationKey: gk, mark });

describe("planPress", () => {
  it("«не ок» по непроверенной ставит отметку, «ок» тоже", () => {
    expect(planPress(item(null), "g1", "bad", null)).toEqual({ applied: true, log: "bad", next: "bad" });
    expect(planPress(item(null), "g1", "ok", null)).toEqual({ applied: true, log: "ok", next: "ok" });
  });
  it("повтор той же отметки снимает её (в журнал — clear)", () => {
    expect(planPress(item("bad"), "g1", "bad", "bad")).toEqual({ applied: true, log: "clear", next: null });
  });
  it("«не ок» → «ок» переключает без снятия", () => {
    expect(planPress(item("bad"), "g1", "ok", "bad")).toEqual({ applied: true, log: "ok", next: "ok" });
  });
  it("вырезка заменена — stale, другая вкладка успела раньше — state_conflict; оба не применяются", () => {
    expect(planPress(item(null, "g2"), "g1", "bad", null)).toMatchObject({ applied: false, reason: "stale" });
    expect(planPress(item("ok"), "g1", "bad", null)).toMatchObject({ applied: false, reason: "state_conflict" });
  });
});

describe("noteVerdict", () => {
  it("первая версия и более новая применяются; та же и старее — только журнал; чужая вырезка — stale", () => {
    expect(noteVerdict({ generationKey: "g1", noteSeq: null }, { generationKey: "g1", seq: 5 })).toBe("apply");
    expect(noteVerdict({ generationKey: "g1", noteSeq: 5 }, { generationKey: "g1", seq: 6 })).toBe("apply");
    expect(noteVerdict({ generationKey: "g1", noteSeq: 5 }, { generationKey: "g1", seq: 5 })).toBe("older");
    expect(noteVerdict({ generationKey: "g1", noteSeq: 5 }, { generationKey: "g1", seq: 4 })).toBe("older");
    expect(noteVerdict({ generationKey: "g2", noteSeq: null }, { generationKey: "g1", seq: 9 })).toBe("stale");
  });
});

describe("счётчики и фильтр", () => {
  it("проверено = есть ok/bad; bad считается отдельно", () => {
    expect(isChecked({ mark: "ok" })).toBe(true);
    expect(isChecked({ mark: null })).toBe(false);
    expect(countMarks([{ mark: "ok" }, { mark: "bad" }, { mark: null }])).toEqual({ total: 3, checked: 2, bad: 1 });
  });
  it("фильтр: известные значения, остальное — «все»", () => {
    expect(parseFilter("bad")).toBe("bad");
    expect(parseFilter("todo")).toBe("todo");
    expect(parseFilter("x")).toBe("all");
    expect(parseFilter(undefined)).toBe("all");
  });
  it("ссылки: роль кодируется, «все» и первая страница без хвоста", () => {
    expect(checkHref(null, "all")).toBe("?");
    expect(checkHref("диван", "bad", 2)).toBe(`?r=${encodeURIComponent("диван")}&f=bad&p=2`);
  });
});

describe("заливка карточек и надписи", () => {
  it("тело заливки: sku + generationKey + position обязательны, null в полях принимается", () => {
    const ok = ItemsBody.safeParse({ run: "1119-a", items: [{ sku: "s_1", generationKey: "abc", position: 0, role: null, name: null, info: { verdict: "ok" } }] });
    expect(ok.success).toBe(true);
    expect(ItemsBody.safeParse({ run: "1119-a", items: [{ sku: "s_1", position: 0 }] }).success).toBe(false);
    expect(ItemsBody.safeParse({ run: "1119-a", items: [] }).success).toBe(false);
  });
  it("каждая надпись — пара RU/EN, обе непустые", () => {
    for (const [k, v] of Object.entries(L)) {
      expect(v.ru.length, k).toBeGreaterThan(0);
      expect(v.en.length, k).toBeGreaterThan(0);
      expect(v.ru, k).not.toBe(v.en);
    }
  });
});
