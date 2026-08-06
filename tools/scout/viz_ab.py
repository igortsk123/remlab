#!/usr/bin/env python3
"""A/B финальной модели (А6): те же входы и промпт, что получал gpt-image-2, — в кандидата
через fal, затем тот же пост-QA (`viz_qa`). Числа для решения владельца (выбор модели — человек).

  ~/venvs/scout/bin/python viz_ab.py 21                       # кандидат по умолчанию — NB Pro
  ~/venvs/scout/bin/python viz_ab.py 21 --model fal-ai/nano-banana/edit

Вход: scene{n}-pair-{collage,marked,identity}.jpg + план + scene{n}-pair-prompt.txt (сохранены
прошлым прогоном viz_final). Выход: scene{n}-pair-final-ab.jpg, scene{n}-{cam}-final-ab.jpg,
scene{n}-ab.json (цена, время, вердикты QA обеих версий).
"""
import json
import os
import sys
import time
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from viz_base import fal_key, fal_run, uri_from_image  # noqa: E402
from viz_final import split_pair  # noqa: E402

SCENE_DIR = os.path.expanduser(os.environ.get('SCENE_DIR', '~/scout-scenes'))
DEFAULT_MODEL = 'fal-ai/nano-banana-pro/edit'


def main() -> None:
    n = int(sys.argv[1])
    model = (sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else DEFAULT_MODEL)
    pref = os.path.join(SCENE_DIR, f'scene{n}-pair')
    prompt = open(f'{pref}-prompt.txt').read()
    imgs = []
    for p in (f'{pref}-collage.jpg', f'{pref}-marked.jpg',
              os.path.join(SCENE_DIR, f'scene{n}-plan.png'), f'{pref}-identity.jpg'):
        if os.path.exists(p):
            imgs.append(Image.open(p).convert('RGB'))
    t0 = time.time()
    res = fal_run(model, {'prompt': prompt,
                          'image_urls': [uri_from_image(im) for im in imgs],
                          'num_images': 1,
                          'output_format': 'jpeg',
                          'resolution': '2K'},
                  fal_key(), timeout=600)
    url = (res.get('images') or [{}])[0].get('url')
    if not url:
        raise SystemExit(f'нет картинки в ответе: {json.dumps(res)[:300]}')
    raw = urllib.request.urlopen(url, timeout=300).read()
    open(f'{pref}-final-ab.jpg', 'wb').write(raw)
    out = Image.open(f'{pref}-final-ab.jpg')
    dt = time.time() - t0
    cams = ['C1', 'C2']
    try:
        parts = split_pair(out)
    except Exception as e:  # noqa: BLE001 — маджента-полоса могла не сохраниться: это уже вердикт
        print(f'разрез по полосе не удался ({str(e)[:80]}) — модель не сохранила разделитель')
        parts = []
    qa = {}
    if parts:
        from viz_qa import qa_cam
        for c, part in zip(cams, parts):
            part.save(os.path.join(SCENE_DIR, f'scene{n}-{c}-final-ab.jpg'), quality=94)
            # подмена финала на AB-вариант для QA, затем возврат
            fin = os.path.join(SCENE_DIR, f'scene{n}-{c}-final.jpg')
            bak = fin + '.bak'
            has_orig = os.path.exists(fin)
            if has_orig:
                os.replace(fin, bak)
            os.link(os.path.join(SCENE_DIR, f'scene{n}-{c}-final-ab.jpg'), fin)
            try:
                qa[c] = qa_cam(n, c)
            finally:
                os.remove(fin)
                if has_orig:
                    os.replace(bak, fin)
    rec = {'model': model, 'seconds': round(dt, 1), 'split_ok': bool(parts),
           'qa_pass': qa, 'size': list(out.size)}
    json.dump(rec, open(os.path.join(SCENE_DIR, f'scene{n}-ab.json'), 'w'),
              ensure_ascii=False, indent=1)
    print(json.dumps(rec, ensure_ascii=False))


if __name__ == '__main__':
    main()
