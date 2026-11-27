"""Проверка входа перед кругом покраски — ПЯТЬ вещей — `circle_origin.py` + запись «вход равнозначен» `cutout_equiv.py` (T-20261127-175/10).
Запуск: python3 tools/scout/tests/test_circle_origin.py   (нужны numpy, pillow, opencv — как в CI-job planner)"""
import copy
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assets'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_circle_origin')
import tempfile  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import circle_origin as CO  # noqa: E402
import cutout_equiv as CE  # noqa: E402
import paint_run_all as RA  # noqa: E402

FAIL = []


def ok(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        FAIL.append(msg)


def put(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)


def png(path, rects, canvas=(200, 200)):
    """Вырезка RGBA: белый предмет-прямоугольники на прозрачном; rects — [(y0, y1, x0, x1)]."""
    a = np.zeros(canvas + (4,), np.uint8)
    for y0, y1, x0, x1 in rects:
        a[y0:y1, x0:x1] = (200, 100, 50, 255)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.fromarray(a, 'RGBA').save(path)


tmp = tempfile.mkdtemp(prefix='circle-origin-')
RULES = CO.load_rules()
R = copy.deepcopy(RULES)
R['current'] = {'chain_version': 'c2', 'from': None}
REC = {'sid': 'k1', 'name': 'Комод Тест', 'role': 'комод', 'params': {'width': 90}}
GOOD = {'chain_version': 'c2', 'cutout_method': 'chain_shape', 'mask_source': 'birefnet-full@w1', 'weights_version': 'rev-e2bf8e', 'code_version': 'abc1234', 'photo_sha256': 'f' * 64, 'date': '2026-11-27',
        'generator': 'TRELLIS.2 out30-v3', 'stage': 'out30-v3'}
n_case = [0]


def sh0rec(sku='k1', status='pass', flags=None, checks=None, **kw):
    """Запись Ш0 в формате `form_checks.run_sku`: {sku, observe, block, checks[{name, flag…}], auto, status, flags}; checks=None — две вызванные проверки (glb_sane, open_edges)."""
    d = {'sku': sku, 'observe': True, 'block': [], 'checks': [{'name': 'glb_sane', 'flag': False}, {'name': 'open_edges', 'flag': False}] if checks is None else checks,
         'auto': 'ok', 'status': status, 'flags': flags or []}
    d.update(kw)
    return d


def mkform(**extra):
    """Новая папка с формой и записью происхождения (GOOD + extra; значение None убирает поле) — случаи не мешают друг другу."""
    n_case[0] += 1
    d = os.path.join(tmp, 'c%d' % n_case[0])
    os.makedirs(d)
    f = os.path.join(d, 'k1-n1024.glb')
    open(f, 'wb').write(b'glb')
    rec = {k: v for k, v in {**GOOD, **extra}.items() if v is not None}
    put(f[:-4] + '.origin.json', rec)
    return f, d


print('— 1. вырезка формы')
f0 = os.path.join(tmp, 'x.glb')
ok(CO.check_cutout(None, R)['status'] == CO.NA, 'формы нет (строится в прогоне) → не применимо, не отказ')
ok(CO.check_cutout(os.path.join(tmp, 'нет.glb'), R)['status'] == CO.REFUSE, 'файла формы нет → отказ')
open(f0, 'wb').write(b'glb')
r = CO.check_cutout(f0, R)
ok(r['status'] == CO.REFUSE and 'нет записи происхождения' in r['reason'] and 'равнозначен' in r['reason'], 'форма без записи → отказ с причиной (старый make_hd_inputs / черновик)')
form, d = mkform()
r = CO.check_cutout(form, R)
ok(r['status'] == CO.OK and r['chain_version'] == 'c2' and 'вход актуален' in r['reason'], 'версия = актуальной → «вход актуален»')
form, d = mkform(chain_version='c1')
r = CO.check_cutout(form, R)
ok(r['status'] == CO.REFUSE and 'c1' in r['reason'] and 'c2' in r['reason'] and 'chain_shape' in r['reason'], 'ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: форма старой вырезки → отказ, видно «c1», «c2», способ')
form, d = mkform(photo_sha256=None, date=None)
r = CO.check_cutout(form, R)
ok(r['status'] == CO.REFUSE and 'photo_sha256' in r['reason'] and 'date' in r['reason'], 'не хватает полей → отказ с перечнем')
form, d = mkform()
put(form[:-4] + '.origin.json', {'cutout': {'chain_version': 'c2', 'method': 'chain_shape'}, 'mask': {'source': 'm', 'revision': 'r'}, 'code': {'version': 'v'}, 'photo': {'sha256': 'a'}, 'created': 'x'})
ok(CO.check_cutout(form, R)['status'] == CO.OK, 'вложенные имена-синонимы из rules (cutout.chain_version, mask.source …) читаются')
form, d = mkform()
os.remove(form[:-4] + '.origin.json')
put(os.path.join(d, 'inputs.json'), {'origin': GOOD})
ok(CO.check_cutout(form, R)['record'].endswith('inputs.json#origin'), 'запись в inputs.json#origin найдена')
form, d = mkform()
R2 = copy.deepcopy(R)
R2['current'] = {'chain_version': None, 'from': 'tools/scout/salad/нет_такого.py:CHAIN_VERSION'}
r = CO.check_cutout(form, R2)
ok(r['status'] == CO.REFUSE and 'сверить нечем' in r['reason'], 'актуальная версия не определена → «сверить нечем», не «пропустить»')
cv = os.path.join(tmp, 'cutout_chain.py')
open(cv, 'w').write("CHAIN_VERSION = 'c2'\nOTHER = 1\n")
R3 = copy.deepcopy(R)
R3['current'] = {'chain_version': None, 'from': 'cutout_chain.py:CHAIN_VERSION'}
ok(CO.current_chain_version(R3, tmp)[0] == 'c2' and CO.check_cutout(form, R3, tmp)['status'] == CO.OK, 'актуальная версия читается константой из файла (разбором, без импорта)')

print('— 1б. «вход равнозначен» (запись пишет программа сравнения)')
form, d = mkform(chain_version='c1')                       # форма старой вырезки …
oldp, newp = os.path.join(d, 'old.rgba.png'), os.path.join(d, 'new.rgba.png')
png(oldp, [(10, 150, 10, 170)])
png(newp, [(11, 150, 10, 170)])                            # … новая отличается кромкой на 1 px
rec = CE.build_record(oldp, newp, 'c2', photo=f0, old_chain='make_hd_inputs')
ok(rec['equal'] and rec['numbers']['far_px'] == 0 and rec['numbers']['mismatch_pct'] < 1 and rec['code_version'] and rec['date'] and rec['old']['sha256'] and rec['new']['sha256'],
   'сдвиг кромки на 1 px → «равнозначен: да»; в записи числа, хеши, версия кода, дата: ' + str(rec['numbers']))
EQ = form[:-4] + '.equiv.json'
put(EQ, rec)
r = CO.check_cutout(form, R)
ok(r['status'] == CO.OK and 'вход равнозначен' in r['reason'] and 'актуален' not in r['reason'].split('(не')[0] and r['how'] == 'равнозначен', 'старая версия + запись «равнозначен» → проходит, в отчёте «вход равнозначен», не «актуален»: ' + r['reason'][:90])
# порог: тонкая деталь далеко от другой маски — мало площади, но расстояние ловит
png(newp, [(10, 150, 10, 170), (160, 199, 100, 102)])      # проволока 2×40 px = 80 px (0,8 % площади, но > 30 px и далеко)
rec2 = CE.build_record(oldp, newp, 'c2')
ok(not rec2['equal'] and rec2['numbers']['far_px'] > 30 and rec2['numbers']['mismatch_pct'] < 1.5, 'потерянная/добавленная проволока → «равнозначен: нет» по расстоянию: far_px=%d' % rec2['numbers']['far_px'])
put(EQ, rec2)
r = CO.check_cutout(form, R)
ok(r['status'] == CO.REFUSE and 'НЕ равнозначны' in r['reason'], 'запись «нет» → отказ')
png(newp, [(10, 150, 10, 170), (10, 150, 170, 178)])       # 3×100 px — несовпадение 3 % > 1 %
rec3 = CE.build_record(oldp, newp, 'c2')
ok(not rec3['equal'] and rec3['numbers']['mismatch_pct'] > 1, 'несовпадение > 1 % площади → «нет» (второе условие)')
# каждое из трёх условий порога ловит своё и ТОЛЬКО своё (иначе снятие одного не заметно)
png(newp, [(10, 150, 10, 170), (160, 164, 100, 103)])      # 12 px далеко (≤ 30), но 0,054 % > 0,02 % площади; несовпадение мало
t = CE.compare(oldp, newp)
ok(not t['equal'] and t['numbers']['far_px'] <= 30 and t['numbers']['far_area_pct'] > 0.02 and t['numbers']['mismatch_pct'] < 1 and 'площади' in t['why'] and 'пикселей различия' not in t['why'], 'условие «≤ 0,02 %% площади» ловит своё: far_px=%d, %s %%' % (t['numbers']['far_px'], t['numbers']['far_area_pct']))
big_old, big_new = os.path.join(d, 'big-old.png'), os.path.join(d, 'big-new.png')
png(big_old, [(10, 700, 10, 590)], (800, 600))
png(big_new, [(10, 700, 10, 590), (710, 750, 100, 101)], (800, 600))   # 40 px далеко (> 30), но 0,01 % ≤ 0,02 % площади
t = CE.compare(big_old, big_new)
ok(not t['equal'] and t['numbers']['far_px'] > 30 and t['numbers']['far_area_pct'] <= 0.02 and 'пикселей различия' in t['why'] and 'площади' not in t['why'], 'условие «≤ 30 px» ловит своё: far_px=%d, %s %%' % (t['numbers']['far_px'], t['numbers']['far_area_pct']))
png(newp, [(10, 150, 10, 172)])                            # кромка шире на 2 px вдоль всего края: 1,25 % несовпадения, но ничего дальше 2 px
t = CE.compare(oldp, newp)
ok(not t['equal'] and t['numbers']['far_px'] == 0 and t['numbers']['mismatch_pct'] > 1 and 'несовпадение' in t['why'], 'условие «несовпадение ≤ 1 %%» ловит своё: far_px=0, %s %%' % t['numbers']['mismatch_pct'])
png(newp, [(11, 150, 10, 170)])
# подделки
fake = dict(rec2, equal=True)
put(EQ, fake)
png(newp, [(10, 150, 10, 170), (160, 199, 100, 102)])
fake['new']['sha256'] = CE.sha256_file(newp)
put(EQ, fake)
r = CO.check_cutout(form, R)
ok(r['status'] == CO.REFUSE and 'не прошла проверку' in r['reason'] and 'вписана не программой' in r['reason'], 'ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: «equal: true» вписан рукой при плохих числах → отказ (итог пересчитывается)')
png(newp, [(11, 150, 10, 170)])
put(EQ, rec)
png(newp, [(11, 150, 10, 170), (160, 199, 100, 102)])      # файл подменён уже ПОСЛЕ записи
r = CO.check_cutout(form, R)
ok(r['status'] == CO.REFUSE and 'хеш new не совпал' in r['reason'], 'ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: подделанный хеш (файл подменён после записи) → отказ')
png(newp, [(11, 150, 10, 170)])
forged = copy.deepcopy(rec)
forged['old']['sha256'] = '0' * 64
put(EQ, forged)
ok('хеш old не совпал' in CO.check_cutout(form, R)['reason'], 'хеш в записи вписан рукой → отказ')
os.remove(oldp)
put(EQ, rec)
ok('файла old нет' in CO.check_cutout(form, R)['reason'], 'файл вырезки пропал → отказ')
png(oldp, [(10, 150, 10, 170)])
# смена версии цепочки
put(EQ, rec)
R4 = copy.deepcopy(R)
R4['current'] = {'chain_version': 'c3', 'from': None}
r = CO.check_cutout(form, R4)
ok(r['status'] == CO.REFUSE and 'устарела' in r['reason'] and 'пересчёт не удался' in r['reason'] and 'c2' in r['reason'] and 'c3' in r['reason'], 'ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: версия цепочки сменилась, команды пересчёта нет → отказ «запись устарела» (не пропускает)')
gen = os.path.join(tmp, 'recut.py')
open(gen, 'w').write("import shutil, sys\nshutil.copy(sys.argv[1], sys.argv[2])\n")
equal_png, wire_png = os.path.join(tmp, 'recut-equal.png'), os.path.join(tmp, 'recut-wire.png')
png(equal_png, [(10, 151, 10, 170)])
png(wire_png, [(10, 150, 10, 170), (160, 199, 100, 102)])
R5 = copy.deepcopy(R4)
R5['equiv'] = dict(R5.get('equiv') or {}, recompute_cmd=[sys.executable, gen, equal_png, '{out}'])
put(EQ, rec)
r = CO.check_cutout(form, R5)
now = json.load(open(EQ, encoding='utf-8'))
ok(r['status'] == CO.OK and 'пересчитана сама' in r['reason'] and now['against_chain_version'] == 'c3' and now['new']['path'].endswith('.new-c3.png'), 'версия сменилась → сравнение пересчиталось само против c3, запись переписана, проходит: ' + r['reason'][-70:])
R6 = copy.deepcopy(R4)
R6['equiv'] = dict(R6.get('equiv') or {}, recompute_cmd=[sys.executable, gen, wire_png, '{out}'])
put(EQ, rec)
r = CO.check_cutout(form, R6)
ok(r['status'] == CO.REFUSE and 'НЕ равнозначны' in r['reason'], 'пересчёт против новой версии не сошёлся (проволока) → отказ, форму строить заново')
ok(CE.verify(json.load(open(EQ, encoding='utf-8')), 'c3')[0] == 'not_equal', 'и запись после пересчёта честно хранит «нет»')

print('— формат рабочего 2 (OTCHET-9: inputs.json → <sku>.origin, format 1)')
ok(CO.sku_of('/x/112923_55-n1024.glb') == '112923_55' and CO.sku_of('112923_55.hd.rgba.png') == '112923_55', 'id товара берётся из имени формы (суффикс -n1024 и .hd.rgba.png отрезаются)')
d6 = os.path.join(tmp, 'rab2')
os.makedirs(d6)
form6 = os.path.join(d6, '112923_55-n1024.glb')
open(form6, 'wb').write(b'glb')
R2F = {'format': 1, 'method': 'cutout_one', 'chain_version': 'c2', 'steps': ['main_object'], 'mask': {'source': 'birefnet-full-cpu-fp32', 'repo': 'ZhengPeng7/BiRefNet', 'revision': 'e2bf8e4460fc'},
       'code': 'abc123def', 'photo_sha256': 'a' * 64, 'pixels_sha256': 'b' * 64, 'created': '2026-11-27T12:00:00Z'}
put(os.path.join(d6, 'inputs.json'), {'112923:55': {'input_png_sha256': 'c' * 64, 'origin': R2F}, '112923:56': {'origin': dict(R2F, chain_version='c1')}})
r = CO.check_cutout(form6, R)
ok(r['status'] == CO.OK and r['chain_version'] == 'c2' and 'inputs.json#112923:55.origin' in r['record'], 'запись рабочего 2 (inputs.json, ключ «112923:55», поле origin) читается ровно в его формате: mask.revision → версия весов, code, created')
put(os.path.join(d6, 'inputs.json'), {'112923:55': {'origin': dict(R2F, chain_version='c1')}})
r = CO.check_cutout(form6, R)
ok(r['status'] == CO.REFUSE and 'c1' in r['reason'], 'тот же формат с chain_version c1 при актуальной c2 → отказ')
put(os.path.join(d6, 'inputs.json'), {'112923:55': {'origin': {k: v for k, v in R2F.items() if k != 'mask'}}})
r = CO.check_cutout(form6, R)
ok(r['status'] == CO.REFUSE and 'mask_source' in r['reason'] and 'weights_version' in r['reason'], 'в записи нет mask → отказ: не названы источник маски и версия весов')
put(form6[:-4] + '.form.json', {'generator': 'trellis2', 'stage': 'out30-v3'})
put(os.path.join(d6, 'form_checks.json'), sh0rec(sku='112923_55'))
put(os.path.join(d6, 'inputs.json'), {'112923:55': {'origin': R2F}})
ok(CO.check_generator(form6, '112923_55', CO.form_facts(form6, R), R)['status'] == CO.OK, 'генератор и ступень — из метки формы (`<форма>.form.json`), запись вырезки их не несёт; Ш0 читается из form_checks.json рядом')
rr = CO.load_rules()
v, src = CO.current_chain_version(rr, CO.ROOT)
ok('cutout_origin.py:CHAIN_VERSION' in (rr['current']['from'] or ''), 'актуальная версия читается константой CHAIN_VERSION из `tools/scout/salad/cutout_origin.py` (файл и имя — у рабочего 2): ' + str(src))
print('— 1в. парные кейсы на НАСТОЯЩЕМ дереве (боевые правила + настоящий cutout_origin.py; не подмена версии в правилах)')
import re  # noqa: E402
mod_real = os.path.join(CO.ROOT, 'tools', 'scout', 'salad', 'cutout_origin.py')
cv_file = re.search(r"^CHAIN_VERSION\s*=\s*'([^']+)'", open(mod_real, encoding='utf-8').read(), re.M).group(1)
v_real, src_real = CO.current_chain_version(RULES, CO.ROOT)
ok(v_real == cv_file and src_real.endswith('cutout_origin.py:CHAIN_VERSION'), 'боевые правила: актуальная версия читается из настоящего модуля вырезки (%s = %s)' % (src_real, v_real))
f_cur, _d = mkform(chain_version=cv_file)
r = CO.check_cutout(f_cur, RULES)
ok(r['status'] == CO.OK and r['chain_version'] == cv_file and 'вход актуален' in r['reason'], 'настоящее дерево: форма с версией модуля (%s) проходит пункт 1 («вход актуален»)' % cv_file)
f_old, _d = mkform(chain_version='c0-старая')
r = CO.check_cutout(f_old, RULES)
ok(r['status'] == CO.REFUSE and 'вход устарел' in r['reason'] and 'c0-старая' in r['reason'] and cv_file in r['reason'], 'настоящее дерево: форма старой версии → «вход устарел», видно обе версии')
f_c1, _d = mkform(chain_version='c1')
ok(CO.check_cutout(f_c1, RULES)['status'] == (CO.OK if cv_file == 'c1' else CO.REFUSE), 'настоящее дерево: форма c1 отказывает, пока актуальная не c1')
nomod_root = os.path.join(tmp, 'tree-without-module')
os.makedirs(os.path.join(nomod_root, 'tools', 'scout', 'salad'))
r = CO.check_cutout(f_cur, RULES, nomod_root)
ok(r['status'] == CO.REFUSE and 'сверить нечем' in r['reason'], 'временное дерево БЕЗ cutout_origin.py (боевые правила) → «сверить нечем», не «пропустить»')
shutil.copy(mod_real, os.path.join(nomod_root, 'tools', 'scout', 'salad', 'cutout_origin.py'))
ok(CO.check_cutout(f_cur, RULES, nomod_root)['status'] == CO.OK, 'то же дерево с модулем вырезки → форма проходит (пара к предыдущему)')
pxa, pxb = os.path.join(d6, 'pa.png'), os.path.join(d6, 'pb.png')
png(pxa, [(10, 150, 10, 170)])
png(pxb, [(11, 150, 10, 170)])
ok(len(CE.pixels_sha256(pxa)) == 64 and CE.pixels_sha256(pxa) != CE.pixels_sha256(pxb), 'pixels_sha256 (хеш содержимого, как у рабочего 2) считается и различает вырезки')
rec_px = CE.build_record(pxa, pxb, 'c2')
ok(rec_px['new']['pixels_sha256'] == CE.pixels_sha256(pxb) and CE.verify(rec_px, 'c2')[0] == 'equal', 'в записи «равнозначен» — хеш файла и хеш содержимого новой вырезки; проверка проходит')
fk = copy.deepcopy(rec_px)
fk['new']['pixels_sha256'] = '0' * 64
ok(CE.verify(fk, 'c2')[0] == 'forged' and 'pixels_sha256' in CE.verify(fk, 'c2')[1], 'вписанный рукой pixels_sha256 → forged')

print('— 2. генератор и Ш0')
form, d = mkform()
put(os.path.join(d, 'form_checks.json'), sh0rec())
r = CO.check_generator(form, 'k1', CO.form_facts(form, R), R)
ok(r['status'] == CO.OK and 'TRELLIS' in r['reason'], 'TRELLIS.2 + Ш0 pass → ok')
for bad_status in ('needs_review', 'shape_reject', 'camera_or_mask_uncertain'):
    put(os.path.join(d, 'form_checks.json'), sh0rec(status=bad_status, flags=['bottom_gap']))
    r = CO.check_generator(form, 'k1', CO.form_facts(form, R), R)
    ok(r['status'] == CO.REFUSE and bad_status in r['reason'] and 'bottom_gap' in r['reason'], 'Ш0 «%s» → отказ с флагами' % bad_status)
put(os.path.join(d, 'k1', 'form_checks.json'), sh0rec())
os.remove(os.path.join(d, 'form_checks.json'))
ok(CO.check_generator(form, 'k1', CO.form_facts(form, R), R)['status'] == CO.OK, 'вердикт Ш0 в <папка>/<sku>/form_checks.json найден')
shutil.rmtree(os.path.join(d, 'k1'))
r = CO.check_generator(form, 'k1', CO.form_facts(form, R), R)
ok(r['status'] == CO.REFUSE and 'нет записи form_checks.json' in r['reason'], 'вердикта Ш0 нет → отказ (приёмка не пройдена)')
form2, d2 = mkform(eye_accepted=True, form_checks={'status': 'pass', 'flags': []})
r = CO.check_generator(form2, 'k1', CO.form_facts(form2, R), R)
ok(r['status'] == CO.REFUSE and 'Ш0 не пройдена' in r['reason'] and 'нет записи form_checks.json' in r['reason'], 'eye_accepted и вложенный в запись происхождения вердикт НЕ читаются: без form_checks.json рядом с формой → отказ «Ш0 не пройдена» (директор 27.11)')
r = CO.check_generator(form, 'k1', CO.form_facts(form, R), R)
ok(r['status'] == CO.REFUSE and 'Ш0 не пройдена' in r['reason'] and 'нет записи' in r['reason'] and 'k1' in r['reason'], 'форма без form_checks → отказ «Ш0 не пройдена: нет записи» и список мест, где искал')
fcp = os.path.join(d, 'form_checks.json')
for what, body in (('пустой файл', ''), ('битый JSON', '{"status": "pa'), ('JSON не словарь', '[1, 2]'), ('пустой словарь', '{}')):
    open(fcp, 'w', encoding='utf-8').write(body)
    r = CO.check_generator(form, 'k1', CO.form_facts(form, R), R)
    ok(r['status'] == CO.REFUSE and 'Ш0 не пройдена' in r['reason'] and 'битая или пустая' in r['reason'], 'запись Ш0: %s → отказ «Ш0 не пройдена»' % what)
for what, body, frag in (('нет status', {k: v for k, v in sh0rec().items() if k != 'status'}, 'нет status'), ('неизвестный status', sh0rec(status='ok'), 'неизвестный'),
                         ('status пуст', sh0rec(status=''), 'нет status'), ('checks нет (ничего не вызвано)', {k: v for k, v in sh0rec().items() if k != 'checks'}, 'не названо ни одной'),
                         ('checks пуст', sh0rec(checks=[]), 'не названо ни одной'), ('checks без имён', sh0rec(checks=[{'flag': False}, 5]), 'не названо ни одной'),
                         ('нет обязательной glb_sane', sh0rec(checks=[{'name': 'open_edges', 'flag': False}]), 'обязательные проверки'), ('чужой товар', sh0rec(sku='другой'), 'другого товара')):
    put(fcp, body)
    r = CO.check_generator(form, 'k1', CO.form_facts(form, R), R)
    ok(r['status'] == CO.REFUSE and 'Ш0 не пройдена' in r['reason'] and frag in r['reason'], 'запись Ш0 с дефектом «%s» → отказ «Ш0 не пройдена»' % what)
put(fcp, sh0rec(status='pass'))
r = CO.check_generator(form, 'k1', CO.form_facts(form, R), R)
ok(r['status'] == CO.OK and 'вызвано проверок: 2' in r['reason'] and r.get('sh0', {}).get('called') == ['glb_sane', 'open_edges'], 'годная запись: ok, в итоге — статус и ЧТО ВЫЗВАНО (glb_sane, open_edges), путь к записи')
put(fcp, sh0rec(sku='112923:1'))
ok(CO.check_generator(form, '112923_1', CO.form_facts(form, R), R)['status'] == CO.OK, 'sku в записи с «:» совпадает с «_»-видом id товара круга')
put(fcp, sh0rec())
res = CO.check_start('k1', form=form, record=REC, camera={'status': 'ok', 'reason': ''}, rules=R)
ok(res['origin']['sh0']['status'] == 'pass' and res['origin']['sh0']['called'] == ['glb_sane', 'open_edges'], 'в журнал круга (origin.sh0) идут статус Ш0 и список вызванного')
os.remove(fcp)
form3, d3 = mkform(generator='Hunyuan3D-2.1')
put(os.path.join(d3, 'form_checks.json'), sh0rec())
r = CO.check_generator(form3, 'k1', CO.form_facts(form3, R), R)
ok(r['status'] == CO.REFUSE and 'не разрешён' in r['reason'] and 'Hunyuan' in r['reason'], 'форма Hunyuan → отказ (ADR-0455, TG 2029)')
form4, d4 = mkform(generator=None, stage=None)
r = CO.check_generator(form4, 'k1', CO.form_facts(form4, R), R)
ok(r['status'] == CO.REFUSE and 'generator' in r['reason'] and 'stage' in r['reason'], 'генератор и ступень не названы → отказ')
ok(CO.check_generator(None, 'k1', None, R)['status'] == CO.NA, 'формы нет → не применимо')
form5, d5 = mkform(chain_version='c1', generator=None, stage=None)
put(form5[:-4] + '.equiv.json', dict(rec, form={'generator': 'trellis2', 'stage': 'out30-v3', 'eye_accepted': True}))
r = CO.check_generator(form5, 'k1', CO.form_facts(form5, R), R)
ok(r['status'] == CO.REFUSE and 'нет записи form_checks.json' in r['reason'] and 'trellis2' in r['reason'],'ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: генератор/ступень берутся из блока form записи «равнозначен», а eye_accepted и Ш0 оттуда НЕ принимаются (рукой Ш0 не обойти) → отказ')

print('— 3. камера 04')
ok(CO.check_camera({'status': 'ok', 'reason': 'все пороги'})['status'] == CO.OK, 'check.json ok → ok')
ok(CO.check_camera({'status': 'soft', 'reason': 'нижняя полоса'})['status'] == CO.OK, 'мягко прошла → ok')
r = CO.check_camera({'status': 'refused', 'reason': 'силуэт IoU 0.4'})
ok(r['status'] == CO.REFUSE and 'IoU' in r['reason'], 'камера отказана → отказ с причиной')
ok(CO.check_camera({'status': 'missing', 'will_run': True})['status'] == CO.NA, 'ещё не считалась, этот прогон посчитает → не применимо')
ok(CO.check_camera({'status': 'missing', 'will_run': False})['status'] == CO.REFUSE, 'не считалась и не будет → отказ')
ok(CO.check_camera(None)['status'] == CO.NA, 'прогон не передан → не применимо')

print('— 4. карточка и тип')
ok(CO.check_card(None, None)['status'] == CO.REFUSE and 'no_type' in CO.check_card(None, None)['reason'], 'нет записи каталога → отказ (причина Avalon)')
c = CO.check_card(REC, None)
ok(c['status'] == CO.OK and c['card_sha'] and c['type'], 'запись есть, роль «комод» → тип «%s» → ok' % c.get('type'))
ok(CO.check_card({'name': 'Х', 'role': '', 'params': {'w': 1}}, None)['status'] == CO.REFUSE, 'пустая роль → отказ «карточка пустая»')
ok('пустая' in CO.check_card({'name': '', 'role': 'комод', 'params': {'w': 1}}, None)['reason'], 'пустое название → «карточка пустая»')
ok('параметров' in CO.check_card({'name': 'Х', 'role': 'комод', 'params': {}}, None, R)['reason'], 'нет параметров → отказ')
r = CO.check_card({'name': 'Х', 'role': 'стол', 'params': {'w': 1}}, None)
ok(r['status'] == CO.REFUSE and 'тип' in r['reason'], 'роль без типа в паспортах («стол») → отказ')
card = os.path.join(tmp, 'work', 'card.json')
put(card, CO.flat_card(REC))
ok(CO.check_card(REC, card)['status'] == CO.OK, 'card.json = текущая запись каталога → ok')
put(card, dict(CO.flat_card(REC), width=70))
c = CO.check_card(REC, card)
ok(c['status'] == CO.REFUSE and 'width' in c['reason'], 'card.json старая (width другой) → отказ с именем поля')

print('— 5. набор правил')
lab = CO.rules_label('комод', R)
p = CO.check_rules_set('комод', R)
ok(p['status'] == CO.OK and lab['type'] and lab['id'] and p['label']['id'] == lab['id'], 'метка набора: тип «%s», id %s' % (lab['type'], lab['id']))
ok(CO.check_rules_set('комод', R, {'id': 'другой'})['status'] == CO.REFUSE and 'новый прогон' in CO.check_rules_set('комод', R, {'id': 'другой'})['reason'], 'прежняя метка другая → отказ «продолжать нельзя»')
ok(CO.check_rules_set('комод', R, {'id': lab['id']})['status'] == CO.OK, 'та же метка → ok')
ok(CO.check_rules_set('комод', R, None, 'ожидаемая-другая')['status'] == CO.REFUSE, 'ожидаемая метка (замороженный набор) ≠ текущей → отказ')
ok(CO.check_rules_set('комод', R, None, lab['id'])['status'] == CO.OK, 'ожидаемая = текущей → ok')
_orig_set = CO.set_label
CO.set_label = lambda root=CO.ROOT: 'метка-aaa'
la = CO.rules_label('комод', R)
CO.set_label = lambda root=CO.ROOT: 'метка-bbb'
lb = CO.rules_label('комод', R)
pb = CO.check_rules_set('комод', R, {'id': la['id']})
CO.set_label = _orig_set
ok(la['set'] == 'метка-aaa' and lb['set'] == 'метка-bbb' and la['id'] == lb['id'] and pb['status'] == CO.OK, 'метка №12 (rules_label.id) только пишется в журнал (set), в решение не входит: другая метка №12 — тот же id круга, отказа нет (менеджер 27.11: у неё дыра по env)')
Rm = copy.deepcopy(R)
Rm['profile_files'] = ['tools/scout/rules/нет-такого.json']
ok(CO.check_rules_set('комод', Rm)['status'] == CO.REFUSE, 'файла правил нет → отказ')
fake_root = os.path.join(tmp, 'root')
os.makedirs(os.path.join(fake_root, 'tools', 'scout', 'rules'))
for rel in R['profile_files']:
    shutil.copy(os.path.join(CO.ROOT, rel), os.path.join(fake_root, rel))
l1 = CO.rules_label('комод', R, fake_root)['id']
with open(os.path.join(fake_root, R['profile_files'][0]), 'a', encoding='utf-8') as fh:
    fh.write('\n')
ok(CO.rules_label('комод', R, fake_root)['id'] != l1, 'правка файла правил меняет метку набора')

print('— 5б. метка №12 сменилась: из-за правки самой метки или правил (показ, решение не меняется)')
sd = os.path.join(tmp, 'rootset')
os.makedirs(os.path.join(sd, 'tools', 'scout', 'rules'))
for rel in R['profile_files']:
    shutil.copy(os.path.join(CO.ROOT, rel), os.path.join(sd, rel))
put(os.path.join(sd, 'tools', 'scout', 'rules', 'rules-label.json'), {'_about': 'комментарий', 'include': ['tools/scout/rules'], 'env': ['A_ENV', 'B_ENV']})
open(os.path.join(sd, 'tools', 'scout', 'rules_label.py'), 'w', encoding='utf-8').write('# метка v1\n')
_o = CO.set_label
SET = ['метка-111']
CO.set_label = lambda root=CO.ROOT: SET[0]
old = CO.rules_label('комод', R, sd)
ok(old['set_def']['code'] and old['set_def']['cfg'], 'определение метки (код rules_label.py и конфиг rules-label.json) считается и пишется в метку круга: %s' % old['set_def'])
SET[0] = 'метка-222'
same = CO.check_rules_set('комод', R, old, None, sd)
ok(same['status'] == CO.OK and 'сменилась' in same['reason'] and 'определение метки то же' in same['reason'] and same['label']['set_change']['cause'] == 'правила', 'set сменился, определение метки то же → «менялись правила/окружение», не «правка метки»; решение прежнее (ok)')
open(os.path.join(sd, 'tools', 'scout', 'rules_label.py'), 'w', encoding='utf-8').write('# метка v2\n')
r_code = CO.check_rules_set('комод', R, old, None, sd)
ok(r_code['status'] == CO.OK and 'САМОЙ метки' in r_code['reason'] and 'rules_label.py' in r_code['reason'] and 'без изменений' in r_code['reason'] and r_code['label']['set_change']['cause'] == 'метка', 'правка кода метки (rules_label.py) → «сменилась из-за правки самой метки», правила круга без изменений, не отказ')
open(os.path.join(sd, 'tools', 'scout', 'rules_label.py'), 'w', encoding='utf-8').write('# метка v1\n')
put(os.path.join(sd, 'tools', 'scout', 'rules', 'rules-label.json'), {'_about': 'комментарий', 'include': ['tools/scout/rules'], 'env': ['A_ENV', 'B_ENV', 'C_ENV']})
r_env = CO.check_rules_set('комод', R, old, None, sd)
ok(r_env['label']['set_change']['cause'] == 'метка' and 'rules-label.json' in r_env['reason'], 'в список env добавлена переменная (rules-label.json) → причина «сама метка»')
put(os.path.join(sd, 'tools', 'scout', 'rules', 'rules-label.json'), {'_about': 'другой комментарий', 'include': ['tools/scout/rules'], 'env': ['A_ENV', 'B_ENV']})
ok(CO.set_def(sd) == old['set_def'] and CO.check_rules_set('комод', R, old, None, sd)['label']['set_change']['cause'] == 'правила', 'правка комментария в rules-label.json определение метки не двигает')
old_nodef = {k: v for k, v in old.items() if k != 'set_def'}
r_nd = CO.check_rules_set('комод', R, old_nodef, None, sd)
ok(r_nd['label']['set_change']['cause'] == 'неизвестно' and 'причину не отделить' in r_nd['reason'], 'прежняя запись без определения метки → «причину не отделить» (честно, без догадки)')
SET[0] = 'метка-111'
ok('set_change' not in CO.check_rules_set('комод', R, old, None, sd)['label'] and 'сменилась' not in CO.check_rules_set('комод', R, old, None, sd)['reason'], 'set не менялся → ни слова про смену')
SET[0] = 'метка-222'
with open(os.path.join(sd, R['profile_files'][0]), 'a', encoding='utf-8') as fh:
    fh.write('\n')
r_both = CO.check_rules_set('комод', R, old, None, sd)
ok(r_both['status'] == CO.REFUSE and 'новый прогон' in r_both['reason'] and 'метка набора №12' in r_both['reason'], 'правилa круга сменились (id) → прежний отказ «новый прогон» + строка про смену set')
CO.set_label = _o

print('— старт целиком и обход')
form, d = mkform()
put(os.path.join(d, 'form_checks.json'), sh0rec())
CAM = {'status': 'ok', 'reason': 'ok'}
res = CO.check_start('k1', form=form, record=REC, card=None, camera=CAM, rules=R)
ok(res['ok'] and res['bypass'] is None and len(res['items']) == 5 and res['origin']['chain_version'] == 'c2' and res['origin']['rules_label']['id'] and res['origin']['generator'], 'всё чисто → ok, пять пунктов, origin для журнала заполнен')
ok([i['item'] for i in res['items']] == ['вырезка формы', 'генератор и Ш0', 'камера 04', 'карточка и тип', 'набор правил'], 'пункты названы и пронумерованы как в плане Fable')
txt = CO.render(res)
ok('1.' in txt and '5.' in txt and 'можно начинать' in txt, 'вывод: пять строк с номерами')
formo, do = mkform(chain_version='c1')
put(os.path.join(do, 'form_checks.json'), sh0rec())
res = CO.check_start('k1', form=formo, record=REC, camera=CAM, rules=R)
ok(not res['ok'] and 'КРУГ НЕ СТАРТУЕТ' in CO.render(res) and 'старая' in CO.render(res), 'форма старой вырезки → круг не стартует')
ok(not CO.check_start('k1', form=formo, record=REC, camera=CAM, rules=R, allow_old='')['ok'], 'обход с пустой причиной → всё равно отказ')
ok(not CO.check_start('k1', form=formo, record=REC, camera=CAM, rules=R, allow_old='короткая')['ok'], 'обход с причиной короче 10 знаков → отказ')
res = CO.check_start('k1', form=formo, record=REC, camera=CAM, rules=R, allow_old='разовая пачка 9 товаров T-172, решение директора')
ok(res['ok'] and res['bypass']['items'] == ['вырезка формы'] and 'пачка' in res['bypass']['reason'], 'обход ключом с причиной → ok, обойдён «вырезка формы», причина в отчёте')
ok('ОБХОД' in CO.render(res) and 'run_all.json' in CO.render(res), 'вывод называет обход и что он попадёт в run_all.json')
res = CO.check_start('k1', form=formo, record=None, camera={'status': 'refused', 'reason': 'x'}, rules=R, allow_old='всё сразу, разово, решение директора')
ok(res['ok'] and {'вырезка формы', 'камера 04', 'карточка и тип'} <= set(res['bypass']['items']), 'обход покрывает все отказавшие пункты и называет их')
for k in ('вход равнозначен',):
    put(formo[:-4] + '.equiv.json', rec)
    png(oldp, [(10, 150, 10, 170)])
    png(newp, [(11, 150, 10, 170)])
    put(formo[:-4] + '.equiv.json', CE.build_record(oldp, newp, 'c2'))
    res = CO.check_start('k1', form=formo, record=REC, camera=CAM, rules=R)
    ok(res['ok'] and res['origin']['cutout_basis'] == 'равнозначен' and res['origin']['equiv']['far_px'] == 0 and 'вход равнозначен' in CO.render(res), 'форма старой вырезки + запись «равнозначен» → круг идёт, в журнале основание «равнозначен» и числа')

print('— проводка в paint_run_all')
cat = os.path.join(tmp, 'cat.json')
put(cat, [REC])
form, d = mkform()
a = {'native': 'n.glb', 'photo': 'p.png', 'catalog': cat, 'prep_glb': form, 'root': tmp}
run = os.path.join(tmp, 'run')
o = RA.origin_start(run, 'k1', a, None)
by = {i['item']: i for i in o['items']}
ok(len(o['items']) == 5 and by['вырезка формы']['status'] == CO.OK and 'c2' in by['вырезка формы']['reason'], 'с боевыми правилами и модулем вырезки (9.1–9.3, CHAIN_VERSION c2) форма с актуальной версией проходит пункт «вырезка формы»')
_load = CO.load_rules                                                      # «модуля вырезки нет» — подменой правил В ТЕСТЕ; боевой rules/circle-origin.json не трогаем
CO.load_rules = lambda *a_, **k_: {**_load(), 'current': {'chain_version': None, 'from': 'tools/scout/salad/нет_такого_модуля.py:CHAIN_VERSION'}}
try:
    o_nomod = RA.origin_start(os.path.join(tmp, 'run_nomod'), 'k1', a, None)
finally:
    CO.load_rules = _load
by_nm = {i['item']: i for i in o_nomod['items']}
ok(len(o_nomod['items']) == 5 and by_nm['вырезка формы']['status'] == CO.REFUSE and 'сверить нечем' in by_nm['вырезка формы']['reason'], 'модуля вырезки нет (подмена правил в тесте) → готовая форма отказывается («сверить нечем», не «пропустить»)')
ok(CO.load_rules is _load, 'подмена правил снята: боевые правила снова читаются из файла')
ok(by['камера 04']['status'] == CO.REFUSE and 'не пройдена' in by['камера 04']['reason'], 'готовая форма без --prep-run: этап 04 заблокирован, камеры нет и не будет → отказ')
ok({i['item']: i for i in RA.origin_start(os.path.join(tmp, 'run0'), 'k1', dict(a, prep_glb=''), None)['items']}['камера 04']['status'] == CO.NA, 'форма строится в этом прогоне: камеру 04 посчитает он сам → не применимо')
o = RA.origin_start(run, 'k1', a, 'разово, решение директора, проверка')
ok(o['ok'] and o['bypass'], 'ключ --allow-old-origin пропускает и помечает обход')
real_procs, steps_seen = [], []                                              # тест решает про СТАРТ круга и журнал обхода, настоящих этапов (Blender и др.) не запускает — в CI их нет (CI main красный на bc067fce0)
_sp, _rs = RA.subprocess.run, RA._run_step
RA.subprocess.run = lambda *a_, **k_: (real_procs.append(str(a_[0] if a_ else k_.get('args'))[:120]), RA.subprocess.CompletedProcess(a_[0] if a_ else [], 97, '', 'запуск процесса запрещён тестом'))[1]   # сторож: любой настоящий запуск — не исполняется, а считается
RA._run_step = lambda step, name, ctx, rules, timeout, use_heavy: (steps_seen.append(name), {'cmd': step['argv'], 'rc': 97, 'seconds': 0.0, 'tail': 'подмена в тесте: этап не запускается'})[1]
try:
    log = RA.execute(run, 'k1', dict(a, prep_glb=''), RA.load_rules(), RA.PC.load_rules(), ['01-02'], 5, origin=o)
finally:
    RA.subprocess.run, RA._run_step = _sp, _rs
ok(RA.subprocess.run is _sp and RA._run_step is _rs, 'подмены запуска сняты после случая')
ok(not real_procs, 'тест не запускает настоящие процессы этапов (запусков subprocess.run: %d %s) — иначе в CI без Blender падение FileNotFoundError' % (len(real_procs), real_procs[:1]))
ok(steps_seen, 'после обхода круг дошёл до шага этапа 01–02 (шаг подменён, не выполнен): %s' % steps_seen[:1])
ok(log.get('origin', {}).get('bypass', {}).get('reason', '').startswith('разово'), 'обход попал в журнал прогона (log.origin.bypass.reason)')
ok(log['origin'].get('rules_label', {}).get('id') == o['origin']['rules_label']['id'], 'метка набора правил записана в журнал прогона')
o2 = RA.origin_start(run, 'k1', dict(a, prep_glb=''), None)
ok(o2['items'][4]['status'] == CO.OK and 'прежней' in o2['items'][4]['reason'], 'повторный старт в том же прогоне: метка совпала с журнальной')
o3 = RA.origin_start(run, 'k1', dict(a, prep_glb=''), None, expected_label='чужая-метка')
ok(o3['items'][4]['status'] == CO.REFUSE, 'ключ --rules-label с чужой меткой → отказ набора правил')
src = open(os.path.join(HERE, '..', 'paint_run_all.py'), encoding='utf-8').read()
ok('--allow-old-origin' in src and '--rules-label' in src, 'в CLI paint_run_all есть ключи --allow-old-origin и --rules-label')
rules_all = RA.load_rules()
pl = RA.plan(os.path.join(tmp, 'run2'), 'k1', dict(a, prep_glb='', product_role='комод'), rules_all, RA.PC.load_rules())
c07 = [i for i in pl if i['stage'] == '07'][0]['steps'][0]['argv']
ok('--photo' in c07 and c07[c07.index('--photo') + 1] == 'p.png', 'сырое фото в шаге 07: --photo p.png стоит в команде')
pl = RA.plan(os.path.join(tmp, 'run3'), 'k1', dict(a, photo='', prep_glb='', product_role='комод'), rules_all, RA.PC.load_rules())
c07 = [i for i in pl if i['stage'] == '07'][0]['steps'][0]['argv']
ok('--photo' not in c07, 'фото не задано → флага --photo в 07 нет (без пустого значения)')

print('— стартеры круга: ворота на пачке товаров (loop5, stage_trial)')
catg = os.path.join(tmp, 'catg.json')
put(catg, [REC, {'sid': 'k2', 'name': 'Шкаф', 'role': 'шкаф', 'params': {'width': 80}}])
formg, dg = mkform()
put(os.path.join(dg, 'form_checks.json'), sh0rec())
poseg = os.path.join(tmp, 'pose-k1')
put(os.path.join(poseg, '04-camera', 'check.json'), {'passed': True, 'metrics': {}})
g = CO.gate_rows({'k1': {'glb': formg, 'pose_run': poseg}}, catalog=catg, rules=R)
ok(g['ok'] and g['n'] == 1 and g['refused'] == [], 'пачка из одного товара: форма с записью, камера 04 пройдена, карточка из каталога → ворота открыты')
g = CO.gate_rows({'k1': {'pose_run': poseg}}, catalog=catg, rules=R)
ok(not g['ok'] and g['refused'] == ['k1'] and g['results']['k1']['items'][0]['status'] == CO.REFUSE, 'строка входа без формы (glb) → отказ пункта 1, а не пропуск')
g = CO.gate_rows({'k1': {'glb': formg}}, catalog=catg, rules=R)
ok(not g['ok'] and 'камера 04' in CO.render_rows(g), 'нет папки камеры этапа 4 (pose_run) → отказ «камера 04 не пройдена»')
put(os.path.join(tmp, 'poseroot', 'g1', 'k1', '04-camera', 'check.json'), {'passed': True})
ok(CO.find_pose_run('k1', {}, [os.path.join(tmp, 'poseroot')]) == os.path.join(tmp, 'poseroot', 'g1', 'k1') and CO.find_pose_run('k9', {}, [os.path.join(tmp, 'poseroot')]) is None, '--pose-root: камера ищется в <корень>/<товар> и <корень>/g*/<товар>; нет — None')
put(os.path.join(tmp, 'pose-k2', '04-camera', 'check.json'), {'passed': False, 'reason': 'силуэт IoU 0.4', 'metrics': {'iou': {'ok': False, 'value': 0.4, 'threshold': 0.8, 'op': '>='}}})
g = CO.gate_rows({'k1': {'glb': formg, 'pose_run': poseg}, 'k2': {'glb': formg, 'pose_run': os.path.join(tmp, 'pose-k2')}}, catalog=catg, rules=R)
ok(g['refused'] == ['k2'] and g['n'] == 2, 'пачка из двух: плохая камера у k2 — отказ ровно у него, k1 чист')
outg = os.path.join(tmp, 'gate-out')
try:
    CO.starter_gate({'k2': {'glb': formg, 'pose_run': os.path.join(tmp, 'pose-k2')}}, who='тест', out_dir=outg, catalog=catg, rules=R, say=lambda m: None)
    code = None
except SystemExit as e:
    code = e.code
ok(code == 3, 'starter_gate при отказе без обхода → SystemExit(3): стартер дальше не идёт')
rep = json.load(open(os.path.join(outg, 'origin-check.json'), encoding='utf-8'))
ok(rep['ok'] is False and rep['refused'] == ['k2'] and rep['who'] == 'тест', 'отчёт origin-check.json записан и при отказе')
g = CO.starter_gate({'k2': {'glb': formg, 'pose_run': os.path.join(tmp, 'pose-k2')}}, who='тест', out_dir=outg, dry=True, catalog=catg, rules=R, say=lambda m: None)
ok(not g['ok'], 'dry (разбор без запуска): отказ печатается, но стартер не падает')
g = CO.starter_gate({'k2': {'glb': formg, 'pose_run': os.path.join(tmp, 'pose-k2')}}, who='тест', out_dir=outg, catalog=catg, rules=R, say=lambda m: None, allow_old='разово, решение директора, проверка')
rep = json.load(open(os.path.join(outg, 'origin-check.json'), encoding='utf-8'))
ok(g['ok'] and rep['allow_old'].startswith('разово') and 'k2' in (rep['bypass'] or {}), 'обход ключом: ворота открыты, причина и товар — в origin-check.json (для отчёта)')
try:
    CO.starter_gate({'k2': {'glb': formg, 'pose_run': os.path.join(tmp, 'pose-k2')}}, who='тест', catalog=catg, rules=R, say=lambda m: None, allow_old='коротко')
    code = None
except SystemExit as e:
    code = e.code
ok(code == 3, 'обход с причиной короче 10 знаков → всё равно отказ')

print('— стартеры круга: сторож (реестр rules/circle-origin.json → starters)')
probs = CO.starter_problems()
ok(not probs, 'боевое дерево: каждый стартер внесён, у каждого must_call вызов ворот стоит до запуска' + (': ' + '; '.join(probs) if probs else ''))
found = CO.scan_starters()
ok({'tools/assets/loop5.py', 'tools/scout/salad/stage/stage_trial.py', 'tools/assets/loop5.sh'} <= set(found), 'сканирование tools/ находит loop5.py, loop5.sh и stage_trial.py: ' + ', '.join(found))
SM = RULES['starters']
ok({m['file'] for m in SM['must_call']} == {'tools/scout/paint_run_all.py', 'tools/assets/loop5.py', 'tools/scout/salad/stage/stage_trial.py'}, 'стартеры с обязательными воротами: paint_run_all.py, loop5.py, stage_trial.py')
ok(all(len(e['why']) >= 20 for e in SM['exempt']), 'у каждого исключения причина ≥ 20 знаков')

fake = os.path.join(tmp, 'fake')
S2 = copy.deepcopy(RULES)
S2['starters']['must_call'] = [{'file': 'tools/a.py', 'entry': 'main', 'gate': 'CO.starter_gate', 'start': ['go']}]
S2['starters']['exempt'] = []


def fk(rel, text):
    p = os.path.join(fake, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'w', encoding='utf-8').write(text)


fk('tools/a.py', 'import circle_origin as CO\nfrom loop5 import x\n\n\ndef main():\n    CO.starter_gate({})\n    go()\n')
ok(CO.starter_problems(fake, S2) == [], 'модель: ворота до запуска → чисто')
fk('tools/a.py', 'from loop5 import x\n\n\ndef main():\n    go()\n')
pr = CO.starter_problems(fake, S2)
ok(len(pr) == 1 and 'без вызова проверки входа' in pr[0], 'ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: убрали вызов ворот → красный: ' + '; '.join(pr))
fk('tools/a.py', 'from loop5 import x\n\n\ndef main():\n    go()\n    CO.starter_gate({})\n')
pr = CO.starter_problems(fake, S2)
ok(len(pr) == 1 and 'ПОСЛЕ запуска' in pr[0], 'ворота стоят после запуска → красный')
fk('tools/a.py', 'from loop5 import x\n\n\ndef main():\n    # CO.starter_gate({})\n    """CO.starter_gate("""\n    go()\n')
ok(any('без вызова' in p for p in CO.starter_problems(fake, S2)), 'вызов только в комментарии/строке → не считается')
fk('tools/a.py', 'from loop5 import x\n\n\ndef other():\n    CO.starter_gate({})\n\n\ndef main():\n    go()\n')
ok(any('без вызова' in p for p in CO.starter_problems(fake, S2)), 'вызов в другой функции, не в точке входа → красный')
fk('tools/a.py', 'import circle_origin as CO\nfrom loop5 import x\n\n\ndef main():\n    CO.starter_gate({})\n    go()\n')
fk('tools/b.py', 'import subprocess\nsubprocess.run(["python", "tools/assets/loop5.py"])\n')
pr = CO.starter_problems(fake, S2)
ok(len(pr) == 1 and 'tools/b.py' in pr[0] and 'не внесён' in pr[0], 'НОВЫЙ стартер (строка-имя скрипта в команде) не внесён в реестр → красный')
S2['starters']['exempt'] = [{'file': 'tools/b.py', 'why': 'коротко'}]
ok(any('без причины' in p for p in CO.starter_problems(fake, S2)), 'исключение без причины → красный')
S2['starters']['exempt'] = [{'file': 'tools/b.py', 'why': 'разбор готового прогона, круг не запускает вовсе'}]
ok(CO.starter_problems(fake, S2) == [], 'исключение с причиной → чисто')
os.remove(os.path.join(fake, 'tools', 'b.py'))
fk('tools/c.py', 'import trellis\nKD.run_probe(a)\n')
ok(any('tools/c.py' in p for p in CO.starter_problems(fake, S2)), 'общий драйвер платных проб (.run_probe) в новом файле → красный до внесения')
os.remove(os.path.join(fake, 'tools', 'c.py'))
S2['starters']['exempt'] = []
fk('tools/w.sh', '#!/bin/bash\n# запускает loop5.py\nexec python3 something.py "$@"\n')
ok(CO.starter_problems(fake, S2) == [], '.sh: имя стартера только в комментарии → не стартер')
fk('tools/w.sh', '#!/bin/bash\nexec python3 /x/loop5.py "$@"\n')
ok(any('tools/w.sh' in p for p in CO.starter_problems(fake, S2)), '.sh с запуском loop5.py не внесён → красный')
S2['starters']['exempt'] = [{'file': 'tools/w.sh', 'wraps': 'tools/a.py', 'why': 'обёртка над стартером a.py, ворота внутри него'}]
ok(any('больше не зовёт' in p for p in CO.starter_problems(fake, S2)), 'обёртка не зовёт заявленный стартер (a.py) → красный')
fk('tools/w.sh', '#!/bin/bash\nexec python3 /x/loop5.py a.py "$@"\n')
ok(CO.starter_problems(fake, S2) == [], 'обёртка зовёт заявленный стартер → чисто')
S2['starters']['exempt'] = [{'file': 'tools/w.sh', 'wraps': 'tools/zzz.py', 'why': 'обёртка над неизвестным стартером, не из must_call'}]
ok(any('нет среди must_call' in p for p in CO.starter_problems(fake, S2)), 'обёртка над стартером не из must_call → красный')

print('— стартеры круга: проводка loop5 → stage_trial')
import loop5 as L5  # noqa: E402
l5r = L5.load_rules()
c1 = L5.stage_cmd(dict(l5r), 'sha', '07', 0, ['k1'], os.path.join(tmp, 'r5'), 'rid', None, os.path.join(tmp, 'in.json'), False)
ok('--origin-rows' not in c1 and '--allow-old-origin' not in c1, 'loop5 без ворот-аргументов: команды stage_trial без них (контроль)')
c2 = L5.stage_cmd(dict(l5r, runtime_origin_args=['--origin-rows', 'rows.json', '--allow-old-origin', 'разово, решение директора']), 'sha', '07', 0, ['k1'], os.path.join(tmp, 'r5'), 'rid', None, os.path.join(tmp, 'in.json'), False)
ok(c2[c2.index('--origin-rows') + 1] == 'rows.json' and c2[c2.index('--allow-old-origin') + 1].startswith('разово'), 'loop5 передаёт stage_trial строки входа и ключ обхода (ворота работают и на каждой ноде)')
st_src = open(os.path.join(HERE, '..', 'salad', 'stage', 'stage_trial.py'), encoding='utf-8').read()
l5_src = open(os.path.join(HERE, '..', '..', 'assets', 'loop5.py'), encoding='utf-8').read()
ok("'--allow-old-origin'" in st_src and "'--origin-rows'" in st_src and "'--allow-old-origin'" in l5_src, 'ключи --allow-old-origin / --origin-rows есть в CLI stage_trial и loop5')

print('FAIL: %d' % len(FAIL) if FAIL else 'всё ок')
sys.exit(1 if FAIL else 0)
