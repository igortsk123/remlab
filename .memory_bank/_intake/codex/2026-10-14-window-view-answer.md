---
tier: 3
topic: codex-answer
scope: Ответ Codex — вид из окна (demo-04 п.5): данные, IR backdrop, back 20–40 см, горизонт по ассету, прокси без SSRF
updated: 2026-10-14
source: external:codex
---

1. **Данные — да; источник отдельно, проекция в IR.**

- `windowView` у квартиры годится как default; `opening.view` — override. Разрешать лучше по цепочке `opening → room → apartment → preset`.
- Не смешивал бы id и URL в строке: `ViewSource = {kind:"preset", id} | {kind:"remote", url}`.
- В `OpeningIR` должна жить уже вычисленная проекция, потому что она нужна обоим рендерам:

```ts
backdrop?: {
  assetId: string;          // внутренний непрозрачный id, не внешний URL
  u0: number; u1: number;
  bottom: number; top: number;
  backCm: number;
}
```

Это естественное продолжение [`opening-ir.ts:38`](/home/pakar/igor/remlab/lib/viewer3d/opening-ir.ts:38). Источник/наследование остаётся в данных, а производная геометрия — в IR. Поднять `OPENING_IR_VERSION` в [`opening-ir.ts:12`](/home/pakar/igor/remlab/lib/viewer3d/opening-ir.ts:12).

Сейчас `view` потеряется в мостах: добавить его в [`fromDemo.ts:67`](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:67) и [`opening-ir.mjs:24`](/home/pakar/igor/remlab/tools/flat3d/opening-ir.mjs:24). Ночная вставка IR уже находится в правильном месте: [`flat215_demo.py:1059`](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1059).

Серверу передавать только `assetId`; внешний URL должен один раз пройти прокси/нормализацию. Не добавлять произвольный URL в клиентский `openings_ir`: сейчас сервер специально санитизирует его как недоверенные данные в [`opening_ir.py:32`](/home/pakar/igor/remlab/tools/scout/opening_ir.py:32).

2. **`back=150` великоват; `tan(70°)` математически верен, но создаёт огромную плоскость.**

При 150 см запас будет `150·tan70° ≈ 412 см` с каждой стороны. Это почти гарантирует пересечения у углов и повторение картинки в соседних окнах.

Я бы начал с `back=20–40 см`. Текущий сервер уже использует `BEYOND_CM=20` и запас 150 см в [`scene.py:349`](/home/pakar/igor/remlab/services/planner-solver/planner/scene.py:349). Запас обязательно ограничивать:

- концами стены;
- серединой простенка до соседнего проёма;
- stencil/mask конкретного выреза в браузере.

Такая отсечка уже реализована сервером в [`scene.py:576`](/home/pakar/igor/remlab/services/planner-solver/planner/scene.py:576) — её стоит вынести в общий расчёт IR. Для нескольких окон одной стены лучше один общий `viewGroup`/проекционная плоскость, иначе одинаковый skyline повторится в каждом окне.

В `paint_beyond` нужны два пересечения: на `z=0` проверяем, что луч прошёл через `cut` и не закрыт мебелью; на `z=-back` только вычисляем UV. Сейчас первая половина уже есть в [`opening_ir.py:169`](/home/pakar/igor/remlab/tools/scout/opening_ir.py:169).

3. **Горизонт и цвет.**

- Не центрировать изображение по глазу. Хранить для каждого ассета `horizon01` от верхнего края и ставить:

```text
bottom = eyeY - (1 - horizon01) * imageHeight
top    = bottom + imageHeight
```

- `135 см` не универсальны: прогулка использует 162 см, photo-v2 — 135 см ([`viewer.ts:46,99`](/home/pakar/igor/remlab/lib/viewer3d/viewer.ts:99)), автоматическая серверная камера — 155 см ([`scene.py:113`](/home/pakar/igor/remlab/services/planner-solver/planner/scene.py:113)). Для неподвижной плоскости разумный компромисс — 155–160 см; точное совпадение во всех режимах возможно только при camera-relative shader.
- Использовать реальное соотношение `1600/1072`, а не условное 3:2. Документация сейчас говорит 1600×1067 и «горизонт посередине» в [`window_views.py:8`](/home/pakar/igor/remlab/tools/scene/window_views.py:8), что уже расходится с файлами и фактическим горизонтом.
- Яркость/дымку считать в linear RGB. Стекло лучше имитировать как `mix(view, #eaf2f6, 0.07)`, а не просто `×0.94` — это ближе к браузерному материалу из [`openings.ts:22`](/home/pakar/igor/remlab/lib/viewer3d/openings.ts:22).
- Если картинки заранее нормализованы прокси, у `MeshBasicMaterial` поставить `fog:false`, `toneMapped:false`; иначе текущий exposure 1.05 даст расхождение с сервером ([`viewer.ts:230`](/home/pakar/igor/remlab/lib/viewer3d/viewer.ts:230)). Дымки достаточно 5–12% к цвету неба около горизонта.
- Серверное стекло пропускать только при успешно загруженном backdrop; сейчас оно всегда превращается в непрозрачный mesh в [`opening_ir.py:106`](/home/pakar/igor/remlab/tools/scout/opening_ir.py:106).

4. **Прокси: обязательный минимум.**

- Только `https`, порт 443, без userinfo; exact-host allowlist.
- Резолвить все A/AAAA и запрещать loopback, private, link-local, multicast, metadata IP; соединяться именно с проверенным IP с сохранением Host/SNI — защита от DNS rebinding.
- Редиректы выключить либо максимум 2–3, заново проверяя URL и IP каждого hop.
- Лимитировать и `Content-Length`, и реально прочитанный поток; connect/read/total timeout, concurrency и rate limit.
- Не доверять `image/*`: разрешить только JPEG/PNG/WebP/AVIF, проверить magic bytes и декодирование; запретить SVG и animation, ограничить размеры/число пикселей, затем перекодировать в собственный WebP.
- Не пересылать cookies/Authorization; не логировать исходный URL с signed query.
- Лучше `/api/scene/view?id=<opaque-id>`, чем `?u=`: серверный renderer тоже получает этот id и не ходит по произвольным URL.
- Дополнительно — egress firewall: процесс прокси может обращаться только наружу по 443.

Это соответствует актуальной схеме защиты от SSRF: allowlist, запрет автоматических редиректов и проверка/фиксация DNS-адреса при соединении ([OWASP SSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)).