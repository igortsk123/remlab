"""T-171/steny-ten · замер «до → после» на 194 листах с глазом, в тени (ничего не включает). python -I steny_ten.py [--only id,id] [--variant centre|inner] [--out res]
Читает inventory.json (опись), сохранённые ответы (plan-clean.json), walls.csv и fit.json «до». Нейросеть не зовёт. Результат: res-<variant>/<лист>/{report.json,plan-after.json,before/,after/,pair.png} и tablica-<variant>.tsv."""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ORIG = os.environ.get('STENY_ORIG', '/home/pakar/remlab-logs/t171-steny-ten')      # исходная папка замера (опись, ответы): только чтение; в CI её нет
sys.path.insert(0, HERE)
import steny_core as SC  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402

PL, VC, OV, vf = SC.PL, SC.VC, SC.OV, SC.vf
CLASSES = '12'
MASK_WORDS = False    # КРУГ 4в (3): ключ --mask-words; слова OCR вычитаются из маски чернил
PARALLEL = False      # КРУГ 4: ключ --parallel (перенос без поворота, соосные соседи целиком); по умолчанию ВЫКЛ


def sheet_sources(e):
    """(каталог наложения «до», картинка листа): для листов, где «до» мерили по входу 4c, — overlay-4c и sheet-4c.png."""
    ov = json.load(open(e['ov'], encoding='utf-8')) if e['ov'] else {}
    if ov.get('вход') == '4c' and os.path.exists(e['dir'] + '/overlay-4c/walls.csv') and os.path.exists(e['dir'] + '/overlay/sheet-4c.png'):
        return e['dir'] + '/overlay-4c', e['dir'] + '/overlay/sheet-4c.png', ov
    return e['dir'] + '/overlay', e['sheet'], ov


def printed_for(e, plan0, k, fit):
    lab = e.get('labels')
    PL.V = lab[1] if lab else PL.V
    sid = e['лист']
    try:
        pm = PL.printed_for_plan(sid, plan0, k, fit)
    except Exception as ex:   # noqa: BLE001  (нет файла подписей и т.п.: цифр нет, перенос не применяем — флажок)
        return {}, 'паспорт не прочитан: %s: %s' % (type(ex).__name__, str(ex)[:80])
    return pm


