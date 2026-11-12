// Автоперевыпуск туров (T-20261112-92): «ожидаемая витрина» проверки «демо = туры» (`tools/ops/demo-release-hash.mjs`) считается тем
// же правилом, что закрепление (`lib/trial/tour-bundle.ts:pinRelease`), а пересборка агента закрепляет ТЕКУЩУЮ витрину.
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { pinJobRelease, pinRelease, releaseFiles, repinCurrentRelease } from "@/lib/trial/tour-bundle";
// @ts-expect-error — модуль .mjs без типов (скрипт DEV)
import { expectedRelease, fromDir, fromUrl, releaseFiles as mjsFiles } from "../../tools/ops/demo-release-hash.mjs";

const ID = "Q".repeat(22);

describe("ожидаемая витрина = pinRelease", () => {
  let root: string, demo: string, dir: string;
  const put = (rel: string, body: string) => writeFileSync(join(demo, rel), body);

  beforeAll(() => {
    root = mkdtempSync(join(tmpdir(), "relhash-"));
    demo = join(root, "demo");
    dir = join(root, "trial");
    mkdirSync(join(demo, "lib"), { recursive: true });
    put("index.html", "<html>v1</html>");
    put("lib/scene.json", JSON.stringify({ file: "scene.0a1b2c3d4e5f.js", basket: { file: "basket.1a1b2c3d4e5f.js" }, camfit: { file: "camfit.2a1b2c3d4e5f.js" } }));
    put("lib/scene.0a1b2c3d4e5f.js", "// scene");
    put("lib/basket.1a1b2c3d4e5f.js", "// basket");
    put("lib/camfit.2a1b2c3d4e5f.js", "// camfit");
    put("rt-meshes.json", "{}");
  });
  afterAll(() => rmSync(root, { recursive: true, force: true }));

  it("тот же список файлов и то же имя — по папке и по адресу", async () => {
    const man = JSON.parse(readFileSync(join(demo, "lib/scene.json"), "utf8"));
    expect(mjsFiles(man)).toEqual(releaseFiles(man));
    expect(mjsFiles({ file: "s.js" })).toEqual(releaseFiles({ file: "s.js" }));     // витрина до camfit/basket
    const pinned = await pinRelease(demo, dir);
    expect(await expectedRelease(fromDir(demo))).toBe(pinned);
    const fake = async (url: string) => {
      const rel = new URL(url).pathname.replace(/^\/demo\//, "");
      return new Response(readFileSync(join(demo, rel)));
    };
    expect(await expectedRelease(fromUrl("https://x.test/demo/", fake))).toBe(pinned);
  });

  it("правка любого файла витрины меняет имя", async () => {
    const before = await expectedRelease(fromDir(demo));
    put("lib/scene.0a1b2c3d4e5f.js", "// scene v2");
    expect(await expectedRelease(fromDir(demo))).not.toBe(before);
    expect(await expectedRelease(fromDir(demo))).toBe(await pinRelease(demo, dir));
  });

  it("пересборка агента закрепляет ТЕКУЩУЮ витрину, а не оставляет первую", async () => {
    put("index.html", "<html>v1</html>");
    const first = await pinRelease(demo, dir);
    await pinJobRelease(ID, first, dir);
    expect(await repinCurrentRelease(ID, dir, demo)).toBe("exists");               // витрина та же
    put("index.html", "<html>v2</html>");                                           // выложили новую
    expect(await repinCurrentRelease(ID, dir, demo)).toBe("pinned");
    expect(readFileSync(join(dir, ID, "release"), "utf8").trim()).toBe(await expectedRelease(fromDir(demo)));
  });
});
