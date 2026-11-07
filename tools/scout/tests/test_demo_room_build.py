"""ВИТРИНА КОМНАТ В СБОРКЕ ДЕМО — ЦЕЛИКОМ, БЕЗ БАЗЫ (hall-demo-01 этап 4, T-20261107-05; хвост этапа 3, ведущий 07.11).

Что проверяем: `flat215_demo.room_variants` / `room_showcases` — всё, что сборка пишет в `demo-data.json` от комнат кроме гостиной
(варианты, ленты «<тип>:<роль>», неполные стили, геометрии `rooms_geo`, полосы `slot_band_cm`, фото-каталоги `<тип>_catalog`):
- спальни — ПОБАЙТНО с эталоном, снятым на коде main ДО этапа 4 (запись на свежей заморозке стенда parity: банк спальни, каталог,
  сторож моделей, товары витрины), — перенос сборки на общий цикл комнат ничего не меняет;
- «спальни выкл» — ни варианта, ни ленты, ни геометрии спальни; каталог спальни остаётся (данные b2b-10, как было);
- прихожая — варианты с жёсткими нарушениями 0, метка `no_mesh` у предметов без модели, когда сторож выключен у сборки рядом;
  выключатель у папки витрины — отказ (`HALL_MESH_GATE=0`).

Ответы базы и сети (товар витрины `_sku`, сторож модели, индекс прода, мёртвые фото, каталог) записаны в фикстуру
`fixtures/demo-room-build-<комната>.json.gz` вместе с банком; здесь они проигрываются: ключа нет — тест падает (код пошёл по
другому пути, эталон переснять осознанно).
    ~/venvs/scout/bin/python tools/scout/tests/test_demo_room_build.py
Перезапись (нужна база стенда; эталон спальни — на коде main, файл теста кладётся в выгрузку main):
    REMLAB_DEVDB_NAME=<копия стенда> python test_demo_room_build.py --record bedroom --bank <sets-bedroom.json> \\
        --ref <demo-data.json эталона стенда> --out <фикстура>
"""
import copy
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_demo_room_build')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
FIX = os.path.join(HERE, 'fixtures')
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


import flat215_demo as F  # noqa: E402
import img_alive  # noqa: E402


def canon(x) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True, default=sorted)


def _k(*a) -> str:
    return hashlib.md5(canon(a).encode()).hexdigest()


def _base(role: str) -> str:
    import re
    return re.sub(r'\s+\d+$', '', role or '')


class Tape:
    """Запись/проигрыш ответов внешнего мира сборки комнаты. rec — записывать (настоящие функции), иначе — проигрывать."""

    def __init__(self, rec: bool, data: dict | None = None):
        self.rec, self.d = rec, data or {'sku': {}, 'ok': {}, 'note': {}, 'msid': {}, 'mode': {}, 'idx': {}, 'm2': {}}
        self.miss: list = []

    def get(self, tab: str, key: str, real):
        if self.rec:
            v = real()
            self.d[tab][key] = v
            return v
        if key not in self.d[tab]:
            self.miss.append(f'{tab}:{key}')
            return None
        return self.d[tab][key]

    def install(self):
        """Подменить в сборке: товар витрины, модель сцены, сторож модели (`room_mesh_gate`; у кода main — `bedroom_mesh_gate`),
        индекс прода. Сторож пишется по режиму вызова (обычный и «для метки no_mesh» — разные записи)."""
        real_sku, real_msid, real_idx = F._sku, F._msid, F._mesh_index
        real_gate = getattr(F, 'room_mesh_gate', None) or F.bedroom_mesh_gate
        tape = self

        def sku(items, role):
            it = items.get(role) or items.get(_base(role))
            return tape.get('sku', _k(role, it), lambda: real_sku(items, role))
        F._sku = sku
        F._msid = lambda sid: tape.get('m2', str(sid), lambda: real_msid(sid))
        F._mesh_index = lambda: set(tape.get('idx', 'idx', lambda: sorted(real_idx())) or [])

        def gate(*a, **kw):
            # режим вызова: room_mesh_gate(тип, rows, why, mode); у main — bedroom_mesh_gate() без аргументов
            mode_arg = kw.get('mode', a[3] if len(a) > 3 and hasattr(F, 'room_mesh_gate') else None)
            box = {}

            def real():
                box['g'] = real_gate(*a, **kw)
                return box['g'].mode if box['g'] else None
            mode = tape.get('mode', str(mode_arg), real)
            if mode is None:
                return None
            g = box.get('g')

            def ok(s):
                return tape.get('ok', f"{s.get('sid')}|{s.get('msid')}", lambda: g(s))
            ok.note = lambda s: tape.get('note', str(s.get('sid')), lambda: g.note(s))
            ok.msid = lambda sid: tape.get('msid', str(sid), lambda: g.msid(sid))
            ok.mode = mode
            return ok
        if hasattr(F, 'room_mesh_gate'):
            F.room_mesh_gate = gate
        else:                                   # код main до этапа 4: сборка зовёт `bedroom_mesh_gate()`
            F.bedroom_mesh_gate = gate


