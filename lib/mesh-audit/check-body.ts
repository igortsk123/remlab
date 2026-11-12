// Входы ручек /lab/mesh-check (T-20261112-118): нажатие и версия комментария. Схемы без импорта БД — их видят тесты.

import { z } from "zod";
import { NOTE_MAX } from "./note-saver";

export const REVIEWER_MAX = 40;
const Reviewer = z.string().trim().min(1).max(REVIEWER_MAX); // «кто проверяет» — выбирается один раз при входе

export const PressBody = z.object({
  itemId: z.number().int().positive(),
  generationKey: z.string().min(1),
  press: z.enum(["ok", "bad"]),
  expected: z.enum(["ok", "bad"]).nullable(),
  reviewer: Reviewer,
  idemKey: z.string().min(8).max(100),
});
export type PressInput = z.infer<typeof PressBody>;

export const NoteBody = z.object({
  itemId: z.number().int().positive(),
  generationKey: z.string().min(1),
  body: z.string().max(NOTE_MAX), // как набрано, без trim
  seq: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
  opId: z.string().min(8).max(100),
  editorId: z.string().min(8).max(100),
  reviewer: Reviewer,
});
export type NoteInput = z.infer<typeof NoteBody>;
