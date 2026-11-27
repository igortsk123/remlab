#!/usr/bin/env python3
"""Журнал сообщений владельца (T-20261127-175, задача 4; Fable 27 § 2–3 п.4; владелец TG 3612/3614 «регламент полностью»).

ЗАЧЕМ. Слово владельца → задача, правило или решение: разбор держался только на памяти директора (P-069), сообщения терялись в блокноте (21.11, 26.11, 27.11).
Теперь код: плагин Telegram пишет КАЖДОЕ входящее сообщение владельца строкой в журнал (номер = message_id Telegram, время, тип, начало текста, «ждёт разбора»);
директор закрывает строку командой с адресом, куда ушло слово; не закрыто дольше порога (2 ч) — напоминание в тот же чат Telegram.

ФОРМАТ. `<папка состояния бота>/zhurnal.jsonl`, дописывается построчно (JSON на строку), никогда не переписывается:
  {"t":"msg","id":3612,"ts":"2026-11-27T11:36:00+00:00","chat":"95903801","user":"igor","tip":"text|voice|photo|document|…","nachalo":"первые 80 знаков"}
  {"t":"zakryt","id":3612,"ts":"…","adres":"задача T-20261127-175","kto":"директор"}
  {"t":"napom","chat":"95903801","ts":"…","ids":[3612,3614]}          # напоминание отправлено
  Состояние строки = свёртка: есть `zakryt` по её номеру — закрыта (последний адрес), иначе «ждёт разбора». Повторное закрытие — новый адрес перекрывает прежний.
Запись плагином (патч tg-patch-zhurnal) и этим скриптом — один формат; плагин пишет прямо в файл (без запуска процесса), здесь — чтение, закрытие, напоминания.

КОМАНДЫ (папка — `--dir`, по умолчанию $TELEGRAM_STATE_DIR, иначе все `~/.claude/channels/tg-*/` с журналом):
  zhurnal-vladeltsa spisok [--vse]                 # ждущие разбора (--vse — и закрытые), время по Лондону, возраст
  zhurnal-vladeltsa zakryt <№|№-№|№,№,…> <адрес>   # адрес: «задача T-ГГГГММДД-N», «P-NNN», «ADR-NNNN», «план <имя>» или «разобрано» (+ пояснение после пробела)
  zhurnal-vladeltsa schet [--starshe-min N]        # одно число: ждущих разбора (только старше N минут — для стража правил, сообщения без разбора дольше 2 ч)
  zhurnal-vladeltsa proverit [--poroh-min 120] [--povtor-min 120]   # JSON-список [{"chat","text"}] напоминаний; пишет `napom` (плагин шлёт и ничего не помнит)
  zhurnal-vladeltsa zapis <№> <чат> <тип> <текст>  # ручная запись строки (проба, восстановление пропущенного)
Закрыть строку без адреса нельзя: «закрыто» без «куда ушло» — та же потеря, что и без журнала. Код выхода: 0 — готово, 2 — ошибка ввода.
Стандартная библиотека; на проверку не влияют ни сеть, ни Telegram."""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys

try:
    from zoneinfo import ZoneInfo
    LONDON = ZoneInfo('Europe/London')
except Exception:  # noqa: BLE001 — без базы часовых поясов: UTC, время всё равно читаемо
    LONDON = dt.timezone.utc