def used_urls(bank: list, cat: dict) -> set:
    out = set()
    for r in bank:
        for it in (r.get('items') or {}).values():
            out.add((it or {}).get('img'))
        for alts in (r.get('alternates') or {}).values():
            out.update((a or {}).get('img') for a in alts or [])
    for rows in ((cat or {}).get('roles') or {}).values():
        out.update(p.get('img') for p in rows)
    return {u for u in out if u}


def run_room(room_type: str, fx: dict, tape: Tape, rooms_enabled: list, out_dir: str | None = None) -> dict:
    """Сборка комнаты типа по фикстуре → то, что идёт в `demo-data.json`."""
    tmp = tempfile.mkdtemp(prefix='demo-room-build-')
    bank = os.path.join(tmp, f'sets-{room_type}.json')
    with open(bank, 'w', encoding='utf-8') as fh:
        json.dump(fx['bank'], fh, ensure_ascii=False)
    os.environ[F.room_env(room_type, 'SETS') if hasattr(F, 'room_env') else 'BEDROOM_SETS'] = bank
    F.OUT = out_dir or os.path.join(tmp, 'side-demo')
    dead = set(fx['dead'])
    img_alive.dead_room_photos = lambda: dead
    variants = [{'id': f'living-{i}', 'room_id': 'living', 'style': s} for i, s in enumerate(fx['styles'])]
    feeds: dict = {'диван': ['гостиная']}
    incomplete: list = []
    apt = F.demo_apartment()
    tape.install()
    fn = getattr(F, 'room_variants', None)
    if fn:
        geos, bands = fn(room_type, apt, {'rooms_enabled': rooms_enabled}, variants, feeds, incomplete, fx['room'], fx['cat'])
    else:
        geos, bands = F.bedroom_variants(apt, {'rooms_enabled': rooms_enabled}, variants, feeds, incomplete, fx['room'], fx['cat'])
    return {'variants': variants[len(fx['styles']):], 'feeds': {k: v for k, v in feeds.items() if k != 'диван'},
            'incomplete': incomplete, 'geos': geos, 'bands': bands}


LOCAL_IMG = re.compile(r'^img/[0-9a-f]{16}\.jpg$')


def variant_photos(variants: list) -> list:
    """(вариант, роль, адрес фото) — предметы и декор каждого варианта: то, что покупатель видит строкой списка и значком плана."""
    return [(v.get('id'), it.get('role'), (it.get('sku') or {}).get('img')) for v in variants
            for it in (v.get('items') or []) + (v.get('decor') or [])]


def _jpeg() -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new('RGB', (640, 480), (200, 190, 170)).save(b, 'JPEG')
    return b.getvalue()


