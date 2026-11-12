// Готовые снимки карточек комнат тура (T-20261112-29): запись на том, карта в странице, отдача файла.
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

import type { TrialJobView } from "@/contracts/trial";
import { trialCardsIn } from "@/contracts/trial-cards";
import { pinJobRelease, pinRelease, writeTourData } from "@/lib/trial/tour-bundle";
import { CARD_INDEX_MAX, pageCards, readCardIndex, writeCards } from "@/lib/trial/tour-cards";
import { injectTour } from "@/lib/trial/tour-page";
import { tourResponse, tourTarget } from "@/lib/trial/tour";

const ID = "AbCdEfGhIjKlMnOpQrStUv";
const LINK = "LiNkLiNkLiNkLiNkLiNkLi";
const view = (async () => ({ id: ID, status: "done", resultVersion: 3 }) as unknown as TrialJobView) as (id: string) => Promise<TrialJobView>;
const jpg = (n: number): Buffer => Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.alloc(200, n)]);
const KEY = "living|set3|s0";

describe("снимки карточек: адреса", () => {
  it("cards/<16 hex>.jpg — снимок; прочее под cards — отказ", () => {
    expect(tourTarget(["cards", "0123456789abcdef.jpg"])).toEqual({ kind: "card", file: "0123456789abcdef.jpg" });
    for (const p of [["cards", "index.json"], ["cards", "0123456789ABCDEF.jpg"], ["cards", "0123.jpg"], ["cards", "..", "release"],
      ["cards", "0123456789abcdef.png"], ["cards"]]) expect(tourTarget(p), p.join("/")).toBeNull();
  });
  it("вход воркера: ключ расстановки и base64, не больше 8 за раз", () => {
    const b64 = jpg(1).toString("base64");
    expect(trialCardsIn.safeParse({ id: ID, cards: [{ key: KEY, jpg: b64 }] }).success).toBe(true);
    expect(trialCardsIn.safeParse({ id: ID, cards: [{ key: "x|<y>|0", jpg: b64 }] }).success).toBe(false);
    expect(trialCardsIn.safeParse({ id: ID, cards: [{ key: KEY, jpg: "!!" + b64 }] }).success).toBe(false);
    expect(trialCardsIn.safeParse({ id: ID, cards: Array(9).fill({ key: KEY, jpg: b64 }) }).success).toBe(false);
  });
});

describe("снимки карточек: карта в странице", () => {
  const html = "<html><head></head><body></body></html>";
  const cardsOf = (out: string) => JSON.parse(out.match(/window\.__TOUR_CARDS=(.*);\n/)?.[1] ?? "null") as unknown;
  it("без снимков — пустая карта", () => expect(cardsOf(injectTour(html, ID, 1))).toEqual({}));
  it("только проверенные ключи и адреса; `<` не закрывает скрипт", () => {
    const out = injectTour(html, ID, 1, { [KEY]: "cards/0123456789abcdef.jpg", "a|b|</script>": "cards/0123456789abcdef.jpg",
      "x|y|z": "https://evil/x.jpg", "k|v|1": "cards/../x.jpg" });
    expect(cardsOf(out)).toEqual({ [KEY]: "cards/0123456789abcdef.jpg" });
    expect(out.match(/<\/script>/g)?.length).toBe(1);
  });
});

