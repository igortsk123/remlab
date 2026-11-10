import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { listingNote, newRequestId, sendErrorText, sizesHead } from "@/components/trial/SizesBox";
import { trialJobView, trialListingIn, type TrialJobView } from "@/contracts/trial";
import { TEXT } from "@/lib/trial/i18n";
import { asksSizes, sizeAsk } from "@/lib/trial/size-ask";

// «Размеры своими словами» без базы (agent-trial-08, Р2-текст; T-20261109-33): когда звать агента, форма тела ручки, строки состояния.

describe("когда звать агента написать размеры", () => {
  const b = (scale: string, states: string[] = ["ready"]) =>
    JSON.stringify({ trial: { scale }, apartment_rooms: states.map((s, i) => ({ id: `r${i}`, furniture_state: s })) });
  it("not_verified и area — да (комнаты при area не переводим в «ждут»); verified/listing — нет; есть ждущие проверки — да", () => {
    expect(asksSizes(b("not_verified"))).toBe(true);
    expect(asksSizes(b("area"))).toBe(true);
    expect(asksSizes(b("verified"))).toBe(false);
    expect(asksSizes(b("listing"))).toBe(false);
    expect(asksSizes(b("verified", ["ready", "awaiting_check"]))).toBe(true);
    expect(asksSizes("{oops")).toBe(false);
  });
  it("по файлу версии: нет публикации или файла — нет; ответ версии запоминается", async () => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), "sizes-"));
    const id = "S".repeat(22);
    expect(await sizeAsk(id, 0, dir)).toBe(false);
    expect(await sizeAsk(id, 1, dir)).toBe(false);
    await fs.mkdir(path.join(dir, id), { recursive: true });
    await fs.writeFile(path.join(dir, id, "bundle-2.json"), b("area"));
    expect(await sizeAsk(id, 2, dir)).toBe(true);
    await fs.writeFile(path.join(dir, id, "bundle-2.json"), b("verified")); // версия неизменна — файл не перечитываем
    expect(await sizeAsk(id, 2, dir)).toBe(true);
    await fs.rm(dir, { recursive: true, force: true });
  });
});

describe("тело ручки и вид задания", () => {
  const ok = { k: "K".repeat(22), request_id: "req-00000001", text: " гостиная 4,2 на 3,8 " };
  it("текст обрезается по краям; пусто, 2001 знак, лишние байты — отказ", () => {
    expect(trialListingIn.parse(ok).text).toBe("гостиная 4,2 на 3,8");
    expect(trialListingIn.safeParse({ ...ok, text: "  " }).success).toBe(false);
    expect(trialListingIn.safeParse({ ...ok, text: "а".repeat(2000) }).success).toBe(true);
    expect(trialListingIn.safeParse({ ...ok, text: "а".repeat(2001) }).success).toBe(false);
    // байты: 2000 знаков UTF-16 дают не больше 6000 байт UTF-8 — потолок байтов совпадает с худшим случаем, не режет допустимую длину
    expect(trialListingIn.safeParse({ ...ok, text: "😀".repeat(1000) }).success).toBe(true); // 2000 единиц, 4000 байт
    expect(trialListingIn.safeParse({ ...ok, text: "€".repeat(2000) }).success).toBe(true); // 6000 байт — ровно потолок
    expect(trialListingIn.safeParse({ ...ok, text: "😀".repeat(1001) }).success).toBe(false); // 2002 единицы — длинно
    expect(trialListingIn.safeParse({ ...ok, k: "bad" }).success).toBe(false);
  });
  it("старый ответ сервера без новых полей — значения по умолчанию", () => {
    const v = trialJobView.parse({ id: "x", status: "done", stage: "done", stages: [], createdAt: "t", finishedAt: null, elapsedSec: 1,
      queueAhead: null, workerAlive: true, errorCode: null, resultVersion: 1, bundleVersion: 1 });
    expect(v).toMatchObject({ askSizes: false, listing: null, listingError: null });
  });
});

describe("строки окошка", () => {
  const t = TEXT.ru.sizes;
  it("состояние текста по опросу; только что отправили — «приняли»", () => {
    const j = (listing: TrialJobView["listing"], listingError: TrialJobView["listingError"] = null, askSizes = true) =>
      ({ listing, listingError, askSizes });
    expect(listingNote(j(null), false, t)).toBeNull();
    expect(listingNote(j(null), true, t)?.text).toBe(t.accepted);
    expect(listingNote(j("applying"), false, t)?.text).toBe(t.applying);
    expect(listingNote(j("failed", "source_gone"), false, t)).toEqual({ text: t.sourceGone, bad: true });
    expect(listingNote(j("failed", "no_match"), false, t)).toEqual({ text: t.noMatch, bad: true });
    expect(listingNote(j("failed", "timeout"), false, t)).toEqual({ text: t.failed, bad: true });
  });
  it("применили: размеры больше не нужны — «готово», часть комнат без размеров — честно «у части нет»", () => {
    expect(listingNote({ listing: "done", listingError: null, askSizes: false }, false, t)).toEqual({ text: t.done, bad: false });
    expect(listingNote({ listing: "done", listingError: null, askSizes: true }, false, t)).toEqual({ text: t.partial, bad: false });
  });
  it("заголовок: размеры применены и не нужны — «Размеры применили / можно уточнить» (и пока уточнение идёт или не легло); иначе просьба", () => {
    const applied = { title: "Размеры применили", text: "Можно уточнить — напишите ещё" };
    expect(sizesHead({ listing: "done", askSizes: false }, t)).toEqual(applied);
    expect(sizesHead({ listing: "done", askSizes: false }, TEXT.en.sizes))
      .toEqual({ title: "Sizes applied", text: "You can refine — write more" });
    for (const listing of ["applying", "accepted", "failed"] as const)
      expect(sizesHead({ listing, askSizes: false }, t), listing).toEqual(applied); // уточнение после успеха: размеры на месте
    for (const listing of ["done", "applying", "failed", null] as const)
      expect(sizesHead({ listing, askSizes: true }, t), String(listing)).toEqual({ title: t.title, text: t.text });
  });
  it("коды отказа — понятный текст; id запроса подходит ручке", () => {
    expect(sendErrorText("source_gone", t)).toBe(t.sourceGone);
    expect(sendErrorText("rebuild_limit", t)).toBe(t.limit);
    expect(sendErrorText("что-то", t)).toBe(t.error);
    expect(newRequestId()).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(TEXT.en.sizes.title).toBe("We couldn't find the room sizes");
  });
});
