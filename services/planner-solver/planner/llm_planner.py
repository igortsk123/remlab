"""LLM-планировщик: модель играет дизайнера, геометрия остаётся проверяющим.

Почему так (план llm-layout-planner, 2026-08-03): правила из открытых источников дают ЧИСЛА
(дистанции, клиренсы, проценты), но не ПРОЦЕДУРУ — какой схемой заполнять конкретную комнату.
Свободный поиск с запретами проходил все проверки и всё равно давал глупые раскладки
(диван перед дверью, пуф в стороне, комод боком). Модель видела миллионы интерьеров и выбирает
схему сама; наш код после неё притягивает к стенам, проверяет и чинит.

Порядок: LLM → снап (стены/сетка/осевые повороты) → hard-проверки → локальное уточнение.
Если ответа нет или он не чинится — вызывающий код падает на beam-движок.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from .clearances import band_scale, distances, rules
from .geometry import footprint
from .models import Item, Layout, Placement, Room, Severity
from .refine import refine
from .validate import WALL_ONLY_ROLES, validate

MODEL = os.environ.get('LAYOUT_LLM_MODEL', 'gpt-5-mini')
ENV_PATH = os.environ.get('OPENAI_ENV', '/home/pakar/igor/v0-health-card/backend/.env')
WALL_GAP_CM = 5.0


def _api_key() -> str | None:
    key = os.environ.get('OPENAI_API_KEY')
    if key:
        return key
    try:
        for line in open(ENV_PATH):
            m = re.match(r'OPENAI_API_KEY=(.+)', line.strip())
            if m:
                return m.group(1).strip().strip('"')
    except OSError:
        pass
    return None


def _room_brief(room: Room) -> str:
    parts = [f"Room is a rectangle {room.width_cm:.0f} cm wide (x axis) and {room.depth_cm:.0f} cm "
             f"deep (y axis). Origin (0,0) is the south-west corner; x grows east, y grows north."]
    for op in room.openings:
        parts.append(f"{op.kind} on the {op.wall} wall, from {op.offset_cm:.0f} to "
                     f"{op.offset_cm + op.width_cm:.0f} cm along that wall"
                     + (f", opens {op.swing_cm:.0f} cm into the room" if op.swing_cm else ""))
    for rad in room.radiators:
        parts.append(f"radiator on the {rad.wall} wall, {rad.offset_cm:.0f}–"
                     f"{rad.offset_cm + rad.width_cm:.0f} cm")
    return "; ".join(parts) + "."


def _num(v, default: float) -> float:
    """Числа в своде бывают диапазонами [lo, hi] — берём нижнюю границу."""
    if isinstance(v, list) and v:
        return float(v[0])
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _rules_brief(room: Room) -> str:
    d = distances()
    tv = band_scale("sofa_tv_cm", room.band, d.get("sofa_tv_cm", [180, 300]))
    tbl = band_scale("sofa_table_cm", room.band, d.get("sofa_coffee_table", [36, 50]))
    return (f"sofa-to-TV {tv[0]:.0f}–{tv[1]:.0f} cm (up to 400 acceptable if the sofa then stands "
            f"against a wall); sofa-to-coffee-table {tbl[0]:.0f}–{tbl[1]:.0f} cm; "
            f"walkways at least {_num(d.get('passage_secondary_min'), 60):.0f} cm; "
            f"{_num(d.get('door_to_furniture'), 150):.0f} cm clear in front of the door; "
            f"drawers/doors need {_num(d.get('dresser_front'), 76):.0f} cm to open.")


def build_prompt(room: Room, items: list[Item]) -> str:
    lines = [f"- {it.role}: {it.w_cm:.0f} cm wide x {it.d_cm:.0f} cm deep"
             + (f", {it.h_cm:.0f} cm tall" if it.h_cm else "")
             + (" (L-shaped corner sofa)" if it.corner else "")
             for it in items]
    return (
        "You are an experienced interior designer laying out a Russian city-flat living room.\n"
        f"{_room_brief(room)}\n"
        f"Room area {room.area_m2:.0f} sq m.\n\n"
        "Furniture to place (footprint sizes):\n" + "\n".join(lines) + "\n\n"
        "First choose the layout SCHEME that a designer would use for this room shape, door and "
        "window position (for example: sofa along the long wall facing the TV on the opposite wall; "
        "L-sofa in the corner; seating by the window with the TV on a blank wall). Then place every "
        "piece.\n\n"
        "Hard habits of a good layout: storage and TV stand stand with their BACKS against walls; "
        "the sofa faces the TV and is not placed on the wall with the entrance door; the coffee "
        "table sits in front of the sofa on its axis; a pouf or armchair belongs to the same "
        "seating group, not somewhere else; nothing stands diagonally — rotations are 0, 90, 180 "
        "or 270 degrees only; the entrance stays clear.\n"
        f"Project distances to respect: {_rules_brief(room)}\n\n"
        "Rotation convention: 0 = the piece faces north (+y), 90 = faces east (+x), 180 = faces "
        "south (-y), 270 = faces west (-x). A sofa against the north wall faces south (180).\n"
        "Coordinates are the CENTRE of each piece in cm.\n\n"
        'Answer with strict JSON only: {"scheme": "one sentence why this scheme fits", '
        '"placements": [{"role": "...", "x": 0, "y": 0, "rot": 0}]}. '
        "Place every item from the list; if one truly does not fit, omit it and say so in scheme."
    )


def ask_llm(room: Room, items: list[Item], *, timeout: int = 120) -> dict | None:
    key = _api_key()
    if not key:
        return None
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": build_prompt(room, items)}],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read())
        txt = out["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", txt, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:                      # сеть/лимиты/битый JSON — молча на фолбэк
        print(f"LLM-планировщик недоступен: {str(e)[:120]}", flush=True)
        return None


def _snap(room: Room, p: Placement) -> Placement:
    """Притяжка: осевой поворот, корпус — спинкой к ближней стене, всё — внутрь комнаты."""
    rot = int(round((p.rot % 360) / 90)) % 4 * 90
    it = p.item
    w, d = (it.d_cm, it.w_cm) if rot in (90, 270) else (it.w_cm, it.d_cm)
    x = min(max(p.x, WALL_GAP_CM + w / 2), room.width_cm - WALL_GAP_CM - w / 2)
    y = min(max(p.y, WALL_GAP_CM + d / 2), room.depth_cm - WALL_GAP_CM - d / 2)
    if p.role in WALL_ONLY_ROLES:
        # к ближайшей стене — спинкой (лицо смотрит в комнату)
        gaps = {0: y - d / 2, 180: room.depth_cm - (y + d / 2),
                90: x - w / 2, 270: room.width_cm - (x + w / 2)}
        rot = min(gaps, key=gaps.get)
        w, d = (it.d_cm, it.w_cm) if rot in (90, 270) else (it.w_cm, it.d_cm)
        if rot == 0:
            y = WALL_GAP_CM + d / 2
        elif rot == 180:
            y = room.depth_cm - WALL_GAP_CM - d / 2
        elif rot == 90:
            x = WALL_GAP_CM + w / 2
        else:
            x = room.width_cm - WALL_GAP_CM - w / 2
        x = min(max(x, WALL_GAP_CM + w / 2), room.width_cm - WALL_GAP_CM - w / 2)
        y = min(max(y, WALL_GAP_CM + d / 2), room.depth_cm - WALL_GAP_CM - d / 2)
    return Placement(role=p.role, x=round(x, 1), y=round(y, 1), rot=rot, item=it)


def plan(room: Room, items: list[Item]) -> tuple[Layout | None, str]:
    """Раскладка от LLM, притянутая и проверенная. Возвращает (layout|None, комментарий схемы)."""
    ans = ask_llm(room, items)
    if not ans or not isinstance(ans.get("placements"), list):
        return None, ""
    by_role = {it.role: it for it in items}
    placements: list[Placement] = []
    for rec in ans["placements"]:
        it = by_role.get(str(rec.get("role", "")).strip())
        if it is None or rec.get("x") is None or rec.get("y") is None:
            continue
        try:
            p = Placement(role=it.role, x=float(rec["x"]), y=float(rec["y"]),
                          rot=float(rec.get("rot", 0)), item=it)
        except Exception:
            continue
        placements.append(_snap(room, p))
    if not placements:
        return None, str(ans.get("scheme", ""))
    layout = refine(room, validate(room, placements))
    layout.unplaced = [it.role for it in items
                       if it.role not in {p.role for p in layout.placements}]
    return layout, str(ans.get("scheme", ""))[:300]


def hard_count(layout: Layout) -> int:
    return sum(1 for v in layout.violations if v.severity is Severity.HARD)
