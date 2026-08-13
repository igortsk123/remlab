#!/usr/bin/env python3
"""Этап B: раскладка сета солвером Holodeck DFS (см) + hard-проверки эргономики + top-down PNG.
Фолбэк-констрейнты по ролям (Gemini мёртв — статичная таблица из плана).
Запуск (venv!): ~/venvs/scout/bin/python solver_run.py <сет> [W_см D_см]"""
import hashlib
import json, os, sys, random, math
from shapely.geometry import Polygon, box
import solver_core
from PIL import Image, ImageDraw

HERE=os.path.dirname(os.path.abspath(__file__))
n=int(sys.argv[1]) if len(sys.argv)>1 else 1
SETS_FILE='sets3.json' if '--v3' in sys.argv else ('sets2.json' if '--v2' in sys.argv else 'sets.json')
TAG='v3set' if '--v3' in sys.argv else 'set'  # артефакты v3 не перетирают v1/v2
s=json.load(open(os.path.join(HERE,SETS_FILE)))[n-1]
_nums=[a for a in sys.argv[2:] if a.isdigit()]       # флаги (--v3/--engine beam) не путать с размерами
if len(_nums)>=2:
    RW,RD=int(_nums[0]),int(_nums[1])                # комната, см (X, Z)
else:  # размер из метража сета: прямоугольник ~1:1.15
    m2=float(s.get('m2') or 15)
    RW=int((m2*10000/1.15)**0.5//5*5); RD=int(m2*10000/RW//5*5)
print(f"комната {RW}x{RD} см ({RW*RD/10000:.0f} м²), сет {n} band={s.get('band')}")
# occupancy р.2: динамические шкалы от площади (решение владельца 2026-08-02)
OCC=json.load(open(os.path.join(HERE,'occupancy.json')))['dynamic'] if os.path.exists(os.path.join(HERE,'occupancy.json')) else None
BAND=s.get('band') or '14-16'
TBL=(OCC['sofa_table_cm'].get(BAND,[30,50]) if OCC else [30,50])          # диван↔столик
TVD=(OCC['sofa_tv_cm'].get(BAND,[180,300]) if OCC else [180,300])         # диван↔ТВ
# БАГ до 12.08: «диван 2» затирал «диван» в этом словаре — и план показывал габарит
# ВТОРОГО дивана вместо первого (сет 20: 200x90 вместо 214x98). Аудит целостности
# поймал это как фантомный габарит. Первый выигрывает, парные роли только дополняют.
items={}
for _r, _it in s['items'].items():
    items.setdefault(_r.replace(' 2', ''), _it)

def dims(role,defw,defd):
    it=items.get(role) or {}
    w=int(it.get('w') or defw); d=int(it.get('d') or defd)
    return (w,d)

# типовые размеры напольных ролей (Ш,Г см) — фолбэк, когда в фиде нет; порядок = приоритет размещения
_TD=os.path.join(HERE,'typical-dims.json')
FLOOR_TYPICAL=[(r,tuple(v)) for r,v in json.load(open(_TD)).items()] if os.path.exists(_TD) else [
    ('диван',(190,95)),('стенка',(240,45)),('стол обеденный',(120,75)),
    ('шкаф',(90,55)),('комод',(90,42)),('тв-тумба',(90,42)),('витрина',(60,40)),
    ('стеллаж',(80,35)),('камин',(100,30)),('кресло',(76,70)),('столик',(90,50)),
    ('стул',(45,50)),('пуф',(67,50)),('торшер',(33,33)),('кашпо',(30,30))]
FLOOR=[(r,dims(r,*d)) for r,d in FLOOR_TYPICAL if r in items]
# P0.6 (рефери 08.08): стенка XOR тв-тумба — МЬЮТЕКС ДО солвера, не soft после. Стенка =
# носитель ТВ (tv_bearer_roles); легаси-сеты с обоими носителями чинятся прямо здесь.
_TV_STAND_BACKUP=None
if any(r=='стенка' for r,_ in FLOOR) and any(r=='тв-тумба' for r,_ in FLOOR):
    # ЛЕСТНИЦА НОСИТЕЛЕЙ (владелец 13.08): оба в банке, ставится ОДИН — лестницу
    # «стенка → тумба» отрабатывает place_media; здесь тумбу больше не выкидываем.
    print('BEARERS: стенка приоритетна, тв-тумба — запасной носитель (лестница медиа)', flush=True)

# диван без глубины в фиде — типовая 95
if items.get('диван') and not items['диван'].get('d'):
    FLOOR[0]=('диван',(FLOOR[0][1][0],95))
# Z4: солвер обязан видеть ВЕСЬ состав — экземпляры по qty («кресло 2», «стул 2–4») и роль
# «диван 2» (раньше qty терялся: сет с парой кресел раскладывался с одним)
_extra=[]
for _r,(_w,_d) in FLOOR:
    _q=int((items.get(_r) or {}).get('qty') or 1)
    for _k in range(2,_q+1):
        _extra.append((f'{_r} {_k}',(_w,_d)))
if items.get('диван 2'):
    _it2=items['диван 2']
    _extra.insert(0,('диван 2',(int(_it2.get('w') or 190),int(_it2.get('d') or _it2.get('dia') or 95))))
FLOOR+=_extra

# фолбэк-констрейнты по ролям (онтология Holodeck; порядок = порядок размещения)
CONS={
 'диван':[{"type":"global","constraint":"edge"}],
 'тв-тумба':[{"type":"global","constraint":"edge"},
             {"type":"direction","constraint":"face to","target":"диван"},
             {"type":"distance","constraint":"far","target":"диван"}],
 'кресло':[{"type":"global","constraint":"edge"},
           {"type":"distance","constraint":"near","target":"диван"},
           {"type":"relative","constraint":"side of","target":"диван"}],
 'столик':[{"type":"global","constraint":"middle"},
           {"type":"relative","constraint":"in front of","target":"диван"},
           {"type":"distance","constraint":"near","target":"диван"}],
 'пуф':[{"type":"global","constraint":"middle"},
        {"type":"distance","constraint":"near","target":"столик"}],
 'торшер':[{"type":"global","constraint":"edge"},
           {"type":"distance","constraint":"near","target":"диван"}],
 'кашпо':[{"type":"global","constraint":"edge"},
          {"type":"distance","constraint":"far","target":"диван"}],
 # роли остальных сетов (универсальная логика гостиной; товар любой — правила по роли)
 'стенка':[{"type":"global","constraint":"edge"},           # длинная секция — к стене напротив дивана
           {"type":"direction","constraint":"face to","target":"диван"},
           {"type":"distance","constraint":"far","target":"диван"}],
 'комод':[{"type":"global","constraint":"edge"},            # к свободной стене, не в зоне отдыха
          {"type":"distance","constraint":"far","target":"диван"}],
 'шкаф':[{"type":"global","constraint":"edge"},
         {"type":"distance","constraint":"far","target":"диван"}],
 'стеллаж':[{"type":"global","constraint":"edge"},
            {"type":"distance","constraint":"far","target":"столик"}],
 'витрина':[{"type":"global","constraint":"edge"},
            {"type":"distance","constraint":"far","target":"диван"}],
 'камин':[{"type":"global","constraint":"edge"},            # электрокамин — центр свободной стены
          {"type":"direction","constraint":"face to","target":"диван"}],
 'стол обеденный':[{"type":"global","constraint":"middle"}, # обеденная зона — ближе к окну/свободному углу
                   {"type":"distance","constraint":"far","target":"диван"}],
 'стул':[{"type":"global","constraint":"middle"},
         {"type":"distance","constraint":"near","target":"стол обеденный"},
         {"type":"relative","constraint":"side of","target":"стол обеденный"}],
}
order_ix={r:i for i,(r,_) in enumerate(FLOOR)}
# пожелание валидно, только если цель есть в сете И размещается РАНЬШЕ (требование DFS-солвера)
CONS={r:[c for c in cl if 'target' not in c or order_ix.get(c['target'],99)<order_ix.get(r,98)]
      for r,cl in CONS.items()}
for r in order_ix:
    if not CONS.get(r): CONS[r]=[{"type":"global","constraint":"edge"}]

# layout-quality п.1: угловой диван — детект по имени/глубине; ставится СТРОГО в угол (СВ, дальше от двери)
import re as _re
# Г-детект (08.08, вердикты «ковёр смещён»): слово «угловой» БЕЗ глубины ≥140 — не Г
# (диваны 285×95 помечались угловыми по имени, ковёр «центрировался» по несуществующему
# плечу на +47 см). Г = глубина >150 ИЛИ (имя + глубина ≥140).
_dv=(items.get('диван') or {})
CORNER=bool(_dv) and (
    ((_dv.get('d') or 0)>150)
    or (bool(_re.search(r'углов',(_dv.get('name') or '').lower())) and (_dv.get('d') or 0)>=140))
room=Polygon([(0,0),(RW,0),(RW,RD),(0,RD)])
# Дверь (юг) и окно (восток) — ВАРИАТИВНЫЕ от номера сета (А5, аудит 06.08): раньше проёмы были
# одни на все сеты, и «логичность» тестировалась на нереальной комнате. Детерминированно
# (никакого random — воспроизводимость), стены фиксированы: на них завязаны glare-правила и камеры.
_r1=((n*2654435761)>>4)%1000/1000.0; _r2=((n*40503)>>3)%1000/1000.0
if os.environ.get('FIXED_OPENINGS')=='1':   # отладка: изоляция эффекта вариативных проёмов
    _r1=_r2=0.0
DOOR_W=90; DOOR_OFF=round(20+_r1*max(RW-DOOR_W-60-20,0))
WIN_W=round(120+_r2*60); WIN_OFF=round(100+(((n*97)%100)/100.0)*max(RD-WIN_W-200,0))
door=box(DOOR_OFF,0,DOOR_OFF+DOOR_W,92); window=box(RW-15,WIN_OFF,RW,WIN_OFF+WIN_W)
initial={'дверь':((DOOR_OFF+DOOR_W/2,45),0,tuple(door.exterior.coords[:]),1),
         'окно-радиатор':((RW-8,WIN_OFF+WIN_W/2),0,tuple(window.exterior.coords[:]),1)}

def hard_checks(placed, zone_used=()):
    """Hard-проверки раскладки (общие для DFS-зона-билдера и beam-движка Э2)."""
    # hard-проверки (правила из плана Ф3 + ресёрч: ТВ не дальше 300 см)
    def poly(role): return Polygon(placed[role][2])
    def gap(a,b): return poly(a).distance(poly(b))
    def zone_gap(role):
        """Дистанция зоны меряется от ФРОНТА посадочного места. У Г-дивана фронт — передняя
        грань ДЛИННОЙ секции (не край короткого плеча) и зависит от поворота: одна реализация
        на оба движка, иначе проверялки расходятся (урок 40)."""
        if not CORNER: return gap('диван',role)
        srot=int(placed['диван'][1])%360
        ax=0 if srot in (90,270) else 1              # ось «лица»: 90/270 → X(0), иначе Z(1)
        lv=sorted({round(c[ax],2) for c in placed['диван'][2]})
        if len(lv)<3: return gap('диван',role)
        tgt=[c[ax] for c in placed[role][2]]
        return (lv[1]-max(tgt)) if srot in (180,270) else (min(tgt)-lv[-2])
    checks=[]
    # Пуф стоит ЗА СТОЛИКОМ, поэтому меряем его по соседу — столику, а не по дивану: до дивана
    # там законные 120-140 см (владелец, 2026-08-05).
    if 'пуф' in placed and 'столик' in placed:
        gt=gap('столик','пуф')
        checks.append(('столик↔пуф ≤60 см', gt<=60, round(gt)))
    if 'диван' in placed and 'пуф' in placed:
        gp=zone_gap('пуф')
        checks.append(('диван↔пуф ≤180 см', gp<=180, round(gp)))
    if 'диван' in placed and 'столик' in placed:
        g=zone_gap('столик')
        checks.append((f'диван↔столик {TBL[0]}–{TBL[1]} см',TBL[0]<=g<=TBL[1]+10,round(g)))
    if 'диван' in placed and 'тв-тумба' in placed:
        # верхняя граница шкалы — КОМФОРТ (мягко), жёсткий потолок — кламп диагоналей (400 см):
        # иначе в глубокой комнате диван вынужден отплывать от стены (решение владельца 2026-08-03)
        g=zone_gap('тв-тумба'); lo_c=150 if CORNER else TVD[0]
        hard_hi=max(TVD[1],((OCC or {}).get('sofa_tv_hard_max') or 400))
        checks.append((f'диван↔ТВ {lo_c}–{hard_hi} см',lo_c<=g<=hard_hi,round(g)))
        if g>TVD[1]: print(f"  (комфорт: дальше шкалы {TVD[1]} см — диван у стены важнее)",flush=True)
    if 'диван' in placed and 'кресло' in placed:
        g=gap('диван','кресло'); checks.append(('диван↔кресло ≤200 см',g<=200,round(g)))
    door_ok=all(not poly(r).intersects(door) for r in placed)
    checks.append(('дуга двери свободна',door_ok,''))
    return checks


def attempt(seed):
    """Одна раскладка: DFS + пост-фиксы + hard-проверки. Возвращает (placed, missing, checks)."""
    random.seed(seed)
    solver=solver_core.DFS_Solver_Floor(grid_size=15,random_seed=seed,max_duration=12)
    init=initial.copy()
    # === ЗОНА-БИЛДЕР (владелец 2026-08-02: «зона разваливается») ===
    # Разговорная зона строится ДЕТЕРМИНИРОВАННО единым блоком: диван (фронт ПАРАЛЛЕЛЕН ТВ) →
    # столик по шкале → кресло ПОЛУКРУГОМ к зоне (ADR-0051, дуга 135–225°±35°) → пуф вне оси →
    # торшер у дивана → кашпо в свободный угол. DFS — только периферия (хранение/камин/обеденная).
    fd=dict(FLOOR); placed={}
    def _rect(cx,cz,w,d):
        return ((cx-w/2,cz-d/2),(cx+w/2,cz-d/2),(cx+w/2,cz+d/2),(cx-w/2,cz+d/2))
    def _fits(coords,ignore=()):
        from shapely.geometry import Polygon as _Z
        p=_Z(coords)
        if not room.buffer(1).contains(p) or p.intersects(door): return False
        return not any(_Z(v[2]).intersects(p) for r,v in placed.items() if r not in ignore)
    zone_used=set()
    if 'диван' in fd:
        w_s,d_s=fd['диван']
        if CORNER:
            dd=max(d_s,150); SEC=(OCC or {}).get('corner_sofa_section_depth_cm',95)
            cx0=RW-w_s
            # float Г-дивана: в глубокой комнате прижатый к дальней стене угловой оказывается
            # дальше TVD от ТВ — сдвигаем ВЕСЬ Г к югу (за диваном легальная зона, свод р.2)
            base=RD
            if 'тв-тумба' in fd:
                dist=(RD-SEC)-fd['тв-тумба'][1]
                # Отплываем от стены только при нарушении ЖЁСТКОГО предела, а не ради комфортных
                # 300 см: иначе диван стоит в 45 см от стены и на плане это читается как ошибка
                # (владелец, 2026-08-05). Та же логика во второй ветке — оба движка обязаны
                # вести себя одинаково (урок 40).
                hard=max(TVD[1],400)
                if dist>hard: base=RD-min(dist-hard,150)
            coords=((cx0,base-SEC),(RW-SEC,base-SEC),(RW-SEC,base-dd),(RW,base-dd),(RW,base),(cx0,base))
            placed['диван']=((cx0+w_s/2,base-SEC/2),180,coords,1)
            sofa_front=base-SEC
            # свободный сегмент длинной секции (без короткого плеча) — центр зоны
            sofa_cx=(cx0+RW-SEC)/2; sofa_x0,sofa_x1=cx0,RW-SEC
        else:
            sofa_cx=RW/2; sofa_front=RD-d_s
            # ТВ-дистанция: диван отплывает от стены ТОЛЬКО если иначе нарушается ЖЁСТКИЙ предел
            # (не «желаемый»). Раньше он подтягивался к комфортным 300 см и вставал в 45 см от
            # стены — на плане это читается как ошибка: мебель у стены обязана касаться стены
            # (владелец, 2026-08-05). Сдвиг остаётся, но только когда без него диван реально
            # слишком далеко от экрана.
            if 'тв-тумба' in fd:
                d_tv=fd['тв-тумба'][1]
                dist=sofa_front-d_tv
                hard=max(TVD[1], 400)
                if dist>hard:
                    sh=min(dist-hard,120); sofa_front-=sh
            placed['диван']=((sofa_cx,sofa_front+d_s/2),180,_rect(sofa_cx,sofa_front+d_s/2,w_s,d_s),1)
            sofa_x0,sofa_x1=sofa_cx-w_s/2,sofa_cx+w_s/2
        zone_used.add('диван')
        # ТВ-тумба: южная стена, фронт ПАРАЛЛЕЛЕН дивану, центр по оси (клэмп от двери)
        if 'тв-тумба' in fd:
            w_tv,d_tv=fd['тв-тумба']
            tvx=max(sofa_cx,115+w_tv/2)  # дверь слева (x<110)
            tvc=_rect(tvx,d_tv/2,w_tv,d_tv)
            if _fits(tvc): placed['тв-тумба']=((tvx,d_tv/2),0,tvc,1); zone_used.add('тв-тумба')
        # столик: по центру фронта, gap по шкале площади
        if 'столик' in fd:
            w_t,d_t=fd['столик']; gap=(TBL[0]+TBL[1])/2
            tz=sofa_front-gap-d_t/2
            tc=_rect(sofa_cx,tz,w_t,d_t)
            if _fits(tc): placed['столик']=((sofa_cx,tz),180,tc,1); zone_used.add('столик')
        # кресло: ПОЛУКРУГОМ вокруг зоны (ADR-0051, схема ProcTHOR — решение владельца 2026-08-02;
        # было: строго 90° к столику слева). Азимут от центра зоны: 180° = сторона дивана,
        # 0° = сторона ТВ; берём дугу 135–225° с джиттером ±35°, кресло смотрит в центр зоны,
        # поворот квантуем к 0/90/180/270 (инвариант «параллельно стенам» держим).
        if 'кресло' in fd:
            w_a,d_a=fd['кресло']
            arc=(OCC or {}).get('armchair_clearances',{}).get('placement_scheme',{})
            lo,hi=arc.get('arc_deg_from_tv_axis',[135,225]); jit=arc.get('jitter_deg',35)
            if 'столик' in placed:
                (cx_z,cz_z)=placed['столик'][0]
                w_t,d_t=fd['столик']; R=max(w_t,d_t)/2+45+max(w_a,d_a)/2
            else:  # без столика — центр зоны перед диваном
                cx_z,cz_z=sofa_cx,sofa_front-90; R=45+max(w_a,d_a)/2
            angles=[lo,hi]+[lo+jit,hi-jit,lo-jit,hi+jit]
            angles=[a+random.uniform(-jit/3,jit/3) for a in angles]
            # радиус эскалируем: на дуге кресло часто упирается в диван — отодвигаем от центра зоны,
            # прежде чем уходить к «плоским» углам (иначе полукруг вырождается в «сбоку от столика»)
            angles=[(a,k) for a in angles for k in (1.0,1.35,1.7)]  # приоритет — сама дуга, радиус вторичен
            done_a=False
            for th,kR in angles:
                R_=R*kR
                r=math.radians(th)
                ax=cx_z+R_*math.sin(r); az=cz_z-R_*math.cos(r)  # 180° → к дивану (+z), 0° → к ТВ (−z)
                fx,fz=-math.sin(r),math.cos(r)                 # лицом в центр зоны
                if abs(fx)>abs(fz)+0.05: rot,ww,dd_=(90 if fx>0 else 270),d_a,w_a
                else:                    rot,ww,dd_=(180 if fz<0 else 0),w_a,d_a
                ax=min(max(ax,20+ww/2),RW-20-ww/2); az=min(max(az,20+dd_/2),RD-20-dd_/2)
                ac=_rect(ax,az,ww,dd_)
                if _fits(ac):
                    placed['кресло']=((ax,az),rot,ac,1); zone_used.add('кресло'); done_a=True; break
            if not done_a:  # фолбэк: сбоку от зоны, лицом к ней
                ax=max(20+d_a/2, sofa_x0-40-d_a/2); az=sofa_front-60
                ac=_rect(ax,az,d_a,w_a)
                if _fits(ac): placed['кресло']=((ax,az),90,ac,1); zone_used.add('кресло')
        # пуф: справа от столика симметрично креслу
        if 'пуф' in fd:
            w_p,d_p=fd['пуф']
            cands=[]
            # ПУФ — ЗА СТОЛИКОМ, ПАРАЛЛЕЛЬНО ДИВАНУ. Это классическая постановка оттоманки: она
            # продолжает зону отдыха, а не встаёт поперёк прохода перед столиком (владелец,
            # 2026-08-05). Ставим по оси дивана, дальше столика от дивана, тем же разворотом.
            if 'столик' in placed:
                tzc_=placed['столик'][0][1]; d_t_=fd['столик'][1]
                pz=tzc_-d_t_/2-30-d_p/2
                cands.append((sofa_cx, pz, 180, w_p, d_p))
            if not CORNER:  # справа от зоны (у Г там короткое плечо)
                cands.append((min(RW-20-d_p/2,sofa_x1+40+d_p/2),
                              (sofa_front-gap/2-w_p/2 if 'столик' in fd else sofa_front-60),270,d_p,w_p))
            if 'столик' in placed:  # сбоку от столика ВНЕ оси просмотра диван-ТВ (не спиной к ТВ)
                tx1=max(c[0] for c in placed['столик'][2]); tx0=min(c[0] for c in placed['столик'][2])
                tzc=placed['столик'][0][1]
                cands.append((tx1+25+d_p/2, tzc, 270, d_p, w_p))          # восточнее столика
                # По диагонали пуф уезжал на 90 см вперёд и оказывался один посреди комнаты
                # (владелец: «пуф далеко», 2026-08-05). Держим его вплотную к столику.
                cands.append((tx0-30-d_p/2, tzc-40, 90, d_p, w_p))        # юго-западная диагональ
            for px,pz,rot_,ww,dd_ in cands:
                pc=_rect(px,pz,ww,dd_)
                if _fits(pc): placed['пуф']=((px,pz),rot_,pc,1); zone_used.add('пуф'); break
        # торшер: у края дивана (запад) → рядом с креслом (PT: лампа вплотную к креслу) → восточный край
        if 'торшер' in fd:
            w_l,d_l=fd['торшер']
            lc_=[(max(20+w_l/2,sofa_x0-25-w_l/2), RD-25-d_l/2)]
            if 'кресло' in placed:      # кресло заняло западный край — лампа встаёт к самому креслу
                (kx,kz)=placed['кресло'][0]
                kx0=min(c[0] for c in placed['кресло'][2]); kx1=max(c[0] for c in placed['кресло'][2])
                kz0=min(c[1] for c in placed['кресло'][2]); kz1=max(c[1] for c in placed['кресло'][2])
                lc_+= [(kx0-20-w_l/2,kz0+d_l/2),(kx1+20+w_l/2,kz0+d_l/2),(kx,kz1+20+d_l/2),(kx,kz0-20-d_l/2)]
            lc_.append((min(RW-20-w_l/2,sofa_x1+25+w_l/2), RD-25-d_l/2))
            for lx,lz in lc_:
                lx=min(max(lx,20+w_l/2),RW-20-w_l/2); lz=min(max(lz,20+d_l/2),RD-20-d_l/2)
                lay=_rect(lx,lz,w_l,d_l)
                if _fits(lay): placed['торшер']=((lx,lz),180,lay,1); zone_used.add('торшер'); break
        # кашпо: свободный угол (СЗ, потом ЮВ)
        if 'кашпо' in fd:
            w_k,d_k=fd['кашпо']
            for kx,kz in ((25+w_k/2,RD-25-d_k/2),(RW-25-w_k/2,110+d_k/2)):
                kc=_rect(kx,kz,w_k,d_k)
                if _fits(kc): placed['кашпо']=((kx,kz),0,kc,1); zone_used.add('кашпо'); break
    # DFS — периферия (всё, что не встало в зону)
    FLOOR_l=[f for f in FLOOR if f[0] not in zone_used]
    CONS_l={r:[c for c in cl if c.get('target') not in zone_used or c.get('target') in dict(FLOOR_l)]
            for r,cl in CONS.items() if r in dict(FLOOR_l)}
    for r,v in placed.items(): init['зона-'+r]=v
    if 'диван' in placed:  # проход вокруг зоны: периферия не прислоняется к дивану/столику (свод: 60-70 см)
        from shapely.geometry import Polygon as _ZB
        buf=_ZB(placed['диван'][2]).buffer(65)
        if 'столик' in placed: buf=buf.union(_ZB(placed['столик'][2]).buffer(50))
        buf=buf.intersection(room)
        init['зона-буфер']=((buf.centroid.x,buf.centroid.y),0,tuple((x,z) for x,z in buf.exterior.coords),1)
        bx0=min(c[0] for c in placed['диван'][2]); bx1=max(c[0] for c in placed['диван'][2])
        bz1=max(c[1] for c in placed['диван'][2])
        if RD-bz1>5:  # диван отплыл — полоса позади него до стены недоступна, никого туда не ставить
            init['зона-тыл']=(((bx0+bx1)/2,(bz1+RD)/2),0,((bx0-25,bz1),(bx1+25,bz1),(bx1+25,RD),(bx0-25,RD)),1)
    random.seed(seed)
    sol=solver.get_solution(room,FLOOR_l,CONS_l,init) if FLOOR_l else {}
    for k,v in sol.items():
        if k not in init: placed[k]=v
    missing=[r for r,_ in FLOOR if r not in placed]

    # пост-фикс эргономики: столик от дивана 30–50 см (DFS-'near' премирует близость)
    def shift(role,dx,dz):
        (cx,cz),rot,coords,sc=placed[role]
        placed[role]=((cx+dx,cz+dz),rot,tuple((x+dx,z+dz) for x,z in coords),sc)
    if 'диван' in placed and 'столик' in placed:
        from shapely.geometry import Polygon as _P
        def _ok(role):
            others=[_P(v[2]) for r,v in placed.items() if r!=role]+[door]
            p=_P(placed[role][2])
            return room.buffer(1).contains(p) and not any(p.intersects(o) for o in others)
        g=_P(placed['диван'][2]).distance(_P(placed['столик'][2]))
        if not (TBL[0]<=g<=TBL[1]+10):
            rot=placed['диван'][1]  # диван edge: 0=лицом на север, 180=на юг, 90=восток, 270=запад
            dxz={0:(0,1),180:(0,-1),90:(1,0),270:(-1,0)}[rot]
            fixed=False
            if g<TBL[0]:  # вплотную: пробуем отодвинуть (полный сдвиг → уменьшающиеся)
                for f in (1.0,0.6,0.3):
                    need=((TBL[0]+TBL[1])/2-g)*f
                    cand=(dxz[0]*need,dxz[1]*need)
                    moved=['столик']; shift('столик',*cand)
                    if 'пуф' in placed and _P(placed['столик'][2]).intersects(_P(placed['пуф'][2])):
                        moved.append('пуф'); shift('пуф',*cand)  # пуф «около столика» — едет каскадом
                    if all(_ok(m) for m in moved) and _P(placed['диван'][2]).distance(_P(placed['столик'][2]))>=TBL[0]-5:
                        fixed=True; break
                    for m in moved: shift(m,-cand[0],-cand[1])
            if not fixed:
                # столик не перед диваном (DFS прижал сбоку) → ПЕРЕСТАВИТЬ прямо перед диваном в 40 см
                sx,sz=placed['диван'][0]
                sxs=[c[0] for c in placed['диван'][2]]; szs=[c[1] for c in placed['диван'][2]]
                tx0,tz0,tx1,tz1=[f([c[i] for c in placed['столик'][2]]) for i,f in ((0,min),(1,min),(0,max),(1,max))]
                tw,td=tx1-tx0,tz1-tz0
                half_sofa=(95/2 if CORNER else abs(dxz[0])*(max(sxs)-min(sxs))/2+abs(dxz[1])*(max(szs)-min(szs))/2)
                if CORNER:  # столик перед ДЛИННОЙ секцией Г-дивана: якорь — центр секции, не bbox
                    sx=(min(sxs)+max(sxs))/2; sz=max(szs)-95/2
                half_t=abs(dxz[0])*tw/2+abs(dxz[1])*td/2
                _mid=(TBL[0]+TBL[1])/2
                ncx,ncz=sx+dxz[0]*(half_sofa+_mid+half_t), sz+dxz[1]*(half_sofa+_mid+half_t)
                old=placed['столик']
                nc=tuple((x-old[0][0]+ncx, z-old[0][1]+ncz) for x,z in old[2])
                placed['столик']=((ncx,ncz),old[1],nc,old[3])
                if not _ok('столик'): placed['столик']=old  # некуда — оставляем как было

    # пост-фикс «закрытый угол»: edge-предмет, вставший в конце стены с щелью до угла ≤80 см,
    # прижимается к углу (артефакт DFS: угол не премируется; замечание владельца 2026-08-02)
    from shapely.geometry import Polygon as _PP
    def _bbox(role):
        xs=[c[0] for c in placed[role][2]]; zs=[c[1] for c in placed[role][2]]
        return min(xs),min(zs),max(xs),max(zs)
    for role in list(placed):
        if role in ('столик','пуф','стул','стол обеденный','кресло','диван','тв-тумба','торшер','кашпо'): continue
        x0,z0,x1,z1=_bbox(role)
        cands=[]
        if min(z0,RD-z1)<12 or min(x0,RW-x1)<12:  # реально у стены
            if 0<x0<=80: cands.append((-x0,0))
            if 0<RW-x1<=80: cands.append((RW-x1,0))
            if 0<z0<=80 and (x0<12 or RW-x1<12): cands.append((0,-z0))
            if 0<RD-z1<=80 and (x0<12 or RW-x1<12): cands.append((0,RD-z1))
        for dx,dz in sorted(cands,key=lambda c:abs(c[0])+abs(c[1])):
            (cx,cz),rot,coords,sc=placed[role]
            nc=tuple((x+dx,z+dz) for x,z in coords)
            np_=_PP(nc)
            if any(np_.intersects(_PP(v[2])) for r2,v in placed.items() if r2!=role) or np_.intersects(door): continue
            if not room.buffer(1).contains(np_): continue
            placed[role]=((cx+dx,cz+dz),rot,nc,sc); break

    # --- layout-quality п.2–5 (владелец + ресёрч 2026-08-02) ---
    from shapely.geometry import Polygon as _Q
    def _bbq(role):
        xs=[c[0] for c in placed[role][2]]; zs=[c[1] for c in placed[role][2]]
        return min(xs),min(zs),max(xs),max(zs)
    def _try_place(role,x0,z0,w,d,rot):
        nc=((x0,z0),(x0+w,z0),(x0+w,z0+d),(x0,z0+d))
        p=_Q(nc)
        if not room.buffer(1).contains(p) or p.intersects(door): return False
        if any(p.intersects(_Q(v[2])) for r2,v in placed.items() if r2!=role): return False
        placed[role]=((x0+w/2,z0+d/2),rot,nc,1); return True
    def wall_of(role):
        x0,z0,x1,z1=_bbq(role)
        wl,dv=min({'W':x0,'E':RW-x1,'S':z0,'N':RD-z1}.items(),key=lambda kv:kv[1])
        return wl if dv<=12 else None
    def snap_wall(role,avoid=None,prefer=None):
        """Спиной к стене, длинной стороной вдоль, лицом в комнату; центр стены → края."""
        # Габариты берём из каталога (fd), а не из bbox текущей постановки: bbox мог остаться от
        # прежнего кандидата с типовой глубиной, и комод со стеллажом уходили ЗА стену на 4-5 см
        # (владелец: «шкаф вдоль стены не пашет», 2026-08-05).
        _w, _d = dict(FLOOR).get(role, (0, 0))
        if _w and _d:
            L, Dp = max(_w, _d), min(_w, _d)
        else:
            x0,z0,x1,z1=_bbq(role); L,Dp=max(x1-x0,z1-z0),min(x1-x0,z1-z0)
        for wl in (prefer or ['N','E','W','S']):
            if wl==avoid: continue
            if wl in ('N','S'):
                zz=RD-Dp if wl=='N' else 0; rot=180 if wl=='N' else 0
                mid=int((RW-L)/2)
                for cx in sorted(range(0,int(RW-L)+1,15),key=lambda c:abs(c-mid)):
                    if _try_place(role,cx,zz,L,Dp,rot): return wl
            else:
                xx=RW-Dp if wl=='E' else 0; rot=270 if wl=='E' else 90
                mid=int((RD-L)/2)
                for cz in sorted(range(95,int(RD-L)+1,15),key=lambda c:abs(c-mid)):
                    if _try_place(role,xx,cz,Dp,L,rot): return wl
        return None
    # п.2: корпусная мебель — спиной к стене, длинной стороной вдоль (не «поперёк комнаты»)
    for role in ('шкаф','стенка','стеллаж','витрина','комод','тв-тумба','камин'):
        if role not in placed or role in zone_used: continue
        wl=wall_of(role); x0,z0,x1,z1=_bbq(role); w_,d_=x1-x0,z1-z0
        if wl is None or (wl in ('N','S') and w_<d_) or (wl in ('E','W') and d_<w_):
            snap_wall(role)
    # п.3: ТВ строго напротив дивана (сектор ±45°) И в дистанции шкалы TVD;
    # далеко в большой комнате → диван «отплывает» от стены (float, свод р.2), столик/пуф каскадом
    if 'диван' in placed and 'тв-тумба' in placed and 'тв-тумба' not in zone_used:
        from shapely.geometry import Polygon as _P3
        def _tv_state():
            (sx,sz)=placed['диван'][0]; srot=placed['диван'][1]
            dirv={0:(0,1),180:(0,-1),90:(1,0),270:(-1,0)}[srot]
            g=_P3(placed['диван'][2]).distance(_P3(placed['тв-тумба'][2]))
            tx,tz=placed['тв-тумба'][0]
            L=math.hypot(tx-sx,tz-sz) or 1
            cos=((tx-sx)*dirv[0]+(tz-sz)*dirv[1])/L
            return dirv,g,cos
        dirv,g,cos=_tv_state()
        oppw={(0,1):'N',(0,-1):'S',(1,0):'E',(-1,0):'W'}[dirv]
        if cos<0.707 or not (TVD[0]<=g<=TVD[1]):
            # перебор стен: смотровая, затем перпендикулярные — берём вариант с лучшей дистанцией
            best_tv=None
            # свод window_tv_glare: окно на E — экран ТВ на западной стене смотрел бы в окно (блики); W исключаем
            for wl in [w_ for w_ in [oppw]+[x_ for x_ in ('N','S','E') if x_!=oppw] if w_!='W']:
                keep=placed['тв-тумба']
                if snap_wall('тв-тумба',prefer=[wl]) is None: continue
                d2,g2,c2=_tv_state()
                pen=(0 if c2>=0.707 else 100)+max(0,TVD[0]-g2)+max(0,g2-TVD[1])
                if best_tv is None or pen<best_tv[0]: best_tv=(pen,placed['тв-тумба'])
                placed['тв-тумба']=keep
            if best_tv: placed['тв-тумба']=best_tv[1]
        dirv,g,cos=_tv_state()
        lo_eff=150 if CORNER else TVD[0]  # угловой смотрит диагонально — ближе допустимо (свод р.2)
        if g<lo_eff and not CORNER:  # слишком близко → диван назад к своей стене
            need=lo_eff-g
            cand=(-dirv[0]*need,-dirv[1]*need)
            moved=['диван']+[r for r in ('столик','пуф') if r in placed]
            for m in moved: shift(m,*cand)
            from shapely.geometry import Polygon as _P5
            ok_all=all(room.buffer(1).contains(_P5(placed[m][2])) and
                       not any(_P5(placed[m][2]).intersects(_P5(v[2])) for r2,v in placed.items() if r2 not in moved)
                       and not _P5(placed[m][2]).intersects(door) for m in moved)
            if not ok_all:
                for m in moved: shift(m,-cand[0],-cand[1])
        dirv,g,cos=_tv_state()
        if g>TVD[1] and not CORNER:  # всё ещё далеко → диван отплывает от стены к ТВ
            need=min(g-TVD[1], 120)
            cand=(dirv[0]*need,dirv[1]*need)
            moved=['диван']+[r for r in ('столик','пуф') if r in placed]
            for m in moved: shift(m,*cand)
            from shapely.geometry import Polygon as _P4
            ok_all=all(room.buffer(1).contains(_P4(placed[m][2])) and
                       not any(_P4(placed[m][2]).intersects(_P4(v[2])) for r2,v in placed.items() if r2 not in moved)
                       and not _P4(placed[m][2]).intersects(door) for m in moved)
            if not ok_all:
                for m in moved: shift(m,-cand[0],-cand[1])
    # разговорная зона: кресло уехало дальше 200 от дивана → прижать к перпендикулярной стене ближе к дивану
    if 'диван' in placed and 'кресло' in placed:
        from shapely.geometry import Polygon as _P6
        if _P6(placed['диван'][2]).distance(_P6(placed['кресло'][2]))>200:
            (sx,sz)=placed['диван'][0]; srot=placed['диван'][1]
            side_walls={'0':['E','W'],'180':['E','W'],'90':['N','S'],'270':['N','S']}[str(srot)]
            keep=placed['кресло']; done=False
            for wl in side_walls:
                if snap_wall('кресло',prefer=[wl]) and _P6(placed['диван'][2]).distance(_P6(placed['кресло'][2]))<=200:
                    done=True; break
                placed['кресло']=keep
            if not done: placed['кресло']=keep
    # п.4: высокая корпусная мебель — НЕ на стене ТВ; п.5: камин — не на стене ТВ (есть тумба)
    twl=wall_of('тв-тумба') if 'тв-тумба' in placed else None
    if twl:
        for role in ('шкаф','стенка','стеллаж','витрина','камин'):
            if role in placed and wall_of(role)==twl: snap_wall(role,avoid=twl)

    checks=hard_checks(placed, zone_used)
    return placed,missing,checks

def attempt_beam():
    """Э7: раскладка прод-ядром (services/planner-solver): кандидаты → hard → beam → доводка.

    Возвращает тот же контракт, что и attempt(): (placed, missing, checks) — рендер, JSON и
    проверки общие, поэтому движки сравнимы «в лоб» на одних и тех же сетах.
    """
    sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))
    from planner.beam import solve as _solve
    from planner.geometry import footprint as _fp
    from planner.models import Item as _It, Opening as _Op, Radiator as _Rad, Room as _Rm

    # Z5: приёмочные сцены могут задавать осевой КОНТУР комнаты (Э8) через env;
    # RW/RD тогда — bbox контура (двери/окна валидны: юг у фикс-контуров сплошной)
    _ctr = os.environ.get('SCENE_CONTOUR')
    # T6 truth-first: реальные проёмы через env (real-бенч acceptance_real.py / мост замера);
    # без SCENE_OPENINGS — прежние синтетические (детерминированные от номера сета)
    _ops = os.environ.get('SCENE_OPENINGS')
    if _ops and json.loads(_ops):
        openings_p = [_Op(**o) for o in json.loads(_ops)]
        radiators_p = [_Rad(**r) for r in json.loads(os.environ.get('SCENE_RADIATORS') or '[]')]
    else:
        # СТОРОНА ПЕТЕЛЬ — своя у каждой сцены (владелец 12.08: «в одном случае вправо,
        # в другом влево»). Детерминированно от номера сета: набор не должен «плыть».
        openings_p = [_Op(kind='door', wall='south', offset_cm=DOOR_OFF, width_cm=DOOR_W,
                          swing_cm=92, hinge=('left' if n % 2 else 'right')),
                      _Op(kind='window', wall='east', offset_cm=WIN_OFF, width_cm=WIN_W,
                          sill_cm=80)]
        radiators_p = [_Rad(wall='east', offset_cm=WIN_OFF, width_cm=WIN_W, depth_cm=15)]
    room_p = _Rm(width_cm=RW, depth_cm=RD, band=BAND,
                 contour=(json.loads(_ctr) if _ctr else None),
                 openings=openings_p, radiators=radiators_p)
    its = []
    for role, (w, d) in FLOOR:
        src = items.get(role) or {}
        # beam решает СРАЗУ по каталожным габаритам (фолбэк — типовые): пост-фикс «типовые →
        # каталожные» после солвера выводил зону из шкал — с составами R3 столик мельче типового
        # уезжал на 58–59 см при вилке 33–47, и 41 сет падал (перегон 2026-08-07)
        rw = float(src.get('w') or src.get('dia') or w)
        rd = float(src.get('d') or src.get('dia') or d)
        its.append(_It(role=role, w_cm=rw, d_cm=rd, h_cm=(src.get('h') or None),
                       name=(src.get('name') or None),
                       corner=(role == 'диван' and CORNER),
                       corner_section_cm=(OCC or {}).get('corner_sofa_section_depth_cm', 95),
                       # LAF/RAF (веб 08.08): сторона угла — свойство SKU; «левый/правый»
                       # в названии фиксирует зеркало, иначе солвер пробует оба (G1)
                       corner_left=bool(_re.search(r'лев', (src.get('name') or '').lower())),
                       corner_side_fixed=bool(_re.search(r'\bлев|\bправ',
                                              (src.get('name') or '').lower()))))
    lay = None
    if ENGINE == 'llm':
        # LLM играет дизайнера (выбирает схему), геометрия притягивает и проверяет;
        # не ответила или её вариант не чинится — молча падаем на beam (план llm-layout-planner)
        from planner.llm_planner import plan as _llm_plan, hard_count as _hc
        lay, scheme = _llm_plan(room_p, its)
        if lay is not None:
            print(f"схема LLM: {scheme}", flush=True)
            if _hc(lay) or lay.unplaced:
                print(f"  LLM-вариант с нарушениями ({_hc(lay)}) — фолбэк на beam", flush=True)
                lay = None
    if lay is None:
        if ENGINE == 'zoned':
            # Z3/Z5: зонный солвер — группа по полезной площади, лексо-отбор (A/B со старым)
            from planner.zones import solve_zoned
            outs, _gid = solve_zoned(room_p, its, top_k=1)
            print(f"зонная группа: {_gid}", flush=True)
        else:
            outs = _solve(room_p, its, top_k=1)
        if not outs:
            return {}, [r for r, _ in FLOOR], []
        lay = outs[0]
    # Зрячая метрика (А3): «нет hard-нарушений» ≠ «логично» — глупая-но-валидная схема раньше
    # проходила как OK. Наружу отдаём score-термы и soft-нарушения, solver_check их собирает.
    from planner.score import score_layout as _score
    _sc = _score(room_p, lay.placements)
    print('SOFT ' + json.dumps({
        'terms': {k: v for k, v in sorted(_sc.terms.items()) if abs(v) > 0.01},
        'soft_violations': [f'{v.code}:{",".join(v.roles)}' for v in lay.violations
                            if v.severity.name != 'HARD'],
    }, ensure_ascii=False), flush=True)
    # D4 (вердикт владельца set84): мьютекс = «ОДИН носитель ТВ», а не «ноль» — если
    # стенка не встала, а тумбу мы исключили, пере-решаем с тумбой (меньший носитель)
    _pr = {p.role for p in lay.placements}
    if _TV_STAND_BACKUP is not None and 'стенка' not in _pr and 'тв-тумба' not in _pr:
        print('D4: стенка не встала — пере-решение с тв-тумбой как носителем', flush=True)
        its2 = [i for i in its if i.role != 'стенка']
        _w2, _d2 = _TV_STAND_BACKUP
        _src2 = items.get('тв-тумба') or {}
        its2.append(_It(role='тв-тумба', w_cm=float(_src2.get('w') or _w2),
                        d_cm=float(_src2.get('d') or _d2), h_cm=(_src2.get('h') or None),
                        name=(_src2.get('name') or None)))
        if ENGINE == 'zoned':
            outs2, _g2 = solve_zoned(room_p, its2, top_k=1)
        else:
            outs2 = _solve(room_p, its2, top_k=1)
        def _seats(l):
            return sum(1 for p in l.placements if p.role.split(' ')[0] in ('кресло', 'диван'))
        if outs2 and 'тв-тумба' in {p.role for p in outs2[0].placements} \
                and _seats(outs2[0]) >= _seats(lay):
            lay = outs2[0]
            FLOOR.append(('тв-тумба', _TV_STAND_BACKUP))   # экспорт берёт габариты из FLOOR
        elif outs2 and 'тв-тумба' in {p.role for p in outs2[0].placements}:
            # носитель против посадки: ещё одна попытка (beam недетерминирован по веткам),
            # затем выбираем вариант с носителем, если посадка не хуже более чем на 1
            if ENGINE == 'zoned':
                outs3, _g3 = solve_zoned(room_p, its2, top_k=3)
            else:
                outs3 = _solve(room_p, its2, top_k=3)
            best2 = max([o for o in (outs3 or []) if 'тв-тумба' in {p.role for p in o.placements}]
                        or outs2, key=_seats)
            if _seats(best2) >= _seats(lay) - 1:
                # медиа-гостиная БЕЗ носителя ТВ хуже, чем минус одно кресло
                if _seats(best2) < _seats(lay):
                    print(f'D4: носитель принят ценой 1 места ({_seats(best2)}<{_seats(lay)})',
                          flush=True)
                lay = best2
                FLOOR.append(('тв-тумба', _TV_STAND_BACKUP))
            else:
                print(f'D4: с тумбой посадка хуже ({_seats(best2)}<{_seats(lay)}) — '
                      'оставляем вариант без носителя, дефицит в лог', flush=True)
    placed = {p.role: ((p.x, p.y), int(p.rot) % 360, tuple(_fp(p).exterior.coords[:]), 1)
              for p in lay.placements}
    # ПРОСЛЕЖИВАЕМОСТЬ ШАБЛОНА (ADR template-integrity): каким паспортом схемы
    # поставлен каждый предмет — в артефакт, отчёт и галерею
    global TPL_BY_ROLE
    TPL_BY_ROLE = {p.role: (p.tpl_id, p.tpl_version) for p in lay.placements}
    _no_tpl = sorted(r for r, (t, _) in TPL_BY_ROLE.items() if not t)
    if _no_tpl and os.environ.get('LAYOUT_ONLY_TEMPLATES', '1') == '1':
        print('NOTPL ' + json.dumps(_no_tpl, ensure_ascii=False), flush=True)
    missing = list(lay.unplaced)
    # Рефери 08.08 (Q1/3.3): дроп ярусом — не провал, но и не молчание (no silent caps)
    if lay.skipped_optional:
        # МОДЕЛЬ (решение владельца 12.08): СЕТ — банк кандидатов, РАССТАНОВКА —
        # один вариант планировки. Предметы банка, не вошедшие в эту расстановку,
        # это НОРМА (для другой квартиры выбор будет другим), а не ошибка.
        # Смета строится по факту расстановки (`placed`), не по банку.
        print('UNUSED ' + json.dumps(sorted(lay.skipped_optional), ensure_ascii=False),
              flush=True)
        print('SURPLUS ' + json.dumps(sorted(lay.skipped_optional), ensure_ascii=False),
              flush=True)   # legacy-имя, уберём после перехода отчётов
        print('SKIPPED ' + json.dumps(sorted(lay.skipped_optional), ensure_ascii=False),
              flush=True)   # legacy-строка для прежних потребителей отчёта
    # ОДНА линейка (2026-08-07): вердикты планнера. Scout-чеки поверх мерили Г-диван другой
    # методикой и спорили с ядром (41 ложный провал «диван↔столик» на перегоне) — они остаются
    # только у DFS, который планнером не проверяется.
    pl = [(f"{v.code}[{','.join(v.roles)}]", False, v.value if v.value is not None else '')
          for v in lay.violations if v.severity.name == 'HARD']
    return placed, missing, (pl or [('planner: hard-чисто', True, '')])


