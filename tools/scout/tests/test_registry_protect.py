"""Реестр кадров не выкидывает кадры, которые показывает главная (T-20261107-17). Реестр полон (120), прежняя обрезка держала только
свежайшую запись пары (комната, стиль): ночной черновик того же стиля снимал защиту с фото нейросети. Теперь ночной прогрев кладёт
ключи показанных кадров (`pub-shots.json`), `draft_guard.registry_trim` их не трогает; счётчики — `shots-trim.json`.
Проверяем:
- сценарий «вариантов в 3 раза больше» (45 вместо 15), 5 ночей прогрева по 45 черновиков и 20 кадров посетителей в день: с защитой
  ни одно фото нейросети опубликованного состояния не пропало, прежнее правило теряет; реестр в пределе; счётчики точны;
- обязательные записи: пересечение правил без дублей, порядок сохранён, защищённых больше предела — остаются все, переполнение;
- старые записи без id — по ключу комната|стиль|время;
- `load_pub`: нет / битый / большой / старый (mtime) / мусорные ключи — защита только прежняя, статус;
- `trim_stats_update`: итоги монотонны, битый файл — новый epoch;
- `draft_service._registry_add` целиком: реестр и счётчики на диске, параллельная запись — целый JSON, ничего не потеряно.
    python3 tools/scout/tests/test_registry_protect.py"""
import json
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_registry_protect')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
from draft_guard import (PUB_MAX_AGE_SEC, PUB_MAX_KEYS, REGISTRY_MAX, load_pub, registry_trim, shot_key,  # noqa: E402
                         trim_stats_update)

BAD = []


def ok(cond, msg):
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond:
        BAD.append(msg)


ROOMS = ['living', 'bedroom-1', 'bedroom-2', 'hall', 'kids', 'kitchen', 'study', 'bedroom-3', 'guest']   # 9 × 5 = 45 вариантов
STYLES = ['сканди', 'современный', 'минимализм', 'лофт', 'джапанди']
_n = [0]


def rec(room, style, state, quality='draft', ts=None, no_id=False):
    _n[0] += 1
    r = {'style': style, 'stateId': state, 'quality': quality, 'ts': ts if ts is not None else _n[0], 'shots': [{'url': f'u{_n[0]}'}]}
    if room != 'living':
        r.update(room_id=room, variant_id=f'{room}-{style}')
    if not no_id:
        r['id'] = f'r{_n[0]:06d}'
    return r


def shown(data, pubstate):
    """Что показала бы главная (как `pubShot`: записи опубликованного состояния, фото нейросети первым) — ключ записи или None."""
    out = {}
    for (room, style), st in pubstate.items():
        fit = [r for r in data if (r.get('room_id') or 'living') == room and r['style'] == style and r['stateId'] == st]
        real = [r for r in fit if r['quality'] == 'realistic']
        pool = real or fit
        out[(room, style)] = (pool[-1]['quality'], shot_key(pool[-1])) if pool else None
    return out


def pub_keys(data, pubstate):
    """Что положит прогрев: последнее годное фото нейросети варианта, нет его — последняя годная запись."""
    return {v[1] for v in shown(data, pubstate).values() if v}


def trim_before(data, cap=REGISTRY_MAX, pub=None, stats=None):
    """Правило до T-17 (копия для контроля): свежайшая запись пары (комната, стиль), остальное — только по свежести."""
    seen, keep = set(), set()
    for i in range(len(data) - 1, -1, -1):
        k = ((data[i].get('room_id') or 'living'), data[i].get('style'))
        if k not in seen:
            seen.add(k)
            keep.add(i)
    rest = [i for i in range(len(data) - 1, -1, -1) if i not in keep][:max(0, cap - len(keep))]
    out_i = keep | set(rest)
    if stats is not None:
        gone = [r for i, r in enumerate(data) if i not in out_i]
        stats.update(dropped=len(gone), dropped_realistic=sum(1 for r in gone if r['quality'] == 'realistic'), overflow=0, protected=0)
    return [data[i] for i in sorted(out_i)] if len(data) > cap else data


