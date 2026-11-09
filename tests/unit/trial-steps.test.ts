import { describe, expect, it } from "vitest";
import { trialErrorCode, type TrialJobView } from "@/contracts/trial";
import { clock, errorText, geometryReady, progressOf, stepsOf, timer, uploadErrorText, waitingNote } from "@/lib/trial/steps";

// Страница задания пробы (agent-trial-01, T-C): три шага макета из стадий воркера, время, очередь, «машина занята», тексты
// на двух языках (agent-trial-08, П), когда пора в тур.
const T0 = "2026-11-09T12:00:00.000Z";
const at = (sec: number) => new Date(Date.parse(T0) + sec * 1000).toISOString();
const job = (over: Partial<TrialJobView> = {}): TrialJobView => ({
  id: "x".repeat(22), status: "queued", stage: "queued", stages: [], createdAt: T0, finishedAt: null, elapsedSec: 0,
  queueAhead: 0, workerAlive: true, errorCode: null, resultVersion: 0, bundleVersion: 0, rebuild: null, rebuildError: null, ...over,
});
const states = (j: TrialJobView) => stepsOf(j, "en").map((s) => s.state);

describe("stepsOf", () => {
  it("три шага макета на двух языках", () => {
    expect(stepsOf(job(), "en").map((s) => s.title)).toEqual(["Plan received", "Rooms and sizes read", "3D ready"]);
    expect(stepsOf(job(), "ru").map((s) => s.title)).toEqual(["План получен", "Комнаты и размеры прочитаны", "3D готово"]);
  });

  it("в очереди: принят — готов, остальное впереди и не крутится", () => {
    expect(states(job())).toEqual(["done", "next", "next"]);
  });

  it("взят воркером, стадии ещё нет — крутится чтение", () => {
    expect(states(job({ status: "running" }))).toEqual(["done", "run", "next"]);
    expect(states(job({ status: "running", stage: "labels", stages: [{ stage: "raster", at: at(2) }, { stage: "labels", at: at(9) }] })))
      .toEqual(["done", "run", "next"]);
  });

  it("идут стены: чтение готово со временем начала стен; пропущенная стадия не мешает", () => {
    const s = stepsOf(job({ status: "running", stage: "walls", stages: [{ stage: "raster", at: at(3) }, { stage: "walls", at: at(51) }] }), "en");
    expect(s.map((x) => x.state)).toEqual(["done", "done", "run"]);
    expect(s[1]!.atSec).toBe(51);
    expect(s[2]!.atSec).toBeNull();
  });

  it("готово: все шаги готовы, последний — время done или finishedAt", () => {
    const st = [{ stage: "raster", at: at(2) }, { stage: "walls", at: at(40) }, { stage: "done", at: at(78) }] as TrialJobView["stages"];
    const s = stepsOf(job({ status: "done", stage: "done", stages: st }), "en");
    expect(s.every((x) => x.state === "done")).toBe(true);
    expect(s[2]!.atSec).toBe(78);
    expect(stepsOf(job({ status: "done", stage: "done", stages: st.slice(0, 2), finishedAt: at(80) }), "en")[2]!.atSec).toBe(80);
    expect(progressOf(job({ status: "done" }))).toBe(1);
  });

  it("полоска растёт по стадиям и не доходит до конца до готовности", () => {
    const a = progressOf(job({ status: "running", stage: "raster" }));
    const b = progressOf(job({ status: "running", stage: "export" }));
    expect(a).toBeGreaterThan(progressOf(job()));
    expect(b).toBeGreaterThan(a);
    expect(b).toBeLessThan(1);
  });

  it("не удалось: текущий шаг не крутится", () => {
    expect(stepsOf(job({ status: "failed", stage: "labels" }), "en").some((x) => x.state === "run")).toBe(false);
  });
});

describe("тексты", () => {
  it("очередь, повтор, машина не на связи, обычное — как в макете", () => {
    expect(waitingNote(job({ queueAhead: 2 }), "en")).toMatch(/2 plans ahead/);
    expect(waitingNote(job({ queueAhead: 1 }), "en")).toMatch(/1 plan ahead/);
    expect(waitingNote(job({ stages: [{ stage: "raster", at: at(1) }] }), "en")).toMatch(/Trying again/);
    expect(waitingNote(job({ workerAlive: false }), "en")).toMatch(/busy right now/);
    expect(waitingNote(job({ status: "running", workerAlive: false }), "en")).toMatch(/busy right now/);
    expect(waitingNote(job({ status: "running" }), "en")).toBe("Times vary by floor plan");
  });

  it("то же по-русски: число планов в очереди склоняется", () => {
    expect(waitingNote(job({ queueAhead: 1 }), "ru")).toBe("В очереди: перед вашим 1 план.");
    expect(waitingNote(job({ queueAhead: 3 }), "ru")).toBe("В очереди: перед вашим 3 плана.");
    expect(waitingNote(job({ queueAhead: 11 }), "ru")).toBe("В очереди: перед вашим 11 планов.");
    expect(waitingNote(job({ workerAlive: false }), "ru")).toMatch(/3D-машина сейчас занята/);
    expect(waitingNote(job({ status: "running" }), "ru")).toBe("Время зависит от плана");
  });

  it("ошибки — по коду, неизвестное — общий текст; без длинных тире; у каждого кода оба языка", () => {
    expect(errorText("pdf_unreadable", "en")).toMatch(/PDF/);
    expect(errorText(null, "en")).toMatch(/Something went wrong/);
    expect(errorText(null, "ru")).toMatch(/что-то пошло не так/);
    expect(uploadErrorText("rate_limited", "en")).toMatch(/10 minutes/);
    expect(uploadErrorText("rate_limited", "ru")).toMatch(/минут 10/);
    expect(uploadErrorText("whatever", "en")).toMatch(/didn't go through/);
    expect(uploadErrorText("toString", "ru")).toMatch(/Загрузка не прошла/); // не поле прототипа
    for (const c of trialErrorCode.options) {
      for (const lang of ["en", "ru"] as const) expect(errorText(c, lang)).not.toMatch(/—/);
      expect(errorText(c, "ru")).toMatch(/[а-я]/);
    }
    for (const c of ["busy", "daily_cap", "rate_limited", "too_large", "unsupported_type", "no_file", "listing_too_long"]) {
      expect(uploadErrorText(c, "ru")).not.toBe(uploadErrorText(undefined, "ru"));
      expect(uploadErrorText(c, "en")).not.toBe(uploadErrorText(undefined, "en"));
    }
  });

  it("тур — когда геометрия опубликована: готово или промежуточная версия у идущего", () => {
    expect(geometryReady(job({ status: "done", resultVersion: 1 }))).toBe(true);
    expect(geometryReady(job({ status: "running", resultVersion: 1 }))).toBe(true);
    expect(geometryReady(job({ status: "running" }))).toBe(false);
    expect(geometryReady(job())).toBe(false);
    expect(geometryReady(job({ status: "failed", resultVersion: 1 }))).toBe(false);
  });

  it("часы: шаг «м:сс», таймер «мм:сс»", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(78.9)).toBe("1:18");
    expect(clock(3725)).toBe("1:02:05");
    expect(timer(102)).toBe("01:42");
    expect(timer(5)).toBe("00:05");
    expect(timer(3725)).toBe("1:02:05");
  });
});
