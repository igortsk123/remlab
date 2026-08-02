"""SVG-отладка раскладки: комната, проёмы, следы, клиренсы, нарушения.

Артефакт для человека (владелец смотрит планы глазами) и для регресс-диффов.
"""
from __future__ import annotations

from shapely.geometry import Polygon

from .geometry import (
    access_zone,
    footprint,
    free_space,
    opening_polygon,
    radiator_polygon,
    swing_polygon,
)
from .models import Layout

PALETTE = {
    "диван": "#7b7bbe", "тв-тумба": "#9aa0a6", "кресло": "#be9a8c", "столик": "#96785a",
    "пуф": "#c9a227", "торшер": "#d9c67a", "кашпо": "#6ea36e", "шкаф": "#8d6e63",
    "комод": "#a1887f", "стенка": "#795548", "стеллаж": "#8d795e", "витрина": "#90a4ae",
    "камин": "#b0603a", "стол обеденный": "#9e7b53", "стул": "#b3a394", "ковёр": "#cfc4b0",
}


def _path(poly: Polygon, scale: float, pad: float) -> str:
    if poly.is_empty:
        return ""
    geoms = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
    d = []
    for g in geoms:
        for ring in [g.exterior, *g.interiors]:
            pts = " ".join(f"{pad + x * scale:.1f},{pad + y * scale:.1f}" for x, y in ring.coords)
            d.append(f"M {pts} Z")
    return " ".join(d)


def render(layout: Layout, path: str | None = None, *, scale: float = 0.55, show_free: bool = True) -> str:
    room = layout.room
    pad = 24.0
    W = room.width_cm * scale + pad * 2
    H = room.depth_cm * scale + pad * 2 + 18 * (len(layout.violations) + 1)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="system-ui,sans-serif" font-size="11">',
           f'<rect x="0" y="0" width="{W:.0f}" height="{H:.0f}" fill="#faf8f5"/>',
           f'<rect x="{pad}" y="{pad}" width="{room.width_cm * scale:.1f}" '
           f'height="{room.depth_cm * scale:.1f}" fill="#fff" stroke="#333" stroke-width="2"/>']
    if show_free:
        fp = free_space(room, layout.placements)
        out.append(f'<path d="{_path(fp, scale, pad)}" fill="#e8f2e8" stroke="none" opacity="0.75"/>')
    for op in room.openings:
        col = "#3f7fbf" if op.kind == "window" else "#c98b2e"
        out.append(f'<path d="{_path(opening_polygon(room, op).buffer(2), scale, pad)}" fill="{col}"/>')
        sw = swing_polygon(room, op)
        if not sw.is_empty:
            out.append(f'<path d="{_path(sw, scale, pad)}" fill="none" stroke="{col}" '
                       f'stroke-dasharray="4 3"/>')
    for rad in room.radiators:
        out.append(f'<path d="{_path(radiator_polygon(room, rad), scale, pad)}" fill="#d94f4f" opacity="0.5"/>')
    for p in layout.placements:
        az = access_zone(p)
        if not az.is_empty:
            out.append(f'<path d="{_path(az, scale, pad)}" fill="#000" opacity="0.06"/>')
    for p in layout.placements:
        col = PALETTE.get(p.role, "#8a8a8a")
        fp = footprint(p)
        out.append(f'<path d="{_path(fp, scale, pad)}" fill="{col}" fill-opacity="0.75" stroke="#333"/>')
        cx, cy = fp.centroid.x * scale + pad, fp.centroid.y * scale + pad
        out.append(f'<text x="{cx:.0f}" y="{cy:.0f}" text-anchor="middle" fill="#111">{p.role}</text>')
        fx, fy = _facing_marker(p, scale, pad)
        out.append(f'<line x1="{cx:.0f}" y1="{cy:.0f}" x2="{fx:.0f}" y2="{fy:.0f}" '
                   f'stroke="#111" stroke-width="1.5" marker-end="url(#a)"/>')
    y = room.depth_cm * scale + pad + 16
    head = "нарушений нет" if layout.ok else f"HARD-нарушений: {sum(1 for v in layout.violations if v.severity == 'hard')}"
    out.append(f'<text x="{pad}" y="{y:.0f}" fill="#111">{head} · пол занят {layout.floor_used_pct}%</text>')
    for v in layout.violations:
        y += 16
        out.append(f'<text x="{pad}" y="{y:.0f}" fill="#a33">• [{v.code}] {v.message}'
                   + (f" (ожидалось {v.expected})" if v.expected else "") + "</text>")
    out.append('<defs><marker id="a" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">'
               '<path d="M0,0 L6,3 L0,6 Z" fill="#111"/></marker></defs></svg>')
    svg = "\n".join(out)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
    return svg


def _facing_marker(p, scale: float, pad: float) -> tuple[float, float]:
    from .geometry import facing_vector

    fx, fy = facing_vector(p.rot)
    fp = footprint(p)
    c = fp.centroid
    L = 26 / scale
    return (c.x + fx * L) * scale + pad, (c.y + fy * L) * scale + pad
