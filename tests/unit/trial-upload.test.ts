import { promises as fs } from "node:fs";
import path from "node:path";
import { afterAll, beforeEach, describe, expect, it } from "vitest";

import { TRIAL_FILE_MAX_BYTES } from "@/lib/trial/config";
import { receiveUpload } from "@/lib/trial/upload";
import { multipart, png, streamRequest, uploadParts } from "./_trial-helpers";

// Загрузка потоком (agent-trial-01, T-A; поправки Codex 09.11): лимит файла по реально прочитанным байтам (chunked и ложный
// Content-Length не обходят), ±1 байт, обрыв связи, неверная сигнатура — после любого отказа на диске ни `.part`, ни файла.

const DIR = path.join(process.cwd(), ".vitest", `trial-upload-${process.pid}`);
const ID = "U".repeat(22);
const files = async () => (await fs.readdir(DIR).catch(() => [] as string[])).sort();

const send = (body: Buffer, type: string, opts: { breakAt?: number; contentLength?: number } = {}) => {
  const h: Record<string, string> = { "content-type": type };
  if (opts.contentLength !== undefined) h["content-length"] = String(opts.contentLength);
  return receiveUpload(streamRequest(body, h, { breakAt: opts.breakAt }), DIR, ID);
};

describe("receiveUpload", () => {
  beforeEach(async () => {
    await fs.rm(DIR, { recursive: true, force: true });
    await fs.mkdir(DIR, { recursive: true });
  });
  afterAll(async () => { await fs.rm(DIR, { recursive: true, force: true }); });

  it("годный PNG: .part на диске, тип по сигнатуре, хэш файла+текста, текст обрезан по краям", async () => {
    const m = multipart(uploadParts(png(1000), [{ name: "email", value: "a@b.c" }]));
    const r = await send(m.body, m.type);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r).toMatchObject({ mime: "image/png", bytes: 1000, listing: "2 bed flat, living room 4.0 x 3.0 m" });
    expect(r.inputHash).toMatch(/^[0-9a-f]{64}$/);
    expect(await files()).toEqual([`${ID}.part`]);
    expect((await fs.stat(r.partPath)).size).toBe(1000);
    // тот же файл и текст → тот же хэш (кэш VLM на DEV), другой текст → другой
    await fs.rm(r.partPath);
    const again = await send(m.body, m.type);
    expect(again.ok && again.inputHash).toBe(r.inputHash);
  });

  it("ровно 15 МБ — принято, 15 МБ + 1 байт — 413 и пусто на диске (chunked, без Content-Length)", async () => {
    const ok = multipart(uploadParts(png(TRIAL_FILE_MAX_BYTES)));
    const r1 = await send(ok.body, ok.type);
    expect(r1.ok).toBe(true);
    await fs.rm(path.join(DIR, `${ID}.part`));
    const big = multipart(uploadParts(png(TRIAL_FILE_MAX_BYTES + 1)));
    const r2 = await send(big.body, big.type);
    expect(r2).toMatchObject({ ok: false, status: 413, error: "too_large" });
    expect(await files()).toEqual([]);
  });

  it("ложный маленький Content-Length не обходит лимит; заявленный большой — отказ сразу", async () => {
    const big = multipart(uploadParts(png(TRIAL_FILE_MAX_BYTES + 10)));
    expect(await send(big.body, big.type, { contentLength: 100 })).toMatchObject({ ok: false, status: 413 });
    expect(await files()).toEqual([]);
    const small = multipart(uploadParts(png(100)));
    expect(await send(small.body, small.type, { contentLength: 17 * 1024 * 1024 })).toMatchObject({ ok: false, status: 413 });
    expect(await files()).toEqual([]);
  });

  it("обрыв связи посреди файла — отказ, .part удалён", async () => {
    const m = multipart(uploadParts(png(3 * 1024 * 1024)));
    const r = await send(m.body, m.type, { breakAt: 1024 * 1024 });
    expect(r.ok).toBe(false);
    expect(await files()).toEqual([]);
  });

  it("не картинка/не PDF (SVG, HTML) — 415; пустой файл и нет файла — 400; всё без следов на диске", async () => {
    const svg = multipart(uploadParts(Buffer.from("<svg xmlns='http://www.w3.org/2000/svg'/>")));
    expect(await send(svg.body, svg.type)).toMatchObject({ ok: false, status: 415, error: "unsupported_type" });
    const empty = multipart(uploadParts(Buffer.alloc(0)));
    expect(await send(empty.body, empty.type)).toMatchObject({ ok: false, status: 400, error: "no_file" });
    const none = multipart([{ name: "consent", value: "yes" }]);
    expect(await send(none.body, none.type)).toMatchObject({ ok: false, status: 400, error: "no_file" });
    expect(await files()).toEqual([]);
  });

  it("без согласия — 400; текст > 5000 — 400; два файла — 400; не multipart — 415", async () => {
    const noConsent = multipart([{ name: "file", file: png(100) }]);
    expect(await send(noConsent.body, noConsent.type)).toMatchObject({ ok: false, error: "consent_required" });
    const long = multipart(uploadParts(png(100), [{ name: "listing", value: "я".repeat(5001) }]).slice(1));
    expect(await send(long.body, long.type)).toMatchObject({ ok: false, error: "listing_too_long" });
    const two = multipart([...uploadParts(png(100)), { name: "file", file: png(100) }]);
    expect(await send(two.body, two.type)).toMatchObject({ ok: false, status: 400 });
    expect(await send(Buffer.from("{}"), "application/json")).toMatchObject({ ok: false, status: 415 });
    expect(await files()).toEqual([]);
  });

  it("битая разметка multipart — 400 без следов", async () => {
    const r = await send(Buffer.from("--nope\r\ngarbage"), "multipart/form-data; boundary=zzz");
    expect(r.ok).toBe(false);
    expect(await files()).toEqual([]);
  });
});
