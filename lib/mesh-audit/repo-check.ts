// Чтение для страницы /lab/mesh-check (T-20261112-118): счётчики разделов и карточки раздела страницами по 20.
// Раздел — из роли (`sections.ts`), в БД только role; «Без типа» = роль пустая или не из таблицы разделов.

import { and, asc, count, eq, inArray, isNull, notInArray, or, type SQL } from "drizzle-orm";
import { db } from "@/lib/db";
import { meshAuditItems } from "@/db/schema";
import { isChecked } from "./marks";
import { PAGE_SIZE } from "./rules";
import { countSections, KNOWN_ROLES, rolesOf, type SectionCount } from "./sections";
import type { AuditItem } from "./repo-items";

export type CheckFilter = "all" | "todo" | "bad";

export async function sectionCounts(): Promise<SectionCount[]> {
  const rows = await db().select({ role: meshAuditItems.role, mark: meshAuditItems.mark }).from(meshAuditItems);
  return countSections(rows.map((r) => ({ role: r.role, checked: isChecked(r) })));
}

function where(section: string, filter: CheckFilter): SQL | undefined {
  const roles = rolesOf(section);
  const bySection = roles ? inArray(meshAuditItems.role, [...roles]) : or(isNull(meshAuditItems.role), notInArray(meshAuditItems.role, [...KNOWN_ROLES]));
  if (filter === "todo") return and(bySection, isNull(meshAuditItems.mark));
  if (filter === "bad") return and(bySection, eq(meshAuditItems.mark, "bad"));
  return bySection;
}

export async function listSection(section: string, filter: CheckFilter, page: number): Promise<{ items: AuditItem[]; total: number }> {
  const d = db();
  const w = where(section, filter);
  const total = (await d.select({ n: count() }).from(meshAuditItems).where(w))[0]?.n ?? 0;
  const items = await d
    .select()
    .from(meshAuditItems)
    .where(w)
    .orderBy(asc(meshAuditItems.id))
    .limit(PAGE_SIZE)
    .offset((page - 1) * PAGE_SIZE);
  return { items, total };
}
