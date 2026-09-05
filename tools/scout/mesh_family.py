#!/usr/bin/env python3
"""Семейства моделей: один меш на МОДЕЛЬ, цвета/ткани — варианты одной формы (владелец 05.09).

Зачем. Магазины продают одну и ту же форму под разными артикулами — «ТВ-тумба Модерн 140x65»
белая, графитовая, латте, терракотовая, оливковая. Конвейер генерил меш каждому артикулу: среди
готовых мешей 503 повторяли форму соседа, в очереди 41 % заданий были цветовыми вариантами.
Владелец: «один меш на модель, цвета — варианты; перекраска по фото варианта — потом»
(линия mesh-color, ADR-0145).

Ключ семейства — по тому, что даёт магазин, и всегда с ролью и габаритами (разные размеры и
разные роли одной серии — разные формы, «Лори» стол 160x90 ≠ журнальный «Лори»):
  * divan.ru (112923): `params['Вариант модели']` («Модерн 140x65», «Тилар») — 94 % товаров;
  * магазины с `params['Ткань']` (114667/114082): имя без ткани и без последнего слова (цвет);
  * остальные: имя без хвостового цвета из словаря; ничего не подошло — товар сам себе семейство.
Ключ консервативен: сомнение — не сливать (лишний меш дешевле склеенных разных форм).

Представитель семейства (`products.mesh_family_rep`) — чей меш считается мешом семейства:
  1) вариант с решением владельца на странице приёмки (его карточка не должна пропасть);
  2) вариант, у которого меш уже есть (самый ранний по времени файла);
  3) вариант, стоящий в опубликованных сетах; 4) наименьший sku.
Остальные варианты в очередь не встают; их готовность и ссылка на меш — от представителя
(`mesh_ready.py`, `mesh_bind.py`). Уже сгенерированные меши вариантов остаются на диске и в
реестре (владелец: «текущие меши не удаляй»).

  ~/venvs/scout/bin/python mesh_family.py --fill      # заполнить mesh_family / mesh_family_rep
  ~/venvs/scout/bin/python mesh_family.py --report    # сводка без записи
  python3 mesh_family.py --selftest
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

COLORS = frozenset('''
белый бежевый серый чёрный черный коричневый синий зелёный зеленый голубой жёлтый желтый розовый
бирюзовый фиолетовый молочный горчичный изумрудный песочный капучино венге дуб орех сонома мокко
шоколад кремовый бордовый мятный пудровый лавандовый антрацит шампань золотой серебряный
натуральный латте терракотовый оливковый графит графитовый тауп агат пепел сталь аква оранж
оранжевый красный бронза хром никель бежевый/белый белый/бежевый светло-бежевый тёмно-серый
темно-серый светло-серый тёмно-синий темно-синий светло-коричневый тёмно-коричневый темно-коричневый
white black grey gray beige brown blue green natural walnut oak red yellow pink ivory cream
'''.split())
SHOP_VARIANT_PARAM = {112923: 'Вариант модели'}


def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '').strip().lower())


def _strip_colors(name: str) -> str:
    """Снять до двух хвостовых слов-цветов (слэш-пары вроде «Молочный/Красный» — одним словом)."""
    words = name.split()
    n = 0
    while words and n < 2 and all(part in COLORS for part in words[-1].lower().split('/')):
        words.pop()
        n += 1
    return ' '.join(words)


def base_name(shop_mid: int, name: str, params: dict | None) -> str:
    params = params or {}
    vp = SHOP_VARIANT_PARAM.get(int(shop_mid or 0))
    if vp and params.get(vp):
        return _norm(params[vp])
    fabric = params.get('Ткань')
    if fabric and fabric in (name or ''):
        rest = _norm(name.replace(fabric, ' '))
        stripped = _strip_colors(rest)
        # цвет не из словаря («аква», «шампань» есть; экзотика — нет) — снимаем последнее слово:
        # у этих магазинов имя всегда кончается цветом (проверено на 114667/114082, 05.09)
        return _norm(stripped if stripped != rest else re.sub(r'\s+\S+\s*$', '', rest) or rest)
    return _norm(_strip_colors(name or ''))


def family_key(shop_mid: int, name: str, params: dict | None, role: str | None, dims: dict | None) -> str:
    d = dims or {}

    def r(v):
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return 0
    return f"{int(shop_mid or 0)}|{_norm(role or '')}|{base_name(shop_mid, name, params)}|{r(d.get('w'))}x{r(d.get('d'))}x{r(d.get('h'))}"


# ---------------------------------------------------------------- одна фотография = одна форма

HAM_SAME = 6   # как в phash.py: ≤6 бит из 128 (dHash+pHash) — та же картинка (пережатие, ресайз)


def hamming_clusters(items: list[tuple[str, str]], limit: int = HAM_SAME, compatible=None) -> list[list[str]]:
    """Кластеры «одна и та же фотография» по перцептивному отпечатку (`product_enrichment.
    perceptual_hash`, 32 hex = dHash 64 + pHash 64, `phash.py`). Магазины отдают одну фотографию
    под несколькими артикулами (tvoydom: ваза Glasar 16×16×17 и 15×15×23 — совпадение 99,7 %),
    и байтовый хеш этого не ловит (разные пережатия). Одна фотография → одна форма → один меш,
    масштаб по габаритам делает расстановка. Вход: [(sku, hex)] ОДНОЙ роли; выход — кластеры
    (в т.ч. одиночные). `compatible(sku_a, sku_b)` — дополнительный фильтр пары: у коробчатой
    мебели (шкафы, тумбы) отпечатки почти одинаковы у РАЗНЫХ моделей, и без него кластеры
    цепочкой склеивали Беррингтон с Сайрисом (проверка 05.09). Чисто, без БД — для selftest."""
    import numpy as np
    good = [(s, h) for s, h in items if h and len(h) == 32]
    if not good:
        return []
    arr = np.array([[int(h[i:i + 2], 16) for i in range(0, 32, 2)] for _s, h in good], dtype=np.uint8)
    n = len(good)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    step = 512
    for a in range(0, n, step):
        x = np.unpackbits(arr[a:a + step, None, :] ^ arr[None, :, :], axis=2).sum(axis=2)
        for i, j in zip(*np.where(x <= limit)):
            gi, gj = a + int(i), int(j)
            if gj > gi and (compatible is None or compatible(good[gi][0], good[gj][0])):
                ri, rj = find(gi), find(gj)
                if ri != rj:
                    parent[rj] = ri
    groups: dict[int, list[str]] = {}
    for i, (s, _h) in enumerate(good):
        groups.setdefault(find(i), []).append(s)
    return list(groups.values())


def _names_alike(a: str, b: str) -> bool:
    """Имена «одной вещи» с точностью до размера/цвета: пересечение слов ≥ половины (Жаккар)
    или одно имя — префикс другого. «ваза glasar с ручкой 16х16х17см» ~ «… 15х15х23см» — да;
    «шкаф-купе беррингтон 2-120x210» ~ «шкаф навесной сайрис 2-98x175» — нет."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return False
    if a.startswith(b) or b.startswith(a):
        return True
    return len(ta & tb) / len(ta | tb) >= 0.5


