import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

import { demoUrl } from "../../e2e/live/browser";

// ОБХОД ОПРОСА В АВТОМАТИКЕ (onb-03 Т9, ADR-0330 п.5): живые проверки и скрипты-обходы открывают демо с `quiz=0`. Две копии одной
// функции — для TypeScript-проверок и для .cjs/.mjs-скриптов — дают одно и то же.
const cjs = createRequire(import.meta.url)("../../tools/ops/demo-url.cjs") as { demoUrl: (p: string) => string };

describe("demoUrl — quiz=0 к адресу демо", () => {
  it.each([
    ["/demo/", "/demo/?quiz=0"],
    ["/demo/?live=0", "/demo/?live=0&quiz=0"],
    ["/demo/?lang=en", "/demo/?lang=en&quiz=0"],
    ["/demo/#v=s1-abc", "/demo/?quiz=0#v=s1-abc"],
    ["/demo/?live=0&lang=ru#plan", "/demo/?live=0&lang=ru&quiz=0#plan"],
    ["https://remont-lab.online/demo/?lang=ru&", "https://remont-lab.online/demo/?lang=ru&quiz=0"],
    ["/demo/?quiz=1", "/demo/?quiz=1"],
    ["/demo/?s=AbCdEfGhIjKlMnOpQrStUv&quiz=1#n=Anna", "/demo/?s=AbCdEfGhIjKlMnOpQrStUv&quiz=1#n=Anna"],
  ])("%s → %s", (src, want) => {
    expect(demoUrl(src)).toBe(want);
    expect(cjs.demoUrl(src)).toBe(want);
  });
});
