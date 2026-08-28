#!/usr/bin/env python3
"""Точечная пересборка: считаем солвером ТОЛЬКО сцены изменившихся комплектов.

ЗАЧЕМ. После автозамены товара пересчитывать все 272 сцены незачем — поменялся один комплект.
Но и «пересчитать что-нибудь» нельзя: отчёт приёмки един, и если часть сцен посчитана старым
составом, а часть новым, глобальные пороги проверяются по франкенштейну.

Поэтому радиус берётся ОТ ПРИЧИНЫ, а не «на глаз»:
  * товар выбыл из продажи        → все комплекты, где он стоял;
  * поменялся слот одного комплекта → только этот комплект;
  * изменились габариты            → все сцены этого комплекта;
  * изменилось только фото         → раскладку НЕ трогаем вовсе (меш/рендер — другой конвейер);
  * изменились правила солвера     → точечный режим ЗАПРЕЩЁН, нужен полный экзамен (урок 297:
    `acceptance_run` резюмирует по существующему jsonl, и отчёт после правок кода обязателен
    к удалению — иначе экзамен загрязнён сценами старого движка).

Комплект опознаётся стабильным `set_id`, но сцены пока названы по НОМЕРУ (`setN-base`), поэтому
перед пересчётом сверяем карту «номер → id»: уехала — значит пересчитали бы не то, и мы
останавливаемся, а не делаем вид, что всё хорошо.

  ~/venvs/scout/bin/python resolve_affected.py            # показать план пересчёта
  ~/venvs/scout/bin/python resolve_affected.py --run      # пересчитать и слить отчёт
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SETS = os.path.join(HERE, 'sets3.json')
SCENES = os.path.join(HERE, 'acceptance-scenes.json')
REPORT_JL = os.path.join(HERE, 'acceptance-report-zoned.jsonl')
PY = os.path.expanduser('~/venvs/scout/bin/python')


def affected_scene_ids(hours: int = 24) -> tuple[list[str], list[str]]:
    """(сцены к пересчёту, предупреждения)."""
    warn = []
    from heal_policy import affected_sets
    from set_identity import check, index_map
    sets = json.load(open(SETS))
    problems = check(sets)
    if problems:
        warn += problems
    changed = set(affected_sets(hours))
    if not changed:
        return [], warn
    nums = {n for n, sid in index_map(sets).items() if sid in changed}
    scenes = [sc['id'] for sc in json.load(open(SCENES)) if sc.get('set') in nums]
    return scenes, warn


def drop_from_report(scene_ids: set[str]) -> int:
    """Убрать пересчитываемые сцены из кэша отчёта — иначе прогон их «подхватит готовыми»."""
    if not os.path.exists(REPORT_JL):
        return 0
    kept, dropped = [], 0
    for line in open(REPORT_JL, encoding='utf-8'):
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001 — битая строка отчёта не должна ронять пересчёт
            continue
        if rec.get('scene') in scene_ids:
            dropped += 1
        else:
            kept.append(line.rstrip('\n'))
    if dropped:
        open(REPORT_JL + '.bak-partial', 'w', encoding='utf-8').write('\n'.join(kept) + '\n')
        os.replace(REPORT_JL + '.bak-partial', REPORT_JL)
    return dropped


def main() -> int:
    hours = int(os.environ.get('RESOLVE_HOURS', '24'))
    scenes, warn = affected_scene_ids(hours)
    for w in warn:
        print('  ⚠', w)
    if warn:
        # Сдвиг номеров означает, что сцены `setN-*` указывают не на те комплекты. Пересчёт в
        # такой ситуации даёт уверенно неверный результат — это хуже, чем не пересчитать.
        print('пересчёт остановлен: идентичность комплектов нарушена, сперва разобраться')
        return 1
    if not scenes:
        print(f'за {hours} ч замен не было — пересчитывать нечего')
        return 0
    print(f'изменившихся сцен: {len(scenes)} из 272')
    for s in scenes[:12]:
        print('  ', s)
    if '--run' not in sys.argv:
        print('это был показ; пересчитать — ключом --run')
        return 0
    dropped = drop_from_report(set(scenes))
    print(f'из кэша отчёта убрано записей: {dropped}')
    env = {**os.environ, 'ACC_SCENES': ','.join(scenes)}
    r = subprocess.run([PY, os.path.join(HERE, 'acceptance_run.py'), 'zoned'], env=env)
    if r.returncode != 0:
        print('прогон сцен завершился с ошибкой — отчёт мог остаться неполным')
        return r.returncode
    # Пороги проверяются на ОБЪЕДИНЁННОМ отчёте: точечный пересчёт не отменяет глобальных
    # требований, а сам по себе о них ничего не знает.
    print('пересчитано; глобальные пороги проверять на объединённом отчёте '
          '(acceptance_analyze.py)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
