// НАЗВАНИЕ ТОВАРА ДЛЯ ПОДПИСИ В КАДРЕ — БЕЗ МАГАЗИНА (flat3d-375-overlaps, 22.10): фиды пишут домен прямо в название
// («Диван прямой divan.ru Викс…», «Sofa · divan.ru»), и на телефоне он съедал ширину подписи. Магазины берём из данных
// (`Option.shopName`), списка в коде нет. Варианты домена: любой регистр, «www.», «divan ru» и одно имя «divan».
// Убираем только латинское слово целиком: «диван» по-русски и «divanboss» при магазине divan.ru не трогаем.

const escape = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Функция «название → название без магазинов»; без магазинов — название как есть (только пробелы выровнены). */
export function shopStripper(shops: readonly string[]): (title: string) => string {
  const alts = [...new Set(shops.map((s) => s.trim().toLowerCase().replace(/^www\./, "")).filter(Boolean))]
    .map((s) => {
      const dot = s.lastIndexOf(".");
      if (dot <= 0) return escape(s);
      return `${escape(s.slice(0, dot))}(?:[.\\s]?${escape(s.slice(dot + 1))})?`;
    })
    .sort((a, b) => b.length - a.length);
  const re = alts.length ? new RegExp(`(?<![\\p{L}\\p{N}.])(?:www\\.)?(?:${alts.join("|")})(?![\\p{L}\\p{N}])`, "giu") : null;
  return (title) => {
    const tidy = (s: string) => s.replace(/\s+/g, " ").trim();
    if (!re) return tidy(title);
    const parts = title.replace(re, " ").split("·").map(tidy).filter(Boolean);
    const out = parts.join(" · ");
    return out || tidy(title);
  };
}
