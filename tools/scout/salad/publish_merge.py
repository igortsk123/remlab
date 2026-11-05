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

    publish_merge.py <локальный json> <публичный url> <root@host:/путь> [-P порт] [--only-resolved]

Ключи, которых нет локально, сохраняются; ключи, посчитанные сейчас, перезаписывают старые.

`--only-resolved` — для `orient.json` из манифеста вида сверху (план orient-cabinet-01, этап 1; T-20261105-56): идут
только записи со статусом `auto_resolved|human_resolved` (`orient_policy.publishable`). Нерешённое
(`vlm_pending`/`review_pending`/без статуса) прод-значение НЕ затирает; ручное решение прода (`human:*`) затирает
только `human_resolved` из БД.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request


def fetch(url: str) -> dict | None:
    """Реестр прода. Файла ещё нет (404) — {} (первая публикация). ЛЮБАЯ другая ошибка — None: публикация
    отменяется. Раньше сбой чтения превращался в {} и локальный (частичный) файл ЗАМЕНЯЛ серверный — так
    теряются записи (разбор Codex 14.10, orient.json: 196 записей на 745 моделей)."""
    import urllib.error
    try:
        with urllib.request.urlopen(url, timeout=30) as f:
            return json.loads(f.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print('  на проде реестра ещё нет — публикую свой', flush=True)
            return {}
        print(f'  прод не прочитан (HTTP {e.code}) — публикацию ОТМЕНЯЮ, чтобы не затереть записи', flush=True)
        return None
    except Exception as e:  # noqa: BLE001
        print(f'  прод не прочитан ({type(e).__name__}) — публикацию ОТМЕНЯЮ, чтобы не затереть записи', flush=True)
        return None


def merge(remote_data: dict, local: dict, only_resolved: bool = False) -> tuple[dict, int]:
    """Прод + посчитанное сейчас (свежее побеждает) → (итог, сколько локальных записей НЕ пошло по фильтру)."""
    if only_resolved:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
        import orient_policy as OP
        held = {k for k, v in local.items() if not OP.publishable(v, remote_data.get(k))}
        local = {k: v for k, v in local.items() if k not in held}
    else:
        held = set()
    merged = dict(remote_data)
    merged.update(local)                      # посчитанное сейчас — свежее, оно и побеждает
    return merged, len(held)


def main() -> int:
    argv = [a for a in sys.argv if a != '--only-resolved']
    only_resolved = len(argv) != len(sys.argv)
    if len(argv) < 4:
        print(__doc__)
        return 2
    local_path, url, remote = argv[1], argv[2], argv[3]
    port = argv[argv.index('-P') + 1] if '-P' in argv else '22222'
    if not os.path.exists(local_path):
        print(f'  локального реестра нет: {local_path} — публиковать нечего')
        return 0
    local = json.load(open(local_path, encoding='utf-8'))
    remote_data = fetch(url)
    if remote_data is None:
        return 1
    if not isinstance(remote_data, dict) or not isinstance(local, dict):
        print('  реестр не словарь — сливать нечем, публикацию отменяю')
        return 1
    merged, held = merge(remote_data, local, only_resolved)
    kept = len(set(remote_data) - set(local))
    print(f'  реестр: на проде {len(remote_data)}, локально {len(local)}, '
          f'публикую {len(merged)} (сохранено с прода {kept}'
          f'{f", не решено — прод не трогаю: {held}" if only_resolved else ""})', flush=True)
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
