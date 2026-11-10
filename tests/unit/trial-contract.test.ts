import { promises as fs } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";

import { floorplanResult, trialJobView, trialRebuildIn } from "@/contracts/trial";
import { POST as claimPost } from "@/app/api/trial/worker/claim/route";
import { GET as inputGet } from "@/app/api/trial/worker/[id]/input/route";
import { workerAuth } from "@/lib/trial/auth";
import { inputName, inputPath, openInput, sniffMime } from "@/lib/trial/storage";
import { metrikaSafeUrl, noMetrikaPath } from "@/lib/metrika";
import { sampleResult } from "./_trial-helpers";

// Проба для агентов (agent-trial-01, T-A) без базы: контракт результата, сигнатуры файлов, путь файла (traversal,
// симлинк), токен воркера fail-closed, ключ ссылки /try/<id> не уходит в Метрику.

const SCHEMA_FILE = path.join(process.cwd(), "tests/fixtures/trial-result.schema.json");

describe("floorplanResult (Zod)", () => {
  it("годный результат проходит", () => {
    expect(floorplanResult.safeParse(sampleResult()).success).toBe(true);
  });

  it("битый: не та версия/единицы, контур из 2 точек, bbox не проекция контура, лишний тип комнаты", () => {
    expect(floorplanResult.safeParse(sampleResult({ version: 2 })).success).toBe(false);
    expect(floorplanResult.safeParse(sampleResult({ units: "m" })).success).toBe(false);
    const bad = (room: Record<string, unknown>) => {
      const r = sampleResult() as { panels: { rooms: Record<string, unknown>[] }[] };
      r.panels[0]!.rooms[0] = { ...r.panels[0]!.rooms[0], ...room };
      return floorplanResult.safeParse(r).success;
    };
    expect(bad({ contour: [[0, 0], [1, 1]] })).toBe(false);
    expect(bad({ bbox: { x: 0, y: 0, w: 500, d: 300 } })).toBe(false);
    expect(bad({ kind: "garage" })).toBe(false);
    expect(bad({ contour: [[0, 0], [Number.NaN, 0], [1, 1]] })).toBe(false);
  });

  it("выгрузка JSON Schema для теста Python совпадает с контрактом (UPDATE_TRIAL_SCHEMA=1 — перезаписать)", async () => {
    const now = JSON.stringify(z.toJSONSchema(floorplanResult), null, 2) + "\n";
    if (process.env.UPDATE_TRIAL_SCHEMA === "1") await fs.writeFile(SCHEMA_FILE, now);
    expect(await fs.readFile(SCHEMA_FILE, "utf8")).toBe(now);
  });

  it("вид страницы — только разрешённые поля (strip лишнего)", () => {
    const v = trialJobView.parse({
      id: "x", status: "queued", stage: "queued", stages: [], createdAt: "t", finishedAt: null, elapsedSec: 0, queueAhead: 0,
      workerAlive: false, errorCode: null, resultVersion: 0, bundleVersion: 0, inputPath: "secret.png", leaseToken: "tok", listingText: "x",
      editKeyHash: "h".repeat(64), editKey: "K".repeat(22),
    });
    expect(Object.keys(v).sort()).toEqual(
      ["askSizes", "bundleVersion", "createdAt", "elapsedSec", "errorCode", "finishedAt", "id", "listing", "listingError", "queueAhead", "rebuild",
        "rebuildError", "resultVersion", "roomEdit", "roomEditError", "stage", "stages", "status", "workerAlive"]);
    expect(v).toMatchObject({ rebuild: null, rebuildError: null, roomEdit: null, roomEditError: null });
  });

  it("«Обустроить»: тело кнопки — ключ, повтор, версия, комнаты или all; лишнее и кривое — отказ", () => {
    const ok = { k: "K".repeat(22), request_id: "req-00000001", base_version: 3, rooms: ["living", "bedroom-1"] };
    expect(trialRebuildIn.safeParse(ok).success).toBe(true);
    expect(trialRebuildIn.safeParse({ ...ok, rooms: "all" }).success).toBe(true);
    for (const bad of [{ ...ok, k: "short" }, { ...ok, rooms: [] }, { ...ok, rooms: ["../x"] }, { ...ok, rooms: "some" },
      { ...ok, base_version: 0 }, { ...ok, request_id: "x" }]) {
      expect(trialRebuildIn.safeParse(bad).success, JSON.stringify(bad)).toBe(false);
    }
  });
});

