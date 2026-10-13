import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { TOKEN_RE } from "@/lib/token";
import type { TgFetch } from "@/lib/telegram/api";
import { handleBotUpdate, NEW_LINK, NOTE_PROMPT } from "@/modules/sends/bot";
import { flushSignals } from "@/modules/sends/dispatch";
import { normalizePhone } from "@/modules/sends/phone";
import { createSend, publicCard, recordBuyerEvent, revokeSend, setStatusByManager } from "@/modules/sends/service";
import { MemorySendStore } from "@/modules/sends/store-memory";
import type { Manager } from "@/modules/sends/types";

// Ссылка от менеджера и сигналы ему (план b2b-02): процесс «создал → открыл → выбрал → нажал
// консультацию → менеджеру пришло» и то, что ломать нельзя (антишум, чужие статусы, данные покупателя).

const T0 = new Date("2026-10-14T09:00:00Z");
const at = (min: number) => new Date(T0.getTime() + min * 60_000);

function mgr(over: Partial<Manager> = {}): Manager {
  return {
    id: "m1", partnerId: "demo", displayName: "Анна", publicPhone: "+7 913 000-00-00", publicTelegram: "anna_sales",
    publicWhatsapp: "79130000000", connectPhone: "79130000000", tgUserId: 501, tgChatId: 501, pageKey: "k".repeat(22), active: true, ...over,
  };
}

function fakeTg() {
  const calls: { method: string; body: Record<string, unknown> }[] = [];
  let status = 200;
  const f: TgFetch = async (url, init) => {
    calls.push({ method: url.split("/").pop()!, body: JSON.parse(String(init.body)) });
    return new Response(JSON.stringify(status === 200 ? { ok: true, result: { message_id: calls.length } } : { ok: false, description: "x" }), { status });
  };
  return { f, calls, setStatus: (s: number) => { status = s; } };
}

let store: MemorySendStore;
beforeEach(() => {
  store = new MemorySendStore();
  store.managers.set("m1", mgr());
  store.managers.set("m2", mgr({ id: "m2", displayName: "Олег", tgUserId: 777, tgChatId: 777, connectPhone: "79990000000", pageKey: "z".repeat(22) }));
  process.env.MANAGER_TG_TOKEN = "bot-token";
});
afterEach(() => { delete process.env.MANAGER_TG_TOKEN; });

describe("отправка ссылки", () => {
  it("токен — 22 символа (128 бит), неизвестная квартира — отказ, а не умолчание", async () => {
    const s = await createSend(mgr(), "flat215", "page", null, T0, store);
    expect(s?.id).toMatch(TOKEN_RE);
    expect(await createSend(mgr(), "flat999", "page", null, T0, store)).toBeNull();
  });

  it("карточка отдаёт контакты менеджера, отозванная ссылка — как несуществующая", async () => {
    const s = (await createSend(mgr(), "flat215", "page", null, T0, store))!;
    expect((await publicCard(s.id, store))?.manager.name).toBe("Анна");
    await revokeSend(mgr(), s.id, store);
    expect(await publicCard(s.id, store)).toBeNull();
    expect(await recordBuyerEvent(s.id, { kind: "designer_open" }, T0, store)).toBe(false);
  });
});

describe("события покупателя и антишум", () => {
  it("«открыл»: первый раз — сигнал, повтор в те же сутки — нет, через сутки — «снова открыл»", async () => {
    const s = (await createSend(mgr(), "flat215", "page", null, T0, store))!;
    await recordBuyerEvent(s.id, { kind: "designer_open" }, at(1), store);
    await recordBuyerEvent(s.id, { kind: "designer_open" }, at(60), store);
    expect(store.outbox.map((o) => o.kind)).toEqual(["open"]);
    await recordBuyerEvent(s.id, { kind: "designer_open" }, at(25 * 60), store);
    expect(store.outbox.map((o) => o.kind)).toEqual(["open", "reopen"]);
    expect((await store.getSend(s.id))?.status).toBe("opened");
  });

  it("повторный клик «консультация» в течение 2 минут не дублирует сигнал", async () => {
    const s = (await createSend(mgr(), "flat215", "page", null, T0, store))!;
    const click = { kind: "manager_contact_click" as const, purpose: "consult" as const, channel: "whatsapp" as const, sum: 150000 };
    await recordBuyerEvent(s.id, click, at(1), store);
    await recordBuyerEvent(s.id, click, at(2), store);
    await recordBuyerEvent(s.id, { ...click, purpose: "mortgage" }, at(2), store);
    expect(store.outbox.map((o) => o.kind)).toEqual(["manager_contact_click", "manager_contact_click"]);
    expect(store.outbox[0]!.text).toContain("150 000 ₽");
  });

  it("выбор — одной сводкой через 30 минут, даже если событий больше нет", async () => {
    const s = (await createSend(mgr(), "flat215", "bot", { chatId: 501, messageId: 42 }, T0, store))!;
    const known = async () => ({ variants: new Set(["джапанди"]), items: new Set(["диван осло"]) });
    await recordBuyerEvent(s.id, { kind: "variant_view", variant: "Джапанди", sum: 200000 }, at(1), store, known);
    await recordBuyerEvent(s.id, { kind: "item_swap", variant: "Джапанди", sum: 210000, items: ["Диван Осло"] }, at(5), store, known);
    const tg = fakeTg();
    expect((await flushSignals(at(20), store, tg.f)).summaries).toBe(0);
    const r = await flushSignals(at(32), store, tg.f);
    expect(r).toMatchObject({ summaries: 1, sent: 1 });
    const sent = tg.calls.find((c) => c.method === "sendMessage")!;
    expect(String(sent.body.text)).toContain("Джапанди");
    expect(sent.body.reply_parameters).toEqual({ message_id: 42, allow_sending_without_reply: true }); // ответом на «Вася, после показа»
  });
});

