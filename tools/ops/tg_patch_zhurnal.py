#!/usr/bin/env python3
"""Патч плагина Telegram: журнал сообщений владельца (T-20261127-175, задача 4; Fable 27 § 2–3 п.4; владелец TG 3612/3614).
Тот же механизм, что `~/.local/bin/tg-patch-limit`: правит `server.ts` плагина (`~/.claude/plugins/cache/claude-plugins-official/telegram/*/server.ts`) по якорям,
идемпотентно, перед записью — копия `server.ts.bak-zhurnal-<время>`; запускать при каждом старте ведущего (после `tg-patch-limit`), после обновления плагина патч встаёт сам.
Действует после перезапуска сервера плагина (перезапуск вкладки `tg-*` или `/mcp reconnect plugin:telegram:telegram`).

ДОБАВЛЯЕТ (два куска, каждый — между маркерами `// >>> zhurnal-vladeltsa …` и `// <<< zhurnal-vladeltsa`):
  1. В `handleInbound` (после перехвата ответов на разрешения, до «typing»): каждое входящее сообщение допущенного отправителя → строка `{"t":"msg",…}` в
     `<папка состояния бота>/zhurnal.jsonl` (формат и команды — `tools/ops/zhurnal_vladeltsa.py`). Сбой записи приём сообщений не останавливает.
     Команды бота (/limit, /plan …) сюда не доходят — их отвечает код раньше.
  2. В `onStart` бота (один раз за процесс): раз в 10 минут `zhurnal-vladeltsa proverit` → ждущие разбора дольше 2 ч → напоминание в чат, откуда пришло сообщение.
     Нет `~/.local/bin/zhurnal-vladeltsa` — тихо ничего не делает.
УСТАНАВЛИВАЕТ команду `~/.local/bin/zhurnal-vladeltsa` (копия `zhurnal_vladeltsa.py`; копия, а не ссылка на папку проекта: sshfs не должен стоять между плагином и журналом).

ИСПОЛЬЗОВАНИЕ:
  python3 tools/ops/tg_patch_zhurnal.py            # наложить (идемпотентно) + поставить команду
  python3 tools/ops/tg_patch_zhurnal.py --proba    # ничего не писать, сказать, что сделал бы
  python3 tools/ops/tg_patch_zhurnal.py --otkat    # снять оба куска (по маркерам; прочие патчи tg-patch-limit не трогает); команду не удаляет
  --server <путь к server.ts> (повторяемый) и --bin <папка> — для проб и тестов.
Якорь не найден (плагин изменился) — выход 1 с названием якоря, файл не тронут."""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import stat
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OPEN = '// >>> zhurnal-vladeltsa'
CLOSE = '// <<< zhurnal-vladeltsa'

# якорь 1: перед индикатором «печатает» в handleInbound (после перехвата ответов на разрешения — они сообщениями владельца не считаются)
ANCHOR_MSG = '  // Typing indicator — signals "processing" until we reply (or ~5s elapses).'
BLOCK_MSG = f"""  {OPEN} (T-20261127-175/4): журнал сообщений владельца — строка «ждёт разбора» на каждое входящее; сбой записи приём не останавливает.
  try {{
    if (msgId != null) {{
      const zhTip = attachment?.kind ?? (downloadImage ? 'photo' : 'text')
      const zhNachalo = text.replace(/\\s+/g, ' ').trim().slice(0, 80)
      const zhTs = new Date((ctx.message?.date ?? 0) * 1000).toISOString()
      writeFileSync(join(STATE_DIR, 'zhurnal.jsonl'), JSON.stringify({{ t: 'msg', id: msgId, ts: zhTs, chat: chat_id, user: from.username ?? String(from.id), tip: zhTip, nachalo: zhNachalo }}) + '\\n', {{ flag: 'a' }})
    }}
  }} catch {{}}
  {CLOSE}

"""

# якорь 2: после строки «polling as» в onStart
ANCHOR_TIMER = '          process.stderr.write(`telegram channel: polling as @${info.username}\\n`)'
BLOCK_TIMER = f"""          {OPEN} (T-20261127-175/4): раз в 10 минут — напоминание о сообщениях без разбора дольше 2 ч (zhurnal-vladeltsa proverit).
          const zhG = globalThis as any
          if (!zhG.__zhurnalTimer) {{
            zhG.__zhurnalTimer = setInterval(async () => {{
              try {{
                const {{ execFile }} = await import('child_process')
                const zhOut = await new Promise<string>(resolve => {{
                  execFile(join(homedir(), '.local/bin/zhurnal-vladeltsa'), ['--dir', STATE_DIR, 'proverit'], {{ encoding: 'utf8', timeout: 20000 }},
                    (_err, out) => resolve(String(out ?? '')))
                }})
                for (const n of JSON.parse(zhOut.trim() || '[]')) await bot.api.sendMessage(n.chat, n.text).catch(() => {{}})
              }} catch {{}}
            }}, 10 * 60 * 1000)
          }}
          {CLOSE}
"""