def pair_png(b, a, out, cap_b, cap_a):
    ib, ia = cv2.imread(b), cv2.imread(a)
    if ib is None or ia is None:
        return False
    h = min(ib.shape[0], ia.shape[0])
    ib, ia = ib[:h], ia[:h]
    for im, cap in ((ib, cap_b), (ia, cap_a)):
        cv2.rectangle(im, (0, 0), (im.shape[1], 26), (255, 255, 255), -1)
        cv2.putText(im, cap, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.imwrite(out, np.hstack([ib, ia]))
    return True


def one(e, variant, outroot, cfg):
    sid = e['лист']
    odir, sheet, ov_saved = sheet_sources(e)
    rows = SC.rows_of(odir + '/walls.csv')
    fit = json.load(open(odir + '/fit.json', encoding='utf-8'))
    plan0 = json.load(open(e['plan'], encoding='utf-8'))
    ws, k = SC.plan_walls(plan0)
    res = {'лист': sid, 'глаз': e['глаз'], 'суть': e['суть'], 'исход': e['исход'], 'набор': e['набор'], 'вариант': variant}
    if SC.WHOLE_MISS:
        miss = SC.whole_plan_miss(fit)
        if miss:
            res['кандидатов'] = {'класс1': 0, 'класс2': 0}
            res['итог'] = 'нет кандидатов: весь план мимо — стены не двигаем'
            res['флажки'] = [{'стена': '*', 'класс': None, 'причина': miss}]
            return res
    g = vf.load_gray(sheet)
    ink = vf.ink_mask(g)
    if MASK_WORDS and any(r['класс'] == 'сдвинута' and r['сдвиг_dx_см'] != '' and (SC.fnum(r['сдвиг_см']) or 0.0) >= SC.MIN_SHIFT_CM for r in rows.values()):   # OCR только листам, где есть кандидаты класса 1
        # КРУГ 4в (3), Fable: слова/цифры размеров OCR вычитаются из маски чернил до счёта (rab-10, 4v/maska_slov.py; стена, на которую легла рамка слова, защищена длинным штрихом)
        sys.path.insert(0, HERE + '/4v')
        import maska_slov as MS  # noqa: E402
        mst = {}
        ink, _words = MS.ink_bez_slov(ink, sheet, stats=mst)
        res['маска_слов'] = mst
    rej1 = []
    dt = cv2.distanceTransform((~ink).astype(np.uint8), cv2.DIST_L2, 3) if SC.EVIDENCE else None
    if SC.PROFILE:
        SC.SHEET_GRAY, SC.SHEET_BLUR = g, cv2.blur(g, (5, 5)).astype(np.float32)      # КРУГ 4в: защита «старое место внутри заливки толстой стены»
    c1 = SC.cands_class1(plan0, rows, dt=dt, fit=fit, rej=rej1)
    res['класс1_отказы_доказательства'] = rej1
    res['класс1_доказательство'] = {c['id']: c['доказательство'] for c in c1 if c.get('доказательство')}
    c2, info2 = SC.cands_class2(plan0, rows, fit, ink, None)
    for c in c2:
        c['d'] = SC.class2_vec(c, variant)
    res['кандидатов'] = {'класс1': len(c1), 'класс2': len(c2)}
    res['класс2_отсев'] = info2[:8]
    cand = (c1 if '1' in CLASSES else []) + (c2 if '2' in CLASSES else [])
    printed, pstat = printed_for(e, plan0, k, fit)
    res['цифры'] = pstat
    res['цифр_комнат'] = len(printed or {})
    flags1 = [{'стена': r['стена'], 'класс': 1, 'dx_см': r['dx_см'], 'dy_см': r['dy_см'], 'причина': r['причина']} for r in rej1 if r.get('флаг')]
    if not cand:
        res['итог'] = 'нет кандидатов'
        res['флажки'] = flags1
        return res
    cinfo = {}
    plan1, moved, cancelled, flags, rooms = SC.correct(plan0, k, cand, printed, pstat, rows=rows, parallel=PARALLEL, info=cinfo)
    res['соседи_целиком'] = cinfo.get('соседи', {})
    res['разрывы_контура'] = cinfo.get('разрывы', [])
    res['соседи_стыки'] = cinfo.get('соседи_стыки')           # круг Б, Fable: скольжение каждого стыка соседа, см (рост длины со знаком), увод поперёк, перенос
    res['увод_соседей_макс_см'] = cinfo.get('увод_соседей_макс_см')
    res['схлопнуто'] = cinfo.get('схлопнуто')
    res['частичная_отмена'] = cinfo.get('частичная_отмена')
    res['замкнутость'] = cinfo.get('замкнутость')           # рабочий 10, круг Б 4в: проверка замкнутости комнат (ключ --hold-neighbors)
    res['соседи_увод'] = cinfo.get('соседи_увод', [])     # rot (град) и увод (см) каждого соседа, чей конец сдвинулся
    res['площадь_строки'] = cinfo.get('площадь_строки', [])      # КРУГ 4в (4): комнаты, где после переноса площадь дальше от подписи (при --area-flag — без отмены)
    res['судья_площади'] = SC.judge_area(plan0, plan1, k, printed, sid)
    res['перенесено'] = [{'стена': c['id'], 'класс': c['класс'], 'вид': c.get('вид'), 'dx_см': c['d'][0], 'dy_см': c['d'][1], 'сдвиг_см': round(float(np.hypot(*c['d'])), 1)} for c in moved]
    res['отменено'] = cancelled
    res['флажки'] = flags + flags1
    res['комнаты'] = {rid: {'имя': v[0], 'цифра': round(v[1], 2), 'до': round(v[2], 2), 'после': round(v[3], 2)} for rid, v in rooms.items()}
    if not moved:
        if SC.HOLD_NEIGHBORS:      # круг Б: «план побайтно прежний» — план до и после выгружены одним способом, сверка md5 и равенство с исходным файлом
            import hashlib
            dd = '%s/%s' % (outroot, sid)
            os.makedirs(dd, exist_ok=True)
            s0, s1 = json.dumps(plan0, ensure_ascii=False, indent=1), json.dumps(plan1, ensure_ascii=False, indent=1)
            open(dd + '/plan-do.json', 'w', encoding='utf-8').write(s0)
            open(dd + '/plan-posle-otmeny.json', 'w', encoding='utf-8').write(s1)
            res['план_до_md5'], res['план_после_md5'] = hashlib.md5(s0.encode('utf-8')).hexdigest(), hashlib.md5(s1.encode('utf-8')).hexdigest()
            res['план_байты_равны'] = s0 == s1
            res['план_равен_исходному_файлу'] = plan1 == json.load(open(e['plan'], encoding='utf-8'))
            json.dump(res, open(dd + '/report.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        res['итог'] = 'ничего не перенесено (только флажки/отмены)'
        return res
    d = '%s/%s' % (outroot, sid)
    os.makedirs(d, exist_ok=True)
    json.dump(plan1, open(d + '/plan-after.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    mb, cb = SC.measure_frozen(e['plan'], sheet, d + '/before', fit, cfg)
    ma, ca = SC.measure_frozen(d + '/plan-after.json', sheet, d + '/after', fit, cfg)
    keys = ('overlay_status', 'на_линии', 'покрыто', 'доля_точек_3px', 'лишнее_м', 'пропущено_м')
    res['до'] = {k_: cb.get(k_) for k_ in keys}
    res['после'] = {k_: ca.get(k_) for k_ in keys}
    res['до_сохранённое'] = {k_: ov_saved.get(k_) for k_ in keys}
    pair_png(d + '/before/overlay.png', d + '/after/overlay.png', d + '/pair.png', '%s ДО (%s)' % (sid, res['до']['overlay_status']), 'ПОСЛЕ (%s) перенесено стен: %d' % (res['после']['overlay_status'], len(moved)))
    res['итог'] = 'перенесено %d' % len(moved)
    json.dump(res, open(d + '/report.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--variant', default='centre', choices=('centre', 'inner'))
    ap.add_argument('--out', default='')
    ap.add_argument('--inv', default='inventory.json', help='опись листов (inventory.json — 194 листа первого замера; inventory-podbor.json — подбор эталона, 228)')
    ap.add_argument('--classes', default='12', help='какие классы переносим: 1, 2 или 12 (кандидаты считаются всегда оба)')
    ap.add_argument('--parallel', action='store_true', help='КРУГ 4: перенос без поворота — соосные соседи переносятся целиком')
    ap.add_argument('--evidence', action='store_true', help='КРУГ 4: ворота доказательства для класса 1 (доля на чернилах на цели переноса, прирост ≥0,30, на старом месте <0,50)')
    ap.add_argument('--mask-words', dest='mask_words', action='store_true', help='КРУГ 4в (3): слова OCR (цифры размеров) вычитаются из маски чернил до счёта (4v/maska_slov.py, rab-10); без кэша рамок — OCR листа')
    ap.add_argument('--area-flag', dest='area_flag', action='store_true', help='КРУГ 4в (4), Fable otvet-46: отмены по площади нет — вместо неё строка в отчёт (res[площадь_строки]); флажком не считается')
    ap.add_argument('--profile', action='store_true', help='КРУГ 4в (2): ворота «цель там, где линия» (профиль поперёк стены ±40 см) вместо порога 0,80; включает --evidence')
    ap.add_argument('--nodigit-flag', dest='nodigit_flag', action='store_true', help='КРУГ 4в, Fable шаг 3: комната без цифры не блокирует перенос — вместо блока флажок «площадь не проверена»')
    ap.add_argument('--old-on-ink', dest='old_on_ink', action='store_true', help='КРУГ 4в: на старом месте чернил ≥ 0,448 (как у верных по глазу) — «неоднозначно», флажок, без переноса (только с --profile)')
    ap.add_argument('--hold-neighbors', dest='hold_neighbors', action='store_true', help='рабочий 10, круг Б 4в: перенос БЕЗ увода соседей — их концы держатся на своей линии, стык переносимой подгоняется; проверка замкнутости комнат обязательна')
    ap.add_argument('--neighbor-drift', dest='neighbor_drift', action='store_true', help='рабочий 6, Fable 28.11: у соседа мерка — увод конца поперёк его линии > 5 см (вместо поворота >2°); отмена «сосед <id> уводится на N см»')
    ap.add_argument('--whole-miss', dest='whole_miss', action='store_true', help='КРУГ 4: «весь план мимо» (доля ≤3 px <0,40 или остаток >7 px) — стены не двигать, флажок')
    a = ap.parse_args()
    global CLASSES, PARALLEL, MASK_WORDS
    CLASSES = a.classes
    MASK_WORDS = a.mask_words
    PARALLEL = a.parallel or SC.PARALLEL
    SC.EVIDENCE = a.evidence or SC.EVIDENCE
    SC.AREA_FLAG_ONLY = a.area_flag or SC.AREA_FLAG_ONLY
    SC.NODIGIT_FLAG = a.nodigit_flag or SC.NODIGIT_FLAG
    SC.PR_OLD_ON_INK = a.old_on_ink or SC.PR_OLD_ON_INK
    SC.PROFILE = a.profile or SC.PROFILE
    if SC.PROFILE:
        SC.EVIDENCE = True      # профиль — это вид ворот доказательства
    SC.WHOLE_MISS = a.whole_miss or SC.WHOLE_MISS
    SC.NEIGHBOR_DRIFT = a.neighbor_drift or SC.NEIGHBOR_DRIFT
    SC.HOLD_NEIGHBORS = a.hold_neighbors or SC.HOLD_NEIGHBORS
    inv = json.load(open(('%s/' % ORIG) + a.inv, encoding='utf-8'))
    if a.only:
        ids = set(a.only.split(','))
        inv = [e for e in inv if e['лист'] in ids]
    out = a.out or '%s/res-%s%s' % (HERE, a.variant, '' if a.classes == '12' else '-k' + a.classes)
    os.makedirs(out, exist_ok=True)
    cfg = OV.load_cfg()
    allr = []
    for i, e in enumerate(inv):
        try:
            r = one(e, a.variant, out, cfg)
        except Exception as ex:   # noqa: BLE001  (сбой листа не прячем: пишется в строку и в счётчик)
            r = {'лист': e['лист'], 'глаз': e['глаз'], 'итог': 'СБОЙ: %s: %s' % (type(ex).__name__, str(ex)[:200])}
        allr.append(r)
        print(i + 1, len(inv), r['лист'], r.get('итог'), r.get('кандидатов'), flush=True)
    json.dump(allr, open('%s/all.json' % out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
