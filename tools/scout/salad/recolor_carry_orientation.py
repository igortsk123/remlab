#!/usr/bin/env python3
"""ПЕРЕНОС ОРИЕНТАЦИИ ПОСЛЕ ПЕРЕКРАСКИ (T-20261118-52/5; правило директора: не ручной INSERT, а шаг в коде).

ЗАЧЕМ. Ориентация меша (`orientation_state`) хранится по ключу `sku|sha16 файла|orient-v1`. Перекраска (`recolor_lp.py`) меняет
только текстуру — геометрия та же, — но sha файла другой, и привязка комнат (`room_bindings`) для нового файла видит
`orientation_missing` и блокирует модель. Прогонять каскад ориентации заново (`orient_worker`) ради неизменной геометрии
незачем (и он берёт всю очередь, а не одну модель), поэтому: СРАВНИВАЕМ ГЕОМЕТРИЮ и, если она совпала, кладём строку для нового
ключа копией старой.

ПРАВИЛО.
  • хеш геометрии = sha256 по позициям вершин и индексам всех примитивов (значения, не байты файла: без текстур, материалов,
    раскладки буфера) — одинаков у оригинала и перекрашенной копии;
  • совпал → строка `orientation_state` нового ключа = копия строки старого (то же `status`, тот же поворот), в решении:
    `glb_sha` нового файла, `source = recolor_copy`, `carried_from` (старый ключ), `carried_source`, `carried_geometry_sha`;
    файл решения рядом (как у `orient_worker.store`); старая строка остаётся;
  • не совпал → НИЧЕГО не копируем, печатаем «геометрия изменилась → orient_worker»;
  • не копируем и решения, которым копия повредит: `headboard_sideways/headboard_flip` (блок кровати) и `symmetric_by_role`
    (их устаревание по ролям ловится по этому источнику) — для них «→ orient_worker»;
  • уже есть строка нового ключа — не трогаем (`already`).

  ~/venvs/scout/bin/python recolor_carry_orientation.py <sku> <старый.glb> <новый.glb> [--apply]   # без --apply — только печать
Модуль ничего не пишет в БД, пока нет --apply (чтение — да). Тест: `tools/scout/tests/test_recolor_carry_orientation.py`."""
from __future__ import annotations

import hashlib
import json
import os
import struct
import sys

import numpy as np

