# basis_transcoder — откуда он и когда обновлять

Файлы `basis_transcoder.js` и `basis_transcoder.wasm` скопированы БЕЗ ИЗМЕНЕНИЙ из
`node_modules/three/examples/jsm/libs/basis/` (пакет `three`, версия в `package.json`).

Нужны для KTX2-текстур в 3D-конфигураторе: `lib/viewer3d/meshes.ts` отдаёт `KTX2Loader`
путь `/vendor/basis/`. В бандл они не попадают — браузер грузит их только когда встречает
модель с KTX2.

**Обновлять вместе с `three`:**

    cp node_modules/three/examples/jsm/libs/basis/basis_transcoder.{js,wasm} public/vendor/basis/

Иначе транскодер и загрузчик разъедутся по версии, и модели с KTX2 молча не покажутся.
