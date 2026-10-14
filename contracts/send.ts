// Отправка ссылки менеджером покупателю (план b2b-02, ADR-0257).
//
// Одна отправка = одна ссылка одному покупателю: по ней видно, что смотрели и о чём просили, без
// имени и телефона покупателя. Словарь событий покупателя совпадает с `b2b-03` (одни имена в
// демо, в отчёте и в сигналах). Статусы делятся на две части: «открыл/выбирает» ставит система по
// событиям, «связались/встреча/сделка/отказ» — только менеджер (публичная страница их не трогает).

import { z } from "zod";

/** События покупателя — единственное, что принимает публичная ручка. */
export const buyerEventKind = z.enum([
  "designer_open", // открыл ссылку
  "variant_view", // посмотрел вариант
  "item_swap", // заменил предмет
  "manager_contact_click", // нажал «консультация»/«ипотека» — это клик, не состоявшийся контакт
  "alternative_request", // «хочу другой вариант» с причиной из списка
  "flat3d_open", // открыл квартиру в 3D по этой ссылке (b2b-03); сохранение коллекции считается из `collections`
  "item_move", // передвинул мебель (владелец 14.10)
  "share", // поделился: ссылка на вариант, «отправить себе» (владелец 14.10)
]);
export type BuyerEventKind = z.infer<typeof buyerEventKind>;

/** Причины «хочу другой вариант» — только из списка: свободный текст мог бы принести имена и телефоны. */
export const alternativeReason = z.enum(["price", "style", "space", "color", "other"]);
export type AlternativeReason = z.infer<typeof alternativeReason>;

export const buyerEvent = z.object({
  kind: buyerEventKind,
  variant: z.string().max(80).optional(),
  items: z.array(z.string().max(120)).max(30).optional(),
  sum: z.number().int().min(0).max(1_000_000_000).optional(),
  purpose: z.enum(["consult", "mortgage"]).optional(),
  channel: z.enum(["telegram", "whatsapp", "phone"]).optional(),
  reason: alternativeReason.optional(),
});
export type BuyerEvent = z.infer<typeof buyerEvent>;

/** Статусы по порядку: система двигает только вперёд и только по своим ступеням. */
export const sendStatus = z.enum(["sent", "opened", "engaged", "contacted", "meeting", "deal", "lost"]);
export type SendStatus = z.infer<typeof sendStatus>;
export const AUTO_STATUSES: readonly SendStatus[] = ["sent", "opened", "engaged"];
export const managerStatus = z.enum(["contacted", "meeting", "deal", "lost"]);
export type ManagerStatus = z.infer<typeof managerStatus>;

/** Какой статус система ставит по событию покупателя; null — не трогает. */
export function autoStatusFor(kind: BuyerEventKind): SendStatus | null {
  return kind === "designer_open" ? "opened" : "engaged";
}

/** Можно ли системе сменить `from` на `to`: только вперёд и только пока менеджер ничего не ставил. */
export function autoAdvanceAllowed(from: SendStatus, to: SendStatus): boolean {
  if (!AUTO_STATUSES.includes(from)) return false;
  return AUTO_STATUSES.indexOf(to) > AUTO_STATUSES.indexOf(from);
}

/** Публичная карточка для страницы покупателя: только то, что менеджер готов показать. */
export type SendCard = {
  id: string;
  apartmentId: string;
  lang: string;
  market: string;
  manager: { name: string; phone: string | null; telegram: string | null; whatsapp: string | null };
};
