"""Патч «канон важнее допуска» (Codex q5-axis-shift-tier.answer.md, владелец №31): применять ПОСЛЕ экзамена."""
import re, json, collections
ROOT='/home/pakar/igor/remlab/services/planner-solver/'
# --- template.py: пометки допусков в tpl_variant (+table_axis_shifted, +gapNN), enumeration: ≤1 деградированный вариант на форму
p=ROOT+'planner/template.py'; s=open(p).read()
s=s.replace("""                      _variant0 = shape + ('+axis_shifted' if _shift else '')
                      for _pv in _one:
                          _pv.tpl_variant = _variant0
                      _enum.append(_one)""",
"""                      _variant0 = shape + _tol_tag(_gap, _shift)
                      # Codex 17.08 (владелец №31): деградированных вариантов (сдвиг/нестандартный
                      # зазор) — не более ОДНОГО на форму в перечислении; канон — все топологии
                      if _tol_tag(_gap, _shift):
                          if shape in _enum_degraded:
                              continue
                          _enum_degraded.add(shape)
                      for _pv in _one:
                          _pv.tpl_variant = _variant0
                      _enum.append(_one)""")
s=s.replace("""                  _variant = shape + ('+axis_shifted' if _shift else '')
                  LAST_AXIS_DIAG = {'table': {""","""                  _variant = shape + _tol_tag(_gap, _shift)
                  LAST_AXIS_DIAG = {'table': {""")
s=s.replace("""                                for _pv in _one:
                                    _pv.tpl_variant = shape + ('+axis_shifted' if _shift else '')
                                _saved.append(_one)""","""                                for _pv in _one:
                                    _pv.tpl_variant = shape + _tol_tag(_gap, _shift)
                                _saved.append(_one)""")
assert "_tol_tag(_gap, _shift)" in s
# helper + degraded set init
s=s.replace("""    variants = tries
    # ЭФФЕКТИВНАЯ группа (11.08)""","""    variants = tries
    _enum_degraded: set = set()

    def _tol_tag(gap: float, shift: float) -> str:
        \"\"\"Пометка допуска схемы (Codex 17.08): сдвиг столика вдоль дивана → +table_axis_shifted;
        нестандартный зазор → +gapNN. Канон (COFFEE_GAP, без сдвига) — без пометки; поворот ковра
        деградацией не считается (правило «длинной стороной вдоль дивана»).\"\"\"
        t = ''
        if shift:
            t += '+table_axis_shifted'
        if abs(gap - COFFEE_GAP) > 0.5:
            t += f'+gap{int(round(gap))}'
        return t
    # ЭФФЕКТИВНАЯ группа (11.08)""")
assert "_enum_degraded: set = set()" in s
open(p,'w').write(s); print('template ok')

# --- zones.py: template_degradation + main_path в ключах v1/v2; сертификат
p=ROOT+'planner/zones.py'; s=open(p).read()
helper='''

def template_degradation(ps) -> tuple:
    """Codex 17.08 (владелец №31 set16-base): степень отхода посадочного шаблона от канона —
    (max_level, count). 0 — канон (столик по центру, номинальный зазор); 1 — допустимый fallback
    (комфортный неноминальный зазор 36); 2 — сдвиг столика вдоль дивана / крайний зазор 32|48.
    Читает пометки tpl_variant (`+table_axis_shifted`, `+gapNN`) — ставит template.place_template."""
    lvl, cnt = 0, 0
    for p in ps:
        v = getattr(p, 'tpl_variant', '') or ''
        if getattr(p, 'tpl_id', '') != 'seating' or not v:
            continue
        l = 0
        if '+table_axis_shifted' in v:
            l = 2
        m = re.search(r'\\+gap(\\d+)', v)
        if m:
            g = int(m.group(1))
            l = max(l, 2 if g in (32, 48) else 1)
        if l:
            lvl = max(lvl, l)
            cnt += 1
    return (lvl, cnt)


def _main_path_violations(lay) -> int:
    """MAIN_PATH_TIGHT — soft в validate; как ярус ключа ВЫШЕ деградации шаблона: канон не должен
    побеждать вариант, реально сохраняющий проход 90 см (Codex 17.08)."""
    return sum(1 for v in getattr(lay, 'violations', []) or [] if getattr(v, 'code', '') == 'MAIN_PATH_TIGHT')


def plan_key(room: Room, lay, needs: dict, seat_rank: int = 0) -> tuple:'''
assert s.count("def plan_key(room: Room, lay, needs: dict, seat_rank: int = 0) -> tuple:")==1
s=s.replace("\n\ndef plan_key(room: Room, lay, needs: dict, seat_rank: int = 0) -> tuple:", helper,1)
if not re.search(r'^import re$', s, re.M):
    s=s.replace("from __future__ import annotations\n","from __future__ import annotations\n\nimport re\n",1)
a="""    axis_cls = _axis_class(lay)
    return (hard, missing_req, -covered_pref, -seat_rank, axis_cls) + tuple(lk[1:])"""
b="""    axis_cls = _axis_class(lay)
    # Codex 17.08 (владелец №31): main-path контракт → деградация шаблона (канон важнее допуска)
    # — ВЫШЕ мягких термов (circulation +1 не должен двигать столик с центра дивана)
    return (hard, missing_req, -covered_pref, -seat_rank, axis_cls,
            _main_path_violations(lay), template_degradation(ps)) + tuple(lk[1:])"""
assert a in s; s=s.replace(a,b,1)
a="""            -int(seat.get('flex_seats', 0)), -int(seat.get('footrest', 0) > 0),
            _axis_class(lay)) + tuple(lk[1:])"""
b="""            -int(seat.get('flex_seats', 0)), -int(seat.get('footrest', 0) > 0),
            _axis_class(lay), _main_path_violations(lay), template_degradation(ps)) + tuple(lk[1:])"""
assert a in s; s=s.replace(a,b,1)
open(p,'w').write(s); print('zones ok')

# --- templates.json: id axis_shifted → table_axis_shifted (алиас в статусе)
p=ROOT+'rules/templates.json'; t=json.load(open(p),object_pairs_hook=collections.OrderedDict)
def walk(o):
    if isinstance(o,dict):
        if o.get('id')=='axis_shifted':
            o['id']='table_axis_shifted'; o['status']=str(o.get('status','')).replace('+axis_shifted','+table_axis_shifted')
            o['_renamed_why']='Codex 17.08: сдвигается столик, не ось посадки; ярус template_degradation в plan_key: канон важнее допуска при равных верхних ярусах (владелец №31 set16-base)'
        for v in o.values(): walk(v)
    elif isinstance(o,list):
        for v in o: walk(v)
walk(t); json.dump(t,open(p,'w'),ensure_ascii=False,indent=1); print('templates.json ok')
