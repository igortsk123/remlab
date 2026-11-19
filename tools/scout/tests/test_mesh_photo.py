"""Вход мешей: одно правило выбора фото и сторож размера (ADR-0452, план mesh-input-hd-01; владелец TG 1864: «фото брать хорошее и по размеру,
маленькие в меш не пропускать, закрепить в конвейере»).

  1) Выбор поля: HD, иначе превью; пустая строка и пробелы в `image_url_hd` = нет HD (не проглатывают превью); нет обоих — нет адреса.
  2) SQL-выражение несёт `nullif` на обоих полях.
  3) Сторож на пороге и рядом: порог−1 — отсечено, порог — проходит, порог+1 — проходит; меньшая/большая сторона; порог не задан — не отсекает;
     нет размеров — не отсекает (решает другой вердикт); битый конфиг — выключен; число с `true` не порог.
  4) Вердикт: `photo_too_small` после collage/bad_cutout/tiny_object, не перекрывает их; порог null (боевой конфиг сегодня) — всё как было.
  5) Пересчёт хранимого вердикта: двигает только границу ok ↔ photo_too_small, прочее не трогает.
  6) Спрос мешей: фидовое превью из сетов заменяется HD; пустой HD — остаётся превью; товар вне базы не затронут.
  7) Сбой сторожа в ночном шаге — не ноль, а -1 с предупреждением в журнале.
  8) Каждое место выбора фото меша берёт правило из `mesh_photo` (нет собственного `coalesce(image_url_hd, …)` без `nullif`).
    python tools/scout/tests/test_mesh_photo.py"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, SCOUT)
import mesh_photo as MP  # noqa: E402
import mesh_queue as MQ  # noqa: E402
import mesh_bind as MB  # noqa: E402
import photo_fit as PF  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


# 1) выбор поля
check('HD есть — берём HD', MP.pick('https://x/hd.jpg', 'https://x/t.jpg') == ('https://x/hd.jpg', 'image_url_hd'))
check('HD пустая строка — превью', MP.pick('', 'https://x/t.jpg') == ('https://x/t.jpg', 'image_url'))
check('HD из пробелов — превью', MP.pick('   ', 'https://x/t.jpg') == ('https://x/t.jpg', 'image_url'))
check('HD None — превью', MP.pick(None, 'https://x/t.jpg') == ('https://x/t.jpg', 'image_url'))
check('оба пусты — нет адреса', MP.pick('', '') == (None, None) and MP.pick(None, None) == (None, None))
check('не строка — нет адреса, не падение', MP.pick(5, ['x']) == (None, None))
check('пробелы по краям срезаны', MP.pick(' https://x/hd.jpg ', '') == ('https://x/hd.jpg', 'image_url_hd'))

# 2) SQL
sql = MP.photo_sql('p')
check('SQL: nullif на HD и на превью, HD первым', sql == "coalesce(nullif(p.image_url_hd, ''), nullif(p.image_url, ''))", sql)
check('SQL без псевдонима таблицы', MP.photo_sql(None) == "coalesce(nullif(image_url_hd, ''), nullif(image_url, ''))")
check('SQL комнатного каталога — тот же вид', MP.photo_sql('r') == "coalesce(nullif(r.image_url_hd, ''), nullif(r.image_url, ''))")

# 3) сторож
R = {'min_cut_side_px': 512, 'measure': 'min'}
check('порог−1 (511) по меньшей стороне — отсечено', MP.check_size([511, 900], R)[0] is False)
check('ровно порог (512) — проходит', MP.check_size([512, 900], R)[0] is True)
check('порог+1 (513) — проходит', MP.check_size([513, 900], R)[0] is True)
check('порядок сторон не важен', MP.check_size([900, 511], R)[0] is False and MP.check_size([900, 512], R)[0] is True)
ok_, why = MP.check_size([300, 900], R)
check('причина называет размеры и порог', (not ok_) and '300×900' in why and '512' in why, why)
RL = {'min_cut_side_px': 512, 'measure': 'long'}
check('мера «большая сторона»: 300×900 проходит, 300×500 отсечено', MP.check_size([300, 900], RL)[0] is True and MP.check_size([300, 500], RL)[0] is False)
check('порог не задан — не отсекает ничего', MP.check_size([1, 1], {'min_cut_side_px': None, 'measure': 'min'})[0] is True)
check('нет размеров — не отсекает', MP.check_size(None, R)[0] is True and MP.check_size([], R)[0] is True and MP.check_size([5], R)[0] is True)
with tempfile.TemporaryDirectory() as td:
    bad = os.path.join(td, 'bad.json')
    open(bad, 'w').write('{не json')
    check('битый конфиг — сторож выключен', MP.load_rules(bad)['min_cut_side_px'] is None)
    check('нет файла — сторож выключен', MP.load_rules(os.path.join(td, 'none.json'))['min_cut_side_px'] is None)
    for val, want in ((512, 512), (512.0, 512), (True, None), (0, None), (-5, None), ('512', None), (None, None)):
        p = os.path.join(td, 'c.json')
        json.dump({'min_cut_side_px': val, 'measure': 'min'}, open(p, 'w'))
        check(f'порог {val!r} → {want!r}', MP.load_rules(p)['min_cut_side_px'] == want)
    p = os.path.join(td, 'm.json')
    json.dump({'min_cut_side_px': 400, 'measure': 'странно'}, open(p, 'w'))
    check('неизвестная мера → min', MP.load_rules(p)['measure'] == 'min')
check('боевой конфиг: 512 px по ДЛИННОЙ стороне (владелец 19.11, TG 1894)', MP.load_rules() == {'min_cut_side_px': 512, 'measure': 'long'}, str(MP.load_rules()))
check('боевой порог: длинная 511 — отсечено, 512 — проходит, длинная 800 при короткой 200 — проходит',
      MP.check_size([300, 511])[0] is False and MP.check_size([300, 512])[0] is True and MP.check_size([200, 800])[0] is True)

# 4) вердикт
real_rules = MP.RULES
with tempfile.TemporaryDirectory() as td:
    cfg = os.path.join(td, 'mesh-photo.json')
    json.dump({'min_cut_side_px': 512, 'measure': 'min'}, open(cfg, 'w'))
    MP.RULES = cfg
    try:
        def M(wh, **kw):
            return {'photo': {'object_wh': wh, 'object_rel_side': 0.7, 'object_share': 0.4}, **kw}
        v, why = PF.verdict_from_metrics('диван', M([400, 900]))
        check('мелкая вырезка → photo_too_small с причиной', v == 'photo_too_small' and '400' in why, f'{v} {why}')
        check('крупная вырезка → ok', PF.verdict_from_metrics('диван', M([600, 900]))[0] == 'ok')
        check('ровно порог → ok', PF.verdict_from_metrics('диван', M([512, 900]))[0] == 'ok')
        check('коллаж главнее размера', PF.verdict_from_metrics('диван', M([100, 100], collage={'verdict': True, 'why': ['a', 'b']}))[0] == 'collage')
        check('брак маски главнее размера', PF.verdict_from_metrics('диван', M([100, 100], verdict='bad', reason='r'))[0] == 'bad_cutout')
        tiny = {'photo': {'object_wh': [100, 100], 'object_rel_side': 0.1, 'object_share': 0.4}}
        check('tiny_object главнее размера', PF.verdict_from_metrics('диван', tiny)[0] == 'tiny_object')
        check('нет object_wh — вердикт как раньше (ok)', PF.verdict_from_metrics('диван', {'photo': {'object_rel_side': 0.7, 'object_share': 0.4}})[0] == 'ok')
        # 5) пересчёт хранимого
        rows = [('s1', 'a1', 'диван', 'ok', json.dumps(M([400, 900]))),                 # → too_small
                ('s2', 'a1', 'диван', 'ok', json.dumps(M([700, 900]))),                 # остаётся ok
                ('s3', 'a1', 'диван', 'photo_too_small', json.dumps(M([700, 900]))),    # порог ослабили → ok
                ('s4', 'a1', 'диван', 'collage', json.dumps(M([100, 100]))),            # не трогаем
                ('s5', 'a1', 'диван', 'ok', '{не json'),                                # битое — пропуск
                ('s6', 'a1', 'диван', 'bad_cutout', json.dumps(M([700, 900])))]         # не трогаем
        plan = PF.reverdict_plan(rows)
        check('пересчёт: ok→too_small и too_small→ok, остальное нетронуто', plan == [('s1', 'a1', 'photo_too_small'), ('s3', 'a1', 'ok')], str(plan))
    finally:
        MP.RULES = real_rules
# боевой конфиг: сторож только для ролей с генерацией меша
live = lambda role, wh: PF.verdict_from_metrics(role, {'photo': {'object_wh': wh, 'object_rel_side': 0.7, 'object_share': 0.4}})[0]
check('боевой конфиг: диван 400×500 → photo_too_small, 400×512 → ok', live('диван', [400, 500]) == 'photo_too_small' and live('диван', [400, 512]) == 'ok')
check('боевой конфиг: зеркало и ковёр (плоскость, без генерации меша) размером не отсекаются', live('зеркало', [100, 200]) == 'ok' and live('ковёр', [100, 200]) == 'ok')
check('боевой конфиг: роль неизвестна (пусто) — не судим', live('', [100, 200]) == 'ok' and live(None, [100, 200]) == 'ok')
check('пересчёт по боевому конфигу двигает только роли с мешем',
      PF.reverdict_plan([('a', 'a1', 'диван', 'ok', json.dumps({'photo': {'object_wh': [10, 10]}})),
                         ('b', 'a1', 'зеркало', 'ok', json.dumps({'photo': {'object_wh': [10, 10]}}))]) == [('a', 'a1', 'photo_too_small')])

# 6) спрос мешей
orig_db = MQ.db
MQ.db = lambda sql: [['1:a', '', 'https://x/a-thumb.jpg'], ['1:b', 'https://x/b-hd.jpg', 'https://x/b-thumb.jpg']]
want = {'1:a': {'image_url': 'https://old/a'}, '1:b': {'image_url': 'https://x/b-thumb.jpg'}, '1:c': {'image_url': 'https://x/c-thumb.jpg'}}
MQ.prefer_hd(want)
MQ.db = orig_db
check('превью из сетов заменено HD', want['1:b']['image_url'] == 'https://x/b-hd.jpg')
check('пустой image_url_hd — остаётся превью, не пустой адрес', want['1:a']['image_url'] == 'https://x/a-thumb.jpg')
check('товар, которого нет в базе, не затронут', want['1:c']['image_url'] == 'https://x/c-thumb.jpg')
check('пустой спрос — без запроса к базе', MQ.prefer_hd({}) == {})

# 7) сбой сторожа
orig = PF._db
PF._db = lambda sql: (_ for _ in ()).throw(RuntimeError('нет базы'))
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    got = MQ.size_guard()
PF._db = orig
check('сбой сторожа — -1 и предупреждение, не молчание и не 0', got == -1 and 'ПРЕДУПРЕЖДЕНИЕ' in buf.getvalue(), buf.getvalue())

# 7b) сбой гибридной маски виден
check('hybrid_error из измерений вынимается', MP.hybrid_error({'hybrid_error': 'RuntimeError: x'}) == 'RuntimeError: x')
check('нет сбоя / не словарь / пустая строка — None', MP.hybrid_error({}) is None and MP.hybrid_error(None) is None and MP.hybrid_error({'hybrid_error': ''}) is None)

# 7c) ворота «требуется меш» (mesh_bind): фото есть, если есть HD ИЛИ превью (7 товаров были с одним HD)
gate = MB.catalog_gates_sql(['диван'], [])
check('ворота mesh_bind: «фото есть» — по общему правилу (HD или превью), не по одному превью',
      MP.photo_sql('p') + ' is not null' in gate and 'p.image_url is not null' not in gate, gate[:160])

# 8) все места берут правило из mesh_photo
BAD = re.compile(r"coalesce\(\s*[a-z]*\.?image_url_hd\s*,\s*[a-z]*\.?image_url\b")   # coalesce(image_url_hd, image_url) без nullif — пустая строка проглатывает превью
PLACES = ['mesh_queue.py', 'photo_hash.py', 'catalog_media.py', 'mesh_priority.py', 'mesh_bind.py', 'mesh_pilot.py', 'cutout_sync.py', 'mesh_review_sync.py', 'mesh_quarantine.py', 'mesh_audit_sync.py',
          'orient_review.py', 'photo_review_page.py', 'photo_bg.py', 'pipeline_map.py', 'room_mesh_demand.py', 'room_mesh_jobs.py', 'photo_fit.py',
          os.path.join('salad', 'cutout_probe.py'), os.path.join('salad', 'blocked_page.py')]
for rel in PLACES:
    src = open(os.path.join(SCOUT, rel), encoding='utf-8').read()
    code = '\n'.join(ln for ln in src.split('\n') if not ln.lstrip().startswith('#'))
    # кавычки-строки с описанием в докстринге не считаем: ищем только в строках с кодом SQL (кавычка в начале строки или присваивание)
    hits = [ln.strip() for ln in code.split('\n') if BAD.search(ln) and not ln.strip().startswith(('Хеш', '`', '-'))]
    check(f'{rel}: берёт правило из mesh_photo', 'import mesh_photo as MP' in src or rel == 'catalog_media.py', rel)
    check(f'{rel}: нет собственного coalesce(image_url_hd, …) без nullif', not hits, '; '.join(hits[:2]))
cm = open(os.path.join(SCOUT, 'catalog_media.py'), encoding='utf-8').read()
check("catalog_media: отдаёт оригинал отдельным ключом img_hd, а превью витрины 'img' не тронуто",
      "'img_hd'" in cm and "{'img': p[2] or None," in cm and 'coalesce(p.image_url_hd' in cm)

print('итог:', 'OK' if not fails else f'ПРОВАЛОВ {fails}')
sys.exit(1 if fails else 0)