FILE = 'zhurnal.jsonl'
POROH_MIN = 120      # ждёт разбора дольше — напоминание (владелец/Fable 27: 2 часа)
POVTOR_MIN = 120     # повторное напоминание тому же чату — не чаще
NACHALO = 80
# адрес закрытия: куда ушло слово владельца
ADRES_RE = re.compile(r'^(задача\s+T-\d{8}-\d+[\w./-]*|P-\d{3}|ADR-\d{4}|план\s+\S+|разобрано)(\s+.*)?$')


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_ts(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def dirs_default() -> list[str]:
    e = os.environ.get('TELEGRAM_STATE_DIR')
    if e:
        return [e]
    home = os.path.expanduser('~/.claude/channels')
    return sorted(os.path.dirname(p) for p in glob.glob(os.path.join(home, '*', FILE)))


def read_events(d: str) -> list[dict]:
    p = os.path.join(d, FILE)
    out = []
    if not os.path.isfile(p):
        return out
    for ln in open(p, encoding='utf-8'):
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:  # noqa: BLE001 — битая строка (обрыв записи) не роняет журнал
            continue
    return out


def fold(events: list[dict]) -> list[dict]:
    """Свёртка: строки сообщений в порядке прихода; closed/adres — по последнему `zakryt`; napom — время последнего напоминания чату."""
    rows: dict[int, dict] = {}
    order: list[int] = []
    for e in events:
        t = e.get('t')
        if t == 'msg' and isinstance(e.get('id'), int):
            if e['id'] not in rows:
                order.append(e['id'])
                rows[e['id']] = {'id': e['id'], 'ts': e.get('ts'), 'chat': str(e.get('chat', '')), 'user': e.get('user', ''), 'tip': e.get('tip', 'text'),
                                 'nachalo': e.get('nachalo', ''), 'adres': None, 'closed_ts': None}
        elif t == 'zakryt' and e.get('id') in rows:
            rows[e['id']]['adres'] = e.get('adres')
            rows[e['id']]['closed_ts'] = e.get('ts')
    return [rows[i] for i in order]


def last_napom(events: list[dict]) -> dict[str, dt.datetime]:
    m: dict[str, dt.datetime] = {}
    for e in events:
        if e.get('t') == 'napom' and e.get('ts'):
            m[str(e.get('chat', ''))] = parse_ts(e['ts'])
    return m


def pending(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not r['adres']]


def append(d: str, ev: dict) -> None:
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, FILE), 'a', encoding='utf-8') as f:
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
    if not ADRES_RE.match(a):
        raise ValueError('адрес закрытия: «задача T-ГГГГММДД-N», «P-NNN», «ADR-NNNN», «план <имя>» или «разобрано» (после адреса можно пояснение)')
    return a


def cmd_zakryt(d: str, spec: str, adres: str, kto: str = 'директор') -> tuple[int, str]:
    ids = parse_ids(spec)
    adres = check_adres(adres)
    rows = {r['id']: r for r in fold(read_events(d))}
    unknown = [i for i in ids if i not in rows]
    if unknown:
        return 2, 'нет в журнале: ' + ', '.join(str(i) for i in unknown) + ' (проверь номер; пропущенное — командой zapis)'
    for i in ids:
        append(d, {'t': 'zakryt', 'id': i, 'ts': now().isoformat(timespec='seconds'), 'adres': adres, 'kto': kto})
    return 0, f'закрыто {len(ids)}: {", ".join(str(i) for i in ids)} → {adres}'


def cmd_spisok(dirs: list[str], vse: bool = False, t: dt.datetime | None = None) -> str:
    t = t or now()
    lines = []
    for d in dirs:
        rows = fold(read_events(d))
        show = rows if vse else pending(rows)
        for r in show:
            ts = parse_ts(r['ts']) if r.get('ts') else t
            mins = (t - ts).total_seconds() / 60
            tail = f"→ {r['adres']}" if r['adres'] else f'ждёт разбора {age_text(mins)}'
            lines.append(f"№{r['id']} {ts.astimezone(LONDON).strftime('%d.%m %H:%M')} [{r['tip']}] {r['nachalo']} — {tail}")
    return '\n'.join(lines) if lines else 'ждущих разбора нет'


def cmd_schet(dirs: list[str], starshe_min: float = 0, t: dt.datetime | None = None) -> int:
    t = t or now()
    n = 0
    for d in dirs:
        for r in pending(fold(read_events(d))):
            ts = parse_ts(r['ts']) if r.get('ts') else t
            if starshe_min <= 0 or (t - ts).total_seconds() / 60 >= starshe_min:   # без порога — все ждущие (часы машины и Telegram могут расходиться)
                n += 1
    return n


