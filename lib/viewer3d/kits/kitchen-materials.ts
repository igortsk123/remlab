// Свои материалы набора кухни (план onb-09 часть А): цвета примеров из магазина, которых нет в общем каталоге покрытий
// (`data/flat3d/materials.json`). Замер — медиана рамки по фото магазина (`colors.*.proposed` в паспортах
// `data/partners/kitchen-examples/*.json`, ΔE до ближайшего нашего > 10). Фактуры нет — честный ровный цвет.
// Набор берёт их, только если каталог сцены такого id не знает: каталог главнее.

import type { Material } from "@/contracts/configurator";

const solid = (id: string, titleRu: string, titleEn: string, colorHex: string, surfaces: Material["surfaces"], roughness: number): Material => ({
  id, titleRu, titleEn, colorHex, roughness, metalness: 0, tileCm: [100, 100], surfaces, source: { kind: "procedural", note: "замер по фото примера onb-08" },
});

export const KITCHEN_MATERIALS: readonly Material[] = [
  solid("front-concrete", "Фасад «бетон»", "Concrete-effect front", "#abb0b4", ["front"], 0.55),
  solid("front-anthracite", "Фасад «антрацит»", "Anthracite front", "#3c4a4a", ["front"], 0.45),
  solid("front-sage", "Фасад «шалфей»", "Sage front", "#bab49a", ["front"], 0.5),
  solid("worktop-oak-votan", "Столешница «дуб вотан»", "Votan oak worktop", "#7e694c", ["worktop"], 0.4),
  solid("splashback-oak-light", "Фартук «светлый дуб»", "Light oak splashback", "#ab9b8b", ["splashback"], 0.45),
];

const BY_ID = new Map(KITCHEN_MATERIALS.map((m) => [m.id, m]));

export function kitchenMaterial(id: string): Material | undefined {
  return BY_ID.get(id);
}
