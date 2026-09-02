#!/usr/bin/env python3
"""Оглавление черновиков запросов — собирается ТАМ, ГДЕ ЛЕЖАТ ПАПКИ.

ЗАЧЕМ ОТДЕЛЬНЫМ ФАЙЛОМ. Страницу `/test/share/src/` строил DEV-рендер по СВОЕМУ списку папок и
клал её на прод поверх прод-овой. Но генерации идут на двух машинах: черновики — на DEV, а
фоновая платная генерация («улучшить фото») выполняется прод-сервисом и пишет папку по id
задания. Такая папка есть только на проде — и после первой же выкладки оглавления с DEV
пропадала из списка: 02.09 владелец не нашёл на странице свою оплаченную генерацию
`3ee913830c`, хотя файлы лежали на месте. Список обязан считаться на той машине, чей каталог
он описывает.

ЗАПУСК: `python3 src_index.py [каталог]` (по умолчанию `/opt/remlab/test/share/src`).
Пишет `index.html` рядом с папками. Зависимостей нет — только стандартная библиотека.
"""
import hashlib
import html
import os
import sys
import time

STYLES = (('INDUSTRIAL LOFT', 'лофт'), ('SOFT MINIMALIST', 'минимализм'),
          ('NEOCLASSICAL', 'неоклассика'), ('CONTEMPORARY', 'современный'))
SHEET = '1-ОТПРАВЛЯЕМ-лист-двух-видов.jpg'


def build(src_dir: str) -> str:
    rows = []
    # СОРТИРОВКА ПО ВРЕМЕНИ, А НЕ ПО ИМЕНИ. Имена — это ЧЧММСС без даты, поэтому по алфавиту
    # вчерашняя папка «improve-213430» встаёт выше сегодняшней «improve-084057», и свежая
    # генерация прячется в середине списка — ровно там, где владелец её ищет первой.
    names = [n for n in os.listdir(src_dir) if os.path.isdir(os.path.join(src_dir, n))]
    names.sort(key=lambda n: os.path.getmtime(os.path.join(src_dir, n)), reverse=True)
    for name in names:
        d = os.path.join(src_dir, name)
        # стиль берём из САМОГО промпта: в нём он не «заявлен», а фактически отправлен
        style = ''
        try:
            txt = open(os.path.join(d, 'prompt.txt'), encoding='utf-8').read()
            style = next((ru for k, ru in STYLES if k in txt), '')
        except OSError:
            pass
        sig = ''
        sheet = os.path.join(d, SHEET)
        if os.path.exists(sheet):
            sig = hashlib.md5(open(sheet, 'rb').read()).hexdigest()[:8]   # noqa: S324
        ts = time.strftime('%d.%m %H:%M', time.localtime(os.path.getmtime(d)))
        rows.append(f'<tr><td><a href="{html.escape(name)}/">{html.escape(name)}</a></td>'
                    f'<td>{style or "—"}</td><td><code>{sig or "—"}</code></td>'
                    f'<td>{ts}</td></tr>')
    return ('<!doctype html><meta charset=utf-8><title>Черновики запросов</title>'
            '<style>body{font:15px system-ui;padding:24px;max-width:820px;margin:0 auto}'
            'table{border-collapse:collapse;width:100%}td,th{padding:8px 10px;'
            'border-bottom:1px solid #e7e5e4;text-align:left}a{color:#9a5a3d}</style>'
            '<h1>Черновики запросов к модели</h1>'
            '<p>Что именно ушло в модель: склеенный лист двух ракурсов, лист эталонов '
            'товаров и полный текст промпта. Служебная страница, покупателю не показывается.</p>'
            '<p>Колонка «сцена» — отпечаток отправленного листа. Одинаковый отпечаток у '
            'разных стилей означал бы, что в модель ушла одна и та же сцена.</p>'
            '<table><tr><th>папка</th><th>стиль</th><th>сцена</th><th>когда</th></tr>'
            + ''.join(rows) + '</table>')


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else '/opt/remlab/test/share/src'
    if not os.path.isdir(src):
        print(f'нет каталога {src}')
        return 1
    out = os.path.join(src, 'index.html')
    open(out, 'w', encoding='utf-8').write(build(src))
    n = sum(1 for x in os.listdir(src) if os.path.isdir(os.path.join(src, x)))
    print(f'оглавление собрано: {n} папок → {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