def scenario(mode: str):
    """mode: list — новое правило со списком прогрева; nolist — новое правило, списка нет (missing/stale); before — правило до T-17."""
    protect, trim = mode == 'list', (trim_before if mode == 'before' else registry_trim)
    _n[0] = 0
    variants = [(r, s) for r in ROOMS for s in STYLES]
    pubstate = {v: f'pub-{v[0]}-{v[1]}' for v in variants}
    # старт: у каждого варианта — фото нейросети и черновик опубликованного состояния (старые), реестр добит старым мусором до предела
    data = []
    for (r, s) in variants:
        data.append(rec(r, s, pubstate[(r, s)], 'realistic'))
        data.append(rec(r, s, pubstate[(r, s)]))
    while len(data) < REGISTRY_MAX:
        data.append(rec(ROOMS[len(data) % 9], STYLES[len(data) % 5], f'old-{len(data)}', 'realistic' if len(data) % 7 == 0 else 'draft'))
    real0 = shown(data, pubstate)
    totals, prev = {'dropped': 0, 'dropped_realistic': 0}, None
    for night in range(5):
        pub = pub_keys(data, pubstate) if protect else None
        add = []
        for k in range(40):   # посетители: правленая расстановка — другое состояние того же стиля и комнаты, каждый второй с фото нейросети
            r, s = variants[(night * 40 + k) % len(variants)]
            add.append(rec(r, s, f'edit-{night}-{k}', 'realistic' if k % 2 else 'draft'))
        add += [rec(r, s, pubstate[(r, s)]) for (r, s) in variants]   # ночной прогрев: черновик каждого варианта
        for a in add:
            data.append(a)
            st = {}
            data = trim(data, pub=pub, stats=st)
            prev = trim_stats_update(prev, st, 'ok' if protect else 'missing', time.time())
            totals['dropped'] += st['dropped']
            totals['dropped_realistic'] += st['dropped_realistic']
            if len(data) > REGISTRY_MAX + st['overflow']:
                return None
    return real0, shown(data, pubstate), data, totals, prev


