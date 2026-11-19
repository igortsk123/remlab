#!/usr/bin/env python3
"""СРАВНЕНИЕ ГРУПП SALAD БЕЗ СЕКРЕТОВ (T-20261118-91/2): печатает у групп только безопасные поля (ресурсы, приоритет, страны, пробы, образ без токенов, имена переменных окружения).
Только чтение: GET /<имя> по API организации.   Запуск (pakardev): ~/venvs/scout/bin/python cmp_groups.py trial-hunyuan21-hy8 trial-pixal3d-px6 …"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import migrate_groups as MG  # noqa: E402


def safe(g: dict) -> dict:
    c = g.get('container', {})
    out = {k: g.get(k) for k in ('name', 'country_codes', 'networking', 'restart_policy', 'replicas', 'autostart_policy', 'update_strategy',
                                 'readiness_probe', 'startup_probe', 'liveness_probe', 'create_time')}
    img = str(c.get('image'))
    out['container'] = {'image': img.split('@')[0] + ('@' + img.split('@')[1][:19] if '@' in img else ''), 'resources': c.get('resources'),
                        'priority': c.get('priority'), 'image_caching': c.get('image_caching'), 'command': ('есть, %d арг.' % len(c['command'])) if c.get('command') else None}
    out['env_keys'] = sorted((c.get('environment_variables') or {}).keys())
    return out


def main() -> int:
    MG.env_from_file()
    for n in sys.argv[1:]:
        code, g = MG.api('/' + n)
        print('=====', n, code)
        print(json.dumps(safe(g), ensure_ascii=False, indent=1, default=str)[:3500] if code == 200 else str(g)[:200])
    return 0


if __name__ == '__main__':
    sys.exit(main())
