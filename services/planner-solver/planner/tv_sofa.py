"""П1 МАСТЕРА tv-sofa-pair: генератор ПАР «позиция медиа-блока × позиция блока посадки».

Свод владельца 13.08 (§3–7): алгоритм не делает «ТВ → потом где-нибудь диван» —
он ищет сразу ПАРУ. Стены ранжируются WallScore; длина стены — только tie-breaker.

Всё в терминах ШАБЛОНОВ: пара = (якорь медиа-БЛОКА, якорь БЛОКА посадки). Составы
блоков — из паспортов (лестница ступеней), внутрь блоков генератор не заглядывает.
Числа — `rules/templates.json → tv_sofa_pair` (WallScore, углы, цель дистанции).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .invariants import TEMPLATES
from .models import Item, Room
from .room_map import RoomMap, WallSegment

_CFG = TEMPLATES.get('tv_sofa_pair', {})
_WS = _CFG.get('wall_score', {})
_ANGLE = _CFG.get('view_angle_deg', {'perfect': 15, 'ok': 30})

WALL_ROT = {'south': 0.0, 'north': 180.0, 'west': 90.0, 'east': 270.0}
# rot дивана, СМОТРЯЩЕГО на данную стену
SOFA_ROT_FACING = {'south': 180.0, 'north': 0.0, 'west': 270.0, 'east': 90.0}


@dataclass
class Pair:
    media_wall: str
    media_x: float
    media_y: float
    media_rot: float
    sofa_x: float
    sofa_y: float
    sofa_rot: float
    sofa_scheme: str            # 'opposite_wall' | 'floating_pair' | 'window_back'
    score: float
    dist_cm: float
    angle_deg: float


def _tv_target_cm(media: Item) -> float:
    """Целевая дистанция — КАНОН planner/tv.py (C-2 свода №11, Кодекс §Q-C:
    прежняя аппроксимация diag=max(w-20,80)·1.6 для стенки 300 давала ~448 см
    против канонических ~229 — почти двукратная ошибка цели пар)."""
    from .geometry import base_role
    from .tv import distance_target
    return distance_target(media.w_cm, bearer=base_role(media.role))


def _media_positions(rmap: RoomMap, media: Item):
    """Позиции якоря медиа-блока по участкам стен: центр участка. Запас краёв —
    по режиму: small +20 (по 10 на сторону, свод №3 §3), иначе +40 (large-свод)."""
    margin = 20.0 if rmap.mode == 'small' else 40.0
    for wall, info in rmap.walls.items():
        for seg in info.segments:
            if seg.length_cm < media.w_cm + margin:
                continue
            mid = (seg.start_cm + seg.end_cm) / 2
            yield wall, seg, mid


def _to_xy(room: Room, wall: str, along: float, depth_off: float) -> tuple[float, float]:
    if wall == 'south':
        return along, depth_off
    if wall == 'north':
        return along, room.depth_cm - depth_off
    if wall == 'west':
        return depth_off, along
    return room.width_cm - depth_off, along


def _pair_metrics(room: Room, wall: str, mx: float, my: float,
                  sx: float, sy: float, sofa_rot: float) -> tuple[float, float]:
    """(дистанция по прямой, угол между осью взгляда дивана и направлением на медиа)."""
    dx, dy = mx - sx, my - sy
    dist = math.hypot(dx, dy)
    r = math.radians(sofa_rot)
    fx, fy = math.sin(r), math.cos(r)
    cosang = (fx * dx + fy * dy) / (dist or 1.0)
    ang = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
    return dist, ang


def _route_cuts_pair(rmap: RoomMap, mx, my, sx, sy) -> bool:
    """Основной маршрут пересекает отрезок диван→медиа (свод §7: поток вокруг
    seating group, не сквозь)."""
    from shapely.geometry import LineString
    axis = LineString([(sx, sy), (mx, my)])
    return any(axis.crosses(rt) for rt in rmap.routes)


def generate_pairs(room: Room, rmap: RoomMap, media: Item, sofa: Item,
                   top_k: int = 6) -> list[Pair]:
    """Топ-K пар по WallScore. Позиции дивана на пару медиа-позиции:
    напротив у стены / floating на ТВ-вилке / (спинкой к окну — если стена с окном).
    """
    target = _tv_target_cm(media)
    out: list[Pair] = []
    _small = rmap.mode == 'small'
    _sm = _CFG.get('small_mode', {})
    for wall, seg, mid in _media_positions(rmap, media):
        m_rot = WALL_ROT[wall]
        mx, my = _to_xy(room, wall, mid, media.d_cm / 2)
        opp = rmap.opposite(wall)
        s_rot = SOFA_ROT_FACING[wall]
        # кандидаты дивана: у противоположной стены; floating на целевой дистанции
        sofa_spots: list[tuple[float, float, str]] = []
        far = (room.depth_cm if wall in ('south', 'north') else room.width_cm)
        wall_off = sofa.d_cm / 2 + 5.0
        sofa_spots.append((far - wall_off, 'opposite_wall'))
        sofa_spots.append((media.d_cm + target + sofa.d_cm / 2, 'floating_pair'))
        # E5 (elongated): вариант «кластер стянут к медиа» — дистанция у нижней границы
        # комфорта, пустота уходит за спинку одним куском (там её заберёт вторая зона
        # или штраф E4 отбракует позицию)
        if rmap.shape in ('elongated', 'strongly'):
            sofa_spots.append((media.d_cm + max(target * 0.82, 150.0) + sofa.d_cm / 2,
                               'floating_pair'))
        _pen = _CFG.get('wall_sofa_penalty', {})
        for depth_off, scheme in sofa_spots:
            if depth_off >= far - 10:
                continue
            sx, sy = _to_xy(room, wall, mid, depth_off)
            # Г-ДИВАН: носитель ставим на ОСЬ ГЛАВНОЙ СЕКЦИИ, а не на центр bbox (26.08).
            # Пара генерировалась с одним `mid` для дивана и носителя, поэтому у углового
            # экран систематически уезжал на ~section/2 (~47 см) — это и был остаток дефекта
            # «ТВ не по оси дивана»: класс оси отчитывался «centered», метрика качества
            # показывала 47 см. Ось считаем той же функцией, что и весь движок.
            _mx, _my = mx, my
            if getattr(sofa, 'corner', False):
                from .geometry import seat_axis_origin as _sao
                from .models import Placement as _Pl
                _ox, _oy = _sao(_Pl(role='диван', x=sx, y=sy, rot=s_rot, item=sofa))
                if wall in ('south', 'north'):
                    _mx = min(max(_ox, media.w_cm / 2 + 5), room.width_cm - media.w_cm / 2 - 5)
                else:
                    _my = min(max(_oy, media.w_cm / 2 + 5), room.depth_cm - media.w_cm / 2 - 5)
            dist, ang = _pair_metrics(room, wall, _mx, _my, sx, sy, s_rot)
            # C-2 свода №11 (Кодекс §Q-C): цель сравнивается с ФРОНТ-зазором
            # (та же величина, что меряет validate), а не с центр-центр —
            # прежний замер был смещён на полусумму глубин (~60-70 см)
            gap = max(0.0, dist - (sofa.d_cm + media.d_cm) / 2)
            # скоринг WallScore (числа из паспорта)
            score = float(_WS.get('fits_media', 20))
            d_err = abs(gap - target) / max(target, 1.0)
            score += float(_WS.get('distance_near_target', 20)) * max(0.0, 1 - d_err)
            # E4 (elongated, свод №4 §7): floating-диван поперёк длинной оси — граница
            # зоны. Сторона за спинкой обязана иметь функцию или быть circulation;
            # «пусто за границей» — сильный штраф (комод зоной не считается — приоритет
            # второй зоны решает лестница зон, здесь только штраф пустоты).
            if rmap.shape in ('elongated', 'strongly') and scheme == 'floating_pair':
                far_axis = (room.depth_cm if wall in ('south', 'north')
                            else room.width_cm)
                behind = far_axis - depth_off - sofa.d_cm / 2
                # вычесть законную пустоту двери на том конце (подход ~110 см)
                _opp = rmap.opposite(wall)
                _door_pad = 110.0 if rmap.walls[_opp].doors else 0.0
                unused = max(0.0, behind - _door_pad)
                if unused > 130.0:
                    score -= 18.0        # residual без функции — сильный штраф (E5
                                         # стянет кластер или отдаст второй зоне)
            if _small:
                # S2: в small пристенный диван — приоритет №1 (максимум пола),
                # floating без нужды штрафуется (свод №3 §4)
                if scheme == 'floating_pair':
                    score -= 12.0
                score += float(_sm.get('wall_score', {}).get('circulation', 25)) -                     float(_WS.get('route_not_cutting', 15))   # вес циркуляции выше
            # L2 (large-room): пороги 1.2×/1.5×V — только в large-режиме
            if rmap.mode == 'large' and scheme == 'opposite_wall':
                ratio = dist / max(target, 1.0)
                if ratio > float(_pen.get('prefer_floating_ratio', 1.5)):
                    score -= 30.0          # «5 м пустоты» проигрывает всегда
                elif ratio > float(_pen.get('ok_ratio', 1.2)):
                    score -= 10.0          # floating предпочтителен
            if ang <= _ANGLE.get('perfect', 15):
                score += float(_WS.get('sofa_opposite', 15))
            elif ang <= _ANGLE.get('ok', 30):
                score += float(_WS.get('sofa_opposite', 15)) * 0.5
            if not _route_cuts_pair(rmap, _mx, _my, sx, sy):
                score += float(_WS.get('route_not_cutting', 15))
            opp_wins = rmap.walls[opp].windows
            if not seg.has_window_behind and not opp_wins:
                score += float(_WS.get('no_window_conflict', 15))
            elif seg.has_window_behind:
                score += 0.0            # низкий носитель可, но балла нет
            else:
                score += float(_WS.get('no_window_conflict', 15)) * 0.4
            score += float(_WS.get('free_length', 5)) * min(1.0, seg.length_cm / 400.0)
            # E2 (M-E, свод №5): divider по масштабу — floating-граница уже
            # 45% поперечного пролёта не структурирует пространство (мелочь)
            if scheme == 'floating_pair':
                _span = (room.width_cm if wall in ('south', 'north') else room.depth_cm)
                if sofa.w_cm < float(_CFG.get('divider_min_share', 0.45)) * _span:
                    score -= float(_CFG.get('divider_scale_penalty', 10))
            # C4 (M-C, свод №5): колонна/пилон в коридоре «медиа↔диван» — беседа и
            # просмотр через препятствие; пары в обход колонны выигрывают
            if rmap.columns:
                from shapely.geometry import box as _cbox
                _pad = max(media.w_cm, sofa.w_cm) / 2
                _corr = _cbox(min(_mx, sx) - _pad, min(_my, sy) - _pad,
                              max(_mx, sx) + _pad, max(_my, sy) + _pad)
                if any(c.buffer(15.0).intersects(_corr) for c in rmap.columns):
                    score -= float(TEMPLATES.get('contour_features', {})
                                   .get('column_pair_penalty', 12))
            out.append(Pair(media_wall=wall, media_x=_mx, media_y=_my, media_rot=m_rot,
                            sofa_x=sx, sofa_y=sy, sofa_rot=s_rot, sofa_scheme=scheme,
                            score=round(score, 1), dist_cm=round(dist),
                            angle_deg=round(ang)))
    out.sort(key=lambda p: -p.score)
    # C-3 свода №11 (Кодекс §Q-C.5): КВОТА comfort-кандидатов — WallScore не должен
    # вытеснить все комфортные дистанции из top-K (веса — только tie-breaker
    # внутри класса). Комфорт по канону: фронт-зазор ≤ min(soft_hi,hi).
    from .geometry import base_role as _brq
    from .tv import distance_range as _drq
    lo_q, hi_q, soft_q = _drq(media.w_cm, bearer=_brq(media.role))
    cap_q = min(soft_q, hi_q)
    def _gap_of(pr):
        dxq, dyq = pr.media_x - pr.sofa_x, pr.media_y - pr.sofa_y
        return max(0.0, math.hypot(dxq, dyq) - (sofa.d_cm + media.d_cm) / 2)
    comfort = [pr for pr in out if lo_q <= _gap_of(pr) <= cap_q]
    picked = out[:top_k]
    if comfort and not any(lo_q <= _gap_of(pr) <= cap_q for pr in picked):
        picked = picked[:-max(1, top_k // 3)] + comfort[:max(1, top_k // 3)]
    return picked
