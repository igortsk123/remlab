import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
// @ts-expect-error — модуль .mjs без типов (тот же код запускается из командной строки)
import { DEBT, PAGE, cyrillicInDicts, internalLeaks, scan, translator } from "../../tools/ops/demo-i18n-scan.mjs";

// СТОРОЖ ПЕРЕВОДА СТРАНИЦЫ ДЕМО (T-20261112-116, владелец TG 1337/1341: «на английском всегда английские слова, на русском — русские;
// всегда, когда добавляется функционал, проходить контроль»). Каждая строка кода страницы с кириллицей либо служебная, либо с парой
// RU/EN в коде, либо переводится словарём показа (`tr`). Новая строка без пары — красный тест: дайте пару (`EN?'…':'…'`, `T('…','…')`)
// или строку в словарь `EX` страницы. Долг до сторожа — `tools/scout/data/demo-i18n-debt.json`, только уменьшается.
// Живой обход — `tools/ops/demo-walk/lang-check.cjs` (видимый текст EN/RU и валюта на каждом экране).
type Unpaired = { text: string; line: number };
const html = readFileSync(PAGE, "utf8");
const debt = new Set<string>(JSON.parse(readFileSync(DEBT, "utf8")).strings);

describe("перевод страницы демо RU/EN", () => {
  it("новые строки интерфейса — только с парой RU/EN", () => {
    const { unpaired } = scan(html) as { unpaired: Unpaired[] };
    const fresh = unpaired.filter((u) => !debt.has(u.text)).map((u) => `стр. ${u.line}: «${u.text}»`);
    expect(fresh, "строка без английской пары — дайте пару в коде или в словаре EX (T-20261112-116)").toEqual([]);
  });

  it("словарь показа — переводы латиницей", () => {
    expect(cyrillicInDicts(html)).toEqual([]);
  });

  it("словарь переводит роли, комнаты и строки с числами", () => {
    const { tr } = translator(html) as { tr: (s: string) => string | null };
    expect(tr("диван")).toBe("sofa");
    expect(tr("стул · 2 шт.")).toBe("chair · 2 pcs");
    expect(tr("Гостиная")).toBe("Living room");
    expect(tr("Sofa")).toBeNull();   // английское не трогает
  });

  it("сторож различает пару и строку без пары", () => {
    const one = (js: string) => (scan(`${html}<script>${js}</script>`) as { unpaired: Unpaired[] }).unpaired.map((u) => u.text)
      .filter((t) => t.startsWith("Пробная"));
    expect(one("x.textContent='Пробная надпись';")).toEqual(["Пробная надпись"]);
    expect(one("x.textContent=EN?'Test label':'Пробная надпись';")).toEqual([]);
    expect(one("x.textContent=T('Пробная надпись','Test label');")).toEqual([]);
    expect(one("if(s==='Пробная надпись')go();")).toEqual([]);
  });

  it("внутренняя причина (liveOff, LIVE.why, console) — служебная, но на экран не попадает (T-20261112-116/2)", () => {
    const one = (js: string) => (scan(`${html}<script>${js}</script>`) as { unpaired: Unpaired[] }).unpaired.map((u) => u.text)
      .filter((t) => t.startsWith("Пробная") || t.startsWith("раз"));
    expect(one("liveOff('Пробная причина '+n+' раза за 2 мин');")).toEqual([]);
    expect(one("liveOff(a?'Пробная причина':'Пробная другая '+n);")).toEqual([]);
    expect(one("LIVE.why='Пробная причина';")).toEqual([]);
    expect(one("x.textContent='Пробная причина '+n+' раз';")).toEqual(["Пробная причина", "раз"]);   // надпись — по-прежнему ловится
    expect(internalLeaks(html)).toEqual([]);
    expect(internalLeaks(`${html}<script>function f(){ el.textContent='3D: '+LIVE.why; }</script>`)).toHaveLength(1);
    const own = html.replace("function liveOff(why){", "function liveOff(why){ el.innerHTML=why;");
    expect(internalLeaks(own).some((s: string) => s.startsWith("liveOff"))).toBe(true);
  });
});
