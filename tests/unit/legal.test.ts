import { describe, expect, it } from "vitest";

import { isEnglishMode } from "@/components/legal/CookieBanner";
import { legalText } from "@/lib/legal/texts";
import { daysFrom } from "@/modules/retention/run";

// Согласия и сроки (план b2b-04): срок не задан — не удаляем ничего; английский режим — Метрика по согласию;
// у каждого документа есть оба языка и пометка черновика.

describe("сроки хранения", () => {
  it("срок — только целое > 0; пусто, ноль и мусор — «не задан» (ничего не удаляем)", () => {
    expect(daysFrom("365")).toBe(365);
    for (const v of [undefined, "", "0", "-5", "abc", "1.5"]) expect(daysFrom(v)).toBeNull();
  });
});

describe("режим cookie", () => {
  it("язык из адреса сильнее сохранённого", () => {
    expect(isEnglishMode("?lang=en", null)).toBe(true);
    expect(isEnglishMode("?lang=ru", "en")).toBe(false);
    expect(isEnglishMode("", "en")).toBe(true);
    expect(isEnglishMode("", null)).toBe(false);
  });
});

describe("тексты политики", () => {
  it("три документа на двух языках, каждый помечен как черновик", () => {
    for (const d of ["privacy", "cookies", "terms"] as const) {
      for (const l of ["ru", "en"] as const) {
        const t = legalText(d, l);
        expect(t.sections.length).toBeGreaterThan(0);
        expect(t.draftNote.toLowerCase()).toMatch(/черновик|draft/);
      }
    }
  });
});
