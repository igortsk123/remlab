#!/usr/bin/env python3
"""Защита от комплектующих (T-20261124-08/2, правило Г): положительные и отрицательные примеры, предохранители, идемпотентность, возврат,
липкость load3/category_map, выключатель шага ночи. Чистая часть — без БД (CI). Интеграция на настоящем postgres — только при
`CG_TEST_CONTAINER=<имя одноразового контейнера>` (CI её пропускает; запуск: см. docstring класса DbIntegration).

  python3 tools/scout/tests/test_component_guard.py
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.dirname(HERE)
sys.path.insert(0, SCOUT)
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_component_guard')                                                  # временное — в REMLAB_TMP, с уборкой (T-20261107-13)
import component_guard as CG  # noqa: E402
import dimless  # noqa: E402

RULES = CG.load_rules()
MDM = 96431


def grp(shop, leaf, role, n, m, names, prior_n=0, prior_wh=0, comp_n=0, new_n=None):
    return dict(shop=shop, leaf=leaf, role=role, n=n, m=m, comp_n=comp_n, new_n=n - comp_n if new_n is None else new_n,
                prior_n=prior_n, prior_wh=prior_wh, names=names)


def judge(groups, paths, rules=None):
    stats = {k: (g['n'], g['m']) for k, g in groups.items()}
    return CG.evaluate(groups, dimless.decide(stats, paths), rules or RULES, paths)


def one(rows, cid):
    return next(r for r in rows if r['cid'] == cid)


P = 'Шкафы. Гардеробные. Двери / '
SHAFT = P + 'Наполнение для шкафов / Штанги'
UNICO = P + 'Стеллажные и гардеробные системы / Стеллажная система UNICO'


class Rule(unittest.TestCase):
    def test_ancestor_role_hardware_is_demoted(self):
        g = {(MDM, 'a'): grp('mdm', 'Штанги', 'шкаф', 88, 0, ['Штанга овальная 25х15', 'Штангодержатель для круглой трубы', 'ВОГ штангодержатель'] * 3,
                              prior_n=42, prior_wh=0)}
        r = one(judge(g, {(MDM, 'a'): SHAFT}), 'a')
        self.assertEqual(r['verdict'], 'снять')
        self.assertTrue(r['ancestor'])
        self.assertIn('предка', r['reason'])

    def test_ancestor_group_without_component_words_is_still_demoted(self):
        # сигнал «предок при неподтверждённом листе» достаточен и без слов (названия мелких категорий mdm: «ps 23», «икм 15»)
        g = {(MDM, 'b'): grp('mdm', 'Система PS23', 'шкаф', 6, 0, ['PS 23 комплект', 'PS23 фолд'], prior_n=2, prior_wh=0)}
        self.assertEqual(one(judge(g, {(MDM, 'b'): P + 'Раздвижные системы для шкафов / Система PS23 для складных дверей'}), 'b')['verdict'], 'снять')

    def test_leaf_confirms_role_but_names_are_components_by_words(self):
        # 61 товар mdm: «Стеллажная система UNICO» — роль дал сам лист, но это полкодержатели и крепления
        g = {(MDM, 'c'): grp('mdm', 'Стеллажная система UNICO', 'стеллаж', 32, 0, ['UNICO полкодержатель 1', 'UNICO угловое крепление', 'UNICO профиль'] * 2,
                              prior_n=4, prior_wh=0)}
        r = one(judge(g, {(MDM, 'c'): UNICO}), 'c')
        self.assertFalse(r['ancestor'])
        self.assertEqual(r['verdict'], 'снять')
        self.assertIn('слов-комплектующих', r['reason'])

    def test_real_modular_wardrobe_without_sizes_is_kept(self):
        # divan.ru «Модульные гостиные»: 24 настоящих предмета без размеров — лист подтверждает «стенка», слов-комплектующих нет
        g = {(1, 'm'): grp('divan.ru', 'Модульные гостиные', 'стенка', 24, 0, ['Модульная гостиная Лофт 3', 'Модульная гостиная Ларго'], prior_n=0)}
        r = one(judge(g, {(1, 'm'): 'Мебель для гостиной / Модульные гостиные'}), 'm')
        self.assertEqual(r['verdict'], 'держим')
        self.assertIn('лист подтверждает', r['reason'])

    def test_group_with_measured_sizes_is_not_quarantined_even_if_ancestor_role(self):
        # divan.ru «Гардеробные системы» (Корпусная мебель / Шкафы / …): роль от предка, размеры у 37 из 42
        g = {(1, 'g'): grp('divan.ru', 'Гардеробные системы', 'шкаф', 42, 37, ['Модуль для гардеробной системы'] * 5)}
        r = one(judge(g, {(1, 'g'): 'Корпусная мебель / Шкафы / Гардеробные системы'}), 'g')
        self.assertEqual(r['verdict'], 'не в карантине')
        self.assertTrue(r['ancestor'])

    def test_word_sistema_alone_is_not_a_signal(self):
        # Codex п.2: «система хранения» бывает мебелью — слова «систем» в словаре нет; лист подтверждает роль, слов-комплектующих нет
        self.assertFalse(any('систем' in w for w in RULES['words']))
        g = {(2, 's'): grp('shop', 'Системы хранения шкафов', 'шкаф', 9, 0, ['Система хранения Лофт', 'Система хранения Хит'])}
        self.assertEqual(one(judge(g, {(2, 's'): 'Мебель / Системы хранения шкафов'}), 's')['verdict'], 'держим')

    def test_feed_outage_with_earlier_sizes_pauses_removal(self):
        # настоящая мебель магазина с ролью от предка потеряла размеры (сбой фида): прежде 90 % строк с Ш×В — НЕ снимать, строка WARN
        g = {(3, 'o'): grp('furn', 'Гардеробные системы', 'шкаф', 30, 0, ['Модуль шкафа'] * 3, prior_n=20, prior_wh=18)}
        rows = judge(g, {(3, 'o'): 'Корпусная мебель / Шкафы / Гардеробные системы'})
        r = one(rows, 'o')
        self.assertEqual(r['verdict'], 'держим')
        self.assertTrue(r['paused'])
        self.assertTrue(any('приостановлено' in ln for ln in CG.digest(rows, applied=True)))
        self.assertEqual(CG.apply_sql(rows), '')

    def test_small_categories_follow_dimless_branch_rule(self):
        # n < MIN_N: решает ветка/магазин (тот же dimless.decide); одиночный товар в ветке без размеров — снимается по предку
        g = {(MDM, 'x'): grp('mdm', 'Система ONE', 'шкаф', 1, 0, ['Уан комплект']),
             (MDM, 'y'): grp('mdm', 'Система MINI', 'шкаф', 6, 0, ['Мини шоп'] * 6)}
        rows = judge(g, {(MDM, 'x'): P + 'Раздвижные системы для шкафов / Система ONE', (MDM, 'y'): P + 'Раздвижные системы для шкафов / Система MINI'})
        self.assertEqual({r['cid']: r['verdict'] for r in rows}, {'x': 'снять', 'y': 'снять'})

    def test_textile_roles_are_outside_the_population(self):
        self.assertFalse({'ковёр', 'плед', 'подушка', 'шторы'} & set(dimless.ROLES))
        self.assertIn('cat_role = any(array[', CG.stats_sql(True))

    def test_overrides_and_mixed_keys_are_not_ancestor(self):
        self.assertFalse(CG.ancestor_role(P + 'Наполнение', 'шкаф', '96431:1476'))      # OVERRIDES — точечно
        self.assertFalse(CG.ancestor_role('', 'шкаф', '1:1'))
        self.assertTrue(CG.ancestor_role(SHAFT, 'шкаф', '1:1'))
        self.assertFalse(CG.ancestor_role(SHAFT, 'стеллаж', '1:1'))                      # роль группы другая — не наш случай


class Cycle(unittest.TestCase):
    def test_idempotent_second_run_has_no_new_removals(self):
        g = {(MDM, 'a'): grp('mdm', 'Штанги', 'шкаф', 88, 0, ['Штанга'] * 4, prior_n=42, prior_wh=0, comp_n=88, new_n=0)}   # уже все component
        rows = judge(g, {(MDM, 'a'): SHAFT})
        self.assertEqual(one(rows, 'a')['verdict'], 'снять')
        self.assertEqual(CG.apply_sql(rows), '')                                            # новых нет → SQL пустой
        self.assertEqual(CG.digest(rows, applied=True), [])

    def test_return_when_sizes_arrive(self):
        # у снятых строк появились измеренные Ш×В — категория вне карантина → роль возвращается из role_before
        g = {(MDM, 'a'): grp('mdm', 'Штанги', 'шкаф', 88, 40, ['Штанга'] * 4, comp_n=88, new_n=0)}
        rows = judge(g, {(MDM, 'a'): SHAFT})
        self.assertEqual(one(rows, 'a')['verdict'], 'вернуть')
        sql = CG.apply_sql(rows)
        self.assertIn('cat_role = p.role_before', sql)
        self.assertIn("product_kind = 'component'", sql)
        self.assertNotIn('role_before = p.cat_role', sql)

    def test_return_when_prior_sizes_show_it_was_an_outage(self):
        g = {(MDM, 'a'): grp('mdm', 'Штанги', 'шкаф', 88, 0, ['Штанга'] * 4, prior_n=10, prior_wh=9, comp_n=88, new_n=0)}
        self.assertEqual(one(judge(g, {(MDM, 'a'): SHAFT}), 'a')['verdict'], 'вернуть')

    def test_apply_sql_shape_and_quoting(self):
        g = {(MDM, "o'neil"): grp('mdm', 'Штанги', 'шкаф', 6, 0, ['Штанга'] * 6)}
        rows = judge(g, {(MDM, "o'neil"): SHAFT})
        sql = CG.apply_sql(rows)
        self.assertTrue(sql.startswith('begin;') and sql.rstrip().endswith('commit;'))
        self.assertIn("'o''neil'", sql)
        self.assertIn('role_before = p.cat_role, cat_role = null', sql)
        self.assertIn('p.cat_role is not null and p.product_kind is null', sql)            # только строки с ролью и ещё не снятые
        self.assertNotIn('delete', sql.lower())

    def test_digest_lines_go_to_night_digest(self):
        g = {(MDM, 'a'): grp('mdm-complect.ru', 'Штанги', 'шкаф', 88, 0, ['Штанга'] * 4, prior_n=42, prior_wh=0)}
        lines = CG.digest(judge(g, {(MDM, 'a'): SHAFT}), applied=True)
        self.assertTrue(lines and all(ln.startswith('WARN:component_guard: ') for ln in lines))
        self.assertIn('88 товаров', lines[0])


class Safety(unittest.TestCase):
    def rows(self, n_new, shop_total=None):
        g = {(MDM, 'a'): grp('mdm', 'Штанги', 'шкаф', n_new, 0, ['Штанга'] * 3, prior_n=1, prior_wh=0)}
        if shop_total:
            g[(MDM, 'z')] = grp('mdm', 'Шкафы', 'шкаф', shop_total - n_new, shop_total - n_new, ['Шкаф'])
        return judge(g, {(MDM, 'a'): SHAFT, (MDM, 'z'): 'Корпусная мебель / Шкафы'})

    def test_big_first_run_needs_explicit_allow(self):
        ok, why = CG.safety(self.rows(824), RULES)
        self.assertFalse(ok)
        self.assertTrue(any('потолка' in w for w in why) and any('магазин' in w for w in why))
        self.assertTrue(CG.safety(self.rows(824), RULES, allow_new=824)[0])
        self.assertFalse(CG.safety(self.rows(824), RULES, allow_new=100)[0])

    def test_small_steady_state_passes(self):
        self.assertTrue(CG.safety(self.rows(5, shop_total=1000), RULES)[0])

    def test_share_limit_catches_whole_shop(self):
        ok, why = CG.safety(self.rows(150, shop_total=300), RULES)                         # 150 < 200 абс., но 50 % магазина
        self.assertFalse(ok)
        self.assertTrue(any('магазин' in w for w in why))


class Wiring(unittest.TestCase):
    def test_rules_shape(self):
        self.assertIsInstance(RULES['enabled'], bool)
        for k in ('min_share_names', 'max_prior_dims_share'):
            self.assertTrue(0 < RULES[k] <= 1)
        self.assertTrue(RULES['limits']['max_new_abs'] > 0 and 0 < RULES['limits']['max_new_share'] <= 1)
        rx = CG.words_rx(RULES)
        self.assertTrue(rx.search('Направляющая нижняя') and rx.search('Крепёж для штанги') and not rx.search('Шкаф-купе Лофт'))
        self.assertFalse(rx.search('Подкроватный ящик'), 'левая граница слова: «ящик» не содержит «ящ…» слов из словаря')

    def test_nightly_off_touches_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'r.json')
            json.dump(dict(RULES, enabled=False), open(p, 'w'))
            old = (CG.RULES_PATH, CG.db, subprocess.run)
            CG.RULES_PATH = p
            CG.db = lambda *_: self.fail('выключенный шаг не должен читать базу')
            CG.subprocess.run = lambda *a, **k: self.fail('выключенный шаг не должен запускать psql')
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    rc = CG.main(['--nightly'])
            finally:
                CG.RULES_PATH, CG.db, CG.subprocess.run = old
            self.assertEqual(rc, 0)
            self.assertIn('выключен', buf.getvalue())

    def test_pre_migration_report_query_has_no_new_columns(self):
        before, after = CG.stats_sql(False), CG.stats_sql(True)
        for col in ('product_kind', 'role_before'):
            self.assertNotIn(col, before)
            self.assertIn(col, after)
        self.assertNotIn('product_kind', CG.names_sql([(1, '2')], False))

    def test_apply_refuses_without_columns(self):
        old = CG.plan
        CG.plan = lambda **k: ([], False)
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = CG.cmd_apply(RULES)
        finally:
            CG.plan = old
        self.assertEqual(rc, 1)
        self.assertIn('миграция', buf.getvalue())

    def test_stickiness_sql_in_load3_and_category_map_checks_the_column(self):
        for fn in ('load3.py', 'category_map.py'):
            src = open(os.path.join(SCOUT, fn), encoding='utf-8').read()
            self.assertIn("column_name = 'product_kind'", src, fn)
            self.assertIn("''component''", src, fn)
        import category_map as CM
        self.assertIn('information_schema.columns', CM.STICKY_COMPONENT_SQL)
        self.assertIn('execute', CM.STICKY_COMPONENT_SQL)                                 # динамически: колонки нет — SQL не разбирается

    def test_step_wired_in_nightly_after_dimless(self):
        src = open(os.path.join(SCOUT, 'refresh_daily.sh'), encoding='utf-8').read()
        a, b = src.index('step dimless '), src.index('step component_guard ')
        self.assertTrue(a < b < src.index('step dim_prior_cal '))
        self.assertIn('component_guard.py --nightly', src)

    def test_migration_is_idempotent_and_nullable(self):
        sql = open(os.path.join(SCOUT, '019-product-kind.sql'), encoding='utf-8').read().lower()
        self.assertEqual(len(re.findall(r'add column if not exists', sql)), 3)
        self.assertFalse(re.search(r'\btext\s+(not null|default)', sql), 'колонки nullable, без default: обычный товар = NULL')
        self.assertNotIn('update products set', sql.split('откат')[0].replace('--', ''), 'миграция данных не меняет')

    def test_no_shop_or_category_ids_in_code(self):
        src = open(os.path.join(SCOUT, 'component_guard.py'), encoding='utf-8').read()
        self.assertFalse(re.search(r"\b96431\b|mdm-complect|112923|93965|99272", src), 'ID/имя магазина в коде — заплатка')


# ----------------------------------------------------------------------------------------------------------------------------------
@unittest.skipUnless(os.environ.get('CG_TEST_CONTAINER'), 'нужен одноразовый postgres: CG_TEST_CONTAINER=<контейнер>')
class DbIntegration(unittest.TestCase):
    """Настоящий SQL на одноразовом postgres (НЕ боевая база): до миграции — отчёт работает, apply отказывает; после миграции — снятие,
    липкость (load3/category_map возвращают роль, SQL липкости гасит), идемпотентность, возврат при появлении размеров, предохранитель.
    Запуск (pakardev):  docker run -d --name cg-test-pg -e POSTGRES_USER=remlab -e POSTGRES_PASSWORD=x -e POSTGRES_DB=remlab --tmpfs /var/lib/postgresql/data pgvector/pgvector:pg17
                       CG_TEST_CONTAINER=cg-test-pg python3 tools/scout/tests/test_component_guard.py DbIntegration ; docker stop cg-test-pg"""

    @classmethod
    def setUpClass(cls):
        cls.c = os.environ['CG_TEST_CONTAINER']
        CG.PSQL[3] = cls.c                                                                # ['docker','exec','-i',<контейнер>,…]
        cls.td = tempfile.mkdtemp(prefix='cg-it-')
        roles = {f'{MDM}:1': dict(mid=MDM, id='1', path=SHAFT, role='шкаф'), f'{MDM}:2': dict(mid=MDM, id='2', path=P + 'Раздвижные системы для шкафов / Система PS48', role='шкаф'),
                 '7:3': dict(mid=7, id='3', path='Мебель для гостиной / Модульные гостиные', role='стенка'),
                 '7:4': dict(mid=7, id='4', path='Корпусная мебель / Шкафы / Гардеробные системы', role='шкаф')}
        cls.rp = os.path.join(cls.td, 'category-roles.json')
        json.dump(roles, open(cls.rp, 'w', encoding='utf-8'), ensure_ascii=False)
        dimless._paths = lambda: {(int(r['mid']), str(r['id'])): r['path'] for r in roles.values()}
        cls.sql('drop table if exists products; create table products (shop_mid int, external_id text, shop text, category_id int, category_path text, name text, '
                "status text default 'active', in_stock bool default true, w_cm real, d_cm real, h_cm real, len_cm real, dia_cm real, dims_evidence jsonb, cat_role text, "
                'primary key (shop_mid, external_id));')
        rows = []
        for i in range(12):
            rows.append(f"({MDM},'a{i}','mdm',1,'Штанги','Штанга овальная {i}','active',true,null,null,null,null,null,null,'шкаф')")
        for i in range(6):
            rows.append(f"({MDM},'b{i}','mdm',2,'PS48','PS48 направляющая {i}','active',true,null,null,null,null,null,null,'шкаф')")
        for i in range(24):
            rows.append(f"(7,'c{i}','divan.ru',3,'Модульные гостиные','Модульная гостиная {i}','active',true,null,null,null,null,null,null,'стенка')")
        for i in range(10):
            rows.append(f"(7,'d{i}','divan.ru',4,'Гардеробные системы','Модуль гардероба {i}','active',true,80,40,200,null,null,null,'шкаф')")
        cls.sql('insert into products values ' + ','.join(rows) + ';')

    @classmethod
    def sql(cls, s):
        r = subprocess.run(['docker', 'exec', '-i', cls.c, 'psql', '-U', 'remlab', '-d', 'remlab', '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '|'],
                           input=s, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return [ln.split('|') for ln in r.stdout.strip().split('\n') if ln]

    def run_apply(self, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = CG.cmd_apply(CG.load_rules(), **kw)
        return rc, buf.getvalue()

    def test_full_cycle(self):
        rules = CG.load_rules()
        rows, kc = CG.plan(rules=rules)                                                    # 1. до миграции: отчёт работает на реальном SQL
        self.assertFalse(kc)
        self.assertEqual(sorted(r['verdict'] for r in rows), ['держим', 'не в карантине', 'снять', 'снять'])
        rc, out = self.run_apply()                                                         # apply до миграции — отказ, данные целы
        self.assertEqual(rc, 1)
        self.assertEqual(self.sql("select count(*) from products where cat_role is not null")[0][0], '52')
        self.sql(open(os.path.join(SCOUT, '019-product-kind.sql'), encoding='utf-8').read())   # 2. миграция (на одноразовой базе)
        self.sql(open(os.path.join(SCOUT, '019-product-kind.sql'), encoding='utf-8').read())   #    идемпотентна
        rc, out = self.run_apply()                                                         # 3. предохранитель: 18 из 52 мебельных строк магазина mdm (100 %) без разрешения — стоп
        self.assertEqual((rc, self.sql("select count(*) from products where product_kind = 'component'")[0][0]), (0, '0'))
        self.assertIn('предохранитель', out)
        rc, out = self.run_apply(allow_new=18)                                             # 4. с разрешением — снято 18, divan.ru не тронут
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.sql("select shop, count(*) filter (where product_kind = 'component'), count(*) filter (where cat_role is not null), "
                                  "count(*) filter (where role_before = 'шкаф') from products group by 1 order by 1"), [['divan.ru', '0', '34', '0'], ['mdm', '18', '0', '18']])
        self.assertEqual(self.sql("select count(*) from products where status = 'active'")[0][0], '52')   # строки на месте, не в архиве
        self.assertEqual(self.sql("select count(*) from products where product_kind = 'component' and kind_reason like 'карантин без размеров%предка%'")[0][0], '18')   # причина записана
        self.sql("update products set cat_role = 'шкаф' where shop_mid = %d;" % MDM)    # 5. «ночной load3» вернул роль из карты…
        import category_map as CM
        self.sql(CM.STICKY_COMPONENT_SQL)                                                  #    …липкость гасит её
        self.assertEqual(self.sql("select count(*) from products where shop_mid = %d and cat_role is not null" % MDM)[0][0], '0')
        rc, out = self.run_apply()                                                         # 6. идемпотентность: повтор — 0 новых
        self.assertIn('снято новых 0', out)
        self.sql("update products set w_cm = 50, h_cm = 20 where shop_mid = %d and category_id = 2;" % MDM)   # 7. у группы PS48 появились размеры
        rc, out = self.run_apply()
        self.assertIn('возвращено 6', out)
        self.assertEqual(self.sql("select category_id, count(*) filter (where cat_role = 'шкаф'), count(*) filter (where product_kind = 'component') "
                                  "from products where shop_mid = %d group by 1 order by 1" % MDM), [['1', '0', '12'], ['2', '6', '0']])
        self.sql("update products set status = 'archived' where shop_mid = 7 and category_id = 4;")


if __name__ == '__main__':
    unittest.main(verbosity=1)
