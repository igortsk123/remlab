"""Глубина диванов и кресел divan.ru из «Размеры: Глубина габаритная» (conv-14, T-20261104-01). Без сети, базы и солвера.

У угловых диванов divan.ru глубина лежит только в «Размеры: Глубина габаритная»; резолвер её не читал → d пустая →
`footprint.require` → DimsUnknown (экзамен set58/77/78). Проверяем:
  1) только новый ключ → d из него; оба ключа → «Глубина габаритная» первой; у комода (только «Ширина габаритная») — как было;
  2) опечатка 750 см (архивный «Винси Textile Ocean», принято 04.11) — глубина пустая, на «Ширину габаритную» не уходим;
  3) у других магазинов разбор не изменился: выборка карточек 6 магазинов / 26 ролей
     (`fixtures/dims-other-shops-sample.jsonl`) — тот же результат с ключом и без него (теневой разбор всей БД 04.11:
     0 изменений из 15 185 карточек вне 112923).
    python3 tools/scout/tests/test_dims_gabarit.py"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..')
sys.path.insert(0, SCOUT)
os.environ.setdefault('SCOUT_PRIORS_PATH', os.path.join(HERE, 'fixtures', 'unit-priors-mini.json'))
import dim_resolver as R  # noqa: E402

NEW = 'Размеры: Глубина габаритная'
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


def d_of(mid, name, params, role):
    dims, ev, _ = R.resolve(mid, name, params, role)
    return dims.get('d'), (ev.get('d') or {}).get('source')


check('ключ «Глубина габаритная» стоит в d раньше «Ширины габаритной»',
      NEW in R.DIM_KEYS['d'] and R.DIM_KEYS['d'].index(NEW) < R.DIM_KEYS['d'].index('Размеры: Ширина габаритная'))
check('угловой диван: только «Глубина габаритная» → 164 из карточки',
      d_of(112923, 'Диван угловой divan.ru Биани-1 Велюр Темно-синий',
           {'Размеры: Длина габаритная': '246см', NEW: '164см', 'Размеры: Высота габаритная': '85см'}, 'диван') == (164.0, 'param'))
check('оба ключа → глубина из «Глубины габаритной»',
      d_of(112923, 'Кресло divan.ru Дилан', {NEW: '90см', 'Размеры: Ширина габаритная': '80см'}, 'кресло') == (90.0, 'param'))
check('комод (только «Ширина габаритная») — глубина как до правки',
      d_of(112923, 'Комод divan.ru Монблан', {'Размеры: Длина габаритная': '185см', 'Размеры: Ширина габаритная': '50см',
                                              'Размеры: Высота габаритная': '76см'}, 'комод') == (50.0, 'param'))
check('опечатка 750 см (Винси, архив) — глубина пустая, не 75 из «Ширины габаритной»',
      d_of(112923, 'Диван прямой divan.ru Винси Textile Ocean',
           {'Размеры: Длина габаритная': '122см', NEW: '750см', 'Размеры: Ширина габаритная': '75см'}, 'диван')[0] is None)

# 3) у других магазинов — тот же разбор с ключом и без него
rows = [json.loads(ln) for ln in open(os.path.join(HERE, 'fixtures', 'dims-other-shops-sample.jsonl'), encoding='utf-8')]
with_key = [R.resolve(r['mid'], r['name'] or '', r['params'] or {}, r['role'])[:2] for r in rows]
saved = copy.deepcopy(R.DIM_KEYS)
R.DIM_KEYS['d'] = [k for k in R.DIM_KEYS['d'] if k != NEW]
try:
    without = [R.resolve(r['mid'], r['name'] or '', r['params'] or {}, r['role'])[:2] for r in rows]
finally:
    R.DIM_KEYS.clear(); R.DIM_KEYS.update(saved)
diff = [r['name'] for r, a, b in zip(rows, with_key, without) if a != b]
check(f'другие магазины ({len(rows)} карточек, {len({r["mid"] for r in rows})} магазинов): разбор не изменился'
      + (f' — изменились: {diff[:3]}' if diff else ''), len(rows) >= 100 and 112923 not in {r['mid'] for r in rows} and not diff)

sys.exit(1 if fails else 0)
