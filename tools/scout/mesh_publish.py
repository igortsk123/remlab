#!/usr/bin/env python3
"""ПУБЛИКАЦИЯ МЕШЕЙ НА ПРОД: сделанное вчера должно быть видно в демо сегодня.

ЗАЧЕМ (разбор 13.10). Меши доезжали до базы и там останавливались: в базе 4 222 готовых модели,
а витрина решала «есть ли меш» по индексу `/test/mesh-pilot10/mesh-index.json`, где с пилота
лежало 590 и ничего не прибавлялось. Публикация жила ВНУТРИ волны за флагом
`MESH_SHOW_GALLERY=0` (решение владельца 31.08 «ночью не нужна, соберу утром руками») — и руками
её с тех пор никто не собрал. Волна 12.10 сделала 986 мешей, и ни один не появился в демо.

ПОЧЕМУ НЕ «ВЫЛОЖИТЬ ВСЁ». Склад мешей — 26 ГБ, на проде свободно 17 ГБ. Публикуем ровно то, что
витрина может показать: товары из комплектов `sets3.json` (372 штуки на все 126 наборов, из них
с готовым мешем 258). Набор ограничен по построению и растёт на единицы в сутки.

ПОРЯДОК ОБЯЗАТЕЛЕН: шаг идёт ПЕРЕД пересборкой демо (`flat215_demo.py`), иначе страница соберётся
по вчерашнему индексу и новые меши увидит только через сутки.

  ~/venvs/scout/bin/python mesh_publish.py          # собрать, выложить, слить индекс
  ~/venvs/scout/bin/python mesh_publish.py --dry    # только показать числа
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.join(HERE, 'salad')
PY = os.path.expanduser('~/venvs/scout/bin/python')
GALLERY = os.path.expanduser('~/scout-scenes/mesh-pilot-gallery')
SETS = os.path.join(HERE, 'sets3.json')
HOST = 'root@89.167.127.0'
PROD_DIR = '/opt/remlab/test/mesh-pilot10'
PROD_IDX = 'https://remont-lab.online/test/mesh-pilot10/mesh-index.json'
# Ниже этого порога на проде не публикуем: забитый диск роняет и сайт, и приёмник мешей.
MIN_FREE_GB = float(os.environ.get('MESH_PUBLISH_MIN_FREE_GB', '5'))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-tAc']


def sh(cmd: str, timeout: int = 1800) -> tuple[int, str]:
    r = subprocess.run(['bash', '-lc', cmd], capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def ready_skus() -> set[str]:
    """Ключи КАТАЛОГА МЕШЕЙ для товаров комплектов, у которых меш готов.

    Ключ — не артикул товара, а артикул ПРЕДСТАВИТЕЛЯ СЕМЕЙСТВА (ADR-0196): цветовые варианты
    своего меша не имеют и берут модель «родителя», и витрина ищет GLB именно по нему
    (`flat215_demo._msid`). Без этого перевода шаг честно считал «не хватает 61 модели», хотя
    все они лежат под ключом родителя — ровно та ложная тревога, из-за которой проверки
    перестают читать (урок 470).
    """
    sets = json.load(open(SETS, encoding='utf-8'))
    want = {f"{it['mid']}:{it['eid']}" for s in sets for _r, it in (s.get('items') or {}).items()
            if it and it.get('mid')}
    out = subprocess.run(
        PSQL + ["select shop_mid||':'||external_id||'~'||coalesce(mesh_family_rep,'') "
                "from products where mesh_uri is not null and mesh_status='ready'"],
        capture_output=True, text=True)
    keys = set()
    for line in out.stdout.split('\n'):
        if '~' not in line:
            continue
        sku, rep = line.strip().split('~', 1)
        if sku in want:
            keys.add(rep or sku)
    return keys


def prod_free_gb() -> float:
    code, out = sh(f"ssh -o BatchMode=yes -o ConnectTimeout=15 {HOST} \"df -BG --output=avail / | tail -1\"", 120)
    if code:
        return -1.0
    return float(''.join(c for c in out if c.isdigit() or c == '.') or 0)


def rebuild_index() -> tuple[int, str]:
    """Индекс = то, что РЕАЛЬНО лежит на сервере: перечисляем каталоги и пишем файл по списку.

    Прежний способ (привезти локальный индекс и слить с прежним) терял записи: копия уже затёрла
    то, с чем собиралась сливаться, — индекс витрины схлопнулся с 590 до 186 за один заход.
    Перечисление каталогов такой ошибки не допускает: индекс не может разойтись с файлами,
    потому что из них и строится. JSON собираем ЗДЕСЬ, на сервер уезжает готовый файл —
    вложенные кавычки в ssh уже стоили одного сломанного захода.
    """
    code, out = sh(f'ssh -o BatchMode=yes -o ConnectTimeout=20 {HOST} '
                   f'"find {PROD_DIR} -maxdepth 2 -name model.glb -printf \'%h\\n\'"', 600)
    if code:
        return code, out[:200]
    keys = sorted({l.strip().rsplit('/', 1)[-1] for l in out.splitlines() if l.strip()})
    if not keys:
        return 1, 'на сервере не нашлось ни одной модели — индекс не трогаю'
    tmp = os.path.join(HERE, '.mesh-index.json')
    json.dump({k: {} for k in keys}, open(tmp, 'w', encoding='utf-8'))
    code, out = sh(f'scp -q -o BatchMode=yes {tmp} {HOST}:{PROD_DIR}/mesh-index.json', 300)
    return code, (out[:160] if code else f'моделей на сервере {len(keys)}')


def main() -> int:
    dry = '--dry' in sys.argv
    skus = ready_skus()
    have = set(os.listdir(GALLERY)) if os.path.isdir(GALLERY) else set()
    missing = {s for s in skus if s.replace(':', '_') not in have}
    print(f'[публикация] в комплектах с готовым мешем: {len(skus)}; '
          f'в локальной галерее уже {len(skus) - len(missing)}; добавить {len(missing)}', flush=True)

    free = prod_free_gb()
    if free < 0:
        print('WARN:mesh_publish: прод не отвечает — публикацию пропускаю', flush=True)
        return 0
    if free < MIN_FREE_GB:
        print(f'WARN:mesh_publish: на проде свободно {free:.0f} ГБ (< {MIN_FREE_GB:.0f}) — '
              f'публикацию пропускаю, иначе забьём диск', flush=True)
        return 0
    if dry:
        print(f'[публикация] сухой заход: на проде свободно {free:.0f} ГБ, ничего не делаю', flush=True)
        return 0

    lst = os.path.join(HERE, '.mesh-publish-only.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(skus)))
    code, out = sh(f'GALLERY_ONLY={lst} GALLERY_SRC=$HOME/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2 '
                   f'{PY} {SALAD}/gallery_build.py', 3600)
    print(f'[публикация] галерея: код {code}; {out.splitlines()[-1][:160] if out else ""}', flush=True)
    if code:
        print('WARN:mesh_publish: галерея не собралась — на прод ничего не везу', flush=True)
        return 0

    # ИНДЕКС НЕ ВЕЗЁМ (13.10). rsync клал локальный `mesh-index.json` поверх прода, а слияние
    # следом читало уже ПОДМЕНЁННЫЙ файл и «сохраняло с прода 0»: индекс витрины схлопнулся с 590
    # до 186 за один заход. Индекс теперь не копируется, а пересобирается по тому, что реально
    # лежит на сервере, — такой способ не умеет терять записи.
    code, out = sh(f'rsync -a --info=stats1 --exclude=mesh-index.json '
                   f'-e "ssh -p 22222 -o BatchMode=yes" '
                   f'{GALLERY}/ {HOST}:{PROD_DIR}/', 3600)
    sent = [l for l in out.splitlines() if 'files transferred' in l or 'Number of' in l]
    print(f'[публикация] выложено: код {code}; {"; ".join(sent)[:200]}', flush=True)
    if code:
        print('WARN:mesh_publish: rsync на прод не прошёл', flush=True)
        return 0

    code, out = rebuild_index()
    print(f'[публикация] индекс пересобран по серверу: код {code}; {out[:160]}', flush=True)

    code, out = sh(f'curl -s -m 60 {PROD_IDX}', 120)
    try:
        n = len(json.loads(out))
    except Exception:  # noqa: BLE001
        n = -1
    print(f'[публикация] в индексе витрины на проде теперь моделей: {n}', flush=True)
    if n >= 0 and n < len(skus):
        print(f'WARN:mesh_publish: в индексе {n}, а показать можем {len(skus)} — слияние не доехало',
              flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