def cmd_proverit(d: str, poroh_min: float = POROH_MIN, povtor_min: float = POVTOR_MIN, t: dt.datetime | None = None, zapisat: bool = True) -> list[dict]:
    """Напоминания: по каждому чату — ждущие дольше порога; не чаще раза в `povtor_min`. Пишет `napom`, если zapisat."""
    t = t or now()
    ev = read_events(d)
    rows = fold(ev)
    prev = last_napom(ev)
    by_chat: dict[str, list[dict]] = {}
    for r in pending(rows):
        ts = parse_ts(r['ts']) if r.get('ts') else t
        if (t - ts).total_seconds() / 60 >= poroh_min and r['chat']:
            by_chat.setdefault(r['chat'], []).append(r)
    out = []
    for chat, rs in by_chat.items():
        if chat in prev and (t - prev[chat]).total_seconds() / 60 < povtor_min:
            continue
        rs.sort(key=lambda r: r['id'])
        shown = rs[:8]
        lines = [f"⏰ Ваши сообщения ждут разбора дольше {int(poroh_min // 60)} ч — {len(rs)} шт.:"]
        for r in shown:
            ts = parse_ts(r['ts'])
            lines.append(f"• №{r['id']} {ts.astimezone(LONDON).strftime('%H:%M')} ({age_text((t - ts).total_seconds() / 60)}): {r['nachalo']}")
        if len(rs) > len(shown):
            lines.append(f'… и ещё {len(rs) - len(shown)}')
        lines.append('Директор: закрыть — zhurnal-vladeltsa zakryt <№> <задача T-… | P-… | ADR-… | разобрано>')
        out.append({'chat': chat, 'text': '\n'.join(lines), 'ids': [r['id'] for r in rs]})
        if zapisat:
            append(d, {'t': 'napom', 'chat': chat, 'ts': t.isoformat(timespec='seconds'), 'ids': [r['id'] for r in rs]})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Журнал сообщений владельца (плагин Telegram → строка → закрытие с адресом → напоминание).')
    ap.add_argument('--dir', action='append', default=[], help='папка состояния бота (по умолчанию $TELEGRAM_STATE_DIR или все tg-* с журналом)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('spisok')
    s.add_argument('--vse', action='store_true')
    z = sub.add_parser('zakryt')
    z.add_argument('nomera')
    z.add_argument('adres', nargs='+')
    z.add_argument('--kto', default='директор')
    c = sub.add_parser('schet')
    c.add_argument('--starshe-min', type=float, default=0)
    p = sub.add_parser('proverit')
    p.add_argument('--poroh-min', type=float, default=POROH_MIN)
    p.add_argument('--povtor-min', type=float, default=POVTOR_MIN)
    p.add_argument('--proba', action='store_true', help='не писать napom')
    w = sub.add_parser('zapis')
    w.add_argument('nomer', type=int)
    w.add_argument('chat')
    w.add_argument('tip')
    w.add_argument('tekst', nargs='+')
    a = ap.parse_args(argv)
    dirs = a.dir or dirs_default()
    if not dirs:
        print('нет папки состояния бота: задайте --dir или TELEGRAM_STATE_DIR', file=sys.stderr)
        return 2
    try:
        if a.cmd == 'spisok':
            print(cmd_spisok(dirs, a.vse))
        elif a.cmd == 'schet':
            print(cmd_schet(dirs, a.starshe_min))
        elif a.cmd == 'proverit':
            out = []
            for d in dirs:
                out.extend(cmd_proverit(d, a.poroh_min, a.povtor_min, zapisat=not a.proba))
            print(json.dumps(out, ensure_ascii=False))
        elif a.cmd == 'zakryt':
            if len(dirs) != 1:   # без --dir: берём единственную папку, где есть все названные номера (номера у разных ботов могут совпасть)
                try:
                    want = parse_ids(a.nomera)
                except ValueError as e:
                    print(str(e), file=sys.stderr)
                    return 2
                cand = [d for d in dirs if set(want) <= {r['id'] for r in fold(read_events(d))}]
                if len(cand) != 1:
                    print('не ясно, в какой папке закрывать (подходят: %s) — задайте --dir' % (', '.join(cand) or 'ни одна'), file=sys.stderr)
                    return 2
                dirs = cand
            rc, msg = cmd_zakryt(dirs[0], a.nomera, ' '.join(a.adres), a.kto)
            print(msg)
            return rc
        elif a.cmd == 'zapis':
            if len(dirs) != 1:
                print('запись — только для одной папки: задайте --dir', file=sys.stderr)
                return 2
            append(dirs[0], {'t': 'msg', 'id': a.nomer, 'ts': now().isoformat(timespec='seconds'), 'chat': a.chat, 'user': 'ручная запись', 'tip': a.tip,
                             'nachalo': ' '.join(a.tekst)[:NACHALO]})
            print(f'записано №{a.nomer}')
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
