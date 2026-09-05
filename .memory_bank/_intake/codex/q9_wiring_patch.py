"""Q9 (тень): проводка модели возможностей в трейс и артефакт. Применять ПОСЛЕ экзамена."""
p='/home/pakar/igor/remlab/services/planner-solver/planner/zones.py'; s=open(p).read()
a="""    _v2 = []
    for c in cands:"""
b="""    # Q9 (тень, Codex 18.08): ключ ПРИОРОВ ПРАКТИКИ по каждой гипотезе — только измерение,
    # production-выбор не трогаем до слепых пар (включение = отдельное решение владельца)
    _pp = []
    for c in cands:
        try:
            from .opportunities import practice_prior_key as _ppk
            _pp.append(_ppk(room, list(c[2][0].placements)) if c[2] else None)
        except Exception:
            _pp.append(None)
    _v2 = []
    for c in cands:"""
assert a in s; s=s.replace(a,b,1)
a="""             'v2_would_choose': (cands[sorted(range(len(cands)), key=lambda i: (_v2[i], i))[0]][0]
                                 if cands and all(v is not None for v in _v2) else None),"""
b="""             'v2_would_choose': (cands[sorted(range(len(cands)), key=lambda i: (_v2[i], i))[0]][0]
                                 if cands and all(v is not None for v in _v2) else None),
             'practice_prior_shadow': [list(x) if x is not None else None for x in _pp],
             'prior_would_choose': (cands[sorted(range(len(cands)), key=lambda i: (_pp[i], i))[0]][0]
                                    if cands and all(x is not None for x in _pp) else None),"""
assert a in s; s=s.replace(a,b,1)
open(p,'w').write(s); print('zones ok')

p='/home/pakar/igor/remlab/tools/scout/solver_run.py'; s=open(p).read()
a="""out['_view']="""
b="""# Q9 (тень): выбранные исходы по возможностям (окно/центр/угол/главная стена) — для отчёта
# «практика vs движок»; на выбор плана не влияет до включения после слепых пар
try:
    from planner.opportunities import opportunities as _opps, practice_prior_key as _ppk
    _ps_final=[_P4(role=r, x=v[0][0], y=v[0][1], rot=v[1], item=_I4(role=r, w_cm=_dims4.get(r,(60,60))[0] or 60,
                                                                    d_cm=_dims4.get(r,(60,60))[1] or 60))
               for r, v in placed.items() if r in _dims4]
    out['_opportunities']={'items': _opps(_r4, _ps_final), 'prior_key': list(_ppk(_r4, _ps_final))}
except Exception as _e:
    out['_opportunities']={'error': str(_e)[:120]}
out['_view']="""
assert a in s; s=s.replace(a,b,1)
open(p,'w').write(s); print('solver_run ok')
