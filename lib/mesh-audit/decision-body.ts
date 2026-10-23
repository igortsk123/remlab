// Вход POST /api/lab/mesh-audit/decisions: клик владельца «переделать» / «нужна замена» с необязательным комментарием
// (план mesh-audit-comments, владелец 23.10: «фото не дорезалось», «ножки пропали»). Схема без импорта БД — её видят тесты.

import { z } from "zod";

export const COMMENT_MAX = 500;

export const DecisionBody = z.object({
  itemId: z.number().int().positive(),
  generationKey: z.string().min(1),
  verdict: z.enum(["redo", "replace_needed"]),
  idemKey: z.string().min(1).max(300),
  comment: z.string().trim().max(COMMENT_MAX).optional(),
});
export type DecisionInput = z.infer<typeof DecisionBody>;

// Пустой комментарий не хранится: «отправил без слов» = null, разбор не считает пустые строки.
export function commentOrNull(comment: string | undefined): string | null {
  return comment ? comment : null;
}