BLOCK_RE = re.compile(r'[ ]*' + re.escape(OPEN) + r'.*?' + re.escape(CLOSE) + r'\n\n?', re.S)


def patch_text(s: str) -> tuple[str, list[str]]:
    """Возвращает (новый текст, что сделано). Падает ValueError, если нужного якоря нет."""
    done: list[str] = []
    if 'zhurnal.jsonl' not in s:
        if s.count(ANCHOR_MSG) != 1:
            raise ValueError('якорь записи (Typing indicator в handleInbound) не найден или не один — плагин изменился, патч вручную')
        s = s.replace(ANCHOR_MSG, BLOCK_MSG + ANCHOR_MSG)
        done.append('запись входящих в журнал')
    if '__zhurnalTimer' not in s:
        if s.count(ANCHOR_TIMER) != 1:
            raise ValueError('якорь напоминаний (polling as в onStart) не найден или не один — плагин изменился, патч вручную')
        s = s.replace(ANCHOR_TIMER, ANCHOR_TIMER + '\n' + BLOCK_TIMER.rstrip('\n'))
        done.append('напоминания раз в 10 мин')
    return s, done


def unpatch_text(s: str) -> tuple[str, int]:
    s2, n = BLOCK_RE.subn('', s)
    return s2, n


def install_cli(bindir: str, proba: bool) -> str:
    src = os.path.join(HERE, 'zhurnal_vladeltsa.py')
    dst = os.path.join(bindir, 'zhurnal-vladeltsa')
    new = open(src, encoding='utf-8').read()
    old = open(dst, encoding='utf-8').read() if os.path.isfile(dst) else None
    if old == new:
        return f'команда уже стоит: {dst}'
    if proba:
        return f'ПРОБА: поставил бы команду {dst}'
    os.makedirs(bindir, exist_ok=True)
    if old is not None:
        shutil.copy2(dst, f"{dst}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    open(dst, 'w', encoding='utf-8').write(new)
    os.chmod(dst, os.stat(dst).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return f'команда поставлена: {dst}'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Патч плагина Telegram: журнал сообщений владельца.')
    ap.add_argument('--proba', action='store_true')
    ap.add_argument('--otkat', action='store_true')
    ap.add_argument('--server', action='append', default=[])
    ap.add_argument('--bin', default=os.path.expanduser('~/.local/bin'))
    a = ap.parse_args(argv)
    servers = a.server or sorted(glob.glob(os.path.expanduser('~/.claude/plugins/cache/claude-plugins-official/telegram/*/server.ts')))
    if not servers:
        print('плагина telegram нет (~/.claude/plugins/cache/claude-plugins-official/telegram/*/server.ts)')
        return 1
    rc = 0
    for p in servers:
        s = open(p, encoding='utf-8').read()
        if a.otkat:
            s2, n = unpatch_text(s)
            if not n:
                print(f'откатывать нечего: {p}')
            elif a.proba:
                print(f'ПРОБА: снял бы {n} кусков журнала: {p}')
            else:
                shutil.copy2(p, f"{p}.bak-zhurnal-{time.strftime('%Y%m%d-%H%M%S')}")
                open(p, 'w', encoding='utf-8').write(s2)
                print(f'снято {n} кусков журнала: {p}')
            continue
        try:
            s2, done = patch_text(s)
        except ValueError as e:
            print(f'{p}: {e}', file=sys.stderr)
            rc = 1
            continue
        if not done:
            print(f'уже есть (журнал сообщений владельца): {p}')
        elif a.proba:
            print(f"ПРОБА: добавил бы {', '.join(done)}: {p}")
        else:
            shutil.copy2(p, f"{p}.bak-zhurnal-{time.strftime('%Y%m%d-%H%M%S')}")
            open(p, 'w', encoding='utf-8').write(s2)
            print(f"добавлено {', '.join(done)}: {p}")
    if not a.otkat:
        print(install_cli(a.bin, a.proba))
    return rc


if __name__ == '__main__':
    sys.exit(main())
