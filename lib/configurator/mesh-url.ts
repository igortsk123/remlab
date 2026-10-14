// Ссылка на модель предмета: лёгкая runtime-копия, иначе исходник галереи.
//
// Отдельный модуль (план demo-01): движок сцены для демо собирается в свой бандл и не должен тянуть за собой
// данные квартиры `/flat` (`data.ts` импортирует все JSON конфигуратора). Таблица копий по умолчанию — та, что
// собрана в Next при сборке; демо подставляет свежую с `/rt/runtime-meshes.json` (`setRuntimeMeshes`), потому что
// копии публикуются чаще, чем выкатывается приложение.

import runtimeJson from "@/data/flat3d/runtime-meshes.json";

/** Галерея исходников (тяжёлые GLB конвейера мешей) — фолбэк, если runtime-копии нет. */
export const MESH_BASE = process.env.NEXT_PUBLIC_FLAT3D_MESH_BASE ?? "/test/mesh-pilot10/";
/** Лёгкие runtime-копии: отдельный immutable-маршрут (ADR-0212). */
export const RUNTIME_BASE = process.env.NEXT_PUBLIC_FLAT3D_RT_BASE ?? "/rt/";

export type RuntimeEntry = { size?: number; "size-lite"?: number; src_sha?: string; "src_sha-lite"?: string };
let runtimeMeshes: Record<string, RuntimeEntry> = (runtimeJson as { meshes?: Record<string, RuntimeEntry> }).meshes ?? {};

/** Подменить таблицу копий (демо читает свежую с сервера). */
export function setRuntimeMeshes(meshes: Record<string, RuntimeEntry>): void {
  runtimeMeshes = meshes;
}

/**
 * Ссылка на модель: сперва лёгкая runtime-копия, иначе исходник галереи. Фолбэк намеренный: сцена обязана работать
 * и до того, как конвейер ассетов прогонит новый товар, — иначе каждый новый диван будет серой коробкой.
 * `?v=` — отпечаток исходника: маршрут `/rt/` отдаётся как immutable, и пересобранная копия по старому адресу
 * осталась бы у браузера на неделю.
 */
export function meshUrl(meshId: string, runtimeUrl?: string, lite = false): string {
  if (runtimeUrl) return runtimeUrl;
  const entry = runtimeMeshes[meshId];
  if (entry) {
    if (lite && entry["size-lite"]) return `${RUNTIME_BASE}${meshId}-lite.glb${entry["src_sha-lite"] ? `?v=${entry["src_sha-lite"]}` : ""}`;
    if (entry.size) return `${RUNTIME_BASE}${meshId}.glb${entry.src_sha ? `?v=${entry.src_sha}` : ""}`;
  }
  return `${MESH_BASE}${meshId}/model.glb`;
}
