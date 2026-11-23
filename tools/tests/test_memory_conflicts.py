#!/usr/bin/env python3
"""Тест сторожа конфликтов канона (tools/memory-conflicts.py): заглушки во временной папке + реальный реестр сверяется с реальным деревом.

  python3 tools/tests/test_memory_conflicts.py
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
spec = importlib.util.spec_from_file_location('memory_conflicts', os.path.join(ROOT, 'tools', 'memory-conflicts.py'))
MC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MC)

REG = {
    'version': 1,
    'scan': {'roots': ['.memory_bank'], 'exclude_dirs': ['archive'], 'history_paths': ['.memory_bank/lessons/*']},
    'history_markers': ['устарел', '~~', 'до \\d{1,2}\\.\\d{1,2}'],
    'history_headings': ['истори', '^ход\\b'],
    'facts': [
        {'id': 'ut-off', 'claim': 'UltraTex выключен', 'canon': [{'file': '.memory_bank/canon.md', 'phrase': 'выключен по умолчанию'}],
         'forbidden': [{'pattern': 'UltraTex\\s+красит', 'why': 'выключен'}, {'pattern': '1024\\s*[·x]\\s*20\\b', 'why': 'режим снят'}]},
        {'id': 'cal', 'claim': 'Ш0', 'canon': [{'file': '.memory_bank/canon.md', 'phrase': 'до калибровки'}], 'exempt_markers': ['калибр'],
         'forbidden': [{'pattern': 'Ш0[^\\n]{0,60}только автоматическ', 'why': 'до калибровки глаз'}]},
    ],
}


_DIRS = []


def make(files: dict, reg=None):
    d = tempfile.mkdtemp(prefix='mc-test-')
    _DIRS.append(d)
    for rel, text in {'.memory_bank/canon.md': 'UltraTex выключен по умолчанию. Ш0 — глаз до калибровки.\n', **files}.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(text)
    rp = os.path.join(d, 'facts.json')
    with open(rp, 'w', encoding='utf-8') as fh:
        json.dump(reg or REG, fh, ensure_ascii=False)
    return d, rp


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = MC.main(argv)
    return rc, out.getvalue(), err.getvalue()


class T(unittest.TestCase):
    def test_conflict_reports_file_line(self):
        d, rp = make({'.memory_bank/core/a.md': 'ok\nстрока\nUltraTex красит всё\n'})
        res = MC.check(d, MC.load(rp))
        self.assertEqual([(c['file'], c['line'], c['fact']) for c in res['conflicts']], [('.memory_bank/core/a.md', 3, 'ut-off')])
        rc, out, _ = run(['--root', d, '--facts-file', rp, '--check'])
        self.assertEqual(rc, 1)
        self.assertIn('.memory_bank/core/a.md:3 [ut-off]', out)

    def test_clean_tree_is_zero(self):
        d, rp = make({'.memory_bank/core/a.md': 'UltraTex выключен, не красит.\n'})
        self.assertEqual(run(['--root', d, '--facts-file', rp, '--check'])[0], 0)

    def test_history_marker_heading_and_canon_ok(self):
        d, rp = make({'.memory_bank/core/a.md': (
            'UltraTex красит — устарело 22.11\n'                       # метка истории в строке
            '~~UltraTex красит~~\n'
            '## История\nUltraTex красит; 1024·20\n'                   # блок под заголовком истории
            '## Ход 22.11\nUltraTex красит\n'
            '## Как сейчас\nвсё хорошо\n'
            '<!-- canon-ok: ut-off цитата для сравнения -->\nUltraTex красит\n'   # явное исключение строкой выше
            'UltraTex красит <!-- canon-ok: ut-* ту же строку -->\n')})
        self.assertEqual(MC.check(d, MC.load(rp))['conflicts'], [])

    def test_history_heading_block_ends_at_same_level(self):
        d, rp = make({'.memory_bank/core/a.md': '## История\nUltraTex красит\n## Канон\nUltraTex красит\n'})
        res = MC.check(d, MC.load(rp))
        self.assertEqual([c['line'] for c in res['conflicts']], [4])

    def test_excluded_dirs_and_history_paths_skipped(self):
        d, rp = make({'.memory_bank/archive/old.md': 'UltraTex красит\n', '.memory_bank/lessons/l.md': 'UltraTex красит\n'})
        self.assertEqual(MC.check(d, MC.load(rp))['conflicts'], [])

    def test_fact_specific_exempt_marker(self):
        d, rp = make({'.memory_bank/core/a.md': 'Ш0 — только автоматическая приёмка\nШ0 — только автоматическая приёмка после калибровки\n'})
        self.assertEqual([c['line'] for c in MC.check(d, MC.load(rp))['conflicts']], [1])

    def test_canon_lost_fails(self):
        d, rp = make({'.memory_bank/canon.md': 'канон переписали\n'})
        res = MC.check(d, MC.load(rp))
        self.assertEqual(sorted(c['fact'] for c in res['canon_lost']), ['cal', 'ut-off'])
        self.assertEqual(run(['--root', d, '--facts-file', rp, '--check'])[0], 1)
        os.remove(os.path.join(d, '.memory_bank/canon.md'))
        self.assertIn('канон-файла нет', MC.check(d, MC.load(rp))['canon_lost'][0]['why'])

    def test_warn_mode_does_not_block_but_strict_does(self):
        d, rp = make({'.memory_bank/core/a.md': 'UltraTex красит\n'}, {**REG, 'mode': 'warn'})
        rc, out, err = run(['--root', d, '--facts-file', rp, '--check'])
        self.assertEqual(rc, 0)
        self.assertIn('a.md:1', out)
        self.assertIn('warn', err)
        self.assertEqual(run(['--root', d, '--facts-file', rp, '--strict'])[0], 1)

    def test_broken_registry_is_2(self):
        d, rp = make({})
        with open(rp, 'w', encoding='utf-8') as fh:
            fh.write('{"facts": [{"id": "x", "canon": [], "forbidden": [{"pattern": "(", "why": "w"}]}]}')
        rc, _, err = run(['--root', d, '--facts-file', rp, '--check'])
        self.assertEqual(rc, 2)
        self.assertIn('ОШИБКА', err)
        with open(rp, 'w', encoding='utf-8') as fh:
            fh.write('не json')
        self.assertEqual(run(['--root', d, '--facts-file', rp])[0], 2)

    def test_real_registry_valid_and_canon_present(self):
        reg = MC.load()                                   # схема реального реестра
        res = MC.check(ROOT, reg)
        self.assertEqual(res['canon_lost'], [], 'канон-файл или ключевая фраза из реестра пропали — обнови реестр вместе с каноном')
        self.assertTrue({'ultratex-off', 'director-by-header', 'sh0-not-auto-before-calibration'} <= {f['id'] for f in reg['facts']})
        for f in reg['facts']:
            self.assertNotRegex(json.dumps(f, ensure_ascii=False), r'\d{5,}', 'в реестре не должно быть идентификаторов товаров')


def tearDownModule():
    for d in _DIRS:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=1)
