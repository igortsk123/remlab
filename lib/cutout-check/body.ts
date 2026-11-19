// Входы ручек /api/lab/cutout-check (T-20261119-104). Схемы без импорта БД — их видят тесты. Нажатие и версия комментария — те же схемы,
// что у /lab/mesh-check (`lib/mesh-audit/check-body.ts`): имя «кто проверяет», idem_key / op_id, версия текста растёт в браузере.

import { z } from "zod";

export { PressBody, NoteBody } from "@/lib/mesh-audit/check-body";
import { NoteBody } from "@/lib/mesh-audit/check-body";

// «Просмотрено»: тот же человек и вкладка, что у версии текста; op_id — повтор запроса (маяк, сеть) не даёт второй строки журнала.
export const ViewBody = NoteBody.pick({ itemId: true, generationKey: true, opId: true, reviewer: true });

export const ItemIn = z.object({
  sku: z.string().min(1),
  generationKey: z.string().min(1),
  position: z.number().int().nonnegative(),
  role: z.string().nullable().optional(),
  name: z.string().nullable().optional(),
  nameEn: z.string().nullable().optional(),
  shop: z.string().nullable().optional(),
  shopUrl: z.string().nullable().optional(),
  photoUrl: z.string().nullable().optional(),
  cutUrl: z.string().nullable().optional(),
  info: z.record(z.string(), z.unknown()).nullable().optional(),
});
export type ItemInput = z.infer<typeof ItemIn>;

// DEV кладёт карточки целого прогона: метка прогона и до 500 карточек за запрос.
export const ItemsBody = z.object({
  run: z.string().min(1).max(80),
  items: z.array(ItemIn).min(1).max(500),
});