def photos(variants: list, dead: set, catalogs: dict, feeds: dict) -> None:
    """Фото товаров вариантов спальни и прихожей. Сеть в CI не ходим: «адрес отвечает» — запись живости фото (`img_alive`) в
    фикстуре, «лежит в медиа» — настоящий шаг фото сборки (`cache_images`) с подменённой загрузкой: после него у предмета адрес
    `img/<id>.jpg`, и плитка с крупной копией лежат в папке сборки. Магазин не отдал фото — у предмета пусто («нет фото» на
    странице), а не мёртвая ссылка магазина (рваная иконка у покупателя)."""
    import urllib.request
    rows = variant_photos(variants)
    check(f'фото: у каждого предмета вариантов спальни и прихожей адрес фото есть ({len(rows)} строк)', rows and all(u for *_, u in rows))
    check('фото: ни один адрес не из мёртвых по записи живости', not [r for r in rows if r[2] in dead])
    refused = rows[0][2]                                      # один адрес магазин не отдаёт ни разу (403 через раз — тут всегда)
    keep = (F.OUT, F.time, F.IMG_FALLBACK, urllib.request.urlopen)
    tmp = tempfile.mkdtemp(prefix='demo-room-photos-')
    jpg = _jpeg()

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else req
        if url == refused:
            raise OSError('403')
        return io.BytesIO(jpg)
    try:
        F.OUT, F.IMG_FALLBACK = tmp, ''                       # без подхвата с прода: только свой шаг
        F.time = type('T', (), {'sleep': staticmethod(lambda s: None), 'time': staticmethod(lambda: 0.0)})
        urllib.request.urlopen = urlopen
        data = F.cache_images(copy.deepcopy({'variants': variants, 'feeds': feeds, **catalogs}))
    finally:
        F.OUT, F.time, F.IMG_FALLBACK, urllib.request.urlopen = keep
    after = variant_photos(data['variants'])
    gone = [r for r in after if r[2] is None]
    local = [r for r in after if r[2] is not None]
    check(f'фото: после шага фото у предметов — свои копии img/<id>.jpg ({len(local)}), адресов магазина не осталось',
          local and all(LOCAL_IMG.match(u) for *_, u in local))
    check('фото: плитка и крупная копия каждого предмета лежат в папке сборки и открываются как JPEG',
          all(_is_jpeg(os.path.join(tmp, u)) and _is_jpeg(os.path.join(tmp, u[:-4] + '-l.jpg')) for *_, u in local))
    n_ref = sum(1 for *_, u in rows if u == refused)
    check(f'фото: магазин не отдал фото — у предмета пусто («нет фото»), не ссылка магазина ({len(gone)} = {n_ref})',
          len(gone) == n_ref and all(r[:2] in {x[:2] for x in rows if x[2] == refused} for r in gone))


def _is_jpeg(path: str) -> bool:
    from PIL import Image
    try:
        with Image.open(path) as im:
            return im.format == 'JPEG' and im.size[0] > 0
    except Exception:
        return False


def check_out(folder: str) -> int:
    """Готовая папка сборки (`--out <папка>`, где лежит `demo-data.json`): фото каждого предмета каждого варианта (все комнаты) —
    свой файл в `img/` (плитка, открывается) или адрес, что отвечает 200 картинкой. Для /test/ и витрины перед публикацией."""
    data = json.load(open(os.path.join(folder, 'demo-data.json'), encoding='utf-8'))
    rows = variant_photos(data.get('variants') or [])
    bad = []
    for vid, role, u in rows:
        if not u:
            bad.append((vid, role, 'нет адреса'))
        elif re.match(r'^https?:|^//', u):
            code, ctype, raw = F._http_get(('https:' + u) if u.startswith('//') else u)
            if code != 200 or not ctype.lower().startswith('image/'):
                bad.append((vid, role, f'{code} {ctype} {u[:80]}'))
        elif not _is_jpeg(os.path.join(folder, u)):
            bad.append((vid, role, f'нет файла {u}'))
    for b in bad:
        print('  ', *b)
    check(f'фото папки {folder}: у всех {len(rows)} строк вариантов фото на месте ({len({r[0] for r in rows})} вариантов)', not bad)
    return 1 if bad else 0


def load_fx(room_type: str) -> dict:
    with gzip.open(os.path.join(FIX, f'demo-room-build-{room_type}.json.gz'), 'rt', encoding='utf-8') as fh:
        return json.load(fh)


