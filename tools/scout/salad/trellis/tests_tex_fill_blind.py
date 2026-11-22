"""Тест мерки «слепое продолжение поверхности» (tex_fill_blind): фейковая мишень → заморозка (local/far/side и wholepart) → run → в каждой записи поля причин решений, без `error`.
Бесплатно, без GPU и без сети: три однотонные «серые» плиты (шум только по яркости), одна роль; черновика TRELLIS нет (источник stat). Запуск: `python tests_tex_fill_blind.py` → «ошибок 0»."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
from PIL import Image
import tex_fill as TF
import tex_fill_blind as BL
from tests_tex_fill import Quads

bad = 0


def ok(cond, msg):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond:
        bad += 1


REASON_KEYS = ('texture_src', 'borrowed_from', 'tone_from', 'relief_why', 'relief_texels', 'source_used', 'quilt_info', 'quilt_rejected_share', 'pattern_part')


def fake_item(root: str, sku: str, T: int = 512) -> None:
    rng = np.random.RandomState(11)
    q = Quads()
    for i in range(3):                                                           # три плиты рядом по u, у каждой свой островок; разнесены в пространстве → три части
        q.quad([[i * 2, 0, 0], [i * 2 + 1, 0, 0], [i * 2 + 1, 1, 0], [i * 2, 1, 0]], (i / 4.0, 0, (i + 1) / 4.0, 1), part=i, sub=8)
    q.quad([[1, 0, 0], [1, 0, -1], [1, 1, -1], [1, 1, 0]], (0.75, 0, 0.85, 1), part=0, sub=8)     # боковая стенка части 0, уже передней (средняя нормаль — на камеру; режим side берёт куски, смотрящие вбок)
    tex = np.clip(140 + rng.normal(0, 5, (T, T, 1)), 0, 255).astype(np.uint8).repeat(3, axis=2)
    g = q.geom(tex)
    vis = os.path.join(root, sku, '06-visible')
    os.makedirs(vis, exist_ok=True)
    TF.write_glb([g], [tex], os.path.join(vis, 'visible.glb'))
    Image.fromarray(np.full((T, T), 255, np.uint8)).save(os.path.join(vis, 'known.png'))
    p3 = os.path.join(root, sku, '03-parts')
    os.makedirs(p3, exist_ok=True)
    json.dump({'parts': [{'id': i, 'role': 'body'} for i in range(3)]}, open(os.path.join(p3, 'parts.json'), 'w'))
    np.savez(os.path.join(p3, 'parts.npz'), part=np.asarray(q.part, np.int16))                        # этап 3: часть каждой грани (одна плита — одна часть)


def test_blind_reason_fields():
    seen = set()
    print('мерка Б: запись run содержит причины решений и не содержит error (local/far/side и wholepart):')
    with tempfile.TemporaryDirectory() as d:
        root, sku = os.path.join(d, 'root'), 'fake_1'
        fake_item(root, sku)
        for wp in (False, True):
            out = os.path.join(d, 'wp' if wp else 'std')
            os.makedirs(out)
            argv = ['--wholepart'] if wp else []
            rc = BL.cmd_freeze(argv + [out, f'{root}:{sku}'])
            ok(rc == 0, f'заморозка ({"wholepart" if wp else "local/far/side"}) rc=0')
            fz = json.load(open(os.path.join(out, 'frozen', 'frozen.json'), encoding='utf-8'))
            modes = {m: ('skipped' not in md) for m, md in fz['items'][0]['modes'].items()}
            print('     режимы:', modes)
            ok(any(modes.values()), 'хотя бы один режим заморожен (мишень годится)')
            rc = BL.cmd_run(['--tag', 't', out, os.path.join(out, 'frozen')])
            ok(rc == 0, f'run rc=0')
            recs = [json.loads(x) for x in open(os.path.join(out, 'blind-t.jsonl'), encoding='utf-8')]
            ok(len(recs) > 0 and not any('error' in r for r in recs), f'записей {len(recs)}, ошибок 0')
            seen |= {r.get('mode') for r in recs}
            for r in recs:
                miss = [k for k in REASON_KEYS if k not in r]
                ok(not miss, f'{r.get("mode")} / зеркало {r.get("mirror")}: поля причин на месте' + (f' (нет: {miss})' if miss else ''))
            if wp:
                ok(any(r.get('mode') == 'wholepart' for r in recs), 'в записях есть режим wholepart')
    ok(seen == {'local', 'far', 'side', 'wholepart'}, f'проверены ВСЕ четыре режима мерки (видели {sorted(seen)})')


def main() -> int:
    test_blind_reason_fields()
    print(f'tests_tex_fill_blind: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
