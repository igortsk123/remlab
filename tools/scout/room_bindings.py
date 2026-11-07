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
  appearance — свой меш; у варианта семьи — цвет обоих известен и в одной группе;
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
        self.quar = {}                       # {sku: {glb_sha16: решение}} — карантин моделей (`mesh_quarantine` cut/reject)
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


def offer_binding(sku: str, cat: dict, F: Facts, pol: dict, groups: dict, assets: dict, families: dict) -> dict | None:
    """Привязка одного товара. cat — {mid, eid, name, dims:[…], footprint_required, footprint_ok, urls:set, seen_in:[…], roles:set}.
    None — у товара нет ни своего кандидата меша, ни семьи (в снимок не попадает: адаптер скажет none)."""
    own_revs = F.revs.get(sku) or []
    frep, ffid, ffam_why = family_of(sku, F)
    rep_mesh = frep is not None and (bool(ffam_why) or bool(F.revs.get(frep)) or frep in F.gen_skus)
    if not own_revs and sku not in F.gen_skus and not rep_mesh:
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
    pp = passport_check(rec['passport']['dims_cm'], cat['dims'], pol, 'family_passport' if via else 'passport') if rec else []
    local += pp
    roles = set(cat.get('roles') or ()) | ({rec['passport']['role']} if rec and rec['passport'].get('role') else set())
    ori = (rec or {}).get('orientation') or {}
    if ori.get('source') == 'symmetric_by_role' and not any(x.startswith('orientation') for x in (rec or {}).get('reasons', [])):
        if any(F.directed(r, cat.get('name') or '') for r in roles):
            local.append('orientation_symmetric_by_role')
        else:
            warn.append('orientation_by_role_only')
    solver_why = []
    if not cat['dims'] or not all(d.get('w') and d.get('d') and d.get('h') for d in cat['dims']):
        solver_why.append('catalog_dims_missing')
    if cat.get('footprint_required') and not cat.get('footprint_ok'):
        solver_why.append('footprint_unverified')
    app_ok, app_why = appearance(sku, rep, F, groups)
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
                         'catalog_dims': cat['dims'], 'hash': dims_hash(cat['dims'], pol['passport']['keys'])},
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
    """Привязка держит товар ТОЛЬКО из-за нерешённого разворота (`orientation_*`, в т.ч. представителя `rep:orientation_*`)."""
    return bool(reasons) and all(str(r).split(':')[-1].startswith('orientation_') for r in reasons)


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


def scene_msid(row: dict | None, sid: str, rep: dict) -> str:
    """Какую модель грузит сцена ЛЮБОЙ КОМНАТЫ (спальня — T-20261106-77/4, вариант А ведущего; гостиная — `flat215_demo._msid`,
    T-77/5 шаг 3): модель привязки (`mesh_id` строки `offer_asset_binding`), её нет — представитель семейства (`mesh_rep`,
    иначе свой артикул). Все через `_`.
    Зачем: привязка проверяет СВОЮ ревизию товара (своё текущее фото), а `mesh_rep` давал модель представителя — `usable` такой
    предмет отбрасывал («сцена грузит X, привязка проверила Y»), хотя своя модель выложена (Теджонс/Ханна/Монсон Латте,
    Модерн Терракотовый); у гостиной представитель — другой цвет той же формы (лист T-77/5: своя ближе к фото почти везде).
    Свои модели гостиной выкладывает `room_publish` (ROOM_PUBLISH=living).
    ФАЙЛА МОДЕЛИ У ПРИВЯЗКИ НЕТ (`local_3d` ложно) — тоже представитель (T-77/5 шаг 3, сухой прогон): у 49 заблокированных строк
    гостиной `mesh_id` — свой артикул без файла; правило без этой оговорки сняло бы модель у 46 товаров лент и у стола варианта
    set16. Спальне вердикт сторожа не меняет (128 из 128 товаров банка — тот же): такой предмет отбрасывается и так."""
    r = row or {}
    m = r.get('mesh_id')
    return m.replace(':', '_', 1) if m and r.get('local_3d') else rep.get(sid, sid)


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
    F = Facts(revs=revs, gens=gens, orient=orient, ppc=ppc, products=products, two_reps=two, colour=colour, prod=prod,
              contract=OW.CONTRACT, directed=lambda role, name='': OW.directed_role(role, name, ''),
              manifest=manifest, glb=make_glb(cache), quar=quar)
    import mesh_queue as MQ
    sources = {'asset_revisions': _digest(revs), 'mesh_generations': _digest(gens), 'orientation_state': _digest(sorted(orient.items())),
               'product_photo_current': _digest(ppc), 'products_mesh': _digest(products), 'enrichment_colour': _digest(colour),
               'mesh_quarantine': _digest(quar),
               'policy': _digest(pol), 'orient_contract': OW.CONTRACT, 'directed_roles': sorted(MQ.DIRECTED),
               'prod': {'source': prod_why, 'digest': _digest(prod)}}
    return F, pol, MDK.COLOUR_GROUPS, sources, cache, cache_p


def build(out_dir: str, prod_src: str, ssh: bool, dry: bool = False) -> tuple:
    t = time.time()
    os.makedirs(out_dir, exist_ok=True)
    F, pol, groups, sources, cache, cache_p = load_facts(prod_src, ssh, out_dir)
    cats = catalog_offers()
    sources['catalog_offers'] = _digest({k: [v['dims'], sorted(v['urls']), v['footprint_ok']] for k, v in cats.items()})
    snap = assemble(cats, F, pol, groups, sources)
    _atomic_write(cache_p, json.dumps(cache, sort_keys=True).encode())
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
       and not w['capabilities']['appearance'] and w['reasons'] == ['family_colour_mismatch:чёрный→светлый'])
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
    ok('scene_msid: модель привязки (есть файл) · файла нет — представитель · строки нет — представитель / свой артикул',
       scene_msid({'mesh_id': '7:c', 'local_3d': True}, '7_c', rmap) == '7_c'
       and scene_msid({'mesh_id': '7:c', 'local_3d': False, 'status': 'blocked'}, '7_c', rmap) == '7_r'
       and scene_msid(None, '7_c', rmap) == '7_r' and scene_msid(None, '8_d', rmap) == '8_d')
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
