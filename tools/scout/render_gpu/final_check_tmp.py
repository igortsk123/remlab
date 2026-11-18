import sys, json
sys.path.insert(0, '/home/pakar/igor/remlab/.claude/worktrees/render-gpu/tools/scout/salad')
import migrate_groups as MG
MG.env_from_file()
c, d = MG.api('')
before = json.load(open('/home/pakar/remlab-logs/t22-1117/mesh-images-before.json'))
for g in d['items']:
    n = g['name']
    cs = g.get('current_state') or {}
    cnt = cs.get('instance_status_counts') or {}
    img = (g.get('container') or {}).get('image')
    tag = ('образ как до: ' + ('ДА' if before[n] == img else 'НЕТ')) if n in before else ''
    print(f"{n:28} {cs.get('status')!s:9} running={cnt.get('running_count')} {tag}")
