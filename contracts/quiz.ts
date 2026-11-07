// Словари опроса-знакомства на /demo (план onb-03, ADR-0330 п.4). Менеджеру и застройщику уходят ТОЛЬКО эти значения —
// свободного текста и имени покупателя нет. Значения совпадают с `tools/scout/rules/quiz.json` и `index.html:STYLE_IDS`
// (сверяет `tests/unit/quiz-events.test.ts`).

import { z } from "zod";

/** Стили витрины демо (`index.html:STYLE_IDS`): ответы на фото, тройка итога, выбранный стиль. */
export const quizStyle = z.enum(["scandi", "modern", "minimal", "loft", "neoclassic", "japandi"]);
export type QuizStyle = z.infer<typeof quizStyle>;

/**
 * Комната квартиры в событиях выбора (план home-mix-01): только вид комнаты из реестра и номер — без свободного текста,
 * чтобы со страницы нельзя было прислать менеджеру имя или телефон.
 */
export const quizRoom = z.string().regex(/^(living|hall|kitchen|bedroom|nursery|kids|bathroom)(-[1-9])?$/);
const ROOM_RU: Record<string, string> = {
  living: "гостиная", hall: "прихожая", kitchen: "кухня", bedroom: "спальня", nursery: "детская", kids: "детская", bathroom: "санузел",
};
/** «bedroom-2» → «спальня 2». */
export function quizRoomRu(id: string): string {
  const [kind = "", n] = id.split("-");
  return `${ROOM_RU[kind] ?? kind}${n ? ` ${n}` : ""}`;
}

/** «Кто будет жить» (`quiz.json` вопрос `household`). */
export const quizHousehold = z.enum(["single", "couple", "child", "pet", "guest"]);
export type QuizHousehold = z.infer<typeof quizHousehold>;

/** Возраст детей — словарь ADR-0330 п.3. */
export const quizChildAge = z.enum(["0-3", "3-7", "7-12", "teen"]);
export type QuizChildAge = z.infer<typeof quizChildAge>;

/** Сколько детей — при «С детьми» (`quiz.json` household → child → kids; владелец 06.11, T-20261106-94), один ответ. */
export const quizKids = z.enum(["1", "2", "3plus"]);
export type QuizKids = z.infer<typeof quizKids>;

/** Цвета (`quiz.json` вопрос `colours`, семейства `palettes.families`). */
export const quizColour = z.enum(["light", "warm", "cool", "accent"]);
export type QuizColour = z.infer<typeof quizColour>;

// Слова опроса по-русски — один источник для сигнала менеджеру (`modules/sends/signals.ts:quizText`) и отчёта застройщику
// (`components/partner/QuizBlock.tsx`): названия стилей — как на вкладках демо (`index.html:STYLE_IDS`), цвета — как в вопросе
// (`tools/scout/rules/quiz.json`), состав — в форме «живут: …»; совпадение словарей сверяет `tests/unit/quiz-events.test.ts`.
export const QUIZ_STYLE_RU: Record<QuizStyle, string> = {
  scandi: "Сканди", modern: "Современный", minimal: "Минимализм", loft: "Лофт", neoclassic: "Неоклассика", japandi: "Джапанди",
};
export const QUIZ_HOUSEHOLD_RU: Record<QuizHousehold, string> = {
  single: "один", couple: "вдвоём", child: "с детьми", pet: "кошка или собака", guest: "часто родители или гости",
};
export const QUIZ_CHILD_RU: Record<QuizChildAge, string> = { "0-3": "до 3 лет", "3-7": "3–7 лет", "7-12": "7–12 лет", teen: "подросток" };
export const QUIZ_KIDS_RU: Record<QuizKids, string> = { "1": "один ребёнок", "2": "двое детей", "3plus": "трое и больше" };
export const QUIZ_COLOUR_RU: Record<QuizColour, string> = {
  light: "светлые нейтральные", warm: "тёплые природные", cool: "графит и холодные", accent: "с яркими акцентами",
};
