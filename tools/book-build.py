#!/usr/bin/env python3
"""Книга о продукте → страница `/test/book/` (план book-memory-sync п.5).

ЗАЧЕМ. Владелец читает книгу на телефоне; страница собиралась руками 13.10, и сборщика в репо не было — после правок
книги страница отставала. Теперь сборка повторяемая: `.memory_bank/guides/product-book.md` → один HTML с оглавлением,
абзацы «Сегодня» выделены. Только стандартная библиотека (без пакета markdown): заголовки, абзацы, списки, `код`,
**жирный**, *курсив*, ссылки. Код в обратных кавычках защищается ДО разметки курсива — иначе `conv-*` и `b2b-*`
превращались в курсив (ошибка ручной сборки 13.10).

  python3 tools/book-build.py                 # собрать в ~/scout-scenes/book/index.html
  python3 tools/book-build.py --publish       # и выложить на прод
  python3 tools/book-build.py --selftest
"""
import html
import os
import re
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = os.path.join(ROOT, '.memory_bank', 'guides', 'product-book.md')
OUT = os.path.expanduser('~/scout-scenes/book/index.html')
CSS = """:root{--bg:#faf8f4;--fg:#1f1d1a;--muted:#6b6560;--accent:#8a3b1f;--note:#fff3e6;--noteb:#e2b48c;--codebg:rgba(128,128,128,.12);--maxw:42rem}
@media (prefers-color-scheme:dark){:root{--bg:#171513;--fg:#ece7df;--muted:#a39b91;--accent:#e0906f;--note:#2a211a;--noteb:#6b4a33;--codebg:rgba(255,255,255,.08)}}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:18px/1.65 Georgia,"Times New Roman",serif}
main{max-width:var(--maxw);margin:0 auto;padding:24px 18px 64px}
h1{font-size:1.9rem;line-height:1.2;margin:.4em 0 .3em;font-weight:700}
h2{font-size:1.45rem;line-height:1.25;margin:2em 0 .6em;color:var(--accent);scroll-margin-top:16px}
h3{font-size:1.1rem;line-height:1.3;margin:1.5em 0 .4em}
p{margin:0 0 1em;hyphens:auto;-webkit-hyphens:auto}
ol,ul{padding-left:1.4em;margin:0 0 1.2em} li{margin:0 0 .7em;hyphens:auto}
p.today{background:var(--note);border-left:4px solid var(--noteb);padding:.6em .9em;font-style:italic;font-size:.95em;border-radius:0 6px 6px 0}
p.today .tag{display:inline-block;font-style:normal;font-weight:700;font-size:.78em;letter-spacing:.04em;text-transform:uppercase;color:var(--accent);margin-right:.4em}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.84em;background:var(--codebg);padding:.05em .3em;border-radius:4px;word-break:break-all}
.meta{color:var(--muted);font-size:.9rem;margin-bottom:1.2em}
.toc{margin:1.2em 0 2em;padding:1em 1.1em;border:1px solid rgba(128,128,128,.25);border-radius:8px;font-size:.95em}
.toc-title{font-weight:700;margin-bottom:.4em}
.toc a{display:block;color:var(--accent);text-decoration:none;padding:.15em 0}
footer{color:var(--muted);font-size:.85rem;margin-top:3em;border-top:1px solid rgba(128,128,128,.3);padding-top:1em}
@media (max-width:480px){body{font-size:17px}main{padding:18px 16px 48px}h1{font-size:1.6rem}ol,ul{padding-left:1.2em}}"""


def inline(t: str) -> str:
    """Строчная разметка. Код вынимается ПЕРВЫМ и возвращается последним — внутри него ничего не размечается."""
    codes: list = []

    def keep(m):
        codes.append(m.group(1))
        return f'\x00{len(codes) - 1}\x00'
    t = re.sub(r'`([^`]+)`', keep, t)
    t = html.escape(t, quote=False)
    t = re.sub(r'\[([^\]]+)\]\((https?://[^)\s]+)\)', lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', t)
    t = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', t)
    t = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'<em>\1</em>', t)
    return re.sub(r'\x00(\d+)\x00', lambda m: f'<code>{html.escape(codes[int(m.group(1))], quote=False)}</code>', t)


