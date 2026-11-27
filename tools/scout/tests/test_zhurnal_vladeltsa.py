#!/usr/bin/env python3
"""Тест журнала сообщений владельца (T-20261127-175, задача 4): свёртка строк (бот, номер), закрытие только с адресом, диапазоны, голосовому — текст, напоминание дольше порога
(не чаще раза в povtor), счёт для стража правил, несколько ботов в одном файле, битая строка не роняет журнал, CLI.
Запуск: python tools/scout/tests/test_zhurnal_vladeltsa.py (стандартная библиотека)."""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_zhurnal_vladeltsa')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'ops'))
import zhurnal_vladeltsa as Z  # noqa: E402

BAD = []
T0 = dt.datetime(2026, 11, 27, 12, 0, tzinfo=dt.timezone.utc)
SCRIPT = os.path.join(ROOT, 'tools', 'ops', 'zhurnal_vladeltsa.py')


def ok(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        BAD.append(msg)


def newj():
    return os.path.join(tempfile.mkdtemp(prefix='zhv-'), 'owner-journal', 'journal.jsonl')


def msg(j, i, minutes_ago, bot='tg-remlab', chat='95903801', tip='text', text='привет', base=T0):
    Z.append(j, {'t': 'msg', 'bot': bot, 'id': i, 'ts': (base - dt.timedelta(minutes=minutes_ago)).isoformat(), 'chat': chat, 'user': 'igor', 'tip': tip, 'nachalo': text})


def cli(j, *a, env=None):
    return subprocess.run([sys.executable, SCRIPT, '--journal', j, *a], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)


def main():
    j = newj()
    msg(j, 3612, 150, text='Регламент Fable — жду')
    msg(j, 3613, 100, tip='voice', text='(voice message)')
    msg(j, 3614, 30)
    msg(j, 3615, 200, chat='459255913')
    rows = Z.fold(Z.read_events(j))
    ok([r['id'] for r in rows] == [3612, 3613, 3614, 3615] and all(r['adres'] is None for r in rows), 'свёртка: четыре строки, все ждут разбора')
    ok(Z.cmd_schet(j, 0, None, T0) == 4 and Z.cmd_schet(j, 120, None, T0) == 2 and Z.cmd_schet(j, 500, None, T0) == 0, 'счёт: все / старше 2 ч (3612, 3615) / старше 500 мин')

    # закрытие: только с адресом
    for bad in ('', 'готово', 'задача', 'P-12', 'ADR-1', 'просто так'):
        try:
            Z.check_adres(bad)
            ok(False, f'адрес «{bad}» должен отклоняться')
        except ValueError:
            ok(True, f'отрицательный контроль: адрес «{bad}» отклонён')
    for good in ('задача T-20261127-175', 'задача T-20261127-175/4', 'P-069', 'ADR-0488', 'план rules-registry-01', 'разобрано', 'разобрано — вопрос без действия'):
        try:
            Z.check_adres(good)
            ok(True, f'адрес «{good}» принят')
        except ValueError as e:
            ok(False, f'адрес «{good}» должен приниматься: {e}')
    rc, out = Z.cmd_zakryt(j, '3612', 'P-069')
    ok(rc == 0 and Z.cmd_schet(j, 0, None, T0) == 3, 'закрытие одного: ждущих 3')
    rc, out = Z.cmd_zakryt(j, '3999', 'P-069')
    ok(rc == 2 and 'нет в журнале' in out and Z.cmd_schet(j, 0, None, T0) == 3, 'номера нет в журнале — отказ, ничего не закрыто')
    rc, out = Z.cmd_zakryt(j, '3613-3614', 'разобрано')
    ok(rc == 0 and Z.cmd_schet(j, 0, None, T0) == 1, 'диапазон 3613-3614 закрыт')
    rc, out = Z.cmd_zakryt(j, '3612', 'ADR-0488')
    rows = {r['id']: r for r in Z.fold(Z.read_events(j))}
    ok(rc == 0 and rows[3612]['adres'] == 'ADR-0488', 'повторное закрытие перекрывает прежний адрес')
    for spec in ('abc', '5-3', '1-9999', ''):
        try:
            Z.parse_ids(spec)
            ok(False, f'номера «{spec}» должны отклоняться')
        except ValueError:
            ok(True, f'номера «{spec}» отклонены')
    ok(Z.parse_ids('1,3-5, 9') == [1, 3, 4, 5, 9], 'разбор списка номеров')

    # напоминания: ждёт 3615 (чат 459…, 200 мин) → один раз; повтор — не раньше povtor
    out = Z.cmd_proverit(j, 120, 120, None, T0)
    ok(len(out) == 1 and out[0]['chat'] == '459255913' and out[0]['ids'] == [3615] and out[0]['bot'] == 'tg-remlab' and '№3615' in out[0]['text'], 'напоминание: только по чату с ждущим дольше 2 ч')
    ok(Z.cmd_proverit(j, 120, 120, None, T0 + dt.timedelta(minutes=30)) == [], 'повтор через 30 мин — тишина')
    out = Z.cmd_proverit(j, 120, 120, None, T0 + dt.timedelta(minutes=125))
    ok(len(out) == 1 and out[0]['ids'] == [3615], 'повтор через 125 мин — напоминание снова')
    Z.cmd_zakryt(j, '3615', 'задача T-20261127-175')
    ok(Z.cmd_proverit(j, 120, 120, None, T0 + dt.timedelta(minutes=600)) == [], 'отрицательный контроль: всё закрыто — напоминаний нет')
    ok(Z.cmd_schet(j, 0, None, T0) == 0 and Z.cmd_spisok(j, False, None, T0) == 'ждущих разбора нет', 'ничего не ждёт: счёт 0, список пуст')
    ok('№3612' in Z.cmd_spisok(j, True, None, T0) and '→ ADR-0488' in Z.cmd_spisok(j, True, None, T0), 'список --vse показывает закрытые с адресом')

    # проба без записи; много ждущих — «и ещё»
    j2 = newj()
    for i in range(12):
        msg(j2, 100 + i, 300)
    out = Z.cmd_proverit(j2, 120, 120, None, T0, zapisat=False)
    ok(len(out) == 1 and '… и ещё 4' in out[0]['text'], 'в напоминании не больше 8 строк, остальное — «и ещё N»')
    ok(not any(e.get('t') == 'napom' for e in Z.read_events(j2)), 'режим пробы не пишет napom')

    # несколько ботов в одном файле: один номер у двух ботов
    j3 = newj()
    msg(j3, 50, 10, bot='tg-remlab')
    msg(j3, 50, 10, bot='tg-tamara')
    msg(j3, 51, 10, bot='tg-remlab')
    ok(Z.cmd_schet(j3, 0, None, T0) == 3 and Z.cmd_schet(j3, 0, 'tg-tamara', T0) == 1, 'два бота: счёт по всем (3) и по одному (1)')
    rc, out = Z.cmd_zakryt(j3, '50', 'разобрано')
    ok(rc == 2 and '--bot' in out and Z.cmd_schet(j3, 0, None, T0) == 3, 'номер у двух ботов — отказ, просит --bot, ничего не закрыто')
    rc, out = Z.cmd_zakryt(j3, '51', 'разобрано')
    ok(rc == 0 and Z.cmd_schet(j3, 0, None, T0) == 2, 'номер только у одного бота — закрывается без --bot')
    rc, out = Z.cmd_zakryt(j3, '50', 'разобрано', 'tg-tamara')
    ok(rc == 0 and Z.cmd_schet(j3, 0, 'tg-remlab', T0) == 1 and Z.cmd_schet(j3, 0, 'tg-tamara', T0) == 0, 'с --bot закрыт только этот бот, второй ждёт')

    # голосовое: расшифровка попадает в начало строки
    j4 = newj()
    msg(j4, 7, 10, tip='voice', text='(voice message)')
    rc, out = Z.cmd_tekst(j4, 7, 'Регламент полностью, всё чётко')
    ok(rc == 0 and Z.fold(Z.read_events(j4))[0]['nachalo'] == 'Регламент полностью, всё чётко' and Z.fold(Z.read_events(j4))[0]['tip'] == 'voice', 'голосовому добавлен текст, тип остался voice')
    ok(Z.cmd_tekst(j4, 8, 'нет такого')[0] == 2, 'текст к несуществующему номеру — отказ')

    # устойчивость: битая строка, нет файла, дубль номера
    j5 = newj()
    os.makedirs(os.path.dirname(j5))
    open(j5, 'w', encoding='utf-8').write('{"t":"msg","bot":"b","id":1,"ts":"%s","chat":"7","tip":"text","nachalo":"а"}\nмусор не json\n[1,2]\n{"t":"msg","bot":"b","id":1,"ts":"%s","chat":"7","nachalo":"дубль"}\n\n' % (T0.isoformat(), T0.isoformat()))
    rows = Z.fold(Z.read_events(j5))
    ok(len(rows) == 1 and rows[0]['nachalo'] == 'а', 'битая строка и не-объект пропущены, дубль номера не плодит строк')
    ok(Z.read_events(os.path.join(os.path.dirname(j5), 'нет-такого')) == [], 'нет файла — пустой журнал')
    ok(Z.cmd_schet(os.path.join(os.path.dirname(j5), 'нет-такого'), 0, None, T0) == 0, 'нет файла — счёт 0, без ошибки')

    # CLI (процесс): запись, закрытие, счёт, проверка пробой, путь по умолчанию из $OWNER_JOURNAL / HOME
    j6 = newj()
    r = cli(j6, '--bot', 'tg-x', 'zapis', '3700', '95903801', 'text', 'проба из командной строки')
    ok(r.returncode == 0 and cli(j6, 'schet').stdout.strip() == '1', 'CLI: запись и счёт = 1')
    r = cli(j6, 'zapis', '3701', '1', 'text', 'без бота')
    ok(r.returncode == 2, 'CLI: ручная запись без --bot — отказ')
    r = cli(j6, 'zakryt', '3700', 'нечто')
    ok(r.returncode == 2 and cli(j6, 'schet').stdout.strip() == '1', 'отрицательный контроль CLI: закрытие без допустимого адреса — код 2, строка ждёт')
    r = cli(j6, 'zakryt', '3700', 'P-070', 'своё', 'пояснение')
    ok(r.returncode == 0 and cli(j6, 'schet').stdout.strip() == '0', 'CLI: закрытие с адресом и пояснением')
    r = cli(j6, 'proverit', '--proba')
    ok(r.returncode == 0 and json.loads(r.stdout) == [], 'CLI: proverit печатает JSON-список')
    r = cli(j6, 'zakryt', '1', 'разобрано')
    ok(r.returncode == 2 and 'нет в журнале' in r.stderr + r.stdout, 'CLI: неизвестный номер — код 2')
    home = tempfile.mkdtemp(prefix='zhv-home-')
    env = {k: v for k, v in os.environ.items() if k not in ('OWNER_JOURNAL',)}
    env['HOME'] = home
    dflt = os.path.join(home, '.local', 'state', 'remlab', 'owner-journal', 'journal.jsonl')
    Z.append(dflt, {'t': 'msg', 'bot': 'tg-remlab', 'id': 1, 'ts': (Z.now() - dt.timedelta(minutes=5)).isoformat(), 'chat': '1', 'tip': 'text', 'nachalo': 'x'})
    r = subprocess.run([sys.executable, SCRIPT, 'schet'], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
    ok(r.stdout.strip() == '1', 'путь по умолчанию — ~/.local/state/remlab/owner-journal/journal.jsonl (его читает страж правил)')
    env['OWNER_JOURNAL'] = j6
    r = subprocess.run([sys.executable, SCRIPT, 'schet'], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
    ok(r.stdout.strip() == '0', '$OWNER_JOURNAL меняет путь')

    # панель tmux: без панели / несуществующая панель — тихо, без падения и без печати куда попало
    os.environ.pop('TMUX_PANE', None)
    rc, m = Z.cmd_panel('проба')
    ok(rc == 0 and 'не в tmux' in m, 'панель: нет $TMUX_PANE — ничего не печатает, код 0')
    rc, m = Z.cmd_panel('проба', '%99999')
    ok(rc == 0 and ('нет' in m or 'не напечатал' in m), 'отрицательный контроль: несуществующая панель — ничего не печатает, код 0')

    print('\nПровалов: %d' % len(BAD))
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
