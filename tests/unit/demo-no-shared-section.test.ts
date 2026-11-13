import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// РАЗДЕЛА «РАССТАНОВКИ ПО ССЫЛКЕ» НА ГЛАВНОЙ НЕТ (владелец 13.11, TG 1449/1453, T-20261113-14). Было: каждая открытая чужая ссылка
// запоминалась в браузере (`remember(want, …, false)`) и вставала карточкой «shared collection · …» на главной /demo и туров навсегда.
// Стало: ссылка открывает свою расстановку (`openId`), на главной ничего не копится, прежние такие записи при загрузке убираются.
// Живая проверка — `~/remlab-logs/t14-1113/coll-probe.cjs` (подставная коллекция, прод не трогает).
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const at = (from: string, to: string) => { const i = html.indexOf(from); expect(i, from).toBeGreaterThanOrEqual(0); return html.slice(i, html.indexOf(to, i)); };

describe("главная /demo: раздела коллекций по ссылке нет", () => {
  it("нет заголовка раздела ни в разметке, ни в коде", () => {
    expect(html).not.toContain('id="collHead"');
    expect(html).not.toContain("getElementById('collHead')");
    expect(html).not.toMatch(/Layouts from links|Расстановки по ссылке<\/h2>/);
  });

  it("сетка коллекций пуста и скрыта всегда — карточки не строятся", () => {
    const fn = at("function drawColl(force){", "\n}\n");
    expect(fn).toContain("box.innerHTML=''; box.hidden=true;");
    expect(fn).not.toMatch(/createElement|appendChild|data-swap/);
    expect(fn).toContain("drawHome();");   // главная перерисовывается, как раньше
  });

  it("открытая по ссылке не запоминается; своя — запоминается при сохранении", () => {
    const boot = at("  function boot(){", "\n  function snapshot(){");
    expect(boot).toContain("if(v)openId(want);");
    expect(boot).not.toMatch(/remember\(want/);
    expect(html).toMatch(/function afterSave\(id,snap\)\{remember\(id,snap\.style\|\|'',true\)/);
  });

  it("прежние чужие записи убираются, свои остаются", () => {
    const boot = at("  function boot(){", "\n  function snapshot(){");
    const purge = boot.split("\n").find((l) => l.includes("var keep=list().filter"));
    expect(purge).toBeDefined();
    // та же строка на заглушке localStorage
    const store: Record<string, string> = { "remlab-collections": JSON.stringify([
      { id: "a".repeat(22), own: true }, { id: "b".repeat(22), own: false }, { id: "c".repeat(22) }]) };
    const localStorage = { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => { store[k] = v; } };
    const KEY = "remlab-collections";
    const list = () => (JSON.parse(localStorage.getItem(KEY) || "[]") as { id: string; own?: boolean }[]).filter((x) => /^[A-Za-z0-9_-]{22}$/.test(x.id));
    new Function("localStorage", "KEY", "list", purge!)(localStorage, KEY, list);
    expect((JSON.parse(store[KEY]!) as { id: string }[]).map((x) => x.id)).toEqual(["a".repeat(22)]);
  });
});
