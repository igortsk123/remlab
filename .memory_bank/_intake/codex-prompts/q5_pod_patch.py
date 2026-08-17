# Q5 pod (Codex): quiet_chat = пара + ОБЯЗАТЕЛЬНАЯ поверхность, 30–45° к центру; fireplace_flank; порядок; не ставить при богатой primary
import json
TP='services/planner-solver/rules/templates.json'; t=json.load(open(TP))
q=t['zones']['quiet']
q['required']=['кресло 3','кресло 4']
q['required_any']=['приставной','столик 2','столик']
q['schemes']=[
 {"id":"quiet_chat","status":"implemented_as: template.build_quiet(variant=quiet_chat)","order":2,
  "why":"пара кресел + малая поверхность между/рядом, кресла повёрнуты 30–45° к общему центру (не 0/180 «интервью»); AD reading-nook: лампа и маленький приставной стол; владелец №181: пара визави без стола — «что это и зачем»"},
 {"id":"fireplace_flank","status":"implemented_as: template.build_quiet(variant=fireplace_flank)","order":1,
  "why":"пара кресел по сторонам камина в вилке дистанции (fireplace.rules.safety_zone/chair_angle 45°), ≤45° к камину — только тогда facing_target=fireplace (H&G furniture-around-a-fireplace); владелец №183: «2 кресла к камину» за 5 м — не камин"}]
q['skip_when']={"primary_rich":"≥2 кресла в главной группе или два дивана","existing_pod":["reading","bay_armchair"],"no_surface_and_no_fireplace":True,
  "_why":"Q5 (Codex): второй pod ставится только осмысленным; fill% — диагностика, не причина"}
json.dump(t,open(TP,'w'),ensure_ascii=False,indent=1); print('passport ok')

T='services/planner-solver/planner/template.py'; s=open(T).read()
a='''def build_quiet(by_role: dict[str, Item]) -> Block | None:
    """B2 (v2, веб-свод «watch zone + quiet zone»): вторая подзона просторных
    гостиных — пара кресел визави + приставной между ними; ставится у камина
    или свободного угла ПОСЛЕ главной зоны."""
    a1 = by_role.get('кресло 3')
    a2 = by_role.get('кресло 4')
    if not (a1 and a2):
        return None
    b = Block(a1)
    side = by_role.get('приставной') or by_role.get('столик')
    gap = (side.d_cm if side else 60.0)
    b.add(a2, 0.0, a1.d_cm / 2 + gap + 40 + a2.d_cm / 2, 180.0)
    if side is not None:
        b.add(side, 0.0, a1.d_cm / 2 + (gap + 40) / 2, 0.0)
    return _valid(b, 'quiet')'''
