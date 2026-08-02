"""PNG-превью раскладки (top-down) — чтобы план можно было посмотреть глазами, а не читать JSON.

SVG (`planner.svg`) — для веба и диффов; PNG — для чата/отчётов и самопроверки движка.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Шрифт с кириллицей: дефолтный bitmap-шрифт PIL рисует русские подписи «иероглифами»
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def _font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

from .geometry import access_zone, facing_vector, footprint, free_space, opening_polygon, radiator_polygon, swing_polygon
from .models import Layout
from .svg import PALETTE


def render_png(layout: Layout, path: str, *, scale: float = 0.9, pad: int = 60,
               title: str | None = None) -> str:
    room = layout.room
    W = max(int(room.width_cm * scale) + pad * 2, 660)   # ширины хватает и на подписи снизу
    H = int(room.depth_cm * scale) + pad * 2 + 22 * (len(layout.violations) + 3)
    im = Image.new("RGB", (W, H), (250, 248, 245))
    dr = ImageDraw.Draw(im, "RGBA")
    f_item, f_text = _font(15), _font(16)

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
        label = f"{p.role} {int(p.item.w_cm)}×{int(p.item.d_cm)}" if p.item else p.role
        lx = min(max(cx, pad + 4 * len(label)), W - pad - 4 * len(label))   # не выезжать за холст
        dr.text((lx, cy - 9), label, fill=(15, 15, 15), font=f_item, anchor="mm",
                stroke_width=3, stroke_fill=(255, 255, 255))
        fx, fy = facing_vector(p.rot)
        dr.line([cx, cy, cx + fx * 26, cy + fy * 26], fill=(15, 15, 15), width=2)
        dr.ellipse([cx + fx * 26 - 3, cy + fy * 26 - 3, cx + fx * 26 + 3, cy + fy * 26 + 3],
                   fill=(15, 15, 15))
    for op in room.openings:
        cx, cy = _wall_label_xy(room, op, scale, pad)
        dr.text((cx, cy), "дверь" if op.kind != "window" else "окно",
                fill=(120, 80, 20) if op.kind != "window" else (40, 90, 150), font=_font(14),
                anchor="mm", stroke_width=3, stroke_fill=(255, 255, 255))
    y = pad + room.depth_cm * scale + 12
    head = title or (f"{room.width_cm:.0f}×{room.depth_cm:.0f} см · {room.area_m2:.0f} м² · "
                     f"пол занят {layout.floor_used_pct}% · "
                     + ("нарушений нет" if layout.ok else "ЕСТЬ НАРУШЕНИЯ"))
    dr.text((pad, y), head, fill=(20, 20, 20), font=f_text)
    for v in layout.violations:
        y += 18
        dr.text((pad, y), f"• {v.message}", fill=(170, 40, 40), font=f_text)
    if layout.unplaced:
        y += 18
        dr.text((pad, y), f"• не размещено: {', '.join(layout.unplaced)}", fill=(170, 40, 40),
                font=f_text)
    y += 24
    dr.text((pad, y), "серая рамка — зона подхода (занимать нельзя)", fill=(90, 90, 90), font=_font(14))
    y += 18
    dr.text((pad, y), "чёрточка — куда предмет смотрит · зелёный фон — свободный пол",
            fill=(90, 90, 90), font=_font(14))
    im.save(path)
    return path


def _wall_label_xy(room, op, scale: float, pad: int) -> tuple[float, float]:
    """Точка подписи проёма — по центру проёма, чуть внутрь комнаты."""
    mid = op.offset_cm + op.width_cm / 2
    if op.wall == "south":
        return pad + mid * scale, pad + 16
    if op.wall == "north":
        return pad + mid * scale, pad + room.depth_cm * scale - 16
    if op.wall == "west":
        return pad + 22, pad + mid * scale
    return pad + room.width_cm * scale - 22, pad + mid * scale
