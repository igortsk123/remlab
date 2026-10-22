// ИЗ КАКОГО БЮДЖЕТА ПАКЕТА ПОКРЫВАЕТСЯ ПОЗИЦИЯ (demo-23, разбор Codex 22.10). Вторая ось рядом с `settlement`: `settlement` говорит,
// КУДА идёт счёт (в пакет, застройщику, в цену квартиры), бюджет — ИЗ ЧЕГО покрывается то, что идёт в пакет. Только по стабильной
// таксономии — товар магазина, вид и категория слота 3D, вид группы опций застройщика; без списков SKU и названий. Техника — к мебели
// (владелец 22.10: бюджет «Мебель и техника»). Чистая функция без React и реестра: её же берёт бандл корзины страницы демо.

export type BudgetBucket = "furniture" | "fitout";

/** Что известно о позиции: товар магазина, слот 3D (`slot.kind`/`slot.category`) или группа опций застройщика (`optionGroup.kind`). */
export type BudgetSubject =
  | { source: "shop" }
  | { slotKind: "surface" | "builtin" | "furniture"; slotCategory?: string }
  | { groupKind: string };

/** Виды групп опций, которые относятся к «Мебели и технике»; все прочие (кухня, шкаф, санузел, пол, стены) — к «Улучшениям». */
const FURNITURE_GROUPS: ReadonlySet<string> = new Set(["appliances"]);

export function budgetBucket(s: BudgetSubject): BudgetBucket {
  if ("source" in s) return "furniture";
  if ("groupKind" in s) return FURNITURE_GROUPS.has(s.groupKind) ? "furniture" : "fitout";
  // техника — к мебели, даже встроенная; дальше решает вид слота: отдельно стоящее — мебель, покрытие и встроенное — улучшения
  if (s.slotCategory === "appliances") return "furniture";
  return s.slotKind === "furniture" ? "furniture" : "fitout";
}
