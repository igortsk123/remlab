#!/usr/bin/env python3
"""Журнал сообщений владельца (T-20261127-175, задача 4; Fable 27 § 2–3 п.4, план Fable `plan-t175.md` § 3 № 4; владелец TG 3612/3614 «регламент полностью»).

ЗАЧЕМ. Слово владельца → задача, правило или решение: разбор держался только на памяти директора (P-069), сообщения терялись в блокноте (21.11, 26.11, 27.11).
Теперь код: плагин Telegram пишет КАЖДОЕ входящее сообщение допущенного отправителя строкой в журнал БЕЗ участия модели (номер = message_id Telegram, время, бот, тип, начало
текста, «ждёт разбора»); директор закрывает строку командой с адресом, куда ушло слово; не закрыто дольше порога (2 ч) — напоминание в тот же чат Telegram.

ГДЕ. Один файл на машину: `~/.local/state/remlab/owner-journal/journal.jsonl` (его ждёт страж правил T-175/3; `$OWNER_JOURNAL` или `--journal` меняют путь). Строки разных ботов
машины — в одном файле, бот назван полем `bot` (имя папки состояния плагина: `tg-remlab`, `tg-tamara`…). Строка сообщения = пара (бот, номер).

ФОРМАТ. Дописывается построчно (JSON на строку), никогда не переписывается:
  {"t":"msg","bot":"tg-remlab","id":3612,"ts":"2026-11-27T11:36:00.000Z","chat":"95903801","user":"igor","tip":"text|voice|photo|document|audio|video|…","nachalo":"первые 80 знаков"}
  {"t":"tekst","bot":"tg-remlab","id":3613,"ts":"…","nachalo":"расшифровка голоса — первые 80 знаков"}    # голосовое: плагин пишет «(voice message)», расшифровку (stt) добавляет директор командой `tekst`
  {"t":"zakryt","bot":"tg-remlab","id":3612,"ts":"…","adres":"задача T-20261127-175","kto":"директор"}
  {"t":"napom","bot":"tg-remlab","chat":"95903801","ts":"…","ids":[3612,3614]}      # напоминание отправлено
  Состояние строки = свёртка: есть `zakryt` по (бот, номер) — закрыта (последний адрес), иначе «ждёт разбора». Повторное закрытие — новый адрес перекрывает прежний.
Запись плагином (патч tg-patch-zhurnal) и этим скриптом — один формат; плагин пишет прямо в файл (без запуска процесса), здесь — чтение, закрытие, напоминания.

КОМАНДЫ (`--bot` — только этот бот; без него — все боты файла):
  zhurnal-vladeltsa spisok [--vse]                  # ждущие разбора (--vse — и закрытые), время по Лондону, возраст
  zhurnal-vladeltsa zakryt <№|№-№|№,№,…> <адрес>    # адрес: «задача T-ГГГГММДД-N», «P-NNN», «ADR-NNNN», «план <имя>» или «разобрано <почему не задача и не правило>» (пояснение ≥ 10 знаков ОБЯЗАТЕЛЬНО, иначе код 2)
  zhurnal-vladeltsa tekst <№> <расшифровка…>        # голосовому сообщению — текст (после stt), чтобы в списке было видно, о чём
  zhurnal-vladeltsa schet [--starshe-min N]         # одно число: ждущих разбора (только старше N минут: 120 — «сообщений без разбора дольше 2 ч», строка стража правил)
  zhurnal-vladeltsa proverit [--poroh-min 120] [--povtor-min 120] [--proba]   # JSON [{"bot","chat","text","ids"}] напоминаний; пишет `napom` (плагин шлёт и ничего не помнит)
  zhurnal-vladeltsa panel <текст…> [--pane %N]      # напечатать строку в панель tmux сессии бота (не в окно выбора); зовёт плагин вместе с отправкой в Telegram
  zhurnal-vladeltsa zapis <№> <чат> <тип> <текст…>  # ручная запись строки (пропущенное до наложения патча; нужен --bot)
Закрыть строку без адреса нельзя: «закрыто» без «куда ушло» — та же потеря, что и без журнала. Номер есть у двух ботов — закрытие требует `--bot`. Код выхода: 0 — готово, 2 — ошибка ввода.
Стандартная библиотека; на проверку не влияют ни сеть, ни Telegram."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

try:
    from zoneinfo import ZoneInfo
    LONDON = ZoneInfo('Europe/London')
except Exception:  # noqa: BLE001 — без базы часовых поясов: UTC, время всё равно читаемо
    LONDON = dt.timezone.utc

DEFAULT_PATH = '~/.local/state/remlab/owner-journal/journal.jsonl'
POROH_MIN = 120      # ждёт разбора дольше — напоминание (Fable 27: 2 часа)
POVTOR_MIN = 120     # повторное напоминание тому же чату — не чаще
NACHALO = 80
# адрес закрытия: куда ушло слово владельца
RAZOBRANO_MIN = 10   # знаков пояснения после «разобрано» (как у «N/A: причина» в приёмке)
ADRES_RE = re.compile(r'^(задача\s+T-\d{8}-\d+[\w./-]*|P-\d{3}|ADR-\d{4}|план\s+\S+|разобрано)(\s+.*)?$')


def journal_path(arg: str | None = None) -> str:
    return os.path.expanduser(arg or os.environ.get('OWNER_JOURNAL') or DEFAULT_PATH)


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_ts(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def read_events(path: str) -> list[dict]:
    out = []
    if not os.path.isfile(path):
        return out
    for ln in open(path, encoding='utf-8'):
        ln = ln.strip()
        if not ln:
            continue
        try:
            e = json.loads(ln)
        except Exception:  # noqa: BLE001 — битая строка (обрыв записи) не роняет журнал
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def fold(events: list[dict], bot: str | None = None) -> list[dict]:
    """Свёртка: строки сообщений в порядке прихода; adres — по последнему `zakryt`; nachalo голосового — по последнему `tekst`. bot — только этот бот."""
    rows: dict[tuple, dict] = {}
    order: list[tuple] = []
    for e in events:
        t, b = e.get('t'), str(e.get('bot', ''))
        if bot and b != bot:
            continue
        k = (b, e.get('id'))
        if t == 'msg' and isinstance(e.get('id'), int):
            if k not in rows:
                order.append(k)
                rows[k] = {'bot': b, 'id': e['id'], 'ts': e.get('ts'), 'chat': str(e.get('chat', '')), 'user': e.get('user', ''), 'tip': e.get('tip', 'text'),
                           'nachalo': e.get('nachalo', ''), 'adres': None, 'closed_ts': None}
        elif k in rows and t == 'zakryt':
            rows[k]['adres'] = e.get('adres')
            rows[k]['closed_ts'] = e.get('ts')
        elif k in rows and t == 'tekst' and e.get('nachalo'):
            rows[k]['nachalo'] = e['nachalo']
    return [rows[k] for k in order]


def last_napom(events: list[dict]) -> dict[tuple, dt.datetime]:
    m: dict[tuple, dt.datetime] = {}
    for e in events:
        if e.get('t') == 'napom' and e.get('ts'):
            m[(str(e.get('bot', '')), str(e.get('chat', '')))] = parse_ts(e['ts'])
    return m


def pending(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not r['adres']]


def append(path: str, ev: dict) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(ev, ensure_ascii=False) + '\n')


def age_text(m: float) -> str:
    m = int(m)
    return f'{m // 60} ч {m % 60:02d} мин' if m >= 60 else f'{m} мин'


def parse_ids(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r'(\d+)-(\d+)', part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b or b - a > 500:
                raise ValueError(f'диапазон «{part}» не годится')
            out.extend(range(a, b + 1))
        elif re.fullmatch(r'\d+', part):
            out.append(int(part))
        else:
            raise ValueError(f'«{part}» — не номер сообщения')
    if not out:
        raise ValueError('нет номеров сообщений')
    return out


def check_adres(a: str) -> str:
    a = ' '.join(a.split())
    # «разобрано: пояснение», «разобрано — пояснение», «разобрано, …» и «разобрано пояснение» — один адрес (живая проверка 27.11: двоеточие отвергалось, Fable п.1); в журнал пишется с пробелом
    a = re.sub(r'^(разобрано)\s*[:—–;,.-]+\s*', r'\1 ', a)
    a = ' '.join(a.split())
    if not ADRES_RE.match(a):
        raise ValueError('адрес закрытия: «задача T-ГГГГММДД-N», «P-NNN», «ADR-NNNN», «план <имя>» или «разобрано <почему не задача и не правило>» (после остальных адресов пояснение необязательно)')
    if a.startswith('разобрано'):                                  # «разобрано» одним словом — лазейка: всё закрывается без следа (Fable 27, proverka-t175-4 § 2 п.2)
        why = re.sub(r'^[\s—–:;,.-]+', '', a[len('разобрано'):])
        if len(why) < RAZOBRANO_MIN:
            raise ValueError(f'«разобрано» требует пояснения — почему слово владельца не задача и не правило (не короче {RAZOBRANO_MIN} знаков): '
                             'zhurnal-vladeltsa zakryt <№> разобрано <пояснение>')
    return a


def resolve_bot(events: list[dict], ids: list[int], bot: str | None) -> str:
    """Бот, в чьём журнале есть все номера: названный, иначе единственный подходящий (номера у разных ботов могут совпасть)."""
    if bot:
        return bot
    bots = sorted({str(e.get('bot', '')) for e in events if e.get('t') == 'msg'})
    cand = [b for b in bots if set(ids) <= {r['id'] for r in fold(events, b)}]
    if len(cand) == 1:
        return cand[0]
    if not cand:
        raise ValueError('нет в журнале ни у одного бота: %s (проверь номер; пропущенное — командой zapis)' % ', '.join(str(i) for i in ids))
    raise ValueError('не ясно, в журнале какого бота закрывать (подходят: %s) — задайте --bot' % ', '.join(cand))


def cmd_zakryt(path: str, spec: str, adres: str, bot: str | None = None, kto: str = 'директор') -> tuple[int, str]:
    ids = parse_ids(spec)
    try:
        adres = check_adres(adres)                                 # плохой адрес / «разобрано» без пояснения — отказ (2), ничего не закрыто
    except ValueError as e:
        return 2, str(e)
    ev = read_events(path)
    try:
        bot = resolve_bot(ev, ids, bot)
    except ValueError as e:
        return 2, str(e)
    have = {r['id'] for r in fold(ev, bot)}
    unknown = [i for i in ids if i not in have]
    if unknown:
        return 2, 'нет в журнале %s: %s (проверь номер; пропущенное — командой zapis)' % (bot, ', '.join(str(i) for i in unknown))
    for i in ids:
        append(path, {'t': 'zakryt', 'bot': bot, 'id': i, 'ts': now().isoformat(timespec='seconds'), 'adres': adres, 'kto': kto})
    return 0, f'закрыто {len(ids)} ({bot}): {", ".join(str(i) for i in ids)} → {adres}'


def cmd_tekst(path: str, nomer: int, tekst: str, bot: str | None = None) -> tuple[int, str]:
    ev = read_events(path)
    try:
        bot = resolve_bot(ev, [nomer], bot)
    except ValueError as e:
        return 2, str(e)
    if nomer not in {r['id'] for r in fold(ev, bot)}:
        return 2, f'нет в журнале {bot}: {nomer}'
    append(path, {'t': 'tekst', 'bot': bot, 'id': nomer, 'ts': now().isoformat(timespec='seconds'), 'nachalo': ' '.join(tekst.split())[:NACHALO]})
    return 0, f'текст добавлен к №{nomer} ({bot})'


def cmd_spisok(path: str, vse: bool = False, bot: str | None = None, t: dt.datetime | None = None) -> str:
    t = t or now()
    rows = fold(read_events(path), bot)
    lines = []
    for r in (rows if vse else pending(rows)):
        ts = parse_ts(r['ts']) if r.get('ts') else t
        tail = f"→ {r['adres']}" if r['adres'] else f'ждёт разбора {age_text((t - ts).total_seconds() / 60)}'
        lines.append(f"{r['bot']} №{r['id']} {ts.astimezone(LONDON).strftime('%d.%m %H:%M')} [{r['tip']}] {r['nachalo']} — {tail}")
    return '\n'.join(lines) if lines else 'ждущих разбора нет'


def cmd_schet(path: str, starshe_min: float = 0, bot: str | None = None, t: dt.datetime | None = None) -> int:
    t = t or now()
    n = 0
    for r in pending(fold(read_events(path), bot)):
        ts = parse_ts(r['ts']) if r.get('ts') else t
        if starshe_min <= 0 or (t - ts).total_seconds() / 60 >= starshe_min:   # без порога — все ждущие (часы машины и Telegram могут расходиться)
            n += 1
    return n


def cmd_proverit(path: str, poroh_min: float = POROH_MIN, povtor_min: float = POVTOR_MIN, bot: str | None = None, t: dt.datetime | None = None, zapisat: bool = True) -> list[dict]:
    """Напоминания: по каждой паре (бот, чат) — ждущие дольше порога; не чаще раза в `povtor_min`. Пишет `napom`, если zapisat."""
    t = t or now()
    ev = read_events(path)
    prev = last_napom(ev)
    groups: dict[tuple, list[dict]] = {}
    for r in pending(fold(ev, bot)):
        ts = parse_ts(r['ts']) if r.get('ts') else t
        if (t - ts).total_seconds() / 60 >= poroh_min and r['chat']:
            groups.setdefault((r['bot'], r['chat']), []).append(r)
    out = []
    for (b, chat), rs in groups.items():
        if (b, chat) in prev and (t - prev[(b, chat)]).total_seconds() / 60 < povtor_min:
            continue
        rs.sort(key=lambda r: r['id'])
        shown = rs[:8]
        lines = [f"⏰ Ваши сообщения ждут разбора дольше {int(poroh_min // 60)} ч — {len(rs)} шт.:"]
        for r in shown:
            ts = parse_ts(r['ts'])
            lines.append(f"• №{r['id']} {ts.astimezone(LONDON).strftime('%H:%M')} ({age_text((t - ts).total_seconds() / 60)}): {r['nachalo']}")
        if len(rs) > len(shown):
            lines.append(f'… и ещё {len(rs) - len(shown)}')
        lines.append('Директор: закрыть — zhurnal-vladeltsa zakryt <№> <задача T-… | P-… | ADR-… | разобрано <почему не задача и не правило>>')
        out.append({'bot': b, 'chat': chat, 'text': '\n'.join(lines), 'ids': [r['id'] for r in rs]})
        if zapisat:
            append(path, {'t': 'napom', 'bot': b, 'chat': chat, 'ts': t.isoformat(timespec='seconds'), 'ids': [r['id'] for r in rs]})
    return out


def cmd_panel(text: str, pane: str | None = None) -> tuple[int, str]:
    """Печатает напоминание строкой в панель tmux сессии бота ($TMUX_PANE — плагин наследует её от claude), как pamyat-svesti. В окно выбора (разрешение, лимит) не печатает."""
    import subprocess
    pane = pane or os.environ.get('TMUX_PANE', '')
    if not pane:
        return 0, 'сессия бота не в tmux — строку в панель не печатаю'
    try:
        lst = subprocess.run(['tmux', 'list-panes', '-a', '-F', '#{pane_id}'], capture_output=True, text=True, timeout=10).stdout.split()
        if pane not in lst:
            return 0, 'панели нет — строку не печатаю'
        screen = subprocess.run(['tmux', 'capture-pane', '-p', '-t', pane], capture_output=True, text=True, timeout=10).stdout
        if 'Enter to confirm' in screen or 'Esc to cancel' in screen:
            return 0, 'в панели окно выбора — строку не печатаю (напоминание ушло только в Telegram)'
        line = '[журнал сообщений владельца] ' + ' '.join(text.split())
        subprocess.run(['tmux', 'send-keys', '-t', pane, '-l', line], check=True, timeout=10)
        subprocess.run(['tmux', 'send-keys', '-t', pane, 'Enter'], check=True, timeout=10)
    except Exception as e:  # noqa: BLE001 — сбой панели не должен ронять напоминание
        return 0, f'строку в панель не напечатал: {e}'
    return 0, 'строка напечатана в панель'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Журнал сообщений владельца (плагин Telegram → строка → закрытие с адресом → напоминание).')
    ap.add_argument('--journal', help='файл журнала (по умолчанию $OWNER_JOURNAL или ' + DEFAULT_PATH + ')')
    ap.add_argument('--bot', help='только этот бот (имя папки состояния плагина: tg-remlab …)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('spisok')
    s.add_argument('--vse', action='store_true')
    z = sub.add_parser('zakryt')
    z.add_argument('nomera')
    z.add_argument('adres', nargs='+')
    z.add_argument('--kto', default='директор')
    tk = sub.add_parser('tekst')
    tk.add_argument('nomer', type=int)
    tk.add_argument('rasshifrovka', nargs='+')
    c = sub.add_parser('schet')
    c.add_argument('--starshe-min', type=float, default=0)
    p = sub.add_parser('proverit')
    p.add_argument('--poroh-min', type=float, default=POROH_MIN)
    p.add_argument('--povtor-min', type=float, default=POVTOR_MIN)
    p.add_argument('--proba', action='store_true', help='не писать napom')
    pn = sub.add_parser('panel')
    pn.add_argument('tekst', nargs='+')
    pn.add_argument('--pane', help='панель tmux (по умолчанию $TMUX_PANE)')
    w = sub.add_parser('zapis')
    w.add_argument('nomer', type=int)
    w.add_argument('chat')
    w.add_argument('tip')
    w.add_argument('tekst', nargs='+')
    a = ap.parse_args(argv)
    path = journal_path(a.journal)
    try:
        if a.cmd == 'spisok':
            print(cmd_spisok(path, a.vse, a.bot))
        elif a.cmd == 'schet':
            print(cmd_schet(path, a.starshe_min, a.bot))
        elif a.cmd == 'proverit':
            print(json.dumps(cmd_proverit(path, a.poroh_min, a.povtor_min, a.bot, zapisat=not a.proba), ensure_ascii=False))
        elif a.cmd == 'zakryt':
            rc, msg = cmd_zakryt(path, a.nomera, ' '.join(a.adres), a.bot, a.kto)
            print(msg, file=sys.stderr if rc else sys.stdout)
            return rc
        elif a.cmd == 'tekst':
            rc, msg = cmd_tekst(path, a.nomer, ' '.join(a.rasshifrovka), a.bot)
            print(msg, file=sys.stderr if rc else sys.stdout)
            return rc
        elif a.cmd == 'panel':
            rc, msg = cmd_panel(' '.join(a.tekst), a.pane)
            print(msg)
            return rc
        elif a.cmd == 'zapis':
            if not a.bot:
                print('ручная запись: задайте --bot', file=sys.stderr)
                return 2
            append(path, {'t': 'msg', 'bot': a.bot, 'id': a.nomer, 'ts': now().isoformat(timespec='seconds'), 'chat': a.chat, 'user': 'ручная запись', 'tip': a.tip,
                          'nachalo': ' '.join(a.tekst)[:NACHALO]})
            print(f'записано №{a.nomer} ({a.bot})')
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
