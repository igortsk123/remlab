"""PNG-превью раскладки (top-down) — чтобы план можно было посмотреть глазами, а не читать JSON.

SVG (`planner.svg`) — для веба и диффов; PNG — для чата/отчётов и самопроверки движка.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .geometry import access_zone, facing_vector, footprint, free_space, opening_polygon, radiator_polygon, swing_polygon
from .models import Layout
from .svg import PALETTE


def render_png(layout: Layout, path: str, *, scale: float = 0.8, pad: int = 30,
               title: str | None = None) -> str:
    room = layout.room
    W = int(room.width_cm * scale) + pad * 2
    H = int(room.depth_cm * scale) + pad * 2 + 20 * (len(layout.violations) + 2)
    im = Image.new("RGB", (W, H), (250, 248, 245))
    dr = ImageDraw.Draw(im, "RGBA")

    def pts(poly):
        if poly.is_empty:
            return []
        geoms = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
        return [[(pad + x * scale, pad + y * scale) for x, y in g.exterior.coords] for g in geoms]

    dr.rectangle([pad, pad, pad + room.width_cm * scale, pad + room.depth_cm * scale],
                 fill=(255, 255, 255), outline=(40, 40, 40), width=2)
    for ring in pts(free_space(room, layout.placements)):
        dr.polygon(ring, fill=(232, 242, 232, 190))
    for op in room.openings:
        col = (63, 127, 191) if op.kind == "window" else (201, 139, 46)
        for ring in pts(opening_polygon(room, op).buffer(3)):
            dr.polygon(ring, fill=col)
        for ring in pts(swing_polygon(room, op)):
            dr.polygon(ring, outline=col)
    for rad in room.radiators:
        for ring in pts(radiator_polygon(room, rad)):
            dr.polygon(ring, fill=(217, 79, 79, 140))
    for p in layout.placements:
        for ring in pts(access_zone(p)):
            dr.polygon(ring, fill=(0, 0, 0, 18))
    for p in layout.placements:
        col = PALETTE.get(p.role, "#8a8a8a")
        rgb = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))
        for ring in pts(footprint(p)):
            dr.polygon(ring, fill=rgb + (200,), outline=(30, 30, 30))
        c = footprint(p).centroid
        cx, cy = pad + c.x * scale, pad + c.y * scale
        dr.text((cx - 4 * len(p.role) / 2, cy - 6), p.role, fill=(15, 15, 15))
        fx, fy = facing_vector(p.rot)
        dr.line([cx, cy, cx + fx * 26, cy + fy * 26], fill=(15, 15, 15), width=2)
        dr.ellipse([cx + fx * 26 - 3, cy + fy * 26 - 3, cx + fx * 26 + 3, cy + fy * 26 + 3],
                   fill=(15, 15, 15))
    y = pad + room.depth_cm * scale + 12
    head = title or (f"{room.width_cm:.0f}×{room.depth_cm:.0f} см · {room.area_m2:.0f} м² · "
                     f"пол занят {layout.floor_used_pct}% · "
                     + ("нарушений нет" if layout.ok else "ЕСТЬ НАРУШЕНИЯ"))
    dr.text((pad, y), head, fill=(20, 20, 20))
    for v in layout.violations:
        y += 18
        dr.text((pad, y), f"• [{v.code}] {v.message}", fill=(170, 40, 40))
    if layout.unplaced:
        y += 18
        dr.text((pad, y), f"• не размещено: {', '.join(layout.unplaced)}", fill=(170, 40, 40))
    im.save(path)
    return path
