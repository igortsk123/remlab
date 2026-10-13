// Заявки «отправить подборку себе» с демо (план b2b-01, ADR-0248). Контакт — ПДн: живёт только
// здесь, до `expires_at` (90 дней), и наружу не отдаётся. Паттерн как у лидов: DATABASE_URL →
// Postgres, иначе память процесса (локально/тесты).

import { randomUUID } from "node:crypto";
import { lt } from "drizzle-orm";
import { db } from "@/lib/db";
import { POLICY_VERSION } from "@/lib/legal/policy";
import { shareRequests } from "@/db/schema";

export const SHARE_RETENTION_DAYS = 90;

export type ShareRequestInput = {
  shareId: string;
  shareUrl: string;
  channel: string;
  contact: string;
  shotCount: number;
  ip?: string;
};
export type ShareRequest = ShareRequestInput & { id: string; createdAt: Date; expiresAt: Date };

export interface ShareRequestRepository {
  create(r: ShareRequestInput, now?: Date): Promise<ShareRequest>;
  /** Удалить заявки с истёкшим сроком; возвращает, сколько удалено. */
  purgeExpired(now?: Date): Promise<number>;
}

const expiry = (now: Date) => new Date(now.getTime() + SHARE_RETENTION_DAYS * 86_400_000);

export class MemoryShareRequestRepository implements ShareRequestRepository {
  readonly rows: ShareRequest[] = [];
  async create(r: ShareRequestInput, now = new Date()): Promise<ShareRequest> {
    const row = { ...r, id: randomUUID(), createdAt: now, expiresAt: expiry(now) };
    this.rows.push(row);
    return row;
  }
  async purgeExpired(now = new Date()): Promise<number> {
    const before = this.rows.length;
    const keep = this.rows.filter((r) => r.expiresAt > now);
    this.rows.splice(0, this.rows.length, ...keep);
    return before - keep.length;
  }
}

class PgShareRequestRepository implements ShareRequestRepository {
  async create(r: ShareRequestInput, now = new Date()): Promise<ShareRequest> {
    const row = { ...r, id: randomUUID(), createdAt: now, expiresAt: expiry(now) };
    // нажатие «Отправить» под ссылкой на политику = согласие; пишем версию текста, действовавшую в этот момент
    await db().insert(shareRequests).values({ ...row, ip: r.ip ?? null, consentVersion: POLICY_VERSION });
    return row;
  }
  async purgeExpired(now = new Date()): Promise<number> {
    const gone = await db().delete(shareRequests).where(lt(shareRequests.expiresAt, now)).returning({ id: shareRequests.id });
    return gone.length;
  }
}

const g = globalThis as unknown as { __remlabShareRepo?: ShareRequestRepository };

export function shareRequestRepo(): ShareRequestRepository {
  if (!g.__remlabShareRepo) {
    g.__remlabShareRepo = process.env.DATABASE_URL ? new PgShareRequestRepository() : new MemoryShareRequestRepository();
  }
  return g.__remlabShareRepo;
}
