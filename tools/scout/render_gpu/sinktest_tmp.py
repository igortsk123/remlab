import sys, json, urllib.request
sys.path.insert(0, '/home/pakar/igor/remlab/.claude/worktrees/render-gpu/tools/scout/salad')
import migrate_groups as MG
MG.env_from_file()
c, d = MG.api('/mesh-q-low-1')
env = d['container']['environment_variables']
url = env['MESH_SINK_URL'].rstrip('/')
print('url', url)
req = urllib.request.Request(f'{url}/staging/renderbench-1117/probe-dev/ping.txt', data=b'ping', method='PUT',
                             headers={'Authorization': 'Bearer ' + env['MESH_SINK_TOKEN'], 'Content-Type': 'application/octet-stream'})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print('HTTP', r.status, r.read()[:200])
except Exception as e:
    print('ERR', type(e).__name__, str(e)[:300], getattr(e, 'read', lambda: b'')()[:300])
