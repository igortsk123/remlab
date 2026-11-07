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

БАНК-КАНДИДАТ (T-20261021-09/4). Новый банк собирается рядом (`sets3.next.json`, `bank_paths`), и до подмены демо на нём
не видело моделей его новых товаров: шаг публиковал только товары живого банка. С `SETS_BANK=<банк>` публикуются товары
ЖИВОГО банка И кандидата — объединение, а не замена: галерея пишет локальный `mesh-index.json` и страницы по списку
отбора, и список «только кандидат» сжал бы их. На прод rsync идёт без `--delete`, индекс пересобирается по папкам
сервера — модели живого демо не пропадают. Без `SETS_BANK` — как раньше, только живой банк.

  ~/venvs/scout/bin/python mesh_publish.py          # собрать, выложить, слить индекс
  ~/venvs/scout/bin/python mesh_publish.py --dry    # только показать числа
  SETS_BANK=<банк> ~/venvs/scout/bin/python mesh_publish.py   # живой банк + кандидат
  ROOM_PUBLISH=bedroom[=next|=путь] [ROOM_PUBLISH_READY=1] ~/venvs/scout/bin/python mesh_publish.py [--rooms-only]

КОМНАТЫ (T-20261105-47, `room_publish.py`). Без `ROOM_PUBLISH` — ровно как прежде (ни одной лишней команды). С ним — в ту же
выкладку меши банка комнаты по таблице привязки `offer_asset_binding`: файл в галерею — ровно путь привязки с проверкой sha
(не «самый свежий манифест»), сбой — комната отказ, гостиная как обычно. Перед пересборкой индекса — копия `mesh-index.json`
на сервере, после — сверка sha выложенного и пересборка привязки (`published_3d`). `--rooms-only` — только комнаты: галерею
гостиной не собирает, на прод везёт лишь папки комнатных мешей (rsync по списку, сверка по содержимому).
  ~/venvs/scout/bin/python mesh_publish.py --selftest
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bank_paths as _BP  # noqa: E402

SALAD = os.path.join(HERE, 'salad')
PY = os.path.expanduser('~/venvs/scout/bin/python')
GALLERY = os.path.expanduser('~/scout-scenes/mesh-pilot-gallery')
SETS = _BP.LIVE
HOST = 'root@89.167.127.0'
PROD_DIR = '/opt/remlab/test/mesh-pilot10'
PROD_IDX = 'https://remont-lab.online/test/mesh-pilot10/mesh-index.json'
# Ниже этого порога на проде не публикуем: забитый диск роняет и сайт, и приёмник мешей.
MIN_FREE_GB = float(os.environ.get('MESH_PUBLISH_MIN_FREE_GB', '5'))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-tAc']