def record(argv: list) -> int:
    room_type = argv[argv.index('--record') + 1]
    import demo_room as DR
    bank = DR.load_bank(argv[argv.index('--bank') + 1])
    ref = json.load(open(argv[argv.index('--ref') + 1], encoding='utf-8'))
    out = argv[argv.index('--out') + 1]
    styles = [v['style'] for v in ref['variants'] if (v.get('room_id') or 'living') == 'living']
    room = {k: ref['room'][k] for k in ('w', 'd', 'window_view', 'height_cm') if k in ref['room']}
    cat = F.room_photo_catalog(room_type) if hasattr(F, 'room_photo_catalog') else F.bedroom_catalog()
    dead = sorted(img_alive.dead_room_photos() & used_urls(bank, cat))
    fx = {'room_type': room_type, 'bank': bank, 'cat': cat, 'dead': dead, 'styles': styles, 'room': room,
          'rooms_enabled': [r['id'] for r in F.demo_apartment()['rooms'] if r.get('kind') == room_type]}
    tape = Tape(True)
    res = run_room(room_type, fx, tape, fx['rooms_enabled'], out_dir=os.environ.get('RECORD_OUT_DIR'))
    fx['tape'] = tape.d
    fx['out'] = json.loads(canon(res))
    # порядок ключей банка — данные (порядок предметов записи → порядок списка варианта): без сортировки
    with gzip.open(out, 'wt', encoding='utf-8') as fh:
        json.dump(fx, fh, ensure_ascii=False)
    print(f'записано {out}: вариантов {len(res["variants"])}, лент {len(res["feeds"])}, неполных {len(res["incomplete"])}, '
          f'товаров витрины {len(tape.d["sku"])}, сторож {len(tape.d["ok"])}')
    return 0


def main() -> int:
    # ВСЕ ВРЕМЕННЫЕ ПАПКИ ТЕСТА — В ОДНОЙ, И ОНА УБИРАЕТСЯ (T-20261107-05/2): прежде каждый прогон оставлял в /tmp по ~2–5 МБ
    # (банк, папка сборки, фото), за день прогонов набралась квота /tmp DEV — и безголовый браузер (он держит там общую память)
    # стал отдавать фото с ERR_INSUFFICIENT_RESOURCES
    with tempfile.TemporaryDirectory(prefix='demo-room-build-') as root:
        tempfile.tempdir = root
        try:
            return _main()
        finally:
            tempfile.tempdir = None


