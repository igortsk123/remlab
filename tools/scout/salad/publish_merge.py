#!/usr/bin/env python3
"""ПУБЛИКАЦИЯ РЕЕСТРА СЛИЯНИЕМ, А НЕ ПЕРЕЗАПИСЬЮ.

Зачем. 01.09 прод потерял 114 из 185 записей ориентации (`orient.json`) и 34 из 190 записей
каталога мешей (`mesh-index.json`). Ломало не «удаление», а обычный `scp`: локальные реестры
считаются ИНКРЕМЕНТАЛЬНО, с бюджетом времени на прогон, и после чистки кэша содержат только то,
что успел посчитать последний цикл. Такой файл, положенный поверх полного, стирает всю историю —
при том что сами GLB и PNG на сервере остаются лежать. Демо в этот момент теряет ориентацию
мебели и вид сверху у предметов, чьи файлы никуда не делись.

Правило: реестр на сервере — НАКОПИТЕЛЬНЫЙ. Публикуем объединение «что на проде» + «что
посчитали сейчас», свежая запись побеждает. Удаление записи — только явным действием человека.

    publish_merge.py <локальный json> <публичный url> <root@host:/путь> [-P порт]

Ключи, которых нет локально, сохраняются; ключи, посчитанные сейчас, перезаписывают старые.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request


def fetch(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=30) as f:
            return json.loads(f.read().decode('utf-8'))
    except Exception as e:  # noqa: BLE001 — прода может не быть; тогда просто публикуем своё
        print(f'  прод не прочитан ({type(e).__name__}), публикую как есть', flush=True)
        return {}


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    local_path, url, remote = sys.argv[1], sys.argv[2], sys.argv[3]
    port = sys.argv[sys.argv.index('-P') + 1] if '-P' in sys.argv else '22222'
    if not os.path.exists(local_path):
        print(f'  локального реестра нет: {local_path} — публиковать нечего')
        return 0
    local = json.load(open(local_path, encoding='utf-8'))
    remote_data = fetch(url)
    if not isinstance(remote_data, dict) or not isinstance(local, dict):
        print('  реестр не словарь — сливать нечем, публикую локальный')
        remote_data = {}
    merged = dict(remote_data)
    merged.update(local)                      # посчитанное сейчас — свежее, оно и побеждает
    kept = len(set(remote_data) - set(local))
    print(f'  реестр: на проде {len(remote_data)}, локально {len(local)}, '
          f'публикую {len(merged)} (сохранено с прода {kept})', flush=True)
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as t:
        json.dump(merged, t, ensure_ascii=False)
        tmp = t.name
    try:
        r = subprocess.run(['scp', '-P', port, '-o', 'BatchMode=yes', tmp, remote],
                           capture_output=True, text=True)
        if r.returncode:
            print(f'  scp не прошёл: {r.stderr.strip()[:200]}')
            return 1
    finally:
        os.unlink(tmp)
    return 0


if __name__ == '__main__':
    sys.exit(main())
