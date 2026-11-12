"""Q5+ свода №13: КОНТРАКТ ПОЗЫ (rot) для 3D/LLM — pose-hash round-trip и orientation в экспорте.

- rot в артефакте == rot в plan-NNN.json (float, не int; 0° и 180° — разный фронт при одном footprint);
- у каждого направленного предмета в экспорте есть orientation (yaw, фронт-вектор, intent, relation);
- facing_target пересчитывается из координат: угловая ошибка соответствует relation
  (faces ≤15°, angled_toward ≤45°), дистанция ≤250 см.

ВЫГРУЗКА — ТОЙ ЖЕ НОЧИ, ЧТО И АРТЕФАКТЫ (T-20261112-94). До 12.11 `~/scout-scenes/plans-export` никто не пересобирал
(последняя — 26.08), и тест сверял артефакты свежего экзамена с выгрузкой другого банка: «pose mismatch set1-base» —
другой диван (Евро 195×80 → Викс 198×90, банк пересобран по ADR-0131/0136), а не сломанный контракт. Теперь: ночная
выгрузка свежее отчёта экзамена — берём её (её пишет `nightly_exam.sh`); иначе тест сам собирает выгрузку из текущих
артефактов во временную папку (`export_plans_ai.py`, env `PLANS_EXPORT_OUT`) — проверяется код выгрузки, а не дата.
Данные экзамена — `tools/scout` этой копии или env `EXAM_SCOUT_DIR` (прогон из worktree по данным основной копии).
"""
import glob
import json
import math
import os
import subprocess
import sys
import tempfile

CODE_SCOUT = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout')
SCOUT = os.environ.get('EXAM_SCOUT_DIR') or CODE_SCOUT
NIGHTLY_EXPORT = os.path.expanduser(os.environ.get('PLANS_EXPORT_DIR') or '~/scout-scenes/plans-export')
GALLERY = os.path.expanduser(os.environ.get('ACC_GALLERY_DIR') or '~/scout-scenes/acc-gallery')
REPORT = os.path.join(SCOUT, 'acceptance-report-zoned.jsonl')
DIRECTIONAL = ('диван', 'кресло', 'тв-тумба', 'стенка', 'камин', 'стул')
_CACHE = {}


def _export_dir():
    """Выгрузка, согласованная с отчётом экзамена; None — сверять не с чем (скип с причиной в `_CACHE['why']`)."""
    if 'dir' in _CACHE:
        return _CACHE['dir']
    _CACHE['dir'], _CACHE['why'] = None, ''
    # контракт позы сверяет артефакты ПОЛНОГО прогона с экспортом; нет отчёта приёмки —
    # значит прогон не делался или прерван, артефакты и экспорт из разных состояний,
    # и тест обязан скипаться, а не падать (19.08)
    if not os.path.exists(REPORT):
        _CACHE['why'] = 'нет отчёта экзамена acceptance-report-zoned.jsonl'
        return None
    rep_t = os.path.getmtime(REPORT)
    idx = os.path.join(NIGHTLY_EXPORT, 'index.json')
    if os.path.exists(idx) and os.path.getmtime(idx) >= rep_t:
        _CACHE['dir'] = NIGHTLY_EXPORT
        return NIGHTLY_EXPORT
    # ночной выгрузки этого экзамена нет — собрать свою; галерея (вход выгрузки) должна быть этого же экзамена
    probe = glob.glob(os.path.join(GALLERY, '*.json'))
    if not probe or max(map(os.path.getmtime, probe)) < rep_t - 600:
        _CACHE['why'] = f'галерея {GALLERY} старше отчёта экзамена — выгрузку собрать не из чего (не поломка позы)'
        return None
    out = os.path.join(tempfile.mkdtemp(prefix='pose-export-'), 'plans-export')
    env = dict(os.environ, PLANS_EXPORT_OUT=out, ACC_GALLERY_DIR=GALLERY, EXAM_SCOUT_DIR=SCOUT)
    r = subprocess.run([sys.executable, os.path.join(CODE_SCOUT, 'export_plans_ai.py')], cwd=CODE_SCOUT, env=env,
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, f'export_plans_ai.py упал: {r.stderr[-800:]}'
    _CACHE['dir'] = out
    return out


def _pairs(limit=60):
    export = _export_dir()
    if not export:
        return []
    idx_p = os.path.join(export, 'index.json')
    idx = json.load(open(idx_p, encoding='utf-8'))['plans']
    out = []
    for it in idx[:limit]:
        n = int(it['scene'].split('-')[0][3:])
        art_p = os.path.join(SCOUT, f"v3set{n}-layout-acc-zoned-{it['scene']}.json")
        exp_p = os.path.join(export, f"plan-{it['plan']:03d}.json")
        if os.path.exists(art_p) and os.path.exists(exp_p):
            out.append((json.load(open(art_p, encoding='utf-8')), json.load(open(exp_p, encoding='utf-8'))))
    return out


def test_pose_hash_round_trip():
    pairs = _pairs()
    if not pairs:
        import pytest
        pytest.skip(_CACHE.get('why') or 'нет экспорта plans-export')
    bad = []
    for art, exp in pairs:
        for role, v in exp['placements'].items():
            a = art.get(role)
            if not isinstance(a, dict) or 'x' not in a:
                continue
            if abs(float(a.get('rot', 0)) % 360 - float(v.get('rot', 0)) % 360) > 0.01 \
                    or abs(float(a['x']) - float(v['x'])) > 0.01:
                bad.append((exp['scene'], role))
    assert not bad, f'pose mismatch артефакт↔экспорт: {bad[:5]}'


def test_orientation_present_and_consistent():
    pairs = _pairs()
    if not pairs:
        import pytest
        pytest.skip(_CACHE.get('why') or 'нет экспорта plans-export')
    missing, incons = [], []
    for _, exp in pairs:
        pl = exp['placements']
        for role, v in pl.items():
            if role.split(' ')[0] not in DIRECTIONAL:
                continue
            o = v.get('orientation')
            if not o:
                missing.append((exp['scene'], role))
                continue
            rot = float(v.get('rot', 0)) % 360
            if abs(o['yaw_deg'] - rot) > 0.01:
                incons.append((exp['scene'], role, 'yaw'))
            ft = o.get('facing_target')
            if ft:
                cx, cz = float(v['x']), float(v.get('z', v.get('y', 0)))
                dx, dz = ft['point_cm']['x'] - cx, ft['point_cm']['z'] - cz
                bearing = math.degrees(math.atan2(dx, dz)) % 360
                err = abs((bearing - rot + 180) % 360 - 180)
                if abs(err - ft['angular_error_deg']) > 0.6 or ft['distance_cm'] > 250.5:
                    incons.append((exp['scene'], role, 'target'))
                if (o['relation'] == 'faces' and err > 15.5) or (o['relation'] == 'angled_toward' and err > 45.5):
                    incons.append((exp['scene'], role, 'relation'))
    assert not missing, f'нет orientation: {missing[:5]}'
    assert not incons, f'orientation несогласована: {incons[:5]}'
