#!/usr/bin/env python3
"""ОТЧЁТ ТЕНИ ПАРСЕРА v2 (план stock-and-dims-honesty, Н0). Сети не трогает.

Сравнивает наблюдения shadow-прогона (парсер v2, disposition='shadow') с ПРИНЯТЫМ состоянием карточек
(product_page_status, парсер v1). Gold-критерии Codex: среди ≥300 прежде живых — НОЛЬ новых негативов;
известные gone/oos пойманы; каждый новый негатив показан для ручной проверки.

  stock_shadow_report.py --run <run_id>            # матрица и список новых негативов
  stock_shadow_report.py --run <run_id> --html f   # то же + страница для владельца
"""
import html
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']


def db(sql: str) -> list:
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip('\n').split('\n') if ln]


def q(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def report(run: str, html_path: str = '') -> int:
    rows = db(f"""
    select coalesce(ps.state,'нет записи'), o.verdict, coalesce(o.evidence_kind,'-'), coalesce(o.failure_kind,'-'),
           p.shop_mid||':'||p.external_id, left(p.name, 70), o.url, coalesce(o.reason,''), coalesce(o.http_code::text,'')
      from product_page_observation o
      join products p on p.shop_mid = o.shop_mid and p.external_id = o.external_id
      left join product_page_status ps on ps.shop_mid = o.shop_mid and ps.external_id = o.external_id
     where o.run_id = {q(run)} and o.disposition = 'shadow';""")
    if not rows:
        print('нет shadow-наблюдений для', run); return 1
    matrix, new_neg, missed = {}, [], []
    for prev, verdict, ev, fk, sku, name, url, reason, code in rows:
        matrix[(prev, verdict)] = matrix.get((prev, verdict), 0) + 1
        if verdict in ('oos', 'gone') and prev not in ('oos', 'gone'):
            new_neg.append((prev, verdict, ev, sku, name, url, reason, code))
        if prev in ('oos', 'gone') and verdict == 'alive':
            missed.append((prev, verdict, ev, sku, name, url, reason, code))
    print(f'тень {run}: наблюдений {len(rows)}')
    print('матрица прежний статус (v1) → вердикт тени (v2):')
    for (prev, v), n in sorted(matrix.items(), key=lambda kv: (kv[0][0], -kv[1])):
        print(f'  {prev:12s} → {v:8s} {n}')
    alive_prev = sum(n for (p_, v), n in matrix.items() if p_ == 'alive')
    fn = sum(n for (p_, v), n in matrix.items() if p_ == 'alive' and v in ('oos', 'gone'))
    unk_prev = sum(n for (p_, v), n in matrix.items() if p_ == 'unknown')
    unk_resolved = sum(n for (p_, v), n in matrix.items() if p_ == 'unknown' and v in ('alive', 'oos', 'gone'))
    neg_prev = sum(n for (p_, v), n in matrix.items() if p_ in ('oos', 'gone'))
    neg_caught = sum(n for (p_, v), n in matrix.items() if p_ in ('oos', 'gone') and v in ('oos', 'gone'))
    print(f'GOLD: прежде живых {alive_prev}, из них тень сняла бы {fn} (нужно 0 при ≥300); '
          f'прежде неизвестных {unk_prev}, распознано {unk_resolved}; известных снятых {neg_prev}, поймано {neg_caught}')
    verdict_ok = alive_prev >= 300 and fn == 0 and (neg_prev == 0 or neg_caught / neg_prev >= 0.9)
    print('ВЕРДИКТ ТЕНИ:', 'gold пройден — можно решать о включении' if verdict_ok else 'НЕ пройден / выборка мала')
    print(f'новых негативов к ручной проверке: {len(new_neg)}' + (' (первые 20 ниже)' if new_neg else ''))
    for prev, v, ev, sku, name, url, reason, code in new_neg[:20]:
        print(f'  {prev:8s}→{v:4s} [{ev}] {sku} {name[:45]} | {url[:70]} | {reason} ({code})')
    if missed:
        print(f'прежде снятые, тень видит живыми: {len(missed)} (проверить руками, воскрешать ли)')
    if html_path:
        rows_html = ''.join(
            f"<tr><td>{html.escape(prev)}</td><td>{html.escape(v)}</td><td>{html.escape(ev)}</td><td>{html.escape(sku)}</td>"
            f"<td>{html.escape(name)}</td><td><a href='{html.escape(url)}' target='_blank' rel='noopener nofollow'>карточка</a></td>"
            f"<td>{html.escape(reason)} ({html.escape(code)})</td></tr>" for prev, v, ev, sku, name, url, reason, code in new_neg + missed)
        mrows = ''.join(f"<tr><td>{html.escape(p_)}</td><td>{html.escape(v)}</td><td>{n}</td></tr>"
                        for (p_, v), n in sorted(matrix.items()))
        open(html_path, 'w', encoding='utf-8').write(
            f"<!doctype html><meta charset=utf-8><title>Тень парсера v2 {html.escape(run)}</title>"
            "<style>body{font:15px system-ui;margin:24px}table{border-collapse:collapse;margin:12px 0}td,th{border:1px solid #ddd;padding:4px 8px}</style>"
            f"<h1>Тень парсера v2 — {html.escape(run)}</h1><p>Наблюдений {len(rows)}. Прежде живых {alive_prev}, тень сняла бы {fn}. "
            f"Неизвестных {unk_prev}, распознано {unk_resolved}. Снятых {neg_prev}, поймано {neg_caught}. Вердикт: "
            f"<b>{'gold пройден' if verdict_ok else 'не пройден'}</b></p>"
            f"<h2>Матрица</h2><table><tr><th>было (v1)</th><th>тень (v2)</th><th>n</th></tr>{mrows}</table>"
            f"<h2>К ручной проверке: новые негативы ({len(new_neg)}) и «снятые, но живые» ({len(missed)})</h2>"
            f"<table><tr><th>было</th><th>тень</th><th>свидетельство</th><th>SKU</th><th>товар</th><th>ссылка</th><th>причина</th></tr>{rows_html}</table>")
        print('html:', html_path)
    return 0 if verdict_ok else 3


if __name__ == '__main__':
    run = sys.argv[sys.argv.index('--run') + 1] if '--run' in sys.argv else ''
    out = sys.argv[sys.argv.index('--html') + 1] if '--html' in sys.argv else ''
    if not run:
        r = db("select run_id from product_page_observation where disposition='shadow' order by observed_at desc limit 1")
        run = r[0][0] if r else ''
    sys.exit(report(run, out) if run else 1)