# ---------------------------------------------------------------- БД

def _db():
    from mesh_queue import db, q
    return db, q


def compute() -> dict:
    """sku → (family, rep). Считает по живой базе, ничего не пишет."""
    db, _q = _db()
    rows = db("""select p.shop_mid||':'||p.external_id, p.shop_mid, coalesce(p.name,''), coalesce(p.params::text,'{}'),
                        coalesce(p.cat_role,''), coalesce(p.w_cm,0), coalesce(p.d_cm,0), coalesce(p.h_cm,0)
                   from products p where p.mesh_required""")
    fam: dict[str, list[str]] = {}
    key_of: dict[str, str] = {}
    role_of: dict[str, str] = {}
    base_of: dict[str, str] = {}
    for r in rows:
        if len(r) != 8:
            continue
        sku, mid, name, params, role, w, d, h = r
        try:
            pr = json.loads(params)
        except ValueError:
            pr = {}
        key = family_key(int(mid), name.replace('\x1f', ' '), pr, role, {'w': w, 'd': d, 'h': h})
        fam.setdefault(key, []).append(sku)
        key_of[sku] = key
        role_of[sku] = role
        base_of[sku] = base_name(int(mid), name.replace('\x1f', ' '), pr)
    # ОДНА ФОТОГРАФИЯ = ОДНА ФОРМА (владелец 05.09, вазы Glasar): кластеры по перцептивному
    # отпечатку внутри роли сливают семейства, найденные по имени. Union-find по ключам семейств.
    parent: dict[str, str] = {k: k for k in fam}

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    by_role: dict[str, list[tuple[str, str]]] = {}
    try:
        hashes = db("""select p.shop_mid||':'||p.external_id, coalesce(p.cat_role,''), e.perceptual_hash
                         from products p join product_enrichment e using (shop_mid, external_id)
                        where p.mesh_required and e.perceptual_hash is not null""")
    except RuntimeError:   # одноразовая база dbtest без обогащения — семейства только по именам
        hashes = []
    for r in hashes:
        if len(r) == 3 and r[0] in key_of:
            by_role.setdefault(r[1], []).append((r[0], r[2]))
    photo_merges = 0
    for role, items in by_role.items():
        for cluster in hamming_clusters(items, compatible=lambda a, b: _names_alike(base_of.get(a, ''), base_of.get(b, ''))):
            keys = {key_of[s] for s in cluster}
            if len(keys) > 1:
                root = find(min(keys))
                for k in keys:
                    rk = find(k)
                    if rk != root:
                        parent[rk] = root
                        photo_merges += 1
    merged: dict[str, list[str]] = {}
    for k, skus in fam.items():
        merged.setdefault(find(k), []).extend(skus)
    fam = merged
    if photo_merges:
        print(f'семейств слито по одной фотографии: {photo_merges}', flush=True)
    decided = {r[0] for r in db("select sku from mesh_rework_requests union select sku from mesh_generations where owner_verdict is not null") if r}
    # Качество меша-кандидата (разбор Codex 05.09): не «самый ранний», а не отвергнутый, с
    # допустимым вердиктом приёмки, по свежему фото, с решённой ориентацией своего файла.
    quality: dict[str, tuple] = {}
    for r in db("""
        select g.sku,
               bool_or(g.owner_verdict is null) as has_clean,
               bool_or(coalesce(g.machine_verdict,'generated') not in ('flat_shape','failed')) as verdict_ok,
               bool_or(pc.source_sha like g.source_sha||'%') as fresh_photo,
               bool_or(o.status in ('auto_resolved','human_resolved')) as oriented,
               min(g.generated_at)
          from mesh_generations g
          left join product_photo_current pc on pc.sku = g.sku
          left join orientation_state o on split_part(o.revision_key,'|',1) = g.sku
               and left(o.resolution->>'glb_sha',16) = g.glb_sha
         group by g.sku"""):
        if len(r) == 6:
            quality[r[0]] = tuple(0 if v == 't' else 1 for v in r[1:5]) + (r[5],)
    # Представитель ЛИПКИЙ (Codex): раз выбранный не меняется от новых мешей других цветов —
    # иначе решения и лимит владельца обнулялись бы сменой представителя.
    sticky = {r[0]: r[1] for r in db("select shop_mid||':'||external_id, mesh_family_rep from products "
                                     "where mesh_family_rep is not null") if len(r) == 2}
    in_sets: set = set()
    try:
        for s in json.load(open(os.path.join(HERE, 'sets3.json'), encoding='utf-8')):
            for it in (s.get('items') or {}).values():
                if it and it.get('mid') is not None:
                    in_sets.add(f"{it['mid']}:{it['eid']}")
    except (OSError, ValueError):
        pass
    out = {}
    for key, skus in fam.items():
        prev = {sticky.get(s) for s in skus} & set(skus)
        if len(prev) == 1:
            rep = prev.pop()            # прежний представитель ещё в семействе — оставляем
        else:
            rep = min(skus, key=lambda s: (0 if s in decided else 1, 0 if s in quality else 1,
                                           *quality.get(s, (1, 1, 1, 1, '')),
                                           0 if s in in_sets else 1, s))
        for s in skus:
            out[s] = (key, rep)
    return out