describe("файлы пробы", () => {
  it("тип — по первым байтам, не по имени", () => {
    expect(sniffMime(Buffer.from([0xff, 0xd8, 0xff, 0xe0]))).toBe("image/jpeg");
    expect(sniffMime(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))).toBe("image/png");
    expect(sniffMime(Buffer.from("RIFF\0\0\0\0WEBPVP8 "))).toBe("image/webp");
    expect(sniffMime(Buffer.from("%PDF-1.7\n"))).toBe("application/pdf");
    expect(sniffMime(Buffer.from("\0\0\0\x1cftypavif\0\0\0\0"))).toBe("image/avif");
    expect(sniffMime(Buffer.from("\0\0\0\x1cftypavis\0\0\0\0"))).toBe("image/avif");
    expect(sniffMime(Buffer.from("\0\0\0\x1cftypheic\0\0\0\0"))).toBeNull();
    expect(sniffMime(Buffer.from("<svg xmlns="))).toBeNull();
    expect(sniffMime(Buffer.from("GIF89a"))).toBeNull();
    expect(sniffMime(Buffer.alloc(0))).toBeNull();
  });

  it("traversal через input_path не проходит", () => {
    const dir = "/data/trial";
    expect(inputPath(dir, inputName("A".repeat(22), "image/png"))).toBe(`/data/trial/${"A".repeat(22)}.png`);
    for (const bad of ["../etc/passwd", "/etc/passwd", `../${"A".repeat(22)}.png`, `${"A".repeat(22)}.png/..`, `${"A".repeat(21)}.png`,
      `${"A".repeat(22)}.sh`, `${"A".repeat(22)}.png\0`, "", null]) {
      expect(inputPath(dir, bad)).toBeNull();
    }
  });

  it("симлинк с годным именем не открывается (O_NOFOLLOW), обычный файл — да", async () => {
    const dir = path.join(process.cwd(), ".vitest", `trial-link-${process.pid}`);
    await fs.mkdir(dir, { recursive: true });
    const link = `${"L".repeat(22)}.png`, real = `${"R".repeat(22)}.png`;
    await fs.writeFile(path.join(dir, real), "x");
    await fs.rm(path.join(dir, link), { force: true });
    await fs.symlink("/etc/hostname", path.join(dir, link));
    expect(await openInput(dir, link)).toBeNull();
    const ok = await openInput(dir, real);
    expect(ok?.size).toBe(1);
    await ok?.handle.close();
    await fs.rm(dir, { recursive: true, force: true });
  });
});

describe("токен воркера — fail-closed", () => {
  const prev = process.env.TRIAL_WORKER_TOKEN;
  afterEach(() => {
    if (prev === undefined) delete process.env.TRIAL_WORKER_TOKEN;
    else process.env.TRIAL_WORKER_TOKEN = prev;
  });
  const req = (auth?: string, url = "http://app/api/trial/worker/claim") =>
    new Request(url, { method: "POST", headers: auth ? { authorization: auth } : {}, body: "{}" });

  it("пустой env → 503 даже с «пустым» Bearer; неверный → 401", async () => {
    expect(workerAuth(new Headers({ authorization: "Bearer " }), {})).toBe("unconfigured");
    expect(workerAuth(new Headers({ authorization: "Bearer x" }), { TRIAL_WORKER_TOKEN: "" })).toBe("unconfigured");
    expect(workerAuth(new Headers({ authorization: "Bearer nope" }), { TRIAL_WORKER_TOKEN: "tok" })).toBe("denied");
    expect(workerAuth(new Headers({ authorization: "tok" }), { TRIAL_WORKER_TOKEN: "tok" })).toBe("denied");
    expect(workerAuth(new Headers({ authorization: "Bearer tok" }), { TRIAL_WORKER_TOKEN: "tok" })).toBe("ok");
    delete process.env.TRIAL_WORKER_TOKEN;
    expect((await claimPost(req("Bearer anything"))).status).toBe(503);
    process.env.TRIAL_WORKER_TOKEN = "secret-token";
    expect((await claimPost(req())).status).toBe(401);
    expect((await claimPost(req("Bearer wrong"))).status).toBe(401);
    const inp = await inputGet(new Request("http://app/x", { headers: { authorization: "Bearer wrong" } }), { params: Promise.resolve({ id: "x" }) });
    expect(inp.status).toBe(401);
    expect(inp.headers.get("cache-control")).toBe("private, no-store");
  });
});

describe("ключ /try/<id> и Метрика", () => {
  it("на /try Метрики нет вовсе; /trying и прочие — как раньше", () => {
    for (const p of ["/try", "/try/", "/try/AbCdEfGhIjKlMnOpQrStUv", "/manager/x", "/partner"]) expect(noMetrikaPath(p)).toBe(true);
    for (const p of ["/", "/trying", "/flat", "/e/x", "/tryout/1"]) expect(noMetrikaPath(p)).toBe(false);
  });

  it("на случай реферера ключ в адресе маскируется", () => {
    expect(metrikaSafeUrl("https://remont-lab.online/try/AbCdEfGhIjKlMnOpQrStUv")).toBe("https://remont-lab.online/try/*");
    expect(metrikaSafeUrl("/try/AbCdEfGhIjKlMnOpQrStUv?x=1")).toBe("/try/*?x=1");
    expect(metrikaSafeUrl("/try")).toBe("/try");
  });
});
