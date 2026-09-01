#!/usr/bin/env python3
"""Возврат заданий, которые конвейер потерял молча.

ЗАЧЕМ. До 01.09 отказ `input_failed`/`failed` считался ответом генератора: задание
закрывалось, курсор `--skip` уходил вперёд, а в очередь перегона такой товар не попадал —
приёмка его не видит, потому что отказ случается ДО создания манифеста (`worker.py`).
Итог: товар исчезал бесследно. Предохранитель (`node_health`) закрывает будущее; этот
скрипт возвращает уже потерянное.

Судим НЕ по журналу, а по дереву мешей: журнал не пишет seed и полный id инстанса, поэтому
единственное надёжное доказательство потери — отсутствие комплекта на диске.

  ~/venvs/scout/bin/python recover_lost.py            # показать, что потеряно
  ~/venvs/scout/bin/python recover_lost.py --write    # положить в спул повторов
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ssh_run as SR  # noqa: E402

PROGRESS = SR.PROGRESS
MESH_ROOT = os.path.expanduser(
    os.environ.get('MESH_ROOT', '~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2'))
# Отказы, в которых задание не виновато: их и надо возвращать. `flat_shape`/`bad_cutout` —
# это ОТВЕТ по товару, а не потеря: их ведёт приёмка через очередь перегона.
LOSS_STATUSES = ('input_failed', 'transport_failed', 'failed')


def has_asset(sku: str) -> bool:
    """Есть ли у товара НАСТОЯЩАЯ модель на диске.

    Признак — `model.glb`, а НЕ `manifest.json`. Забракованная гейтом форма публикуется
    комплектом из манифеста и `shape.glb`, без модели: это «гейт ответил», а не «меш готов».
    По манифесту таких на диске 55 комплектов у 25 SKU — они выглядели бы обеспеченными и
    никогда бы не вернулись в очередь (нашла соседняя сессия на своей волне 01.09).
    """
    d = os.path.join(MESH_ROOT, sku.replace(':', '_'))
    if not os.path.isdir(d):
        return False
    for sub in os.listdir(d):
        if os.path.exists(os.path.join(d, sub, 'model.glb')):
            return True
    return False


def lost_skus() -> tuple[set, dict]:
    """SKU, которые падали не по своей вине и не имеют комплекта. Плюс причина последнего
    отказа — чтобы отличать «сеть ноды» от «мёртвая ссылка» глазами, а не догадкой."""
    failed, ok, why = set(), set(), {}
    with open(PROGRESS, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            sku = r.get('sku')
            if not sku:
                continue
            if r.get('status') in ('ok', 'cached'):
                ok.add(sku)
            elif r.get('status') in LOSS_STATUSES:
                failed.add(sku)
                why[sku] = f"{r.get('status')}: {str(r.get('error') or '')[:90]}"
    return {s for s in failed - ok if not has_asset(s)}, why


def main() -> None:
    lost, why = lost_skus()
    plan = {j['sku']: j for j in SR.plan_jobs()}
    jobs = [plan[s] for s in sorted(lost) if s in plan]
    orphan = sorted(lost - set(plan))
    print(f'потеряно (падали не по своей вине и комплекта нет): {len(lost)}')
    for s in sorted(lost):
        print(f'  {s:42s} {why.get(s, "")}')
    if orphan:
        print(f'не в текущем плане, вернуть нечем: {len(orphan)} — {orphan}')
    if '--write' not in sys.argv:
        print(f'\nк возврату готово {len(jobs)} заданий. Записать: --write')
        return
    if not jobs:
        print('возвращать нечего')
        return
    with open(SR.RETRY_SPOOL, 'a', encoding='utf-8') as f:
        for j in jobs:
            f.write(json.dumps({'job': j, 'sku': j['sku'], 'seed': j.get('seed'),
                                'status': 'recovered', 'fault': 'node',
                                'error': why.get(j['sku'], ''), 'retries': 0,
                                'exhausted': False}, ensure_ascii=False) + '\n')
    print(f'в спул повторов дописано {len(jobs)} заданий → {SR.RETRY_SPOOL}')
    print('конвейер разберёт их следующей пачкой (batch_show → drain_retry_spool)')


if __name__ == '__main__':
    main()