_eng_arg = sys.argv[sys.argv.index('--engine') + 1] if '--engine' in sys.argv else None
# Дефолт — beam (А3, аудит 06.08): прод-ядро выигрывает у DFS 110+/122 против 107/126, но
# батчи коллажей/рендеров шли через дефолт и рендерили DFS — чинили beam, а ляпы были DFS.
# Боевой дефолт — ZONED (приёмка 08.08 на 252 фикс-сценах, оба движка на одних Z4-составах:
# zoned 239/252 чистых против beam 119/252, ни одной сцены хуже; эркер/пилоны/трапеция
# 20-21/21 против 4-12/21). beam остаётся для A/B: --engine beam.
ENGINE = _eng_arg or os.environ.get('LAYOUT_ENGINE', 'zoned')   # zoned | beam | dfs | llm

# перебор сидов ПОСЛЕДОВАТЕЛЬНО с ранним выходом (чистый сид обычно первый-второй, max_duration=12);
# параллельность — на уровне СЕТОВ (render6.sh): внутренний ProcessPool на слабой VM ловил OOM
best=None
if ENGINE in ('beam', 'zoned', 'llm'):
    _pl, _ms, _ck = attempt_beam()
    best = (sum(1 for _, ok, _ in _ck if not ok) + len(_ms), ENGINE, _pl, _ms, _ck)
