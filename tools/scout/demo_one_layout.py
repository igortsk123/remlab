#!/usr/bin/env python3
"""ОДНА РАССТАНОВКА НА ВСЕ СТИЛИ ДЕМО (demo-31, владелец 02.11, TG 55/58; T-20261102-01).

Было: демо звало солвер отдельно на каждый сет, и у современного/минимализма диван и ТВ стояли у противоположной
стены — при переключении стиля «другая комната». Теперь: солвер берёт только гипотезы с опорной подписью
(`rules/demo-layout.json` → env `LAYOUT_SIGNATURE_FILE`, фильтр — `planner/zones.py:_signature_filter`), а здесь —
сверка подписи итоговых расстановок и выравнивание центров дивана/столика/ТВ/ковра по общей оси. Ось берётся та,
при которой ни у одного варианта не прибавилось жёстких нарушений `planner.validate`; прочая мебель не двигается.

  ~/venvs/scout/bin/python demo_one_layout.py --selftest
"""
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, 'rules', 'demo-layout.json')
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))


def rules() -> dict:
    return json.load(open(RULES_PATH, encoding='utf-8'))


def enabled(env=os.environ) -> bool:
    """Включено: env DEMO_ONE_LAYOUT=1/0, иначе `enabled` в правиле (по умолчанию выключено — см. `_enabled_why`)."""
    v = env.get('DEMO_ONE_LAYOUT')
    return v == '1' if v in ('0', '1') else bool(rules().get('enabled'))


def _base(role: str) -> str:
    """«стул 2» → «стул», «стол обеденный» — как есть (солверное `base_role`)."""
    from planner.geometry import base_role
    return base_role(role)


def _placed(art: dict) -> dict:
    return {k: v for k, v in art.items() if not k.startswith('_') and isinstance(v, dict) and 'x' in v}


def signature(art: dict) -> str:
    """Подпись расстановки из артефакта солвера (`x`, `z` — центр, см) — тот же расчёт, что у фильтра солвера."""
    from planner.zones import signature_xy
    pos: dict = {}
    for k, v in _placed(art).items():
        pos.setdefault(_base(k), (v['x'], v['z']))
    return signature_xy(art['_room']['w'], art['_room']['d'], pos)


def _scene(art: dict):
    from planner.models import Item, Placement, Room
    r = art['_room']
    room = Room(width_cm=r['w'], depth_cm=r['d'], openings=r.get('openings') or [], radiators=r.get('radiators') or [])
    ps = [Placement(role=k, x=v['x'], y=v['z'], rot=v.get('rot') or 0,
                    item=Item(role=k, w_cm=v['w'], d_cm=v['d'], h_cm=v.get('h') or 60, corner=bool(v.get('corner')),
                              corner_section_cm=float(v.get('section') or 95), corner_left=bool(v.get('corner_left'))))
          for k, v in _placed(art).items()]
    return room, ps


def hard_codes(art: dict) -> set:
    """Жёсткие нарушения расстановки по `planner.validate` (код|роли) — для сравнения до/после сдвига."""
    from planner.validate import validate
    room, ps = _scene(art)
    return {f"{v.code}|{','.join(sorted(v.roles))}" for v in validate(room, ps).violations if v.severity.name == 'HARD'}


def _axis_dim(art: dict) -> str | None:
    """По какой координате выравнивать: диван у N/S стены — ось вертикальная (x), у W/E — горизонтальная (z)."""
    s = signature(art).split('|')[0].split(':')[1]
    return 'x' if s in ('N', 'S') else 'z' if s in ('W', 'E') else None


def shifted(art: dict, dim: str, value: float, roles: list) -> dict:
    """Копия артефакта: центры осевых ролей (первая штука роли, без номера) — на `value` по `dim`; прочее как было."""
    out = dict(art)
    for r in roles:
        if isinstance(art.get(r), dict) and 'x' in art[r]:
            out[r] = dict(art[r], **{dim: round(value, 1)})
    return out


