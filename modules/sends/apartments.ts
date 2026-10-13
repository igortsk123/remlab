// Какие квартиры может отправить менеджер партнёра (план b2b-02). ВРЕМЕННЫЙ реестр до контракта
// партнёра и квартиры (`b2b-06`): там он станет данными. Неизвестная квартира — отказ, не умолчание.

export type ApartmentRef = { id: string; title: string; lang: "ru" | "en"; market: "ru" | "uk" };

const REGISTRY: Record<string, ApartmentRef[]> = {
  demo: [{ id: "flat215", title: "Трёхкомнатная 73,7 м²", lang: "ru", market: "ru" }],
};

export function apartmentsOf(partnerId: string): ApartmentRef[] {
  return REGISTRY[partnerId] ?? [];
}

export function findApartment(partnerId: string, id: string): ApartmentRef | null {
  return apartmentsOf(partnerId).find((a) => a.id === id) ?? null;
}

/** Ссылка покупателю. Демо-страница читает `?s=` и подставляет карточку менеджера. */
export function sendUrl(sendId: string, base = process.env.APP_URL || "https://remont-lab.online"): string {
  return `${base.replace(/\/$/, "")}/demo/?s=${sendId}`;
}
