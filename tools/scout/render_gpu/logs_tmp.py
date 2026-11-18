import sys, time, json
sys.path.insert(0, '/home/pakar/igor/remlab/.claude/worktrees/render-gpu/tools/scout/salad')
import migrate_groups as MG
import pool_ledger as PL
MG.env_from_file()
now = time.time()
for q in ('resource.type = "container" AND resource.labels.container_group_name = "render-4090m2"',):
    try:
        es = PL.log_entries(q, now - 1200, now)
    except Exception as e:
        print('ERR', type(e).__name__, str(e)[:300])
        continue
    print('query', q, 'записей', len(es))
    for x in es:
        print(x.get('text_log') or '')
