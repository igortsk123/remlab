// Типы и интерфейс хранилища отправок (план b2b-02). Две реализации: Postgres (прод) и память
// (тесты/локально) — как у лидов. Сервис (`service.ts`) пишет только через этот интерфейс.

import type { SendStatus } from "@/contracts/send";

export type Manager = {
  id: string;
  partnerId: string;
  displayName: string;
  publicPhone: string | null;
  publicTelegram: string | null;
  publicWhatsapp: string | null;
  connectPhone: string | null;
  tgUserId: number | null;
  tgChatId: number | null;
  pageKey: string;
  active: boolean;
};

export type Send = {
  id: string;
  partnerId: string;
  apartmentId: string;
  managerId: string;
  lang: string;
  market: string;
  status: SendStatus;
  createdVia: "bot" | "page" | "crm";
  originChatId: number | null;
  originMessageId: number | null;
  revoked: boolean;
  openedAt: Date | null;
  openSignalAt: Date | null;
  summaryDueAt: Date | null;
  statusAt: Date | null;
  createdAt: Date;
};

export type SendEventRow = { sendId: string; kind: string; payload: Record<string, unknown>; createdAt: Date };

export type OutboxRow = {
  id: number;
  sendId: string;
  managerId: string;
  kind: string;
  text: string;
  status: "pending" | "sent" | "failed" | "no_channel";
  attempts: number;
  nextAt: Date;
  lastError: string | null;
};

export type SendPatch = Partial<Pick<Send, "status" | "openSignalAt" | "summaryDueAt" | "statusAt" | "revoked">>;

export interface SendStore {
  managerByKey(key: string): Promise<Manager | null>;
  managerById(id: string): Promise<Manager | null>;
  managerByTgUser(tgUserId: number): Promise<Manager | null>;
  managersByConnectPhone(digits: string): Promise<Manager[]>;
  bindTelegram(managerId: string, tgUserId: number, tgChatId: number): Promise<void>;
  createSend(s: Send): Promise<void>;
  getSend(id: string): Promise<Send | null>;
  listSends(managerId: string, limit: number): Promise<Send[]>;
  /** Сменить статус, только если текущий входит в `from` (атомарно). true — сменили. */
  changeStatus(id: string, from: readonly SendStatus[], to: SendStatus, at: Date): Promise<boolean>;
  updateSend(id: string, patch: SendPatch): Promise<void>;
  /** Отметить первое открытие атомарно: true — это действительно первое. */
  claimFirstOpen(id: string, at: Date): Promise<boolean>;
  addEvent(e: SendEventRow): Promise<void>;
  events(sendId: string, limit: number): Promise<SendEventRow[]>;
  enqueue(row: Omit<OutboxRow, "id" | "status" | "attempts" | "lastError">): Promise<void>;
  /** Сколько сигналов менеджеру поставлено в очередь начиная с `since` (бюджет антишума). */
  queuedSince(managerId: string, since: Date): Promise<number>;
  /** Взять созревшие сигналы в работу: им ставится «аренда» `leaseMs` — второй запуск их не увидит. */
  claimOutbox(now: Date, limit: number, leaseMs: number): Promise<OutboxRow[]>;
  /** Сигналы по ссылкам — для страницы менеджера (что доставлено, что нет). */
  outboxFor(sendIds: string[]): Promise<OutboxRow[]>;
  markOutbox(id: number, patch: Partial<Pick<OutboxRow, "status" | "attempts" | "nextAt" | "lastError">> & { sentAt?: Date }): Promise<void>;
  /** Забрать созревшие сводки атомарно (срок обнуляется); `dueAt` — каким он был. */
  claimSummaries(now: Date, limit: number): Promise<{ send: Send; dueAt: Date }[]>;
  /** Отметить повторное «открыл», если прошлый сигнал старше `gapMs` (атомарно). */
  claimReopen(id: string, now: Date, gapMs: number): Promise<boolean>;
  /** «Первый за `gapMs`?» — атомарно: true и отметка, если прошлой отметки нет или она старше окна. */
  claimDedup(key: string, now: Date, gapMs: number): Promise<boolean>;
  /** Забыть апдейт Telegram, если его обработка упала, — чтобы повтор прошёл. */
  forgetUpdate(updateId: number): Promise<void>;
  /** Telegram повторяет вебхук при сбое: true — апдейт новый, false — уже обрабатывали. */
  firstSeenUpdate(updateId: number): Promise<boolean>;
}
