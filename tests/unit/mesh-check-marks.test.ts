import { describe, expect, it } from "vitest";
import { NoteBody, PressBody } from "@/lib/mesh-audit/check-body";
import { checkStateLine, isChecked, planPress, type MarkState } from "@/lib/mesh-audit/marks";
import { decisionComment } from "@/lib/mesh-audit/repo-marks";
import { noteVerdict } from "@/lib/mesh-audit/repo-notes";
import { checkDecision, isAccepted } from "@/lib/mesh-audit/rules";
import { countSections, firstOpenSection, rolesOf, sectionOf } from "@/lib/mesh-audit/sections";

// /lab/mesh-check (T-20261112-118): правила нажатий «ок»/«брак», версий комментария и разделов. Ручки с БД — в mesh-check-routes.

const open: MarkState = { generationKey: "g1", status: "open", manualAttempts: 0, mark: null };

describe("mesh-check: нажатие", () => {
  it("«ок» на непроверенной — отметка без решения", () => {
    expect(planPress(open, "g1", "ok", null)).toEqual({ applied: true, log: "ok", next: "ok" });
  });
  it("«брак» — отметка и решение «переделать»; после двух переделок — «нужна замена»", () => {
    expect(planPress(open, "g1", "bad", null)).toEqual({ applied: true, log: "bad", next: "bad", decide: "redo" });
    expect(planPress({ ...open, manualAttempts: 2 }, "g1", "bad", null)).toMatchObject({ decide: "replace_needed" });
  });
  it("повтор того же нажатия снимает отметку («ок» → снято)", () => {
    expect(planPress({ ...open, mark: "ok" }, "g1", "ok", "ok")).toEqual({ applied: true, log: "clear", next: null });
  });
  it("снятие «брака», пока переделка не ушла в волну, отменяет решение", () => {
    const st = { ...open, mark: "bad", status: "redo_requested", manualAttempts: 1 };
    expect(planPress(st, "g1", "bad", "bad")).toEqual({ applied: true, log: "clear", next: null, cancel: true });
  });
  it("снятие «брака», когда переделка уже в волне: отметка снимается, переделка идёт (queued_kept)", () => {
    const st = { ...open, mark: "bad", status: "redo_queued", manualAttempts: 1 };
    expect(planPress(st, "g1", "bad", "bad")).toEqual({ applied: true, log: "clear", next: null, reason: "queued_kept" });
  });
  it("«ок» поверх «брака» отменяет ещё не ушедшее решение", () => {
    const st = { ...open, mark: "bad", status: "redo_requested", manualAttempts: 1 };
    expect(planPress(st, "g1", "ok", "bad")).toEqual({ applied: true, log: "ok", next: "ok", cancel: true });
  });
  it("«брак», когда переделка уже идёт (решение со старой страницы), второго решения не создаёт", () => {
    for (const status of ["redo_requested", "redo_queued", "replace_needed"]) {
      expect(planPress({ ...open, status }, "g1", "bad", null)).toEqual({ applied: true, log: "bad", next: "bad" });
    }
  });
  it("«брак» после неудачной переделки (redo_blocked) — новое решение", () => {
    expect(planPress({ ...open, status: "redo_blocked", manualAttempts: 1 }, "g1", "bad", null)).toMatchObject({ decide: "redo" });
  });
  it("модель уже заменена (старая вкладка) — не применяется, но это не потеря: журнал пишет applied=false", () => {
    expect(planPress(open, "g0", "ok", null)).toMatchObject({ applied: false, reason: "stale" });
  });
  it("двойной тап из двух вкладок: вторая видела другое состояние — state_conflict, а не молчаливая перезапись", () => {
    expect(planPress({ ...open, mark: "ok" }, "g1", "bad", null)).toMatchObject({ applied: false, reason: "state_conflict" });
  });
  it("«проверено» — только при отметке текущего поколения", () => {
    expect(isChecked({ mark: null })).toBe(false);
    expect(isChecked({ mark: "ok" })).toBe(true);
    expect(isChecked({ mark: "bad" })).toBe(true);
  });
  it("строка состояния переделки", () => {
    const base = { status: "open", manualAttempts: 1, mark: null, redoneAt: null, reworkError: null };
    expect(checkStateLine(base)).toBeNull();
    expect(checkStateLine({ ...base, status: "redo_queued" })?.text).toBe("на переделке 1 из 2");
    expect(checkStateLine({ ...base, redoneAt: "2026-11-12T00:00:00Z" })?.tone).toBe("info");
  });
});