CONTRACT = 'orient-v1'
SOURCE = 'recolor_copy'
NO_COPY_SOURCES = ('headboard_sideways', 'headboard_flip', 'symmetric_by_role')
RES_DIR = os.path.join(os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes')), 'orientation', 'v1')
_DT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def _read_glb(path: str) -> tuple[dict, bytes]:
    data = open(path, 'rb').read()
    magic, _ver, _ln = struct.unpack('<4sII', data[:12])
    if magic != b'glTF':
        raise ValueError(f'{path}: не GLB')
    off, js, bn = 12, None, b''
    while off + 8 <= len(data):
        cl, ct = struct.unpack('<II', data[off:off + 8])
        chunk = data[off + 8:off + 8 + cl]
        if ct == 0x4E4F534A:
            js = json.loads(chunk)
        elif ct == 0x004E4942:
            bn = chunk
        off += 8 + cl
    if js is None:
        raise ValueError(f'{path}: нет JSON-блока')
    return js, bn


def _accessor(js: dict, bn: bytes, i: int) -> np.ndarray:
    a = js['accessors'][i]
    if 'sparse' in a or 'bufferView' not in a:
        raise ValueError('аксессор sparse/без буфера не поддержан')
    bv = js['bufferViews'][a['bufferView']]
    dt, n, cnt = np.dtype(_DT[a['componentType']]), _NC[a['type']], int(a['count'])
    base = int(bv.get('byteOffset', 0)) + int(a.get('byteOffset', 0))
    stride = int(bv.get('byteStride') or n * dt.itemsize)
    buf = np.frombuffer(bn, dtype=np.uint8)
    rows = np.lib.stride_tricks.as_strided(buf[base:], shape=(cnt, n * dt.itemsize), strides=(stride, 1))
    return np.ascontiguousarray(rows).view(dt).reshape(cnt, n)


def geometry_hash(path: str) -> str:
    """sha256 по позициям вершин (float32) и индексам (uint32) всех примитивов, в порядке мешей. Текстуры и материалы не входят."""
    js, bn = _read_glb(path)
    h = hashlib.sha256()
    for m in js.get('meshes', []):
        for p in m.get('primitives', []):
            pos = _accessor(js, bn, p['attributes']['POSITION']).astype('<f4')
            h.update(struct.pack('<II', pos.shape[0], 0xA11CE))
            h.update(pos.tobytes())
            if p.get('indices') is not None:
                idx = _accessor(js, bn, p['indices']).astype('<u4')
                h.update(struct.pack('<II', idx.shape[0], 0x1D1CE))
                h.update(idx.tobytes())
            else:
                h.update(b'noidx')
    return h.hexdigest()


def file_sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _default_db():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    import mesh_queue as MQ  # noqa: E402 — тяжёлый модуль; только боевой путь
    return MQ.db, MQ.q


def carry(sku: str, old_glb: str, new_glb: str, db=None, q=None, res_dir: str = RES_DIR, apply: bool = False) -> dict:
    """→ {action: copy|already|skip, why, old_rk, new_rk, geometry_sha, resolution?}. `db(sql)` → строки (списки), `q(str)` → литерал."""
    if db is None:
        db, q = _default_db()
    old_full, new_full = file_sha(old_glb), file_sha(new_glb)
    old_rk, new_rk = f'{sku}|{old_full[:16]}|{CONTRACT}', f'{sku}|{new_full[:16]}|{CONTRACT}'
    out = {'sku': sku, 'old_rk': old_rk, 'new_rk': new_rk}
    g_old, g_new = geometry_hash(old_glb), geometry_hash(new_glb)
    out['geometry_sha'] = g_old[:16]
    if g_old != g_new:
        return {**out, 'action': 'skip', 'why': 'геометрия изменилась → orient_worker'}
    if old_full == new_full:
        return {**out, 'action': 'skip', 'why': 'файл тот же (sha совпал) — переносить нечего'}
    if db(f'select 1 from orientation_state where revision_key = {q(new_rk)}'):
        return {**out, 'action': 'already', 'why': 'строка нового ключа уже есть — не трогаю'}
    rows = db(f'select status, resolution::text from orientation_state where revision_key = {q(old_rk)}')
    if not rows:
        return {**out, 'action': 'skip', 'why': 'у старого файла нет строки ориентации → orient_worker'}
    status, txt = rows[0][0], rows[0][1]
    res = json.loads(txt)
    if res.get('source') in NO_COPY_SOURCES:
        return {**out, 'action': 'skip', 'why': f"источник «{res.get('source')}» копировать нельзя → orient_worker"}
    new_res = {**res, 'glb_sha': new_full, 'source': SOURCE, 'carried_from': old_rk, 'carried_source': res.get('source'),
               'carried_geometry_sha': g_old[:16], 'task': 'T-20261118-52/5'}
    out.update(action='copy', why='геометрия совпала — копия строки старого файла', status=status, resolution=new_res)
    if apply:
        fp = os.path.join(res_dir, new_rk.replace(':', '_').replace('|', '__') + '.json')
        os.makedirs(res_dir, exist_ok=True)
        json.dump(new_res, open(fp + '.tmp', 'w'), ensure_ascii=False, indent=1)
        os.replace(fp + '.tmp', fp)
        db(f"insert into orientation_state (revision_key, sku, status, resolution) values ({q(new_rk)}, {q(sku)}, "
           f"{q(status)}, {q(json.dumps(new_res, ensure_ascii=False))}::jsonb) on conflict (revision_key) do nothing")
        out['written'] = fp
    return out


def main() -> int:
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if len(a) != 3:
        print(__doc__)
        return 2
    r = carry(a[0], a[1], a[2], apply='--apply' in sys.argv)
    res = r.pop('resolution', None)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    if res:
        keep = {k: res[k] for k in ('glb_sha', 'source', 'carried_from', 'carried_source', 'carried_geometry_sha', 'status', 'role',
                                    'legacy_front_yaw') if k in res}
        print(('ЗАПИСАНО' if 'written' in r else 'СУХО — вставил бы') + ' в orientation_state:', json.dumps(keep, ensure_ascii=False))
    return 0 if r['action'] in ('copy', 'already') else 1


if __name__ == '__main__':
    sys.exit(main())
