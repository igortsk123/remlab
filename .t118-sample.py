"""T-118: выборка реальных карточек /lab/mesh-audit для макета (только чтение БД DEV) + счёт по ролям."""
import collections
import json
import os
import sys

sys.path.insert(0, '/home/pakar/igor/remlab/tools/scout')
import mesh_audit_sync as S  # noqa: E402

items = S.current_items()
cnt = collections.Counter(i.get('role') or '?' for i in items)
with_poster = collections.Counter(i.get('role') or '?' for i in items if i.get('posterUrl'))
print('TOTAL', len(items))
for role, n in cnt.most_common():
    print(f'ROLE {role} {n} poster={with_poster.get(role, 0)}')
pick = []
for role in ('диван', 'кашпо'):
    xs = [i for i in items if i.get('role') == role and i.get('posterUrl') and i.get('imageUrl')]
    pick += xs[:4]
out = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/remlab-logs/t118-1112/sample.json')
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, 'w') as f:
    json.dump({'counts': cnt.most_common(), 'pick': pick}, f, ensure_ascii=False, indent=1)
print('PICK', len(pick), out)