def _main() -> int:
    if '--record' in sys.argv:
        return record(sys.argv)
    if '--out' in sys.argv:
        return check_out(sys.argv[sys.argv.index('--out') + 1])
    saved = {k: getattr(F, k) for k in ('_sku', '_msid', '_mesh_index', 'bedroom_mesh_gate', 'room_mesh_gate', 'OUT',
                                        'room_photo_catalog')}
    dead_saved = img_alive.dead_room_photos

    def restore():
        for k, v in saved.items():
            setattr(F, k, v)
        img_alive.dead_room_photos = dead_saved
        for k in ('BEDROOM_SETS', 'HALL_SETS', 'HALL_MESH_GATE', 'FLAT215_FEED_ANY_MESH'):
            os.environ.pop(k, None)

    # --- спальни: побайтно с эталоном main
    B = load_fx('bedroom')
    tape = Tape(False, copy.deepcopy(B['tape']))
    got = json.loads(canon(run_room('bedroom', B, tape, B['rooms_enabled'])))
    restore()
    check(f'спальни: ответы базы из записи — все на месте (путь кода тот же; промахов {len(tape.miss)})', not tape.miss)
    for part in ('variants', 'feeds', 'incomplete', 'geos', 'bands'):
        check(f'спальни: {part} — побайтно с эталоном main до этапа 4 ({len(B["out"][part])})', canon(got[part]) == canon(B['out'][part]))
    check('спальни: в эталоне есть что сравнивать — варианты обеих спален и ленты',
          {v['room_id'] for v in B['out']['variants']} == {'bedroom-1', 'bedroom-2'} and len(B['out']['feeds']) >= 5)

    # --- прихожая у сборки рядом: сторож выключен, метка no_mesh
    H = load_fx('hall')
    os.environ['HALL_MESH_GATE'] = '0'
    os.environ['FLAT215_FEED_ANY_MESH'] = '1'
    tape = Tape(False, copy.deepcopy(H['tape']))
    hall = json.loads(canon(run_room('hall', H, tape, ['hall'])))
    restore()
    import demo_hall as DH
    import demo_room as DR
    vs = hall['variants']
    check(f'прихожая: ответы базы из записи — все на месте (промахов {len(tape.miss)})', not tape.miss)
    check(f'прихожая: вариантов столько же, сколько в записи ({len(vs)}), не меньше 5', len(vs) == len(H['out']['variants']) >= 5)
    check('прихожая: побайтно с записью (варианты, ленты, полосы, геометрия)',
          all(canon(hall[p]) == canon(H['out'][p]) for p in ('variants', 'feeds', 'incomplete', 'geos', 'bands')))
    # своя расстановка у каждого стиля — своя пара ракурсов (T-20261107-05/4, `demo-cams.mjs`): метка у прихожей (правила одной
    # расстановки у типа нет), у спален (расстановка общая) — нет
    check('ракурсы: у прихожей метка cams_own, у спален — нет',
          hall['geos']['hall'].get('cams_own') is True and not any(g.get('cams_own') for g in got['geos'].values()))
    hard = {v['id']: DR.hard_codes(DH.SPEC, {'_room': hall['geos']['hall'], **{i['role']: dict(i, z=i['y']) for i in v['items']}},
                                   None) for v in vs}
    check(f'прихожая: жёстких нарушений 0 у всех вариантов ({", ".join(hard)})', all(not x for x in hard.values()))
    check('прихожая: у каждого варианта есть хранение (шкаф-купе, прихожая или вешалка)',
          all({'шкаф-купе', 'прихожая', 'вешалка'} & {DR.base_role(i['role']) for i in v['items']} for v in vs))
    marks = [i for v in vs for i in v['items'] if i.get('no_mesh')]
    check(f'прихожая: предметы без модели — с меткой no_mesh и причиной ({len(marks)})',
          marks and all(isinstance(i['no_mesh'], str) and i['no_mesh'] for i in marks))
    check('прихожая: у зеркала метки нет (плоскость по фото, модель не нужна) и оно висит (elev > 0)',
          all(not i.get('no_mesh') and i.get('elev', 0) > 0 for v in vs for i in v['items'] if i['role'] == 'зеркало'))
    check('прихожая: ленты — под ключом «hall:<роль>», строки без модели — с меткой',
          hall['feeds'] and all(k.startswith('hall:') for k in hall['feeds'])
          and any(r.get('no_mesh') for rows in hall['feeds'].values() for r in rows))

    # --- стратегия плоскости в предметах (T-20261107-05/3): мост рисует зеркало на стене только по полю `strategy`
    #     (`fromDemo.ts:isWallPlane` — procedural_plane и высота больше глубины); канон — `asset_strategy`, один для всех путей
    import asset_strategy as AS
    sv = copy.deepcopy({'variants': B['out']['variants'] + vs})
    n_plane = F.annotate_strategy(sv)
    its = [i for v in sv['variants'] for i in v['items']]
    wall = lambda i: i.get('strategy') == 'procedural_plane' and i.get('w') and i.get('d') and i.get('h') and i['h'] > i['d']  # noqa: E731
    mirrors = [i for i in its if DR.base_role(i['role']) == 'зеркало']
    check(f'стратегия: у каждого зеркала прихожей — procedural_plane и оно стоймя, мост рисует плоскость на стене ({len(mirrors)})',
          len(mirrors) == len(vs) and all(wall(i) for i in mirrors))
    check(f'стратегия: поле только у ролей procedural_plane канона, у мебели с моделью данных не прибавилось ({n_plane})',
          n_plane == sum(1 for i in its if i.get('strategy'))
          and all(AS.strategy(i['role']) == 'procedural_plane' for i in its if i.get('strategy')))
    check('стратегия: ковёр спальни с полем остаётся на полу (не стена), мебель плоскостью не стала',
          not [i for i in its if wall(i) and DR.base_role(i['role']) not in ('зеркало', 'картина')])

    # --- фото товаров вариантов (T-20261107-05/2): есть у каждого, живое, после шага фото лежит в своей медиа
    photos(B['out']['variants'] + vs, set(B['dead']) | set(H['dead']), {'bedroom_catalog': B['cat'], 'hall_catalog': H['cat']},
           hall['feeds'])

    # --- таблица лёгких копий у сборки рядом: копия витрины, когда своей нет; у витрины — ничего
    keep = (F.OUT, F._BP.DEMO_OUT_DEFAULT)
    try:
        shop, side = tempfile.mkdtemp(), tempfile.mkdtemp()
        json.dump({'meshes': {'m1': {'size': 1}}}, open(os.path.join(shop, 'rt-meshes.json'), 'w'))
        F._BP.DEMO_OUT_DEFAULT, F.OUT = shop, side
        first, again = F.rt_table_side(), F.rt_table_side()
        F.OUT = shop
        own = F.rt_table_side()
    finally:
        F.OUT, F._BP.DEMO_OUT_DEFAULT = keep
    check(f'сборка рядом: таблица лёгких копий — копия витрины, второй раз своя, у витрины не трогаем ({first}/{again}/{own or "—"})',
          (first, again, own) == ('копия', 'своя', '')
          and json.load(open(os.path.join(side, 'rt-meshes.json')))['meshes'] == {'m1': {'size': 1}})

    # --- выключатель сторожа у папки витрины — отказ
    os.environ['HALL_MESH_GATE'] = '0'
    F.OUT = F._BP.DEMO_OUT_DEFAULT
    try:
        F.room_mesh_gate('hall')
        check('HALL_MESH_GATE=0 у папки витрины — отказ', False)
    except SystemExit as e:
        check('HALL_MESH_GATE=0 у папки витрины — отказ (только сборка рядом)', 'FLAT215_DEMO_OUT' in str(e))
    restore()
    check('у спальни выключатель — откат, у папки витрины он разрешён (как было)', F.showcase('bedroom').GATE_OFF_MAIN is True)

    # --- «спальни выкл» и «только прихожая» на уровне всех комнат витрины
    def showcases(enabled: list, fxs: dict) -> tuple:
        F.room_photo_catalog = lambda rt: copy.deepcopy(fxs[rt]['cat'])
        tapes = {rt: Tape(False, copy.deepcopy(fx['tape'])) for rt, fx in fxs.items()}
        variants = [{'id': f'living-{i}', 'room_id': 'living', 'style': s} for i, s in enumerate(B['styles'])]
        feeds = {'диван': ['гостиная']}
        inc: list = []
        real_rv = F.room_variants

        def rv(rt, *a):
            fx = fxs[rt]
            tmp = tempfile.mkdtemp(prefix='demo-room-build-')
            path = os.path.join(tmp, f'sets-{rt}.json')
            json.dump(fx['bank'], open(path, 'w', encoding='utf-8'), ensure_ascii=False)
            os.environ[F.room_env(rt, 'SETS')] = path
            img_alive.dead_room_photos = lambda: set(fx['dead'])
            F.OUT = os.path.join(tmp, 'side-demo')
            tapes[rt].install()
            return real_rv(rt, *a)
        F.room_variants = rv
        try:
            g, b, c = F.room_showcases(F.demo_apartment(), {'rooms_enabled': enabled} if enabled else {}, variants, feeds, inc,
                                       B['room'])
        finally:
            F.room_variants = real_rv
            restore()
        return g, b, c, variants[len(B['styles']):], {k: v for k, v in feeds.items() if k != 'диван'}, inc
    g, b, c, v, fd, inc = showcases([], {'bedroom': B, 'hall': H})
    check('спальни выкл: ни варианта, ни ленты, ни геометрии, ни полосы комнат; гостиная не тронута',
          (g, b, v, fd, inc) == ({}, {}, [], {}, []))
    check('спальни выкл: в данных только каталог спальни (как было), каталога прихожей нет', list(c) == ['bedroom_catalog'])
    os.environ['HALL_MESH_GATE'] = '0'
    g, b, c, v, fd, inc = showcases(['hall'], {'bedroom': B, 'hall': H})
    check('только прихожая: варианты и ленты — только прихожей, каталоги спальни и прихожей',
          v and {x['room_id'] for x in v} == {'hall'} and all(k.startswith('hall:') for k in fd)
          and list(c) == ['bedroom_catalog', 'hall_catalog'] and list(g) == ['hall'])
    g, b, c, v, fd, inc = showcases(['bedroom-1', 'bedroom-2'], {'bedroom': B, 'hall': H})
    check('только спальни: те же варианты, что эталон main, каталога прихожей нет',
          canon(v) == canon(B['out']['variants']) and list(c) == ['bedroom_catalog'])
    print('итог:', 'OK' if not fails else f'{fails} FAIL')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