def sh(cmd: str, timeout: int = 1800) -> tuple[int, str]:
    r = subprocess.run(['bash', '-lc', cmd], capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def bank_files(env=os.environ) -> list[str]:
    """Банки, чьи товары публикуем: живой всегда; кандидат из `SETS_BANK` — в добавку (заданный, но отсутствующий —
    отказ `bank_paths`, на «только живой» молча не откатываемся)."""
    bank, live = _BP.input_bank(env)
    return [SETS] if live else [SETS, bank]


def want_skus(files: list[str]) -> set[str]:
    """`mid:eid` всех товаров комплектов из этих банков."""
    return {f"{it['mid']}:{it['eid']}" for f in files for s in json.load(open(f, encoding='utf-8'))
            for _r, it in (s.get('items') or {}).items() if it and it.get('mid')}


def scene_keys(ready: list, rows: dict | None) -> set[str]:
    """Чистое ядро `ready_skus`: [(sku, представитель|'')] → ключи моделей СЦЕНЫ (`mid:eid`). С привязкой (rows) — то же правило,
    что у демо (`room_bindings.scene_msid`: своя модель привязки, если у неё есть файл, иначе представитель); rows None —
    прежнее правило (представитель)."""
    import room_bindings as RB
    if rows is None:
        return {rep or sku for sku, rep in ready}
    rep = {sku.replace(':', '_', 1): (r or sku).replace(':', '_', 1) for sku, r in ready}
    return {RB.scene_msid(rows.get(sku), sku.replace(':', '_', 1), rep).replace('_', ':', 1) for sku, _r in ready}


def ready_skus(files: list[str] | None = None, rows: dict | None = None) -> set[str]:
    """Ключи КАТАЛОГА МЕШЕЙ для товаров комплектов, у которых меш готов.

    Ключ — не артикул товара, а МОДЕЛЬ СЦЕНЫ (T-20261106-77/6): та же, что грузит демо (`flat215_demo._msid` →
    `room_bindings.scene_msid`). У цветового варианта своей модели нет — ключ представителя семьи (ADR-0196; без перевода шаг
    считал «не хватает 61 модели» — урок 470); есть своя модель привязки с файлом — она. До T-77/6 ключом всегда был
    представитель, и свою модель варианта из комплектов выкладка не везла, а файл представителя брала галерея «по свежести».
    rows — строки привязки (`room_publish.load_rows`); None — прежнее правило.
    """
    want = want_skus(files or [SETS])
    out = subprocess.run(
        PSQL + ["select shop_mid||':'||external_id||'~'||coalesce(mesh_family_rep,'') "
                "from products where mesh_uri is not null and mesh_status='ready'"],
        capture_output=True, text=True)
    ready = []
    for line in out.stdout.split('\n'):
        if '~' not in line:
            continue
        sku, rep = line.strip().split('~', 1)
        if sku in want:
            ready.append((sku, rep))
    return scene_keys(ready, rows)


def prod_free_gb() -> float:
    code, out = sh(f"ssh -o BatchMode=yes -o ConnectTimeout=15 {HOST} \"df -BG --output=avail / | tail -1\"", 120)
    if code:
        return -1.0
    return float(''.join(c for c in out if c.isdigit() or c == '.') or 0)


def prod_keys() -> set[str] | None:
    """Модели в индексе прода (свежий, мимо кэша); нет ответа — None."""
    import time
    import urllib.request
    try:
        with urllib.request.urlopen(f'{PROD_IDX}?v={int(time.time())}', timeout=60) as f:
            return set(json.load(f))
    except Exception:  # noqa: BLE001
        return None


def bytes_to_send(gallery: str = GALLERY, prod: set[str] | None = None) -> int:
    """Сколько байт уедет на прод: папки галереи, которых нет в индексе прода (rsync шлёт новое, лежащее не трогает). Индекс не
    ответил — считаем всю галерею: лучше не выложить, чем забить диск."""
    prod = prod_keys() if prod is None else prod
    n = 0
    for k in (os.listdir(gallery) if os.path.isdir(gallery) else []):
        d = os.path.join(gallery, k)
        if os.path.isdir(d) and (not prod or k not in prod):
            n += sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))
    return n


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
    files = bank_files()
    if len(files) > 1:
        print(f'[публикация] банк-кандидат {files[1]} — публикую товары живого банка и кандидата', flush=True)
    import room_publish as RP
    try:                                      # привязка — одна на отбор гостиной и на комнаты (T-20261106-77/6)
        rows, why = RP.load_rows()
    except Exception as e:  # noqa: BLE001
        rows, why = None, repr(e)[:160]
    if rows is None:
        print(f'WARN:mesh_publish: привязка не читается ({why}) — отбор гостиной по представителю (прежнее правило)', flush=True)
    skus = ready_skus(files, rows)
    # ПОД НЕДОБОР ЛЕНТЫ ЗАМЕН (план demo-20 В1, владелец 22.10 TG 793): готовые меши годных в полосе размера, которых нет на
    # сервере, — в той же выкладке. До этого шаг брал только товары комплектов, и модели «под ленту» до ленты не доходили
    demo = set()
    try:
        import demo_band
        demo = demo_band.publish_skus() - skus
    except Exception as e:  # noqa: BLE001 — нет демо/базы: выкладываем как раньше, но громко
        print(f'WARN:mesh_publish: недобор ленты не посчитан ({repr(e)[:120]}) — только комплекты', flush=True)
    if demo:
        print(f'[публикация] под недобор ленты замен (demo_band): ещё {len(demo)} моделей', flush=True)
    skus |= demo
    have = set(os.listdir(GALLERY)) if os.path.isdir(GALLERY) else set()
    missing = {s for s in skus if s.replace(':', '_') not in have}
    print(f'[публикация] с готовым мешем (комплекты + недобор ленты): {len(skus)}; '
          f'в локальной галерее уже {len(skus) - len(missing)}; добавить {len(missing)}', flush=True)
    rooms_only = '--rooms-only' in sys.argv
    rplans, rerr = RP.plans(rows=rows)        # без ROOM_PUBLISH — ([], []): ни базы, ни файлов
    for e in rerr:
        print(f'WARN:mesh_publish: комнаты не публикую: {e}', flush=True)
    for P in rplans:
        print(f'[публикация] комната {RP.summary(P)}', flush=True)
    if rooms_only and not rplans:
        print('WARN:mesh_publish: --rooms-only без годной настройки комнат — нечего делать', flush=True)
        return 0
    sel = {s.replace(':', '_', 1) for s in skus}
    bound = living_bound(rplans, sel)
    if bound:
        print(f'[публикация] гостиная: файл по привязке у {len(bound)} моделей отбора, по галерее (свежесть) — у '
              f'{len(sel - bound)}', flush=True)

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

    if not rooms_only:
        lst = os.path.join(HERE, '.mesh-publish-only.txt')
        with open(lst, 'w', encoding='utf-8') as f:
            f.write('\n'.join(sorted(skus)))
        env = f'GALLERY_ONLY={lst} '
        if bound:                             # галерея кладёт тот же файл привязки — иначе ночной пинг-понг байтов с `stage`
            blst = os.path.join(HERE, '.mesh-publish-bound.txt')
            with open(blst, 'w', encoding='utf-8') as f:
                f.write('\n'.join(sorted(bound)))
            env += f'GALLERY_FROM_BINDING=1 GALLERY_BIND_ONLY={blst} '
        code, out = sh(f'{env}GALLERY_SRC=$HOME/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2 '
                       f'{PY} {SALAD}/gallery_build.py', 3600)
        print(f'[публикация] галерея: код {code}; {out.splitlines()[-1][:160] if out else ""}', flush=True)
        if code:
            print('WARN:mesh_publish: галерея не собралась — на прод ничего не везу', flush=True)
            return 0
    room_ids = rooms_stage(rplans, sel - bound) if rplans else []
    if rooms_only and not room_ids:
        print('[публикация] комнаты: выкладывать нечего', flush=True)
        return 0

    # МЕСТО — ПО РЕАЛЬНЫМ БАЙТАМ (Codex 22.10): rsync без удаления, склад на проде только растёт; выкладку, после которой
    # останется меньше порога, не начинаем вовсе. Старое не удаляем — это только по слову владельца
    new_gb = (bytes_of(room_ids) if rooms_only else bytes_to_send()) / 2 ** 30
    if free - new_gb < MIN_FREE_GB:
        print(f'WARN:mesh_publish: выложить {new_gb:.2f} ГБ, на проде свободно {free:.0f} ГБ — останется меньше '
              f'{MIN_FREE_GB:.0f}; выкладку пропускаю', flush=True)
        return 0
    print(f'[публикация] к выкладке {new_gb:.2f} ГБ новых моделей; на проде свободно {free:.0f} ГБ', flush=True)

    # ИНДЕКС НЕ ВЕЗЁМ (13.10). rsync клал локальный `mesh-index.json` поверх прода, а слияние
    # следом читало уже ПОДМЕНЁННЫЙ файл и «сохраняло с прода 0»: индекс витрины схлопнулся с 590
    # до 186 за один заход. Индекс теперь не копируется, а пересобирается по тому, что реально
    # лежит на сервере, — такой способ не умеет терять записи.
    if rooms_only:
        code, out = rsync_rooms(room_ids)
    else:
        code, out = sh(f'rsync -a --info=stats1 --exclude=mesh-index.json '
                       f'-e "ssh -p 22222 -o BatchMode=yes" '
                       f'{GALLERY}/ {HOST}:{PROD_DIR}/', 3600)
    sent = [l for l in out.splitlines() if 'files transferred' in l or 'Number of' in l]
    print(f'[публикация] выложено: код {code}; {"; ".join(sent)[:200]}', flush=True)
    if code:
        print('WARN:mesh_publish: rsync на прод не прошёл', flush=True)
        return 0

    if rplans:
        code, out = backup_index()
        print(f'[публикация] копия индекса на сервере: {out}', flush=True)
        if code:
            print('WARN:mesh_publish: копию индекса снять не удалось — индекс не пересобираю', flush=True)
            return 0
    code, out = rebuild_index()
    print(f'[публикация] индекс пересобран по серверу: код {code}; {out[:160]}', flush=True)
    if room_ids:
        rooms_verify(room_ids, rplans)

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


