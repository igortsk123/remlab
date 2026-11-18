#!/usr/bin/env python3
"""ЗАГОТОВКА ТЕКСТУР МЕШЕЙ ВИТРИНЫ ДЛЯ ВЫГРУЗКИ СЦЕНЫ (T-20261118-10/3 ❷, бесплатно, процессор DEV).

Зачем. Заказ «Сделать фото» со сменой товара считает сцену на DEV (`render_exec._prepare` → `cycles_probe/export_scene.py`). Меш НОВОГО товара, которого до этого не видели, стоит в заказе:
скачать GLB с галереи в кэш (`draft_render._scene3d_glb`, сеть) и закодировать его текстуры в PNG (`export_scene.ensure_png`, ≈0,5 с на текстуру 2048², две на диван). Всё это — содержимое
МЕША, а не заказа: считается один раз и лежит в общих кэшах по содержимому (`~/scout-cache/render-tex`), следующий заказ берёт готовое (повтор тех же пикселей — без кодирования).

Где в конвейере. Меш появляется на двух шагах: (1) привязка и публикация меша к товару витрины (`mesh_bind.py`, `mesh_publish.py` — ночная публикация, их не трогаем); (2) заготовка кадров
(`render_prewarm.py`, проход каждые `prewarm.interval_s`). Эта программа — идемпотентный шаг между ними: «по всем товарам витрины (предметы вариантов и корзины замены `feeds` в `demo-data.json`)
положить в кэш GLB и PNG текстур». Запуск: после публикации витрины и/или из прохода заготовки (одна строка `render_texwarm.warm_showcase()`); повторный запуск ничего не пересчитывает.
Сама программа в чужие шаги не встроена — место встройки выбирает директор.

Результат на заказе не меняется ни одним байтом: имена и содержимое файлов — те же, что кодировал бы заказ (общий путь `ensure_png`); проверяется сравнением `scene/` и тестом.

  ~/venvs/scout/bin/python tools/scout/render_texwarm.py [--limit N] [--dry] [--sid <msid> …]      → строка итога и ~/scout-cache/render-texwarm.json
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'cycles_probe')]

DEMO_DATA = os.environ.get('DEMO_DATA_FILE') or os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
STATUS_FILE = os.environ.get('RENDER_TEXWARM_STATUS') or os.path.expanduser('~/scout-cache/render-texwarm.json')
CACHE_FILL = 0.85               # GLB-кэш (потолок `rules/dev-tmp.json: mesh3d_cache_mb`) заполняем не выше этой доли — иначе заготовка вытесняет мешей, что нужны сейчас


def showcase_sids(data: dict) -> list:
    """Меши витрины: `msid`/`sid` предметов вариантов и товаров корзин замены (тем же правилом, что берёт выгрузка сцены: `msid`, иначе `sid`). Порядок стабильный, без повторов."""
    out: dict = {}

    def take(sku):
        sk = sku or {}
        sid = sk.get('msid') or sk.get('sid')
        if sid:
            out.setdefault(str(sid), None)

    for v in data.get('variants') or []:
        for it in v.get('items') or []:
            take(it.get('sku'))
            if it.get('msid'):
                out.setdefault(str(it['msid']), None)
    for items in (data.get('feeds') or {}).values():
        for it in items or []:
            take(it if ('msid' in it or 'sid' in it) else it.get('sku'))
    return list(out)


def warm_mesh(glb: str) -> dict:
    """Все текстуры меша (цвет и шероховатость/металл) → PNG в общий кэш. → {'tex': сколько, 'new': сколько закодировано сейчас}."""
    import numpy as np
    import export_scene as ES
    import mesh_render as MR
    n = new = 0
    for m in MR.load_parts(glb):
        mat = getattr(getattr(m, 'visual', None), 'material', None)
        img, _uv = ES._tex_image(m)
        if img is None:
            continue
        for im in (img, getattr(mat, 'metallicRoughnessTexture', None)):
            if im is None:
                continue
            _h, key, _shape = ES._tex_memo(im)[1:4]
            had = os.path.isfile(os.path.join(ES.TEX_CACHE, key))
            ES.ensure_png(lambda im=im: np.asarray(im.convert('RGB')), key=key)
            n += 1
            new += 0 if had else 1
    return {'tex': n, 'new': new}


def _glb_cache_full() -> bool:
    import draft_render as DR
    try:
        cap = float(json.load(open(os.path.join(HERE, 'rules', 'dev-tmp.json'), encoding='utf-8')).get('mesh3d_cache_mb') or 600)
        total = sum(os.path.getsize(os.path.join(DR.SCENE3D_CACHE, f)) for f in os.listdir(DR.SCENE3D_CACHE)) / 2 ** 20
        return total > cap * CACHE_FILL
    except (OSError, ValueError):
        return False


def warm_showcase(sids: list | None = None, limit: int | None = None, dry: bool = False, log=print) -> dict:
    import draft_render as DR
    if sids is None:
        sids = showcase_sids(json.load(open(DEMO_DATA, encoding='utf-8')))
    t0 = time.time()
    st = {'ts': int(t0), 'sids': len(sids), 'warmed': 0, 'already': 0, 'no_mesh': 0, 'cache_full': 0, 'png_new': 0, 'png_total': 0, 'dry': dry}
    for i, sid in enumerate(sids):
        if limit is not None and st['warmed'] + st['already'] >= limit:
            break
        if _glb_cache_full():
            st['cache_full'] = len(sids) - i
            log(f'  GLB-кэш заполнен на {int(CACHE_FILL * 100)} % — остальные {st["cache_full"]} мешей заготовке не нужны, стоп')
            break
        glb = os.path.join(DR.SCENE3D_CACHE, sid + '.glb')
        have = os.path.exists(glb) and os.path.getsize(glb) > 1000
        if dry:
            st['already' if have else 'warmed'] += 1
            continue
        glb = DR._scene3d_glb(sid)
        if not glb:
            st['no_mesh'] += 1                  # у товара нет меша на галерее — заготовки нет
            continue
        r = warm_mesh(glb)
        st['png_total'] += r['tex']
        st['png_new'] += r['new']
        st['already' if (r['new'] == 0 and have) else 'warmed'] += 1
    st['sec'] = round(time.time() - t0, 1)
    if not dry:
        try:
            os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
            with open(STATUS_FILE, 'w', encoding='utf-8') as f:
                json.dump(st, f, ensure_ascii=False)
        except OSError:
            pass
    log(f"заготовка текстур: мешей {st['sids']}, готовых {st['already']}, доложено {st['warmed']}, без меша {st['no_mesh']}, PNG {st['png_total']} (новых {st['png_new']}), {st['sec']} с")
    return st


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int)
    ap.add_argument('--dry', action='store_true', help='только посчитать, что докладывать (ничего не скачиваем и не кодируем)')
    ap.add_argument('--sid', nargs='*', help='конкретные msid/sid вместо всей витрины')
    a = ap.parse_args()
    warm_showcase(a.sid or None, a.limit, a.dry)
