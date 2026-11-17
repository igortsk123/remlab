#!/usr/bin/env python3
"""Только чтение Salad (T-20261117-22): группы проекта, классы GPU и их цены, спека образца-соседа без секретов.

    ~/venvs/scout/bin/python tools/scout/render_gpu/salad_look.py [--donor mesh-q-low-1]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'salad'))
import migrate_groups as MG  # noqa: E402
import recreate_group as RG  # noqa: E402

MG.env_from_file()
donor = sys.argv[sys.argv.index('--donor') + 1] if '--donor' in sys.argv else None

code, d = MG.api('')
print('GET groups', code)
for g in d.get('items', []):
    st = g.get('current_state') or {}
    c = g.get('container') or {}
    print(f"  {g['name']:28} {st.get('status'):10} реплик {g.get('replicas')} prio {c.get('priority') or g.get('priority')} "
          f"счётчики {st.get('instance_status_counts')}")

cls = RG.gpu_classes()
print('gpu classes:', len(cls))
for i, n in sorted(cls.items(), key=lambda x: x[1]):
    if '3090' in n or '4090' in n or 'A5000' in n:
        print('  ', i, n)

if donor:
    code, g = MG.api(f'/{donor}')
    print('donor', donor, code)
    c = g.get('container') or {}
    c = dict(c)
    c.pop('registry_authentication', None)
    env = c.get('environment_variables') or {}
    c['environment_variables'] = {k: ('<скрыто>' if any(s in k for s in ('TOKEN', 'KEY', 'SECRET', 'PASS')) else v) for k, v in env.items()}
    g = dict(g)
    g['container'] = c
    print(json.dumps(g, ensure_ascii=False, indent=1)[:6000])
