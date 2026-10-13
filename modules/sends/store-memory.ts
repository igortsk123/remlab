// Хранилище отправок в памяти процесса — для тестов и локального запуска без базы.

import type { SendStatus } from "@/contracts/send";
import type { Manager, OutboxRow, Send, SendEventRow, SendPatch, SendStore } from "@/modules/sends/types";

export class MemorySendStore implements SendStore {
  readonly managers = new Map<string, Manager>();
  readonly sends = new Map<string, Send>();
  readonly eventRows: SendEventRow[] = [];
  readonly outbox: (OutboxRow & { createdAt: Date; sentAt?: Date })[] = [];
  private readonly updates = new Set<number>();

  async managerByKey(key: string) {
    return [...this.managers.values()].find((m) => m.pageKey === key && m.active) ?? null;
  }
  async managerById(id: string) { return this.managers.get(id) ?? null; }
  async managerByTgUser(u: number) {
    return [...this.managers.values()].find((m) => m.tgUserId === u && m.active) ?? null;
  }
  async managersByConnectPhone(digits: string) {
    return [...this.managers.values()].filter((m) => m.active && m.connectPhone === digits);
  }
  async bindTelegram(id: string, tgUserId: number, tgChatId: number) {
    const m = this.managers.get(id);
    if (m) Object.assign(m, { tgUserId, tgChatId });
  }
  async createSend(s: Send) { this.sends.set(s.id, { ...s }); }
  async getSend(id: string) { const s = this.sends.get(id); return s ? { ...s } : null; }
  async listSends(managerId: string, limit: number) {
    return [...this.sends.values()].filter((s) => s.managerId === managerId)
      .sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime()).slice(0, limit);
  }
  async changeStatus(id: string, from: readonly SendStatus[], to: SendStatus, at: Date) {
    const s = this.sends.get(id);
    if (!s || !from.includes(s.status)) return false;
    Object.assign(s, { status: to, statusAt: at });
    return true;
  }
  async updateSend(id: string, patch: SendPatch) {
    const s = this.sends.get(id);
    if (s) Object.assign(s, patch);
  }
  async claimFirstOpen(id: string, at: Date) {
    const s = this.sends.get(id);
    if (!s || s.openedAt) return false;
    s.openedAt = at;
    s.openSignalAt = at;
    return true;
  }
  async addEvent(e: SendEventRow) { this.eventRows.push(e); }
  async events(sendId: string, limit: number) {
    return this.eventRows.filter((e) => e.sendId === sendId).slice(-limit).reverse();
  }
  async enqueue(row: Omit<OutboxRow, "id" | "status" | "attempts" | "lastError">) {
    this.outbox.push({ ...row, id: this.outbox.length + 1, status: "pending", attempts: 0, lastError: null, createdAt: row.nextAt });
  }
  async queuedSince(managerId: string, since: Date) {
    return this.outbox.filter((o) => o.managerId === managerId && o.createdAt >= since).length;
  }
  async dueOutbox(now: Date, limit: number) {
    return this.outbox.filter((o) => o.status === "pending" && o.nextAt <= now).slice(0, limit).map((o) => ({ ...o }));
  }
  async outboxFor(ids: string[]) {
    return this.outbox.filter((o) => ids.includes(o.sendId)).map((o) => ({ ...o }));
  }
  async markOutbox(id: number, patch: Partial<OutboxRow> & { sentAt?: Date }) {
    const o = this.outbox.find((x) => x.id === id);
    if (o) Object.assign(o, patch);
  }
  async dueSummaries(now: Date, limit: number) {
    return [...this.sends.values()].filter((s) => s.summaryDueAt && s.summaryDueAt <= now).slice(0, limit).map((s) => ({ ...s }));
  }
  async firstSeenUpdate(updateId: number) {
    if (this.updates.has(updateId)) return false;
    this.updates.add(updateId);
    return true;
  }
}
