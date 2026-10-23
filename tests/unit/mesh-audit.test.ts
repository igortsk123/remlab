import { describe, expect, it } from "vitest";
import { COMMENT_MAX, commentOrNull, DecisionBody } from "@/lib/mesh-audit/decision-body";
import {
  batchCount,
  batchOfPage,
  checkCancel,
  checkDecision,
  clampPage,
  isAccepted,
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
  it("отмена случайного клика: только пока не в очереди; попытка возвращается", () => {
    expect(checkCancel({ ...open, manualAttempts: 1, status: "redo_requested" }, "g1", "redo")).toEqual({ ok: true, manualAttempts: 0 });
    expect(checkCancel({ ...open, manualAttempts: 2, status: "replace_needed" }, "g1", "replace_needed")).toEqual({ ok: true, manualAttempts: 2 });
    const queued = checkCancel({ ...open, manualAttempts: 1, status: "redo_queued" }, "g1", "redo");
    expect(queued.ok).toBe(false);
    if (!queued.ok) expect(queued.code).toBe("queued");
    expect(checkCancel(open, "g1", "redo").ok).toBe(false);
    expect(checkCancel({ ...open, status: "redo_requested" }, "g0", "redo").ok).toBe(false);
  });
  it("ACK конвейера: queued/running → в очереди, blocked → ошибка, done не трогает статус", () => {
    expect(reworkToItemStatus("queued")).toBe("redo_queued");
    expect(reworkToItemStatus("running")).toBe("redo_queued");
    expect(reworkToItemStatus("blocked")).toBe("redo_blocked");
    expect(reworkToItemStatus("applied")).toBe("redo_requested");
    expect(reworkToItemStatus("done")).toBeNull();
  });
});

describe("mesh-audit: приёмка без кнопки «принять»", () => {
  it("принято = владелец видел карточку и не забраковал", () => {
    expect(isAccepted({ seenAt: "2026-10-02T10:00:00Z", status: "open" })).toBe(true);
    expect(isAccepted({ seenAt: new Date(), status: "open" })).toBe(true);
  });
  it("не просмотрено — не принято, даже если статус open", () => {
    expect(isAccepted({ seenAt: null, status: "open" })).toBe(false);
  });
  it("забраковано — не принято: именно у этих мешей болванка нужна под перепокраску", () => {
    for (const status of ["redo_requested", "redo_queued", "redo_blocked", "replace_needed"]) {
      expect(isAccepted({ seenAt: "2026-10-02T10:00:00Z", status })).toBe(false);
    }
  });
});

describe("mesh-audit: комментарий к браку (необязательный)", () => {
  const base = { itemId: 7, generationKey: "g1", verdict: "redo", idemKey: "g1:redo" };

  it("без комментария — решение принимается, в журнал идёт null", () => {
    const r = DecisionBody.safeParse(base);
    expect(r.success).toBe(true);
    expect(commentOrNull(r.success ? r.data.comment : "x")).toBeNull();
  });
  it("комментарий обрезается по краям; одни пробелы = пустой = null", () => {
    const r = DecisionBody.safeParse({ ...base, comment: "  фото не дорезалось  " });
    expect(r.success && r.data.comment).toBe("фото не дорезалось");
    const e = DecisionBody.safeParse({ ...base, comment: "   " });
    expect(e.success).toBe(true);
    expect(commentOrNull(e.success ? e.data.comment : "x")).toBeNull();
  });
  it("длиннее 500 символов — 400, а ровно 500 проходит", () => {
    expect(DecisionBody.safeParse({ ...base, comment: "я".repeat(COMMENT_MAX + 1) }).success).toBe(false);
    expect(DecisionBody.safeParse({ ...base, comment: "я".repeat(COMMENT_MAX) }).success).toBe(true);
  });
  it("комментарий не строка — 400", () => {
    expect(DecisionBody.safeParse({ ...base, comment: 5 }).success).toBe(false);
  });
});
