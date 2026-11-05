// Словари опроса-знакомства на /demo (план onb-03, ADR-0330 п.4). Менеджеру и застройщику уходят ТОЛЬКО эти значения —
// свободного текста и имени покупателя нет. Значения совпадают с `tools/scout/rules/quiz.json` и `index.html:STYLE_IDS`
// (сверяет `tests/unit/quiz-events.test.ts`).

import { z } from "zod";

/** Стили витрины демо (`index.html:STYLE_IDS`): ответы на фото, тройка итога, выбранный стиль. */
export const quizStyle = z.enum(["scandi", "modern", "minimal", "loft", "neoclassic", "japandi"]);
export type QuizStyle = z.infer<typeof quizStyle>;

/** «Кто будет жить» (`quiz.json` вопрос `household`). */
export const quizHousehold = z.enum(["single", "couple", "child", "pet", "guest"]);
export type QuizHousehold = z.infer<typeof quizHousehold>;

/** Возраст детей — словарь ADR-0330 п.3. */
export const quizChildAge = z.enum(["0-3", "3-7", "7-12", "teen"]);
export type QuizChildAge = z.infer<typeof quizChildAge>;

/** Цвета (`quiz.json` вопрос `colours`, семейства `palettes.families`). */
export const quizColour = z.enum(["light", "warm", "cool", "accent"]);
export type QuizColour = z.infer<typeof quizColour>;