for seed in ([] if ENGINE in ('beam', 'llm', 'zoned') else (7,11,23,42,77,101)):
    placed,missing,checks=attempt(seed)
    nf=sum(1 for _,ok,_ in checks if not ok)+len(missing)
    if best is None or nf<best[0]: best=(nf,seed,placed,missing,checks)
    if nf==0: break
nf,seed,placed,missing,checks=best
print(f"seed {seed}, нарушений {nf}")

out={r:{'x':placed[r][0][0],'z':placed[r][0][1],'rot':placed[r][1],
        'w':dict(FLOOR)[r][0],'d':dict(FLOOR)[r][1]} for r in placed}
# ПРЕДМЕТ НЕ ТОРЧИТ ЗА СТЕНУ — только для DFS: он решает по типовым габаритам, и каталожные
# вылезали за стену (владелец, 2026-08-05). Beam с 2026-08-07 решает СРАЗУ по каталожным
# (check_boundary hard) — пост-прижим ему не нужен и ВРЕДЕН: сдвиг после валидации выводил
# зону из шкал, и вторая линейка (scout-чек) спорила с первой (планнером) — 41 ложный провал.
if ENGINE not in ('beam', 'llm'):
    for _r, _v in out.items():
        _w, _d = (_v['w'], _v['d']) if int(_v['rot']) % 180 == 0 else (_v['d'], _v['w'])
        _v['x'] = min(max(_v['x'], _w / 2), RW - _w / 2)
        _v['z'] = min(max(_v['z'], _d / 2), RD - _d / 2)

