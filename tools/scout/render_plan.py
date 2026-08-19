#!/usr/bin/env python3
"""Рендер плана (PNG) ИЗ АРТЕФАКТА JSON — единый источник подачи для solver_run (в момент решения)
и для render-only перерисовки без пересчёта (ускорение 17.08, Codex п.2: подписи/подача меняются
без экзамена). Логика скопирована из solver_run.py 1:1 (нормализация «диван у дальней стены»,
стены/контур/проёмы, предметы, подписи ориентации, стрелка фасада, пилон/снаружи).

  ~/venvs/scout/bin/python render_plan.py <artifact.json> [out.png]     # один
  ~/venvs/scout/bin/python render_plan.py --all [-j 6]                   # все v3set*-layout-acc-zoned-*.json
"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))


def _placed_from_artifact(art: dict) -> tuple[dict, dict]:
    """placed {role: ((x,z), rot, footprint_coords, 1)} и dims {role: (w,d)} — как в зонном пути solver_run."""
    from planner.geometry import footprint as _fp
    from planner.models import Item, Placement
    placed, dims = {}, {}
    for k, v in art.items():
        if k.startswith('_') or not isinstance(v, dict) or 'x' not in v:
            continue
        w, d = float(v.get('w') or 0), float(v.get('d') or 0)
        it = Item(role=k, w_cm=w or 1.0, d_cm=d or 1.0, h_cm=float(v.get('h') or 80))
        p = Placement(role=k, x=float(v['x']), y=float(v.get('z', v.get('y', 0))), rot=float(v.get('rot', 0)), item=it)
        placed[k] = ((p.x, p.y), int(p.rot) % 360, tuple(_fp(p).exterior.coords[:]), 1)
        dims[k] = (w, d)
    return placed, dims


def render_artifact(out: dict, png_path: str, band: str = '14-16') -> None:
    """out — артефакт (как пишет solver_run: предметы x/z/rot/w/d + _room/_zones)."""
    placed, dims = _placed_from_artifact(out)
    FLOOR = list(dims.items())
    RW, RD = float(out['_room']['w']), float(out['_room']['d'])
    BAND = band
    ZONE_IDS = out.get('_zones') or {}
    _CTR_LABELS: list = []
    _r4 = None
    try:
        from planner.models import Opening as _O4, Room as _R4
        _r4 = _R4(width_cm=RW, depth_cm=RD, contour=out['_room'].get('contour'),
                  openings=[_O4(kind=o['kind'], wall=o['wall'], offset_cm=o['offset_cm'], width_cm=o['width_cm']) for o in out['_room'].get('openings', [])])
    except Exception:
        _r4 = None
    # top-down PNG — В НОРМАЛИЗОВАННОМ ВИДЕ (как кадр pipeline2): диван у ДАЛЬНЕЙ стены лицом
    # к камере, камера снизу. Так план и генерация читаются как одна и та же комната.
    _srot=int(placed.get('диван',((0,0),180))[1])%360 if 'диван' in placed else 180
    RWO,RDO=RW,RD                      # ИСХОДНЫЕ габариты — только по ним и нормализуем
    def _nrm(x,z):
        # БАГ до 12.08: здесь стояли RW/RD, которые ниже подменяются на swapped —
        # при повороте плана предметы пересчитывались по чужим габаритам и «выезжали»
        # за стены (замечание владельца «диван заходит за границы комнаты»).
        if _srot==180: return x,z
        if _srot==0:   return RWO-x,RDO-z
        if _srot==90:  return z,RWO-x
        return RDO-z,x
    if _srot in (90,270): RW,RD=RD,RW
    placed={r:(_nrm(*v[0]), (v[1]-(_srot-180))%360, tuple(_nrm(*c) for c in v[2]), v[3])
            for r,v in placed.items()}
    SC=2.6                             # крупнее план — крупнее и подписи (владелец 12.08)
    img=Image.new('RGB',(int(RW*SC)+40,int(RD*SC)+40),(250,247,240)); dr=ImageDraw.Draw(img)
    # шрифт с кириллицей: дефолтный bitmap-шрифт PIL рисует русские подписи «иероглифами» (урок 42)
    from PIL import ImageFont as _IF
    def _font(sz):
        for _p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                   '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'):
            if os.path.exists(_p): return _IF.truetype(_p,sz)
        return _IF.load_default()
    F_ITEM,F_TXT=_font(21),_font(22)   # подписи было не разобрать (владелец 12.08)
    _LBL_BOXES=[]                      # занятые прямоугольники подписей — против наложений
    _ITEM_BOXES=[]                     # рамки предметов — подпись не должна их накрывать


    def _put_label(dr, x, y, txt, font, fill=(15,15,15)):
        """Подпись без наложения на другие подписи: пробуем сместиться по вертикали,
        держимся в кадре; если пришлось уехать далеко — тянем выноску к предмету."""
        bb = dr.textbbox((0, 0), txt, font=font)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        W, H = img.width, img.height
        x = min(max(x, w / 2 + 6), W - w / 2 - 6)

        def _hits(box, boxes):
            return any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3]
                       for b in boxes)

        own = None
        for _b in _ITEM_BOXES:                       # своя рамка — по ней подпись не мешает
            if _b[0] <= x <= _b[2] and _b[1] <= y + h <= _b[3] + h:
                own = _b if own is None else own
        others = [b for b in _ITEM_BOXES if b is not own]
        # два круга: сперва ищем место, свободное И от подписей, И от чужих блоков
        for _strict in (True, False):
          for k in (0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6):
            cy = min(max(y + k * (h + 6), h / 2 + 6), H - h / 2 - 6)
            box = (x - w / 2 - 3, cy - h / 2 - 3, x + w / 2 + 3, cy + h / 2 + 3)
            if _hits(box, _LBL_BOXES) or (_strict and _hits(box, others)):
                continue
            if True:
                _LBL_BOXES.append(box)
                if abs(cy - y) > h:                       # уехала — показываем, к чему она
                    dr.line([x, cy, x, y], fill=(120, 120, 120), width=1)
                dr.text((x, cy), txt, fill=fill, font=font, anchor='mm',
                        stroke_width=3, stroke_fill=(255, 255, 255))
                return x, cy
        _LBL_BOXES.append((x - w / 2, y - h / 2, x + w / 2, y + h / 2))
        dr.text((x, y), txt, fill=fill, font=font, anchor='mm',
                stroke_width=3, stroke_fill=(255, 255, 255))
        return x, y
    def T(x,z): return (20+x*SC,20+(RD-z)*SC)  # z вверх
    # СТЕНЫ ПО ФАКТУ: если сцена задана контуром — рисуем контур, а не прямоугольник
    _ctr_pts=out['_room'].get('contour')
    if _ctr_pts:
        # P5 свода №12 (владелец №5: «рисуется прямоугольник у окна — зачем?»): вырез контура
        # (пилон/выступ) — это НЕ предмет; заштриховать область bbox∖contour и подписать,
        # чтобы читалось как конструкция, одинаково на всех планах с контуром
        try:
            from shapely.geometry import Polygon as _PgC, box as _boxC
            _cp=_PgC([_nrm(x,z) for x,z in _ctr_pts])
            _out=_boxC(0,0,RW,RD).difference(_cp)
            # владелец 17.08 (№18): «выступ» у окна непонятен — эркер выступает НАРУЖУ. Различаем:
            # кусок bbox∖contour, касающийся угла bbox при наличии эркера/скоса — это «снаружи
            # комнаты» (стена рядом с эркером/скошенная стена), иначе — пилон (несущий выступ внутрь)
            try:
                from planner.room_map import contour_features as _cfR
                _has_bay=bool(_cfR(_r4)[0]) if _r4 is not None else False
            except Exception:
                _has_bay=False
            _corners=[(0,0),(RW,0),(0,RD),(RW,RD)]
            for _g in (getattr(_out,'geoms',[_out]) if not _out.is_empty else []):
                if _g.area<400: continue
                _pp=[T(x,z) for x,z in _g.exterior.coords]
                dr.polygon(_pp,fill=(225,222,214),outline=(120,120,120))
                _bx=_g.bounds; _sx,_sy=T((_bx[0]+_bx[2])/2,(_bx[1]+_bx[3])/2)
                _touch=any(abs(_bx[0]-cx)<1e-6 or abs(_bx[2]-cx)<1e-6 for cx,_ in _corners) and \
                       any(abs(_bx[1]-cz)<1e-6 or abs(_bx[3]-cz)<1e-6 for _,cz in _corners)
                _lblc=('снаружи' if _touch else 'пилон/колонна')
                _CTR_LABELS.append((_sx,_sy,_lblc))   # подпись — ПОВЕРХ предметов (в конце)
        except Exception:
            pass
        dr.polygon([T(*_nrm(x,z)) for x,z in _ctr_pts],outline=(60,60,60),width=3)
    else:
        dr.rectangle([T(0,RD),T(RW,0)],outline=(60,60,60),width=3)


    def _wall_seg(op):
        """Отрезок проёма на стене В ИСХОДНЫХ координатах (до нормализации)."""
        o,w = op['offset_cm'], op['width_cm']
        if op['wall']=='south': return (o,0),(o+w,0)
        if op['wall']=='north': return (o,RDO),(o+w,RDO)
        if op['wall']=='west':  return (0,o),(0,o+w)
        return (RWO,o),(RWO,o+w)


    # ПРОЁМЫ ПО ФАКТУ (те же, что видел солвер) — раньше дверь/окно рисовались в
    # фиксированных местах и не совпадали с расстановкой (владелец 12.08)
    for _op in out['_room']['openings']:
        (_ax,_az),(_bx,_bz) = _wall_seg(_op)
        _p1,_p2 = T(*_nrm(_ax,_az)), T(*_nrm(_bx,_bz))
        _door = _op['kind']=='door'
        dr.line([_p1,_p2],fill=((200,120,60) if _door else (90,150,210)),width=9)
        _mid=((_p1[0]+_p2[0])/2,(_p1[1]+_p2[1])/2)
        # подпись — внутрь комнаты, чтобы не уезжала за кадр
        _cx0,_cy0 = T(*_nrm(RWO/2,RDO/2))
        _dx,_dy = _cx0-_mid[0], _cy0-_mid[1]
        _n=max((_dx*_dx+_dy*_dy)**0.5,1e-6)
        _put_label(dr,_mid[0]+_dx/_n*34,_mid[1]+_dy/_n*34,
                   'дверь' if _door else 'окно',F_TXT,
                   fill=(180,110,50) if _door else (60,110,170))
        if _door:
            # ЗОНА ОТКРЫВАНИЯ — РОВНО ТА, ЧТО ПРОВЕРЯЕТ ПРАВИЛО (замечание владельца 12.08:
            # «рисуешь полукруг, а дверь открывается с одной стороны»). Раньше рисовалась
            # окружность 360° — картинка не совпадала с тем, что резервирует движок.
            # Модель консервативна: полоса глубиной swing внутрь комнаты у проёма.
            # рисуем РОВНО ту зону, которую резервирует правило (четверть круга у петли)
            from planner.geometry import swing_polygon as _swp
            from planner.models import Opening as _OpM, Room as _RmM
            _sp=_swp(_RmM(width_cm=RWO, depth_cm=RDO, band=BAND), _OpM(**_op))
            if not _sp.is_empty:
                dr.polygon([T(*_nrm(x,z)) for x,z in _sp.exterior.coords],
                           outline=(225,190,150))
    cols={'диван':(120,120,190),'тв-тумба':(160,160,160),'кресло':(190,150,140),'столик':(150,120,90),
          'пуф':(170,170,150),'торшер':(60,60,60),'кашпо':(170,140,169)}
    # КОНТЕКСТ (19.08, замечание владельца «зачем диван на этом каноне»): предметы из `_context`
    # не входят в состав схемы — они лишь свидетель отношения («ТВ, к которому повёрнута форма»,
    # «диван, по оси которого центрирован носитель»). Рисуем бледной заливкой и пунктирным
    # контуром, подписываем «контекст», но валидатор их всё равно проверяет как часть сцены.
    CTX = set(out.get('_context') or [])

    def _pale(c):
        return tuple(int(v + (250 - v) * 0.62) for v in c)

    def _dashed(pts, fill, dash=9):
        import math as _md
        for i in range(len(pts)):
            (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % len(pts)]
            _L = _md.hypot(x2 - x1, y2 - y1) or 1
            n = max(1, int(_L // dash))
            for k in range(0, n, 2):
                t1, t2 = k / n, min(1.0, (k + 1) / n)
                dr.line([x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1,
                         x1 + (x2 - x1) * t2, y1 + (y2 - y1) * t2], fill=fill, width=2)
    # СНАЧАЛА ковёр (подложка), потом мебель — иначе ковёр закрашивает диван
    _order=sorted(placed.items(), key=lambda kv: 0 if kv[0].split(' ')[0]=='ковёр' else 1)
    for r,v in _order:
        pts=[T(x,z) for x,z in v[2]]
        if r in CTX:
            dr.polygon(pts, fill=_pale(cols.get(r, (200, 200, 200))))
            _dashed(pts, (130, 130, 130))
        else:
            dr.polygon(pts,outline=(40,40,40),fill=cols.get(r,(200,200,200)))
        xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
        _ITEM_BOXES.append((min(xs),min(ys),max(xs),max(ys)))
    # подписи — вторым проходом, поверх всей мебели и в обход чужих блоков
    def _facing_word(r, v):
        """Подпись ориентации (правило владельца 17.08, №2/№15): писать ТОЛЬКО куда повёрнут предмет —
        «→ к ТВ» / «→ к дивану» при точном взгляде (≤15°), «под 30° к дивану» при развороте (число
        градусов до 5°, цель — ближайшая по приоритету в конусе ≤60°); симметричные/пристенные предметы
        (обеденный стол, столик, хранение) — без подписи. Ничего не повёрнуто — пусто (стрелка есть).
        Для 3D/LLM истина — rot; подпись — объяснение (export_plans_ai._with_orientation)."""
        import math as _m
        _base=r.split(' ')[0]
        if _base not in ('диван','кресло'):
            return None
        cx,cz=v[0]; _a=_m.radians(v[1]); fx,fz=_m.sin(_a),_m.cos(_a)
        best=None
        # цели: для дивана — только фокус (ТВ/камин, без лимита дистанции: «к столику» бессмысленно);
        # для кресла — фокус, диван, столик (≤250 см)
        _targets=('тв-тумба','стенка','камин') if _base=='диван' else ('тв-тумба','стенка','камин','диван','столик')
        for r2,v2 in placed.items():
            if r2==r: continue
            b2_=r2.split(' ')[0]
            if b2_ not in _targets: continue
            dx,dz=v2[0][0]-cx,v2[0][1]-cz; d=_m.hypot(dx,dz) or 1.0
            cosang=max(-1.0,min(1.0,(fx*dx+fz*dz)/d)); ang=_m.degrees(_m.acos(cosang))
            _pri={'тв-тумба':0,'стенка':0,'камин':1,'диван':2,'кресло':2,'стол обеденный':3,'столик':4}[b2_]
            if (_base=='кресло' and d>250) or ang>60: continue
            # владелец 17.08 (№55): «под углом» — ТОЛЬКО когда сам предмет повёрнут диагонально
            # (rot не кратен 90°); осевая поза — либо точное «→ к X» (≤15°), либо ничего
            _diag=(int(round(v[1]))%90)!=0
            if ang>15 and not _diag: continue
            _tier=0 if ang<=15 else 1
            if best is None or (_tier,_pri,d)<(best[0],best[1],best[2]): best=(_tier,_pri,d,b2_,ang)
        if not best: return None
        _nm={'тв-тумба':'ТВ','стенка':'ТВ','диван':'дивану','столик':'столику','камин':'камину','стол обеденный':'столу','кресло':'креслу'}
        if best[0]==0: return f"→ к {_nm[best[3]]}"
        return f"под {int(5*round(best[4]/5))}° к {_nm[best[3]]}"

    def _pouf_role(r, v):
        """P5 (владелец №192: «пуф — для ног или что?»): назначение по близости к посадке."""
        import math as _m
        cx,cz=v[0]
        for r2,v2 in placed.items():
            b2_=r2.split(' ')[0]
            if b2_ in ('диван','кресло'):
                d=_m.hypot(v2[0][0]-cx,v2[0][1]-cz)
                if d<=110: return 'для ног'
        return 'доп. место'

    for r,v in _order:
        cx,cz=v[0]; _w,_d=dict(FLOOR).get(r,(0,0))
        _fw=_facing_word(r,v)
        _extra=(f' · {_pouf_role(r,v)}' if r.split(' ')[0]=='пуф' else '')
        # зона кресла (владелец 16.08 №62/181): кресло из чтения/тихой/эркера — подписать зону
        try:
            _zid=(ZONE_IDS or {})
            _zn=None
            for _zk,_zv in (_zid.items() if isinstance(_zid,dict) else []):
                if isinstance(_zv,dict) and r in (_zv.get('members') or []): _zn=_zk; break
            if r.split(' ')[0]=='кресло' and _zn in ('reading','quiet','bay_armchair'):
                _extra+={'reading':' · зона чтения','quiet':' · тихая зона','bay_armchair':' · эркер'}[_zn]
        except Exception:
            pass
        _lbl=f"{r} {int(_w)}x{int(_d)}" + (f" · {_fw}" if _fw else '') + _extra + (
            ' · контекст' if r in CTX else '')
        _tx,_ty=T(cx,cz)
        _put_label(dr,_tx,_ty-8,_lbl,F_ITEM,fill=((120,120,120) if r in CTX else (15,15,15)))
        # стрелка фасада (заметнее): rot 180 = к южной стене
        import math as _m
        if r.split(' ')[0] in ('диван','кресло'):      # стрелка фасада — у направленных всегда (контракт позы)
            _a=_m.radians(v[1]); _fx,_fz=_m.sin(_a),-_m.cos(_a)
            dr.line([_tx,_ty,_tx+_fx*34,_ty+_fz*34],fill=(15,15,15),width=3)
            dr.ellipse([_tx+_fx*34-4,_ty+_fz*34-4,_tx+_fx*34+4,_ty+_fz*34+4],fill=(15,15,15))
    for _sx,_sy,_lblc in _CTR_LABELS:
        _put_label(dr,_sx,_sy,_lblc,F_TXT,fill=(90,90,90))
    img.save(png_path)



def render_file(json_path: str, png_path: str | None = None, band: str | None = None) -> str:
    art = json.load(open(json_path, encoding='utf-8'))
    if png_path is None:
        png_path = json_path[:-5] + '.png'
    if band is None:
        try:
            import re as _re
            m = _re.search(r'v3set(\d+)-', os.path.basename(json_path))
            sets = json.load(open(os.path.join(HERE, 'sets3.json'), encoding='utf-8'))
            band = sets[int(m.group(1)) - 1].get('band') or '14-16'
        except Exception:
            band = '14-16'
    render_artifact(art, png_path, band)
    return png_path


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit(0)
    if a[0] == '--all':
        import glob
        from concurrent.futures import ProcessPoolExecutor
        j = int(a[a.index('-j') + 1]) if '-j' in a else 6
        files = sorted(glob.glob(os.path.join(HERE, 'v3set*-layout-acc-zoned-*.json')))
        with ProcessPoolExecutor(j) as ex:
            list(ex.map(render_file, files))
        print(f'render-only: {len(files)} PNG перерисованы')
    else:
        print(render_file(a[0], a[1] if len(a) > 1 else None))