describe("mesh-check: решения и приёмка", () => {
  it("«нужна замена», пока идёт переделка, не принимается (дыра, найденная Codex 12.11)", () => {
    expect(checkDecision({ generationKey: "g1", manualAttempts: 2, status: "redo_queued" }, "g1", "replace_needed")).toMatchObject({ ok: false, code: "pending" });
  });
  it("«брак» снимает принятие меша (прополка болванок), «ок» не добавляет", () => {
    expect(isAccepted({ seenAt: "2026-11-12T00:00:00Z", status: "open", mark: "bad" })).toBe(false);
    expect(isAccepted({ seenAt: null, status: "open", mark: "ok" })).toBe(false);
    expect(isAccepted({ seenAt: "2026-11-12T00:00:00Z", status: "open", mark: null })).toBe(true);
  });
  it("комментарий решения — начало текста до 500 знаков, пустой — null", () => {
    expect(decisionComment(null)).toBeNull();
    expect(decisionComment("  ")).toBeNull();
    expect(decisionComment("x".repeat(2000))).toHaveLength(500);
  });
});

describe("mesh-check: версии комментария", () => {
  it("новее принятой — применяется; старее или та же — только журнал (older); модель заменена — stale", () => {
    const it0 = { generationKey: "g1", noteSeq: 100 };
    expect(noteVerdict({ ...it0, noteSeq: null }, { generationKey: "g1", seq: 1 })).toBe("apply");
    expect(noteVerdict(it0, { generationKey: "g1", seq: 101 })).toBe("apply");
    expect(noteVerdict(it0, { generationKey: "g1", seq: 100 })).toBe("older");
    expect(noteVerdict(it0, { generationKey: "g1", seq: 99 })).toBe("older");
    expect(noteVerdict(it0, { generationKey: "g2", seq: 200 })).toBe("stale");
  });
  it("текст сохраняется как набран (без обрезки пробелов), номер версии — миллисекунды (не влезают в integer)", () => {
    const b = { itemId: 1, generationKey: "g1", body: "  ножки  \n", seq: 1_800_000_000_000, opId: "op-123456", editorId: "ed-123456", reviewer: "Аня" };
    const p = NoteBody.parse(b);
    expect(p.body).toBe("  ножки  \n");
    expect(p.seq).toBe(1_800_000_000_000);
    expect(NoteBody.safeParse({ ...b, body: "x".repeat(2001) }).success).toBe(false);
    expect(NoteBody.safeParse({ ...b, reviewer: " " }).success).toBe(false);
  });
  it("нажатие: expected обязателен (null — «не проверено»), лишнее нажатие — 400", () => {
    const b = { itemId: 1, generationKey: "g1", press: "bad", expected: null, reviewer: "Аня", idemKey: "k-12345678" };
    expect(PressBody.safeParse(b).success).toBe(true);
    expect(PressBody.safeParse({ ...b, press: "clear" }).success).toBe(false);
    expect(PressBody.safeParse({ ...b, expected: undefined }).success).toBe(false);
  });
});

describe("mesh-check: разделы", () => {
  it("роль → раздел; неизвестная и пустая — «Без типа»", () => {
    expect(sectionOf("диван")).toBe("divan");
    expect(sectionOf(" Торшер ")).toBe("svet");
    expect(sectionOf("ковёр")).toBe("other");
    expect(sectionOf(null)).toBe("other");
    expect(rolesOf("other")).toBeNull();
    expect(rolesOf("shkaf")).toContain("витрина");
  });
  it("счётчики «проверено N из M» в порядке обхода, пустые разделы скрыты; продолжить — с первого недоделанного", () => {
    const c = countSections([
      { role: "кашпо", checked: false },
      { role: "диван", checked: true },
      { role: "диван", checked: true },
      { role: null, checked: false },
    ]);
    expect(c.map((x) => [x.key, x.checked, x.total])).toEqual([
      ["divan", 2, 2],
      ["kashpo", 0, 1],
      ["other", 0, 1],
    ]);
    expect(firstOpenSection(c)).toBe("kashpo");
  });
});
