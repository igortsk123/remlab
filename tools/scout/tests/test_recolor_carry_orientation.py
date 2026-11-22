"""ПЕРЕНОС ОРИЕНТАЦИИ ПОСЛЕ ПЕРЕКРАСКИ (`salad/recolor_carry_orientation.py`, T-20261118-52/5): на синтетических GLB, без базы и сети.
Случаи: ① геометрия та же, текстура другая → строка нового ключа = копия старой (`source=recolor_copy`, ссылка на старый ключ);
② геометрия изменилась → ничего не вставляем; ③ защитные: нет строки у старого, источник «headboard_flip»/«symmetric_by_role»,
повтор (строка уже есть), без --apply ничего не пишется.
    python tools/scout/tests/test_recolor_carry_orientation.py   (нужен только numpy)
Временные файлы — во временной папке процесса (`remlab_tmp.use`)."""
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'salad'))
sys.path.insert(0, os.path.join(HERE, '..'))
import recolor_carry_orientation as C  # noqa: E402
import remlab_tmp  # noqa: E402
TMP = remlab_tmp.use('test_recolor_carry_orientation')   # временное — на диске, убирается при выходе (T-20261107-13)

fails = []


def check(name, cond, extra=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f'  [{extra}]' if extra else ''))
    if not cond:
        fails.append(name)


def glb_bytes(pos: np.ndarray, idx: np.ndarray, image: bytes, stride_pad: int = 0) -> bytes:
    """Минимальный GLB: один примитив (позиции + индексы) и «картинка» в буфере — для проверки, что хеш её не видит."""
    pos = pos.astype('<f4')
    if stride_pad:                                                  # позиции с byteStride > 12 (чужая раскладка буфера)
        rows = np.zeros((len(pos), 12 + stride_pad), np.uint8)
        rows[:, :12] = pos.view(np.uint8).reshape(len(pos), 12)
        pb, stride = rows.tobytes(), 12 + stride_pad
    else:
        pb, stride = pos.tobytes(), None
    ib = idx.astype('<u2').tobytes()
    ib += b'\0' * (-len(ib) % 4)
    img = image + b'\0' * (-len(image) % 4)
    blob = pb + ib + img
    bv0 = {'buffer': 0, 'byteOffset': 0, 'byteLength': len(pb)}
    if stride:
        bv0['byteStride'] = stride
    js = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(blob)}],
          'bufferViews': [bv0, {'buffer': 0, 'byteOffset': len(pb), 'byteLength': len(ib)},
                          {'buffer': 0, 'byteOffset': len(pb) + len(ib), 'byteLength': len(img)}],
          'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': len(pos), 'type': 'VEC3'},
                        {'bufferView': 1, 'componentType': 5123, 'count': len(idx), 'type': 'SCALAR'}],
          'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
          'images': [{'bufferView': 2, 'mimeType': 'image/png'}]}
    j = json.dumps(js).encode()
    j += b' ' * (-len(j) % 4)
    return (struct.pack('<4sII', b'glTF', 2, 12 + 8 + len(j) + 8 + len(blob)) + struct.pack('<II', len(j), 0x4E4F534A) + j
            + struct.pack('<II', len(blob), 0x004E4942) + blob)


class Mem:
    """База в памяти вместо `mesh_queue.db`: обрабатывает ровно три запроса модуля."""

    def __init__(self, rows):
        self.rows, self.log = dict(rows), []

    def q(self, s):
        return "'" + str(s) + "'"

    def db(self, sql):
        self.log.append(sql)
        if sql.startswith('select 1 from orientation_state'):
            k = sql.split("'")[1]
            return [['1']] if k in self.rows else []
        if sql.startswith('select status, resolution::text'):
            k = sql.split("'")[1]
            return [[self.rows[k][0], json.dumps(self.rows[k][1])]] if k in self.rows else []
        if sql.startswith('insert into orientation_state'):
            k = sql.split("'")[1]
            self.rows.setdefault(k, ('inserted', {}))
            return []
        raise AssertionError(sql)


def put(name, data):
    p = os.path.join(TMP, name)
    open(p, 'wb').write(data)
    return p


rng = np.random.default_rng(3)
POS = rng.normal(0, 1, (40, 3))
IDX = np.arange(0, 39, dtype=np.uint16)
SKU = '112923:1'
orig = put('orig.glb', glb_bytes(POS, IDX, b'tex-original'))
recol = put('recol.glb', glb_bytes(POS, IDX, b'tex-RECOLORED-longer-bytes'))
strided = put('strided.glb', glb_bytes(POS, IDX, b'x', stride_pad=4))
moved = put('moved.glb', glb_bytes(POS + np.array([0, 0, 0.01]), IDX, b'tex-original'))
fewer = put('fewer.glb', glb_bytes(POS, IDX[:30], b'tex-original'))

# ── хеш геометрии ──────────────────────────────────────────────────────────────────────────────────────────────────
check('хеш геометрии не зависит от текстуры и раскладки буфера', C.geometry_hash(orig) == C.geometry_hash(recol) == C.geometry_hash(strided))
check('сдвиг одной вершины меняет хеш', C.geometry_hash(orig) != C.geometry_hash(moved))
check('другие индексы меняют хеш', C.geometry_hash(orig) != C.geometry_hash(fewer))
check('sha файла у перекрашенного другой', C.file_sha(orig) != C.file_sha(recol))

