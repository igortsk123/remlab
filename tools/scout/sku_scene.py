"""ПОЛЯ 3D-СЦЕНЫ У ТОВАРА — ОДНО ПРАВИЛО ДЛЯ ДЕМО И ДЛЯ ТУРА ЗАГРУЖЕННОГО ПЛАНА (T-20261112-96, владелец TG 940/942: «новый план
на лендинге — по ВСЕМ отработанным правилам»).

Раньше эти шаги жили только в сборке демо (`flat215_demo.main` → `annotate_*`), и тур (`trial_bundle.build`) их не делал:
цветовой вариант рисовался цветом представителя (нет `tint`), модель с калибровкой стояла неразвёрнутой (нет `yaw`), подвесная
тумба в «Фото» тура вставала на пол (нет `hung`). Теперь оба пути зовут функции отсюда:
  - `hung(name)` — подвесная тумба по НАЗВАНИЮ товара;
  - `yaw(skus)` — разворот фронта модели (`orient.json` прода, ручные поправки `data/flat3d/front-overrides.json` сильнее);
  - `tint(skus, out_dir)` — подкраска цветового варианта на модели семейства (строка ночного замера сторожа или тоны двух фото);
  - `strategy(items)` — `procedural_plane` у зеркала, картины, ковра (`asset_strategy`).
`skus` — список словарей `sku` (меняются на месте). Подкраске нужен ключ товара: `sid` (демо) или `_sid` (тур: `sid` в данные
страницы не идёт — `trial_bundle.NEVER_KEYS`, ключ живёт только на время сборки)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ORIENT_URL = 'https://remont-lab.online/test/mesh-pilot10/orient.json'
HUNG_WORDS = ('подвесн', 'навесн', 'настенн')


def skus_of(data: dict) -> list:
    """Все `sku` данных страницы: предметы и декор вариантов + строки лент замен."""
    skus = [it.get('sku') or {} for v in data.get('variants') or [] for it in (v.get('items') or []) + (v.get('decor') or [])]
    skus += [f for lst in (data.get('feeds') or {}).values() for f in lst if isinstance(f, dict)]
    return skus


def _key(sk: dict):
    return sk.get('sid') or sk.get('_sid')


def hung(name: str | None) -> bool:
    """Подвесная (навесная) тумба? Размечаем ПО НАЗВАНИЮ ТОВАРА, а не по высоте.

    Владелец 02.09: «посмотри все тв-тумбы на замену и размети навесные». Соблазн был считать
    низкие тумбы подвесными, но проверка карточки показала обратный пример: «Флавир 140x27» при
    высоте 27 см — НАПОЛЬНАЯ, на ножках («Расположение: напольное» в характеристиках). Высота
    признаком не является; название — является.

    Зачем признак: у подвесной тумбы её «высота» — толщина корпуса, а не уровень верхней
    плоскости, и телевизор на неё не ставят, а вешают над ней (`draft_render.tv_spec`).
    """
    n = (name or '').lower()
    return any(k in n for k in HUNG_WORDS)


def mark_hung(skus: list) -> int:
    """`sku.hung = True` у товаров с «подвесным» названием (поле только «да»: нет — нет поля). → сколько отмечено."""
    n = 0
    for sk in skus:
        if isinstance(sk, dict) and hung(sk.get('name')):
            sk['hung'] = True
            n += 1
    return n


_ORIENT: dict = {}


def family(skus: list, rep: dict) -> int:
    """СЕМЬЯ ЦВЕТОВ — по представителю семьи (`rep`: артикул товара → артикул модели семьи, `room_bindings.mesh_rep`), а не по
    модели сцены (T-20261106-77/5): у цвета бывает своя 3D-модель (`msid`), и группировка по `msid` разбивала семью. Где семья
    отличается от `msid`, она пишется в `sku.fam` — по ней страница собирает «Цвета этой модели» (`index.html:famKey`). → сколько."""
    n = 0
    for sk in skus:
        sk.pop('fam', None)
        sid = _key(sk)
        if sk.get('msid') and sid:
            key = rep.get(sid) or sk['msid']                 # семьи не знаем — как раньше, по модели
            if key != sk['msid']:
                sk['fam'] = key
                n += 1
    return n


def orient_tables(orient: dict | None = None, over: dict | None = None) -> tuple:
    """(orient.json прода, ручные поправки). Нет сети/файла — пустые: разворотов нет, как раньше. Таблица прода читается один раз
    на процесс (тур собирает по сборке на задание, перевыпуск — пачкой)."""
    if orient is None and 'orient' in _ORIENT:
        orient = _ORIENT['orient']
    if orient is None:
        import urllib.request
        try:
            orient = json.load(urllib.request.urlopen(ORIENT_URL, timeout=30))
        except Exception:  # noqa: BLE001
            orient = {}
        _ORIENT['orient'] = orient
    if over is None:
        try:
            over = json.load(open(os.path.join(HERE, '..', '..', 'data', 'flat3d', 'front-overrides.json'),
                                  encoding='utf-8')).get('overrides') or {}
        except Exception:  # noqa: BLE001
            over = {}
    return orient, over


def yaw(skus: list, orient: dict | None = None, over: dict | None = None) -> int:
    """Разворот фронта модели в `sku.yaw` (3D `lib/configurator/fromDemo.ts` берёт `sk.yaw ?? 0`): поправка руками сильнее
    калибровки. → сколько проставлено."""
    orient, over = orient_tables(orient, over)
    n = 0
    for sk in skus:
        m = sk.get('msid')
        if not m:
            continue
        y = (over.get(m) or {}).get('yawDeg', (orient.get(m) or {}).get('yaw'))
        if y is not None:
            sk['yaw'] = float(y)
            n += 1
    return n


def strategy(items: list) -> int:
    """Не-меш стратегия `procedural_plane` (зеркало, картина, ковёр) в предмет — мост рисует их плоскостью на стене только по
    этому полю. У остальных данные не меняются. → сколько отмечено."""
    import asset_strategy as _AS
    n = 0
    for it in items:
        if _AS.strategy(it.get('role')) == 'procedural_plane':
            it['strategy'] = 'procedural_plane'
            n += 1
    return n


def tone(path: str):
    """Средний цвет товара по фото без белого фона (доли 0..1) — `mesh_color_check.tone`, одно правило со сторожем цвета."""
    import mesh_color_check as _MCC
    return _MCC.tone(path)


def rep_tones(msids: set) -> dict:
    """Тон текущего фото ПРЕДСТАВИТЕЛЯ, которого нет среди товаров страницы (T-20261107-14/2). Нет базы или фото — {} и WARN."""
    if not msids:
        return {}
    try:
        import mesh_color_check as _MCC
        th = _MCC.thumbs_of(_MCC.photo_urls({m.replace('_', ':', 1) for m in msids}))
        return {k.replace(':', '_', 1): tone(p) for k, p in th.items()}
    except Exception as e:  # noqa: BLE001 — нет базы/сети: подкраска только по товарам страницы, громко
        print(f'WARN:tint_rep: фото представителей вне демо не прочитаны ({repr(e)[:120]}) — подкраска только по товарам демо',
              flush=True)
        return {}


def tint(skus: list, out_dir: str, rep=None, table=None) -> int:
    """ЦВЕТ ВАРИАНТА НА МОДЕЛИ СЕМЕЙСТВА (demo-02 п.11б): у цветового варианта своей 3D-модели нет, он показывается моделью
    представителя (`msid`). Подкраска `sku.tint` — множитель цвета материала (`lib/viewer3d/meshes.ts`):
    строка ночного замера сторожа про пару «вариант → модель» (T-20261112-89) — её множитель; нет строки — тон фото варианта / тон
    фото представителя (`mesh_color_check.tint_of`, границы — `rules/mesh-color-guard.json`). Фото — плитки `img/…` в `out_dir`;
    представителя нет среди товаров — его текущее фото из каталога (`rep`, по умолчанию `rep_tones`). → сколько подкрашено."""
    import mesh_color_check as _MCC
    rep = rep or rep_tones
    tones: dict = {}
    for sk in skus:
        sid, img = _key(sk), sk.get('img')
        if sid and sid not in tones and img and not str(img).startswith('http'):
            tones[sid] = tone(os.path.join(out_dir, img))
    need = {sk.get('msid') for sk in skus if _key(sk) and sk.get('msid') and _key(sk) != sk['msid'] and not tones.get(sk['msid'])}
    tones.update({k: v for k, v in rep(need).items() if v})
    R = _MCC.rules()
    if table is None:
        table, _why = _MCC.load_table(R=R)
    table = table or {}
    n = 0
    for sk in skus:
        sk.pop('tint', None)
        sid, msid = _key(sk), sk.get('msid')
        if not sid or not msid or sid == msid:
            continue
        row = table.get(sid.replace('_', ':', 1)) or {}
        if row.get('via_family') and row.get('owner') == msid.replace('_', ':', 1) and row.get('verdict') in ('ok', 'mismatch'):
            if row.get('tint'):
                sk['tint'] = row['tint']
                n += 1
            continue
        t = _MCC.tint_of(tones.get(sid), tones.get(msid), R)
        if t:
            sk['tint'] = t
            n += 1
    return n
