#!/usr/bin/env python3
"""Тесты control_words.py (контроль дня экзамена: 5 случайных листов локально vs кэш Salad). Без OCR и сети: локальное распознавание подменено, листы — временные файлы.
Запуск: python tools/scout/salad/ocr/tests_control_words.py"""
import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control_words as C  # noqa: E402
import ocr_words_run as RUN  # noqa: E402

RULES = RUN.rules_ver()


def entry(words=True, found=('кухня',), conf=0.99, n=6, rules=None, sheet='x'):
    return {'words': words, 'found': list(found), 'conf': conf, 'n_lines': n, 'rules': rules or RULES, 'sheet': sheet}


class Env:
    """N листов-файлов <dir>/<id>/plan.png с разным содержимым + кэш на все (как после Salad) + список id."""

    def __init__(self, tmp, n=8):
        self.dir = os.path.join(tmp, 'sheets')
        self.ids = [f'sh-{i}' for i in range(n)]
        self.cache = {}
        self.truth = {}
        for i, sid in enumerate(self.ids):
            os.makedirs(os.path.join(self.dir, sid))
            p = os.path.join(self.dir, sid, 'plan.png')
            with open(p, 'wb') as f:
                f.write(b'img-%d' % i)
            self.truth[p] = {'words': i % 2 == 0, 'found': ['кухня'] if i % 2 == 0 else [], 'conf': 0.9 if i % 2 == 0 else 0, 'n_lines': 5 + i}
            self.cache[RUN.sheet_sha(p)] = entry(**{'words': self.truth[p]['words'], 'found': self.truth[p]['found'], 'conf': self.truth[p]['conf'], 'n': self.truth[p]['n_lines'], 'sheet': sid})
        self.cache_path = os.path.join(tmp, 'words_flags.json')
        self.ids_path = os.path.join(tmp, 'ids.txt')
        self.save()
        with open(self.ids_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.ids) + '\n')

    def save(self):
        with open(self.cache_path, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, ensure_ascii=False)

    def args(self, **kw):
        d = dict(cache=self.cache_path, ids=self.ids_path, sheets_dirs=self.dir, n=5, seed=7, discard=False)
        d.update(kw)
        return argparse.Namespace(**d)

    def ocr(self, path):
        return dict(self.truth[path])


def run(a, ocr_fn):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = C.run(a, ocr_fn=ocr_fn)
    return rc, out.getvalue(), err.getvalue()


