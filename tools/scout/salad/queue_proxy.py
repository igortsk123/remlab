# ПОСРЕДНИК МЕЖДУ ВОРКЕРОМ ОЧЕРЕДИ SALAD И ГЕНЕРАЦИЕЙ (план mesh-18 этап 2, T-20261024-05) — работает внутри контейнера.
#
# ЗАЧЕМ. Задание очереди не говорит, какая машина его сделала (канарейка 24.10: строка журнала без `instance` → учёт пула
# `pool_ledger` записал работавшую машину в «раздатчик не видел»). Salad кладёт в окружение контейнера SALAD_INSTANCE_ID и
# SALAD_MACHINE_ID (docs «Environment Variables»); образ не пересобираем — посредник дописывает их в ответ генерации полем
# `_salad`, сборщик (`queue_run.account`) пишет их в журнал как у SSH (`instance`, `machine`).
#
# КАК. Слушает PX_PORT (8001 — `queue_connection` группы), тело задания передаёт на GEN (127.0.0.1:8000/generate) и
# возвращает ответ с тем же HTTP-кодом: 503 «прогрев», 409 «уже считается», 400 — Salad должен видеть их как раньше.
# Ответ не JSON-объект — отдаём как есть. Генерация не ответила — 502 с причиной (Salad повторит попытку).
#
# Код уходит в `command` группы отдельным элементом (`queue_setup.proxy_code`: строки-комментарии и пустые вырезаются,
# лимит 1000 знаков), обёртка `queue_entry.sh` запускает его `python -c "$1"` после прогрева генерации.
# Компактно (1 пробел отступа, `;`) — ради лимита Salad 1000 знаков на элемент command; поведение — как описано выше.
import http.server as h,urllib.request as u,urllib.error as e,json,os
N={'instance_id':os.environ.get('SALAD_INSTANCE_ID'),'machine_id':os.environ.get('SALAD_MACHINE_ID')}
G=os.environ.get('GEN','http://127.0.0.1:8000/generate')
class H(h.BaseHTTPRequestHandler):
 def do_POST(s):
  b=s.rfile.read(int(s.headers.get('Content-Length') or 0))
  try:r=u.urlopen(u.Request(G,b,{'Content-Type':'application/json'}),timeout=3600);c,d=r.status,r.read()
  except e.HTTPError as x:c,d=x.code,x.read()
  except Exception as x:c,d=502,json.dumps({'error':f'proxy: {x}'}).encode()
  try:
   j=json.loads(d)
   if isinstance(j,dict):j['_salad']=N;d=json.dumps(j).encode()
  except ValueError:pass
  s.send_response(c);s.send_header('Content-Type','application/json');s.send_header('Content-Length',str(len(d)));s.end_headers();s.wfile.write(d)
 def log_message(s,*a):pass
h.ThreadingHTTPServer(('',int(os.environ.get('PX_PORT',8001))),H).serve_forever()