def main():
    print('сценарий «вариантов в 3 раза больше» (45), 5 ночей по 45 черновиков прогрева + 40 кадров посетителей (20 с фото нейросети):')

    def lost_of(r):
        return [v for v, x in r[0].items() if x and x[0] == 'realistic' and (r[1][v] is None or r[1][v][0] != 'realistic')]
    real0, after, data, tot, stats = res = scenario('list')
    lost = lost_of(res)
    ok(all(x and x[0] == 'realistic' for x in real0.values()), 'до: у всех 45 вариантов главная показывает фото нейросети')
    ok(not lost, f'с защитой: фото нейросети не потеряно ни у одного варианта (потеряно {len(lost)})')
    ok(len(data) <= REGISTRY_MAX, f'реестр в пределе ({len(data)} ≤ {REGISTRY_MAX})')
    ok(stats['protected_current'] == 45 and stats['overflow_current'] == 0, f'счётчик: защищено 45, переполнения нет ({stats})')
    ok(stats['dropped_total'] == tot['dropped'] == 5 * 85,
       f'счётчик: выкинуто = добавлено сверх предела (5 ночей × 85 = 425; {stats["dropped_total"]})')
    ok(stats['dropped_realistic_total'] == tot['dropped_realistic'] > 0,
       f'фото нейросети уходят только чужих состояний (правки посетителей, старое): {tot["dropped_realistic"]}')
    lost_nolist, lost_before = lost_of(scenario('nolist')), lost_of(scenario('before'))
    ok(len(lost_nolist) > 0, f'контроль: без списка прогрева (нет/старый файл) теряется у {len(lost_nolist)} из 45 — список нужен')
    ok(len(lost_before) >= len(lost_nolist) and len(lost_before) > 0,
       f'контроль: правило до T-17 теряет у {len(lost_before)} из 45 — дыра, которую закрываем')
    print(f'  сводка: защищено {stats["protected_current"]}, выкинуто {stats["dropped_total"]} (фото нейросети {stats["dropped_realistic_total"]})')

    print('обязательные записи:')
    _n[0] = 0
    d = [rec('living', 'сканди', 's1', 'realistic')] + [rec('living', 'сканди', f'x{i}') for i in range(10)]
    pk = {shot_key(d[0]), shot_key(d[-1])}   # пересечение: последняя (комната, стиль) — та же, что в списке
    st = {}
    tr = registry_trim(d, 3, pub=pk, stats=st)
    ok(tr[0] is d[0] and tr[-1] is d[-1] and len(tr) == 3, 'пересечение правил без дублей, порядок записей сохранён')
    ok(st['protected'] == 2 and st['dropped'] == 8 and st['overflow'] == 0, f'счётчики: защищено 2, выкинуто 8 ({st})')
    st = {}
    tr = registry_trim(d, 1, pub={shot_key(x) for x in d[:5]}, stats=st)
    ok(len(tr) == 6 and st['overflow'] == 5, f'защищённых больше предела — остаются все, переполнение 5 ({len(tr)}, {st})')
    d2 = [rec('living', 'лофт', 'a', 'realistic'), rec('living', 'лофт', 'b', 'draft'), rec('living', 'сканди', 'c', 'draft'),
          rec('living', 'сканди', 'd', 'draft')]
    tr = registry_trim(d2, 3)
    ok([x['stateId'] for x in tr] == ['a', 'b', 'd'], 'свободное место — сперва фото нейросети, затем по свежести')
    st = {}
    ok(registry_trim(d2, 10, pub={shot_key(d2[0])}, stats=st) == d2 and st == {'dropped': 0, 'dropped_realistic': 0, 'overflow': 0, 'protected': 1},
       'реестр в пределе — не трогаем, счётчик защищённых считается')
    old = rec('bedroom-1', 'лофт', 's', 'realistic', ts=12345, no_id=True)
    ok(shot_key(old) == 'bedroom-1|лофт|12345' and shot_key({'style': 'x', 'ts': 7}) == 'living|x|7', 'старая запись без id — ключ комната|стиль|время')
    ok(shot_key({'id': 'abc', 'style': 'x'}) == 'abc', 'запись с id — ключ id')

    print('список прогрева pub-shots.json:')
    with tempfile.TemporaryDirectory() as t:
        p = os.path.join(t, 'pub-shots.json')
        ok(load_pub(p) == (None, 'missing'), 'нет файла — защита прежняя, статус missing')
        json.dump({'ts': 1, 'keys': ['a', 'b']}, open(p, 'w'))
        ok(load_pub(p) == ({'a', 'b'}, 'ok'), 'годный — ключи и ok')
        os.utime(p, (time.time() - PUB_MAX_AGE_SEC - 60,) * 2)
        ok(load_pub(p)[1] == 'stale', 'старше 3 суток по mtime — stale')
        open(p, 'w').write('{битый')
        ok(load_pub(p) == (None, 'bad'), 'битый JSON — bad')
        json.dump({'keys': [1, 2]}, open(p, 'w'))
        ok(load_pub(p) == (None, 'bad'), 'ключи не строки — bad')
        json.dump({'keys': [f'k{i}' for i in range(PUB_MAX_KEYS + 1)]}, open(p, 'w'))
        ok(load_pub(p) == (None, 'big'), f'ключей больше {PUB_MAX_KEYS} — big')
        open(p, 'w').write(' ' * (300 * 1024))
        ok(load_pub(p) == (None, 'big'), 'файл больше 256 КБ — big, не читаем')

    print('счётчики shots-trim.json:')
    s1 = trim_stats_update(None, {'dropped': 2, 'dropped_realistic': 1, 'protected': 5, 'overflow': 0}, 'ok', 100.0)
    s2 = trim_stats_update(s1, {'dropped': 0, 'dropped_realistic': 0, 'protected': 6, 'overflow': 0}, 'ok', 200.0)
    s3 = trim_stats_update(s2, {'dropped': 3, 'dropped_realistic': 0, 'protected': 6, 'overflow': 2}, 'stale', 300.0)
    ok(s3['epoch'] == s1['epoch'] and s3['dropped_total'] == 5 and s3['dropped_realistic_total'] == 1 and s3['trim_events_total'] == 2,
       f'итоги растут монотонно в одном epoch ({s3})')
    ok(s3['protected_current'] == 6 and s3['overflow_current'] == 2 and s3['overflow_events_total'] == 1 and s3['pub_status'] == 'stale',
       'текущие: защищено, переполнение, статус списка — последнего события')
    ok(trim_stats_update({'junk': 1}, {}, 'ok', 1.0)['epoch'] != s1['epoch'], 'битый файл счётчиков — новый epoch (ночь увидит сброс)')

    print('draft_service._registry_add целиком:')
    with tempfile.TemporaryDirectory() as t:
        os.environ['FRAMES_DIR'] = os.path.join(t, 'frames')
        try:
            import draft_service as DS
        except Exception as e:  # noqa: BLE001
            ok(False, f'draft_service не импортируется: {e}')
            return 1
        DS.DR.FRAMES_DIR = os.path.join(t, 'frames')
        reg, trimf = os.path.join(t, 'shots.json'), os.path.join(t, 'shots-trim.json')
        _n[0] = 0
        base = [rec('living', 'сканди', 'pub', 'realistic')] + [rec('living', 'сканди', f'o{i}') for i in range(REGISTRY_MAX - 1)]
        json.dump(base, open(reg, 'w'))
        json.dump({'keys': [shot_key(base[0])]}, open(os.path.join(t, 'pub-shots.json'), 'w'))
        out = {'shots': [{'url': '/test/share/frames/x.jpg', 'camera': 'C1'}]}

        def add(k):
            DS._registry_add({'style': 'сканди', 'stateId': f'n{k}', 'quality': 'draft'}, out)
        ths = [threading.Thread(target=add, args=(k,)) for k in range(12)]
        [x.start() for x in ths]
        [x.join() for x in ths]
        data = json.load(open(reg))
        stt = json.load(open(trimf))
        ok(len(data) == REGISTRY_MAX and data[0]['id'] == base[0]['id'], 'реестр в пределе, защищённое фото нейросети на месте')
        ok(sum(1 for x in data if str(x.get('stateId', '')).startswith('n')) == 12, '12 параллельных записей — все в реестре, JSON целый')
        ok(stt['dropped_total'] == 12 and stt['trim_events_total'] == 12 and stt['protected_current'] == 1 and stt['pub_status'] == 'ok',
           f'счётчики на диске: выкинуто 12, защищено 1, список ok ({stt})')
        os.remove(os.path.join(t, 'pub-shots.json'))
        add(99)
        ok(json.load(open(trimf))['pub_status'] == 'missing', 'список пропал — статус missing в счётчиках')

    print('итог:', 'OK' if not BAD else f'FAIL ({len(BAD)})')
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
