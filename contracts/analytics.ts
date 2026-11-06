// Счётчики страниц БЕЗ ссылки менеджера (план b2b-03, ADR-0265). Персональная воронка живёт в
// `send_events` (`contracts/send.ts`), сюда — только заходы «напрямую»: день × квартира × действие × язык.
// Пользовательских идентификаторов в таблице нет; числа не уникальные и подделываемые (публичная ручка) —
// в отчёте подписаны как «действия, не люди» и с воронкой не складываются.

import { z } from "zod";

import { quizChildAge, quizColour, quizHousehold, quizKids, quizStyle } from "@/contracts/quiz";

export const pageCounterKind = z.enum([
  "designer_open", // открыл демо квартиры
  "variant_view", // посмотрел вариант
  "item_swap", // заменил предмет
  "flat3d_open", // открыл квартиру в 3D
  "item_move", // передвинул мебель (владелец 14.10)
  "share", // поделился: ссылка на вариант, «отправить себе» (владелец 14.10)
  "stale_link", // открыл устаревшую ссылку на вариант — показан текущий того же стиля (demo-05 п.10)
  "floor_pick", // выбрал пол из вариантов застройщика (demo-06)
  "walls_pick", // выбрал стены из вариантов застройщика (demo-07)
  "favourite_save", // сохранил расстановку в избранное (demo-15)
  "favourite_rename", // переименовал избранное (demo-15)
  "view_switch", // переключил ракурс подписью (demo-15)
  "style_tab", // переключил вкладку стиля на главной (demo-16)
  "quiz_open", // показали приветствие опроса (onb-03)
  "quiz_done", // прошёл опрос и выбрал стиль
  "quiz_skip", // «Сразу к стилям»
  "style_change", // «Выбрать другой» стиль после опроса
  // Ответы опроса — по счётчику на значение словаря, без связки с человеком (ADR-0330 п.4)
  ...quizStyle.options.flatMap((s) => [`quiz_photo:${s}`, `quiz_result:${s}`, `quiz_chosen:${s}`] as const),
  ...quizHousehold.options.map((h) => `quiz_household:${h}` as const),
  ...quizChildAge.options.map((a) => `quiz_child:${a}` as const),
  ...quizKids.options.map((k) => `quiz_kids:${k}` as const), // сколько детей (T-20261106-94)
  ...quizColour.options.map((c) => `quiz_colour:${c}` as const),
]);
export type PageCounterKind = z.infer<typeof pageCounterKind>;

export const pageEventIn = z.object({
  apartmentId: z.string().min(1).max(80),
  kind: pageCounterKind,
  lang: z.enum(["ru", "en"]).default("ru"),
});
export type PageEventIn = z.infer<typeof pageEventIn>;
