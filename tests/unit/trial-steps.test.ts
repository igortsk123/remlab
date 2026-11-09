import { describe, expect, it } from "vitest";
import type { TrialJobView } from "@/contracts/trial";
import { clock, errorText, progressOf, stepsOf, timer, uploadErrorText, waitingNote } from "@/lib/trial/steps";

// Страница задания пробы (agent-trial-01, T-C): три шага макета из стадий воркера, время, очередь, «машина занята», тексты.
const T0 = "2026-11-09T12:00:00.000Z";
const at = (sec: number) => new Date(Date.parse(T0) + sec * 1000).toISOString();
const job = (over: Partial<TrialJobView> = {}): TrialJobView => ({
  id: "x".repeat(22), status: "queued", stage: "queued", stages: [], createdAt: T0, finishedAt: null, elapsedSec: 0,
  queueAhead: 0, workerAlive: true, errorCode: null, resultVersion: 0, ...over,
});
const states = (j: TrialJobView) => stepsOf(j).map((s) => s.state);

describe("stepsOf", () => {
  it("три шага макета", () => {
    expect(stepsOf(job()).map((s) => s.title)).toEqual(["Plan received", "Rooms and sizes read", "3D ready"]);
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
    const s = stepsOf(job({ status: "running", stage: "walls", stages: [{ stage: "raster", at: at(3) }, { stage: "walls", at: at(51) }] }));
    expect(s.map((x) => x.state)).toEqual(["done", "done", "run"]);
    expect(s[1]!.atSec).toBe(51);
    expect(s[2]!.atSec).toBeNull();
  });

  it("готово: все шаги готовы, последний — время done или finishedAt", () => {
    const st = [{ stage: "raster", at: at(2) }, { stage: "walls", at: at(40) }, { stage: "done", at: at(78) }] as TrialJobView["stages"];
    const s = stepsOf(job({ status: "done", stage: "done", stages: st }));
    expect(s.every((x) => x.state === "done")).toBe(true);
    expect(s[2]!.atSec).toBe(78);
    expect(stepsOf(job({ status: "done", stage: "done", stages: st.slice(0, 2), finishedAt: at(80) }))[2]!.atSec).toBe(80);
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
    expect(stepsOf(job({ status: "failed", stage: "labels" })).some((x) => x.state === "run")).toBe(false);
  });
});

describe("тексты", () => {
  it("очередь, повтор, машина не на связи, обычное — как в макете", () => {
    expect(waitingNote(job({ queueAhead: 2 }))).toMatch(/2 plans ahead/);
    expect(waitingNote(job({ queueAhead: 1 }))).toMatch(/1 plan ahead/);
    expect(waitingNote(job({ stages: [{ stage: "raster", at: at(1) }] }))).toMatch(/Trying again/);
    expect(waitingNote(job({ workerAlive: false }))).toMatch(/busy right now/);
    expect(waitingNote(job({ status: "running", workerAlive: false }))).toMatch(/busy right now/);
    expect(waitingNote(job({ status: "running" }))).toBe("Times vary by floor plan");
  });

  it("ошибки — по коду, неизвестное — общий текст; без длинных тире", () => {
    expect(errorText("pdf_unreadable")).toMatch(/PDF/);
    expect(errorText(null)).toMatch(/Something went wrong/);
    expect(uploadErrorText("rate_limited")).toMatch(/10 minutes/);
    expect(uploadErrorText("whatever")).toMatch(/didn't go through/);
    for (const c of ["pdf_unreadable", "no_plan", "budget", "timeout", "stale"] as const) expect(errorText(c)).not.toMatch(/—/);
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
