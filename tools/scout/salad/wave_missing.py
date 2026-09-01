#!/usr/bin/env python3
"""Какие задания волны НЕ доехали — по факту скачанного результата, а не по журналу прогона.

Зачем отдельная проверка. В нынешнем `ssh_run.py` отказ вида `input_failed` считается ответом
генератора: задание закрывается, курсор идёт вперёд, в очередь перегона оно не попадает —
товар исчезает молча. Сегодня так вела себя нода 35b10e39 (35 отказов из 37 за день: у неё
нет сети наружу, и она не может скачать фото). На волне из 35 заданий по прямой просьбе
владельца потерять часть недопустимо, поэтому после каждого прохода сверяемся с ДЕРЕВОМ
результатов: есть ли у товара свежая генерация именно с нашим входом.

  wave_missing.py <jobs.json> <out-missing.json>   → печатает, сколько осталось
"""
import glob
import json
import os
import sys

SRC = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')


def done_inputs() -> set:
    """Пары (sku, image_url), для которых результат уже лежит на диске."""
    out = set()
    for mp in glob.glob(os.path.join(SRC, '*/*/manifest.json')):
        d = os.path.dirname(mp)
        try:
            man = json.load(open(mp, encoding='utf-8'))
        except Exception:  # noqa: BLE001
            continue
        # suspect-комплект (форма отбракована гейтом) — это ОТВЕТ генератора, а не потеря:
        # такое задание повторять не надо, иначе волна будет крутить его до упора.
        has = os.path.exists(os.path.join(d, 'model.glb')) or \
            os.path.exists(os.path.join(d, 'shape.glb'))
        if has:
            out.add((man.get('sku'), (man.get('input') or {}).get('image_url')))
    return out


def main() -> None:
    jobs = json.load(open(sys.argv[1], encoding='utf-8'))
    have = done_inputs()
    missing = [j for j in jobs if (j['sku'], j['image_url']) not in have]
    json.dump(missing, open(sys.argv[2], 'w'), ensure_ascii=False, indent=1)
    print(f'из {len(jobs)} заданий не доехало {len(missing)}')
    for j in missing[:10]:
        print(f"   {j['sku']} ({j.get('role')})")


if __name__ == '__main__':
    main()
