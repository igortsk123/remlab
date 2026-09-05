#!/usr/bin/env python3
"""Мост DEV ↔ /lab/mesh-audit (ручная приёмка мешей владельцем): минутный тик.

Что делает один тик (под `flock`, лёгкий — заливка партии живёт в ОТДЕЛЬНОМ процессе):
  1. pull — решения владельца курсором `after_id`. Каждое применяется ОДНОЙ транзакцией на DEV:
     ledger (`mesh_rework_requests.prod_decision_id` unique) → вердикт поколению → ревизия в
     `owner_reject`/`replace_needed` только при CAS «текущее поколение = отвергнутое» → отвязка
     от карточки товара (меш выходит из сетов сразу) → sidecar `owner_reject.json` для старых
     читателей. Курсор двигается ТОЛЬКО после успешной транзакции; неизвестное поколение —
     повтор, а через полчаса — `blocked` с текстом, но не молчаливый пропуск.
  2. push — текущие поколения (одна карточка на товар) и ACK статусов переделок
     (`applied → queued → done | blocked`). Отправляется только то, что изменилось с прошлого тика.
  3. партии — запрошенную партию отдаём публикатору (свой процесс, свой замок); отслужившую
     он же удаляет после grace (`--cleanup`).

Секреты: MESH_REVIEW_MACHINE_TOKEN / MESH_REVIEW_URL из окружения или ~/.config/remlab/env
(как у mesh_review_sync.py; значения — только в _secrets/ACCESS.md и на сервере).

  ~/venvs/scout/bin/python mesh_audit_sync.py --tick     # крон раз в минуту под flock
  ~/venvs/scout/bin/python mesh_audit_sync.py --push     # только список
  ~/venvs/scout/bin/python mesh_audit_sync.py --pull     # только решения
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
STATE_DIR = os.path.expanduser('~/scout-scenes/mesh-audit')
CURSOR = os.path.join(STATE_DIR, 'decisions.cursor')
PUSH_STATE = os.path.join(STATE_DIR, 'push-state.json')
STUCK = os.path.join(STATE_DIR, 'decision-stuck.json')
POSTERS = os.path.join(STATE_DIR, 'posters')
STUCK_S = 1800
PIPELINE_VERSION = os.environ.get('PIPELINE_VERSION', 'v1')

from mesh_queue import db, q  # noqa: E402


# ---------------------------------------------------------------- прод API

def _env() -> tuple[str, str]:
    cfg = os.path.expanduser('~/.config/remlab/env')
    if os.path.exists(cfg):
        for ln in open(cfg):
            if '=' in ln and not ln.strip().startswith('#'):
                k, v = ln.strip().split('=', 1)
                os.environ.setdefault(k, v)
    url = os.environ.get('MESH_REVIEW_URL', 'https://remont-lab.online')
    tok = os.environ.get('MESH_REVIEW_MACHINE_TOKEN', '')
    if not tok:
        raise SystemExit('нет MESH_REVIEW_MACHINE_TOKEN (см. _secrets/ACCESS.md)')
    return url.rstrip('/'), tok


def api(method: str, path: str, body: dict | None = None) -> dict:
    url, tok = _env()
    req = urllib.request.Request(url + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def _atomic_write(path: str, text: str) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_json(path: str, default):
    try:
        return json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- pull: решения владельца

def apply_decision(d: dict) -> str:
    """Применить решение одной транзакцией. Возвращает статус для ACK: applied | blocked.
    Бросает, если поколение неизвестно — вызывающий решает, ждать или блокировать."""
    gk, sku, verdict, did = d['generationKey'], d['sku'], d['verdict'], int(d['id'])
    rows = db(f"select path, source_sha from mesh_generations where generation_key={q(gk)}")
    if not rows or len(rows[0]) != 2:
        raise LookupError(f'поколение {gk} неизвестно на DEV')
    path, sha16 = rows[0]
    rk = f'{sku}|{sha16}|{PIPELINE_VERSION}'
    rev_status = 'owner_reject' if verdict == 'redo' else 'replace_needed'
    sql = ['begin;']
    if verdict == 'redo':
        sql.append(f"insert into mesh_rework_requests (prod_decision_id, sku, source_sha, pipeline_version, "
                   f"rejected_generation_key, manual_attempt_no) values ({did}, {q(sku)}, {q(sha16)}, "
                   f"{q(PIPELINE_VERSION)}, {q(gk)}, {int(d['manualAttemptNo'])}) "
                   f"on conflict (prod_decision_id) do nothing;")
    sql.append(f"update mesh_generations set owner_verdict={q(verdict)}, owner_decision_id={did}, "
               f"owner_verdict_at=now(), updated=now() where generation_key={q(gk)} "
               f"and (owner_verdict is null or owner_decision_id={did});")
    sql.append(f"update asset_revisions set status={q(rev_status)}, rejected_reason='owner', updated=now() "
               f"where revision_key={q(rk)} and current_generation_key={q(gk)};")
    sql.append(f"update products set mesh_uri=null, mesh_at=null, mesh_revision_key=null, "
               f"mesh_generation_key=null, mesh_status='rejected' "
               f"where shop_mid||':'||external_id={q(sku)} "
               f"and (mesh_generation_key={q(gk)} or mesh_generation_key is null);")
    sql.append('commit;')
    db('\n'.join(sql))
    try:      # sidecar для gallery_build/topview_render — атомарно, маленький файл, без удалений
        _atomic_write(os.path.join(path, 'owner_reject.json'),
                      json.dumps({'decision_id': did, 'verdict': verdict, 'at': time.strftime('%Y-%m-%dT%H:%M:%S')}))
    except OSError as e:
        print(f'  sidecar не записан для {gk}: {e}', flush=True)
    return 'applied'


def pull() -> int:
    after = _cursor()
    r = api('GET', f'/api/lab/mesh-audit/decisions?after_id={after}')
    n, acks = 0, []
    stuck = _load_json(STUCK, {})
    for d in r.get('decisions', []):
        try:
            st = apply_decision(d)
        except LookupError as e:
            key = str(d['id'])
            first = stuck.setdefault(key, time.time())
            _atomic_write(STUCK, json.dumps(stuck))
            if time.time() - first < STUCK_S:
                print(f'  решение {key}: {e} — жду (повторю следующим тиком)', flush=True)
                break                    # курсор не двигаем: следующие решения подождут
            st = 'blocked'
            acks.append({'sku': d['sku'], 'reworkStatus': 'blocked', 'error': str(e)[:160]})
            print(f'  решение {key}: {e} — полчаса без поколения, blocked', flush=True)
        else:
            acks.append({'sku': d['sku'], 'reworkStatus': st})
        _atomic_write(CURSOR, str(d['id']))     # курсор — после применения
        stuck.pop(str(d['id']), None)
        n += 1
    if acks:
        api('POST', '/api/lab/mesh-audit/items', {'acks': acks})
    if n:
        print(f'[audit] применено решений: {n}', flush=True)
    return n


def _cursor() -> int:
    try:
        return int(open(CURSOR).read().strip() or 0)
    except (OSError, ValueError):
        return 0


# ---------------------------------------------------------------- push: карточки и ACK

def current_items() -> list[dict]:
    """Одна карточка на товар: текущее поколение + карточка товара + свежесть фото + постер.

    Роли, которым меш не положен по канону (`rules/asset-strategies.json`: ковры, пледы, шторы…
    идут вклейкой), на страницу НЕ попадают — даже если пилотный меш лежит на диске (владелец
    05.09: «ковры не показывай»). Их sku уходят в `retire`, и прод удаляет карточки."""
    import asset_strategy as AS
    from mesh_audit_posters import poster_name
    rows = db("""
      with cur as (
        select distinct on (g.sku) g.sku, g.generation_key, g.source_sha, g.seed, g.generated_at, g.glb_sha
          from mesh_generations g order by g.sku, g.generated_at desc, g.generation_key desc),
      att as (select sku, count(*) as n, min(generated_at) as first_at from mesh_generations group by sku)
      select c.sku, c.generation_key, c.source_sha, c.seed, to_char(c.generated_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
             att.n, to_char(att.first_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
             coalesce(p.cat_role,''), regexp_replace(coalesce(p.name,''), E'[\\n\\r\\x1f]', ' ', 'g'),
             coalesce(p.image_url_hd, p.image_url, ''),
             case when pc.source_sha is null then 'unknown'
                  when pc.source_sha like c.source_sha||'%' then 'fresh' else 'stale' end
        from cur c
        join att on att.sku = c.sku
        left join products p on p.shop_mid||':'||p.external_id = c.sku
        left join product_photo_current pc on pc.sku = c.sku
       order by att.first_at, c.sku""")
    out = []
    for r in rows:
        if len(r) != 11:
            continue
        sku, gk, sha16, seed, gen_at, n, _first, role, name, img, fresh = r
        if AS.strategy(role or None) != 'hunyuan3d':
            continue
        poster = poster_name(gk)
        item = {'sku': sku, 'generationKey': gk, 'revisionKey': f'{sku}|{sha16}|{PIPELINE_VERSION}',
                'role': role or None, 'name': name or None, 'imageUrl': img or None,
                'posterUrl': f'/test/mesh-audit/posters/{poster}' if os.path.exists(os.path.join(POSTERS, poster)) else None,
                'modelPath': f'{sku.replace(":", "_", 1)}/model.glb',
                'seed': int(seed), 'attempt': int(n), 'generatedAt': gen_at, 'photoStale': fresh == 'stale'}
        # Zod на проде: `optional()` принимает отсутствие ключа, но не null — пустое не отправляем
        out.append({k: v for k, v in item.items() if v is not None})
    return out


def rework_acks() -> list[dict]:
    """Переход queued → done: поколение с зарезервированным seed появилось на диске."""
    db("""update mesh_rework_requests r set status='done', updated=now()
           where r.status in ('queued','requested') and r.next_seed is not null
             and exists (select 1 from mesh_generations g where g.sku=r.sku and g.seed=r.next_seed)""")
    return [{'sku': r[0], 'reworkStatus': r[1], **({'error': r[2]} if r[2] else {})}
            for r in db("select sku, status, coalesce(error,'') from mesh_rework_requests "
                        "where status in ('queued','done','blocked')") if len(r) == 3]


def push() -> int:
    state = _load_json(PUSH_STATE, {'items': {}, 'acks': {}})
    items = current_items()
    changed = [it for it in items if state['items'].get(it['sku']) != json.dumps(it, sort_keys=True, ensure_ascii=False)]
    acks = [a for a in rework_acks() if state['acks'].get(a['sku']) != a['reworkStatus']]
    # Карточки, которые раньше отправляли, а теперь не показываем (роль без меша, товар исчез)
    retire = sorted(set(state['items']) - {it['sku'] for it in items})
    if retire:
        r = api('POST', '/api/lab/mesh-audit/items', {'retire': retire})
        # Забываем sku только когда прод ПОДТВЕРДИЛ, что умеет retire (ключ в ответе): старая
        # версия ручки молча отбрасывает неизвестное поле, и карточки остались бы навсегда.
        if 'retired' in r:
            for sku in retire:
                state['items'].pop(sku, None)
            _atomic_write(PUSH_STATE, json.dumps(state, ensure_ascii=False))
            print(f'[audit] снято карточек: {r["retired"]} из {len(retire)} (роль без меша / товара нет)', flush=True)
    sent = 0
    for i in range(0, len(changed), 300):
        chunk = changed[i:i + 300]
        api('POST', '/api/lab/mesh-audit/items', {'items': chunk})
        for it in chunk:
            state['items'][it['sku']] = json.dumps(it, sort_keys=True, ensure_ascii=False)
        sent += len(chunk)
        _atomic_write(PUSH_STATE, json.dumps(state, ensure_ascii=False))
    if acks:
        api('POST', '/api/lab/mesh-audit/items', {'acks': acks})
        for a in acks:
            state['acks'][a['sku']] = a['reworkStatus']
        _atomic_write(PUSH_STATE, json.dumps(state, ensure_ascii=False))
    if sent or acks:
        print(f'[audit] отправлено карточек: {sent} (всего {len(items)}), ACK переделок: {len(acks)}', flush=True)
    return sent


# ---------------------------------------------------------------- партии

def serve_batches() -> None:
    st = api('GET', '/api/lab/mesh-audit/batch')
    pend = st.get('pending')
    py = sys.executable
    pub = os.path.join(HERE, 'mesh_audit_publish.py')
    if pend and pend.get('status') == 'requested':
        # публикатор — отдельный процесс со своим замком; тик его не ждёт
        subprocess.Popen([py, pub, '--token', pend['token'], '--batch', str(pend['batch'])],
                         stdout=open(os.path.join(STATE_DIR, 'publish.log'), 'a'), stderr=subprocess.STDOUT,
                         start_new_session=True)
        print(f'[audit] партия {pend["batch"]} отдана публикатору ({pend["token"]})', flush=True)
    if st.get('retiring'):
        subprocess.run([py, pub, '--cleanup'], capture_output=True, text=True, timeout=600)


def publish_posters() -> None:
    """Инкрементальный rsync постеров (секунда-две, когда нового нет): карточка получает
    `posterUrl`, как только файл есть локально, — на проде он должен появиться тем же тиком."""
    if not os.path.isdir(POSTERS):
        return
    r = subprocess.run(['rsync', '-aq', '-e', 'ssh -p 22222 -o BatchMode=yes -o ConnectTimeout=20',
                        POSTERS + '/', 'root@89.167.127.0:/opt/remlab/test/mesh-audit/posters/'],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print(f'[audit] постеры не синхронизированы: {r.stderr.strip()[-160:]}', flush=True)


def tick() -> None:
    """Шаги независимы: упавший pull (например, 502 во время деплоя прода) не должен отменять
    публикацию постеров и обслуживание партии — каждый шаг ловит своё и жалуется в лог."""
    os.makedirs(STATE_DIR, exist_ok=True)
    for step in (pull, publish_posters, push, serve_batches):
        try:
            step()
        except Exception as e:  # noqa: BLE001 — следующий тик повторит; молчать нельзя
            print(f'[audit] {step.__name__}: {type(e).__name__}: {str(e)[:160]}', flush=True)


if __name__ == '__main__':
    if '--tick' in sys.argv:
        tick()
    elif '--push' in sys.argv:
        os.makedirs(STATE_DIR, exist_ok=True)
        push()
    elif '--pull' in sys.argv:
        os.makedirs(STATE_DIR, exist_ok=True)
        pull()
    else:
        print(__doc__)
