"""ГОРЯЧИЙ СПИСОК МЕШЕЙ ДЛЯ ПРОГРЕВА ПОСТОЯННЫХ ПРОЦЕССОВ ПОДГОТОВКИ (T-20261118-10/5 ❷).

Зачем. Смена товара в заказе «Сделать фото» — почти всегда НОВЫЙ для процесса меш: страница дампера разбирает GLB (≈0,5 с на меш), Python-выгрузка — `load_parts` (≈0,3–0,8 с). Постоянные процессы
(`render_exec.ExportClient`) в простое заранее разбирают меши этого списка; заказ с таким мешем берёт готовый разбор из кэша процесса.

Что в списке. Меши, которые витрина может показать при замене: корзины замены `feeds` и предметы вариантов из `demo-data.json` (тот же файл, что читает сервис кадров и `showcase_assets.build_scenes`).
`renderjobs/_hot/hot.json` (горячий список машины) хранит хеши АССЕТОВ без привязки к товару, поэтому мешей из него не вывести — берём исходник витрины. Только меши, чей GLB УЖЕ лежит в кэше GLB
на диске: прогрев сеть не трогает и кэш GLB не вытесняет (докачка нового меша остаётся делом заказа). Порядок: сперва четыре самые частые роли замены (диван, кровать, кресло, тв-тумба) по четыре ближайших в корзине, затем по кругу по всем ролям; после корзин — предметы вариантов. Чем ближе к началу, тем нужнее; хвост греется, только пока хватает памяти.

Память и уступки заказу — в клиенте (`render_exec.ExportClient._hot_loop`): потолки процессов, ни одного прогрева при ожидающем заказе, по одному мешу под замком.
"""
import json
import os
from typing import Callable

DEMO_DATA = os.environ.get('DEMO_DATA_FILE') or os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
HOT_MAX_N = int(os.environ.get('RENDER_HOT_MAX_N', '40'))
TOP_ROLES, TOP_DEPTH = 4, 4        # самые частые роли замены (по ROLE_FIRST) — по 4 меша вглубь первыми
# порядок ролей по «что чаще меняют» (по порядку корзин `feeds`; роли спальни — с префиксом `bedroom:`); остальные — следом, в порядке файла
ROLE_FIRST = ['диван', 'bedroom:кровать', 'кресло', 'тв-тумба', 'стол обеденный', 'комод', 'bedroom:шкаф', 'bedroom:комод', 'bedroom:тумба прикроватная',
              'стул', 'столик', 'пуф', 'стеллаж', 'торшер', 'витрина']


def mesh_dir() -> str:
    """Каталог кэша GLB (то же правило, что `draft_render._cache_dir`, без импорта тяжёлого модуля)."""
    env = os.environ.get('SCENE3D_CACHE')
    if env:
        return env
    try:
        cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rules', 'dev-tmp.json'), encoding='utf-8'))
        disk = os.path.expanduser(cfg.get('mesh3d_cache_dir') or '')
        if disk and os.path.isdir(os.path.dirname(disk)):
            return disk
    except (OSError, ValueError):
        pass
    return '/tmp/mesh3d-cache'


def have_glb(sid: str, root: str | None = None) -> bool:
    p = os.path.join(root or mesh_dir(), sid + '.glb')
    try:
        return os.path.getsize(p) > 1000
    except OSError:
        return False


def _sid(item) -> str | None:
    it = item or {}
    sk = it.get('sku') if isinstance(it.get('sku'), dict) else it
    s = sk.get('msid') or sk.get('sid') or it.get('msid')
    return str(s) if s else None


def hot_sids(data: dict | None = None, have: Callable[[str], bool] | None = None, max_n: int | None = None) -> list:
    """Меши горячего списка по важности: [sid, …] без повторов, только с GLB в кэше. `data` — разобранный demo-data.json (нет — читаем файл; нет файла — пусто)."""
    if data is None:
        try:
            data = json.load(open(DEMO_DATA, encoding='utf-8'))
        except (OSError, ValueError):
            return []
    have = have or have_glb
    cap = HOT_MAX_N if max_n is None else max_n
    feeds = data.get('feeds') or {}
    roles = [r for r in ROLE_FIRST if r in feeds] + [r for r in feeds if r not in ROLE_FIRST]
    queues = []
    for r in roles:
        q = [s for s in (_sid(i) for i in (feeds.get(r) or [])) if s]
        queues.append(q)
    out, seen = [], set()

    def take(s):
        if s and s not in seen and have(s):
            seen.add(s)
            out.append(s)
    # память процессов вмещает ≈8–11 мешей сверх заказа, поэтому сперва — самые частые роли замены (первые TOP_ROLES) вглубь на TOP_DEPTH мешей, потом по кругу по всем ролям
    top = queues[:TOP_ROLES]
    for depth in range(TOP_DEPTH):
        for q in top:
            if depth < len(q):
                take(q[depth])
    depth = 0
    while len(out) < cap and any(depth < len(q) for q in queues):       # по кругу: у каждой роли по очереди следующий по порядку корзины
        for q in queues:
            if depth < len(q):
                take(q[depth])
                if len(out) >= cap:
                    break
        depth += 1
    for v in data.get('variants') or []:
        for it in v.get('items') or []:
            if len(out) >= cap:
                break
            take(_sid(it))
    return out[:cap]