b='''def build_quiet(by_role: dict[str, Item], variant: str = 'quiet_chat',
                fireplace: Item | None = None) -> Block | None:
    """Второй pod (Q5 свода №13, Codex по замечаниям владельца №181/№183):
    quiet_chat — пара кресел 3/4 + ОБЯЗАТЕЛЬНАЯ малая поверхность (приставной|столик 2|столик)
    между ними, кресла повёрнуты 30–45° к общему центру (не «интервью» 0/180);
    fireplace_flank — пара по сторонам камина под 45° к очагу (fireplace.rules), камин — часть блока.
    Без поверхности и без камина — блока НЕТ (пара визави «ни о чём» — владелец)."""
    a1 = by_role.get('кресло 3')
    a2 = by_role.get('кресло 4')
    if not (a1 and a2):
        return None
    if variant == 'fireplace_flank' and fireplace is not None:
        b = Block(fireplace)
        _rules = (_zone_rules_tpl().get('zones', {}).get('fireplace', {}).get('rules') or {})
        _ang = float(_rules.get('chair_angle_deg', 45))
        _off = fireplace.w_cm / 2 + 45 + a1.w_cm / 2
        _fwd = float((_rules.get('safety_zone_cm') or [61, 91])[0]) + a1.d_cm / 2 + 20
        b.add(a1, -_off, _fwd, 180.0 - _ang)      # слева, к очагу под углом
        b.add(a2, +_off, _fwd, 180.0 + _ang)      # справа, зеркально
        side = by_role.get('приставной') or by_role.get('столик 2')
        if side is not None:
            b.add(side, 0.0, _fwd + a1.d_cm / 2 + 20 + side.d_cm / 2, 0.0)
        return _valid(b, 'quiet')
    side = by_role.get('приставной') or by_role.get('столик 2') or by_role.get('столик')
    if side is None:
        return None                               # quiet_chat без поверхности не собирается
    b = Block(a1)
    gap = side.d_cm + 40
    cy = a1.d_cm / 2 + gap / 2                    # общий центр между креслами
    # кресла под 35° к центру (внутрь), не строго визави
    b.rel[0] = (a1, 0.0, 0.0, 35.0)
    b.add(a2, 0.0, a1.d_cm / 2 + gap + a2.d_cm / 2, 180.0 + 35.0)
    b.add(side, 0.0, cy, 0.0)
    return _valid(b, 'quiet')


def _zone_rules_tpl():
    from .invariants import TEMPLATES as _T
    return _T'''
assert a in s; s=s.replace(a,b,1)
a2='''    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    b = build_quiet(by_role)
    if b is None:
        return None
    _cands = list(wall_candidates(room, b.anchor, free)) \\
        + list(middle_candidates(room, b.anchor, free, limit=8))
    return _best_block(room, b, free, _cands, tv=None, fixed=fixed)'''
b2='''    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    # Q5 (Codex): pod не ставится при богатой primary (≥2 кресла в главной группе или два
    # дивана) и при уже существующем reading/bay pod — вторая зона должна быть осмысленной
    _fx = list(fixed or [])
    _main_arm = sum(1 for p in _fx if p.role.split(' ')[0] == 'кресло' and getattr(p, 'tpl_id', '') == 'seating')
    _sofas = sum(1 for p in _fx if p.role.split(' ')[0] == 'диван')
    if _main_arm >= 2 or _sofas >= 2:
        return None
    if any(getattr(p, 'tpl_id', '') in ('reading', 'bay_armchair') for p in _fx):
        return None
    # порядок: fireplace_flank (камин уже стоит и достижим) → quiet_chat у окна/в углу
    _fp = next((p for p in _fx if p.role.split(' ')[0] == 'камин'), None)
    outs = []
    if _fp is not None and _fp.item is not None:
        bf = build_quiet(by_role, variant='fireplace_flank', fireplace=_fp.item)
        if bf is not None:
            # блок якорится на камине: единственный кандидат — фактическая поза камина
            from .candidates import Candidate as _CQ
            _cq = _CQ(placement=Placement(role=_fp.role, x=_fp.x, y=_fp.y, rot=_fp.rot, item=_fp.item),
                      kind='anchor', note='fireplace_flank')
            _fx_wo = [p for p in _fx if p is not _fp]
            ps = _best_block(room, bf, free.union(footprint(_fp)), [_cq], tv=None, fixed=_fx_wo)
            if ps:
                for q in ps:
                    q.tpl_variant = 'fireplace_flank'
                return [q for q in ps if q.role != _fp.role]   # камин уже стоит — не дублируем
    b = build_quiet(by_role, variant='quiet_chat')
    if b is None:
        return None
    _cands = list(wall_candidates(room, b.anchor, free)) \\
        + list(middle_candidates(room, b.anchor, free, limit=8))
    ps = _best_block(room, b, free, _cands, tv=None, fixed=fixed)
    if ps:
        for q in ps:
            q.tpl_variant = 'quiet_chat'
    return ps'''
assert a2 in s; s=s.replace(a2,b2,1)
open(T,'w').write(s); print('template quiet ok')