describe("текст со страницы не доверяем", () => {
  const known = async () => ({ variants: new Set(["джапанди"]), items: new Set(["диван осло"]) });

  it("в сигнал попадают только вариант и товары из данных витрины", async () => {
    const s = (await createSend(mgr(), "flat215", "page", null, T0, store))!;
    await recordBuyerEvent(s.id, { kind: "manager_contact_click", purpose: "consult", variant: "Джапанди", items: ["Диван Осло", "Позвоните Ивану +7 999 111-22-33"] }, at(1), store, known);
    const text = store.outbox[0]!.text;
    expect(text).toContain("Джапанди");
    expect(text).toContain("Диван Осло");
    expect(text).not.toContain("+7 999");
    expect(JSON.stringify(store.eventRows)).not.toContain("+7 999");
  });

  it("нет данных витрины — текста нет вовсе, сумма остаётся", async () => {
    const s = (await createSend(mgr(), "flat215", "page", null, T0, store))!;
    await recordBuyerEvent(s.id, { kind: "manager_contact_click", purpose: "consult", variant: "Что угодно", sum: 1000 }, at(1), store, async () => null);
    expect(store.outbox[0]!.text).not.toContain("Что угодно");
    expect(store.outbox[0]!.text).toContain("1 000 ₽");
  });

  it("ушедший менеджер не показывается по старой ссылке", async () => {
    const s = (await createSend(mgr(), "flat215", "page", null, T0, store))!;
    store.managers.get("m1")!.active = false;
    expect(await publicCard(s.id, store)).toBeNull();
  });
});

describe("статусы", () => {
  it("система двигает только вперёд и не перетирает статус менеджера", async () => {
    const s = (await createSend(mgr(), "flat215", "page", null, T0, store))!;
    await recordBuyerEvent(s.id, { kind: "designer_open" }, at(1), store);
    expect(await setStatusByManager(mgr(), s.id, "meeting", at(2), store)).toBe(true);
    await recordBuyerEvent(s.id, { kind: "item_swap" }, at(3), store);
    expect((await store.getSend(s.id))?.status).toBe("meeting");
    expect(store.eventRows.find((e) => e.kind === "status")?.payload).toMatchObject({ from: "opened", to: "meeting", by: "m1" });
  });

  it("чужой менеджер статус не меняет", async () => {
    const s = (await createSend(mgr(), "flat215", "page", null, T0, store))!;
    expect(await setStatusByManager((await store.managerById("m2"))!, s.id, "deal", at(1), store)).toBe(false);
  });
});

