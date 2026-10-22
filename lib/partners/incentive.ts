// ПАКЕТ ПООЩРЕНИЯ КВАРТИРЫ (demo-23, разбор Codex 22.10): ближайший уровень квартира → ЖК → партнёр заменяет политику ЦЕЛИКОМ —
// без слияния полей, иначе лимит одного уровня тихо смешался бы с режимом другого. Ни на одном уровне нет — прежний сертификат
// (`certificateShare`) как одна сумма, всё в мебели: старые данные дают прежние суммы. Чистые функции: реестр, сохранение подбора
// и тесты берут пакет только отсюда.

import type { ApartmentRef, Complex, Partner, ResolvedIncentive } from "@/contracts/partner";

/** Прежний сертификат: доля цены, округлённая ВНИЗ (₽ — до 10 000, £ — до 100): не обещаем больше доли. */
export function certificateAmount(p: Partner, a: ApartmentRef): number {
  const step = p.currency === "RUB" ? 10_000 : 100;
  return Math.floor((a.price * p.certificateShare) / step) * step;
}

export function resolveIncentive(p: Partner, c: Complex | undefined, a: ApartmentRef): ResolvedIncentive | null {
  const hit = a.incentive ? { ...a.incentive, source: "apartment" as const }
    : c?.incentive ? { ...c.incentive, source: "complex" as const }
    : p.incentive ? { ...p.incentive, source: "partner" as const }
    : null;
  if (hit) {
    const total = hit.limits.furniture + hit.limits.fitout;
    return total > 0 ? { mode: hit.mode, limits: { ...hit.limits }, total, source: hit.source } : null;
  }
  const legacy = certificateAmount(p, a);
  return legacy > 0 ? { mode: "pooled", limits: { furniture: legacy, fitout: 0 }, total: legacy, source: "legacy" } : null;
}
