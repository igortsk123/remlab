// T-118: снимки макета (без 3D): 375x667 и 1280x800, разделы диваны/кашпо, увеличение на 375 и 1280.
// Запуск: node .t118-shots.mjs <папка>
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const SRC = "file:///home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/.t118-mockup/index.html";
const OUT = process.argv[2];
mkdirSync(OUT, { recursive: true });
const SHOTS = [
  ["375-divan", 375, 667, "", true],
  ["375-divan-top", 375, 667, "", false],
  ["375-kashpo", 375, 667, "?tab=kashpo", true],
  ["375-zoom-photo", 375, 667, "?zoom=photo:1", false],
  ["375-zoom-model", 375, 667, "?zoom=model:0", false],
  ["1280-divan", 1280, 800, "", true],
  ["1280-kashpo", 1280, 800, "?tab=kashpo", false],
  ["1280-zoom", 1280, 800, "?zoom=model:0", false],
];
const b = await chromium.launch();
for (const [name, w, h, qs, full] of SHOTS) {
  const pg = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: w < 500 ? 2 : 1 });
  await pg.goto(SRC + qs, { waitUntil: "networkidle", timeout: 60000 });
  const okImgs = await pg
    .waitForFunction(() => [...document.images].filter((i) => i.offsetParent).every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 30000 })
    .then(() => true, () => false);
  const over = await pg.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  await pg.screenshot({ path: join(OUT, `${name}.png`), fullPage: full });
  console.log("SHOT", name, "overflow_x", over, "imgs_ok", okImgs);
  await pg.close();
}
await b.close();