def align(arts: dict, cfg: dict | None = None) -> tuple[dict, dict]:
    """{вариант: артефакт} → ({вариант: выровненный артефакт}, отчёт).

    Кандидаты оси — центр дивана каждого варианта и их медиана; берём ту, где ни у кого не прибавилось жёстких нарушений,
    при равенстве — меньший наибольший сдвиг. Такой нет — варианты остаются как были, отчёт `ok=False` (ворота громко)."""
    cfg = cfg or rules()
    roles = cfg.get('axis_roles') or []
    walls = {signature(a).rsplit('|', 1)[0] for a in arts.values()}
    dims = {_axis_dim(a) for a in arts.values()}
    if len(walls) != 1 or len(dims) != 1 or None in dims:
        return arts, {'ok': False, 'why': f'стены дивана/ТВ у вариантов разные: {sorted(walls)}'}
    dim = dims.pop()
    sofa = [a['диван'][dim] for a in arts.values() if isinstance(a.get('диван'), dict)]
    if not sofa:
        return arts, {'ok': False, 'why': 'дивана нет ни в одном варианте'}
    before = {n: hard_codes(a) for n, a in arts.items()}
    best = None
    for value in sorted(set([round(statistics.median(sofa), 1)] + [round(s, 1) for s in sofa])):
        trial = {n: shifted(a, dim, value, roles) for n, a in arts.items()}
        new = {n: sorted(hard_codes(t) - before[n]) for n, t in trial.items()}
        bad = sum(len(v) for v in new.values())
        move = max(abs(a[r][dim] - value) for a in arts.values() for r in roles if isinstance(a.get(r), dict) and 'x' in a[r])
        key = (bad, move)
        if best is None or key < best[0]:
            best = (key, value, trial, new)
    (bad, move), value, trial, new = best
    rep = {'ok': bad == 0, 'dim': dim, 'axis': value, 'max_shift_cm': round(move, 1),
           'new_hard': {n: v for n, v in new.items() if v}}
    return (trial if bad == 0 else arts), rep


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    room = {'w': 439, 'd': 325, 'openings': [], 'radiators': []}

    def art(sx, extra=None):
        a = {'_room': room,
             'диван': {'x': sx, 'z': 280, 'rot': 180, 'w': 198, 'd': 90},
             'столик': {'x': sx + 3, 'z': 165, 'rot': 180, 'w': 120, 'd': 58},
             'ковёр': {'x': sx - 2, 'z': 180, 'rot': 180, 'w': 230, 'd': 160},
             'тв-тумба': {'x': sx + 1, 'z': 25, 'rot': 0, 'w': 140, 'd': 40},
             'стол обеденный': {'x': 394, 'z': 50, 'rot': 270, 'w': 90, 'd': 90}}
        a.update(extra or {})
        return a

    a1, a2 = art(155.3), art(194.3)
    ok('подпись: диван у южной стены, ТВ у северной, обед — СВ', signature(a1) == 'диван:S|тв:N|обед:NE')
    b = dict(a1)
    b.pop('стол обеденный')
    ok('нет роли — «-» в подписи', signature(b).endswith('обед:-'))
    out, rep = align({'set1': a1, 'set6': a2})
    ok('выравнивание: общая ось по x', rep['ok'] and rep['dim'] == 'x')
    xs = {round(out[n][r]['x'], 1) for n in out for r in ('диван', 'столик', 'ковёр', 'тв-тумба')}
    ok('центры дивана/столика/ковра/ТВ — на одной оси у обоих', len(xs) == 1)
    ok('обеденный стол не сдвинут', out['set1']['стол обеденный'] == a1['стол обеденный'])
    c = art(170.0)
    c.pop('столик')
    out2, rep2 = align({'set1': a1, 'set9': c})
    ok('нет столика в варианте — место пустое, прочее выровнено', 'столик' not in out2['set9'] and rep2['ok']
       and out2['set9']['диван']['x'] == out2['set1']['диван']['x'])
    mir = art(160.0)
    mir['диван'] = dict(mir['диван'], z=50, rot=0)
    mir['тв-тумба'] = dict(mir['тв-тумба'], z=300, rot=180)
    _, rep3 = align({'set1': a1, 'set6': mir})
    ok('разные стороны дивана — не выравнивает, ok=False', not rep3['ok'])
    print('OK' if not bad else f'ПРОВАЛОВ: {bad}')
    return bad


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(1 if _selftest() else 0)
    print(__doc__)