# Г-ДИВАН ДОЛЖЕН ДОЙТИ ДО СЦЕНЫ. Солвер ставит его настоящим шестиугольником, но в раскладку
# уезжали только x/z/w/d — сцена и план рисовали прямоугольник, который вдобавок стоял в 45 см
# от стены (там, где у настоящего дивана выступает плечо). Владелец 2026-08-05: «или буквой Г,
# или не делать». Передаём признак, глубину с плечом и центр ГАБАРИТНОГО прямоугольника.
if CORNER and 'диван' in out:
    # P0.2 (ревью рефери 08.08, set66): единственный canonical footprint — тот, которым РЕШАЛ
    # солвер. Прежний код мутировал экспорт (d→max(150) «с плечом», corner_left=True хардкод,
    # пересчёт Z): при SKU без глубины солвер решал с d=95 ВАЛИДНО, а реконструкция
    # scene_build с d=150 уезжала за стену (−22.5 см, OUT_OF_ROOM). Экспортируем solve-time
    # параметры без мутаций; зеркальность — сверкой IoU с фактическим полигоном солвера.
    _sec = (OCC or {}).get('corner_sofa_section_depth_cm', 95)
    _dd = dict(FLOOR)['диван'][1]                 # глубина, которой решал солвер
    _cs = placed['диван'][2]                      # шестиугольник от солвера
    out['диван'].update({'corner': True, 'section': _sec, 'd': _dd})
    from shapely.geometry import Polygon as _Poly
    from planner.geometry import footprint as _fpc
    from planner.models import Item as _Itc, Placement as _Plc
    _sol = _Poly(_cs)
    _best = (0.0, False)
    for _cl in (True, False):
        _itc = _Itc(role='диван', w_cm=out['диван']['w'], d_cm=_dd, h_cm=85,
                    corner=True, corner_section_cm=_sec, corner_left=_cl)
        _fpp = _fpc(_Plc(role='диван', x=out['диван']['x'], y=out['диван']['z'],
                         rot=out['диван']['rot'], item=_itc))
        _iou = _sol.intersection(_fpp).area / max(_sol.union(_fpp).area, 1e-6)
        if _iou > _best[0]:
            _best = (_iou, _cl)
    out['диван']['corner_left'] = _best[1]
    if _best[0] < 0.98:
        print(f'CANONICAL-FOOTPRINT WARN: реконструкция Г-дивана IoU={_best[0]:.2f} — '
              'экспорт расходится с полигоном солвера', flush=True)
