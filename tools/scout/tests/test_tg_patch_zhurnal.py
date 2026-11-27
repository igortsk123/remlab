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
    ok(len(done) == 2 and 'owner-journal' in s2 and '__zhurnalTimer' in s2, 'патч ставит оба куска')
    ok(s2.index('owner-journal') < s2.index('Typing indicator'), 'запись — до индикатора «печатает», после перехвата разрешений')
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
    ok(P.BLOCK_MSG.count('flag: \'a\'') == 1 and 'owner-journal' in P.BLOCK_MSG, 'запись — дописыванием в журнал машины, один раз')
    ok('.config/zhurnal-vladeltsa' in P.BLOCK_MSG and '.config/zhurnal-vladeltsa' in P.BLOCK_TIMER and 'access.json' not in P.BLOCK_MSG + P.BLOCK_TIMER,
       'включение — файл настроек бота в ~/.config; access.json плагина не трогаем')
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
    pz = os.path.join(binp, 'tg-patch-zhurnal')
    ok(os.path.isfile(pz) and os.access(pz, os.X_OK), 'патчер поставлен как tg-patch-zhurnal (стабильный путь для вызова из tg-patch-limit)')
    r2 = subprocess.run([sys.executable, pz, '--server', srv, '--bin', binp, '--proba'], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    ok(r2.returncode == 0 and 'уже есть' in r2.stdout, 'поставленный tg-patch-zhurnal запускается из своей папки и видит «уже есть»')
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

    # 2б. поведение патча под bun на заглушке handleInbound: включение файлом настроек, только владелец, без файла — молчит, сбой не роняет приём
    bun = next((t for t in (os.path.expanduser('~/.bun/bin/bun'), shutil.which('bun')) if t and os.path.isfile(t)), None)
    if bun:
        head = ("import { readFileSync, writeFileSync, mkdirSync } from 'fs'\nimport { homedir } from 'os'\nimport { join, sep } from 'path'\n"
                "const STATE_DIR = process.env.TG_STATE_DIR as string\nconst bot: any = { api: { sendChatAction: () => {}, sendMessage: async () => {} } }\n")
        body = P.patch_text(FAKE.replace("import { join } from 'path'\n", ''))[0]
        body = body.replace('async function handleInbound(ctx, text, downloadImage, attachment) {', 'async function handleInbound(ctx: any, text: string, downloadImage: boolean, attachment: any) {')
        cut = body[:body.index('void (async () => {')]      # без bot.start: берём только функцию handleInbound
        tail = ("\nasync function main() {\n  const mk = (id: number, uid: number) => ({ message: { message_id: id, date: 1795780000 }, chat: { id: 95903801 }, from: { id: uid, username: 'u' + uid } })\n"
                "  await handleInbound(mk(1, 95903801), 'Привет   мир', false, undefined)\n  await handleInbound(mk(2, 459255913), 'чужой', false, undefined)\n"
                "  await handleInbound(mk(3, 95903801), 'фото', true, undefined)\n}\nmain()\n")

        def scenario(cfg):
            home = tempfile.mkdtemp(prefix='tgz-home-')
            st = os.path.join(home, '.claude', 'channels', 'tg-test')
            os.makedirs(st)
            if cfg is not None:
                os.makedirs(os.path.join(home, '.config', 'zhurnal-vladeltsa'))
                open(os.path.join(home, '.config', 'zhurnal-vladeltsa', 'tg-test.json'), 'w').write(cfg)
            f = os.path.join(home, 'h.ts')
            open(f, 'w', encoding='utf-8').write(head + cut + tail)
            rr = subprocess.run([bun, f], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=dict(os.environ, HOME=home, TG_STATE_DIR=st))
            jf = os.path.join(home, '.local', 'state', 'remlab', 'owner-journal', 'journal.jsonl')
            return rr, (open(jf, encoding='utf-8').read().splitlines() if os.path.isfile(jf) else None)
        import json as _j
        rr, lines = scenario('{"owner":"95903801","panel":true}')
        ev = [_j.loads(x) for x in lines or []]
        ok(rr.returncode == 0 and [e['id'] for e in ev] == [1, 3], 'под bun: с файлом настроек записаны сообщения владельца (1, 3), чужого отправителя (2) — нет')
        ok(len(ev) == 2 and ev[0]['bot'] == 'tg-test' and ev[0]['nachalo'] == 'Привет мир' and ev[0]['tip'] == 'text' and ev[1]['tip'] == 'photo',
           'под bun: бот = имя папки состояния, пробелы схлопнуты, тип text/photo')
        rr, lines = scenario(None)
        ok(rr.returncode == 0 and lines is None, 'отрицательный контроль: без файла настроек бот молчит — журнала нет, приём не упал')
        rr, lines = scenario('это не json')
        ok(rr.returncode == 0 and lines is None, 'отрицательный контроль: битый файл настроек — молчит, приём не упал')
        rr, lines = scenario('{"owner":"1"}')
        ok(rr.returncode == 0 and lines is None, 'отрицательный контроль: в настройках другой владелец — никто не записан')
    else:
        print('  (bun нет — поведение патча не проверялось)')

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
