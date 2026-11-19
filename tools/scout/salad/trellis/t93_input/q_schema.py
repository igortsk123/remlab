#!/usr/bin/env python3
"""T-93: разведка колонок products (только чтение; тот же способ доступа, что у catalog_media — PSQL оттуда)."""
import json
import subprocess
import sys

sys.path.insert(0, '/home/pakar/igor/remlab/.claude/worktrees/trellis-trial/tools/scout')
import catalog_media as CM


def q(sql):
    r = subprocess.run(CM.PSQL + [sql], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit('psql rc=%s %s' % (r.returncode, r.stderr[:300]))
    return r.stdout


for t in ('product_photo_current', 'api_offers', 'product_enrichment', 'catalog_ready'):
    print('---', t)
    print(q("select column_name||' '||data_type from information_schema.columns where table_name='%s' order by ordinal_position" % t))
