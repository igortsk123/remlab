#!/usr/bin/env python3
"""СТОРОЖ НОЧНОЙ ЖИВОЙ ПРОВЕРКИ ДЕМО — красные проверки не должны стать «нормой» (T-20261119-115/2; разбор 12–19.11: шаг `demo_live`
кончался rc 0 при 7–13 красных, шаг ночи всегда «warn», и семь ночей подряд никто не смотрел).

Читает вывод `pnpm exec playwright test -c playwright.live.config.ts` (строчный репортёр; итог в конце: `N failed` / `N flaky` /
`N passed`, под каждым — строки `[chromium] › файл:строка:столбец › название`). Пороги — ДАННЫЕ, не код: `tools/scout/rules/demo-live.json`
(`red_fail_at` — по всем красным, `red_fail_at_core` — по «ядру», ядро — по номеру сценария в названии, `core_title_re`).

  bash tools/ops/demo-live.sh                          # вызывает: python3 tools/ops/demo-live-gate.py --file ВЫВОД --rc КОД
  python3 tools/ops/demo-live-gate.py --file F [--rc N] [--rules ПУТЬ]
  python3 tools/ops/demo-live-gate.py --selftest       # ниже порога → rc 0 и строка; на пороге и выше → rc 1 и DIGEST:!; ядро; сбой запуска

Печатает строки `DIGEST:` (шаг ночи складывает их в сводку; `DIGEST:!` — проблема) и `WARN:demo_live:` при красных.
Код выхода: 0 — красных меньше порогов; 1 — красных столько или больше (шаг FAIL); 2 — сломан файл порогов."""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, '..', 'scout', 'rules', 'demo-live.json')
ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
HEAD_RE = re.compile(r'^\s*(\d+) (failed|flaky|skipped|did not run|passed|interrupted)\b')
TEST_RE = re.compile(r'^\s+\[[^\]]+\] › (\S+?):(\d+):\d+ › (.*?)(?: ─+)?\s*$')
PASSED_RE = re.compile(r'^\s*(\d+) passed\b')


def parse(text: str) -> dict:
    """Итог Playwright: {'failed': [(файл, строка, название)], 'flaky': [...], 'passed': N, 'summary': найден ли итог}."""
    res = {'failed': [], 'flaky': [], 'passed': 0, 'summary': False}
    section = None
    for raw in ANSI_RE.sub('', text).splitlines():
        m = HEAD_RE.match(raw)
        if m:
            section = m.group(2)
            res['summary'] = True
            if section == 'passed':
                res['passed'] = int(m.group(1))
            continue
        t = TEST_RE.match(raw)
        if t and section in ('failed', 'flaky'):
            res[section].append((t.group(1), int(t.group(2)), t.group(3)))
        elif raw.strip() and not raw.startswith(' '):
            section = None
    return res


def load_rules(path: str) -> dict:
    with open(path, encoding='utf-8') as f:
        r = json.load(f)
    for k in ('red_fail_at', 'red_fail_at_core', 'core_title_re'):
        if k not in r:
            raise ValueError(f'в {os.path.basename(path)} нет «{k}»')
    re.compile(r['core_title_re'])
    return r


def short(title: str) -> str:
    n = re.match(r'^((?:\d+\.\d+(?:[–-]\d+\.\d+)?)|п\.\d+\([а-я]\))', title)      # номер сценария: «2.12», «2.41–2.42», «п.1(е)»
    return n.group(1) if n else title[:20]


def judge(res: dict, rc: int, rules: dict) -> tuple[int, list[str]]:
    """(код выхода, строки вывода)."""
    out: list[str] = []
    core_re = re.compile(rules['core_title_re'])
    red = res['failed']
    core = [t for t in red if core_re.search(t[2])]
    names = ', '.join(short(t[2]) for t in red)
    if not res['summary'] and rc != 0:
        out.append('DIGEST:!демо вживую: проверка не дошла до итога (упала или оборвана, rc=%d) — сторож не знает, сколько красных; разбор — журнал ~/scout-scenes/demo-live/' % rc)
        out.append('WARN:demo_live: нет итога Playwright, rc=%d' % rc)
        return 1, out
    bad_total = len(red) >= rules['red_fail_at']
    bad_core = len(core) >= rules['red_fail_at_core']
    line = (f'демо вживую: красных {len(red)} (порог {rules["red_fail_at"]}), в ядре {len(core)} (порог {rules["red_fail_at_core"]}), '
            f'нестабильных {len(res["flaky"])}, зелёных {res["passed"]}')
    if red:
        line += f' · красные: {names}'
    if bad_total or bad_core:
        why = []
        if bad_core:
            why.append('ядро: ' + ', '.join(short(t[2]) for t in core))
        if bad_total:
            why.append(f'всего {len(red)} ≥ {rules["red_fail_at"]}')
        out.append('DIGEST:!' + line + ' — ' + '; '.join(why))
        out.append('WARN:demo_live: красных больше порога — ' + '; '.join(why))
        return 1, out
    out.append('DIGEST:' + line)
    if red:
        out.append('WARN:demo_live: красные ниже порога — ' + names)
    return 0, out