# габариты И проёмы — рендеру и компилятору сцены: без проёмов генератор придумывает свои
# двери/окна, и кадр перестаёт совпадать с планом (поймано 2026-08-04)
_ops_env=os.environ.get('SCENE_OPENINGS')
_room_ops=(json.loads(_ops_env) if (_ops_env and json.loads(_ops_env)) else [
    {'kind':'door','wall':'south','offset_cm':DOOR_OFF,'width_cm':DOOR_W,'swing_cm':92},
    {'kind':'window','wall':'east','offset_cm':WIN_OFF,'width_cm':WIN_W,'sill_cm':80}])
# контур комнаты — в артефакт: план обязан рисовать НАСТОЯЩИЕ стены, а не bbox
# (замечание владельца 12.08: «диван заходит за границы комнаты» — это врал чертёж)
out['_templates']={r:{'id':t,'version':v} for r,(t,v) in (globals().get('TPL_BY_ROLE') or {}).items()}
# S3 (small-room-mode): «ТВ адаптируется к комнате легче, чем планировка к ТВ» — если
# фактическая дистанция посадка↔носитель меньше цели RTINGS, пишем рекомендацию меньшей
# диагонали в артефакт (для сметы/подбора); геометрию НЕ ломаем
try:
    _b=next((r for r in ('стенка','тв-тумба') if r in placed), None)
    if _b and 'диван' in placed:
        import math as _m3
        _sx,_sz=placed['диван'][0]; _bx,_bz=placed[_b][0]
        _dist=_m3.hypot(_bx-_sx,_bz-_sz)
        _diag_max=_dist/1.6/2.54          # RTINGS: дюймы диагонали из дистанции
        _bw=dict(FLOOR).get(_b,(120,40))[0]
        _diag_fit=(_bw-20)/2.54
        if _diag_max<_diag_fit-5:
            out['_tv_advice']={'max_diag_inch':round(_diag_max),
                'why':'дистанция посадки меньше цели RTINGS для носителя — рекомендован меньший экран'}