class T(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.env = Env(self._t.name)

    def test_pick_reproducible_distinct_and_n(self):
        a = C.pick(self.env.ids, 5, 7)
        self.assertEqual(a, C.pick(self.env.ids, 5, 7))
        self.assertEqual(len(set(a)), 5)
        self.assertNotEqual(a, C.pick(self.env.ids, 5, 8))   # другое зерно — другой выбор (при этих данных)

    def test_pick_too_few_is_error_not_pass(self):
        with self.assertRaises(C.ControlError):
            C.pick(['a', 'b'], 5, 1)

    def test_all_equal_rc0(self):
        rc, out, _ = run(self.env.args(), self.env.ocr)
        self.assertEqual(rc, 0, out)
        self.assertIn('совпало 5 из 5', out)
        self.assertIn('КОНТРОЛЬ ПРОЙДЕН', out)

    def test_conf_difference_alone_is_not_a_mismatch(self):
        loc = lambda p: {**self.env.truth[p], 'conf': self.env.truth[p]['conf'] + 0.004}
        rc, _, _ = run(self.env.args(), loc)
        self.assertEqual(rc, 0)

    def test_negative_controls_each_field_gives_rc1(self):
        for field, val in (('words', None), ('found', ['ванная']), ('n_lines', 999)):
            with self.subTest(field=field):
                chosen = C.pick(self.env.ids, 5, 7)
                bad_path = os.path.join(self.env.dir, chosen[2], 'plan.png')

                def loc(p, field=field, val=val):
                    d = dict(self.env.truth[p])
                    if p == bad_path:
                        d[field] = (not d['words']) if field == 'words' else val
                    return d
                rc, out, err = run(self.env.args(), loc)
                self.assertEqual(rc, 1, out)
                self.assertIn('КЭШ ВЫБРОСИТЬ', err)
                self.assertIn(chosen[2], err)
                self.assertIn('❌', out)

    def test_missing_in_cache_rc1(self):
        chosen = C.pick(self.env.ids, 5, 7)
        p = os.path.join(self.env.dir, chosen[0], 'plan.png')
        del self.env.cache[RUN.sheet_sha(p)]
        self.env.save()
        rc, out, err = run(self.env.args(), self.env.ocr)
        self.assertEqual(rc, 1)
        self.assertIn('нет в кэше', out)

    def test_other_rules_version_rc1(self):
        chosen = C.pick(self.env.ids, 5, 7)
        p = os.path.join(self.env.dir, chosen[1], 'plan.png')
        self.env.cache[RUN.sheet_sha(p)]['rules'] = 'deadbeef0000'
        self.env.save()
        rc, out, _ = run(self.env.args(), self.env.ocr)
        self.assertEqual(rc, 1)
        self.assertIn('правила кэша deadbeef0000', out)

    def test_broken_checks_are_rc2_not_pass(self):
        def boom(p):
            raise C.ControlError('OCR упал')
        rc, _, err = run(self.env.args(), boom)
        self.assertEqual(rc, 2)
        self.assertIn('КОНТРОЛЬ НЕ ВЫПОЛНЕН', err)
        rc, _, err = run(self.env.args(sheets_dirs=os.path.join(self._t.name, 'нет-такой')), self.env.ocr)
        self.assertEqual(rc, 2)                                   # нет файлов листов
        rc, _, _ = run(self.env.args(cache=os.path.join(self._t.name, 'нет.json')), self.env.ocr)
        self.assertEqual(rc, 2)                                   # нет кэша
        rc, _, _ = run(self.env.args(n=50), self.env.ocr)
        self.assertEqual(rc, 2)                                   # листов меньше, чем просят

    def test_discard_renames_cache_only_on_mismatch(self):
        rc, _, _ = run(self.env.args(discard=True), self.env.ocr)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.env.cache_path))      # сошлось — кэш на месте
        rc, _, err = run(self.env.args(discard=True), lambda p: {**self.env.truth[p], 'n_lines': -1})
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(self.env.cache_path))     # расхождение — кэш отложен (не удалён)
        moved = [f for f in os.listdir(self._t.name) if f.startswith('words_flags.json.DISCARDED-')]
        self.assertEqual(len(moved), 1)
        with open(os.path.join(self._t.name, moved[0]), encoding='utf-8') as f:
            self.assertEqual(len(json.load(f)), 8)
        self.assertIn('кэш отложен', err)

    def test_local_ocr_refuses_cached_answer_and_missing_python(self):
        with self.assertRaises(C.ControlError):
            C.local_ocr('x.png', python=os.path.join(self._t.name, 'нет-питона'))
        # подставной «питон»-скрипт: печатает JSON с cache=true → контроль недействителен
        fake = os.path.join(self._t.name, 'fakepy.sh')
        with open(fake, 'w', encoding='utf-8') as f:
            f.write('#!/bin/sh\necho \'{"words": true, "found": [], "conf": 1, "n_lines": 1, "cache": true}\'\n')
        os.chmod(fake, 0o755)
        with self.assertRaises(C.ControlError) as cm:
            C.local_ocr('x.png', python=fake)
        self.assertIn('недействителен', str(cm.exception))
        with open(fake, 'w', encoding='utf-8') as f:
            f.write('#!/bin/sh\necho \'{"words": true, "found": ["кухня"], "conf": 1, "n_lines": 3, "cache": false}\'\n')
        self.assertEqual(C.local_ocr('x.png', python=fake)['n_lines'], 3)

    def only_words(self, with_words):
        """Оставить слова только у листов из with_words (и в кэше, и в «локальной правде»)."""
        for sid in self.env.ids:
            p = os.path.join(self.env.dir, sid, 'plan.png')
            w = sid in with_words
            self.env.truth[p].update(words=w, found=['кухня'] if w else [], conf=0.9 if w else 0)
            self.env.cache[RUN.sheet_sha(p)].update(words=w, found=['кухня'] if w else [], conf=0.9 if w else 0)
        self.env.save()

    def seed_where(self, sid, included):
        for s in range(1, 200):
            if (sid in C.pick(self.env.ids, 5, s)) == included:
                return s
        self.fail('нет подходящего зерна')

    def test_adds_sixth_sheet_with_words_when_none_chosen(self):
        self.only_words({'sh-7'})
        seed = self.seed_where('sh-7', False)
        rc, out, _ = run(self.env.args(seed=seed), self.env.ocr)
        self.assertEqual(rc, 0, out)
        self.assertIn('добран шестой: sh-7', out)
        self.assertIn('совпало 6 из 6', out)
        self.assertIn('| sh-7 |', out)

    def test_no_extra_when_a_words_sheet_is_already_chosen(self):
        self.only_words({'sh-7'})
        rc, out, _ = run(self.env.args(seed=self.seed_where('sh-7', True)), self.env.ocr)
        self.assertEqual(rc, 0)
        self.assertIn('совпало 5 из 5', out)
        self.assertNotIn('добран', out)

    def test_no_words_anywhere_warns_and_stays_five(self):
        self.only_words(set())
        rc, out, _ = run(self.env.args(), self.env.ocr)
        self.assertEqual(rc, 0)
        self.assertIn('нет листов со словами', out)
        self.assertIn('совпало 5 из 5', out)

    def test_negative_control_mismatch_on_the_added_sixth_sheet_is_rc1(self):
        self.only_words({'sh-7'})
        seed = self.seed_where('sh-7', False)
        bad = os.path.join(self.env.dir, 'sh-7', 'plan.png')
        loc = lambda p: {**self.env.truth[p], 'found': []} if p == bad else self.env.ocr(p)
        rc, out, err = run(self.env.args(seed=seed), loc)
        self.assertEqual(rc, 1, out)
        self.assertIn('sh-7', err)

    def test_added_sheet_is_reproducible_by_seed(self):
        self.only_words({'sh-3', 'sh-7'})
        a = C.add_words_sheet(C.pick(self.env.ids, 5, 3), self.env.ids, self.env.cache, [self.env.dir], RULES, 3)
        b = C.add_words_sheet(C.pick(self.env.ids, 5, 3), self.env.ids, self.env.cache, [self.env.dir], RULES, 3)
        self.assertEqual(a, b)

    def test_uses_frozen_module_and_same_helpers(self):
        self.assertTrue(C.WORDS_PY.endswith(os.path.join('frozen', 'words_on_sheet.py')))
        self.assertTrue(os.path.exists(C.WORDS_PY))
        self.assertEqual(RUN.rules_ver(), RULES)


if __name__ == '__main__':
    unittest.main(verbosity=1)