describe("снимки карточек: том и отдача", () => {
  let root: string, dir: string, demo: string;
  beforeAll(async () => {
    root = mkdtempSync(join(tmpdir(), "cards-"));
    dir = join(root, "trial");
    demo = join(root, "demo");
    mkdirSync(join(demo, "lib"), { recursive: true });
    writeFileSync(join(demo, "index.html"), "<html><head></head><body>v1</body></html>");
    writeFileSync(join(demo, "lib", "scene.json"), JSON.stringify({ file: "scene.abc123.js" }));
    writeFileSync(join(demo, "lib", "scene.abc123.js"), "// scene");
    writeFileSync(join(demo, "rt-meshes.json"), '{"meshes":{}}');
    const rel = await pinRelease(demo, dir);
    await pinJobRelease(ID, rel, dir);
    await writeTourData(ID, JSON.stringify({ trial: { id: ID }, variants: [] }), dir);
  });
  afterAll(() => rmSync(root, { recursive: true, force: true }));

  it("нет задания или папка — ссылка: отказ; не JPEG — отказ", async () => {
    expect(await writeCards(dir, "ZZZZZZZZZZZZZZZZZZZZZZ", [{ key: KEY, jpg: jpg(1) }])).toEqual({ ok: false, error: "not_found" });
    symlinkSync(join(dir, ID), join(dir, LINK));
    expect(await writeCards(dir, LINK, [{ key: KEY, jpg: jpg(1) }])).toEqual({ ok: false, error: "not_found" });
    expect(await writeCards(dir, ID, [{ key: KEY, jpg: Buffer.alloc(300, 1) }])).toEqual({ ok: false, error: "not_jpeg" });
    expect(await readCardIndex(dir, ID)).toEqual({});
  });

  it("запись: файл по содержимому, повтор не пишется, карта сливается", async () => {
    expect(await writeCards(dir, ID, [{ key: KEY, jpg: jpg(1) }, { key: "bedroom-1|scandi|s0", jpg: jpg(2) }]))
      .toEqual({ ok: true, written: 2, index: 2 });
    expect(await writeCards(dir, ID, [{ key: KEY, jpg: jpg(1) }])).toEqual({ ok: true, written: 0, index: 2 });
    const m = await readCardIndex(dir, ID);
    expect(Object.keys(m).sort()).toEqual(["bedroom-1|scandi|s0", KEY]);
    expect(m[KEY]).toMatch(/^[a-f0-9]{16}\.jpg$/);
    expect(readFileSync(join(dir, ID, "cards", m[KEY]!)).equals(jpg(1))).toBe(true);
    expect((await pageCards(dir, ID))[KEY]).toBe(`cards/${m[KEY]}`);
  });

  it("битая карта или чужие ключи в ней — пусто/отброшены", async () => {
    const f = join(dir, ID, "cards", "index.json");
    const keep = readFileSync(f);
    writeFileSync(f, "{oops");
    expect(await readCardIndex(dir, ID)).toEqual({});
    writeFileSync(f, JSON.stringify({ [KEY]: "../release", "bad key": "0123456789abcdef.jpg" }));
    expect(await readCardIndex(dir, ID)).toEqual({});
    writeFileSync(f, keep);
  });

  it("карта не растёт без предела: старые ключи вытесняются", async () => {
    const many = Array.from({ length: CARD_INDEX_MAX + 5 }, (_, i) => ({ key: `room|v${i}|s0`, jpg: jpg(3) }));
    for (let i = 0; i < many.length; i += 8) await writeCards(dir, ID, many.slice(i, i + 8));
    const m = await readCardIndex(dir, ID);
    expect(Object.keys(m).length).toBe(CARD_INDEX_MAX);
    expect(m[`room|v${CARD_INDEX_MAX + 4}|s0`]).toBeDefined();
    expect(m[KEY]).toBeUndefined();
  });

  it("страница несёт карту, снимок отдаётся JPEG навсегда, чужое имя — 404", async () => {
    await writeCards(dir, ID, [{ key: KEY, jpg: jpg(1) }]);
    const file = (await readCardIndex(dir, ID))[KEY]!;
    const page = await (await tourResponse(ID, [], { view, dir })).text();
    expect(page).toContain(`"${KEY}":"cards/${file}"`);
    const r = await tourResponse(ID, ["cards", file], { view, dir });
    expect(r.status).toBe(200);
    expect(r.headers.get("content-type")).toBe("image/jpeg");
    expect(r.headers.get("cache-control")).toContain("immutable");
    expect(Buffer.from(await r.arrayBuffer()).equals(jpg(1))).toBe(true);
    expect((await tourResponse(ID, ["cards", "ffffffffffffffff.jpg"], { view, dir })).status).toBe(404);
  });
});