def fill() -> None:
    db, q = _db()
    m = compute()
    lines = ['begin;', 'create temp table _fam(sku text, fam text, rep text) on commit drop;']
    vals = ','.join(f"({q(s)},{q(k)},{q(r)})" for s, (k, r) in m.items())
    if vals:
        lines.append(f'insert into _fam values {vals};')
    lines.append("""update products p set mesh_family=f.fam, mesh_family_rep=f.rep from _fam f
                     where p.shop_mid||':'||p.external_id=f.sku
                       and (p.mesh_family is distinct from f.fam or p.mesh_family_rep is distinct from f.rep);""")
    lines.append("""update products set mesh_family=null, mesh_family_rep=null
                     where not coalesce(mesh_required,false) and mesh_family is not null;""")
    lines.append('commit;')
    db('\n'.join(lines))
    report(m)


def report(m: dict | None = None) -> None:
    m = m or compute()
    fams: dict[str, int] = {}
    for _s, (k, _r) in m.items():
        fams[k] = fams.get(k, 0) + 1
    multi = {k: n for k, n in fams.items() if n > 1}
    print(f'товаров с мешом по канону: {len(m)}; семейств: {len(fams)}; из них с вариантами: {len(multi)} '
          f'(товаров в них {sum(multi.values())}, вариантов сверх представителя {sum(n - 1 for n in multi.values())})', flush=True)


