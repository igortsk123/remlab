// Вход модуля корзины для статической страницы демо (demo-16 шаг 2): `tools/flat3d/build-scene-bundle.mjs` собирает его в
// `lib/basket.<версия>.js` рядом с движком сцены; страница грузит его `import()` сразу (он маленький), движок — лениво.
export * from "@/lib/basket/basket";
export { settle } from "@/lib/configurator/settlement";
export { budgetBucket } from "@/lib/configurator/budget";
