import { test, expect, type Page } from "@playwright/test";

// ПРОГУЛКА /flat НЕ СКВОЗЬ МЕБЕЛЬ — ЧИСЛАМИ, А НЕ ЭКРАНОМ (demo-05 п.1д, приёмка п.5 по просьбе d8 15.10). По снимку не
// отличить «камера внутри тумбы» от «упёрлась в стену»: оба — серый экран. Поэтому у движка спрашиваем позицию и расстояние
// до ближайшего следа мебели (`viewer.debugWalk`): в каждом опубликованном варианте поворачиваемся к каждому предмету ядра,
// идём 4 с и требуем — камера в комнате и не ближе 25 см к мебели. Позиции печатаются в отчёт.

type Walk = { x: number; y: number; heading: number; inRoom: boolean; nearestCm: number | null };
type Viewer = {
  debugState(): { placed: number };
  debugWalk(): Walk;
  faceToward(x: number, y: number): void;
  keyDown(code: string): void;
  keyUp(code: string): void;
};
type Item = { role?: string; x?: number; y?: number; sku?: { msid?: string } };

const CORE = ["диван", "столик", "тв-тумба", "стол обеденный"];

// без видеокарты (DEV, ночной шаг) вкладка /flat падала на втором варианте (прогон d8 15.10, «Target crashed»): явный
// программный рендер ANGLE и свежая вкладка на каждый вариант — память сцены уходит вместе с вкладкой
test.use({ launchOptions: { args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] } });
const MIN_CM = 25;

async function viewerReady(page: Page, want: number): Promise<void> {
  // готовность — состояние, а не время: предметов в сцене столько, сколько у варианта, два замера подряд
  let last = -1;
  for (let i = 0; i < 90; i += 1) {
    const n = await page.evaluate(() => {
      const v = (window as unknown as { __flatViewer?: Viewer }).__flatViewer;
      return v ? v.debugState().placed : -1;
    });
    if (n >= want && n === last) return;
    last = n;
    await page.waitForTimeout(1000);
  }
}

test("1д прогулка /flat: 4 с к каждому предмету ядра — в комнате и ≥ 25 см от мебели", async ({ browser, request }) => {
  test.setTimeout(20 * 60_000);
  const data = (await (await request.get(process.env.LIVE_DEMO_DATA ?? "/demo/demo-data.json")).json()) as { variants: { id: string; style?: string; items: Item[] }[] };
  const report: string[] = [];
  const bad: string[] = [];
  for (const v of data.variants) {
    const page = await browser.newPage();
    await page.goto(`/flat?demo=${v.id}&flat=flat215`, { waitUntil: "load", timeout: 120_000 });
    await viewerReady(page, v.items.filter((it) => it.sku?.msid && !String(it.role).startsWith("ковёр")).length);
    const start = (await page.evaluate("window.__flatViewer.debugWalk()")) as Walk;
    report.push(`${v.id} ${v.style ?? ""}: старт (${start.x}, ${start.y}) до мебели ${start.nearestCm} см`);
    if (!start.inRoom || (start.nearestCm ?? 999) < MIN_CM) bad.push(`${v.id} старт: ${JSON.stringify(start)}`);
    for (const role of CORE) {
      const it = v.items.find((i) => i.role === role);
      if (!it || it.x === undefined || it.y === undefined) continue;
      await page.evaluate(([x, y]) => {
        const vw = (window as unknown as { __flatViewer: Viewer }).__flatViewer;
        vw.faceToward(x as number, y as number);
        vw.keyDown("KeyW");
      }, [it.x, it.y]);
      await page.waitForTimeout(4000);
      const w = (await page.evaluate(() => {
        const vw = (window as unknown as { __flatViewer: Viewer }).__flatViewer;
        vw.keyUp("KeyW");
        return vw.debugWalk();
      })) as Walk;
      report.push(`  → ${role}: (${w.x}, ${w.y}) в комнате ${w.inRoom ? "да" : "НЕТ"}, до мебели ${w.nearestCm} см`);
      if (!w.inRoom || (w.nearestCm ?? 999) < MIN_CM) bad.push(`${v.id} → ${role}: ${JSON.stringify(w)}`);
    }
    await page.close();
  }
  console.log(report.join("\n"));
  expect(bad, "камера вне комнаты или ближе 25 см к мебели").toEqual([]);
});
