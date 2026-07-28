"use server";

import { randomUUID } from "node:crypto";
import { getSessionId } from "@/lib/session";
import { estimateRepo } from "@/modules/estimate/repository";
import { estimate as estimateSchema } from "@/contracts/estimate";
import { calcProject as calcProjectSchema } from "@/contracts/calc";
import { calcToItems } from "@/lib/calc/to-estimate";
import { CALC_META } from "@/lib/estimate/companions";
import { track } from "@/lib/analytics";

// Сохранить результат калькулятора v2 в смету (M1). Клиент передаёт проект (JSON, валидируем Zod).
// Возвращаем id (не redirect): клиент сам чистит черновик localStorage и переходит на /e/<id>.
export async function saveCalcEstimate(raw: unknown): Promise<{ ok: true; id: string } | { ok: false }> {
  const parsed = calcProjectSchema.safeParse(raw);
  if (!parsed.success) return { ok: false };
  const project = parsed.data;
  const items = calcToItems(project, () => randomUUID());
  if (items.length === 0) return { ok: false };

  const sessionId = await getSessionId();
  const now = new Date().toISOString();
  const est = estimateSchema.parse({
    id: randomUUID(),
    sessionId,
    title: `Смета: ${CALC_META[project.kind].title.toLowerCase()}`,
    source: "calc",
    items,
    meta: { kind: project.kind, rooms: project.rooms.length },
    createdAt: now,
    updatedAt: now,
  });
  await estimateRepo().create(est);
  await track("estimate_created", sessionId, { source: "calc_v2", kind: project.kind });
  return { ok: true, id: est.id };
}
