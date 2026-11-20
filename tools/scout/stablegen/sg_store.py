"""Выход покраски StableGen → склад мешей (план painted-to-rt-01, п. (а); T-20261120-150/1).

ЗАЧЕМ. Покраска писала только `<папка прогона>/blender/painted.glb` в `~/remlab-logs/...`. Конвейер лёгких копий и галерея мешей берут модель
из СКЛАДА (`<склад>/<товар>/<прогон>/{model.glb, manifest.json}`, роль-стратегия по манифесту), поэтому крашеную они не видели: новый генератор
обязан писать в склад сразу (урок плана). Склад покраски лежит рядом со складом Hunyuan, его путь и источник — данные
`rules/asset-strategies.json:painted_source`; галерея (`salad/gallery_build.py`) читает оба.

ЧТО В МАНИФЕСТЕ: sku (`mid:eid`), role (из cfg.json прогона — `cat_role`), source (из канона), variant, run, sha256/bytes модели, guard.
`guard` — итог сторожа покрытия текстуры: пока сторожа под 8 камер StableGen нет, пишется `none` → крашеная НЕ побеждает Hunyuan
(`gallery_build.painted_winners`); сторож потом ставит `pass` через `set_guard`. Время файла для выбора не используется.

ЧТО ЧИСТИТ: в склад кладутся только `model.glb` и `manifest.json` (копия ≈1,5–16 МБ); `session.blend` и промежуточное уже убрал `sg_queue.slim_run`.
Запись атомарная (временный файл рядом → `os.replace`), манифест — последним: папка без манифеста галерее не видна."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, '..', 'rules', 'asset-strategies.json')


def painted_cfg(path: str = RULES) -> dict:
    """Блок `painted_source` канона: source, store, guard_pass, guard_none (канон — один файл, `asset_strategy.painted_source` читает его же)."""
    return json.load(open(path, encoding='utf-8'))['painted_source']


def store_root(cfg: dict | None = None) -> str:
    return os.path.expanduser(os.environ.get('PAINTED_STORE') or (cfg or painted_cfg())['store'])


def _atomic_write(path: str, data: bytes) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(data)
    os.replace(tmp, path)


def store_run(it: dict, cfg: dict | None = None, root: str | None = None) -> dict:
    """Успешный прогон `it` (key, variant, label, dir) → склад: `<склад>/<товар>/<имя папки прогона>/{model.glb, manifest.json}`.
    Возвращает поля для записи прогона (`stored`, `guard`). Нет `painted.glb` — FileNotFoundError (вызывающий не молчит)."""
    cfg = cfg or painted_cfg()
    glb = os.path.join(it['dir'], 'blender', 'painted.glb')
    if not os.path.isfile(glb):
        raise FileNotFoundError(f'нет {glb}')
    run_cfg: dict = {}
    try:
        run_cfg = json.load(open(os.path.join(it['dir'], 'cfg.json'), encoding='utf-8'))
    except (OSError, ValueError):
        pass                                            # роль неизвестна — пустая (стратегия по умолчанию), прогон не роняем
    prod = it['key'].partition('@')[0]                  # «товар@форма» → товар `mid_eid`
    sku = prod.replace('_', ':', 1)
    dest = os.path.join(root or store_root(cfg), prod, os.path.basename(it['dir'].rstrip('/')))
    os.makedirs(dest, exist_ok=True)
    data = open(glb, 'rb').read()
    _atomic_write(os.path.join(dest, 'model.glb'), data)
    man = {'sku': sku, 'role': run_cfg.get('cat_role') or '', 'source': cfg['source'], 'variant': it['variant'], 'label': it.get('label'),
           'run': os.path.basename(it['dir'].rstrip('/')), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
           'guard': cfg['guard_none'], 'stored_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    _atomic_write(os.path.join(dest, 'manifest.json'), json.dumps(man, ensure_ascii=False, indent=1).encode('utf-8'))
    return {'stored': dest, 'guard': man['guard']}


def set_guard(dest: str, status: str, report: dict | None = None) -> None:
    """Итог сторожа покрытия текстуры → манифест записи склада (`pass` — крашеная может победить Hunyuan; иное — нет)."""
    p = os.path.join(dest, 'manifest.json')
    man = json.load(open(p, encoding='utf-8'))
    man['guard'] = status
    if report is not None:
        man['guard_report'] = report
    _atomic_write(p, json.dumps(man, ensure_ascii=False, indent=1).encode('utf-8'))


def drop_run(dest: str, root: str | None = None) -> bool:
    """Убрать запись склада (отказанную/ошибочную). Только внутри склада — за его пределами не трогаем."""
    r = os.path.realpath(root or store_root())
    d = os.path.realpath(dest)
    if os.path.commonpath([r, d]) != r or d == r:
        raise ValueError(f'{dest} не внутри склада {r}')
    if os.path.isdir(d):
        shutil.rmtree(d)
        return True
    return False