def build(md: str, today: str) -> str:
    md = re.sub(r'\A---\n.*?\n---\n', '', md, flags=re.S)       # шапка банка памяти — не для читателя
    blocks = re.split(r'\n\s*\n', md.strip())
    body, toc, title, n = [], [], 'Книга', 0
    for b in blocks:
        lines = b.split('\n')
        h = re.match(r'^(#{1,3})\s+(.+)$', lines[0])
        if h and len(lines) == 1:
            lvl, txt = len(h.group(1)), h.group(2).strip()
            if lvl == 1:
                title = txt
                body.append(f'<h1>{inline(txt)}</h1>')
                continue
            if lvl == 2:
                n += 1
                toc.append(f'<a href="#g{n}">{inline(txt)}</a>')
                body.append(f'<h2 id="g{n}">{inline(txt)}</h2>')
            else:
                body.append(f'<h3>{inline(txt)}</h3>')
            continue
        if all(re.match(r'^(\d+\.|-)\s', ln) or ln.startswith('   ') or ln.startswith('  ') for ln in lines):
            tag = 'ol' if re.match(r'^\d+\.', lines[0]) else 'ul'
            items, cur = [], ''
            for ln in lines:
                if re.match(r'^(\d+\.|-)\s', ln):
                    if cur:
                        items.append(cur)
                    cur = re.sub(r'^(\d+\.|-)\s+', '', ln)
                else:
                    cur += ' ' + ln.strip()
            items.append(cur)
            body.append(f'<{tag}>' + ''.join(f'<li>{inline(i)}</li>' for i in items) + f'</{tag}>')
            continue
        text = ' '.join(ln.strip() for ln in lines)
        m = re.match(r'^\*(Сегодня[^*]*?)(.*)\*$', text, re.S)
        if text.startswith('*Сегодня') and text.endswith('*'):
            inner = text[1:-1]
            body.append(f'<p class="today"><span class="tag">Сегодня</span>{inline(inner[len("Сегодня"):].lstrip())}</p>')
        else:
            body.append(f'<p>{inline(text)}</p>')
        del m
    if toc:
        nav = '<nav class="toc"><div class="toc-title">Оглавление</div>' + ''.join(toc) + '</nav>'
        first_h2 = next(i for i, x in enumerate(body) if x.startswith('<h2'))
        body.insert(first_h2, nav)
    return ('<!doctype html>\n<html lang="ru"><head><meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n<meta name="robots" content="noindex, nofollow">\n'
            f'<title>{html.escape(title)}</title>\n<style>\n{CSS}\n</style></head>\n<body><main>\n'
            f'<div class="meta">Книга о продукте · собрана {today} из банка памяти · для владельца</div>\n'
            + '\n'.join(body) +
            '\n<footer>Пометки «Сегодня» показывают, как обстоят дела сейчас; всё остальное — идеал, к которому идём. '
            'Имена в скобках — скрипты и функции в коде, чтобы агент мог ориентироваться по той же книге.</footer>\n</main></body></html>\n')


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    ok('код защищён от курсива', inline('планы `conv-*` и `b2b-*`') == 'планы <code>conv-*</code> и <code>b2b-*</code>')
    ok('курсив и жирный', inline('*важно* и **очень**') == '<em>важно</em> и <b>очень</b>')
    ok('экранирование', inline('a < b') == 'a &lt; b')
    doc = build('---\ntier: 2\n---\n# Книга\n\nВступление.\n\n## Глава 1. А\n\n*Сегодня (`b2b-05`): ещё нет.*\n\n1. раз\n2. два', '2026-10-14')
    ok('шапка банка снята, заголовок и оглавление', '<h1>Книга</h1>' in doc and 'href="#g1"' in doc and 'tier:' not in doc)
    ok('абзац «Сегодня» выделен, код внутри', '<p class="today"><span class="tag">Сегодня</span>(<code>b2b-05</code>): ещё нет.</p>' in doc)
    ok('нумерованный список', '<ol><li>раз</li><li>два</li></ol>' in doc)
    return 1 if bad else 0


def main() -> int:
    doc = build(open(BOOK, encoding='utf-8').read(), date.today().strftime('%d.%m.%Y'))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w', encoding='utf-8').write(doc)
    print(f'книга: {OUT} ({len(doc) // 1024} КБ)')
    if '--publish' in sys.argv:
        r = subprocess.run(['bash', '-c', 'ssh -p 22222 -o BatchMode=yes root@89.167.127.0 "mkdir -p /opt/remlab/test/book" && '
                            f'scp -q -P 22222 "{OUT}" root@89.167.127.0:/opt/remlab/test/book/index.html'], timeout=120)
        print('https://remont-lab.online/test/book/' if r.returncode == 0 else 'WARN:book: не выложена')
    return 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else main())