def _selftest() -> int:
    bad = 0
    k = lambda mid, name, params=None, role='тв-тумба', dims=None: family_key(mid, name, params, role, dims or {'w': 140, 'd': 40, 'h': 65})  # noqa: E731
    a = k(112923, 'ТВ-тумба divan.ru Модерн 140x65 Белый', {'Вариант модели': 'Модерн 140x65'})
    b = k(112923, 'ТВ-тумба divan.ru Модерн 140x65 Графитовый', {'Вариант модели': 'Модерн 140x65'})
    if a != b:
        bad += 1; print('  FAIL divan: цвета одной модели — одно семейство')
    if k(112923, 'Диван divan.ru Маркфул Велюр Бежевый', {'Вариант модели': 'Маркфул'}, role='диван') == \
            k(112923, 'Кресло divan.ru Маркфул Шенилл Бежевый', {'Вариант модели': 'Маркфул'}, role='кресло'):
        bad += 1; print('  FAIL роль в ключе: диван и кресло одной серии — разные формы')
    if k(112923, 'Стол divan.ru Лори', {'Вариант модели': 'Лори'}, dims={'w': 160, 'd': 90, 'h': 75}) == \
            k(112923, 'Стол divan.ru Лори', {'Вариант модели': 'Лори'}, dims={'w': 90, 'd': 60, 'h': 45}):
        bad += 1; print('  FAIL габариты в ключе')
    c = k(114667, 'Диван Босс двухместный Велюр Монолит аква', {'Ткань': 'Велюр Монолит'}, role='диван')
    d = k(114667, 'Диван Босс двухместный Рогожка Мальмо серый', {'Ткань': 'Рогожка Мальмо'}, role='диван')
    if c != d or 'босс двухместный' not in c:
        bad += 1; print(f'  FAIL ткань+цвет сняты: {c} vs {d}')
    if k(114667, 'Диван Босс Мини Велюр Монолит аква', {'Ткань': 'Велюр Монолит'}, role='диван') == c:
        bad += 1; print('  FAIL «Босс Мини» ≠ «Босс двухместный»')
    e = k(99272, 'Стол обеденный TC pure white 107+46x76 см', role='стол')
    if e != k(99272, 'Стол обеденный TC pure white 107+46x76 см', role='стол'):
        bad += 1; print('  FAIL детерминизм')
    if k(99272, 'Стул Клео белый', role='стул') != k(99272, 'Стул Клео чёрный', role='стул'):
        bad += 1; print('  FAIL словарь цветов: хвостовой цвет снят')
    if k(99272, 'Стул Клео', role='стул') == k(99272, 'Стул Клео Люкс', role='стул'):
        bad += 1; print('  FAIL не-цветовое слово не снимается')
    if _strip_colors('Стул Келтон Букле Молочный/Красный') != 'Стул Келтон Букле':
        bad += 1; print('  FAIL слэш-пара цветов')
    # одна фотография: вазы Glasar (реальные отпечатки, 5 бит из 128) — вместе; далёкий — отдельно
    cl = hamming_clusters([('a', '4b4d0d17234b7b0ffae2810f6d2d851f'), ('b', '4b4d0d17234b7b17eae2814f6c2d851f'),
                           ('c', '8f172b2f332b2326bd63f0938327939f'), ('d', '')])
    if not _names_alike('ваза glasar с ручкой 16х16х17см', 'ваза glasar с ручкой 15х15х23см') or \
            _names_alike('шкаф-купе divan.ru беррингтон 2-120x210', 'шкаф навесной divan.ru сайрис 2-98x175'):
        bad += 1; print('  FAIL _names_alike')
    same = hamming_clusters([('x', '4b4d0d17234b7b0ffae2810f6d2d851f'), ('y', '4b4d0d17234b7b17eae2814f6c2d851f')], compatible=lambda a, b: False)
    if sorted(len(c) for c in same) != [1, 1]:
        bad += 1; print('  FAIL предикат пары не применён')
    cl = sorted(sorted(c) for c in cl)
    if cl != [['a', 'b'], ['c']]:
        bad += 1; print(f'  FAIL hamming_clusters: {cl}')
    print(f'mesh_family selftest: случаев 12, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    elif '--fill' in sys.argv:
        fill()
    else:
        report()
