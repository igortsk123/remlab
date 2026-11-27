#!/usr/bin/env python3
"""Тест журнала сообщений владельца (T-20261127-175, задача 4): свёртка строк, закрытие только с адресом, диапазоны, напоминание дольше порога (не чаще раза в povtor),
счёт для стража правил, битая строка не роняет журнал, CLI. Запуск: python tools/scout/tests/test_zhurnal_vladeltsa.py (стандартная библиотека)."""
import datetime as dt
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_zhurnal_vladeltsa')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'ops'))
import zhurnal_vladeltsa as Z  # noqa: E402

BAD = []
T0 = dt.datetime(2026, 11, 27, 12, 0, tzinfo=dt.timezone.utc)


def ok(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        BAD.append(msg)


def msg(d, i, minutes_ago, chat='95903801', tip='text', text='привет'):
    Z.append(d, {'t': 'msg', 'id': i, 'ts': (T0 - dt.timedelta(minutes=minutes_ago)).isoformat(), 'chat': chat, 'user': 'igor', 'tip': tip, 'nachalo': text})


def main():
    d = tempfile.mkdtemp(prefix='zhv-')
    msg(d, 3612, 150, text='Регламент Fable — жду')
    msg(d, 3613, 100, tip='voice', text='(voice message)')
    msg(d, 3614, 30)
    msg(d, 3615, 200, chat='459255913')
    rows = Z.fold(Z.read_events(d))
    ok([r['id'] for r in rows] == [3612, 3613, 3614, 3615] and all(r['adres'] is None for r in rows), 'свёртка: четыре строки, все ждут разбора')
    ok(Z.cmd_schet([d], 0, T0) == 4 and Z.cmd_schet([d], 120, T0) == 2 and Z.cmd_schet([d], 500, T0) == 0, 'счёт: все / старше 2 ч (3612, 3615) / старше 500 мин')

    # закрытие: только с адресом, номера обязаны быть в журнале
    for bad in ('', 'готово', 'задача', 'P-12', 'ADR-1', 'просто так'):
        try:
            Z.check_adres(bad)
            ok(False, f'адрес «{bad}» должен отклоняться')
        except ValueError:
            ok(True, f'адрес «{bad}» отклонён')
    for good in ('задача T-20261127-175', 'задача T-20261127-175/4', 'P-069', 'ADR-0488', 'план rules-registry-01', 'разобрано', 'разобрано — вопрос без действия'):
        try:
            Z.check_adres(good)
            ok(True, f'адрес «{good}» принят')
        except ValueError as e:
            ok(False, f'адрес «{good}» должен приниматься: {e}')
    rc, out = Z.cmd_zakryt(d, '3612', 'P-069')
    ok(rc == 0 and Z.cmd_schet([d], 0, T0) == 3, 'закрытие одного: ждущих 3')
    rc, out = Z.cmd_zakryt(d, '3999', 'P-069')
    ok(rc == 2 and 'нет в журнале' in out and Z.cmd_schet([d], 0, T0) == 3, 'номера нет в журнале — отказ, ничего не закрыто')
    rc, out = Z.cmd_zakryt(d, '3613-3614', 'разобрано')
    ok(rc == 0 and Z.cmd_schet([d], 0, T0) == 1, 'диапазон 3613-3614 закрыт')
    rc, out = Z.cmd_zakryt(d, '3612', 'ADR-0488')
    rows = {r['id']: r for r in Z.fold(Z.read_events(d))}
    ok(rc == 0 and rows[3612]['adres'] == 'ADR-0488', 'повторное закрытие перекрывает прежний адрес')
    for spec in ('abc', '5-3', '1-9999', ''):
        try:
            Z.parse_ids(spec)
            ok(False, f'номера «{spec}» должны отклоняться')
        except ValueError:
            ok(True, f'номера «{spec}» отклонены')
    ok(Z.parse_ids('1,3-5, 9') == [1, 3, 4, 5, 9], 'разбор списка номеров')

    # напоминания: ждёт 3615 (чат 459…, 200 мин) → один раз; повтор — не раньше povtor
    out = Z.cmd_proverit(d, 120, 120, T0)
    ok(len(out) == 1 and out[0]['chat'] == '459255913' and out[0]['ids'] == [3615] and '№3615' in out[0]['text'], 'напоминание: только по чату с ждущим дольше 2 ч')
    ok(Z.cmd_proverit(d, 120, 120, T0 + dt.timedelta(minutes=30)) == [], 'повтор через 30 мин — тишина')
    out = Z.cmd_proverit(d, 120, 120, T0 + dt.timedelta(minutes=125))
    ok(len(out) == 1 and out[0]['ids'] == [3615], 'повтор через 125 мин — напоминание снова')
    Z.cmd_zakryt(d, '3615', 'задача T-20261127-175')
    ok(Z.cmd_proverit(d, 120, 120, T0 + dt.timedelta(minutes=600)) == [], 'всё закрыто — напоминаний нет')
    ok(Z.cmd_schet([d], 0, T0) == 0 and Z.cmd_spisok([d], False, T0) == 'ждущих разбора нет', 'ничего не ждёт: счёт 0, список пуст')
    ok('№3612' in Z.cmd_spisok([d], True, T0) and '→ ADR-0488' in Z.cmd_spisok([d], True, T0), 'список --vse показывает закрытые с адресом')

    # проба без записи; много ждущих — «и ещё»
    d2 = tempfile.mkdtemp(prefix='zhv-')
    for i in range(12):
        msg(d2, 100 + i, 300)
    out = Z.cmd_proverit(d2, 120, 120, T0, zapisat=False)
    ok(len(out) == 1 and '… и ещё 4' in out[0]['text'], 'в напоминании не больше 8 строк, остальное — «и ещё N»')
    ok(not any(e.get('t') == 'napom' for e in Z.read_events(d2)), 'режим пробы не пишет napom')

    # устойчивость: битая строка, пустой/нет файла, дубль номера
    d3 = tempfile.mkdtemp(prefix='zhv-')
    open(os.path.join(d3, Z.FILE), 'w', encoding='utf-8').write('{"t":"msg","id":1,"ts":"%s","chat":"7","tip":"text","nachalo":"а"}\nмусор не json\n{"t":"msg","id":1,"ts":"%s","chat":"7","nachalo":"дубль"}\n\n' % (T0.isoformat(), T0.isoformat()))
    rows = Z.fold(Z.read_events(d3))
    ok(len(rows) == 1 and rows[0]['nachalo'] == 'а', 'битая строка пропущена, дубль номера не плодит строк')
    ok(Z.read_events(os.path.join(d3, 'нет-такой')) == [], 'нет файла — пустой журнал')

    # CLI (процесс): запись, закрытие, счёт, проверка пробой
    py = sys.executable
    script = os.path.join(ROOT, 'tools', 'ops', 'zhurnal_vladeltsa.py')
    d4 = tempfile.mkdtemp(prefix='zhv-')
    def run(*a):
        return subprocess.run([py, script, '--dir', d4, *a], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    r = run('zapis', '3700', '95903801', 'text', 'проба из командной строки')
    ok(r.returncode == 0 and run('schet').stdout.strip() == '1', 'CLI: запись и счёт = 1')
    r = run('zakryt', '3700', 'нечто')
    ok(r.returncode == 2 and run('schet').stdout.strip() == '1', 'CLI: закрытие без допустимого адреса — код 2, строка ждёт')
    r = run('zakryt', '3700', 'P-070', 'своё', 'пояснение')
    ok(r.returncode == 0 and run('schet').stdout.strip() == '0', 'CLI: закрытие с адресом и пояснением')
    r = run('proverit', '--proba')
    ok(r.returncode == 0 and json.loads(r.stdout) == [], 'CLI: proverit печатает JSON-список')
    r = subprocess.run([py, script, '--dir', d4, 'zakryt', '1', 'разобрано'], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    ok(r.returncode == 2 and 'нет в журнале' in r.stderr + r.stdout, 'CLI: неизвестный номер — код 2')

    # без --dir: папки tg-* под HOME; закрытие — только если номер есть ровно в одной папке
    home = tempfile.mkdtemp(prefix='zhv-home-')
    da, db = (os.path.join(home, '.claude', 'channels', n) for n in ('tg-a', 'tg-b'))
    for dd, i in ((da, 10), (da, 11), (db, 11)):   # время — от настоящих часов: процесс командной строки считает возраст по ним
        Z.append(dd, {'t': 'msg', 'id': i, 'ts': (Z.now() - dt.timedelta(minutes=5)).isoformat(), 'chat': '1', 'user': 'igor', 'tip': 'text', 'nachalo': 'проба'})
    env = {k: v for k, v in os.environ.items() if k != 'TELEGRAM_STATE_DIR'}
    env['HOME'] = home

    def run_home(*a):
        return subprocess.run([py, script, *a], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
    ok(run_home('schet').stdout.strip() == '3', 'без --dir: счёт по всем папкам tg-* (3)')
    r = run_home('zakryt', '10', 'разобрано')
    ok(r.returncode == 0 and run_home('schet').stdout.strip() == '2', 'номер есть в одной папке — закрыт без --dir')
    r = run_home('zakryt', '11', 'разобрано')
    ok(r.returncode == 2 and 'задайте --dir' in r.stderr and run_home('schet').stdout.strip() == '2', 'номер в двух папках — отказ, просит --dir, ничего не закрыто')
    r = run_home('--dir', db, 'zakryt', '11', 'разобрано')
    ok(r.returncode == 0 and run_home('schet').stdout.strip() == '1', 'с --dir закрывает нужную папку')

    print('\nПровалов: %d' % len(BAD))
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
