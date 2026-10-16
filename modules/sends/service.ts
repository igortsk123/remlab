// Отправки: создание, события покупателя, статусы менеджера (план b2b-02, ADR-0257).
//
// Антишум (разбор Codex 13.10): «открыл» — первый раз и снова не чаще раза в сутки; выбор
// (вариант/замены) — одной сводкой через 30 минут после первого изменения, по сохранённому
// сроку, даже если событий больше не будет; «консультация»/«другой вариант» — сразу, но повтор
// того же клика в течение 2 минут не дублируется; общий бюджет — 20 сигналов в час на менеджера.

import { autoAdvanceAllowed, autoStatusFor, AUTO_STATUSES, type BuyerEvent, type ManagerStatus, type SendCard } from "@/contracts/send";
import { randomToken } from "@/lib/token";
import { demoNames, keepKnown, loadDemoRaw, type DemoNames } from "@/lib/partners/demo-data";
import { findApartment as findApartmentHit } from "@/lib/partners/registry";
import { findApartment } from "@/modules/sends/apartments";
import { alternativeText, contactText, openText } from "@/modules/sends/signals";
import { MemorySendStore } from "@/modules/sends/store-memory";
import { PgSendStore } from "@/modules/sends/store-pg";
import type { Manager, Send, SendStore } from "@/modules/sends/types";

const MIN = 60_000;
export const REOPEN_SIGNAL_MS = 24 * 60 * MIN;
export const SUMMARY_DELAY_MS = 30 * MIN;
const CLICK_DEDUP_MS = 2 * MIN;
const MANAGER_BUDGET_PER_HOUR = 20;

const g = globalThis as unknown as { __remlabSendStore?: SendStore };
export function sendStore(): SendStore {
  g.__remlabSendStore ??= process.env.DATABASE_URL ? new PgSendStore() : new MemorySendStore();
  return g.__remlabSendStore;
}

export async function publicCard(id: string, store = sendStore()): Promise<SendCard | null> {
  const s = await store.getSend(id);
  if (!s || s.revoked) return null;
  const m = await store.managerById(s.managerId);
  if (!m?.active) return null; // ушедший менеджер не показывается по старым ссылкам
  return {
    id: s.id, apartmentId: s.apartmentId, lang: s.lang, market: s.market,
    manager: { name: m.displayName, phone: m.publicPhone, telegram: m.publicTelegram, whatsapp: m.publicWhatsapp },
  };
}

export async function createSend(
  m: Manager, apartmentId: string, via: Send["createdVia"],
  origin: { chatId: number; messageId: number } | null = null, now = new Date(), store = sendStore(),
): Promise<Send | null> {
  const apt = m.active ? findApartment(m.partnerId, apartmentId) : null;
  if (!apt) return null;
  const s: Send = {
    id: randomToken(), partnerId: m.partnerId, apartmentId: apt.id, managerId: m.id, lang: apt.lang, market: apt.market,
    status: "sent", createdVia: via, originChatId: origin?.chatId ?? null, originMessageId: origin?.messageId ?? null,
    revoked: false, openedAt: null, openSignalAt: null, summaryDueAt: null, statusAt: now, createdAt: now,
  };
  await store.createSend(s);
  return s;
}

/** В очередь — если у менеджера не исчерпан часовой бюджет сигналов (касается и сводок). */
export async function enqueueWithinBudget(store: SendStore, s: Send, kind: string, text: string, now: Date): Promise<boolean> {
  if ((await store.queuedSince(s.managerId, new Date(now.getTime() - 60 * MIN))) >= MANAGER_BUDGET_PER_HOUR) return false;
  await store.enqueue({ sendId: s.id, managerId: s.managerId, kind, text, nextAt: now });
  return true;
}
const signal = (store: SendStore, s: Send, kind: string, text: string, now: Date) => enqueueWithinBudget(store, s, kind, text, now).then(() => undefined);

/** Имена вариантов и товаров, которые знает витрина этой квартиры (текст со страницы не верим). */
export type KnownNames = (apartmentId: string) => Promise<DemoNames | null>;
const demoKnown: KnownNames = async (apartmentId) => {
  const src = findApartmentHit(apartmentId)?.apartment.sources.demoData;
  return src ? demoNames(await loadDemoRaw(src)) : null;
};

/** Событие со страницы покупателя. false — ссылки нет или она отозвана. */
export async function recordBuyerEvent(
  id: string, raw: BuyerEvent, now = new Date(), store = sendStore(), known: KnownNames = demoKnown,
): Promise<boolean> {
  const s = await store.getSend(id);
  if (!s || s.revoked) return false;
  // Текст со страницы — только если он есть в данных витрины (verify 13.10: иначе любой с ссылкой
  // писал бы менеджеру в Telegram что угодно, в том числе чужие имена и телефоны).
  const names = raw.variant || raw.items?.length ? await known(s.apartmentId) : null;
  const ev: BuyerEvent = { ...raw, ...keepKnown(names, raw.variant, raw.items) };
  if (!ev.variant) delete ev.variant;
  if (!ev.items?.length) delete ev.items;
  await store.addEvent({ sendId: id, kind: ev.kind, payload: ev, createdAt: now });

  const to = autoStatusFor(ev.kind);
  if (to && autoAdvanceAllowed(s.status, to)) await store.changeStatus(id, AUTO_STATUSES.slice(0, AUTO_STATUSES.indexOf(to)), to, now);

  if (ev.kind === "designer_open") {
    if (await store.claimFirstOpen(id, now)) return signal(store, s, "open", openText(s, false), now).then(() => true);
    if (await store.claimReopen(id, now, REOPEN_SIGNAL_MS)) await signal(store, s, "reopen", openText(s, true), now);
  } else if (ev.kind === "variant_view" || ev.kind === "item_swap" || ev.kind === "item_move" || ev.kind === "share" || ev.kind === "floor_pick") {
    if (!s.summaryDueAt) await store.updateSend(id, { summaryDueAt: new Date(now.getTime() + SUMMARY_DELAY_MS) });
  } else if (ev.kind === "manager_contact_click" || ev.kind === "alternative_request") {
    // Дедуп одинаковых кликов — атомарной отметкой (`dedup_marks`), а не чтением событий: два
    // одновременных клика (sendBeacon + повтор) оба прошли бы проверку «не было» (verify 13.10).
    const key = `send-click:${id}:${ev.kind}:${ev.purpose ?? ""}:${ev.reason ?? ""}`;
    if (await store.claimDedup(key, now, CLICK_DEDUP_MS)) await signal(store, s, ev.kind, ev.kind === "alternative_request" ? alternativeText(s, ev) : contactText(s, ev), now);
  }
  return true;
}

/** Статус ставит менеджер — только своей отправке. Любой ручной статус можно исправить, история хранится. */
export async function setStatusByManager(m: Manager, id: string, to: ManagerStatus, now = new Date(), store = sendStore()): Promise<boolean> {
  const s = await store.getSend(id);
  if (!s || s.managerId !== m.id || !m.active) return false;
  if (s.status === to) return true;
  const ok = await store.changeStatus(id, [s.status], to, now);
  if (ok) await store.addEvent({ sendId: id, kind: "status", payload: { from: s.status, to, by: m.id }, createdAt: now });
  return ok;
}

export async function revokeSend(m: Manager, id: string, store = sendStore()): Promise<boolean> {
  const s = await store.getSend(id);
  if (!s || s.managerId !== m.id) return false;
  await store.updateSend(id, { revoked: true });
  return true;
}
