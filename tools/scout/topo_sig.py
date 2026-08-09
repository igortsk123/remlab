"""L4 (MASTER-layout-v5): топология-сигнатура раскладки — семантическая схема вместо координат.

Считается из экспортного артефакта раскладки (роль → {x,z,rot,w,d} + _room). Используется
solver_run (строка TOPO + поле _topo в артефакте) и topology_report.py (пост-хок разнообразие).
Сигнатура отвечает на вопрос V5 §21: широк ли поиск СЕМАНТИЧЕСКИ (много кандидатов ≠ много
топологий).
"""

# спинка предмета — сторона, противоположная взгляду: rot 0 = лицом на север → спинка Юг
_BACK_WALL = {0: 'S', 90: 'W', 180: 'N', 270: 'E'}


def _back_gap(o: dict, rw: float, rd: float) -> float:
    """Зазор спинки предмета до «его» стены, см."""
    r = int(o['rot']) % 360
    half = o['d'] / 2      # глубина всегда вдоль оси взгляда
    if r == 0:
        return o['z'] - half
    if r == 180:
        return rd - (o['z'] + half)
    if r == 90:
        return o['x'] - half
    return rw - (o['x'] + half)


def topo_signature(out: dict) -> dict:
    room = out.get('_room') or {}
    rw = float(room.get('w') or max((v['x'] for k, v in out.items()
                                     if not k.startswith('_')), default=0))
    rd = float(room.get('d') or max((v['z'] for k, v in out.items()
                                     if not k.startswith('_')), default=0))
    sig = {}
    bearer = out.get('тв-тумба') or out.get('стенка')
    sig['tv_wall'] = _BACK_WALL.get(int(bearer['rot']) % 360) if bearer else None
    sofa = out.get('диван')
    if sofa:
        sig['sofa_wall'] = _BACK_WALL.get(int(sofa['rot']) % 360)
        if 'corner_left' in sofa:
            sig['sofa_mode'] = 'corner'
        else:
            sig['sofa_mode'] = 'wall' if _back_gap(sofa, rw, rd) <= 25 else 'floating'
    else:
        sig['sofa_wall'] = sig['sofa_mode'] = None
    arms = [k for k in out if k.split(' ')[0] == 'кресло']
    sig['armchairs'] = len(arms)
    dining = out.get('стол обеденный')
    if dining:
        dx, dz = dining['x'] - rw / 2, dining['z'] - rd / 2
        sig['dining'] = ('E' if dx > 0 else 'W') if abs(dx) >= abs(dz) else ('N' if dz > 0 else 'S')
    else:
        sig['dining'] = None
    sig['rug'] = 'ковёр' in out
    return sig


def topo_key(sig: dict) -> str:
    return (f"tv={sig['tv_wall']} sofa={sig['sofa_mode']}@{sig['sofa_wall']} "
            f"arm={sig['armchairs']} din={sig['dining']} rug={int(bool(sig['rug']))}")
