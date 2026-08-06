#!/usr/bin/env python3
"""Таблица «категория × признак»: что спрашивать у модели и сколько это весит.

Одна таблица вместо двух разных мест. Раньше вопросы задавались по семи ГРУППАМ, а ранги правил
были общими на весь каталог — и они расходились: у пледа спрашивали про ножки, а «отсутствие
декора» весило одинаково у комода и у вазы. Из-за этого в четырёх категориях один стиль забирал
все десять позиций (замер 270 карточек, 2026-08-06).

Таблица собирается из трёх источников:
  1. применимость — из смысла вещи (юбка бывает только у мягкой мебели, ворс только у ковра);
  2. ранг — из дизайнерских правил `style_rules.json` (что названо определяющим);
  3. понижение — из фактической частоты внутри КАТЕГОРИИ: маркер обязан быть редким именно
     здесь. У малочисленных категорий (ковёр 26, часы 53) частота шумная — там ранг берём
     из источников, не из данных.

  ~/venvs/scout/bin/python matrix_build.py --build
  ~/venvs/scout/bin/python matrix_build.py --show люстра
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from role_prompt import Q, group_of  # noqa: E402

OUT = os.path.join(HERE, 'style-matrix.json')
MIN_FOR_FREQ = 150       # меньше товаров в категории — частоте не верим

# Точечная применимость: что у КОНКРЕТНОЙ вещи спрашивать бессмысленно, хотя её группа это умеет.
DROP = {
    'пуф': ['arms', 'back'],                     # у пуфа нет подлокотников и спинки
    'полка': ['handles', 'handle_finish', 'base'],  # навесная полка без ручек и основания
    'стеллаж': ['handles', 'handle_finish'],
    'люстра': ['base_form'],                     # у подвеса нет основания
    'бра': ['base_form'],
    'плед': ['heading'],                         # верх бывает только у шторы
    'подушка': ['heading'],
    'зеркало': ['glaze', 'pot_material'],
    'часы': ['glaze', 'pot_material'],
    'камин': ['pot_material'],
    'растение': ['relief', 'frame'],
    'статуэтка': ['pot_material', 'frame'],
    'ваза': ['frame'],
    'стул': ['top_shape', 'edge', 'top_material'],   # у стула нет столешницы
}
# Что добавить сверх набора группы
ADD = {
    'стул': {'back': ['отдельные_подушки', 'цельная', 'стёганая', 'низкая_прямая', 'не_видно'],
             'seat_height': ['низкая', 'средняя', 'высокая', 'не_видно']},
    'камин': {'top_material': ['дерево', 'шпон', 'стекло', 'камень', 'металл', 'ЛДСП', 'неясно']},
}
# Свои маркеры категории (из источников), даже если частота их не выделяет
# Категории, у которых стиля нет по природе вещи: искусственная зелень одинаково уместна
# в любом интерьере, а её «стиль» задаёт кашпо, а не сам букет (замер 2026-08-06).
NEUTRAL_BY_NATURE = {'растение'}

CATEGORY_MARKERS = {
    'люстра': ['frame', 'shade', 'shade_material'],
    'бра': ['frame', 'shade_material'],
    'торшер': ['base_form', 'shade_material'],
    'лампа': ['base_form', 'shade_material'],
    'ковёр': ['pile', 'rug_pattern'],
    'плед': ['weave', 'edge_trim'],
    'подушка': ['weave', 'edge_trim', 'textile_pattern'],
    'шторы': ['heading', 'weave'],
    'зеркало': ['frame', 'form'],
    'часы': ['frame', 'form'],
    'ваза': ['form', 'relief', 'pot_material'],
    'статуэтка': ['form', 'relief'],
    'камин': ['form', 'top_material'],
    'диван': ['arms', 'tufting', 'skirt', 'legs'],
    'кресло': ['arms', 'tufting', 'skirt', 'legs'],
    'пуф': ['tufting', 'legs', 'shape'],
    'столик': ['base', 'top_material', 'ornament'],
    'стол обеденный': ['base', 'top_material', 'ornament'],
    'стул': ['legs', 'back'],
    'комод': ['fronts', 'handles', 'base', 'ornament'],
    'тв-тумба': ['fronts', 'handles', 'base'],
    'шкаф': ['fronts', 'handles', 'ornament'],
    'стенка': ['fronts', 'openness', 'ornament'],
    'витрина': ['fronts', 'openness', 'ornament'],
    'стеллаж': ['openness', 'body'],
    'полка': ['body', 'openness'],
    'растение': ['form', 'pot_material'],
}


COLOURS = ['белый', 'бежевый', 'серый', 'чёрный', 'коричневый', 'синий', 'зелёный', 'жёлтый',
           'красный', 'розовый', 'фиолетовый', 'оранжевый', 'разноцветный', 'не_определён']


def attrs_for_category(role: str) -> dict:
    g = group_of(role)
    if not g:
        return {}
    out = {k: dict(v) for k, v in Q[g]['attrs'].items() if k not in (DROP.get(role) or [])}
    # цвет участвует у всех: насыщенные оттенки — язык современного, монохром — минимализма
    out['primary_color'] = {'q': 'основной цвет', 'opts': COLOURS}
    for k, opts in (ADD.get(role) or {}).items():
        out.setdefault(k, {'q': k, 'opts': opts})
    return out


def build() -> dict:
    rules = json.load(open(os.path.join(HERE, 'style_rules.json')))['rules']
    freq_path = os.path.join(HERE, 'attr-freq-cat.json')
    catfreq = json.load(open(freq_path)) if os.path.exists(freq_path) else {}
    totals = catfreq.get('_totals', {})
    matrix = {}
    for role in sorted({r for g in Q.values() for r in g['roles']}):
        attrs = attrs_for_category(role)
        if not attrs:
            continue
        cells = {}
        own = CATEGORY_MARKERS.get(role) or []
        for attr, spec in attrs.items():
            per_value = {}
            for val in spec['opts']:
                hit = [r for r in rules if r['attr'] == attr and r['value'] == val]
                if not hit:
                    continue
                tiers = {}
                for st, t in (hit[0].get('tiers') or {}).items():
                    tier = t['tier']
                    # частота внутри категории: частый здесь признак маркером быть не может
                    n = totals.get(role, 0)
                    f = catfreq.get(f'{role}|{attr}={val}')
                    if n >= MIN_FOR_FREQ and f is not None:
                        if f > 0.45:
                            tier = 'фон'
                        elif f > 0.22 and tier == 'маркер':
                            tier = 'поддержка'
                    # признак, названный определяющим ДЛЯ ЭТОЙ вещи, не опускается ниже поддержки
                    if attr in own and tier == 'фон' and t.get('sign', 1) > 0:
                        tier = 'поддержка'
                    tiers[st] = {'tier': tier, 'sign': t.get('sign', 1)}
                per_value[val] = {'tiers': tiers, 'veto': hit[0].get('veto') or []}
            cells[attr] = {'q': spec['q'], 'opts': spec['opts'], 'values': per_value,
                           'own_marker': attr in own}
        matrix[role] = {'group': group_of(role), 'attrs': cells,
                        'neutral_by_nature': role in NEUTRAL_BY_NATURE}
    json.dump(matrix, open(OUT, 'w'), ensure_ascii=False)
    print(f'категорий в таблице: {len(matrix)}')
    print(f'{"категория":16s} {"вопросов":>9} {"своих маркеров":>15}')
    for role, m in sorted(matrix.items()):
        own = sum(1 for a in m['attrs'].values() if a['own_marker'])
        print(f'{role:16s} {len(m["attrs"]):>9} {own:>15}')
    return matrix


def load() -> dict:
    return json.load(open(OUT)) if os.path.exists(OUT) else build()


def show(role: str) -> None:
    m = load().get(role)
    if not m:
        print(f'категории «{role}» в таблице нет')
        return
    print(f'{role} (группа {m["group"]}), вопросов {len(m["attrs"])}\n')
    for attr, a in m['attrs'].items():
        mark = ' ← свой маркер' if a['own_marker'] else ''
        print(f'  {a["q"]}{mark}')
        for val, cell in list(a['values'].items())[:4]:
            tt = ', '.join(f'{s} {t["tier"]}{"−" if t["sign"] < 0 else ""}'
                           for s, t in list(cell['tiers'].items())[:3])
            print(f'      {val:24s} {tt}')


def main() -> None:
    if '--build' in sys.argv:
        build()
    elif '--show' in sys.argv:
        show(sys.argv[sys.argv.index('--show') + 1])
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
