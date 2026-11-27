#!/usr/bin/env python3
"""Тест патча плагина Telegram «журнал сообщений владельца» (T-20261127-175, задача 4): якоря, идемпотентность, откат побайтно, отказ при изменившемся плагине,
установка команды, копия перед записью; если на машине есть настоящий плагин — патч на его копии + проверка синтаксиса (bun/esbuild, если есть).
Запуск: python tools/scout/tests/test_tg_patch_zhurnal.py (стандартная библиотека)."""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_tg_patch_zhurnal')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'ops'))
import tg_patch_zhurnal as P  # noqa: E402

BAD = []
FAKE = """import { join } from 'path'
async function handleInbound(ctx, text, downloadImage, attachment) {
  const msgId = ctx.message?.message_id
  const chat_id = String(ctx.chat.id)
  const from = ctx.from
  const permMatch = null
  if (permMatch) { return }

  // Typing indicator — signals "processing" until we reply (or ~5s elapses).
  void bot.api.sendChatAction(chat_id, 'typing')
}
void (async () => {
  await bot.start({
    onStart: info => {
      attempt = 0
          process.stderr.write(`telegram channel: polling as @${info.username}\\n`)
      void bot.api.setMyCommands([], {})
    },
  })
})()
"""


def ok(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        BAD.append(msg)


def run(*a):
    return subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'ops', 'tg_patch_zhurnal.py'), *a], capture_output=True, text=True, stdin=subprocess.DEVNULL)


def main():
    # 1. функции на синтетическом тексте
    s2, done = P.patch_text(FAKE)
    ok(len(done) == 2 and 'zhurnal.jsonl' in s2 and '__zhurnalTimer' in s2, 'патч ставит оба куска')
    ok(s2.index('zhurnal.jsonl') < s2.index('Typing indicator'), 'запись — до индикатора «печатает», после перехвата разрешений')
    s3, done3 = P.patch_text(s2)
    ok(s3 == s2 and done3 == [], 'повторный патч ничего не меняет (идемпотентность)')
    back, n = P.unpatch_text(s2)
    ok(n == 2 and back == FAKE, 'откат снимает оба куска и возвращает текст побайтно')
    ok(P.unpatch_text(FAKE)[1] == 0, 'откат чистого текста — нечего снимать')
    try:
        P.patch_text(FAKE.replace('// Typing indicator', '// Другой комментарий'))
        ok(False, 'без якоря записи патч обязан отказать')
    except ValueError as e:
        ok('якорь записи' in str(e), 'без якоря записи — отказ с названием якоря')
    try:
        P.patch_text(FAKE.replace('polling as', 'слушаем как'))
        ok(False, 'без якоря напоминаний патч обязан отказать')
    except ValueError as e:
        ok('якорь напоминаний' in str(e), 'без якоря напоминаний — отказ с названием якоря')
    ok(P.BLOCK_MSG.count('flag: \'a\'') == 1 and 'STATE_DIR' in P.BLOCK_MSG, 'запись — дописыванием в STATE_DIR, один раз')
    ok(P.BLOCK_TIMER.lstrip().split('\n')[1].lstrip().startswith('const zhG'), 'после маркера напоминаний идёт `const` (скобка в начале строки без `;` склеила бы вызов)')

    # 2. процесс: файл на диске, проба, копия, откат, команда
    d = tempfile.mkdtemp(prefix='tgz-')
    srv, binp = os.path.join(d, 'server.ts'), os.path.join(d, 'bin')
    open(srv, 'w', encoding='utf-8').write(FAKE)
    r = run('--server', srv, '--bin', binp, '--proba')
    ok(r.returncode == 0 and 'ПРОБА' in r.stdout and open(srv, encoding='utf-8').read() == FAKE and not os.path.exists(binp), 'проба: сказала, что сделает, файл и команда не тронуты')
    r = run('--server', srv, '--bin', binp)
    ok(r.returncode == 0 and '__zhurnalTimer' in open(srv, encoding='utf-8').read(), 'наложение на файл')
    ok(len(glob.glob(srv + '.bak-zhurnal-*')) == 1, 'перед записью — копия .bak-zhurnal-*')
    cli = os.path.join(binp, 'zhurnal-vladeltsa')
    ok(os.path.isfile(cli) and os.access(cli, os.X_OK), 'команда zhurnal-vladeltsa поставлена и исполняема')
    r = run('--server', srv, '--bin', binp)
    ok(r.returncode == 0 and 'уже есть' in r.stdout and 'уже стоит' in r.stdout, 'повторный запуск: «уже есть», «уже стоит»')
    r = run('--server', srv, '--bin', binp, '--otkat')
    ok(r.returncode == 0 and open(srv, encoding='utf-8').read() == FAKE and os.path.isfile(cli), 'откат файла; команда остаётся')
    open(srv, 'w', encoding='utf-8').write(FAKE.replace('polling as', 'x'))
    r = run('--server', srv, '--bin', binp)
    ok(r.returncode == 1 and 'якорь' in r.stderr, 'плагин изменился — код 1 и название якоря, файл не тронут')
    ok(open(srv, encoding='utf-8').read() == FAKE.replace('polling as', 'x'), 'при отказе файл плагина не тронут')
    r = run('--server', os.path.join(d, 'нет.ts'), '--bin', binp)
    ok(r.returncode != 0, 'нет файла плагина — не молчаливый успех')

    # 3. настоящий плагин на машине (если есть): патч на копии + синтаксис
    real = sorted(glob.glob(os.path.expanduser('~/.claude/plugins/cache/claude-plugins-official/telegram/*/server.ts')))
    if real:
        cp = os.path.join(d, 'real-server.ts')
        shutil.copy(real[-1], cp)
        r = run('--server', cp, '--bin', binp)
        ok(r.returncode == 0, 'настоящий плагин: патч ложится на копию (якоря на месте)')
        for tool in (os.path.expanduser('~/.bun/bin/bun'), shutil.which('bun')):
            if tool and os.path.isfile(tool):
                rr = subprocess.run([tool, 'build', '--no-bundle', cp], capture_output=True, text=True, stdin=subprocess.DEVNULL)
                ok(rr.returncode == 0, 'настоящий плагин: синтаксис после патча (bun build) в порядке')
                break
        else:
            print('  (bun нет — синтаксис настоящего плагина не проверялся)')
    else:
        print('  (настоящего плагина нет — проверка на копии пропущена)')

    print('\nПровалов: %d' % len(BAD))
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