describe("доставка сигналов", () => {
  it("нет бота — сигнал помечен «нет канала», а не потерян молча", async () => {
    delete process.env.MANAGER_TG_TOKEN;
    const s = (await createSend(mgr(), "flat215", "page", null, T0, store))!;
    await recordBuyerEvent(s.id, { kind: "designer_open" }, at(1), store);
    expect(await flushSignals(at(1), store, fakeTg().f)).toMatchObject({ noChannel: 1, sent: 0 });
    expect(store.outbox[0]!.lastError).toBe("no_token");
  });

  it("два одновременных запуска доставки не шлют один сигнал дважды", async () => {
    const s = (await createSend(mgr(), "flat215", "page", null, T0, store))!;
    await recordBuyerEvent(s.id, { kind: "designer_open" }, at(1), store);
    const tg = fakeTg();
    const [a, b] = await Promise.all([flushSignals(at(1), store, tg.f), flushSignals(at(1), store, tg.f)]);
    expect(a.sent + b.sent).toBe(1);
    expect(tg.calls.filter((c) => c.method === "sendMessage")).toHaveLength(1);
  });

  it("Telegram 500 — повтор через минуту; 403 (бот заблокирован) — без повтора", async () => {
    const s = (await createSend(mgr(), "flat215", "page", null, T0, store))!;
    await recordBuyerEvent(s.id, { kind: "designer_open" }, at(1), store);
    const tg = fakeTg();
    tg.setStatus(500);
    expect((await flushSignals(at(1), store, tg.f)).retried).toBe(1);
    expect((await flushSignals(at(1.5), store, tg.f)).retried).toBe(0); // ещё рано
    tg.setStatus(403);
    expect((await flushSignals(at(3), store, tg.f)).failed).toBe(1);
  });
});

describe("бот менеджеров", () => {
  const msg = (u: number, m: Record<string, unknown>) => ({ update_id: u, message: { message_id: u, from: { id: 900 }, chat: { id: 900, type: "private" }, ...m } });

  it("подключение только своим номером; затем «Новая ссылка» → заметка → ссылка ответом на заметку", async () => {
    store.managers.set("m3", mgr({ id: "m3", tgUserId: null, tgChatId: null, connectPhone: "79131112233", pageKey: "q".repeat(22) }));
    const tg = fakeTg();
    await handleBotUpdate(msg(1, { contact: { phone_number: "+7 913 111-22-33", user_id: 12345 } }), "t", store, tg.f, T0);
    expect((await store.managerById("m3"))?.tgUserId).toBeNull(); // чужой контакт
    await handleBotUpdate(msg(2, { contact: { phone_number: "8 913 111 22 33", user_id: 900 } }), "t", store, tg.f, T0);
    expect((await store.managerById("m3"))?.tgChatId).toBe(900);

    await handleBotUpdate(msg(3, { text: NEW_LINK }), "t", store, tg.f, T0);
    await handleBotUpdate(msg(4, { text: "Вася, после показа", reply_to_message: { message_id: 3, from: { is_bot: true }, text: `${NOTE_PROMPT} (например…)` } }), "t", store, tg.f, T0);
    const s = [...store.sends.values()].find((x) => x.managerId === "m3")!;
    expect(s).toMatchObject({ originChatId: 900, originMessageId: 4, createdVia: "bot" });
    expect(JSON.stringify([...store.sends.values()])).not.toContain("Вася"); // заметку не храним
    const last = tg.calls.at(-1)!;
    expect(String(last.body.text)).toContain(`/demo/?s=${s.id}`);
    expect(last.body.reply_parameters).toEqual({ message_id: 4 });
  });

  it("повтор апдейта Telegram не создаёт вторую ссылку; групповой чат игнорируется", async () => {
    const tg = fakeTg();
    const note = { update_id: 10, message: { message_id: 10, from: { id: 501 }, chat: { id: 501, type: "private" }, text: "Петя", reply_to_message: { message_id: 9, from: { is_bot: true }, text: NOTE_PROMPT } } };
    await handleBotUpdate(note, "t", store, tg.f, T0);
    await handleBotUpdate(note, "t", store, tg.f, T0);
    await handleBotUpdate({ ...note, update_id: 11, message: { ...note.message, chat: { id: -5, type: "group" } } }, "t", store, tg.f, T0);
    expect(store.sends.size).toBe(1);
  });

  it("кнопка статуса работает только у владельца ссылки", async () => {
    const s = (await createSend(mgr(), "flat215", "bot", null, T0, store))!;
    const tg = fakeTg();
    await handleBotUpdate({ update_id: 20, callback_query: { id: "c1", from: { id: 777 }, data: `st:${s.id}:deal` } }, "t", store, tg.f, T0);
    expect((await store.getSend(s.id))?.status).toBe("sent");
    await handleBotUpdate({ update_id: 21, callback_query: { id: "c2", from: { id: 501 }, data: `st:${s.id}:meeting` } }, "t", store, tg.f, T0);
    expect((await store.getSend(s.id))?.status).toBe("meeting");
  });
});

describe("номер телефона", () => {
  it.each([
    ["+7 (913) 111-22-33", "79131112233"],
    ["8 913 111 22 33", "79131112233"],
    ["9131112233", "79131112233"],
    ["07700 900123", "447700900123"],
    ["+44 7700 900123", "447700900123"],
    ["123", null],
  ])("%s → %s", (raw, want) => expect(normalizePhone(raw)).toBe(want));
});
