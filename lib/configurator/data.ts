// Загрузка данных конфигуратора: квартира + каталог (покрытия, встроенное, мебель из мешей).
// Данные лежат JSON-файлами в `data/flat3d/` и проверяются Zod при первом обращении —
// битые данные должны падать на сборке/тесте, а не в браузере покупателя.

import { apartment as apartmentSchema, type Apartment } from "@/contracts/apartment";
import { catalogue as catalogueSchema, type Catalogue, type Material, type Option } from "@/contracts/configurator";
import apartmentJson from "@/data/flat3d/apartment.json";
import catalogueJson from "@/data/flat3d/catalogue-base.json";
import furnitureJson from "@/data/flat3d/furniture.json";
import materialsJson from "@/data/flat3d/materials.json";
export { MESH_BASE, RUNTIME_BASE, meshUrl } from "@/lib/configurator/mesh-url";

function withBase(base: string, url?: string): string | undefined {
  if (!url) return undefined;
  return /^https?:|^\//.test(url) ? url : base + url;
}

let cached: { apartment: Apartment; catalogue: Catalogue } | null = null;

/** Квартира и каталог. Разбор один раз на процесс — данные статические. */
export function loadFlat3d(): { apartment: Apartment; catalogue: Catalogue } {
  if (cached) return cached;

  const base = (materialsJson as { baseUrl?: string }).baseUrl ?? "/flat3d/materials/";
  const textured: Material[] = (materialsJson as { materials: unknown[] }).materials.map((raw) => {
    const m = raw as Record<string, string | number | undefined>;
    return {
      ...m,
      baseColorUrl: withBase(base, m.baseColorUrl as string | undefined),
      normalUrl: withBase(base, m.normalUrl as string | undefined),
      roughnessUrl: withBase(base, m.roughnessUrl as string | undefined),
      aoUrl: withBase(base, m.aoUrl as string | undefined),
      previewUrl: withBase(base, m.previewUrl as string | undefined),
    } as unknown as Material;
  });

  // материалы каталога (краски, фасады) тоже могут ссылаться на файл текстуры
  const plain = (catalogueJson.materials as unknown[]).map((raw) => {
    const m = raw as Record<string, unknown>;
    return { ...m, baseColorUrl: withBase(base, m.baseColorUrl as string | undefined) };
  });

  const merged = {
    developerId: catalogueJson.developerId,
    titleRu: catalogueJson.titleRu,
    titleEn: catalogueJson.titleEn,
    // валюта — из файла каталога (застройщик UK — GBP); source.ts сверяет её с валютой застройщика
    currency: (catalogueJson as { currency?: string }).currency === "RUB" ? ("RUB" as const) : ("GBP" as const),
    options: [...(catalogueJson.options as unknown[]), ...(furnitureJson.options as unknown[])],
    materials: [...plain, ...textured],
  };

  const parsedCatalogue = catalogueSchema.parse(merged);
  const parsedApartment = apartmentSchema.parse(apartmentJson);
  cached = { apartment: parsedApartment, catalogue: parsedCatalogue };
  return cached;
}

/** Опции одной категории — для панели комнаты. */
export function optionsByCategory(c: Catalogue, category: Option["category"]): Option[] {
  return c.options.filter((o) => o.category === category);
}
