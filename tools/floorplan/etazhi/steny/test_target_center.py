"""T-171 круг Б-3 4в (rab-10, 28.11, Fable: «выбор цели у двойной линии» и «сдвиг внутри полосы»): центрирование цели по плато профиля, target_center.plateau_center — чистая функция, годится для CI.
Ключ --center-target в steny_core ВЫКЛ по умолчанию.
(1) синтетика: двойная линия, цель в центре → добавка 0; цель села на одну из двух линий (плато несимметрично) → центр плато; чернила везде / пика нет / цель вне плато → None;
(2) РЕАЛЬНЫЕ профили пяти стен трёх листов «хуже» слепых пар rab-2 (fixtures/steny/profili-hudshie3.json): kazan-14726759 w_log_top/w_log_bottom и kazan-12621608 w11 стоят в центре плато (|добавка| < 2 см = 1,3 px) —
    двойная линия там НЕ причина: цель по центру пары; kazan-14835363 w16 стоит на краю плато — центр на 6 см по нормали (правка «внутри полосы»);
(3) −контроль: порог плато 0,5 вместо 0,75 теряет w16 (плато упирается в край окна → None) — тест на w16 красный.
Запуск: python tools/floorplan/etazhi/steny/test_target_center.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import target_center as TC  # noqa: E402

MIN_CM, MAX_CM = 2.0, 8.0      # как CENTER_MIN_CM / CENTER_MAX_CM в steny_core
RES = []


def check(name, cond, extra=''):
    RES.append((name, bool(cond)))
    print('%s  %s%s' % ('OK  ' if cond else 'FAIL', name, (' — ' + str(extra)) if (extra and not cond) else ''))


def prof(lo, hi, base=0.1, top=1.0):
    offs = [float(o) for o in range(-40, 41)]
    return offs, [top if lo <= o <= hi else base for o in offs]


def synthetic():
    offs, P = prof(-9, 9)
    r = TC.plateau_center(offs, P)
    check('(1) двойная линия, цель в центре пары → центр 0', r and r['center'] == 0.0, r)
    offs, P = prof(-4, 14)
    r = TC.plateau_center(offs, P)
    check('(1) цель села на одну из двух линий (плато −4…+14) → центр +5', r and r['center'] == 5.0, r)
    check('(1) чернила везде (плато упирается в край окна) → None', TC.plateau_center(*prof(-40, 40)) is None)
    check('(1) пика нет (max P < 0,3) → None', TC.plateau_center(*prof(-9, 9, base=0.05, top=0.2)) is None)
    offs, P = prof(10, 25)
    check('(1) цель вне плато (P(0) ниже порога) → None', TC.plateau_center(offs, P) is None)
    check('(1) пустые данные → None', TC.plateau_center([], []) is None)


def real():
    fx = json.load(open(os.path.join(HERE, '..', 'fixtures', 'steny', 'profili-hudshie3.json'), encoding='utf-8'))['стены']
    for key in ('kazan-14726759:w_log_top', 'kazan-14726759:w_log_bottom', 'kazan-12621608:w11', 'kazan-14835363:w1'):
        r = TC.plateau_center(fx[key]['offs'], fx[key]['P'])
        check('(2) %s: цель в центре плато (|добавка| %.1f < %.0f см) — не двигаем' % (key, abs(r['center']), MIN_CM), r and abs(r['center']) < MIN_CM, r)
    r = TC.plateau_center(fx['kazan-14835363:w16']['offs'], fx['kazan-14835363:w16']['P'])
    check('(2) kazan-14835363:w16: цель на краю плато → центр −6 см (в пределах %.0f–%.0f см)' % (MIN_CM, MAX_CM), r and r['center'] == -6.0 and MIN_CM <= abs(r['center']) <= MAX_CM, r)
    r = TC.plateau_center(fx['kazan-14835363:w16']['offs'], fx['kazan-14835363:w16']['P'], frac=0.5)
    check('(3) −контроль: порог 0,5 → w16 теряется (None), утверждение (2) на нём было бы красным', r is None, r)


if __name__ == '__main__':
    synthetic()
    real()
    bad = [n for n, ok in RES if not ok]
    print('ИТОГ: %d проверок, красных %d' % (len(RES), len(bad)))
    sys.exit(1 if bad else 0)
