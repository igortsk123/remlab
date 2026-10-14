// Короткие ролики для справки «?» в 3D (план flat3d-sims-ux D5): ходьба, выбор предмета, перемещение. Снимает ТОЛЬКО
// сцену и ТОЛЬКО во время действия (кадры ~8 в секунду, без долгой загрузки), склеивает в анимированный WebP (Pillow
// из окружения конвейера), кладёт в `public/flat3d-help/`. Перезапуск после правок интерфейса:
//   BASE=http://127.0.0.1:3000 node tools/flat3d/help-clips.mjs      # ONLY=move — один ролик
import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import { chromium } from "@playwright/test";

const BASE = process.env.BASE ?? "http://127.0.0.1:3000";
const OUT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../public/flat3d-help");
const TMP = path.join(OUT, ".tmp");
const size = { width: 1100, height: 980 };          // окно ноутбука: сцена достаточно высокая

async function clip(name, act) {
  rmSync(TMP, { recursive: true, force: true });
  mkdirSync(TMP, { recursive: true });
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: size });
  await p.goto(`${BASE}/flat`);
  await p.getByRole("tab", { name: "Бродилка" }).click();
  await p.locator('[data-flat3d="hotspots"]').waitFor({ timeout: 150000 });
  await p.waitForTimeout(1500);
  const box = await p.locator("canvas").first().boundingBox();
  let n = 0, on = true;
  const shoot = (async () => {
    while (on) {
      await p.screenshot({ path: path.join(TMP, `${String(n++).padStart(4, "0")}.png`), clip: box });
      await p.waitForTimeout(90);
    }
  })();
  await act(p);
  on = false;
  await shoot;
  await b.close();
  const py = process.env.PY ?? path.join(os.homedir(), "venvs/scout/bin/python");
  execFileSync(py, ["-c", `import glob,sys
from PIL import Image
fs=sorted(glob.glob(sys.argv[1]+'/*.png'))
im=[Image.open(f).convert('RGB') for f in fs]
w=520; im=[x.resize((w, round(x.height*w/x.width))) for x in im]
im[0].save(sys.argv[2], save_all=True, append_images=im[1:], duration=120, loop=0, quality=60, method=4)`, TMP, path.join(OUT, `${name}.webp`)]);
  rmSync(TMP, { recursive: true, force: true });
  console.log(`ролик: ${name}.webp (${n} кадров)`);
}

const canvas = (p) => p.locator("canvas").first();

if (!process.env.ONLY || process.env.ONLY === "walk") await clip("walk", async (p) => {
  await p.keyboard.down("ArrowUp"); await p.waitForTimeout(1200); await p.keyboard.up("ArrowUp");
  const c = await canvas(p).boundingBox();
  await p.mouse.move(c.x + c.width / 2, c.y + c.height / 2);
  await p.mouse.down(); await p.mouse.move(c.x + c.width / 2 + 160, c.y + c.height / 2, { steps: 25 }); await p.mouse.up();
  await p.waitForTimeout(600);
});

if (!process.env.ONLY || process.env.ONLY === "pick") await clip("pick", async (p) => {
  await p.waitForTimeout(2500); await p.locator('[data-flat3d="hotspots"] button').first().click({ force: true });
  await p.waitForTimeout(900);
  await p.getByRole("button", { name: "Варианты" }).click({ force: true }).catch(() => {});
  await p.waitForTimeout(1200);
});

if (!process.env.ONLY || process.env.ONLY === "move") await clip("move", async (p) => {
  await p.waitForTimeout(2500); await p.locator('[data-flat3d="hotspots"] button').first().click({ force: true });
  await p.waitForTimeout(600);
  await p.getByRole("button", { name: "Двигать" }).click({ force: true });
  const c = await canvas(p).boundingBox();
  await p.mouse.move(c.x + c.width / 2, c.y + c.height * 0.7);
  await p.mouse.down(); await p.mouse.move(c.x + c.width / 2 + 90, c.y + c.height * 0.7, { steps: 25 }); await p.mouse.up();
  await p.getByRole("button", { name: "Повернуть вправо" }).click().catch(() => {});
  await p.waitForTimeout(900);
});
