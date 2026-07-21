// Repository лидов «найти дешевле» (К6), паттерн как estimates (ADR-0008): DATABASE_URL → Postgres,
// иначе in-memory (локально/тесты не хранят). email — ПДн: пишем только по согласию (см. lead-actions).

import { randomUUID } from "node:crypto";
import { db } from "@/lib/db";
import { leads } from "@/db/schema";

export type LeadChannel = "email" | "telegram" | "max";
export type Lead = { email?: string; channel: LeadChannel; url?: string; city?: string; kind?: string; sessionId?: string };

export interface LeadRepository {
  create(l: Lead): Promise<void>;
}

class MemoryLeadRepository implements LeadRepository {
  async create(): Promise<void> {
    /* локально не храним (только прод с DATABASE_URL) */
  }
}

class PgLeadRepository implements LeadRepository {
  async create(l: Lead): Promise<void> {
    await db().insert(leads).values({
      id: randomUUID(),
      email: l.email ?? null,
      channel: l.channel,
      url: l.url ?? null,
      city: l.city ?? null,
      kind: l.kind ?? null,
      sessionId: l.sessionId ?? null,
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
