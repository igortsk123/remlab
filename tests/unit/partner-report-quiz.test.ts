import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { pageCounterKind } from "@/contracts/analytics";
import { QUIZ_CHILD_RU, QUIZ_COLOUR_RU, QUIZ_HOUSEHOLD_RU, QUIZ_KIDS_RU, QUIZ_STYLE_RU } from "@/contracts/quiz";
import { buildQuiz, quizPart } from "@/modules/partner-report/quiz";
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

const c = (kind: string, n: number, apartmentId = "flat215", day = "2026-10-20") => ({ day, apartmentId, kind, n });
const withQuiz = (counters: ReportInput["counters"], over: Partial<ReportInput> = {}): ReportInput => ({ ...noQuiz, counters: [...noQuiz.counters, ...counters], ...over });

describe("блок «Знакомство»", () => {
  it("все 44 счётчика опроса из словаря `pageCounterKind` узнаются блоком, прочие — нет", () => {
    const quiz = pageCounterKind.options.filter((k) => quizPart(k));
    expect(quiz).toHaveLength(44);   // 38 + шаг спальни `quiz_bedroom:<стиль>` (опрос по комнатам, home-mix-01)
    expect(pageCounterKind.options.filter((k) => !quizPart(k))).toEqual(OLD_KINDS);
    for (const k of ["quiz_photo:pink", "quiz_child:5", "quiz_kids:4", "quiz_household:", "quiz_x:loft", "quiz"]) expect(quizPart(k)).toBeNull();
  });

  it("у каждого значения ответа есть русская подпись словаря", () => {
    const dict: Record<string, Record<string, string>> = { photo: QUIZ_STYLE_RU, bedroom: QUIZ_STYLE_RU, result: QUIZ_STYLE_RU, chosen: QUIZ_STYLE_RU,
      household: QUIZ_HOUSEHOLD_RU, child: QUIZ_CHILD_RU, kids: QUIZ_KIDS_RU, colour: QUIZ_COLOUR_RU };
    for (const k of pageCounterKind.options) {
      const p = quizPart(k);
      if (p && "group" in p) expect(dict[p.group]![p.id], k).toBeTruthy();
    }
  });

  it("действия и ответы суммируются по квартире за окно; заходы без ссылки и воронка — прежние", () => {
    const r = buildReport(withQuiz([c("quiz_open", 10), c("quiz_open", 4, "flat215", "2026-10-13"), c("quiz_done", 6), c("quiz_skip", 3),
      c("style_change", 2), c("quiz_photo:loft", 4), c("quiz_photo:scandi", 3), c("quiz_result:loft", 6), c("quiz_chosen:loft", 5),
      c("quiz_household:couple", 4), c("quiz_household:pet", 1), c("quiz_kids:2", 2), c("quiz_colour:light", 5), c("quiz_open", 2, "uk1"), c("quiz_photo:pink", 9)]));
    const old = JSON.parse(readFileSync(GOLDEN, "utf8")) as ReturnType<typeof buildReport>;
    expect(r.direct).toEqual(old.direct);
    expect(r.weeks).toEqual(old.weeks);
    expect(r.quiz?.map((q) => q.apartmentId)).toEqual(["flat215", "uk1"]);
    const f = r.quiz![0]!;
    expect(f).toMatchObject({ open: 14, done: 6, skip: 3, styleChange: 2 });
    expect(f.photo).toEqual([{ id: "scandi", n: 3 }, { id: "loft", n: 4 }]);            // витрина неизвестна — по словарю, только выбранные
    expect(f.household.map((h) => h.id)).toEqual(["single", "couple", "child", "pet", "guest"]);   // по словарю, нули — тоже ответ
    expect(f.household.find((h) => h.id === "couple")?.n).toBe(4);
    expect(f.child.every((x) => x.n === 0)).toBe(true);
    expect(f.kids).toEqual([{ id: "1", n: 0 }, { id: "2", n: 2 }, { id: "3plus", n: 0 }]);   // сколько детей (T-20261106-94)
    expect(r.quiz![1]).toMatchObject({ open: 2, done: 0 });
  });

  it("стили — в порядке витрины; стиль вне витрины — только если выбирали", () => {
    const showcase = { flat215: ["loft", "scandi", "modern", "minimal", "japandi"] };
    const [f] = buildQuiz([c("quiz_photo:scandi", 3), c("quiz_photo:neoclassic", 1), c("quiz_chosen:loft", 2)], showcase);
    expect(f!.photo.map((x) => x.id)).toEqual(["loft", "scandi", "modern", "minimal", "japandi", "neoclassic"]);
    expect(f!.chosen.map((x) => [x.id, x.n])).toEqual([["loft", 2], ["scandi", 0], ["modern", 0], ["minimal", 0], ["japandi", 0]]);
  });

  it("шаг спальни — своя группа, в порядке витрины; гостиные не смешиваются со спальнями", () => {
    const showcase = { flat215: ["loft", "scandi", "modern", "minimal", "japandi"] };
    const [f] = buildQuiz([c("quiz_photo:scandi", 3), c("quiz_bedroom:loft", 2), c("quiz_bedroom:japandi", 1)], showcase);
    expect(f!.bedroom.map((x) => [x.id, x.n])).toEqual([["loft", 2], ["scandi", 0], ["modern", 0], ["minimal", 0], ["japandi", 1]]);
    expect(f!.photo.find((x) => x.id === "loft")?.n).toBe(0);
  });

  it("окно отчёта отсекает старые счётчики опроса; одни старые — блока нет", () => {
    const r = buildReport(withQuiz([c("quiz_open", 5, "flat215", "2026-08-02")], { fromWeek: "2026-08-03" }));
    expect(r).not.toHaveProperty("quiz");
  });

  it("«прошёл знакомство» по ссылке менеджера считается в «выбирал»", () => {
    const r = buildReport({ ...noQuiz, sends: [{ id: "q", apartmentId: "flat215", createdAt: new Date("2026-10-20T10:00:00Z"), openedAt: null, status: "engaged" }],
      events: [{ sendId: "q", kind: "designer_open" }, { sendId: "q", kind: "quiz_done" }], counters: [] });
    expect(r.total).toMatchObject({ sent: 1, opened: 1, engaged: 1 });
  });
});
