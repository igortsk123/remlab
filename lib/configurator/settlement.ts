// КУДА ИДЁТ ДЕНЬГА ВЫБОРА — ОДНО ЯДРО ДЛЯ ОКНА ДЕМО, /flat И СМЕТЫ (план demo-06 п.2, разбор Codex 16.10). Мебель и встраиваемое
// идут в мебельный сертификат застройщика (ADR-0254: «выбрано / лимит / доплата»), а отделка — отдельно: в RF пол — доплата
// застройщику вне сертификата, в UK — часть цены квартиры. Раньше /flat клал всё в «выбрано», и доплата за пол съела бы
// сертификат. Чистые функции, без React, реестра и three.js — страница демо получает их тем же бандлом движка.

export type Settlement = "allowance" | "developer_surcharge" | "property_price";

/** Строка выбора: сколько стоит и куда идёт. `onRequest` — цена неизвестна (не ноль). */
export interface SettlementLine {
  amount: number;
  settlement: Settlement;
  onRequest?: boolean;
  label?: string;
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
}

/** Куда идёт группа по умолчанию, когда в данных поле не задано (Codex: только для старых данных; новые задают явно). */
export function settlementOf(kind: string, market: string, explicit?: Settlement): Settlement {
  if (explicit) return explicit;
  if (kind === "flooring" || kind === "walls" || kind === "bathroom") return market === "uk" ? "property_price" : "developer_surcharge";
  // UK: кухня застройщика — персонализация в цене квартиры, не furniture allowance (владелец 16.10, ADR-0298); RF — в сертификат
  if (kind === "kitchen" && market === "uk") return "property_price";
  return "allowance";
}

/** Сумма за м² — округление один раз на вариант (Codex 16.10). */
export const perM2Amount = (rate: number, areaM2: number): number => Math.round(rate * areaM2);

export function settle(lines: readonly SettlementLine[], allowanceLimit: number): SettlementTotals {
  let eligible = 0;
  let surcharge = 0;
  let property = 0;
  const onRequest: string[] = [];
  for (const l of lines) {
    if (l.onRequest) {
      onRequest.push(l.label ?? "");
      continue;
    }
    const a = Math.max(0, Math.round(l.amount));
    if (l.settlement === "allowance") eligible += a;
    else if (l.settlement === "developer_surcharge") surcharge += a;
    else property += a;
  }
  const limit = Math.max(0, allowanceLimit);
  return {
    allowanceEligible: eligible,
    allowanceCovered: Math.min(eligible, limit),
    allowanceOverage: Math.max(0, eligible - limit),
    developerSurcharge: surcharge,
    propertyPriceDelta: property,
    onRequest,
  };
}
