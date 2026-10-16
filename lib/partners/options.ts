// ВЫБОР В ГРУППАХ ОПЦИЙ ЗАСТРОЙЩИКА — КАНОНИЧЕСКИЙ ВИД (demo-06, разбор Codex 16.10). Источник выбора — пара «группа → вариант»;
// слоты квартиры (пол витрины) — лишь проекция. Канон: только включённые группы карточки, только их варианты и только
// отличные от варианта по умолчанию — так одна и та же квартира с полом по умолчанию даёт пустой выбор (номер состояния s1).

import type { ApartmentCard } from "@/contracts/partner";

export function canonDeveloperOptions(groups: ApartmentCard["options"], picked: Record<string, string> | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const g of groups) {
    const v = picked?.[g.id];
    if (v && v !== g.defaultVariantId && g.variants.some((x) => x.id === v)) out[g.id] = v;
  }
  return out;
}
