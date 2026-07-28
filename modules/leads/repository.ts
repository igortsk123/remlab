// Repository лидов «найдём дешевле» (К6→П7), паттерн как estimates (ADR-0008): DATABASE_URL → Postgres,
// иначе in-memory (локально/тесты). email/город/чат — ПДн: пишем только по согласию (см. lead-actions).
// П7: номер заявки, привязка чата мессенджера, сообщения по заявке (reply-маппинг служебного TG-бота).

import { randomUUID } from "node:crypto";
import { desc, eq } from "drizzle-orm";
import { db } from "@/lib/db";
import { leadMessages, leads } from "@/db/schema";

export type LeadChannel = "email" | "tg" | "max";
export type LeadInput = { email?: string; channel: LeadChannel; url?: string; city?: string; kind?: string; sessionId?: string; ipRegion?: string };
export type Lead = LeadInput & { id: string; leadNo: number | null; messengerChatId?: string | null };
export type LeadMessage = { leadId: string; direction: "in" | "out"; text: string; adminTgMessageId?: number };

export interface LeadRepository {
  create(l: LeadInput): Promise<Lead>;
  get(id: string): Promise<Lead | null>;
  byChat(chatId: string): Promise<Lead | null>; // последняя заявка, привязанная к чату клиента
  byAdminMsg(adminTgMessageId: number): Promise<Lead | null>; // заявка по id сообщения в служебном боте
  setChat(id: string, chatId: string): Promise<void>;
  addMessage(m: LeadMessage): Promise<void>;
}

class MemoryLeadRepository implements LeadRepository {
  private readonly byId = new Map<string, Lead>();
  private readonly messages: (LeadMessage & { id: string })[] = [];
  private no = 0;
  async create(l: LeadInput): Promise<Lead> {
    const lead: Lead = { ...l, id: randomUUID(), leadNo: ++this.no, messengerChatId: null };
    this.byId.set(lead.id, lead);
    return lead;
  }
  async get(id: string) { return this.byId.get(id) ?? null; }
  async byChat(chatId: string) {
    return [...this.byId.values()].reverse().find((l) => l.messengerChatId === chatId) ?? null;
  }
  async byAdminMsg(msgId: number) {
    const m = [...this.messages].reverse().find((x) => x.adminTgMessageId === msgId);
    return m ? this.byId.get(m.leadId) ?? null : null;
  }
  async setChat(id: string, chatId: string) {
    const l = this.byId.get(id);
    if (l) l.messengerChatId = chatId;
  }
  async addMessage(m: LeadMessage) { this.messages.push({ ...m, id: randomUUID() }); }
}

class PgLeadRepository implements LeadRepository {
  async create(l: LeadInput): Promise<Lead> {
    const id = randomUUID();
    const rows = await db().insert(leads).values({
      id,
      email: l.email ?? null,
      channel: l.channel,
      url: l.url ?? null,
      city: l.city ?? null,
      kind: l.kind ?? null,
      sessionId: l.sessionId ?? null,
      ipRegion: l.ipRegion ?? null,
      status: "new",
    }).returning({ leadNo: leads.leadNo });
    return { ...l, id, leadNo: rows[0]?.leadNo ?? null };
  }
  async get(id: string): Promise<Lead | null> {
    const r = (await db().select().from(leads).where(eq(leads.id, id)).limit(1))[0];
    return r ? (r as unknown as Lead) : null;
  }
  async byChat(chatId: string): Promise<Lead | null> {
    const r = (await db().select().from(leads).where(eq(leads.messengerChatId, chatId)).orderBy(desc(leads.createdAt)).limit(1))[0];
    return r ? (r as unknown as Lead) : null;
  }
  async byAdminMsg(msgId: number): Promise<Lead | null> {
    const m = (await db().select().from(leadMessages).where(eq(leadMessages.adminTgMessageId, msgId)).orderBy(desc(leadMessages.createdAt)).limit(1))[0];
    return m ? this.get(m.leadId) : null;
  }
  async setChat(id: string, chatId: string): Promise<void> {
    await db().update(leads).set({ messengerChatId: chatId }).where(eq(leads.id, id));
  }
  async addMessage(m: LeadMessage): Promise<void> {
    await db().insert(leadMessages).values({
      id: randomUUID(),
      leadId: m.leadId,
      direction: m.direction,
      text: m.text,
      adminTgMessageId: m.adminTgMessageId ?? null,
    });
  }
}

const g = globalThis as unknown as { __remlabLeadRepo?: LeadRepository };
export function leadRepo(): LeadRepository {
  if (!g.__remlabLeadRepo) {
    g.__remlabLeadRepo = process.env.DATABASE_URL ? new PgLeadRepository() : new MemoryLeadRepository();
  }
  return g.__remlabLeadRepo;
}
