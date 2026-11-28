"""Окружение тестов test_4v_b*.py БЕЗ внешних данных (~/remlab-logs): всё из репо.
— модули чтения (vetka_fit, vetka_correct, passport_load, overlay_status + конфиг ворот) лежат в `steny/work/` (копии снимка 20261126-2234, sha256 — в `work/SHA256SUMS`);
— лист kazan-14726759 (экзамен 28.11) — маленькая фикстура `fixtures/steny/kazan-14726759/` (картинка листа, привязка, walls.csv, план «до», паспорт labels5, площадь из объявления, ответ прежнего 4в f).
entry() даёт запись описи (как inventory-*.json у рабочего) с путями в фикстуру; паспорт и площадь читаются из неё же (PL.V / PL.R)."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, '..', 'fixtures', 'steny')


def entry(sid='kazan-14726759'):
    import steny_ten as ST
    d = os.path.normpath(os.path.join(FIX, sid))
    ST.SC.PL.R = d      # площадь из объявления: <R>/ru-plans/<лист>/listing.json
    return {'лист': sid, 'набор': 'экзамен', 'исход': '', 'глаз': '', 'суть': '', 'тревога': '',
            'dir': d, 'plan': d + '/plan-clean.json', 'ov': d + '/overlay.json', 'sheet': d + '/plan.jpeg',
            'walls': d + '/overlay/walls.csv', 'fit': d + '/overlay/fit.json', 'guard': '', 'listing_dir': d + '/ru-plans/' + sid,
            'labels': ['labels5', d]}


def res_4vf_plan(sid='kazan-14726759'):
    """ответ прежнего 4в f (до круга Б) — план после правки с наклонённой w_top"""
    return os.path.normpath(os.path.join(FIX, sid, 'res-4vf-plan-after.json'))
