"""T-118: снимок модели 1024 px для макета увеличения (тот же ракурс, что у постера 320 px). Без сети, без записи в БД."""
import os
import sys

sys.path.insert(0, '/home/pakar/igor/remlab/tools/scout')
from PIL import Image  # noqa: E402

from mesh_audit_posters import PITCH, YAW, poster_name  # noqa: E402
from mesh_queue import db  # noqa: E402
from mesh_render import load_parts, render  # noqa: E402

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
for sku in sys.argv[2:]:
    rows = db(f"select generation_key, path from mesh_generations where sku = '{sku}' order by generated_at desc, generation_key desc limit 1")
    gk, path = rows[0]
    im = render(load_parts(os.path.join(path, 'model.glb')), YAW, PITCH, size=(1024, 1024))
    bg = Image.new('RGB', im.size, (244, 244, 242))
    bg.paste(im, (0, 0), im)
    dst = os.path.join(OUT, 'hd-' + poster_name(gk))
    bg.save(dst, 'JPEG', quality=86)
    print('HD', sku, dst, os.path.getsize(dst))

# Тот же слот очереди: сразу снимки макета (без 3D), чтобы не стоять в очереди второй раз (ядра DEV заняты 14,6 из 15).
import subprocess  # noqa: E402
import time  # noqa: E402

shots = os.path.expanduser('~/remlab-logs/t118-1112/' + time.strftime('%H%M'))
here = os.path.dirname(os.path.abspath(__file__))
subprocess.run(['node', os.path.join(here, '.t118-shots.mjs'), shots], check=False)
print('SHOTS_DIR', shots)