def selftest() -> int:
    errs: list[str] = []

    def chk(ok: bool, what: str) -> None:
        if not ok:
            errs.append(what)

    def log(red: list[str], flaky: int = 0, passed: int = 40) -> str:
        s = '  · какой-то вывод теста\n\n'
        if red:
            s += f'  {len(red)} failed\n' + ''.join(f'    [chromium] › e2e/live/x.live.ts:{10 + i}:5 › {t} ────────\n' for i, t in enumerate(red))
        if flaky:
            s += f'  {flaky} flaky\n    [chromium] › e2e/live/x.live.ts:99:5 › 2.44 нестабильный ──\n'
        return s + f'  2 skipped\n  {passed} passed (30.0m)\n'

    rules = {'red_fail_at': 4, 'red_fail_at_core': 1, 'core_title_re': r'^(1\.\d+|2\.([1-9]|1[0-2]))[ –]'}
    # ниже порогов (3 вне ядра при пороге 4) → rc 0 и строка DIGEST без «!»
    rc, out = judge(parse(log(['2.19 a', '2.20 b', '2.35 c'])), 0, rules)
    chk(rc == 0, f'ниже порога: rc {rc}, ждали 0')
    chk(any(l.startswith('DIGEST:') and not l.startswith('DIGEST:!') for l in out), 'ниже порога: нет строки DIGEST')
    # ровно на пороге (4) → rc 1 и строка DIGEST:!
    rc, out = judge(parse(log(['2.19 a', '2.20 b', '2.35 c', '2.41–2.42 d'])), 1, rules)
    chk(rc == 1, f'на пороге: rc {rc}, ждали 1')
    chk(any(l.startswith('DIGEST:!') and 'красных 4' in l for l in out), 'на пороге: нет строки DIGEST:!')
    # выше порога
    rc, out = judge(parse(log([f'2.{30 + i} t' for i in range(9)])), 1, rules)
    chk(rc == 1 and any(l.startswith('DIGEST:!') for l in out), 'выше порога: нет rc 1 / DIGEST:!')
    # один красный в ядре (2.12) при общем счёте ниже порога → rc 1, ядро названо
    rc, out = judge(parse(log(['2.12 фото'])), 1, rules)
    chk(rc == 1 and any('ядро: 2.12' in l for l in out), 'ядро: 2.12 не остановил шаг')
    # 2.24 — не ядро по номеру (2.2 + «4»), 2.4 — ядро
    rc, _ = judge(parse(log(['2.24 x'])), 1, rules)
    chk(rc == 0, '2.24 принят за ядро')
    rc, _ = judge(parse(log(['2.4 x'])), 1, rules)
    chk(rc == 1, '2.4 не принят за ядро')
    # нестабильный не красный
    rc, out = judge(parse(log([], flaky=1)), 0, rules)
    chk(rc == 0 and any('нестабильных 1' in l for l in out), 'нестабильный посчитан красным')
    # всё зелёное
    rc, out = judge(parse(log([])), 0, rules)
    chk(rc == 0 and out and 'красных 0' in out[0], 'зелёная ночь')
    # нет итога и rc≠0 (упал, оборван) → rc 1, DIGEST:!
    rc, out = judge(parse('Error: browserType.launch: ...\n'), 1, rules)
    chk(rc == 1 and any(l.startswith('DIGEST:!') for l in out), 'нет итога: не остановил шаг')
    # цвета строчного репортёра срезаются; название с длинным хвостом
    colored = log(['2.12 a']).replace('failed', '\x1b[31mfailed\x1b[39m')
    chk(len(parse(colored)['failed']) == 1, 'цветные коды не срезаны')
    # файл порогов настоящий и читается; без ключа — ошибка
    chk(load_rules(RULES)['red_fail_at'] >= 1, 'настоящий файл порогов не читается')
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'r.json')
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({'red_fail_at': 3}, f)
        try:
            load_rules(p)
            chk(False, 'файл порогов без ключей принят')
        except ValueError:
            pass
    for e in errs:
        print('ПРОВАЛ:', e)
    print(f'demo-live-gate selftest: ошибок {len(errs)}')
    return 1 if errs else 0


def main(a: list[str]) -> int:
    if '--selftest' in a:
        return selftest()

    def opt(name: str, default: str | None = None) -> str | None:
        return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default

    path, rc = opt('--file'), int(opt('--rc', '0') or 0)
    if not path:
        print('нужен --file ВЫВОД_PLAYWRIGHT (или --selftest)', file=sys.stderr)
        return 2
    try:
        rules = load_rules(opt('--rules', RULES) or RULES)
    except (OSError, ValueError) as e:
        print(f'DIGEST:!демо вживую: сломан файл порогов demo-live.json — {e}')
        return 2
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError as e:
        print(f'DIGEST:!демо вживую: вывод проверки не прочитан — {e}')
        return 1
    code, out = judge(parse(text), rc, rules)
    print('\n'.join(out))
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
