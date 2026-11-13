import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { NO_ZOOM_CSS, NO_ZOOM_JS, NO_ZOOM_VIEWPORT, noZoomHead } from "@/lib/page/no-zoom";
import { stubHtml } from "@/lib/trial/tour-stub";

// Масштаб страницы на телефоне запрещён везде одним правилом (T-20261113-15, П1.58): сайт, туры, витрина /demo.
const ROOT = path.resolve(__dirname, "../..");
const read = (p: string) => readFileSync(path.join(ROOT, p), "utf8");

describe("запрет масштаба страницы — одно правило на все страницы", () => {
  it("витрина /demo (и туры — её копия) несёт ровно блок правила, других viewport нет", () => {
    const html = read("tools/scout/flat215-demo/index.html");
    const m = html.match(/<!-- no-zoom:start[\s\S]*?<!-- no-zoom:end -->/g);
    expect(m).toHaveLength(1);
    expect(m![0]).toBe(noZoomHead("viewport-fit=cover"));
    expect(html.match(/<meta name="viewport"/g)).toHaveLength(1);
  });

  it("заглушка тура — тот же блок", () => {
    const html = stubHtml("wait", "abc", "/try/abc/tour/", { lang: "ru" });
    expect(html).toContain(noZoomHead());
    expect(html.match(/name="viewport"/g)).toHaveLength(1);
  });

  it("сайт: viewport без масштаба, стиль и скрипт правила в <head>", () => {
    const src = read("app/layout.tsx");
    expect(src).toMatch(/export const viewport: Viewport = \{[^}]*maximumScale: 1[^}]*userScalable: false/);
    expect(src).toContain("__html: NO_ZOOM_CSS");
    expect(src).toContain("__html: NO_ZOOM_JS");
    expect(NO_ZOOM_VIEWPORT).toContain("maximum-scale=1");
    expect(NO_ZOOM_VIEWPORT).toContain("user-scalable=no");
  });

  it("двойной тап — manipulation у корня; поля на сенсорном экране не мельче 16 px", () => {
    expect(NO_ZOOM_CSS).toContain("html{touch-action:manipulation");
    expect(NO_ZOOM_CSS).toMatch(/pointer:coarse\)\{input,textarea,select\{font-size:max\(16px,1em\)/);
  });

  it("скрипт: щипок страницы (жесты iOS, два пальца) гасится, прокрутка одним пальцем — нет, повторный запуск не вешает второй раз", () => {
    const ls: Record<string, Array<(e: unknown) => void>> = {};
    const doc = { addEventListener: (t: string, f: (e: unknown) => void, o: { passive: boolean }) => {
      expect(o.passive).toBe(false);
      (ls[t] ||= []).push(f);
    } };
    const win: Record<string, unknown> = {};
    new Function("window", "document", NO_ZOOM_JS)(win, doc);
    new Function("window", "document", NO_ZOOM_JS)(win, doc);
    const fire = (t: string, e: Record<string, unknown>) => {
      let prevented = false;
      for (const f of ls[t] || []) f({ ...e, preventDefault: () => { prevented = true; } });
      return prevented;
    };
    for (const t of ["gesturestart", "gesturechange", "gestureend"]) {
      expect(ls[t]).toHaveLength(1);
      expect(fire(t, { scale: 1.4 })).toBe(true);
    }
    expect(fire("touchmove", { touches: [{}, {}] })).toBe(true);
    expect(fire("touchmove", { touches: [{}], scale: 1.3 })).toBe(true);
    expect(fire("touchmove", { touches: [{}] })).toBe(false);
    expect(fire("touchmove", { touches: [{}], scale: 1 })).toBe(false);
  });
});