old_rk = f'{SKU}|{C.file_sha(orig)[:16]}|orient-v1'
OLD_RES = {'contract': 'orient-v1', 'sku': SKU, 'glb': 'model.glb', 'glb_sha': C.file_sha(orig), 'status': 'auto_resolved',
           'source': 'orienter+vlm_agree', 'role': 'комод', 'legacy_front_yaw': 0,
           'raw_to_canonical_quat_wxyz': [0.0, 0.0, 1.0, 0.0]}
RES_DIR = os.path.join(TMP, 'res')

# ── ① геометрия совпала → копия ────────────────────────────────────────────────────────────────────────────────────
m = Mem({old_rk: ('auto_resolved', OLD_RES)})
r = C.carry(SKU, orig, recol, db=m.db, q=m.q, res_dir=RES_DIR, apply=True)
new_rk = f'{SKU}|{C.file_sha(recol)[:16]}|orient-v1'
check('совпала: действие copy, ключ нового файла', r['action'] == 'copy' and r['new_rk'] == new_rk, str(r.get('why')))
check('совпала: вставлена ровно одна строка нового ключа, старая осталась', new_rk in m.rows and old_rk in m.rows and sum(s.startswith('insert') for s in m.log) == 1)
res = r['resolution']
check('копия: source=recolor_copy, glb_sha нового файла, ссылка на старый ключ, поворот тот же',
      res['source'] == 'recolor_copy' and res['glb_sha'] == C.file_sha(recol) and res['carried_from'] == old_rk
      and res['carried_source'] == 'orienter+vlm_agree' and res['raw_to_canonical_quat_wxyz'] == OLD_RES['raw_to_canonical_quat_wxyz']
      and res['status'] == 'auto_resolved', str(res)[:120])
fp = r.get('written', '')
check('файл решения записан рядом', fp.endswith('__orient-v1.json') and json.load(open(fp))['carried_from'] == old_rk)

m2 = Mem({old_rk: ('auto_resolved', OLD_RES)})
r2 = C.carry(SKU, orig, recol, db=m2.db, q=m2.q, res_dir=RES_DIR, apply=False)
check('без --apply: БД не пишется (только чтение), решение показано', r2['action'] == 'copy' and not any(s.startswith('insert') for s in m2.log))

m3 = Mem({old_rk: ('auto_resolved', OLD_RES), new_rk: ('auto_resolved', {})})
r3 = C.carry(SKU, orig, recol, db=m3.db, q=m3.q, res_dir=RES_DIR, apply=True)
check('повтор: строка нового ключа уже есть — не трогаем', r3['action'] == 'already' and not any(s.startswith('insert') for s in m3.log))

# ── ② геометрия не совпала → ничего ────────────────────────────────────────────────────────────────────────────────
for nm, f in (('сдвиг вершины', moved), ('другие индексы', fewer)):
    m4 = Mem({old_rk: ('auto_resolved', OLD_RES)})
    r4 = C.carry(SKU, orig, f, db=m4.db, q=m4.q, res_dir=RES_DIR, apply=True)
    check(f'геометрия изменилась ({nm}): ничего не вставлено, «→ orient_worker»',
          r4['action'] == 'skip' and 'orient_worker' in r4['why'] and not m4.log, r4['why'])

# ── ③ защитные ─────────────────────────────────────────────────────────────────────────────────────────────────────
m5 = Mem({})
r5 = C.carry(SKU, orig, recol, db=m5.db, q=m5.q, res_dir=RES_DIR, apply=True)
check('у старого файла нет строки ориентации — не выдумываем', r5['action'] == 'skip' and not any(s.startswith('insert') for s in m5.log), r5['why'])
for src in ('headboard_flip', 'headboard_sideways'):
    m6 = Mem({old_rk: ('auto_resolved', {**OLD_RES, 'source': src})})
    r6 = C.carry(SKU, orig, recol, db=m6.db, q=m6.q, res_dir=RES_DIR, apply=True)
    check(f'источник «{src}» не копируется', r6['action'] == 'skip' and not any(s.startswith('insert') for s in m6.log), r6['why'])
# симметрия по роли: копия сохраняет source и role_policy (устаревание по ролям продолжает работать)
SYM = {**OLD_RES, 'source': 'symmetric_by_role', 'role_policy': 'roles-28dac485', 'role': 'пуф'}
m8 = Mem({old_rk: ('auto_resolved', SYM)})
r8 = C.carry(SKU, orig, recol, db=m8.db, q=m8.q, res_dir=RES_DIR, apply=True)
check('symmetric_by_role: копия с СОХРАНЁННЫМ source и role_policy, carried_* добавлены',
      r8['action'] == 'copy' and r8['resolution']['source'] == 'symmetric_by_role' and r8['resolution']['role_policy'] == 'roles-28dac485'
      and r8['resolution']['carried_source'] == 'symmetric_by_role' and r8['resolution']['carried_from'] == old_rk
      and new_rk in m8.rows, str(r8.get('why')))
r7 = C.carry(SKU, orig, orig, db=m.db, q=m.q, res_dir=RES_DIR, apply=True)
check('тот же файл (sha совпал) — переносить нечего', r7['action'] == 'skip')

print('---', 'FAIL: ' + ', '.join(fails) if fails else 'всё OK')
sys.exit(1 if fails else 0)
