// КУДА ИДЁТ ДЕНЬГА ВЫБОРА — ОДНО ЯДРО ДЛЯ ОКНА ДЕМО, /flat И СМЕТЫ (план demo-06 п.2, разбор Codex 16.10). Мебель и встраиваемое
// идут в мебельный сертификат застройщика (ADR-0254: «выбрано / лимит / доплата»), а отделка — отдельно: в RF пол — доплата
// застройщику вне сертификата, в UK — часть цены квартиры. Раньше /flat клал всё в «выбрано», и доплата за пол съела бы
// сертификат. Чистые функции, без React, реестра и three.js — страница демо получает их тем же бандлом движка.

import type { BudgetBucket } from "@/lib/configurator/budget";

export type Settlement = "allowance" | "developer_surcharge" | "property_price";

/** Строка выбора: сколько стоит и куда идёт. `onRequest` — цена неизвестна (не ноль). */
export interface SettlementLine {
  amount: number;
  settlement: Settlement;
  onRequest?: boolean;
  label?: string;
  /** Из какого бюджета пакета покрывается (`lib/configurator/budget.ts`); только для `allowance`, нет поля — мебель (старые строки). */
  budgetBucket?: BudgetBucket;
}

/** Пакет для расчёта (demo-23): режим и лимиты бюджетов. Число вместо политики — прежний контракт: одна сумма, всё в мебели. */
export interface BudgetPolicy {
  mode: "pooled" | "split";
  limits: { furniture: number; fitout: number };
}

export type BudgetSplit = { furniture: number; fitout: number; total: number };

/** Пакет по бюджетам. В `pooled` разбивка покрытия по бюджетам — справочная (сначала мебель, потом улучшения), граница одна — общая. */
export interface BudgetTotals {
  mode: BudgetPolicy["mode"];
  limits: BudgetSplit;
  /** Сколько выбрано в каждый бюджет (известные цены). */
  eligible: BudgetSplit;
  covered: BudgetSplit;
  /** Сверх лимита — доплата покупателя, а не отказ включить. */
  overage: BudgetSplit;
  /** Осталось: общий остаток всегда; по бюджетам — только в `split` (в `pooled` остаток один на двоих — `null`). */
  left: { total: number; furniture: number | null; fitout: number | null };
}

export interface SettlementTotals {
  /** Всё, что идёт в сертификат. */
  allowanceEligible: number;
  /** Покрыто сертификатом. */
  allowanceCovered: number;
  /** Сверх сертификата (доплата покупателя за мебель). */
  allowanceOverage: number;
  /** Доплата застройщику вне сертификата (RF отделка). */
  developerSurcharge: number;
  /** Прибавка к цене квартиры (UK отделка). */
  propertyPriceDelta: number;
  /** Позиции «цена по запросу» — в известный итог не входят. */
  onRequest: string[];
  /** Пакет по бюджетам; `allowance*` выше — его итоги (`total`). */
  budget: BudgetTotals;
}

/** Куда идёт группа по умолчанию, когда в данных поле не задано (Codex: только для старых данных; новые задают явно). */
export function settlementOf(kind: string, market: string, explicit?: Settlement): Settlement {
  if (explicit) return explicit;
  if (kind === "flooring" || kind === "walls" || kind === "bathroom") return market === "uk" ? "property_price" : "developer_surcharge";
  // UK: встраиваемое застройщика (кухня; позже шкафы и техника, шторка v5) — персонализация в цене квартиры, не furniture
  // allowance (владелец 16.10, ADR-0298); RF — в сертификат
  if ((kind === "kitchen" || kind === "wardrobe" || kind === "appliances") && market === "uk") return "property_price";
  return "allowance";
}

/** Сумма за м² — округление один раз на вариант (Codex 16.10). */
export const perM2Amount = (rate: number, areaM2: number): number => Math.round(rate * areaM2);

/** Политика из прежнего числового лимита: одна сумма, всё в мебели (совместимость старых вызовов и данных). */
export const asPolicy = (limit: number | BudgetPolicy): BudgetPolicy =>
  typeof limit === "number" ? { mode: "pooled", limits: { furniture: limit, fitout: 0 } } : limit;

const split = (furniture: number, fitout: number): BudgetSplit => ({ furniture, fitout, total: furniture + fitout });

/** Покрытие пакета по бюджетам. `pooled`: граница одна — сумма лимитов; `split`: каждый бюджет отдельно, перенос запрещён. */
export function budgetTotals(eligible: { furniture: number; fitout: number }, policy: BudgetPolicy): BudgetTotals {
  const lim = split(Math.max(0, policy.limits.furniture), Math.max(0, policy.limits.fitout));
  const el = split(eligible.furniture, eligible.fitout);
  let cov: BudgetSplit;
  if (policy.mode === "split") cov = split(Math.min(el.furniture, lim.furniture), Math.min(el.fitout, lim.fitout));
  else {
    const f = Math.min(el.furniture, lim.total);
    cov = split(f, Math.min(el.fitout, lim.total - f));
  }
  const over = split(el.furniture - cov.furniture, el.fitout - cov.fitout);
  const left = policy.mode === "split"
    ? { total: lim.total - cov.total, furniture: lim.furniture - cov.furniture, fitout: lim.fitout - cov.fitout }
    : { total: lim.total - cov.total, furniture: null, fitout: null };
  return { mode: policy.mode, limits: lim, eligible: el, covered: cov, overage: over, left };
}

export function settle(lines: readonly SettlementLine[], limit: number | BudgetPolicy): SettlementTotals {
  const eligible = { furniture: 0, fitout: 0 };
  let surcharge = 0;
  let property = 0;
  const onRequest: string[] = [];
  for (const l of lines) {
    if (l.onRequest) {
      onRequest.push(l.label ?? "");
      continue;
    }
    const a = Math.max(0, Math.round(l.amount));
    if (l.settlement === "allowance") eligible[l.budgetBucket ?? "furniture"] += a;
    else if (l.settlement === "developer_surcharge") surcharge += a;
    else property += a;
  }
  const budget = budgetTotals(eligible, asPolicy(limit));
  return {
    allowanceEligible: budget.eligible.total,
    allowanceCovered: budget.covered.total,
    allowanceOverage: budget.overage.total,
    developerSurcharge: surcharge,
    propertyPriceDelta: property,
    onRequest,
    budget,
  };
}
