// Вход бандла движка сцены для статической страницы демо (план demo-01 п.1): `tools/flat3d/build-scene-bundle.mjs`
// собирает его ES-модулем `lib/scene.<версия>.js` рядом с демо, страница грузит его `import()`. Демо остаётся одним html без
// сборки (ADR-0158); `/flat` берёт тот же исходник через Next — версия движка у обоих одна (`build` = отпечаток входов).

declare const __ENGINE_BUILD__: string;

export const build: string = typeof __ENGINE_BUILD__ === "string" ? __ENGINE_BUILD__ : "dev";
export { createDemoScene, liveApartment } from "@/lib/viewer3d/demo-scene";
// куда идёт деньга выбора (сертификат / доплата застройщику / цена квартиры) — то же ядро, что у /flat (demo-06)
export { settle } from "@/lib/configurator/settlement";
