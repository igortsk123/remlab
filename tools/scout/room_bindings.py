"""Привязка товар → меш для комнат (room-pipeline-01 В-1а, T-20261105-45; разбор Codex
`.memory_bank/_intake/codex/room-bind-2026-11-05-answer.md`).

ЗАЧЕМ. Меши спальни делает `room_mesh_jobs.py`, а привязку к товару пишет только `mesh_bind` — и только в `products`. У товаров
из `room_catalog` привязки нет (781 «сирота» на 05.11, T-42). Миграцию БД без владельца не делаем, поэтому привязка — генерируемый
файл-снимок поверх фактов БД и диска (БД — истина о поколениях, ревизиях, ориентации; снимок — материализованный вывод из них):

    ~/scout-scenes/catalog-assets/v1/bindings-<content_sha16>.json   — неизменяемый снимок (старые не трогаем — откат)
    ~/scout-scenes/catalog-assets/v1/current.json                    — копия текущего, атомарная замена

КЛЮЧИ. Товар — (mid, eid) раздельно (offer_id «mid:eid» не режем по «:»), ассет — полный sha256 `model.glb`; ревизия и попытка —
существующие `revision_key` / `generation_key`. Комната и роль в ключ не входят (`seen_in` — справка): товар в двух комнатах —
одна привязка. Семья — ссылкой: вариант → `family_id` → представитель → его ассет (только `products.mesh_family_rep`;
`CatalogItem.family` — семья СТИЛЯ, не мешей; своей семейной логики для товаров только из `room_catalog` нет — прямая привязка).

ГОТОВНОСТЬ (Codex п.1–8, правила — `rules/catalog-bindings.json`, версия политики в снимке):
  local_3d — ревизия ТЕКУЩЕГО фото (product_photo_current; без хеша — по адресу, если разрешено), её `current_generation_key`
             (не самый свежий файл по mtime), статус и вердикты чисты, файл есть, цел и его полный sha совпадает с БД,
             ориентация решена для ЭТОГО sha по текущему контракту и не unusable («симметрична по роли» — только у ненаправленной
             роли), паспорт генерации (manifest input.dims_cm) ≈ габарит каталога (политика v1: 3 % или 2 см);
  solver   — габарит каталога есть, у товара из room_catalog — footprint_ok;
  appearance — свой меш; у варианта семьи — цвет обоих известен и в одной группе И замер видимого цвета (модель × подкраска)
             не дальше порога от фото товара (`mesh_color_check`, таблица ночного замера, `measured_colour`; свой меш с
             расхождением — только предупреждение `mesh_color_mismatch`);
  published_3d — mesh_id в индексе прода и размер файла там = привязанному (только чтение; публикация — В-1б).
  status = ready, когда solver ∧ local_3d ∧ appearance; иначе blocked со списком причин.

ХРАНЕНИЕ (владелец 05.11 TG 126 — «можешь править базу»): таблица DEV-базы `offer_asset_binding` (миграция
`016-offer-asset-binding.sql`), полная замена одной транзакцией; тот же снимок файлом рядом — откат и разбор. Читает
`catalog_items.items(..., with_assets=True)` одним SELECT (`load_db`).

    ~/venvs/scout/bin/python room_bindings.py --build [--dry] [--out ДИР] [--no-ssh] [--prod URL|ФАЙЛ] [--report-out ДИР]
                                                     # --dry — только файл, таблицу не трогать
    python room_bindings.py --report [СНИМОК]      # сводка по комнатам и причинам
    python room_bindings.py --selftest             # правила на подставных данных: без базы, диска мешей и сети
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
POLICY = os.path.join(HERE, 'rules', 'catalog-bindings.json')
SCHEMA = os.path.join(HERE, 'rules', 'catalog-bindings.schema.json')
OUT_DIR = os.environ.get('CATALOG_ASSETS_DIR') or os.path.expanduser('~/scout-scenes/catalog-assets/v1')
CURRENT = 'current.json'
SCHEMA_VERSION = 1
PROD_IDX = 'https://remont-lab.online/test/mesh-pilot10/mesh-index.json'   # = mesh_publish.PROD_IDX
PROD_HOST, PROD_DIR = 'root@89.167.127.0', '/opt/remlab/test/mesh-pilot10'   # = mesh_publish.HOST / PROD_DIR (чтение)


def policy(path: str = POLICY) -> dict:
    return json.load(open(path, encoding='utf-8'))


# ---------------------------------------------------------------- чистые правила
def verdict_ok(v, pol: dict) -> bool:
    """Машинный вердикт поколения годен: null (не судили) при machine_verdict_null_ok или ступень лестницы не ниже
    machine_verdict_min (лестница — ступени mesh_gate_pbr.status снизу вверх; выше — значит прошёл все нижние)."""
    g = pol['generation']
    if v is None:
        return bool(g['machine_verdict_null_ok'])
    lad = g['machine_verdict_ladder']
    return v in lad and lad.index(v) >= lad.index(g['machine_verdict_min'])


def within(m, c, pol: dict) -> bool:
    p = pol['passport']
    return abs(float(m) - float(c)) <= max(p['rel'] * float(m), p['abs_cm'])


def passport_check(gen_dims: dict | None, cat_dims_list: list, pol: dict, prefix: str = 'passport') -> list:
    """Паспорт генерации против КАЖДОГО габарита каталога (товар в двух источниках — оба). → причины ([] — сходится)."""
    if not gen_dims:
        return [f'{prefix}_missing']
    out = []
    for cd in cat_dims_list:
        for k in pol['passport']['keys']:
            m, c = gen_dims.get(k), cd.get(k)
            if m is None and c is None:
                continue
            if m is None or c is None:
                why = f'{prefix}_dim_missing:{k}'
            elif not within(m, c, pol):
                why = f'{prefix}_mismatch:{k}'
            else:
                continue
            if why not in out:
                out.append(why)
    return out


def plan_depth(gen_dims: dict | None, cat_dims_list: list, name: str | None, pol: dict) -> tuple:
    """Паспорт генерации без глубины у КРУГЛОГО или КВАДРАТНОГО в плане предмета → глубина = диаметру/ширине паспорта
    (T-20261107-11/2). Генерация круглого столика получает в manifest только Ш и В (d=None), и паспорт навсегда
    `passport_dim_missing:d` (347 прямых и ~400 семейных привязок 07.11). Круглый — слово из `round_words` в названии;
    квадратный — у КАЖДОГО габарита каталога |w − d| ≤ `square_tol_cm`. Иначе (или d уже есть) — паспорт как был.
    → (паспорт, взята ли глубина из плана)."""
    p = (pol.get('passport') or {}).get('plan_depth') or {}
    if not p.get('enabled') or not gen_dims or gen_dims.get('d') is not None:
        return gen_dims, False
    side = gen_dims.get('dia') if gen_dims.get('dia') is not None else gen_dims.get('w')
    if side is None:
        return gen_dims, False
    nm = (name or '').lower()
    round_ = any(wd in nm for wd in p.get('round_words') or ())
    square = bool(cat_dims_list) and all(cd.get('w') is not None and cd.get('d') is not None
                                         and abs(float(cd['w']) - float(cd['d'])) <= float(p.get('square_tol_cm', 0))
                                         for cd in cat_dims_list)
    if not (round_ or square):
        return gen_dims, False
    return dict(gen_dims, d=side), True


def copied_d(mid, name: str, params: dict, role: str, cat_dims_list: list, pol: dict) -> bool:
    """Глубина в каталоге — КОПИЯ ширины (T-20261107-25/7, Codex «узкий К2»): магазин и роль из `passport.d_by_mesh`, разборщик
    взял w ровно из `w_key` и d ровно из `d_key` (значения фида, не составные и не из названия), более сильного ключа глубины
    в карточке нет, и w == d у разбора и у КАЖДОГО габарита каталога. У стульев divan.ru «Размеры: Ширина габаритная» = «Длине»
    (сайт показывает только «Ширина 49 см, Высота 82 см») — глубины фид не знает, а каталог пишет квадрат."""
    P = (pol.get('passport') or {}).get('d_by_mesh') or {}
    if not P.get('enabled') or int(mid) not in set(P.get('shops') or ()) or role not in set(P.get('roles') or ()):
        return False
    import dim_resolver as DR
    d_keys = DR.dim_keys_for(int(mid), role).get('d') or []
    if P['d_key'] not in d_keys or any(params.get(k) for k in d_keys[:d_keys.index(P['d_key'])]):
        return False                       # сильнее ключа глубины в карточке есть — глубина измерена
    dims, ev, _ = DR.resolve(int(mid), name, params, role)
    ew, ed = ev.get('w') or {}, ev.get('d') or {}
    if (ew.get('param_key'), ed.get('param_key')) != (P['w_key'], P['d_key']) \
            or ew.get('value_source') != 'param' or ed.get('value_source') != 'param':
        return False
    w, d = dims.get('w'), dims.get('d')
    if w is None or d is None or abs(w - d) > 0.01 or not cat_dims_list:
        return False
    return all(cd.get('w') is not None and cd.get('d') is not None and abs(float(cd['w']) - w) <= 0.01
               and abs(float(cd['d']) - d) <= 0.01 for cd in cat_dims_list)


def d_by_mesh(path: str, full_sha: str, gen_d, cat_dims_list: list, F, pol: dict) -> dict:
    """Глубину паспорта сверить с ОТНОШЕНИЕМ сторон своего меша (T-20261107-25/7), когда глубина каталога — копия ширины.
    Мерка — `mesh_dims.raw_measure` (сырой фрейм, Y вверх, след — стороны минимального прямоугольника; подложка снята),
    кэш по (версия замера, полный sha glb) → только отношение сторон; сантиметры — от ТЕКУЩЕЙ ширины каталога. Сторона
    ширины — та, что ближе к ширине каталога при масштабе по высоте; масштабы по ширине и высоте расходятся больше
    `scale_tol` — не выводим. Ошибка одна и симметричная: |паспорт − меш| / min(паспорт, меш) ≤ `tol`.
    → {ok, why, passport_d, mesh_d, err, measurement}; why ∈ no_passport_d | mask | measure | slab | scale | err."""
    P = pol['passport']['d_by_mesh']
    out = {'ok': False, 'why': '', 'passport_d': gen_d, 'mesh_d': None, 'err': None, 'measurement': None}
    if gen_d is None:
        return dict(out, why='no_passport_d')
    m = F.aspect(path, full_sha)
    if m and m.get('mask'):
        return dict(out, why='mask', measurement=m.get('version'))
    if not m or not m.get('h') or not m.get('long') or not m.get('short'):
        return dict(out, why='measure', measurement=(m or {}).get('version'))
    out['measurement'] = m.get('version')
    if m.get('slab'):
        return dict(out, why='slab')
    worst = None
    for cd in cat_dims_list:
        w, h = float(cd['w']), float(cd['h'])
        s_h = h / float(m['h'])
        a, b = float(m['long']), float(m['short'])
        w_side, d_side = (a, b) if abs(a * s_h - w) <= abs(b * s_h - w) else (b, a)
        if abs((w / w_side) / s_h - 1) > float(P['scale_tol']):
            return dict(out, why='scale')
        dm = w * d_side / w_side
        err = abs(float(gen_d) - dm) / min(float(gen_d), dm)
        if worst is None or err > worst[1]:
            worst = (dm, err)
    out.update(mesh_d=round(worst[0], 1), err=round(worst[1], 3))
    return dict(out, ok=worst[1] <= float(P['tol']), why='' if worst[1] <= float(P['tol']) else 'err')


def effective_dims(dbm: dict, aid: str, cat_dims_list: list, pol: dict) -> dict | None:
    """Глубина «для сцены» (T-20261107-25/9, план dims-effective-01, Codex 07.11 п.5): К2 подтвердил глубину паспорта отношением
    сторон своего меша — сцена (солвер, след, 3D, фото) берёт её, а не квадрат каталога; каталог, банк, цены и фильтры — как
    были. Пишется только при `d_by_mesh.ok` и `passport.d_by_mesh.effective`; `catalog_w` — ширина каталога на момент снимка:
    читатель (`effective_d`) сверяет с текущей и при расхождении берёт каталог (снимок устарел)."""
    P = (pol.get('passport') or {}).get('d_by_mesh') or {}
    if not dbm or not dbm.get('ok') or not P.get('effective') or not cat_dims_list:
        return None
    return {'d': dbm['passport_d'], 'source': 'passport_by_mesh', 'mesh_d': dbm['mesh_d'], 'err': dbm['err'],
            'asset_id': aid, 'measurement': dbm['measurement'], 'catalog_w': cat_dims_list[0].get('w')}


def effective_d(row: dict | None, scene_msid: str | None, cat_w, cat_d, pol: dict | None = None):
    """Читатель глубины «для сцены» (T-20261107-25/9): строка привязки → глубина паспорта по мешу или None (тогда — каталог).
    Только если ВСЁ сразу: политика включена (`passport.d_by_mesh.effective`); строка ready и своя модель (не `via_family`);
    сцена грузит ровно модель привязки (`mesh_id` == `scene_msid`); у строки есть `passport.effective_dims`; ширина каталога
    сейчас та же (±2 см), а глубина каталога по-прежнему копия ширины — магазин починил фид или поменял товар → каталог."""
    P = ((pol if pol is not None else policy()).get('passport') or {}).get('d_by_mesh') or {}
    r = row or {}
    e = (r.get('passport') or {}).get('effective_dims') or {}
    if not P.get('effective') or not e or r.get('status') != 'ready' or r.get('via_family'):
        return None
    if not scene_msid or not r.get('mesh_id') or str(r['mesh_id']).replace(':', '_', 1) != scene_msid \
            or e.get('d') is None or e.get('catalog_w') is None:
        return None
    try:
        w, d = float(cat_w), float(cat_d)
    except (TypeError, ValueError):
        return None
    if abs(w - float(e['catalog_w'])) > 2 or abs(w - d) > 0.01:
        return None
    return e['d']


def dims_hash(dims_list: list, keys: list) -> str:
    return hashlib.sha256(json.dumps([[d.get(k) for k in keys] for d in dims_list], sort_keys=True).encode()).hexdigest()[:16]


def pick_revision(revs: list, photo_ok) -> tuple:
    """Ревизия текущего фото: среди ревизий товара те, чьё фото — текущее (`photo_ok(rev)`); при нескольких (конвейеры) —
    сперва с годным статусом, затем старшая версия конвейера и ключ. → (ревизия | None, есть ли ревизии вообще)."""
    match = [r for r in revs if photo_ok(r)]
    if not match:
        return None, bool(revs)
    return max(match, key=lambda r: (r['status'] in ('accepted', 'generated'), r['pipeline'], r['revision_key'])), True


def glb_header_ok(head: bytes, size: int) -> bool:
    """GLB: магия glTF, версия 2, длина в заголовке = размер файла (обрезанный файл — нет)."""
    return len(head) >= 12 and head[:4] == b'glTF' and int.from_bytes(head[4:8], 'little') == 2 \
        and int.from_bytes(head[8:12], 'little') == size


class Facts:
    """Факты для правил — словари; сборка их наполняет из БД/диска, селфтест — руками.
    revs {sku: [rev]} · gens {generation_key: gen} · manifest(gen) → dict · glb(gen) → (полный sha | None, причина | None)
    orient {(sku, glb_sha16): row} · ppc {sku: (url, sha64)} · products {sku: {mesh_status, family, rep}} · two_reps {family}
    colour {sku: цвет} · prod {mesh_id: размер | None} | None · contract · directed(role, name) → bool."""

    def __init__(self, **kw):
        self.revs, self.gens, self.orient, self.ppc, self.products = {}, {}, {}, {}, {}
        self.two_reps, self.colour, self.prod = set(), {}, None
        self.contract, self.directed = 'orient-v1', (lambda role, name='': False)
        self.manifest, self.glb = (lambda g: {}), (lambda g: (None, 'glb_missing'))
        self.urls = {}                       # {sku: адреса фото} — для представителя семьи (его фото сверяем по его адресам)
        self.mesh_colour = {}                # {sku: вердикт сторожа цвета} — `mesh_color_check.load_table` (T-20261107-14/2)
        self.quar = {}                       # {sku: {glb_sha16: решение}} — карантин моделей (`mesh_quarantine` cut/reject)
        self.roles = {}                      # {sku: (роль, имя, подтип)} — `orient_worker.role_index` (`effective_role`)
        self.copy_d = set()                  # товары с глубиной-копией ширины (`copied_d`, T-20261107-25/7)
        self.aspect = lambda path, full_sha: None   # мерка меша {h, long, short, slab, mask, version} (`make_aspect`)
        self.__dict__.update(kw)
        self.gen_skus = {g.get('sku') for g in self.gens.values()}


def asset_of(sku: str, cat_urls: set, F: Facts, pol: dict) -> tuple:
    """Прямой ассет товара-владельца → (запись ассета | None, asset_id | None, есть ли кандидат меша, фото {basis, current_sha},
    предупреждения). Причины отказа — в записи (`reasons`, gate fail) или, если записи нет, в .reasons особого вида."""
    revs = list(F.revs.get(sku, []))
    warn, P = [], pol
    ppc = F.ppc.get(sku)
    photo = {'basis': None, 'current_sha': None}
    pre = []
    if ppc:
        url, sha = ppc
        photo = {'basis': 'hash', 'current_sha': sha}
        if cat_urls and url not in cat_urls:
            pre.append('photo_url_changed')        # хеш посчитан по старому адресу — текущего фото не знаем
        ok = lambda r: bool(sha) and sha.startswith(r['sha16'])  # noqa: E731
    elif P['photo'].get('url_fallback'):
        photo = {'basis': 'url', 'current_sha': None}
        ok = lambda r: (F.manifest(F.gens.get(r.get('current_generation_key')) or {}).get('input') or {}).get('image_url') in cat_urls  # noqa: E731
    else:
        ok = lambda r: False  # noqa: E731
        pre.append('photo_sha_unknown')
    usable = [r for r in revs if r.get('origin') not in P['generation']['origin_bad']]
    if revs and not usable:
        return None, None, True, photo, warn, ['legacy_origin']
    rev, had = pick_revision(usable, ok)
    if rev is None:
        return None, None, had, photo, warn, pre + (['photo_changed'] if had else ['no_revision'])
    if photo['basis'] == 'url':
        warn.append('photo_by_url')
    reasons = list(pre)
    if rev['status'] not in P['generation']['revision_status_ok']:
        reasons.append(f"revision_{rev['status']}")
    gen = F.gens.get(rev.get('current_generation_key') or '')
    if gen is None:
        return None, None, True, photo, warn, reasons + ['no_current_generation']
    if not verdict_ok(gen.get('machine_verdict'), P):
        reasons.append(f"machine_verdict:{gen['machine_verdict']}")
    if gen.get('owner_verdict'):
        reasons.append(f"owner_verdict:{gen['owner_verdict']}")
    ps = (F.products.get(sku) or {}).get('mesh_status')
    if ps in P['generation']['product_mesh_status_bad']:
        reasons.append(f'product_mesh_{ps}')
    full, why = F.glb(gen)
    if why:
        reasons.append(why)
    # КАРАНТИН МОДЕЛИ (`mesh_quarantine` cut/reject, T-20261107-05/3): витрина такую модель уже вычитает из индекса прода
    # (`prod_index`), а привязка считала её готовой — сборщик банка ставил её первой («с мешом готов»), спрос писал «нет в индексе»
    # и звал выкладку по кругу. Карантин — на конкретный файл (`glb_sha`, 16 знаков): пересобранная модель под него не попадает
    q = (F.quar.get(sku) or {}).get((full or gen.get('glb_sha') or '')[:16])
    if q:
        reasons.append(f'mesh_quarantine:{q}')
    if full and not (full.startswith(gen.get('glb_sha') or '-') and full.startswith(rev.get('glb_sha') or gen.get('glb_sha') or '-')):
        reasons.append('glb_sha_mismatch')
    man = F.manifest(gen) or {}
    passport = {'role': man.get('role'), 'dims_cm': (man.get('input') or {}).get('dims_cm')}
    ori = None
    if full:
        row = F.orient.get((sku, full[:16]))
        if row is None:
            reasons.append('orientation_missing')
        else:
            ori = {k: row.get(k) for k in ('revision_key', 'status', 'source', 'contract', 'resolution_sha', 'yaw_deg', 'quat_wxyz')}
            if row.get('contract') != F.contract:
                reasons.append('orientation_contract')
            elif row.get('glb_sha') != full:
                reasons.append('orientation_other_glb')
            elif row.get('source') in ('headboard_sideways', 'headboard_flip'):
                # кровать стоит боком, а куда смотрит изголовье — не ясно, или изголовье по геометрии с другой стороны, а форма
                # этого не подтверждает (`orient_worker.apply_headboard`, `MISMATCH_SOURCES`, T-20261110-20/3): не «фронт не
                # решён», а «модель встанет не так» — жёсткий блок, режим orient его не пускает (`orient_only`)
                reasons.append('orientation_mismatch')
            elif row.get('status') not in P['orientation']['status_ok']:
                reasons.append(f"orientation_{row.get('status')}")
            elif row.get('unusable'):
                reasons.append('orientation_unusable')
    rec = {'owner_offer_id': sku, 'generation_key': gen['generation_key'], 'revision_key': rev['revision_key'],
           'source_sha': rev['sha16'], 'pipeline_version': rev['pipeline'], 'local_path': os.path.join(gen['path'], 'model.glb'),
           'glb_bytes': int(gen.get('glb_bytes') or 0), 'passport': passport, 'orientation': ori,
           'gate': 'fail' if reasons else 'pass', 'reasons': reasons,
           'published': published(prod_key(sku), int(gen.get('glb_bytes') or 0), F.prod)}
    return rec, (f'sha256:{full}' if full else None), True, photo, warn, reasons


def prod_key(sku: str) -> str:
    return sku.replace(':', '_')


def published(mesh_id: str, size: int, prod) -> dict:
    """Опубликован ли НУЖНЫЙ файл: в индексе прода и размер там = размеру привязанного (галерея копирует model.glb байт в байт;
    sha на общем с VPN хосте не считаем). prod None — индекс не прочитан; размеры None — только индекс (не доказано)."""
    if prod is None:
        return {'in_index': False, 'size_match': False, 'basis': 'unavailable'}
    if mesh_id not in prod:
        return {'in_index': False, 'size_match': False, 'basis': 'index'}
    s = prod[mesh_id]
    return {'in_index': True, 'size_match': s is not None and s == size, 'basis': 'size' if s is not None else 'index_only'}


def family_of(sku: str, F: Facts) -> tuple:
    """(представитель | None, family_id | None, причины). Вариант — только по products.mesh_family_rep; нет записи или
    представитель = сам товар — не вариант."""
    p = F.products.get(sku)
    if not p or not p.get('rep') or p['rep'] == sku:
        return None, None, []
    rep, fam = p['rep'], p.get('family') or ''
    fid = 'mesh-family:v1:' + hashlib.sha256(fam.encode()).hexdigest()[:16]
    why = []
    rp = F.products.get(rep)
    if rp is None:
        why.append('family_rep_missing')
    elif rp.get('rep') != rep:
        why.append('family_chain')           # представитель сам вариант чужой семьи (и цикл)
    if fam in F.two_reps:
        why.append('family_two_reps')
    return rep, fid, why


def appearance(sku: str, rep: str | None, F: Facts, groups: dict) -> tuple:
    if rep is None:
        return True, []
    a, b = F.colour.get(sku), F.colour.get(rep)
    ga, gb = groups.get(a), groups.get(b)
    if ga is None or gb is None:
        return False, ['appearance_unverified']
    return (True, []) if ga == gb else (False, [f'family_colour_mismatch:{ga}→{gb}'])


COLOUR_REASON = 'mesh_color_mismatch'


def measured_colour(sku: str, aid: str | None, via: bool, F: Facts, app_why: list | tuple = ()) -> tuple:
    """Сторож «меш не того цвета» (T-20261107-14/2): (причины blocked, предупреждения). Вердикт ночного замера
    (`mesh_color_check.guard`) действует, только если он про ЭТОТ ассет: модель сменилась — старый вердикт не считается.
    Вариант семьи с расхождением — blocked `mesh_color_mismatch:ΔL…,Δab…` (не в ленту и не в вариант; кандидат на свой меш,
    `room_mesh_demand`); свой меш — только пометка в строке (прятать нечем; число — в DIGEST сторожа, список — для К8).
    ВАРИАНТ СЕМЬИ ДРУГОЙ ГРУППЫ ЦВЕТА БЕЗ ЗАМЕРА (T-20261112-89): `appearance` дал `family_colour_mismatch`, а замера про этот
    ассет нет (таблицы нет, модель сменилась, нет фото) — `mesh_color_mismatch:unmeasured`: лента его прячет, спрос ставит
    свой меш. Раньше `colour_flagged` такие не видел, и чужая модель другого цвета шла в «Заменить» без проверки."""
    r = (F.mesh_colour or {}).get(sku)
    fam_other = via and any(str(x).startswith('family_colour_mismatch') for x in app_why)
    if not r or not aid or r.get('asset_id') != aid or r.get('verdict') not in ('mismatch', 'ok'):
        return ([f'{COLOUR_REASON}:unmeasured'], []) if fam_other else ([], [])
    if r.get('verdict') != 'mismatch':
        return [], []
    if not via:
        return [], [COLOUR_REASON]
    d = r.get('seen_vs_sku') or {}
    return [f"{COLOUR_REASON}:dL{d.get('dL', 0):+.0f},dab{d.get('dab', 0):.0f}"], []


def colour_flagged(row: dict | None) -> bool:
    """Строка привязки (снимок или таблица) отмечена сторожем цвета — для ленты гостиной и спроса мешей."""
    return any(str(x).startswith(COLOUR_REASON) for x in (row or {}).get('reasons') or [])


def effective_role(sku: str, cat: dict, passport_role: str | None, F: Facts) -> tuple[str, str]:
    """ОДНА роль товара для вопроса «нужен ли перед» → (роль, откуда: catalog | passport | unknown) (T-20261107-25/5, Codex A).
    Порядок — канон `orient_worker` (тот, по которому разворот и решается): роль `room_catalog` (`pick_room_role`: узкая
    главнее общей, направленная главнее) → `products.cat_role` → `mesh_demand` (`role_index`, готов в `F.roles` при сборке);
    товара там нет (селфтест) — тот же резолвер по ролям каталога из `seen_in`. Паспорт генерации (`manifest.role`) — ТОЛЬКО
    если каталог роли не знает (`cat_role_known`). Раньше брали объединение ролей каталога и паспорта и блокировали, если хоть
    одна направленная: паспорт «стул» у обеденного стола «Мелтон» держал его свой меш (179 товаров, у 124 — единственный блок)."""
    import orient_worker as OW
    r = (F.roles or {}).get(sku)
    if r is None:
        room = OW.pick_room_role([(x[1], cat.get('name') or '') for x in cat.get('seen_in') or () if x[2] == 'room_catalog'])
        prod = next(((x[1], cat.get('name') or '') for x in cat.get('seen_in') or () if x[2] != 'room_catalog'), None)
        r = OW.pick_role(prod, None, room) if (room or prod) else None
    if r and OW.cat_role_known(r[0]):
        return r[0].strip(), 'catalog'
    if OW.cat_role_known(passport_role):
        return passport_role.strip(), 'passport'
    return '', 'unknown'


def offer_binding(sku: str, cat: dict, F: Facts, pol: dict, groups: dict, assets: dict, families: dict) -> dict | None:
    """Привязка одного товара. cat — {mid, eid, name, dims:[…], footprint_required, footprint_ok, urls:set, seen_in:[…], roles:set}.
    None — у товара нет ни своего кандидата меша, ни семьи (в снимок не попадает: адаптер скажет none).
    ЗАПАСНОЙ ПУТЬ К ПРЕДСТАВИТЕЛЮ (T-20261107-25/5, Codex B): своя модель есть, но не годна к 3D (`local_3d` нет), а у товара
    семья — привязка проверяет модель представителя ПРОТИВ ЭТОГО товара (файл, разворот, паспорт к габаритам товара, цвет группы
    и замер) и берёт её ЯВНО (`via_family`, `asset_id` представителя, предупреждение `family_fallback`), только если она годна к
    3D и по виду. Не прошла — остаётся своя заблокированная привязка с `fallback_rejected:<orientation|color|other>`; сцена тогда
    модели не получает (`scene_msid` → None, штатная замена). Раньше сцена молча грузила представителя (оливковый «Мелтон»
    вместо бежевого) — модель, которую привязка не проверяла."""
    b = _offer_binding(sku, cat, F, pol, groups, assets, families)
    if b is None or b['via_family'] or b['capabilities']['local_3d']:
        return b
    frep, _, _ = family_of(sku, F)
    if frep is None or not (F.revs.get(frep) or frep in F.gen_skus):
        return b
    a2, f2 = {}, {}
    fb = _offer_binding(sku, cat, F, pol, groups, a2, f2, family=True)
    if fb is not None and fb['capabilities']['local_3d'] and fb['capabilities']['appearance']:
        assets.update({k: v for k, v in a2.items() if k not in assets})
        families.update({k: v for k, v in f2.items() if k not in families})
        own = reason_key(b['reasons'][0]) if b['reasons'] else 'own'
        fb['warnings'] = sorted(set(fb['warnings']) | {'family_fallback', f'own_mesh_blocked:{own}'})
        return fb
    if fb is None:
        kind = 'other'
    elif any(r.startswith('rep:orientation') for r in fb['reasons']):
        kind = 'orientation'
    elif not fb['capabilities']['appearance']:
        kind = 'color'
    else:
        kind = 'other'
    b['warnings'] = sorted(set(b['warnings']) | {f'fallback_rejected:{kind}'})
    return b


def _offer_binding(sku: str, cat: dict, F: Facts, pol: dict, groups: dict, assets: dict, families: dict,
                   family: bool = False) -> dict | None:
    """Привязка по одному пути: своя модель (если своя ревизия текущего фото есть) или семья; family=True — только семья
    (запасной путь `offer_binding`)."""
    own_revs = [] if family else (F.revs.get(sku) or [])
    frep, ffid, ffam_why = family_of(sku, F)
    rep_mesh = frep is not None and (bool(ffam_why) or bool(F.revs.get(frep)) or frep in F.gen_skus)
    if not own_revs and (family or sku not in F.gen_skus) and not rep_mesh:
        return None              # ни своего меша, ни меша у представителя (битая ссылка семьи — блок, не «нет»)
    rec, aid, photo, w, why = None, None, {'basis': None, 'current_sha': None}, [], ['no_revision']
    if own_revs:
        rec, aid, _, photo, w, why = asset_of(sku, cat['urls'], F, pol)
    # своя ревизия текущего фото есть (даже забракованная) — прямая привязка; нет — семья по products.mesh_family_rep
    via = rec is None and rep_mesh
    rep, fid, fam_why = (frep, ffid, ffam_why) if via else (None, None, [])
    owner = rep or sku
    if via:
        rep_urls = set(F.urls.get(rep) or ()) | ({F.ppc[rep][0]} if rep in F.ppc else set())
        rec, aid, _, photo, w, why = asset_of(rep, rep_urls, F, pol)
    warn = list(w)
    if rec is not None and aid:
        assets.setdefault(aid, rec)
    local = list(why) if rec is None else list(rec['reasons'])
    if via:
        local = [f'rep:{x}' for x in local] + fam_why
        families.setdefault(fid, {'family': (F.products.get(sku) or {}).get('family') or '', 'representative_offer_id': rep,
                                  'basis': 'products.mesh_family_rep'})
    # перед нужен? — по ОДНОЙ роли (`effective_role`); паспорт другой роли — предупреждение, не блок
    prole = ((rec or {}).get('passport') or {}).get('role')
    role, role_src = effective_role(sku, cat, prole, F)
    pp, dbm, effd = [], None, None
    if rec:
        gd0 = rec['passport']['dims_cm']
        # глубина каталога — копия ширины (`copied_d`): паспорт сверяем ДО plan_depth — тот достроил бы d = w при w == d,
        # ровно ложный квадрат каталога (T-20261107-25/7, Codex)
        cp = sku in F.copy_d and not via and role in set((pol['passport'].get('d_by_mesh') or {}).get('roles') or ())
        gdims, from_plan = (gd0, False) if cp else plan_depth(gd0, cat['dims'], cat.get('name'), pol)
        pp = passport_check(gdims, cat['dims'], pol, 'family_passport' if via else 'passport')
        if from_plan:
            warn.append('passport_d_from_plan')
        # своя модель, держит ТОЛЬКО глубина паспорта, других причин нет (карантин, файл, разворот — в rec.reasons)
        if cp and pp == ['passport_mismatch:d'] and not local and aid:
            dbm = d_by_mesh(rec['local_path'], aid.removeprefix('sha256:'), (gd0 or {}).get('d'), cat['dims'], F, pol)
            if dbm['ok']:
                pp = []
                warn.append('passport_d_by_mesh')
                effd = effective_dims(dbm, aid, cat['dims'], pol)
            else:
                warn.append(f"passport_d_by_mesh_rejected:{dbm['why']}")
    local += pp
    nm = cat.get('name') or ''
    mism = role_src == 'catalog' and bool(prole) and str(prole).strip() not in ('', '?') and str(prole).strip() != role
    if mism:
        warn.append('passport_role_mismatch')
    ori = (rec or {}).get('orientation') or {}
    if ori.get('source') == 'symmetric_by_role' and not any(x.startswith('orientation') for x in (rec or {}).get('reasons', [])):
        if role and F.directed(role, nm):
            local.append('orientation_symmetric_by_role')
        else:
            warn.append('orientation_by_role_only')
            if mism and F.directed(str(prole).strip(), nm):
                warn.append('passport_role_overruled')     # прежнее правило (объединение ролей) держало бы по паспорту
    solver_why = []
    if not cat['dims'] or not all(d.get('w') and d.get('d') and d.get('h') for d in cat['dims']):
        solver_why.append('catalog_dims_missing')
    if cat.get('footprint_required') and not cat.get('footprint_ok'):
        solver_why.append('footprint_unverified')
    app_ok, app_why = appearance(sku, rep, F, groups)
    mc_why, mc_warn = measured_colour(sku, aid, via, F, app_why)
    app_ok, app_why, warn = app_ok and not mc_why, app_why + mc_why, warn + mc_warn
    local_3d = rec is not None and bool(aid) and not local
    caps = {'solver': not solver_why, 'local_3d': local_3d, 'appearance': app_ok,
            'published_3d': bool(local_3d and rec and rec['published']['size_match'])}
    all_why = local + solver_why + app_why
    if local_3d and rec and rec['published']['in_index'] and not rec['published']['size_match']:
        warn.append('published_other_bytes' if rec['published']['basis'] == 'size' else 'published_unverified')
    return {'mid': cat['mid'], 'eid': cat['eid'], 'status': 'ready' if not all_why else 'blocked', 'asset_id': aid,
            'mesh_id': prod_key(owner) if aid else None, 'representative_offer_id': rep, 'via_family': via, 'family_id': fid,
            'generation_key': rec['generation_key'] if rec else None, 'revision_key': rec['revision_key'] if rec else None,
            'reasons': all_why, 'warnings': sorted(set(warn)), 'capabilities': caps,
            'passport': {'status': 'ok' if not pp and rec is not None else ('mismatch' if pp else 'unknown'),
                         'catalog_dims': cat['dims'], 'hash': dims_hash(cat['dims'], pol['passport']['keys']),
                         **({'d_by_mesh': dbm} if dbm else {}), **({'effective_dims': effd} if effd else {})},
            'photo': photo, 'seen_in': sorted(cat['seen_in'])}


def canonical(snap: dict) -> bytes:
    body = {k: v for k, v in snap.items() if k not in ('content_sha', 'built_at')}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def content_sha(snap: dict) -> str:
    return hashlib.sha256(canonical(snap)).hexdigest()


def tally(offers: dict) -> dict:
    st, why = {'ready': 0, 'blocked': 0}, {}
    for o in offers.values():
        st[o['status']] += 1
        for r in o['reasons']:
            k = r.split(':')[0]
            why[k] = why.get(k, 0) + 1
    return {'offers': len(offers), 'by_status': st, 'by_reason': dict(sorted(why.items(), key=lambda kv: -kv[1]))}


def assemble(cats: dict, F: Facts, pol: dict, groups: dict, sources: dict) -> dict:
    assets, families, offers = {}, {}, {}
    for sku in sorted(cats):
        b = offer_binding(sku, cats[sku], F, pol, groups, assets, families)
        if b is not None:
            offers[sku] = b
    snap = {'schema_version': SCHEMA_VERSION, 'policy_version': pol['policy_version'], 'content_sha': '', 'built_at': '',
            'sources': sources, 'assets': dict(sorted(assets.items())), 'families': dict(sorted(families.items())),
            'offers': offers, 'counts': tally(offers)}
    snap['content_sha'] = content_sha(snap)
    snap['built_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    return snap


# ---------------------------------------------------------------- снимок: проверка, атомарная запись, чтение
def validate(snap: dict) -> list:
    import room_profile as RP
    errs = RP.schema_errors(snap, json.load(open(SCHEMA, encoding='utf-8')))
    if not errs and snap.get('content_sha') != content_sha(snap):
        errs.append('content_sha не совпадает с содержимым')
    if not errs:
        for k, o in snap['offers'].items():
            if f"{o['mid']}:{o['eid']}" != k:
                errs.append(f'offers.{k}: ключ ≠ mid:eid')
            if o['asset_id'] and o['asset_id'] not in snap['assets']:
                errs.append(f'offers.{k}: ассета {o["asset_id"]} нет')
            if o['family_id'] and o['family_id'] not in snap['families']:
                errs.append(f'offers.{k}: семьи {o["family_id"]} нет')
            if o['status'] == 'ready' and o['reasons']:
                errs.append(f'offers.{k}: ready с причинами')
    return errs


def _atomic_write(path: str, data: bytes, check=None) -> None:
    """Временный файл рядом → fsync → проверка → os.replace → fsync папки. Сбой до replace оставляет прежний файл целым."""
    d = os.path.dirname(path) or '.'
    tmp = f'{path}.tmp-{os.getpid()}'
    try:
        with open(tmp, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if check:
            check(tmp)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)               # свой недописанный временный файл; снимки не трогаем
        raise
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_snapshot(snap: dict, out_dir: str) -> str:
    errs = validate(snap)
    if errs:
        raise SystemExit('снимок не прошёл проверку: ' + '; '.join(errs[:5]))
    os.makedirs(out_dir, exist_ok=True)
    final = os.path.join(out_dir, f"bindings-{snap['content_sha'][:16]}.json")

    def check(tmp):
        got = json.load(open(tmp, encoding='utf-8'))
        if content_sha(got) != snap['content_sha']:
            raise RuntimeError('записанный снимок не совпал с собранным')
    if not os.path.exists(final):            # тот же sha уже есть — неизменяемый, не переписываем
        _atomic_write(final, json.dumps(snap, ensure_ascii=False, sort_keys=True).encode(), check)
    _atomic_write(os.path.join(out_dir, CURRENT), open(final, 'rb').read(), check)
    return final


def load(path: str | None = None, pol: dict | None = None) -> tuple:
    """(снимок | None, причина). Нет файла — binding_missing; не JSON/хеш не тот — binding_corrupt; чужая схема или политика —
    binding_version. Исключений наружу нет: адаптер не падает посреди выдачи (Codex «fail closed: unbound»)."""
    path = path or os.path.join(OUT_DIR, CURRENT)
    try:
        if not os.path.exists(path):
            return None, 'binding_missing'
        snap = json.load(open(path, encoding='utf-8'))
        if not isinstance(snap, dict) or not isinstance(snap.get('offers'), dict) or not isinstance(snap.get('assets'), dict):
            return None, 'binding_corrupt'
        pv = (pol or policy())['policy_version']
        if snap.get('schema_version') != SCHEMA_VERSION or snap.get('policy_version') != pv:
            return None, 'binding_version'
        if snap.get('content_sha') != content_sha(snap):
            return None, 'binding_corrupt'
        return snap, ''
    except Exception:  # noqa: BLE001 — любой сбой чтения = нет привязки, с причиной
        return None, 'binding_corrupt'


# ---------------------------------------------------------------- таблица offer_asset_binding (миграция 016)
TABLE = 'offer_asset_binding'
COLS = (('shop_mid', 'integer'), ('external_id', 'text'), ('status', 'text'), ('asset_id', 'text'), ('mesh_id', 'text'),
        ('local_path', 'text'), ('generation_key', 'text'), ('revision_key', 'text'), ('source_sha', 'text'),
        ('representative_mid', 'integer'), ('representative_eid', 'text'), ('via_family', 'boolean'), ('family_id', 'text'),
        ('reasons', 'jsonb'), ('warnings', 'jsonb'), ('solver', 'boolean'), ('local_3d', 'boolean'), ('appearance', 'boolean'),
        ('published_3d', 'boolean'), ('passport', 'jsonb'), ('orientation', 'jsonb'), ('photo', 'jsonb'), ('seen_in', 'jsonb'),
        ('policy_version', 'text'), ('snapshot_id', 'text'), ('built_at', 'timestamptz'))


def db_rows(snap: dict) -> list:
    """Снимок → строки таблицы (одна на товар). Сведения ассета (путь, паспорт генерации, ориентация) — копией из assets."""
    out = []
    for k, o in snap['offers'].items():
        a = snap['assets'].get(o['asset_id']) or {}
        rep = o['representative_offer_id']
        rmid, reid = (rep.split(':', 1) if rep else (None, None))   # offer_id представителя = «mid:eid», eid может содержать «:»
        out.append({'shop_mid': o['mid'], 'external_id': o['eid'], 'status': o['status'], 'asset_id': o['asset_id'],
                    'mesh_id': o['mesh_id'], 'local_path': a.get('local_path'), 'generation_key': o['generation_key'],
                    'revision_key': o['revision_key'], 'source_sha': a.get('source_sha'),
                    'representative_mid': int(rmid) if rmid else None, 'representative_eid': reid, 'via_family': o['via_family'],
                    'family_id': o['family_id'], 'reasons': o['reasons'], 'warnings': o['warnings'],
                    **{c: o['capabilities'][c] for c in ('solver', 'local_3d', 'appearance', 'published_3d')},
                    'passport': dict(o['passport'], asset_dims_cm=(a.get('passport') or {}).get('dims_cm'),
                                     role=(a.get('passport') or {}).get('role')),
                    'orientation': a.get('orientation'), 'photo': o['photo'], 'seen_in': o['seen_in'],
                    'policy_version': snap['policy_version'], 'snapshot_id': snap['content_sha'], 'built_at': snap['built_at']})
    return out


def write_sql(snap: dict) -> str:
    """Полная замена одной транзакцией: блокировка → delete → insert из JSON → проверка числа строк и snapshot_id → commit.
    Ошибка на любом шаге — ON_ERROR_STOP, транзакция откатывается, читатели видят прежнюю привязку целиком."""
    body = json.dumps(db_rows(snap), ensure_ascii=False, sort_keys=True)
    tag = 'b' + hashlib.sha256(body.encode()).hexdigest()[:12]
    assert f'${tag}$' not in body
    names = ', '.join(c for c, _ in COLS)
    decl = ', '.join(f'{c} {t}' for c, t in COLS)
    n = len(snap['offers'])
    return (f'begin;\nlock table {TABLE} in exclusive mode;\ndelete from {TABLE};\n'
            f'insert into {TABLE} ({names})\nselect {names} from jsonb_to_recordset(${tag}${body}${tag}$::jsonb) as x({decl});\n'
            f"do $chk$ begin if (select count(*) from {TABLE}) <> {n} or exists (select 1 from {TABLE} where snapshot_id <> "
            f"'{snap['content_sha']}') then raise exception 'room_bindings: запись не сошлась'; end if; end $chk$;\ncommit;\n")


def write_db(snap: dict, run=None) -> int:
    run = run or (lambda q: _psql_run(q))
    run(write_sql(snap))
    got = run(f"select count(*), min(snapshot_id), max(snapshot_id) from {TABLE}").split('|')
    if int(got[0]) != len(snap['offers']) or got[1] != got[2] or (got[0] != '0' and got[1] != snap['content_sha']):
        raise RuntimeError(f'room_bindings: в таблице {got}, ждали {len(snap["offers"])} строк снимка {snap["content_sha"][:16]}')
    return int(got[0])


def _psql_run(q: str) -> str:
    r = subprocess.run(['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d',
                        os.environ.get('REMLAB_DEVDB_NAME', 'remlab'), '-q', '-v', 'ON_ERROR_STOP=1', '-tA'],
                       input=q, capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(f'room_bindings: SQL упал: {r.stderr[:400]}')
    return r.stdout.strip()


READ_COLS = ('status', 'asset_id', 'mesh_id', 'local_path', 'generation_key', 'revision_key', 'source_sha', 'via_family',
             'family_id', 'reasons', 'warnings', 'solver', 'local_3d', 'appearance', 'published_3d', 'passport', 'orientation',
             'policy_version', 'snapshot_id')
JSON_COLS = {'reasons', 'warnings', 'passport', 'orientation'}
BOOL_COLS = {'via_family', 'solver', 'local_3d', 'appearance', 'published_3d'}


def read_sql() -> str:
    cols = ', '.join(f'{c}::text' if c in JSON_COLS else c for c in READ_COLS)
    return (f"select shop_mid||':'||external_id, case when representative_mid is null then null "
            f"else representative_mid||':'||representative_eid end, {cols} from {TABLE}")


def load_db(fetch, pol: dict | None = None) -> tuple:
    """Привязка из таблицы ОДНИМ запросом → ({offer_id: запись} | None, причина). Нет таблицы — binding_missing, пусто —
    binding_empty, чужая политика или смесь снимков — binding_version / binding_corrupt. Исключений наружу нет."""
    try:
        rows = fetch(read_sql())
    except Exception as e:  # noqa: BLE001 — нет таблицы/базы: unbound с причиной, выдача не падает
        return None, 'binding_missing' if 'does not exist' in str(e) or 'не существует' in str(e) else 'binding_unreadable'
    if not rows:
        return None, 'binding_empty'
    try:
        pv = (pol or policy())['policy_version']
        out = {}
        for r in rows:
            d = dict(zip(('offer_id', 'representative_offer_id') + READ_COLS, r))
            for c in JSON_COLS:
                d[c] = json.loads(d[c]) if d[c] is not None else None
            for c in BOOL_COLS:
                d[c] = d[c] in ('t', True)
            out[d.pop('offer_id')] = d
        if {d['policy_version'] for d in out.values()} != {pv}:
            return None, 'binding_version'
        if len({d['snapshot_id'] for d in out.values()}) != 1:
            return None, 'binding_corrupt'
        return out, ''
    except Exception:  # noqa: BLE001
        return None, 'binding_corrupt'


# ---------------------------------------------------------------- точка входа для демо (T-20261105-47)
_ROWS: dict = {}


def mesh_for(offer_id: str, rows: dict | None = None, *, require_published: bool = True, require_ready: bool = True) -> dict | None:
    """Меш товара комнаты для данных демо: {mesh_id, yaw, glb_sha, ver, asset_id, representative_offer_id, via_family, snapshot}
    или None. msid даём ТОЛЬКО по привязке (не «есть в mesh-index», Codex): готов (ready; require_ready=False — хватит
    local_3d ∧ appearance) и, по умолчанию, опубликован нужный файл (published_3d — после `mesh_publish` и пересборки).
    yaw — разворот фронта ЭТОГО glb (orientation.yaw_deg = legacy_front_yaw, те же градусы, что `orient.json` прода);
    ver — первые 12 знаков sha: меш перегенерирован → другой ver → клиент не берёт старый GLB из кэша (`?v=`).
    rows — {offer_id: строка} (`load_db`); не дан — одно чтение таблицы на процесс."""
    if rows is None:
        if 'rows' not in _ROWS:
            import catalog_items as CI
            _ROWS['rows'] = load_db(CI.fetch)[0] or {}
        rows = _ROWS['rows']
    r = rows.get(offer_id)
    if not r or not r.get('asset_id') or not r.get('mesh_id'):
        return None
    if require_ready and r['status'] != 'ready':
        return None
    if not require_ready and not (r['local_3d'] and r['appearance']):
        return None
    if require_published and not r['published_3d']:
        return None
    sha = r['asset_id'].split(':', 1)[1]
    yaw = (r.get('orientation') or {}).get('yaw_deg')
    return {'mesh_id': r['mesh_id'], 'yaw': float(yaw) if yaw is not None else None, 'glb_sha': sha, 'ver': sha[:12],
            'asset_id': r['asset_id'], 'representative_offer_id': r.get('representative_offer_id'),
            'via_family': bool(r.get('via_family')), 'snapshot': (r.get('snapshot_id') or '')[:16]}


# ---------------------------------------------------------------- годность модели предмета: ОДНО правило банка и демо
# (room-bank-01 этап В, T-20261106-70; правило сторожа T-20261105-51/3, ведущий 06.11: «одно на банк и демо»). Сторож варианта
# спальни (`flat215_demo.bedroom_mesh_gate`) и готовность банка спальни (`room_ready.classify`) зовут `usable`; индекс прода и
# модель представителя — тоже отсюда (`prod_index`, `mesh_rep`), источник один.
MESH_GATE_MODES = ('orient', 'strict')


def orient_only(reasons) -> bool:
    """Привязка держит товар ТОЛЬКО из-за нерешённого разворота (`orientation_*`, в т.ч. представителя `rep:orientation_*`).
    `orientation_mismatch` — не «не решён», а «разворот заведомо неверен» (кровать боком, T-20261110-20/3): не пускается."""
    tails = [str(r).split(':')[-1] for r in reasons or ()]
    return bool(tails) and all(t.startswith('orientation_') for t in tails) and 'orientation_mismatch' not in tails


def orient_loose(a: dict, mode: str = 'orient') -> bool:
    """Режим orient пускает этот asset, хотя привязка не `ready`: `blocked` только по развороту (`orientation_*`)."""
    return mode == 'orient' and not a['ready'] and a['mesh_status'] == 'blocked' and orient_only(a['reasons'])


def orient_note(a: dict, mode: str = 'orient') -> str:
    """Нерешённый разворот у asset, который режим orient пускает, — причины строкой (в журнал), иначе ''."""
    return ', '.join(a['reasons']) if orient_loose(a, mode) else ''


QUARANTINED = 'карантин модели'


class ProdIndex(set):
    """Индекс прода без карантина; `quarantined` — что вычтено (через `_`): `usable` называет такую модель карантином."""
    quarantined: frozenset = frozenset()


def usable(a: dict, msid: str | None, idx, mode: str = 'orient') -> tuple[str, str]:
    """Модель предмета годна для сцены? a — asset товара после привязки (`catalog_items.bound_asset`), msid — какую модель
    грузит сцена (`mesh_rep`: представитель семейства или свой артикул, через `_`), idx — индекс прода (`prod_index`).
    → (причина, заметка): причина '' — годен; заметка — нерешённый разворот у годного в режиме orient (в журнал).
      strict — привязка `ready` и модель выложена привязкой (`published_3d`);
      orient (по умолчанию, ведущий T-51/3) — `ready` ИЛИ `blocked` только по развороту (`orientation_*`): брака у модели нет,
             не решён лишь фронт; у такого `published_3d` ложно всегда (замер Работника 1) — его не требуем.
    В обоих: модель сцены = модель привязки (`mesh_id`; иначе в кадре меш, которого привязка не проверяла) и она в индексе
    прода без карантина — иначе серая коробка."""
    if mode not in MESH_GATE_MODES:
        raise ValueError(f'режим сторожа {mode!r}? можно {", ".join(MESH_GATE_MODES)}')
    # карантин — своей причиной, не «нет в индексе» (иначе спрос и шаг банка зовут выкладку по кругу): по привязке
    # (`mesh_quarantine:*`) или, пока привязку не пересобрали, по вычтенному индексом (`prod_index(...).quarantined`)
    if any('mesh_quarantine' in r for r in a.get('reasons') or ()) or msid in getattr(idx, 'quarantined', ()):
        return QUARANTINED, ''
    loose = orient_loose(a, mode)
    if not (a['ready'] or loose):
        return f"привязка {a['mesh_status']}" + (f": {', '.join(a['reasons'][:2])}" if a['reasons'] else ''), ''
    if a['ready'] and not a['published']:
        return 'модель не выложена', ''
    if msid is None:
        return 'модели сцены нет: представитель семьи привязкой не проверен', ''
    if (a['mesh_id'] or '').replace(':', '_', 1) != msid:
        return f"сцена грузит {msid}, привязка проверила {a['mesh_id']}", ''
    if msid not in idx:
        return 'нет в индексе прода', ''
    return '', orient_note(a, mode)


def prod_index(fallback=lambda: set(), quarantine=None) -> set:
    """SKU (через `_`), у которых меш реально ЛЕЖИТ НА СЕРВЕРЕ: свежий индекс прода (`?v=` — мимо кэша) минус карантин
    (`mesh_quarantine` cut/reject: кривая по осям — для сцены её «нет»). Прод не ответил — fallback() (у демо — модели
    вчерашнего демо) и WARN. Тело — прежнее `flat215_demo._mesh_index` (перенесено, T-70), печать та же."""
    idx = set()
    try:
        import urllib.request
        with urllib.request.urlopen(f'{PROD_IDX}?v={int(time.time())}', timeout=60) as f:
            idx = set(json.load(f))
    except Exception as e:  # noqa: BLE001 — прод недоступен: запасной список
        idx = fallback()
        print(f'WARN:mesh_index: каталог мешей прода недоступен ({repr(e)[:80]}) — беру модели вчерашнего демо: {len(idx)}')
    try:
        if quarantine is None:
            from mesh_queue import db as _db
            quarantine = lambda: {r[0].replace(':', '_', 1) for r in _db(  # noqa: E731
                "select sku from mesh_quarantine where coalesce(decision,'cut') in ('cut','reject')") if r and r[0]}
        quar = quarantine()
        if quar & idx:
            print(f'карантин: моделей убрано из демо {len(quar & idx)}')
        idx -= quar
    except Exception as e:  # noqa: BLE001 — нет таблицы: карантина нет
        print('карантин не прочитан:', e)
        quar = set()
    out = ProdIndex(idx)
    out.quarantined = frozenset(quar)
    return out


def demo_msids(path: str) -> set:
    """Модели опубликованного демо (ленты и предметы вариантов) — запасная истина «на сервере», когда прод не ответил.
    Тело — прежнее `flat215_demo._demo_msids` (перенесено, T-70)."""
    try:
        d = json.load(open(path, encoding='utf-8'))
    except Exception:  # noqa: BLE001 — демо ещё не собиралось
        return set()
    out = {p['msid'] for lst in (d.get('feeds') or {}).values() for p in lst if p.get('msid')}
    out |= {(i.get('sku') or {}).get('msid') for v in d.get('variants') or [] for i in v.get('items') or []}
    return {m for m in out if m}


def scene_msid(row: dict | None, sid: str, rep: dict) -> str | None:
    """Какую модель грузит сцена ЛЮБОЙ КОМНАТЫ (спальня — T-20261106-77/4, вариант А ведущего; гостиная — `flat215_demo._msid`,
    T-77/5 шаг 3): ТОЛЬКО модель привязки (`mesh_id` строки `offer_asset_binding`), все через `_`.
    Зачем: привязка проверяет СВОЮ ревизию товара (своё текущее фото), а `mesh_rep` давал модель представителя — `usable` такой
    предмет отбрасывал («сцена грузит X, привязка проверила Y»), хотя своя модель выложена (Теджонс/Ханна/Монсон Латте,
    Модерн Терракотовый); у гостиной представитель — другой цвет той же формы (лист T-77/5: своя ближе к фото почти везде).
    Свои модели гостиной выкладывает `room_publish` (ROOM_PUBLISH=living).
    ПРЕДСТАВИТЕЛЯ СЕМЬИ МОЛЧА НЕ БЕРЁМ (T-20261107-25/5, Codex B): модель представителя — только если привязка взяла её явно
    (`via_family`: своей модели нет или запасной путь `offer_binding` проверил её против этого товара). Своя модель
    заблокирована, а запасной путь не прошёл (или привязки у товара с семьёй нет) — None: модели нет, сборка делает штатную
    замену. Раньше здесь брался `mesh_rep` — оливковый «Мелтон» вместо бежевого (54 товара гостиной, сухой прогон 07.11).
    Товар без семьи: строки нет — свой артикул (ковры, декор: модель им не положена или её судит индекс прода); строка есть —
    её `mesh_id` (заблокированная своя — как раньше, её судьбу решает сторож комнаты / индекс прода).
    rep — `mesh_rep` (артикул → представитель): только чтобы узнать, что у товара есть семья."""
    r = row or {}
    m = r.get('mesh_id')
    if m and (r.get('local_3d') or r.get('via_family')):
        return m.replace(':', '_', 1)
    if rep.get(sid, sid) != sid:
        return None
    return m.replace(':', '_', 1) if m else sid


def implicit_fallback(row: dict | None, sid: str, rep: dict) -> bool:
    """Прежнее правило `scene_msid` взяло бы представителя семьи молча (модель, которую привязка не проверяла) — для счётчика
    DIGEST `implicit_family_fallback` (сколько таких закрыто правилом B)."""
    r = row or {}
    return not (r.get('mesh_id') and (r.get('local_3d') or r.get('via_family'))) and rep.get(sid, sid) != sid


def mesh_rep(db=None) -> dict:
    """Артикул товара → артикул его МОДЕЛИ (представитель семейства, ADR-0196), оба через `_`. Нет БД — {} (модель у каждого
    своя). Тело — прежнее `flat215_demo._mesh_rep` (перенесено, T-70)."""
    out = {}
    try:
        if db is None:
            from mesh_queue import db
        for r in db("select shop_mid||'_'||external_id, replace(mesh_family_rep,':','_') "
                    "from products where mesh_family_rep is not null"):
            if len(r) == 2 and r[1]:
                out[r[0]] = r[1]
    except Exception:  # noqa: BLE001 — нет БД: считаем, что модель у каждого своя
        out = {}
    return out


# ---------------------------------------------------------------- сборка из БД и диска (только чтение)
def _rows(sql: str) -> list:
    import catalog_items as CI
    return CI.fetch(sql)


def _digest(x) -> str:
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]


def catalog_offers() -> dict:
    """Товары всех комнат адаптера (без мешей) → {offer_id: факты каталога}; один товар в нескольких комнатах — одна запись."""
    import catalog_items as CI
    out: dict = {}
    for room in CI.ROOM_TYPES:
        for c in CI.items(room):
            o = out.setdefault(c.offer_id, {'mid': c.mid, 'eid': c.eid, 'name': c.name, 'dims': [], 'footprint_required': False,
                                            'footprint_ok': True, 'urls': set(), 'seen_in': [], 'roles': set()})
            dm = {k: c.dims.get(k) for k in ('w', 'd', 'h')}
            if dm not in o['dims']:
                o['dims'].append(dm)
            if c.origin == 'room_catalog':
                o['footprint_required'] = True
                o['footprint_ok'] = o['footprint_ok'] and c.dims.get('footprint_ok') is True
            o['urls'] |= {u for u in (c.photo.get('url'), c.photo.get('url_hd'), c.photo.get('best')) if u}
            for r in c.roles:
                o['roles'].add(r)
                if [room, r, c.origin] not in o['seen_in']:
                    o['seen_in'].append([room, r, c.origin])
    return out


def sha_cache_path(out_dir: str) -> str:
    return os.path.join(out_dir, 'glb-sha-cache.json')


def make_glb(cache: dict):
    """gen → (полный sha | None, причина | None); кэш по (путь, размер, mtime) — 15 ГБ мешей не перечитываем каждый раз."""
    def glb(gen):
        p = os.path.join(gen['path'], 'model.glb')
        try:
            st = os.stat(p)
        except OSError:
            return None, 'glb_missing'
        try:
            with open(p, 'rb') as f:
                head = f.read(12)
            if not glb_header_ok(head, st.st_size) or (gen.get('glb_bytes') and int(gen['glb_bytes']) != st.st_size):
                return None, 'glb_truncated'
            hit = cache.get(p)
            if hit and hit[0] == st.st_size and abs(hit[1] - st.st_mtime) < 1e-6:
                return hit[2], None
            h = hashlib.sha256()
            with open(p, 'rb') as f:
                for ch in iter(lambda: f.read(1 << 20), b''):
                    h.update(ch)
            cache[p] = [st.st_size, st.st_mtime, h.hexdigest()]
            return cache[p][2], None
        except OSError:
            return None, 'glb_unreadable'
    return glb


def prod_sizes(src: str, ssh: bool) -> tuple:
    """({mesh_id: размер | None} | None, откуда). По ssh — размеры model.glb на проде (find, только чтение); иначе индекс."""
    if ssh:
        try:
            r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', PROD_HOST,
                                f"find {PROD_DIR} -mindepth 2 -maxdepth 2 -name model.glb -printf '%h %s\\n'"],
                               capture_output=True, text=True, timeout=180)
            if r.returncode == 0 and r.stdout.strip():
                idx, _ = prod_sizes(src, False)
                sizes = {os.path.basename(ln.rsplit(' ', 1)[0]): int(ln.rsplit(' ', 1)[1]) for ln in r.stdout.split('\n') if ' ' in ln}
                if idx is None:
                    return None, f'ssh {PROD_HOST}: индекс не прочитан'
                return {k: sizes.get(k) for k in idx}, f'индекс {src} + размеры ssh {PROD_HOST}:{PROD_DIR}'
        except Exception:  # noqa: BLE001 — нет ssh: только индекс
            pass
    try:
        import urllib.request
        if re.match(r'https?://', src):
            with urllib.request.urlopen(f'{src}?v={int(time.time())}', timeout=60) as f:
                d = json.load(f)
        else:
            d = json.load(open(src, encoding='utf-8'))
        return {k: None for k in d}, f'индекс {src} (без размеров)'
    except Exception as e:  # noqa: BLE001
        return None, f'прод не прочитан: {str(e)[:120]}'


QUARANTINE_SQL = ("select sku, glb_sha, coalesce(decision,'cut') from mesh_quarantine "
                  "where coalesce(decision,'cut') in ('cut','reject')")


def load_quarantine(rows) -> dict:
    """Карантин моделей → {sku: {glb_sha16: решение}}. Решения — те же, что вычитает `prod_index` (cut, reject; пусто = cut)."""
    out: dict = {}
    for r in rows(QUARANTINE_SQL):
        if r and r[0] and r[1]:
            out.setdefault(r[0], {})[str(r[1])[:16]] = r[2]
    return out


def aspect_cache_path(out_dir: str) -> str:
    return os.path.join(out_dir, 'mesh-aspect-cache.json')


def make_aspect(cache: dict, pol: dict):
    """(путь glb, полный sha) → мерка `mesh_dims.raw_measure` + метка вырезки `mask_flag` | None. Кэш — по (версия замера:
    политика `measurement_version` + отпечаток кода замера, полный sha): только стороны следа и высота в единицах меша,
    сантиметры считает `d_by_mesh` от текущей ширины каталога (Codex: кэш готовой глубины по sha устарел бы со сменой ширины)."""
    import mesh_dims as MD
    ver = f"{pol['passport']['d_by_mesh']['measurement_version']}:{hashlib.sha256(MD._RAW2_CHILD.encode()).hexdigest()[:12]}"

    def aspect(path, full_sha):
        k = f'{ver}|{full_sha}'
        if k not in cache:
            m = MD.raw_measure(path) if os.path.exists(path) else None
            cache[k] = {x: m.get(x) for x in ('h', 'long', 'short', 'slab')} if m else {'fail': True}
        r = cache[k]
        return None if r.get('fail') else dict(r, mask=MD.mask_flag(path), version=ver)
    return aspect


def copy_d_index(cats: dict, pol: dict, rows=None) -> set:
    """Товары каталога с глубиной-копией ширины (`copied_d`): карточки магазинов и ролей `passport.d_by_mesh` из БД, разбор —
    тем же `dim_resolver.resolve`, что пишет каталог (роль — products.cat_role, как у load3)."""
    P = (pol.get('passport') or {}).get('d_by_mesh') or {}
    shops = {int(x) for x in P.get('shops') or ()}
    cand = {k for k, c in cats.items() if int(c['mid']) in shops}
    if not P.get('enabled') or not cand:
        return set()
    rows = rows or _rows
    lit = ','.join("'" + r.replace("'", "''") + "'" for r in P.get('roles') or ())
    out = set()
    for r in rows(f"select shop_mid||':'||external_id, name, cat_role, coalesce(params::text,'{{}}') from products "
                  f"where shop_mid in ({','.join(str(s) for s in sorted(shops))}) and cat_role in ({lit})"):
        if len(r) < 4 or r[0] not in cand:
            continue
        try:
            params = json.loads(r[3]) or {}
        except ValueError:
            continue
        if copied_d(cats[r[0]]['mid'], r[1], params, r[2], cats[r[0]]['dims'], pol):
            out.add(r[0])
    return out


def load_facts(prod_src: str, ssh: bool, out_dir: str) -> tuple:
    import mesh_dark as MDK
    pol = policy()
    revs: dict = {}
    for r in _rows("select revision_key, sku, split_part(revision_key,'|',2), split_part(revision_key,'|',3), status, "
                   "coalesce(origin,''), glb_sha, current_generation_key from asset_revisions"):
        revs.setdefault(r[1], []).append({'revision_key': r[0], 'sha16': r[2], 'pipeline': r[3], 'status': r[4], 'origin': r[5],
                                          'glb_sha': r[6], 'current_generation_key': r[7]})
    gens = {r[0]: {'generation_key': r[0], 'sku': r[1], 'glb_sha': r[2], 'path': r[3], 'glb_bytes': r[4], 'machine_verdict': r[5],
                   'owner_verdict': r[6]}
            for r in _rows("select generation_key, sku, glb_sha, path, glb_bytes, machine_verdict, owner_verdict from mesh_generations")}
    orient = {}
    for r in _rows("select revision_key, sku, split_part(revision_key,'|',2), status, resolution->>'glb_sha', "
                   "coalesce(resolution->>'contract', split_part(revision_key,'|',3)), resolution->>'source', "
                   "coalesce(resolution->>'unusable',''), resolution->>'legacy_front_yaw', "
                   "(resolution->'raw_to_canonical_quat_wxyz')::text, "
                   "encode(sha256(convert_to(coalesce(resolution::text,''),'UTF8')),'hex') "
                   "from orientation_state where split_part(revision_key,'|',2) <> ''"):
        orient[(r[1], r[2])] = {'revision_key': r[0], 'status': r[3], 'glb_sha': r[4], 'contract': r[5], 'source': r[6],
                                'unusable': r[7] == 'true', 'yaw_deg': int(float(r[8])) if r[8] else None,
                                'quat_wxyz': json.loads(r[9]) if r[9] else None, 'resolution_sha': r[10][:16]}
    ppc = {r[0]: (r[1], r[2]) for r in _rows('select sku, image_url, source_sha from product_photo_current')}
    products, reps_of = {}, {}
    for r in _rows("select shop_mid||':'||external_id, mesh_status, mesh_family, mesh_family_rep from products "
                   "where mesh_family_rep is not null or mesh_status is not null"):
        products[r[0]] = {'mesh_status': r[1], 'family': r[2], 'rep': r[3]}
        if r[2] and r[3]:
            reps_of.setdefault(r[2], set()).add(r[3])
    two = {f for f, s in reps_of.items() if len(s) > 1}
    quar = load_quarantine(_rows)
    import enrich_bridge as EB
    colour = {k: v.get('colour') for k, v in EB.load().items() if v.get('colour')}
    prod, prod_why = prod_sizes(prod_src, ssh)
    import orient_worker as OW
    cache_p = sha_cache_path(OUT_DIR)       # кэш хешей один на машину (и для --out в другую папку)
    os.makedirs(OUT_DIR, exist_ok=True)
    cache = json.load(open(cache_p, encoding='utf-8')) if os.path.exists(cache_p) else {}
    mans: dict = {}

    def manifest(gen):
        p = os.path.join(gen.get('path') or '', 'manifest.json')
        if p not in mans:
            try:
                mans[p] = json.load(open(p, encoding='utf-8'))
            except Exception:  # noqa: BLE001 — нет манифеста: паспорт неизвестен (passport_missing)
                mans[p] = {}
        return mans[p]
    # сторож цвета мешей (T-20261107-14/2): таблица ночного замера; нет — без отметок, громко (fail-open)
    import mesh_color_check as MCC
    mcol, mcol_why = MCC.load_table()
    if mcol_why:
        print(f'WARN:mesh_colour: таблица сторожа цвета не читается ({mcol_why}) — привязка без отметок mesh_color_mismatch',
              flush=True)
    mcol = mcol or {}
    F = Facts(revs=revs, gens=gens, orient=orient, ppc=ppc, products=products, two_reps=two, colour=colour, prod=prod,
              contract=OW.CONTRACT, directed=lambda role, name='': OW.directed_role(role, name, ''),
              manifest=manifest, glb=make_glb(cache), mesh_colour=mcol, quar=quar)
    import mesh_queue as MQ
    sources = {'asset_revisions': _digest(revs), 'mesh_generations': _digest(gens), 'orientation_state': _digest(sorted(orient.items())),
               'product_photo_current': _digest(ppc), 'products_mesh': _digest(products), 'enrichment_colour': _digest(colour),
               'mesh_quarantine': _digest(quar),
               'policy': _digest(pol), 'orient_contract': OW.CONTRACT, 'directed_roles': sorted(MQ.DIRECTED),
               'prod': {'source': prod_why, 'digest': _digest(prod)},
               'mesh_colour': {'rules': MCC.rules()['version'], 'source': mcol_why or 'table',
                               'digest': _digest({k: [v.get('asset_id'), v.get('verdict')] for k, v in mcol.items()})}}
    return F, pol, MDK.COLOUR_GROUPS, sources, cache, cache_p


def build(out_dir: str, prod_src: str, ssh: bool, dry: bool = False) -> tuple:
    t = time.time()
    os.makedirs(out_dir, exist_ok=True)
    F, pol, groups, sources, cache, cache_p = load_facts(prod_src, ssh, out_dir)
    cats = catalog_offers()
    sources['catalog_offers'] = _digest({k: [v['dims'], sorted(v['urls']), v['footprint_ok']] for k, v in cats.items()})
    import orient_worker as OW
    F.roles = OW.role_index(cats)          # роль «нужен ли перед» — тем же резолвером, что разворот (`effective_role`)
    sources['roles'] = _digest(sorted(F.roles.items()))
    # глубина-копия ширины → сверка паспорта по мерке своего меша (T-20261107-25/7); кэш мерки — один на машину, как хеши
    F.copy_d = copy_d_index(cats, pol)
    acache_p = aspect_cache_path(OUT_DIR)
    acache = json.load(open(acache_p, encoding='utf-8')) if os.path.exists(acache_p) else {}
    F.aspect = make_aspect(acache, pol)
    sources['copy_d'] = _digest(sorted(F.copy_d))
    snap = assemble(cats, F, pol, groups, sources)
    _atomic_write(cache_p, json.dumps(cache, sort_keys=True).encode())
    _atomic_write(acache_p, json.dumps(acache, sort_keys=True).encode())
    path = write_snapshot(snap, out_dir)          # сперва файл: откат и разбор есть, даже если запись в таблицу упадёт
    n = None if dry else write_db(snap)
    return snap, path, round(time.time() - t, 1), n


# ---------------------------------------------------------------- отчёт
def reason_key(r: str) -> str:
    """Ключ причины для счёта: без уточнения после «:», у варианта семьи — «rep:<причина представителя>»."""
    return 'rep:' + r[4:].split(':')[0] if r.startswith('rep:') else r.split(':')[0]


def report(snap: dict) -> dict:
    """По комнатам (seen_in): ready / blocked, причины (первая и все), семья, паспорт, ориентация «по роли», прод."""
    rooms: dict = {}
    for o in snap['offers'].values():
        for room in sorted({s[0] for s in o['seen_in']}):
            R = rooms.setdefault(room, {'offers': 0, 'ready': 0, 'blocked': 0, 'via_family': 0, 'via_family_ready': 0,
                                        'primary_reason': {}, 'any_reason': {}, 'passport_mismatch': 0, 'published_3d': 0,
                                        'orientation_by_role_only': {}, 'orientation_blocked': 0, 'photo_by_url': 0,
                                        'orientation_by_role': {}})
            R['offers'] += 1
            R[o['status']] += 1
            R['via_family'] += o['via_family']
            R['via_family_ready'] += o['via_family'] and o['status'] == 'ready'
            R['published_3d'] += o['capabilities']['published_3d']
            R['passport_mismatch'] += any('passport_mismatch' in r or 'passport_dim_missing' in r for r in o['reasons'])
            R['photo_by_url'] += 'photo_by_url' in o['warnings']
            if o['reasons']:
                k = reason_key(o['reasons'][0])
                R['primary_reason'][k] = R['primary_reason'].get(k, 0) + 1
            for r in {reason_key(x) for x in o['reasons']}:
                R['any_reason'][r] = R['any_reason'].get(r, 0) + 1
            ori = sorted({r.removeprefix('rep:') for r in o['reasons'] if r.removeprefix('rep:').startswith('orientation')})
            R['orientation_blocked'] += bool(ori)
            if ori:      # «не решена» (review/vlm pending, нет записи) против «только симметричная по роли» — по ролям комнаты
                kind = 'symmetric_by_role' if ori == ['orientation_symmetric_by_role'] else 'not_resolved'
                for role in sorted({s[1] for s in o['seen_in'] if s[0] == room}):
                    d = R['orientation_by_role'].setdefault(role, {'not_resolved': 0, 'symmetric_by_role': 0})
                    d[kind] += 1
            if 'orientation_by_role_only' in o['warnings']:
                for role in sorted({s[1] for s in o['seen_in'] if s[0] == room}):
                    R['orientation_by_role_only'][role] = R['orientation_by_role_only'].get(role, 0) + 1
    for R in rooms.values():
        for k in ('primary_reason', 'any_reason'):
            R[k] = dict(sorted(R[k].items(), key=lambda kv: -kv[1]))
    return {'snapshot': snap['content_sha'][:16], 'policy_version': snap['policy_version'], 'counts': snap['counts'], 'rooms': rooms,
            'assets': len(snap['assets']), 'families': len(snap['families'])}


def role_fallback_counts(snap: dict) -> dict:
    """Счётчики правил A и B (T-20261107-25/5) по снимку: паспорт ≠ каталог (`passport_role_mismatch`; из них только он держал
    бы привязку — `passport_role_overruled` без других причин), запасной путь к представителю — взят явно (`family_fallback`)
    и отклонён по развороту / цвету / иному (`fallback_rejected:*`: прежде сцена молча грузила бы представителя — теперь модели
    нет, `implicit_family_fallback`)."""
    c = {'passport_role_mismatch': 0, 'passport_role_only_blocking': 0, 'family_fallback': 0, 'implicit_family_fallback': 0,
         'fallback_rejected': {'orientation': 0, 'color': 0, 'other': 0}}
    for o in snap['offers'].values():
        w = o['warnings']
        c['passport_role_mismatch'] += 'passport_role_mismatch' in w
        c['passport_role_only_blocking'] += 'passport_role_overruled' in w and not o['reasons']
        c['family_fallback'] += 'family_fallback' in w
        for x in w:
            if x.startswith('fallback_rejected:'):
                k = x.split(':', 1)[1]
                c['fallback_rejected'][k] = c['fallback_rejected'].get(k, 0) + 1
                c['implicit_family_fallback'] += 1
    return c


def digest_line(snap: dict) -> str:
    """Строка в ночную сводку (`refresh_daily.sh`, шаг room_bindings с --digest)."""
    c = role_fallback_counts(snap)
    r = c['fallback_rejected']
    return (f"DIGEST:привязка мешей: паспорт ≠ каталог по роли {c['passport_role_mismatch']} (только он держал бы "
            f"{c['passport_role_only_blocking']}); представитель семьи вместо своей заблокированной — проверен и взят "
            f"{c['family_fallback']}, отклонён {c['implicit_family_fallback']} (разворот {r['orientation']}, цвет {r['color']}, "
            f"иное {r['other']}) — у них модели в сцене нет, замена")


def report_md(rep: dict) -> str:
    L = [f"# Привязка мешей — снимок {rep['snapshot']} (политика {rep['policy_version']})", '',
         f"Товаров в снимке {rep['counts']['offers']}, ассетов {rep['assets']}, семей {rep['families']}.", '',
         '| комната | товаров с мешем | ready | blocked | из них семья (ready) | паспорт не сошёлся | ориентация держит | на проде нужный файл |',
         '|---|---|---|---|---|---|---|---|']
    for room, R in sorted(rep['rooms'].items()):
        L.append(f"| {room} | {R['offers']} | {R['ready']} | {R['blocked']} | {R['via_family']} ({R['via_family_ready']}) | "
                 f"{R['passport_mismatch']} | {R['orientation_blocked']} | {R['published_3d']} |")
    for room, R in sorted(rep['rooms'].items()):
        L += ['', f'**{room}** — первая причина: ' + (', '.join(f'{k} {v}' for k, v in R['primary_reason'].items()) or '—'),
              '', 'все причины: ' + (', '.join(f'{k} {v}' for k, v in R['any_reason'].items()) or '—'),
              '', 'ориентация «симметрична по роли» (пропущена, роль не направленная по DIRECTED): '
              + (', '.join(f'{k} {v}' for k, v in R['orientation_by_role_only'].items()) or '—')
              + f"; фото по адресу (нет хеша): {R['photo_by_url']}",
              '', 'ориентация держит по ролям (не решена / только «симметрична по роли» у направленной роли): '
              + (', '.join(f"{k} {v['not_resolved']}/{v['symmetric_by_role']}" for k, v in
                           sorted(R['orientation_by_role'].items(), key=lambda kv: -sum(kv[1].values()))) or '—')]
    return '\n'.join(L) + '\n'


# ---------------------------------------------------------------- селфтест: тесты Codex «Pure/unit» на подставных фактах
def _fixture() -> tuple:
    pol = policy()
    G = {'белый': 'светлый', 'серый': 'светлый', 'чёрный': 'чёрный'}
    gen = lambda key, sku, path, sha='aaaa1111', v='generated', ov=None: {  # noqa: E731
        'generation_key': key, 'sku': sku, 'glb_sha': sha, 'path': path, 'glb_bytes': 100, 'machine_verdict': v, 'owner_verdict': ov}
    full = {'/g/1old': 'aaaa1111' + '0' * 56, '/g/1new': 'bbbb2222' + '0' * 56, '/g/2': 'cccc3333' + '0' * 56,
            '/g/rep': 'dddd4444' + '0' * 56}
    mans = {'/g/1old': {'role': 'кровать', 'input': {'dims_cm': {'w': 176, 'd': 214, 'h': 100}, 'image_url': 'u1'}},
            '/g/1new': {'role': 'кровать', 'input': {'dims_cm': {'w': 176, 'd': 214, 'h': 100}, 'image_url': 'u1'}},
            '/g/2': {'role': 'комод', 'input': {'dims_cm': {'w': 98, 'd': 35, 'h': 25}, 'image_url': 'u2'}},
            '/g/rep': {'role': 'комод', 'input': {'dims_cm': {'w': 93, 'd': 50, 'h': 76}, 'image_url': 'ur'}}}
    F = Facts(
        revs={'1:a': [{'revision_key': '1:a|ph1|v1', 'sha16': 'ph1', 'pipeline': 'v1', 'status': 'generated', 'origin': 'salad-pilot',
                       'glb_sha': 'aaaa1111', 'current_generation_key': 'G1old'}],
              '2:b': [{'revision_key': '2:b|ph2|v1', 'sha16': 'ph2', 'pipeline': 'v1', 'status': 'generated', 'origin': 'salad-pilot',
                       'glb_sha': 'cccc3333', 'current_generation_key': 'G2'}],
              '5:r': [{'revision_key': '5:r|phr|v1', 'sha16': 'phr', 'pipeline': 'v1', 'status': 'generated', 'origin': 'salad-pilot',
                       'glb_sha': 'dddd4444', 'current_generation_key': 'GR'}]},
        gens={'G1old': gen('G1old', '1:a', '/g/1old'), 'G1new': gen('G1new', '1:a', '/g/1new', 'bbbb2222'),
              'G2': gen('G2', '2:b', '/g/2', 'cccc3333'), 'GR': gen('GR', '5:r', '/g/rep', 'dddd4444')},
        orient={('1:a', 'aaaa1111' + '0' * 8): {'revision_key': '1:a|aaaa1111|orient-v1', 'status': 'auto_resolved', 'glb_sha': full['/g/1old'],
                                                 'contract': 'orient-v1', 'source': 'orienter+vlm_agree', 'unusable': False, 'yaw_deg': 180},
                ('2:b', 'cccc3333' + '0' * 8): {'revision_key': '2:b|cccc3333|orient-v1', 'status': 'auto_resolved', 'glb_sha': full['/g/2'],
                                                 'contract': 'orient-v1', 'source': 'symmetric_by_role', 'unusable': False, 'yaw_deg': 0},
                ('5:r', 'dddd4444' + '0' * 8): {'revision_key': '5:r|dddd4444|orient-v1', 'status': 'human_resolved', 'glb_sha': full['/g/rep'],
                                                 'contract': 'orient-v1', 'source': 'human:front_90', 'unusable': False, 'yaw_deg': 90}},
        ppc={'1:a': ('u1', 'ph1' + 'f' * 61), '5:r': ('ur', 'phr' + 'f' * 61)},
        products={'6:v': {'mesh_status': None, 'family': 'комод|монблан|93x50x76', 'rep': '5:r'},
                  '5:r': {'mesh_status': 'ready', 'family': 'комод|монблан|93x50x76', 'rep': '5:r'},
                  '7:w': {'mesh_status': None, 'family': 'комод|монблан|93x50x76', 'rep': '5:r'}},
        colour={'6:v': 'белый', '5:r': 'серый', '7:w': 'чёрный'},
        prod={'1_a': 100, '5_r': 99}, directed=lambda role, name='': role in {'кровать', 'диван'},
        manifest=lambda g: mans.get(g.get('path'), {}), glb=lambda g: (full.get(g['path']), None) if g['path'] in full else (None, 'glb_missing'))
    cat = lambda mid, eid, w, d, h, room='bedroom', role='кровать', origin='room_catalog', urls=('u1',), fp=True: {  # noqa: E731
        'mid': mid, 'eid': eid, 'name': 'Товар', 'dims': [{'w': w, 'd': d, 'h': h}], 'footprint_required': origin == 'room_catalog',
        'footprint_ok': fp, 'urls': set(urls), 'seen_in': [[room, role, origin]], 'roles': {role}}
    return pol, G, F, cat, full


def _selftest() -> int:
    import remlab_tmp  # временное селфтеста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
    remlab_tmp.use('room_bindings-selftest')
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
        return bool(cond)
    pol, G, F, cat, full = _fixture()

    def bind(sku, c, F=F):
        return offer_binding(sku, c, F, pol, G, {}, {})
    b = bind('1:a', cat(1, 'a', 178, 212, 101))
    ok('прямая привязка: текущее поколение ревизии (не самое свежее по mtime) — ready',
       b['status'] == 'ready' and b['asset_id'] == 'sha256:' + full['/g/1old'] and b['mesh_id'] == '1_a', ) or print(b)
    # один товар в двух комнатах и трёх ролях — одна привязка
    c2 = cat(1, 'a', 178, 212, 101)
    c2['seen_in'] += [['hall', 'шкаф', 'room_catalog'], ['bedroom', 'комод', 'room_catalog']]
    snap = assemble({'1:a': c2}, F, pol, G, {})
    ok('товар в двух комнатах и трёх ролях — одна привязка', list(snap['offers']) == ['1:a'] and len(snap['assets']) == 1
       and len(snap['offers']['1:a']['seen_in']) == 3)
    F2 = copy.copy(F)
    F2.glb = lambda g: (None, 'glb_missing')
    ok('нет файла — не ready', bind('1:a', cat(1, 'a', 176, 214, 100), F2)['reasons'] == ['glb_missing'])
    F2.glb = lambda g: (None, 'glb_truncated')
    ok('обрезанный файл — не ready', 'glb_truncated' in bind('1:a', cat(1, 'a', 176, 214, 100), F2)['reasons'])
    F2.glb = lambda g: ('eeee' + '0' * 60, None)
    ok('sha не совпал с БД — не ready', 'glb_sha_mismatch' in bind('1:a', cat(1, 'a', 176, 214, 100), F2)['reasons'])
    ok('заголовок GLB: магия, версия, длина', glb_header_ok(b'glTF' + (2).to_bytes(4, 'little') + (100).to_bytes(4, 'little'), 100)
       and not glb_header_ok(b'glTF' + (2).to_bytes(4, 'little') + (100).to_bytes(4, 'little'), 60) and not glb_header_ok(b'xx', 2))
    F3 = copy.deepcopy(F.__dict__)
    F3 = Facts(**F3)
    F3.manifest, F3.glb, F3.directed = F.manifest, F.glb, F.directed
    F3.revs['1:a'][0]['current_generation_key'] = 'G1new'     # перегон: новое поколение, ориентация была у старого
    ok('новое поколение с ориентацией старого — не ready (orientation_missing)',
       'orientation_missing' in bind('1:a', cat(1, 'a', 176, 214, 100), F3)['reasons'])
    for st, want in (('human_resolved', None), ('pending', 'orientation_pending'), ('review_pending', 'orientation_review_pending')):
        F4 = Facts(**copy.deepcopy({k: v for k, v in F.__dict__.items() if k not in ('manifest', 'glb', 'directed')}))
        F4.manifest, F4.glb, F4.directed = F.manifest, F.glb, F.directed
        F4.orient[('1:a', 'aaaa1111' + '0' * 8)]['status'] = st
        r = bind('1:a', cat(1, 'a', 176, 214, 100), F4)['reasons']
        ok(f'ориентация {st} → {want or "годна"}', (want in r) if want else not r)
    F4.orient[('1:a', 'aaaa1111' + '0' * 8)].update(status='auto_resolved', unusable=True)
    ok('ориентация unusable — не ready', 'orientation_unusable' in bind('1:a', cat(1, 'a', 176, 214, 100), F4)['reasons'])
    F4.orient[('1:a', 'aaaa1111' + '0' * 8)].update(unusable=False, contract='orient-v0')
    ok('чужой контракт ориентации — не ready', 'orientation_contract' in bind('1:a', cat(1, 'a', 176, 214, 100), F4)['reasons'])
    c = cat(2, 'b', 98, 35, 25, role='комод', urls=('u2',))
    F5 = copy.copy(F)
    F5.ppc = dict(F.ppc)
    r = bind('2:b', c, F5)
    ok('без хеша фото — по адресу генерации, с отметкой; «симметрична по роли» у ненаправленной роли — годна',
       r['status'] == 'ready' and 'photo_by_url' in r['warnings'] and 'orientation_by_role_only' in r['warnings'])
    F5.directed = lambda role, name='': role in {'кровать', 'комод'}
    ok('роль стала направленной (DIRECTED) — старое «симметрична по роли» не годно',
       'orientation_symmetric_by_role' in bind('2:b', c, F5)['reasons'])
    F6 = Facts(**copy.deepcopy({k: v for k, v in F.__dict__.items() if k not in ('manifest', 'glb', 'directed')}))
    F6.manifest, F6.glb, F6.directed = F.manifest, F.glb, F.directed
    F6.revs['1:a'][0]['status'] = 'owner_reject'
    ok('отказ владельца — не ready', 'revision_owner_reject' in bind('1:a', cat(1, 'a', 176, 214, 100), F6)['reasons'])
    F6.revs['1:a'][0]['status'] = 'flat_shape'
    ok('flat_shape — не ready', 'revision_flat_shape' in bind('1:a', cat(1, 'a', 176, 214, 100), F6)['reasons'])
    F6.revs['1:a'][0]['status'] = 'generated'
    F6.gens['G1old']['owner_verdict'] = 'redo'
    ok('вердикт владельца на поколении (redo) — не ready', 'owner_verdict:redo' in bind('1:a', cat(1, 'a', 176, 214, 100), F6)['reasons'])
    F6.gens['G1old'].update(owner_verdict=None, machine_verdict='failed')
    ok('машинный вердикт-отказ — не ready', 'machine_verdict:failed' in bind('1:a', cat(1, 'a', 176, 214, 100), F6)['reasons'])
    for v in ('scene_ready', 'web_ready', 'geometry_valid', 'generated', None):
        F6.gens['G1old']['machine_verdict'] = v
        ok(f'машинный вердикт {v} (ступень лестницы или не судили) — годен',
           not any(x.startswith('machine_verdict') for x in bind('1:a', cat(1, 'a', 176, 214, 100), F6)['reasons']))
    for v in ('failed', 'rejected', '', 'web_ready2'):
        F6.gens['G1old']['machine_verdict'] = v
        ok(f'машинный вердикт «{v}» не из лестницы — blocked', bind('1:a', cat(1, 'a', 176, 214, 100), F6)['status'] == 'blocked')
    F6.gens['G1old']['machine_verdict'] = 'generated'
    pmin = json.loads(json.dumps(pol))
    pmin['generation']['machine_verdict_min'] = 'scene_ready'
    ok('нижний порог лестницы: ниже min — не годен, min и выше — годен',
       not verdict_ok('geometry_valid', pmin) and verdict_ok('scene_ready', pmin) and verdict_ok('web_ready', pmin))
    src = open(os.path.join(HERE, 'mesh_gate_pbr.py'), encoding='utf-8').read()
    body = src[src.index('def status('):]
    body = body[:body.index('\ndef ', 1)] if '\ndef ' in body[1:] else body
    gate = re.findall(r"st = '([a-z_]+)'", body)
    ok('лестница правила = ступени mesh_gate_pbr.status в порядке роста',
       gate == pol['generation']['machine_verdict_ladder']) or print('  код:', gate, 'правило:', pol['generation']['machine_verdict_ladder'])
    F6.products['1:a'] = {'mesh_status': 'quarantine', 'family': None, 'rep': None}
    ok('карантин товара — не ready', 'product_mesh_quarantine' in bind('1:a', cat(1, 'a', 176, 214, 100), F6)['reasons'])
    # карантин модели (`mesh_quarantine`): на ЭТОТ файл — blocked без 3D (витрина его вычитает); на прежний файл — не мешает
    try:
        F.quar = {'1:a': {full['/g/1old'][:16]: 'cut'}}
        q = bind('1:a', cat(1, 'a', 178, 212, 101))
        F.quar = {'1:a': {'0123456789abcdef': 'reject'}}
        q2 = bind('1:a', cat(1, 'a', 178, 212, 101))
    finally:
        F.quar = {}
    ok('карантин модели на её файл — blocked, причина mesh_quarantine:cut, local_3d и published_3d нет',
       q['status'] == 'blocked' and 'mesh_quarantine:cut' in q['reasons'] and not q['capabilities']['local_3d']
       and not q['capabilities']['published_3d']) or print(q)
    ok('карантин на другой (прежний) файл модели — привязка готова (пересобранная модель под карантин не попадает)',
       q2['status'] == 'ready' and not any(x.startswith('mesh_quarantine') for x in q2['reasons'])) or print(q2)
    ok('load_quarantine: cut/reject → {sku: {sha16: решение}}, пустое решение — cut (как prod_index)',
       load_quarantine(lambda sql: [['1:a', 'aaaa1111bbbb2222cccc', 'cut'], ['2:b', 'dddd', 'reject'], ['', 'x', 'cut']])
       == {'1:a': {'aaaa1111bbbb2222': 'cut'}, '2:b': {'dddd': 'reject'}} and "coalesce(decision,'cut')" in QUARANTINE_SQL)
    ok('паспорт: 3 % или 2 см — что больше', passport_check({'w': 176, 'd': 214, 'h': 100}, [{'w': 181, 'd': 208, 'h': 98}], pol) == []
       and passport_check({'w': 176, 'd': 214, 'h': 100}, [{'w': 182, 'd': 214, 'h': 100}], pol) == ['passport_mismatch:w'])
    # глубина из плана (T-20261107-11/2): круглый по названию или квадратный по каталогу; прямоугольный — как было
    noD = {'w': 80, 'd': None, 'h': 33}
    ok('паспорт без d, квадратный в плане по каталогу — d = ширине, сходится',
       plan_depth(noD, [{'w': 80, 'd': 80, 'h': 33}], 'Стол журнальный Gatwick 80 см', pol) == ({'w': 80, 'd': 80, 'h': 33}, True)
       and passport_check(plan_depth(noD, [{'w': 80, 'd': 80, 'h': 33}], '', pol)[0], [{'w': 80, 'd': 80, 'h': 33}], pol) == [])
    ok('паспорт без d, «круглый» в названии — d = ширине, хотя каталог не квадратный',
       plan_depth(noD, [{'w': 80, 'd': 60, 'h': 33}], 'Столик Круглый 80', pol)[1]
       and passport_check(plan_depth(noD, [{'w': 80, 'd': 60, 'h': 33}], 'Столик Круглый 80', pol)[0],
                          [{'w': 80, 'd': 60, 'h': 33}], pol) == ['passport_mismatch:d'])
    ok('паспорт без d, диаметр в паспорте — d = диаметру',
       plan_depth({'w': None, 'd': None, 'h': 40, 'dia': 50}, [{'w': 50, 'd': 50, 'h': 40}], 'Столик Ø50', pol)[0]['d'] == 50)
    ok('паспорт без d у прямоугольного — по-прежнему passport_dim_missing:d',
       plan_depth(noD, [{'w': 80, 'd': 60, 'h': 33}], 'Стол журнальный Лори', pol) == (noD, False)
       and passport_check(noD, [{'w': 80, 'd': 60, 'h': 33}], pol) == ['passport_dim_missing:d'])
    ok('d в паспорте есть — правило не вмешивается (квадратный каталог, d паспорта иной)',
       plan_depth({'w': 80, 'd': 70, 'h': 33}, [{'w': 80, 'd': 80, 'h': 33}], 'кругл', pol) == ({'w': 80, 'd': 70, 'h': 33}, False))
    poff = json.loads(json.dumps(pol))
    poff['passport']['plan_depth']['enabled'] = False
    ok('правило выключено — паспорт как был', plan_depth(noD, [{'w': 80, 'd': 80, 'h': 33}], 'кругл', poff) == (noD, False))
    mans_sq = {'role': 'столик', 'input': {'dims_cm': {'w': 98, 'd': None, 'h': 25}, 'image_url': 'u2'}}
    Fsq = copy.copy(F)
    Fsq.manifest = lambda g: mans_sq if g.get('path') == '/g/2' else F.manifest(g)
    r = bind('2:b', cat(2, 'b', 98, 98, 25, role='комод', urls=('u2',)), Fsq)
    ok('привязка: квадратный столик без d в паспорте — ready с отметкой passport_d_from_plan',
       r['status'] == 'ready' and 'passport_d_from_plan' in r['warnings']) or print(r['reasons'], r['warnings'])
    r = bind('2:b', cat(2, 'b', 98, 35, 25, role='комод', urls=('u2',)), Fsq)
    ok('привязка: прямоугольный без d в паспорте — blocked passport_dim_missing:d',
       'passport_dim_missing:d' in r['reasons'] and 'passport_d_from_plan' not in r['warnings'])
    r = bind('1:a', cat(1, 'a', 200, 214, 100))
    ok('габарит каталога сменился — не ready', r['status'] == 'blocked' and 'passport_mismatch:w' in r['reasons']
       and r['passport']['status'] == 'mismatch')
    r = bind('1:a', cat(1, 'a', 176, 214, 100, fp=False))
    ok('footprint_ok потерян — solver нет, не ready', r['reasons'] == ['footprint_unverified'] and not r['capabilities']['solver']
       and r['capabilities']['local_3d'])
    F7 = copy.copy(F)
    F7.ppc = dict(F.ppc, **{'1:a': ('u1', 'zzz' + 'f' * 61)})
    ok('фото сменилось (хеш другой) — не ready', bind('1:a', cat(1, 'a', 176, 214, 100), F7)['reasons'] == ['photo_changed'])
    F7.ppc = dict(F.ppc, **{'1:a': ('u-old', 'ph1' + 'f' * 61)})
    ok('хеш фото по старому адресу — не ready', 'photo_url_changed' in bind('1:a', cat(1, 'a', 176, 214, 100), F7)['reasons'])
    # семья: ссылкой на представителя
    v = bind('6:v', cat(6, 'v', 93, 50, 76, role='комод', origin='products', urls=('uv',)))
    ok('вариант семьи берёт ассет представителя ссылкой, цвет одной группы — ready',
       v['status'] == 'ready' and v['via_family'] and v['representative_offer_id'] == '5:r' and v['mesh_id'] == '5_r'
       and v['asset_id'] == 'sha256:' + full['/g/rep'] and v['family_id'].startswith('mesh-family:v1:')) or print(v)
    w = bind('7:w', cat(7, 'w', 93, 50, 76, role='комод', origin='products', urls=('uw',)))
    ok('вариант другого цвета: геометрия да, вид нет', w['status'] == 'blocked' and w['capabilities']['local_3d']
       and not w['capabilities']['appearance']
       and w['reasons'] == ['family_colour_mismatch:чёрный→светлый', 'mesh_color_mismatch:unmeasured'])
    ok('вариант другой группы цвета без замера — отметка сторожа (лента прячет, спрос — свой меш; T-20261112-89)',
       colour_flagged(w)) or print(w)
    Fw = copy.copy(F)
    Fw.mesh_colour = {'7:w': {'asset_id': 'sha256:' + full['/g/rep'], 'verdict': 'ok', 'seen_vs_sku': {'dL': 3.0, 'dab': 2.0}}}
    w2 = bind('7:w', cat(7, 'w', 93, 50, 76, role='комод', origin='products', urls=('uw',)), Fw)
    ok('вариант другой группы цвета, замер этого ассета «ok» (подкраска свела) — не отметка, в ленту можно',
       not colour_flagged(w2) and w2['reasons'] == ['family_colour_mismatch:чёрный→светлый']) or print(w2)
    # сторож цвета мешей (T-20261107-14/2): вердикт замера про ЭТОТ ассет
    rep_aid = 'sha256:' + full['/g/rep']
    Fc = copy.copy(F)
    Fc.mesh_colour = {'6:v': {'asset_id': rep_aid, 'verdict': 'mismatch', 'seen_vs_sku': {'dL': -39.2, 'dab': 72.0}},
                      '5:r': {'asset_id': rep_aid, 'verdict': 'mismatch', 'seen_vs_sku': {'dL': 50.0, 'dab': 2.0}}}
    v = bind('6:v', cat(6, 'v', 93, 50, 76, role='комод', origin='products', urls=('uv',)), Fc)
    ok('вариант семьи, видимый цвет не тот (замер) — blocked mesh_color_mismatch, вид нет, геометрия да',
       v['status'] == 'blocked' and v['reasons'] == ['mesh_color_mismatch:dL-39,dab72'] and not v['capabilities']['appearance']
       and v['capabilities']['local_3d'] and colour_flagged(v)) or print(v)
    r5 = bind('5:r', cat(5, 'r', 93, 50, 76, role='комод', origin='products', urls=('ur',)), Fc)
    ok('свой меш с расхождением — не прячем: статус прежний, только предупреждение',
       COLOUR_REASON in r5['warnings'] and not colour_flagged(r5)
       and r5['status'] == bind('5:r', cat(5, 'r', 93, 50, 76, role='комод', origin='products', urls=('ur',)))['status']) or print(r5)
    Fc.mesh_colour = {'6:v': {'asset_id': 'sha256:старый', 'verdict': 'mismatch', 'seen_vs_sku': {'dL': -39, 'dab': 72}}}
    ok('вердикт про другой (старый) ассет — не действует, вариант ready',
       bind('6:v', cat(6, 'v', 93, 50, 76, role='комод', origin='products', urls=('uv',)), Fc)['status'] == 'ready')
    Fc.mesh_colour = {'6:v': {'asset_id': rep_aid, 'verdict': 'unknown', 'seen_vs_sku': None}}
    ok('нет замера (unknown) — не отметка', bind('6:v', cat(6, 'v', 93, 50, 76, role='комод', origin='products', urls=('uv',)),
                                                 Fc)['status'] == 'ready')
    F8 = Facts(**copy.deepcopy({k: v for k, v in F.__dict__.items() if k not in ('manifest', 'glb', 'directed')}))
    F8.manifest, F8.glb, F8.directed = F.manifest, F.glb, F.directed
    F8.revs['5:r'][0]['status'] = 'owner_reject'
    v = bind('6:v', cat(6, 'v', 93, 50, 76, role='комод', origin='products', urls=('uv',)), F8)
    ok('представитель забракован — все варианты не ready', 'rep:revision_owner_reject' in v['reasons'])
    F8.revs['5:r'][0]['status'] = 'generated'
    del F8.products['5:r']
    ok('нет представителя — не ready', 'family_rep_missing' in bind('6:v', cat(6, 'v', 93, 50, 76, role='комод', origin='products'), F8)['reasons'])
    F8.products['5:r'] = {'mesh_status': None, 'family': 'x', 'rep': '6:v'}
    ok('цикл/цепочка представителей — не ready', 'family_chain' in bind('6:v', cat(6, 'v', 93, 50, 76, role='комод', origin='products'), F8)['reasons'])
    F8.products['5:r'] = {'mesh_status': None, 'family': 'комод|монблан|93x50x76', 'rep': '5:r'}
    F8.two_reps = {'комод|монблан|93x50x76'}
    ok('два представителя у семьи — не ready', 'family_two_reps' in bind('6:v', cat(6, 'v', 93, 50, 76, role='комод', origin='products'), F8)['reasons'])
    v = bind('6:v', cat(6, 'v', 120, 50, 76, role='комод', origin='products'))
    ok('вариант другого размера, чем паспорт представителя, — не ready', 'family_passport_mismatch:w' in v['reasons'])
    ok('товар без меша и семьи — вне снимка', bind('9:z', cat(9, 'z', 1, 1, 1)) is None)
    F9 = copy.copy(F)
    F9.products = dict(F.products, **{'8:u': {'mesh_status': None, 'family': 'f2', 'rep': '8:r'}, '8:r': {'mesh_status': None, 'family': 'f2', 'rep': '8:r'}})
    ok('вариант, у представителя которого меша нет, — вне снимка (меша нет, не блок)', bind('8:u', cat(8, 'u', 1, 1, 1), F9) is None)
    snap = assemble({'1:a': cat(1, 'a', 176, 214, 100)}, F, pol, G, {})
    ok('снесённый товар не попадает в снимок (снимок — только по выдаче каталога)', '6:v' not in snap['offers'])
    ok('опубликован нужный файл: в индексе и размер совпал', snap['offers']['1:a']['capabilities']['published_3d']
       and published('5_r', 100, F.prod) == {'in_index': True, 'size_match': False, 'basis': 'size'}
       and published('x', 1, None)['basis'] == 'unavailable')
    s1 = assemble({'1:a': cat(1, 'a', 176, 214, 100), '6:v': cat(6, 'v', 93, 50, 76, role='комод', origin='products')}, F, pol, G, {})
    s2 = assemble({'6:v': cat(6, 'v', 93, 50, 76, role='комод', origin='products'), '1:a': cat(1, 'a', 176, 214, 100)}, F, pol, G, {})
    ok('снимок детерминирован (порядок входа не важен, время не входит в хеш)', s1['content_sha'] == s2['content_sha']
       and canonical(s1) == canonical(s2))
    ok('снимок проходит схему', not validate(s1) or print(validate(s1)))
    import tempfile
    d = tempfile.mkdtemp(prefix='bind-selftest-', dir=os.environ.get('TMPDIR'))
    p1 = write_snapshot(s1, d)
    before = open(os.path.join(d, CURRENT), 'rb').read()
    s3 = assemble({'1:a': cat(1, 'a', 176, 214, 100)}, F, pol, G, {})
    real = os.replace

    def boom(a, b):
        raise OSError('сбой посреди записи')
    os.replace = boom
    try:
        write_snapshot(s3, d)
        ok('прерванная запись — ошибка', False)
    except OSError:
        ok('прерванная запись: прежний current.json цел, временных файлов нет',
           open(os.path.join(d, CURRENT), 'rb').read() == before and not [f for f in os.listdir(d) if '.tmp-' in f])
    finally:
        os.replace = real
    got, why = load(os.path.join(d, CURRENT), pol)
    ok('чтение снимка: тот же content_sha', why == '' and got['content_sha'] == s1['content_sha'] and os.path.exists(p1))
    open(os.path.join(d, 'bad.json'), 'w').write('{"schema_version": 1')
    open(os.path.join(d, 'v2.json'), 'w').write(json.dumps(dict(s1, schema_version=2)))
    t = dict(s1, offers=dict(s1['offers']))
    t['offers']['1:a'] = dict(t['offers']['1:a'], status='blocked')
    open(os.path.join(d, 'edit.json'), 'w').write(json.dumps(t))
    ok('нет / битый / чужая версия / правка руками — причина, без исключения',
       load(os.path.join(d, 'none.json'), pol)[1] == 'binding_missing' and load(os.path.join(d, 'bad.json'), pol)[1] == 'binding_corrupt'
       and load(os.path.join(d, 'v2.json'), pol)[1] == 'binding_version' and load(os.path.join(d, 'edit.json'), pol)[1] == 'binding_corrupt')
    # таблица offer_asset_binding: запись одной транзакцией и чтение одним запросом
    q = write_sql(s1)
    tag = re.search(r'\$(b[0-9a-f]{12})\$', q).group(1)
    body = json.loads(q.split(f'${tag}$')[1])
    ok('запись в таблицу: одна транзакция, полная замена, проверка числа строк; строки = товары снимка',
       q.startswith('begin;\nlock table offer_asset_binding') and 'delete from offer_asset_binding;' in q and q.endswith('commit;\n')
       and "raise exception" in q and body == db_rows(s1) and len(body) == len(s1['offers'])
       and {(r['shop_mid'], r['external_id']) for r in body} == {(1, 'a'), (6, 'v')})
    v6 = next(r for r in body if r['external_id'] == 'v')
    ok('строка варианта: представитель mid/eid раздельно, путь и паспорт ассета представителя',
       v6['representative_mid'] == 5 and v6['representative_eid'] == 'r' and v6['local_path'] == '/g/rep/model.glb'
       and v6['passport']['asset_dims_cm'] == {'w': 93, 'd': 50, 'h': 76} and v6['orientation']['status'] == 'human_resolved')
    seen = []

    def fake(qq, n=len(s1['offers']), sid=s1['content_sha']):
        seen.append(qq)
        return f'{n}|{sid}|{sid}' if qq.startswith('select count') else ''
    ok('write_db: запись и сверка', write_db(s1, fake) == 2 and len(seen) == 2)
    try:
        write_db(s1, lambda qq: '1|x|x' if qq.startswith('select count') else '')
        ok('write_db: не сошлось — ошибка', False)
    except RuntimeError:
        ok('write_db: не сошлось — ошибка', True)

    def as_text(r):          # строка таблицы так, как её вернёт read_sql через catalog_items.fetch
        rep_ = None if r['representative_mid'] is None else f"{r['representative_mid']}:{r['representative_eid']}"
        cv = {c: (json.dumps(r[c]) if c in JSON_COLS and r[c] is not None else ('t' if r[c] else 'f') if c in BOOL_COLS else r[c])
              for c in READ_COLS}
        return [f"{r['shop_mid']}:{r['external_id']}", rep_] + [cv[c] for c in READ_COLS]
    got, why = load_db(lambda qq: [as_text(r) for r in body], pol)
    ok('load_db: тот же снимок, представитель, флаги', why == '' and set(got) == {'1:a', '6:v'}
       and got['6:v']['representative_offer_id'] == '5:r' and got['6:v']['via_family'] is True
       and got['1:a']['local_3d'] is True and got['1:a']['snapshot_id'] == s1['content_sha'])
    ok('load_db: нет таблицы / пусто — причина', load_db(lambda qq: (_ for _ in ()).throw(RuntimeError('relation does not exist')), pol)[1]
       == 'binding_missing' and load_db(lambda qq: [], pol)[1] == 'binding_empty')
    got['1:a']['published_3d'] = True
    m = mesh_for('1:a', got)
    ok('mesh_for: свой меш — mesh_id, разворот этого glb, sha и версия для кэша', m and m['mesh_id'] == '1_a' and m['yaw'] == 180.0
       and m['glb_sha'] == full['/g/1old'] and m['ver'] == full['/g/1old'][:12] and not m['via_family'])
    ok('mesh_for: вариант — меш представителя; не опубликован — нет msid', mesh_for('6:v', got) is None
       and mesh_for('6:v', got, require_published=False)['mesh_id'] == '5_r'
       and mesh_for('6:v', got, require_published=False)['yaw'] == 90.0)
    g2 = {k: dict(v) for k, v in got.items()}
    g2['1:a'].update(status='blocked', local_3d=True, appearance=True, reasons=['footprint_unverified'])
    ok('mesh_for: не ready — нет; require_ready=False берёт годный к 3D; нет товара — нет',
       mesh_for('1:a', g2) is None and mesh_for('1:a', g2, require_ready=False)['mesh_id'] == '1_a' and mesh_for('9:z', got) is None)
    g2['1:a'].update(asset_id='sha256:' + 'b' * 64)
    ok('mesh_for: перегенерирован (другой sha) — другая версия для кэша', mesh_for('1:a', g2, require_ready=False)['ver'] == 'b' * 12)
    rep = report(s1)
    ok('отчёт по комнатам', rep['rooms']['bedroom']['ready'] == 2 and rep['rooms']['bedroom']['offers'] == 2 and report_md(rep))
    rmap = {'7_c': '7_r'}
    ok('scene_msid: модель привязки (есть файл) · явная семья (via_family) — представитель · своя заблокирована при семье — '
       'None (не представитель молча, T-25/5) · строки нет при семье — None · без семьи — свой артикул / mesh_id',
       scene_msid({'mesh_id': '7:c', 'local_3d': True}, '7_c', rmap) == '7_c'
       and scene_msid({'mesh_id': '7:r', 'local_3d': False, 'via_family': True}, '7_c', rmap) == '7_r'
       and scene_msid({'mesh_id': '7:c', 'local_3d': False, 'status': 'blocked'}, '7_c', rmap) is None
       and scene_msid(None, '7_c', rmap) is None and scene_msid(None, '8_d', rmap) == '8_d'
       and scene_msid({'mesh_id': '8:d', 'local_3d': False}, '8_d', rmap) == '8_d')
    ok('implicit_fallback: прежнее правило взяло бы представителя молча — да у заблокированной своей и у пустой при семье',
       implicit_fallback({'mesh_id': '7:c', 'local_3d': False}, '7_c', rmap) and implicit_fallback(None, '7_c', rmap)
       and not implicit_fallback({'mesh_id': '7:c', 'local_3d': True}, '7_c', rmap)
       and not implicit_fallback({'mesh_id': '8:d', 'local_3d': False}, '8_d', rmap))
    ok('usable: модели сцены нет (None) — своя причина, не «сцена грузит None»',
       usable({'ready': True, 'published': True, 'mesh_status': 'ready', 'reasons': [], 'mesh_id': '7:c'}, None, {'7_c'})[0]
       .startswith('модели сцены нет'))

    # ---- A (T-20261107-25/5): «нужен ли перед» — по ОДНОЙ роли (`effective_role`, порядок `orient_worker`), паспорт — запасной
    mans_a = {'role': 'кровать', 'input': {'dims_cm': {'w': 98, 'd': 35, 'h': 25}, 'image_url': 'u2'}}
    Fa = copy.copy(F)
    Fa.manifest = lambda g: mans_a if g.get('path') == '/g/2' else F.manifest(g)
    r = bind('2:b', c, Fa)          # каталог «комод» (не направлен), паспорт «кровать» (направлен), «симметрична по роли»
    ok('A: каталог знает роль (комод) — паспорт «кровать» не держит: ready, предупреждения passport_role_mismatch и _overruled',
       r['status'] == 'ready' and {'passport_role_mismatch', 'passport_role_overruled', 'orientation_by_role_only'}
       <= set(r['warnings'])) or print(r['reasons'], r['warnings'])
    ca = cat(2, 'b', 98, 35, 25, role='кровать', urls=('u2',))
    r = bind('2:b', ca)             # каталог «кровать» (направлен), паспорт «комод»
    ok('A: каталог — направленная роль — «симметрична по роли» не годна, расхождение паспорта — предупреждение',
       'orientation_symmetric_by_role' in r['reasons'] and 'passport_role_mismatch' in r['warnings']
       and 'passport_role_overruled' not in r['warnings'])
    cu = cat(2, 'b', 98, 35, 25, role='другое', urls=('u2',))
    r = bind('2:b', cu, Fa)         # каталог роли не знает → паспорт «кровать»
    ok('A: каталог роли не знает («другое») — роль из паспорта (кровать): blocked, без passport_role_mismatch',
       'orientation_symmetric_by_role' in r['reasons'] and 'passport_role_mismatch' not in r['warnings'])
    Fr = copy.copy(F)
    Fr.roles = {'2:b': ('кровать', '', '')}
    ok('A: роль из резолвера (`role_index`: room_catalog → cat_role → mesh_demand) главнее ролей строки каталога',
       'orientation_symmetric_by_role' in bind('2:b', c, Fr)['reasons'])
    Fr.roles = {'2:b': ('?', '', '')}
    ok('A: резолвер роли не знает («?») — паспорт', effective_role('2:b', c, 'кровать', Fr) == ('кровать', 'passport')
       and effective_role('2:b', c, None, Fr) == ('', 'unknown'))
    import orient_worker as OW
    two = {'name': 'Шкаф', 'seen_in': [['bedroom', 'шкаф', 'room_catalog'], ['hall', 'шкаф-купе', 'room_catalog'],
                                       ['living', 'комод', 'products']]}
    ok('A: без записи резолвера — тот же резолвер по строкам каталога: узкая роль комнаты главнее, комната главнее cat_role',
       effective_role('x', two, 'стул', Facts()) == ('шкаф-купе', 'catalog')
       and effective_role('x', {'name': 'Стол', 'seen_in': [['living', 'стол обеденный', 'products']]}, 'стул', Facts())
       == (OW.pick_role(('стол обеденный', 'Стол'), None)[0], 'catalog'))

    # ---- B (T-20261107-25/5): своя модель заблокирована → представитель семьи только ЯВНО и проверенным против товара
    def with_own(F0, sku, st='owner_reject', ppc_url='uv'):
        Fb = Facts(**copy.deepcopy({k: v for k, v in F0.__dict__.items() if k not in ('manifest', 'glb', 'directed')}))
        Fb.directed = F0.directed
        own_full = 'eeee5555' + '0' * 56
        Fb.revs[sku] = [{'revision_key': f'{sku}|ph6|v1', 'sha16': 'ph6', 'pipeline': 'v1', 'status': st, 'origin': 'salad-pilot',
                         'glb_sha': 'eeee5555', 'current_generation_key': 'G6'}]
        Fb.gens['G6'] = gen('G6', sku, '/g/6', 'eeee5555')
        Fb.gen_skus = {g.get('sku') for g in Fb.gens.values()}
        Fb.ppc[sku] = (ppc_url, 'ph6' + 'f' * 61)
        Fb.orient[(sku, 'eeee5555' + '0' * 8)] = {'revision_key': f'{sku}|eeee5555|orient-v1', 'status': 'auto_resolved',
                                                    'glb_sha': own_full, 'contract': 'orient-v1', 'source': 'orienter+vlm_agree',
                                                    'unusable': False, 'yaw_deg': 0}
        Fb.manifest = lambda g: ({'role': 'комод', 'input': {'dims_cm': {'w': 93, 'd': 50, 'h': 76}, 'image_url': ppc_url}}
                                 if g.get('path') == '/g/6' else F0.manifest(g))
        Fb.glb = lambda g: (own_full, None) if g.get('path') == '/g/6' else F0.glb(g)
        return Fb
    gen = lambda key, sku, path, sha: {'generation_key': key, 'sku': sku, 'glb_sha': sha, 'path': path, 'glb_bytes': 100,  # noqa: E731
                                       'machine_verdict': 'generated', 'owner_verdict': None}
    cv = cat(6, 'v', 93, 50, 76, role='комод', origin='products', urls=('uv',))
    Fb = with_own(F, '6:v')
    ok('B: без брака своя модель — прямая привязка (запасной путь не нужен)',
       bind('6:v', cv, with_own(F, '6:v', 'generated'))['mesh_id'] == '6_v')
    v = bind('6:v', cv, Fb)
    ok('B: своя забракована, представитель годен и того же цвета — ЯВНАЯ привязка к нему: via_family, ассет представителя, '
       'family_fallback и own_mesh_blocked', v['via_family'] and v['mesh_id'] == '5_r' and v['asset_id'] == rep_aid
       and v['capabilities']['local_3d'] and 'family_fallback' in v['warnings']
       and 'own_mesh_blocked:revision_owner_reject' in v['warnings'] and v['status'] == 'ready') or print(v)
    ok('B: сцена грузит представителя ТОЛЬКО по такой привязке', scene_msid({'mesh_id': v['mesh_id'], 'local_3d': True,
                                                                             'via_family': True}, '6_v', {'6_v': '5_r'}) == '5_r')
    cw = cat(7, 'w', 93, 50, 76, role='комод', origin='products', urls=('uw',))
    w7 = bind('7:w', cw, with_own(F, '7:w', ppc_url='uw'))
    ok('B: представитель другого цвета — отклонён (fallback_rejected:color), привязка своя заблокированная, сцена — None',
       not w7['via_family'] and w7['mesh_id'] == '7_w' and 'fallback_rejected:color' in w7['warnings']
       and scene_msid({'mesh_id': '7:w', 'local_3d': False}, '7_w', {'7_w': '5_r'}) is None) or print(w7)
    Fo = with_own(F, '6:v')
    Fo.orient[('5:r', 'dddd4444' + '0' * 8)]['status'] = 'review_pending'
    v = bind('6:v', cv, Fo)
    ok('B: у представителя не решён разворот — отклонён (fallback_rejected:orientation)',
       not v['via_family'] and 'fallback_rejected:orientation' in v['warnings']) or print(v)
    Fm = with_own(F, '6:v')
    Fm.mesh_colour = {'6:v': {'asset_id': rep_aid, 'verdict': 'mismatch', 'seen_vs_sku': {'dL': -40, 'dab': 70}}}
    ok('B: замер цвета модели представителя против ЭТОГО товара — расхождение — отклонён по цвету',
       'fallback_rejected:color' in bind('6:v', cv, Fm)['warnings'])
    snap = assemble({'6:v': cv, '7:w': cw}, with_own(with_own(F, '6:v'), '7:w', ppc_url='uw'), pol, G, {})
    cnt = role_fallback_counts(snap)
    ok('B: снимок — ассет и семья запасного пути на месте, схема цела; счётчики и строка сводки',
       not validate(snap) and cnt['family_fallback'] == 1 and cnt['implicit_family_fallback'] == 1
       and cnt['fallback_rejected']['color'] == 1 and digest_line(snap).startswith('DIGEST:привязка мешей:')) \
        or print(validate(snap), cnt)

    # ---- К2 узко (T-20261107-25/7): глубина каталога — копия ширины → паспорт по мерке своего меша
    MP = {'Размеры: Длина габаритная': '49см', 'Размеры: Ширина габаритная': '49см', 'Размеры: Высота габаритная': '82см'}
    sq = [{'w': 49.0, 'd': 49.0, 'h': 82.0}]
    ok('К2 copied_d: стул divan.ru «Длина = Ширина габаритная», каталог квадрат — копия',
       copied_d(112923, 'Стул divan.ru Марти-2 Велюр', MP, 'стул', sq, pol))
    ok('К2 copied_d: ключ «Глубина габаритная» в карточке есть — глубина измерена, не копия',
       not copied_d(112923, 'Стул Марти-2', dict(MP, **{'Размеры: Глубина габаритная': '54см'}), 'стул', sq, pol))
    ok('К2 copied_d: пуф и столик с честным w == d, кресло divan.ru — роли вне правила',
       not copied_d(112923, 'Пуф Круг', MP, 'пуф', sq, pol) and not copied_d(112923, 'Столик', MP, 'столик', sq, pol)
       and not copied_d(112923, 'Кресло-кровать', MP, 'кресло', sq, pol))
    ok('К2 copied_d: чужой магазин (Glasar 99272, измеренная d) и другой магазин с теми же ключами — не трогаем',
       not copied_d(99272, 'Стул Glasar Олень 48х46х96 см', {'Длина': '48', 'Ширина': '46', 'Высота': '96'}, 'стул',
                    [{'w': 48.0, 'd': 46.0, 'h': 96.0}], pol)
       and not copied_d(114082, 'Стул Марти', MP, 'стул', sq, pol))
    ok('К2 copied_d: каталог не квадрат (габарит из другого источника) — не копия',
       not copied_d(112923, 'Стул Марти-2', MP, 'стул', [{'w': 49.0, 'd': 54.0, 'h': 82.0}], pol))
    poff = json.loads(json.dumps(pol))
    poff['passport']['d_by_mesh']['enabled'] = False
    ok('К2 copied_d: правило выключено — не копия', not copied_d(112923, 'Стул Марти-2', MP, 'стул', sq, poff))

    def chair(pass_dims, asp, role='стул', marked=True, **kw):
        Fk = Facts(**dict(F.__dict__))
        Fk.manifest = lambda g: ({'role': role, 'input': {'dims_cm': pass_dims, 'image_url': 'u2'}} if g.get('path') == '/g/2'
                                 else F.manifest(g))
        Fk.copy_d = {'2:b'} if marked else set()
        calls = []
        Fk.aspect = lambda path, sha: (calls.append((path, sha)), asp and dict(asp, version='raw2:t'))[1]
        Fk.__dict__.update(kw)
        return bind('2:b', cat(2, 'b', 49, 49, 82, role=role, urls=('u2',)), Fk), calls
    A = {'h': 0.82, 'long': 0.54, 'short': 0.49, 'slab': None, 'mask': None}
    r, calls = chair({'w': 49, 'd': 54, 'h': 82}, A)
    ok('К2 Марти-2: паспорт d 54, каталог 49 (копия w), меш 54 — ready, passport_d_by_mesh, разбор в passport.d_by_mesh, '
       'мерка по полному sha своего glb', r['status'] == 'ready' and 'passport_d_by_mesh' in r['warnings']
       and r['passport']['d_by_mesh']['mesh_d'] == 54.0 and r['passport']['d_by_mesh']['err'] == 0.0
       and calls == [('/g/2/model.glb', full['/g/2'])]) or print(r)
    r, _ = chair({"w": 49, "d": 54, "h": 82}, A, marked=False)
    ok('К2: без отметки «копия» — по-прежнему passport_mismatch:d', r['reasons'] == ['passport_mismatch:d'])
    r, _ = chair({'w': 49, 'd': 83, 'h': 82}, dict(A, long=0.49, short=0.48))
    ok('К2 Маргарита: паспорт d 83, меш 48 — блок остаётся, passport_d_by_mesh_rejected:err',
       r['reasons'] == ['passport_mismatch:d'] and 'passport_d_by_mesh_rejected:err' in r['warnings']
       and r['passport']['d_by_mesh']['mesh_d'] == 48.0) or print(r)
    r, _ = chair({'w': 49, 'd': 55, 'h': 82}, dict(A, long=0.60))      # 60.0 против 55: 9 % — в допуске; 62 против 55 — нет
    r2, _ = chair({'w': 49, 'd': 55, 'h': 82}, dict(A, long=0.62))
    ok('К2 допуск 12 % симметричный |п − м| / min: 55 против 60 — да, против 62 — нет',
       r['status'] == 'ready' and r2['status'] == 'blocked' and r2['passport']['d_by_mesh']['err'] == 0.127) or print(r2)
    r, _ = chair({'w': 49, 'd': None, 'h': 82}, A)
    ok('К2: паспорт без d у стула с глубиной-копией — plan_depth НЕ достраивает квадрат: passport_dim_missing:d, мерки нет',
       r['reasons'] == ['passport_dim_missing:d'] and 'passport_d_from_plan' not in r['warnings']
       and 'd_by_mesh' not in r['passport']) or print(r)
    r, _ = chair({"w": 49, "d": None, "h": 82}, A, marked=False)
    ok('К2: то же без отметки «копия» (прежнее правило) — квадрат из плана, ready', r['status'] == 'ready'
       and 'passport_d_from_plan' in r['warnings'])
    r, calls = chair({'w': 49, 'd': 110, 'h': 82}, A, role='кресло')
    ok('К2 кресло-кровать Босс (роль вне правила) — блок по d остаётся, меш не меряем',
       r['reasons'] == ['passport_mismatch:d'] and not calls and 'd_by_mesh' not in r['passport']) or print(r)
    for why, asp in (('mask', dict(A, mask='коллаж')), ('slab', dict(A, slab='merged')), ('measure', None),
                     ('scale', dict(A, h=0.60))):
        r, _ = chair({'w': 49, 'd': 54, 'h': 82}, asp)
        ok(f'К2: {why} — блок остаётся, passport_d_by_mesh_rejected:{why}',
           r['status'] == 'blocked' and f'passport_d_by_mesh_rejected:{why}' in r['warnings']) or print(r)
    r, calls = chair({'w': 56, 'd': 54, 'h': 82}, A)
    ok('К2: держит не только d (w тоже мимо) — не меряем', 'passport_mismatch:w' in r['reasons'] and not calls)
    Fq = {'quar': {'2:b': {full['/g/2'][:16]: 'cut'}}}
    r, calls = chair({'w': 49, 'd': 54, 'h': 82}, A, **Fq)
    ok('К2: модель в карантине — не меряем, блок', 'mesh_quarantine:cut' in r['reasons'] and 'passport_mismatch:d' in r['reasons']
       and not calls)
    Fo2 = {'orient': {k: (dict(v, status='review_pending') if k[0] == '2:b' else v) for k, v in F.orient.items()}}
    r, calls = chair({'w': 49, 'd': 54, 'h': 82}, A, **Fo2)
    ok('К2: другая причина (разворот не решён) — не меряем, d остаётся в причинах', not calls
       and 'passport_mismatch:d' in r['reasons'])
    # вариант семьи — глубину по мешу представителя не выводим (Codex: никогда по представителю)
    Fv = Facts(**{k: v for k, v in F.__dict__.items()})
    Fv.copy_d, Fv.aspect = {'6:v'}, (lambda p, s: dict(A, version='t'))
    v = bind('6:v', cat(6, 'v', 93, 93, 76, role='стул', origin='products', urls=('uv',)), Fv)
    ok('К2: вариант семьи (меш представителя) — правило не применяется', v['via_family']
       and 'family_passport_mismatch:d' in v['reasons'] and 'd_by_mesh' not in v['passport']) or print(v)
    # сантиметры — от ТЕКУЩЕЙ ширины каталога, кэш — только отношение сторон
    d1 = d_by_mesh('/x', 's', 54, [{'w': 49, 'd': 49, 'h': 82}], Facts(aspect=lambda p, s: dict(A, version='t')), pol)
    d2 = d_by_mesh('/x', 's', 54, [{'w': 45, 'd': 45, 'h': 82}], Facts(aspect=lambda p, s: dict(A, version='t')), pol)
    ok('К2: ширина каталога сменилась — глубина меша пересчитана от неё (54.0 → 49.6)',
       d1['mesh_d'] == 54.0 and d2['mesh_d'] == 49.6) or print(d1, d2)
    ac = {}
    asp_fn = make_aspect(ac, pol)
    ok('К2 make_aspect: нет файла — None, отказ в кэше по (версия замера, полный sha)',
       asp_fn('/нет/model.glb', 'f' * 64) is None and len(ac) == 1
       and next(iter(ac)).startswith(pol['passport']['d_by_mesh']['measurement_version'] + ':')
       and next(iter(ac)).endswith('|' + 'f' * 64))
    rows = [['112923:m2', 'Стул divan.ru Марти-2', 'стул', json.dumps(MP, ensure_ascii=False)],
            ['112923:gl', 'Стул Марти-3', 'стул', json.dumps(dict(MP, **{'Размеры: Глубина габаритная': '54см'}), ensure_ascii=False)],
            ['112923:nx', 'Стул вне каталога', 'стул', json.dumps(MP, ensure_ascii=False)]]
    cats_k = {'112923:m2': {'mid': 112923, 'dims': sq}, '112923:gl': {'mid': 112923, 'dims': sq},
              '99272:g': {'mid': 99272, 'dims': sq}}
    seen_q = []
    idx = copy_d_index(cats_k, pol, lambda qq: (seen_q.append(qq), rows)[1])
    ok('К2 copy_d_index: только товары каталога, ключ глубины в карточке — не копия; запрос по магазину и роли',
       idx == {'112923:m2'} and 'shop_mid in (112923)' in seen_q[0] and "cat_role in ('стул')" in seen_q[0]) or print(idx, seen_q)
    snap = assemble({'2:b': cat(2, 'b', 49, 49, 82, role='стул', urls=('u2',))},
                    Facts(**dict(F.__dict__, copy_d={'2:b'}, aspect=lambda p, s: dict(A, version='t'),
                                 manifest=lambda g: {'role': 'стул', 'input': {'dims_cm': {'w': 49, 'd': 54, 'h': 82}, 'image_url': 'u2'}}
                                 if g.get('path') == '/g/2' else F.manifest(g))), pol, G, {})
    ok('К2: снимок с разбором d_by_mesh проходит схему, политика v4', not validate(snap) and snap['policy_version'] == 'v4'
       and snap['offers']['2:b']['status'] == 'ready') or print(validate(snap))
    # ГЛУБИНА «ДЛЯ СЦЕНЫ» (T-20261107-25/9, план dims-effective-01): запись в снимок и читатель `effective_d`
    r, _ = chair({'w': 49, 'd': 54, 'h': 82}, A)
    e = r['passport'].get('effective_dims') or {}
    ok('сцена К2: вернувшийся стул — passport.effective_dims {d паспорта 54, источник, меш, ошибка, asset, ширина каталога 49}',
       e.get('d') == 54 and e.get('source') == 'passport_by_mesh' and e.get('mesh_d') == 54.0 and e.get('err') == 0.0
       and e.get('asset_id') == r['asset_id'] and e.get('catalog_w') == 49 and e.get('measurement') == 'raw2:t') or print(e)
    ok('сцена К2: снимок с effective_dims проходит схему', not validate(snap)
       and 'effective_dims' in snap['offers']['2:b']['passport']) or print(snap['offers']['2:b']['passport'])
    r2, _ = chair({'w': 49, 'd': 83, 'h': 82}, dict(A, long=0.49, short=0.48))
    ok('сцена К2: отказ К2 (ошибка вне допуска) — effective_dims нет', 'effective_dims' not in r2['passport']) or print(r2)
    r3, _ = chair({'w': 49, 'd': 54, 'h': 82}, A, marked=False)
    ok('сцена К2: без К2 — effective_dims нет', 'effective_dims' not in r3['passport'])
    pne = json.loads(json.dumps(pol))
    pne['passport']['d_by_mesh']['effective'] = False
    ok('сцена К2: флаг effective выключен — запись не делается',
       effective_dims(r['passport']['d_by_mesh'], r['asset_id'], [{'w': 49, 'd': 49, 'h': 82}], pne) is None)
    ms = r['mesh_id']
    ok('сцена К2 effective_d: ready, своя модель, каталог прежний (49×49) — глубина 54',
       effective_d(r, ms, 49, 49, pol) == 54) or print(r['mesh_id'], r['status'])
    ok('сцена К2 effective_d: флаг effective выключен (откат без пересборки) — None (каталог)',
       effective_d(r, ms, 49, 49, pne) is None)
    ok('сцена К2 effective_d: сцена грузит другую модель — None', effective_d(r, 'чужая_модель', 49, 49, pol) is None)
    ok('сцена К2 effective_d: ширина каталога сменилась больше 2 см (снимок устарел) — None; на 1,5 см — глубина',
       effective_d(r, ms, 45, 45, pol) is None and effective_d(r, ms, 50.5, 50.5, pol) == 54)
    ok('сцена К2 effective_d: магазин починил фид (глубина каталога больше не копия ширины) — None',
       effective_d(r, ms, 49, 52, pol) is None)
    ok('сцена К2 effective_d: строка не ready / вариант семьи / нет строки / нет поля — None',
       effective_d(dict(r, status='blocked'), ms, 49, 49, pol) is None
       and effective_d(dict(r, via_family=True), ms, 49, 49, pol) is None
       and effective_d(None, ms, 49, 49, pol) is None and effective_d(r3, r3['mesh_id'], 49, 49, pol) is None
       and effective_d(r, ms, None, 49, pol) is None)
    print('selftest:', 'OK' if not bad else f'{bad} FAIL')
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    if '--build' in argv:
        out = argv[argv.index('--out') + 1] if '--out' in argv else OUT_DIR
        prod = argv[argv.index('--prod') + 1] if '--prod' in argv else PROD_IDX
        snap, path, sec, n = build(out, prod, '--no-ssh' not in argv, '--dry' in argv)
        rep = report(snap)
        print(report_md(rep))
        print(f'снимок: {path} ({sec} с); current: {os.path.join(out, CURRENT)}; '
              + ('таблицу не трогали (--dry)' if n is None else f'таблица {TABLE}: {n} строк, snapshot_id {snap["content_sha"][:16]}'))
        line = digest_line(snap)
        print(line if '--digest' in argv else line.removeprefix('DIGEST:'), flush=True)   # в сводку — один раз за ночь
        if '--report-out' in argv:
            d = argv[argv.index('--report-out') + 1]
            os.makedirs(d, exist_ok=True)
            json.dump(rep, open(os.path.join(d, 'bindings-report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            open(os.path.join(d, 'bindings-report.md'), 'w', encoding='utf-8').write(report_md(rep))
            print(f'отчёт: {d}')
        return 0
    if '--report' in argv:
        i = argv.index('--report')
        path = argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith('--') else os.path.join(OUT_DIR, CURRENT)
        snap, why = load(path)
        if snap is None:
            print(f'снимка нет: {why} ({path})')
            return 1
        print(report_md(report(snap)))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