def living_bound(rplans: list, sel: set) -> set:
    """Модели отбора гостиной («mid_eid»), чей файл — ПО ПРИВЯЗКЕ (T-20261106-77/6): есть в плане гостиной (`ROOM_PUBLISH=living`,
    годная ready-привязка, не в `publish_hold`). Их файл кладёт `room_publish.stage` со сверкой sha, галерея берёт тот же файл
    (`GALLERY_BIND_ONLY`), а не «самый свежий»: до T-77/6 у отобранных гостиной стоял файл галереи, и файл привязки на прод
    не доезжал (`living_other`: 13770…, 1600…; 5177 с отбором по модели сцены из отбора вышел — его товары на своих моделях).
    Остальной отбор — галерея по свежести, как прежде.
    Без плана гостиной — пусто (всё как прежде)."""
    return {m.replace(':', '_', 1) for P in rplans if P['room'] == 'living' for m in P['meshes']} & sel


def rooms_stage(rplans: list, living: set) -> list:
    """Меши комнат — в галерею ровно файлами привязки (`room_publish.stage`). → mesh_id, которые надо видеть на проде."""
    import room_publish as RP
    ids = []
    for P in rplans:
        R = RP.stage(P, GALLERY, living)
        P['stage'] = R
        print(f"[публикация] комната {P['room']}: {R['status']}; новых файлов {len(R['staged'])} ({R['bytes'] / 2 ** 20:.0f} МБ), "
              f"уже те же {len(R['same'])}, у гостиной {len(R['living_same'])}"
              + (f", у гостиной ДРУГИЕ байты {R['living_other'][:5]}" if R['living_other'] else '')
              + (f"; ОТКАЗ: {'; '.join(R['errors'][:3])}" if R['errors'] else ''), flush=True)
        if R['status'] == 'ok':
            ids += R['staged'] + R['same']
    return sorted(set(ids))


