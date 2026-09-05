import { describe, expect, it } from "vitest";
import {
  batchCount,
  batchOfPage,
  checkDecision,
  clampPage,
  MAX_MANUAL_REDO,
  pageCount,
  pagesOfBatch,
  reworkToItemStatus,
} from "@/lib/mesh-audit/rules";

describe("mesh-audit: страницы и партии", () => {
  it("1291 карточка → 65 страниц, 7 партий; страница 11 — партия 2 (страницы 11–20)", () => {
    expect(pageCount(1291)).toBe(65);
    expect(batchCount(1291)).toBe(7);
    expect(batchOfPage(1)).toBe(1);
    expect(batchOfPage(10)).toBe(1);
    expect(batchOfPage(11)).toBe(2);
    expect(pagesOfBatch(2)).toEqual([11, 20]);
  });
  it("номер страницы из адреса зажимается в допустимый диапазон", () => {
    expect(clampPage(undefined, 65)).toBe(1);
    expect(clampPage("0", 65)).toBe(1);
    expect(clampPage("abc", 65)).toBe(1);
    expect(clampPage("999", 65)).toBe(65);
    expect(clampPage("7", 65)).toBe(7);
    expect(pageCount(0)).toBe(1);
  });
});

describe("mesh-audit: решение владельца", () => {
  const open = { generationKey: "g1", manualAttempts: 0, status: "open" };

  it("первая переделка принимается и увеличивает счёт", () => {
    const r = checkDecision(open, "g1", "redo");
    expect(r).toEqual({ ok: true, attemptNo: 1, manualAttempts: 1, status: "redo_requested" });
  });
  it("устаревшая вкладка (другое поколение) → 409 stale, актуальный меш не трогается", () => {
    const r = checkDecision(open, "g0", "redo");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r).toMatchObject({ http: 409, code: "stale" });
  });
  it("повторный клик, пока переделка в работе → 409 pending", () => {
    for (const status of ["redo_requested", "redo_queued"]) {
      const r = checkDecision({ ...open, manualAttempts: 1, status }, "g1", "redo");
      expect(r.ok).toBe(false);
      if (!r.ok) expect(r.code).toBe("pending");
    }
  });
  it("третьей переделки нет — лимит 2 на товар за всё время", () => {
    const r = checkDecision({ ...open, manualAttempts: MAX_MANUAL_REDO }, "g1", "redo");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r).toMatchObject({ http: 409, code: "limit" });
  });
  it("«нужна замена» — только после двух переделок и один раз", () => {
    const early = checkDecision({ ...open, manualAttempts: 1 }, "g1", "replace_needed");
    expect(early.ok).toBe(false);
    if (!early.ok) expect(early.code).toBe("too_early");
    const ok = checkDecision({ ...open, manualAttempts: 2 }, "g1", "replace_needed");
    expect(ok).toEqual({ ok: true, attemptNo: 3, manualAttempts: 2, status: "replace_needed" });
    const again = checkDecision({ ...open, manualAttempts: 2, status: "replace_needed" }, "g1", "replace_needed");
    expect(again.ok).toBe(false);
  });
  it("ACK конвейера: queued/running → в очереди, blocked → ошибка, done не трогает статус", () => {
    expect(reworkToItemStatus("queued")).toBe("redo_queued");
    expect(reworkToItemStatus("running")).toBe("redo_queued");
    expect(reworkToItemStatus("blocked")).toBe("redo_blocked");
    expect(reworkToItemStatus("applied")).toBe("redo_requested");
    expect(reworkToItemStatus("done")).toBeNull();
  });
});
