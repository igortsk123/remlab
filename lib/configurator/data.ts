// Загрузка данных конфигуратора: квартира + каталог (покрытия, встроенное, мебель из мешей).
// Данные лежат JSON-файлами в `data/flat3d/` и проверяются Zod при первом обращении —
// битые данные должны падать на сборке/тесте, а не в браузере покупателя.

import { apartment as apartmentSchema, type Apartment } from "@/contracts/apartment";
import { catalogue as catalogueSchema, type Catalogue, type Material, type Option } from "@/contracts/configurator";
import apartmentJson from "@/data/flat3d/apartment.json";
import catalogueJson from "@/data/flat3d/catalogue-base.json";
import furnitureJson from "@/data/flat3d/furniture.json";
import materialsJson from "@/data/flat3d/materials.json";
import runtimeJson from "@/data/flat3d/runtime-meshes.json";

/** Галерея исходников (тяжёлые GLB конвейера мешей) — фолбэк, если runtime-копии нет. */
export const MESH_BASE = process.env.NEXT_PUBLIC_FLAT3D_MESH_BASE ?? "/test/mesh-pilot10/";
/** Лёгкие runtime-копии: отдельный immutable-маршрут (ADR-0212). */
export const RUNTIME_BASE = process.env.NEXT_PUBLIC_FLAT3D_RT_BASE ?? "/rt/";

const runtimeMeshes = (runtimeJson as { meshes?: Record<string, { size?: number; "size-lite"?: number }> }).meshes ?? {};

/**
 * Ссылка на модель: сперва лёгкая runtime-копия (1024 текстуры, без MR-карты), иначе исходник
 * галереи. Фолбэк намеренный: сцена обязана работать и до того, как конвейер ассетов прогонит
 * новый товар, — иначе каждый новый диван будет серой коробкой.
 */
export function meshUrl(meshId: string, runtimeUrl?: string, lite = false): string {
  if (runtimeUrl) return runtimeUrl;
  const entry = runtimeMeshes[meshId];
  if (entry) {
    if (lite && entry["size-lite"]) return `${RUNTIME_BASE}${meshId}-lite.glb`;
    if (entry.size) return `${RUNTIME_BASE}${meshId}.glb`;
  }
  return `${MESH_BASE}${meshId}/model.glb`;
}

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
    currency: "GBP" as const,
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