except Exception:
    pass
out['_set_hash']=hashlib.sha1(json.dumps(items,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:12]
out['_room']={'w':RW,'d':RD,'m2':round(RW*RD/10_000,1),'openings':_room_ops,
              'contour':(json.loads(os.environ.get('SCENE_CONTOUR')) 
                         if os.environ.get('SCENE_CONTOUR') else None)}
# L4 (MASTER-layout-v5): топология-сигнатура — семантическая схема раскладки в артефакт и лог
from topo_sig import topo_key, topo_signature
out['_topo'] = topo_signature(out)
# ЗАПОЛНЕННОСТЬ (правило владельца 11.08, коридор 30–45%): доля пола под мебелью,
# пристенное — за половину футпринта (веб-свод); ковёр как подложка не считается
try:
    from planner.zones import WALL_HUGGING_ROLES as _WH, _base as _bs
    _fill = 0.0
    for _r, (_c, _rot, _poly, _q) in placed.items():
        if _r in ('ковёр', 'дверь', 'окно'):
            continue
        from shapely.geometry import Polygon as _P
        _fill += _P(_poly).area / 10_000 * (0.5 if _bs(_r) in _WH else 1.0)
    out['_fill_pct'] = round(_fill / (RW * RD / 10_000) * 100, 1)
    print(f'FILL {out["_fill_pct"]}', flush=True)
    # доля банка сета, задействованная в ЭТОЙ расстановке
    _bank = len(FLOOR)
    _used = len([r for r in placed if r not in ('дверь', 'окно')])
    out['_used_of_bank'] = f'{_used}/{_bank}'
    print(f'USED {_used}/{_bank}', flush=True)
except Exception as _e:
    pass
print('TOPO ' + topo_key(out['_topo']), flush=True)
# W2.4 (kb-rules-merge): аннотация диагонали ТВ от фактической дистанции просмотра —
# подсказка подбору ТВ в смету/сет (дистанция >3 м → ТВ от 55″), числа из tv._cfg
_bearer = next((r for r in ('стенка', 'тв-тумба') if r in out), None)
if _bearer and 'диван' in out:
    import math as _m
    from planner.tv import _cfg as _tvcfg
    _s, _b = out['диван'], out[_bearer]
    _dist = max(0.0, _m.hypot(_s['x'] - _b['x'], _s['z'] - _b['z'])
                - (_s['d'] + _b['d']) / 2)
    _c = _tvcfg()
    out['_tv'] = {'bearer': _bearer, 'viewing_distance_cm': round(_dist),
                  'diag_min_in': round(_dist / _c['diag_range'][1] / 2.54),
                  'diag_preferred_in': round(_dist / _c['preferred'] / 2.54)}
    if _dist > 300:
        out['_tv']['note'] = 'дистанция просмотра >3 м — ТВ от 55″'
_sfx=os.environ.get('LAYOUT_SUFFIX','')
json.dump(out,open(os.path.join(HERE,f'{TAG}{n}-layout{_sfx}.json'),'w'),ensure_ascii=False,indent=1)

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
# СНАЧАЛА ковёр (подложка), потом мебель — иначе ковёр закрашивает диван
_order=sorted(placed.items(), key=lambda kv: 0 if kv[0].split(' ')[0]=='ковёр' else 1)
for r,v in _order:
    pts=[T(x,z) for x,z in v[2]]
    dr.polygon(pts,outline=(40,40,40),fill=cols.get(r,(200,200,200)))
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
    _ITEM_BOXES.append((min(xs),min(ys),max(xs),max(ys)))
# подписи — вторым проходом, поверх всей мебели и в обход чужих блоков
for r,v in _order:
    cx,cz=v[0]; _w,_d=dict(FLOOR).get(r,(0,0))
    _lbl=f"{r} {int(_w)}x{int(_d)} см, {v[1]}°"
    _tx,_ty=T(cx,cz)
    _put_label(dr,_tx,_ty-8,_lbl,F_ITEM)
    # стрелка «куда смотрит»: rot 180 = к южной стене (к камере вида A)
    import math as _m
    _a=_m.radians(v[1]); _fx,_fz=_m.sin(_a),-_m.cos(_a)
    dr.line([_tx,_ty,_tx+_fx*30,_ty+_fz*30],fill=(15,15,15),width=2)
img.save(os.path.join(HERE,f'{TAG}{n}-layout{_sfx}.png'))
print("placed:",", ".join(f"{r}@({v[0][0]},{v[0][1]})r{v[1]}" for r,v in placed.items()))
if missing: print("НЕ размещены:",missing)
for name,ok,val in checks: print(("OK " if ok else "FAIL "),name,val)
