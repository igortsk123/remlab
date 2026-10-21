#!/usr/bin/env python3
"""Пути банка комплектов для «нового банка рядом» — одно место (план conv-13, п.1/4/5).

ЗАЧЕМ. Живой банк `sets3.json` читают ночной конвейер, экзамен, демо и тесты планировщика. Новый банк собирается рядом
(`sets3.next.json`) и до подмены ⚑ владельцем не должен ни перезаписать живой, ни испортить общие файлы прогона:
`demo-sets.json`, раскладки `v3set{n}-layout.json`, снимок экзамена `sets3.snapshot.json`, `scene-durations.json`,
отчёты `acceptance-report-<движок>.json[l]`. Раньше экзамен безусловно копировал живой банк, а демо читало его по
зашитому пути — проверить копию было нельзя, не тронув живое.

Env: `SETS_OUTPUT` — куда пишет сборщик `compose2` (в живой банк — отказ); `SETS_BANK` — какой банк читают экзамен,
демо и тесты (по умолчанию живой). Заданный, но отсутствующий банк — отказ, а не тихий откат на живой.

  python3 bank_paths.py --selftest
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, 'sets3.json')
DEMO_OUT_DEFAULT = os.path.expanduser('~/scout-scenes/flat215-demo')


def same(a: str, b: str) -> bool:
    """Один и тот же файл (через ссылки и `..`); файла может ещё не быть."""
    return os.path.realpath(a) == os.path.realpath(b)


def compose_output(env, default_name: str) -> str:
    """Куда `compose2` пишет банк. Без `SETS_OUTPUT` — как раньше (`sets3.json`/`sets2.json` рядом)."""
    out = env.get('SETS_OUTPUT')
    if not out:
        return os.path.join(HERE, default_name)
    out = out if os.path.isabs(out) else os.path.join(HERE, out)
    if same(out, LIVE):
        raise SystemExit(f'SETS_OUTPUT={out} — это живой банк sets3.json; новый банк пишется рядом (sets3.next.json), '
                         f'подмена — отдельным шагом с бэкапом')
    return out


def compose_preview(out: str, default_name: str) -> str:
    """HTML-превью сборки: рядом с выводом копии, а не поверх общего `sets3-preview.html`."""
    if any(same(out, os.path.join(HERE, n)) for n in ('sets3.json', 'sets2.json')):
        return os.path.join(HERE, default_name)
    return os.path.splitext(out)[0] + '-preview.html'


def input_bank(env) -> tuple[str, bool]:
    """Банк, который читают экзамен, демо и тесты → (путь, живой ли)."""
    b = env.get('SETS_BANK')
    if not b:
        return LIVE, True
    b = os.path.abspath(b)
    if not os.path.exists(b):
        raise SystemExit(f'SETS_BANK={b}: файла нет — на живой банк молча не переключаюсь')
    return b, same(b, LIVE)


def acceptance_plan(env) -> dict:
    """Экзамен: какой снимок банка читают солверы и что из общих файлов писать.

    Живой банк замораживается копией на старте (утренний heal 17.08 переписал его посреди экзамена) — как раньше;
    копия рядом и так не меняется, её читаем напрямую. Копии нужен свой `ACC_REPORT_SUFFIX`: без него её строки
    легли бы в основной jsonl и считались бы «уже готовыми» сценами. Прогон с суффиксом не переписывает общий
    `scene-durations.json`. Раскладки копии — `v3set{n}-layout<суффикс>-acc-…`: суффикс ДО `-acc-`, чтобы маска
    `v3set*-layout-acc-zoned-*` отчётов по экзамену (`template_gaps`, `shadow_core`, `blind_pairs_v2`…) их не брала."""
    bank, live = input_bank(env)
    sfx = env.get('ACC_REPORT_SUFFIX', '')
    if not live and not sfx:
        raise SystemExit('SETS_BANK — копия банка, а ACC_REPORT_SUFFIX не задан: отчёт лёг бы поверх основного')
    return {'bank': bank, 'live': live,
            'snapshot': os.path.join(HERE, f'sets3.snapshot{sfx}.json') if live else bank,
            'copy': live, 'durations': not sfx, 'layout_sfx': '' if live else sfx}


def demo_plan(env, out: str) -> dict:
    """Демо: банк, его дозаполненная копия для солвера и суффикс раскладок. С копией банка — всё своё, в `out`."""
    bank, live = input_bank(env)
    if live:
        return {'bank': bank, 'live': True, 'demo_sets': os.path.join(HERE, 'demo-sets.json'), 'layout_sfx': ''}
    if same(out, DEMO_OUT_DEFAULT):
        raise SystemExit('SETS_BANK — копия банка, а вывод — публикуемая папка демо: задайте FLAT215_DEMO_OUT')
    h = hashlib.sha1(os.path.realpath(out).encode()).hexdigest()[:8]
    return {'bank': bank, 'live': False, 'demo_sets': os.path.join(out, 'demo-sets.json'), 'layout_sfx': f'-demo-{h}'}


def _selftest() -> int:
    import tempfile
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    def refused(fn) -> bool:
        try:
            fn()
        except SystemExit:
            return True
        return False

    ok('compose2 без env пишет как раньше', compose_output({}, 'sets3.json') == LIVE
       and compose_output({}, 'sets2.json') == os.path.join(HERE, 'sets2.json'))
    ok('SETS_OUTPUT относительный — рядом', compose_output({'SETS_OUTPUT': 'sets3.next.json'}, 'sets3.json')
       == os.path.join(HERE, 'sets3.next.json'))
    ok('SETS_OUTPUT в живой банк — отказ (имя, абсолютный путь, через ..)',
       refused(lambda: compose_output({'SETS_OUTPUT': 'sets3.json'}, 'sets3.json'))
       and refused(lambda: compose_output({'SETS_OUTPUT': LIVE}, 'sets3.json'))
       and refused(lambda: compose_output({'SETS_OUTPUT': os.path.join(HERE, '..', 'scout', 'sets3.json')}, 'x')))
    with tempfile.TemporaryDirectory() as td:
        link = os.path.join(td, 'bank.json')
        os.symlink(LIVE, link)
        ok('SETS_OUTPUT — ссылка на живой банк: отказ', refused(lambda: compose_output({'SETS_OUTPUT': link}, 'x')))
        ok('превью: по умолчанию общее, у копии — своё',
           compose_preview(LIVE, 'sets3-preview.html') == os.path.join(HERE, 'sets3-preview.html')
           and compose_preview(os.path.join(td, 'n.json'), 'sets3-preview.html') == os.path.join(td, 'n-preview.html'))
        cp = os.path.join(td, 'sets3.next.json')
        open(cp, 'w').write('[]')
        ok('SETS_BANK: нет env — живой; нет файла — отказ; копия — не живой',
           input_bank({}) == (LIVE, True) and refused(lambda: input_bank({'SETS_BANK': os.path.join(td, 'nope.json')}))
           and input_bank({'SETS_BANK': cp}) == (cp, False))
        a = acceptance_plan({})
        ok('экзамен без env — как раньше: снимок sets3.snapshot.json копией, длительности пишем, раскладки без суффикса',
           a['snapshot'] == os.path.join(HERE, 'sets3.snapshot.json') and a['copy'] and a['durations']
           and a['layout_sfx'] == '')
        a = acceptance_plan({'SETS_BANK': cp, 'ACC_REPORT_SUFFIX': '-next'})
        ok('экзамен на копии: читает её напрямую, без копии живого; общие длительности не пишет; свой суффикс',
           a['snapshot'] == cp and not a['copy'] and not a['durations'] and a['layout_sfx'] == '-next')
        ok('экзамен на копии без суффикса — отказ', refused(lambda: acceptance_plan({'SETS_BANK': cp})))
        a = acceptance_plan({'ACC_REPORT_SUFFIX': '-smoke'})
        ok('смоук живого с суффиксом: свой снимок, общие длительности не пишет',
           a['snapshot'] == os.path.join(HERE, 'sets3.snapshot-smoke.json') and a['copy'] and not a['durations']
           and a['layout_sfx'] == '')
        import fnmatch
        ok('раскладка копии не попадает в маску отчётов экзамена v3set*-layout-acc-zoned-*',
           not fnmatch.fnmatch('v3set3-layout-next-acc-zoned-s1.json', 'v3set*-layout-acc-zoned-*.json'))
        d = demo_plan({}, DEMO_OUT_DEFAULT)
        ok('демо без env — как раньше', d['demo_sets'] == os.path.join(HERE, 'demo-sets.json') and d['layout_sfx'] == '')
        ok('демо на копии в публикуемую папку — отказ', refused(lambda: demo_plan({'SETS_BANK': cp}, DEMO_OUT_DEFAULT)))
        d = demo_plan({'SETS_BANK': cp}, os.path.join(td, 'demo'))
        ok('демо на копии: demo-sets в своей папке, раскладки со своим суффиксом',
           d['demo_sets'] == os.path.join(td, 'demo', 'demo-sets.json') and d['layout_sfx'].startswith('-demo-')
           and not d['live'])
    print(f'bank_paths selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else 0)
