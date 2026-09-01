#!/usr/bin/env python3
"""ГЕЙТ 0 плана `photo-improve-from-mesh`: замер до всякой разработки.

Два вопроса, на которые нельзя отвечать по памяти, потому что от ответа зависит, имеет ли смысл
остальное:

1. **Какой максимальный размер листа принимает шлюз.** Сейчас вертикальный лист запрашивается как
   1024×1536 — после резки на два вида это ~720 px на вид против 1344×896 у нашего исходного
   кадра, то есть мы отдаём модели хороший кадр и забираем вдвое хуже. Владелец 01.09: «надо с
   высоким разрешением запрашивать, чтоб потом разрезать».
2. **Соблюдается ли маска.** По документации OpenAI маска — guidance, не гарантия. Проверяется
   честно: ПОЛНОСТЬЮ НЕПРОЗРАЧНАЯ маска (редактировать нечего) обязана вернуть кадр без изменений.
   Не вернула — значит на маску опираться нельзя, и единственный механизм защиты мебели остаётся
   композит поверх ответа.

Деньги: каждый вызов платный, поэтому по умолчанию `quality=low` и минимум запросов; список
размеров задаётся явно. Сначала `--dry-run` — он показывает, что будет отправлено и почём.

  improve_probe.py --dry-run
  improve_probe.py --sizes 1024x1536,1536x2048 --mask-test
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PIL import Image  # noqa: E402

SIZES = ('1024x1536', '1536x1024', '1536x2048', '2048x1536', '2048x3072', 'auto')
OUT = os.path.expanduser('~/scout-scenes/improve-probe')
PROMPT = ('Renovate only the wall, ceiling and floor surfaces of this room in a light neoclassical '
          'style. Keep every piece of furniture exactly as it is: same position, size, shape, '
          'colour and count. Do not add or remove any object. Return one image.')


def base_frame() -> Image.Image:
    """Берём НАСТОЯЩИЙ кадр сцены, а не синтетику: замер должен идти по тому входу, который
    поедет в бою. Самый свежий файл из папки кадров."""
    import glob
    fr = os.environ.get('FRAMES_DIR', os.path.expanduser('~/scout-scenes/frames'))
    cands = sorted(glob.glob(os.path.join(fr, 'scene3d-*-C1.jpg')), key=os.path.getmtime)
    if not cands:
        raise SystemExit(f'нет кадров сцены в {fr} — сначала сделай кадр в демо')
    return Image.open(cands[-1]).convert('RGB')


def opaque_mask(size) -> Image.Image:
    """Маска «редактировать НЕЧЕГО»: полностью непрозрачная. Прозрачное = разрешено менять."""
    return Image.new('RGBA', size, (0, 0, 0, 255))


def diff_pct(a: Image.Image, b: Image.Image) -> float:
    import numpy as np
    if a.size != b.size:
        b = b.resize(a.size)
    x = np.asarray(a.convert('RGB'), int)
    y = np.asarray(b.convert('RGB'), int)
    return round(float((np.abs(x - y).max(axis=2) > 12).mean()) * 100, 2)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    sizes = (sys.argv[sys.argv.index('--sizes') + 1].split(',')) if '--sizes' in sys.argv \
        else list(SIZES)
    quality = sys.argv[sys.argv.index('--quality') + 1] if '--quality' in sys.argv else 'low'
    dry = '--dry-run' in sys.argv
    img = base_frame()
    print(f'исходный кадр: {img.width}×{img.height}')
    print(f'проверяю размеры: {", ".join(sizes)} (качество {quality})')
    if '--mask-test' in sys.argv:
        print('плюс проверка маски: полностью непрозрачная маска обязана вернуть кадр без правок')
    if dry:
        n = len(sizes) + (1 if '--mask-test' in sys.argv else 0)
        print(f'--dry-run: было бы {n} платных вызовов, ничего не отправлено')
        return 0
    from draft_render import gpt_edit
    from openai_budget import allow
    n = len(sizes) + (1 if '--mask-test' in sys.argv else 0)
    if not allow('gpt-image-2', n, note='improve_probe'):
        print('дневной лимит не пускает')
        return 1
    rows = []
    for sz in sizes:
        try:
            out = gpt_edit([img], PROMPT, size=sz, quality=quality)
            path = os.path.join(OUT, f'size-{sz}.png')
            out.save(path)
            rows.append({'size': sz, 'ok': True, 'got': f'{out.width}x{out.height}', 'file': path})
            print(f'  {sz:<12} → принят, вернул {out.width}×{out.height}')
        except Exception as e:  # noqa: BLE001 — нам важна ПРИЧИНА отказа, а не падение замера
            rows.append({'size': sz, 'ok': False, 'err': str(e)[:160]})
            print(f'  {sz:<12} → отказ: {str(e)[:120]}')
    if '--mask-test' in sys.argv:
        ok_sizes = [r['size'] for r in rows if r.get('ok')]
        sz = ok_sizes[-1] if ok_sizes else '1024x1536'
        try:
            out = gpt_edit([img], PROMPT, size=sz, quality=quality, mask=opaque_mask(img.size))
            out.save(os.path.join(OUT, 'mask-opaque.png'))
            d = diff_pct(img, out)
            rows.append({'mask_test': True, 'size': sz, 'changed_pct': d})
            print(f'\nмаска «менять нечего» ({sz}): изменено {d}% пикселей '
                  + ('— МАСКА СОБЛЮДАЕТСЯ' if d < 2 else '— МАСКА НЕ РАБОТАЕТ, нужен композит'))
        except Exception as e:  # noqa: BLE001
            rows.append({'mask_test': True, 'err': str(e)[:160]})
            print(f'\nпроверка маски не прошла: {str(e)[:140]}')
    json.dump(rows, open(os.path.join(OUT, 'probe.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f'\nрезультаты и картинки: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