def bytes_of(ids: list, gallery: str = GALLERY) -> int:
    return sum(os.path.getsize(os.path.join(gallery, i, 'model.glb')) for i in ids
               if os.path.exists(os.path.join(gallery, i, 'model.glb')))


def rsync_rooms(ids: list) -> tuple[int, str]:
    """Только папки комнатных мешей, по списку; --checksum — выложенные руками не те байты того же размера тоже заменятся."""
    lst = os.path.join(HERE, '.mesh-publish-rooms.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        f.write(''.join(f'{i}/model.glb\n' for i in ids))
    return sh(f'rsync -a -c --info=stats1 --files-from={lst} -e "ssh -p 22222 -o BatchMode=yes" '
              f'{GALLERY}/ {HOST}:{PROD_DIR}/', 3600)


def backup_index() -> tuple[int, str]:
    """Копия `mesh-index.json` на сервере рядом (`.bak-<ммдд-ччммсс>`) перед пересборкой — откат одной командой cp."""
    import time
    dst = f'{PROD_DIR}/mesh-index.json.bak-{time.strftime("%m%d-%H%M%S")}'
    code, out = sh(f'ssh -o BatchMode=yes -o ConnectTimeout=20 {HOST} "cp -p {PROD_DIR}/mesh-index.json {dst}"', 120)
    return code, (out[:160] if code else dst)


def rooms_verify(ids: list, rplans: list) -> None:
    """После выкладки: каждый комнатный меш — в индексе прода и sha файла на сервере = привязке; затем пересборка привязки,
    чтобы `published_3d` в таблице стал правдой (демо берёт msid только у опубликованных — `room_bindings.mesh_for`)."""
    want = {mid: m['asset_id'].split(':', 1)[1] for P in rplans for mid, m in P['meshes'].items() if mid in ids}
    idx = prod_keys() or set()
    files = ' '.join(f'{PROD_DIR}/{i}/model.glb' for i in sorted(want))
    code, out = sh(f'ssh -o BatchMode=yes -o ConnectTimeout=20 {HOST} "sha256sum {files}"', 600)
    got = {ln.split()[1].split('/')[-2]: ln.split()[0] for ln in out.splitlines() if len(ln.split()) == 2}
    bad = sorted(i for i in want if got.get(i) != want[i])
    miss = sorted(i for i in want if i not in idx)
    print(f'[публикация] комнаты на проде: {len(want) - len(bad)} из {len(want)} — sha совпал; нет в индексе {len(miss)}'
          + (f'; НЕ СОШЛИСЬ {bad[:5]}' if bad else '') + (f'; НЕТ В ИНДЕКСЕ {miss[:5]}' if miss else ''), flush=True)
    code, out = sh(f'cd {HERE} && {PY} room_bindings.py --build', 1800)
    print(f'[публикация] привязка пересобрана (published_3d): код {code}; '
          f'{[ln for ln in out.splitlines() if ln.startswith("снимок:")][-1:] or out[-160:]}', flush=True)


def _selftest() -> int:
    import tempfile
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    with tempfile.TemporaryDirectory() as tmp:
        cand = os.path.join(tmp, 'sets3.next.json')
        json.dump([{'items': {'диван': {'mid': 1, 'eid': 'new'}, 'торшер': {'mid': 2, 'eid': 'lamp'}, 'шторы': None}}],
                  open(cand, 'w', encoding='utf-8'))
        ok('без SETS_BANK — только живой банк, как раньше', bank_files({}) == [SETS])
        if os.path.exists(SETS):                            # в CI живого банка нет (вне git)
            ok('SETS_BANK = живой — без дубля', bank_files({'SETS_BANK': SETS}) == [SETS])
        ok('SETS_BANK = кандидат — живой И кандидат (объединение, не замена)', bank_files({'SETS_BANK': cand}) == [SETS, cand])
        try:
            bank_files({'SETS_BANK': os.path.join(tmp, 'нет.json')})
            ok('отсутствующий кандидат — отказ', False)
        except SystemExit:
            ok('отсутствующий кандидат — отказ, а не тихий откат на живой', True)
        live = os.path.join(tmp, 'live.json')
        json.dump([{'items': {'диван': {'mid': 1, 'eid': 'old'}, 'торшер': {'mid': 2, 'eid': 'lamp'}}}],
                  open(live, 'w', encoding='utf-8'))
        ok('товары — объединение банков, пустые слоты пропущены',
           want_skus([live, cand]) == {'1:old', '1:new', '2:lamp'})
        gal = os.path.join(tmp, 'gal')
        for k, size in (('1_a', 300), ('1_b', 500)):
            os.makedirs(os.path.join(gal, k))
            open(os.path.join(gal, k, 'model.glb'), 'wb').write(b'x' * size)
        open(os.path.join(gal, 'index.html'), 'w').write('<html>')
        ok('байты к выкладке — только папки, которых нет в индексе прода', bytes_to_send(gal, {'1_a'}) == 500)
        ok('индекс прода не ответил (пустой) — считаем всю галерею', bytes_to_send(gal, set()) == 800)
    # комнаты (T-20261105-47): без настройки — ни плана, ни команд; с настройкой — rsync только списком
    import room_publish as RP
    ok('без ROOM_PUBLISH — комнат нет (гостиная как прежде)', RP.plans({}, rows={}) == ([], []))
    cmds = []
    real_sh = globals()['sh']
    globals()['sh'] = lambda c, t=0: (cmds.append(c), (0, ''))[1]
    try:
        rsync_rooms(['5_r', '1_a'])
    finally:
        globals()['sh'] = real_sh
    ok('комнаты: rsync только папками комнатных мешей, со сверкой по содержимому, без --delete',
       len(cmds) == 1 and '--files-from=' in cmds[0] and ' -c ' in cmds[0] and '--delete' not in cmds[0]
       and open(os.path.join(HERE, '.mesh-publish-rooms.txt')).read() == '5_r/model.glb\n1_a/model.glb\n')
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, '5_r'))
        open(os.path.join(tmp, '5_r', 'model.glb'), 'wb').write(b'x' * 70)
        ok('комнаты: байты к выкладке — только свои папки', bytes_of(['5_r', 'нет'], tmp) == 70)
    # T-20261106-77/6: отбор гостиной — по модели сцены; модели с привязкой гостиной — файлом привязки
    ready = [('1:own', '1:rep'), ('1:var', '1:rep'), ('1:blk', '1:rep'), ('1:solo', '')]
    rows = {'1:own': {'mesh_id': '1:own', 'local_3d': True}, '1:var': {'mesh_id': '1:rep', 'local_3d': True},
            '1:blk': {'mesh_id': '1:blk', 'local_3d': False}}
    ok('отбор без привязки — прежнее правило (представитель)', scene_keys(ready, None) == {'1:rep', '1:solo'})
    ok('отбор по модели сцены: своя с файлом — своя; вариант и без файла — представитель; без строки — свой артикул',
       scene_keys(ready, rows) == {'1:own', '1:rep', '1:solo'})
    rp = [{'room': 'living', 'meshes': {'1:own': {}, '1:rep': {}, '9:x': {}}}, {'room': 'bedroom', 'meshes': {'1:solo': {}}}]
    ok('по привязке — только модели плана гостиной, попавшие в отбор', living_bound(rp, {'1_own', '1_rep', '1_solo'}) == {'1_own', '1_rep'})
    ok('без плана гостиной — по привязке ничего (как прежде)', living_bound([], {'1_own'}) == set())
    print(f'mesh_publish selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(_selftest() if '--selftest' in sys.argv else main())
