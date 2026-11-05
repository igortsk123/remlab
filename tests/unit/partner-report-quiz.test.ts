import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { buildReport, type ReportInput } from "@/modules/partner-report/report";

// ОТЧЁТ ЗАСТРОЙЩИКУ: БЛОК «ЗНАКОМСТВО» (план onb-12, ADR-0265 + ADR-0330 п.4). Квартира без опроса — отчёт побайтно прежний:
// эталон `tests/fixtures/partner-report-noquiz.json` снят с кода ДО блока (onb-12d); пересъёмка — только осознанно,
// `UPDATE_GOLDEN=1 pnpm vitest run tests/unit/partner-report-quiz.test.ts`.

const GOLDEN = "tests/fixtures/partner-report-noquiz.json";
const NOW = new Date("2026-10-21T12:00:00Z");
const OLD_KINDS = ["designer_open", "variant_view", "item_swap", "flat3d_open", "item_move", "share", "stale_link", "floor_pick", "walls_pick",
  "favourite_save", "favourite_rename", "view_switch", "style_tab"];
const ENGAGE_OLD = ["variant_view", "item_swap", "item_move", "share", "manager_contact_click", "alternative_request", "flat3d_open", "floor_pick", "walls_pick"];
const noQuiz: ReportInput = {
  sends: ["a", "b", "c", "d", "e"].map((id, i) => ({ id, apartmentId: i % 2 ? "uk1" : "flat215", createdAt: new Date(`2026-10-${String(8 + i * 3).padStart(2, "0")}T10:00:00Z`),
    openedAt: i < 3 ? new Date("2026-10-20T10:00:00Z") : null, status: ["sent", "opened", "engaged", "meeting", "deal"][i]! })),
  events: [
    ...ENGAGE_OLD.map((kind, i) => ({ sendId: ["a", "b", "c"][i % 3]!, kind })),
    { sendId: "a", kind: "designer_open" }, { sendId: "d", kind: "designer_open" }, { sendId: "e", kind: "status" },
  ],
  savedSendIds: ["b"],
  counters: OLD_KINDS.flatMap((kind, i) => [
    { day: "2026-10-13", apartmentId: "flat215", kind, n: i + 1 },
    { day: "2026-10-20", apartmentId: i % 2 ? "uk1" : "flat215", kind, n: 2 * i + 1 },
  ]),
  timezone: "Europe/Moscow", now: NOW,
};

describe("отчёт без опроса — прежний", () => {
  it("побайтно совпадает с эталоном, снятым до блока «Знакомство»", () => {
    const got = JSON.stringify(buildReport(noQuiz), null, 1);
    if (process.env.UPDATE_GOLDEN || !existsSync(GOLDEN)) writeFileSync(GOLDEN, got + "\n");
    expect(got + "\n").toBe(readFileSync(GOLDEN, "utf8"));
  });
});
