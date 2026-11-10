import { describe, expect, it } from "vitest";

import { trialOpeningEditIn, type TrialOpeningEditIn } from "@/contracts/trial";
import { openingRows, panelNow } from "@/lib/trial/repo-opening-edit";
import { injectTour, openingEditPath } from "@/lib/trial/tour-page";

// Окна и двери агента на плане тура (T-20261110-39): форма тела, панель → проёмы с ключами и охват, только изменённые строки, песочница.

type Op = TrialOpeningEditIn["ops"][number];
const op = (over: Record<string, unknown> = {}): Op => ({ key: "s1", kind: "door", c: [505, 200], w_cm: 80, removed: false, ...over }) as Op;
const ok = { k: "A".repeat(22), request_id: "open-0000001", base_version: 3, panel: "p0", ops: [op()] };
const box = (x: number, w = 500, d = 400) => ({ x, y: 0, w, d });
const bundle = { trial: { panels: [{ id: "p0", rooms: [{ id: "living", bbox: box(0) }, { id: "bedroom-1", bbox: box(510, 300) }],
  openings: [{ kind: "window", c: [250, 0], widthCm: 150, exterior: true }, { kind: "door", c: [505, 200], widthCm: 80 },
    { kind: "door", c: [700, 400], widthCm: 90, key: "uAAAAAA1", user: true }, { kind: "window", c: [100, 400], widthCm: 0 }] }] } };

describe("окна и двери: контракт и правила", () => {
  it("тело: ключ s<номер> или u<токен>, тип окно/дверь, ширина 30…600, 1…30 проёмов; иное не проходит", () => {
    expect(trialOpeningEditIn.parse(ok).ops[0]).toEqual(op());
    expect(trialOpeningEditIn.safeParse({ ...ok, ops: [op({ key: "uA1b2C3d4" })] }).success).toBe(true);
    for (const bad of [{ ops: [] }, { ops: Array.from({ length: 31 }, () => op()) }, { ops: [op({ key: "x1" })] }, { ops: [op({ key: "u123" })] },
      { ops: [op({ kind: "opening" })] }, { ops: [op({ w_cm: 29 })] }, { ops: [op({ w_cm: 601 })] }, { ops: [op({ c: [1] })] }, { panel: "" },
      { k: "short" }]) {
      expect(trialOpeningEditIn.safeParse({ ...ok, ...bad }).success).toBe(false);
    }
  });

  it("панель → проёмы с ключами (у прочитанного — s<номер> и центр как прочитан; у агентского — свой ключ), охват комнат", () => {
    const now = panelNow(bundle, "p0")!;
    expect(now.openings.map((o) => [o.key, o.kind, o.w, o.srcC])).toEqual([["s0", "window", 150, [250, 0]], ["s1", "door", 80, [505, 200]],
      ["uAAAAAA1", "door", 90, null]]);
    expect(now.box).toEqual({ x0: 0, y0: 0, x1: 810, y1: 400 });
    expect(panelNow(bundle, "p9")).toBeNull();
    expect(panelNow({}, "p0")).toBeNull();
  });

  it("строки: только изменённые (< 1 см и тот же тип — нет); снятый свой новый — нет; чужой ключ s и центр вне плана — bad_opening", () => {
    const now = panelNow(bundle, "p0")!;
    expect(openingRows(now, [op({ c: [505.4, 200.3] }), op({ key: "uZZZZZZ9", removed: true })])).toEqual([]);
    expect(openingRows(now, [op({ kind: "window" }), op({ key: "s0", kind: "window", c: [250, 0], w_cm: 150, removed: true }),
      op({ key: "uBBBBBB1", c: [300.04, 400], w_cm: 90.4 })])).toEqual([
      { key: "s1", srcIdx: 1, srcC: [505, 200], kind: "window", c: [505, 200], w: 80, removed: false },
      { key: "s0", srcIdx: 0, srcC: [250, 0], kind: "window", c: [250, 0], w: 150, removed: true },
      { key: "uBBBBBB1", srcIdx: null, srcC: null, kind: "door", c: [300, 400], w: 90, removed: false }]);
    expect(openingRows(now, [op({ key: "uAAAAAA1", c: [720, 400], w_cm: 90 })])).toMatchObject([{ key: "uAAAAAA1", srcC: null, c: [720, 400] }]);
    // свой опубликованный сдвинут и снят — центр как в сборке: у него стоит мебель, комнаты у него воркер пересоберёт
    expect(openingRows(now, [op({ key: "uAAAAAA1", c: [760, 400], w_cm: 90, removed: true })])).toMatchObject([{ key: "uAAAAAA1", c: [700, 400],
      removed: true }]);
    expect(openingRows(now, [op({ key: "s7" })])).toBe("bad_opening");
    expect(openingRows(now, [op({ key: "uCCCCCC1", c: [1000, 200] })])).toBe("bad_opening");
  });

  it("песочница тура пропускает ручку окон и дверей ЭТОГО задания и только её", () => {
    const id = "a".repeat(22);
    const html = injectTour("<html><head></head><body></body></html>", id, 1);
    expect(html).toContain(JSON.stringify(openingEditPath(id)));
    expect(html).not.toContain(`/api/trial/${"b".repeat(22)}/opening-edit`);
  });
});
