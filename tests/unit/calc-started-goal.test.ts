import { afterEach, describe, expect, it, vi } from "vitest";

import { calcStartedGoal } from "@/lib/calc/started-goal";
import { METRIKA_COUNTER_ID } from "@/lib/metrika";

// ЦЕЛЬ «РАСЧЁТ НАЧАТ» (T-20261020-03): одна на расчёт — первая правка с площадью > 0; повтор только после
// «новый расчёт»; уходит через trackGoal, поэтому молчит, когда metrikaAllowed() = false.

function stubPage(path: string, search = "", store: Record<string, string> = {}) {
  const ym = vi.fn();
  vi.stubGlobal("window", { ym, location: { pathname: path, search } });
  vi.stubGlobal("localStorage", { getItem: (k: string) => store[k] ?? null });
  return ym;
}

afterEach(() => vi.unstubAllGlobals());

describe("calcStartedGoal", () => {
  it("правки без площади не шлют; первая площадь — одна цель, дальнейшие правки — нет", () => {
    const send = vi.fn();
    const g = calcStartedGoal(send);
    g.edited(false);
    g.edited(false);
    expect(send).not.toHaveBeenCalled();
    g.edited(true);
    g.edited(true);
    g.edited(false);
    g.edited(true);
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("«новый расчёт» (reset) — следующая площадь снова цель", () => {
    const send = vi.fn();
    const g = calcStartedGoal(send);
    g.edited(true);
    g.reset();
    g.edited(true);
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("по умолчанию шлёт reachGoal calc_started в счётчик Метрики", () => {
    const ym = stubPage("/calc/oboi");
    const g = calcStartedGoal();
    g.edited(true);
    g.edited(true);
    expect(ym).toHaveBeenCalledTimes(1);
    expect(ym).toHaveBeenCalledWith(METRIKA_COUNTER_ID, "reachGoal", "calc_started");
  });

  it("metrikaAllowed() = false (английский режим без согласия) — ничего не уходит", () => {
    const ym = stubPage("/calc/oboi", "?lang=en");
    calcStartedGoal().edited(true);
    expect(ym).not.toHaveBeenCalled();
  });

  it("английский режим с согласием — уходит", () => {
    const ym = stubPage("/calc/oboi", "", { "remlab-lang": "en", "remlab-cookies": "yes" });
    calcStartedGoal().edited(true);
    expect(ym).toHaveBeenCalledTimes(1);
  });
});
