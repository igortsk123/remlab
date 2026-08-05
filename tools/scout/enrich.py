#!/usr/bin/env python3
"""Каскад обогащения: правила → дешёвая текстовая модель → (при нужде) картинка → эскалация.

Порядок продиктован деньгами и качеством:
  0. Правила (`rules0.py`) — бесплатно; цвет, материал, форма, размеры, флаги трудности.
  1. `gpt-5.6-luna` по тексту — суждение: роль, функция, стиль, визуальная масса (выбрана по
     числам на золотой выборке, [[golden-sample]]: роль 92.6%, функция 89.8%).
  2. Картинка — только карточкам без описания И с общим названием. Замер: таких 36 из 26 147
     (0.1%), поэтому уровень 2 включаем точечно, а не пакетом.
  3. Эскалация на `gpt-5.6-terra` — позициям с низким системным качеством.

Качество считает СИСТЕМА, а не модель о себе: сходится ли роль с правилами, полны ли размеры,
согласны ли цвет и материал, есть ли флаги. Вербализованная уверенность модели завышена всегда.

Дельта: товар, у которого не менялись текст и размеры, а обогащение сделано теми же версиями,
пропускается — за него уже заплачено (ADR-0068).

  ~/venvs/scout/bin/python enrich.py --sample 200        # синхронно, с записью в БД
  ~/venvs/scout/bin/python enrich.py --pool --batch      # весь пул пакетом (−50%)
  ~/venvs/scout/bin/python enrich.py --fetch <batch_id>  # забрать результат пакета
  ~/venvs/scout/bin/python enrich.py --stats             # что уже обогащено
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from golden_label import SCHEMA, SYS, prompt, _key  # noqa: E402
from rules0 import extract, flags, pool  # noqa: E402

MODEL = 'gpt-5.6-luna'
MODEL_STRONG = 'gpt-5.6-terra'    # уровень 3: только спорным, и только если сильной модели есть
                                  # с чем работать — размеры она восстановить не может
ENRICH_VERSION = 'furniture-v1'
PROMPT_VERSION = 'p3'
SCHEMA_VERSION = 's2'
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
API = 'https://api.openai.com/v1'


def sql(q: str, inp: str | None = None) -> str:
    r = subprocess.run(PSQL, input=inp if inp is not None else q, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[:500])
        sys.exit(1)
    return r.stdout


# Родственные роли: расхождение внутри семьи — не ошибка, а уточнение. Категория магазина зовёт
# «люстрой» и потолочный светильник, и бра; модель разбирает их точнее нас, и штрафовать её за это
# значит гнать в эскалацию половину светильников (замер 2026-08-05: было 37% эскалаций).
FAMILIES = [{'лампа', 'люстра', 'бра', 'торшер'}, {'стеллаж', 'полка', 'витрина', 'стенка'},
            {'комод', 'тв-тумба', 'шкаф'}, {'столик', 'стол обеденный'}, {'пуф', 'кресло'},
            {'плед', 'подушка'}, {'ваза', 'кашпо', 'статуэтка', 'растение'}]


def _same_family(a: str, b: str) -> bool:
    return any(a in f and b in f for f in FAMILIES)


def quality(r0: dict, m: dict) -> float:
    """Системная оценка: сходится ли сказанное моделью с тем, что видно в тексте."""
    q = 0.35
    role_m, role_f = m.get('role'), r0.get('role_feed')
    if role_m == role_f:
        q += 0.30                       # модель согласна с категорией магазина
    elif _same_family(role_m or '', role_f or ''):
        q += 0.22                       # уточнение внутри семьи светильников или хранения
    elif role_m == 'другое':
        q += 0.05                       # честное «не для гостиной» — не ошибка
    if r0['dims_quality'] == 'полные':
        q += 0.15
    elif r0['dims_quality'] == 'частичные':
        q += 0.05
    if r0.get('primary_color') and m.get('primary_color') == r0['primary_color']:
        q += 0.10
    if r0.get('materials') and set(m.get('materials') or []) & set(r0['materials']):
        q += 0.10
    if r0.get('has_desc'):
        q += 0.05
    if not r0.get('dims_sane'):
        q -= 0.30                       # мусорные размеры отравляют подбор сильнее всего
    if m.get('functional_subtype') == 'не_определён':
        q -= 0.10
    return max(0.0, min(1.0, round(q, 2)))


def body_for(it: dict, model: str = MODEL, vision: bool = False) -> dict:
    # Уровень 2 включается ПО ПОЛЮ, а не по «нет описания». Замер 2026-08-05: роль и функция по
    # тексту надёжны (88% и 91% совпадения с разметкой по фото), а главный стиль меняется у 47%
    # товаров, когда модель видит вещь; на декоре — у 60-80%. Значит стиль, материал и цвет
    # считаем по фотографии, роль и функцию оставляем тексту (вопрос владельца «это реально?»).
    content = prompt(it)
    if vision and it.get('img'):
        url = it['img']
        url = 'https:' + url if url.startswith('//') else url
        content = [{'type': 'text', 'text': content},
                   {'type': 'image_url', 'image_url': {'url': url, 'detail': 'low'}}]
    return {
        'model': model,
        'messages': [{'role': 'system', 'content': SYS},
                     {'role': 'user', 'content': content}],
        'response_format': {'type': 'json_schema',
                            'json_schema': {'name': 'furniture', 'strict': True, 'schema': SCHEMA}},
        'reasoning_effort': 'low',
    }


# p2 остаётся годной там, где промпт p3 ничего не поменял: разница между ними одна — p3 не шлёт
# негодное описание. Если описания не было или оно было годным, ответ p2 идентичен p3, и платить
# за перегон незачем (2026-08-05).
ACCEPT_PROMPTS = ("'p2'", "'p3'")


def todo(items: list[dict]) -> list[dict]:
    """Кому обогащение реально нужно: новым и тем, у кого поменялся смысл или версия."""
    rows = sql(f"""select shop_mid, external_id from product_enrichment
                 where payload is not null and enrichment_version='{ENRICH_VERSION}'
                   and prompt_version in ({','.join(ACCEPT_PROMPTS)})
                   and schema_version='{SCHEMA_VERSION}'""")
    done = {tuple(l.split('\x1f')) for l in rows.strip().split('\n') if l}
    out = [it for it in items if (str(it['mid']), it['eid']) not in done]
    if len(out) < len(items):
        print(f'пропускаю {len(items) - len(out)} — уже обогащены этой версией')
    return out


VISION_FIELDS = ('styles', 'style_strength', 'materials', 'primary_color', 'shape',
                 'visual_mass', 'warmth', 'decorativeness', 'base_type')


def save(rows: list[tuple[dict, dict, dict]], model: str = MODEL, vision: bool = False) -> None:
    """Запись обогащения одной пачкой: payload + качество + версии.

    В режиме с картинкой ответ НЕ затирает текстовый: роль и функцию оставляем от текста (они
    надёжнее и дешевле), а внешние признаки берём от фотографии. Обе версии остаются в payload,
    чтобы было видно, чем именно они разошлись.
    """
    if not rows:
        return
    old = {}
    if vision:
        keys = ','.join(f"({it['mid']},'{it['eid']}')" for it, _, _ in rows)
        for line in sql(f"""select shop_mid, external_id, payload->'model'
                            from product_enrichment
                           where (shop_mid, external_id) in ({keys})""").strip().split('\n'):
            f = line.split('\x1f')
            if len(f) >= 3 and f[2]:
                old[f'{f[0]}:{f[1]}'] = json.loads(f[2])
    vals = []
    for it, r0, m in rows:
        if vision:
            base = dict(old.get(f'{it["mid"]}:{it["eid"]}') or m)
            merged = dict(base)
            for fld in VISION_FIELDS:
                if fld in m:
                    merged[fld] = m[fld]
            payload = json.dumps({'rules': r0, 'model': merged, 'model_text': base,
                                  'model_vision': m, 'flags': flags(r0)}, ensure_ascii=False)
            m = merged
        else:
            payload = json.dumps({'rules': r0, 'model': m, 'flags': flags(r0)}, ensure_ascii=False)
        payload = payload.replace("'", "''")
        vals.append(f"({it['mid']},'{it['eid']}','{payload}'::jsonb,{quality(r0, m)})")
    sql(f"""
      update product_enrichment e set payload=v.payload, quality=v.q,
             enrichment_version='{ENRICH_VERSION}', model_name='{model}',
             prompt_version='{PROMPT_VERSION}', schema_version='{SCHEMA_VERSION}',
             enriched_at=now(), updated_at=now()
        from (values {','.join(vals)}) as v(mid, eid, payload, q)
       where e.shop_mid=v.mid and e.external_id=v.eid;
    """)


def ask(it: dict, key: str, model: str = MODEL, vision: bool = False) -> dict | None:
    req = urllib.request.Request(f'{API}/chat/completions',
                                 data=json.dumps(body_for(it, model, vision)).encode(),
                                 headers={'Authorization': f'Bearer {key}',
                                          'Content-Type': 'application/json'})
    for attempt in range(3):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=180))
            msg = r['choices'][0]['message']
            if msg.get('refusal'):
                return None
            return json.loads(msg['content'])
        except Exception:  # noqa: BLE001 — 429/5xx: подождать и повторить
            if attempt == 2:
                return None
            time.sleep(2 + 3 * attempt)
    return None


def run_sync(items: list[dict], model: str = MODEL) -> None:
    key = _key()
    got: list[tuple[dict, dict, dict]] = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(8) as ex:
        vision = '--vision' in sys.argv
        futs = {ex.submit(ask, it, key, model, vision): it for it in items}
        for i, f in enumerate(cf.as_completed(futs), 1):
            it = futs[f]
            m = f.result()
            if m:
                got.append((it, extract(it), m))
            if i % 50 == 0:
                print(f'  {i}/{len(items)}', flush=True)
    save(got, model, '--vision' in sys.argv)
    qs = [quality(r0, m) for _, r0, m in got]
    low = sum(1 for q in qs if q < 0.65)
    print(f'обогащено {len(got)}/{len(items)} за {time.time() - t0:.0f} с; '
          f'среднее качество {sum(qs) / max(len(qs), 1):.2f}; '
          f'на эскалацию (<0.65): {low} ({low / max(len(qs), 1) * 100:.0f}%)')


CHUNK = 7000     # ~50 МБ на файл при лимите 200 МБ и 50 000 запросов


def _submit(lines: list[str], key: str, tag: str) -> str:
    path = os.path.join(HERE, f'enrich-batch-{tag}.jsonl')
    open(path, 'w').write('\n'.join(lines))
    size = os.path.getsize(path) / 1e6
    # multipart вручную: тянуть requests ради одной загрузки незачем
    boundary = '----remlabbatch'
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nbatch\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="enrich-batch-{tag}.jsonl"\r\nContent-Type: application/jsonl\r\n\r\n').encode()
    body += open(path, 'rb').read() + f'\r\n--{boundary}--\r\n'.encode()
    up = json.load(urllib.request.urlopen(urllib.request.Request(
        f'{API}/files', data=body,
        headers={'Authorization': f'Bearer {key}',
                 'Content-Type': f'multipart/form-data; boundary={boundary}'}), timeout=600))
    b = json.load(urllib.request.urlopen(urllib.request.Request(
        f'{API}/batches', data=json.dumps({'input_file_id': up['id'],
                                           'endpoint': '/v1/chat/completions',
                                           'completion_window': '24h'}).encode(),
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}),
        timeout=120))
    print(f'  часть {tag}: {len(lines)} запросов, {size:.0f} МБ → {b["id"]} ({b["status"]})')
    return b['id']


def run_batch(items: list[dict]) -> None:
    """Пакетом: вдвое дешевле, окно до 24 часов, результат забираем командой --fetch.

    Режем на части по 7 000 запросов: один файл каталога целиком упирается в лимит 200 МБ
    (схема с перечислениями повторяется в каждой строке).
    """
    key = _key()
    vision = '--vision' in sys.argv
    lines = [json.dumps({'custom_id': f'{it["mid"]}:{it["eid"]}', 'method': 'POST',
                         'url': '/v1/chat/completions', 'body': body_for(it, MODEL, vision)},
                        ensure_ascii=False) for it in items]
    ids = []
    for i in range(0, len(lines), CHUNK):
        ids.append(_submit(lines[i:i + CHUNK], key, str(i // CHUNK + 1)))
    open(os.path.join(HERE, 'enrich-batch-id.txt'), 'w').write('\n'.join(ids))
    print(f'отправлено частей: {len(ids)}. Забрать: --fetch (id читаются из enrich-batch-id.txt)')


def fetch(batch_id: str, items: dict | None = None) -> None:
    key = _key()
    b = json.load(urllib.request.urlopen(urllib.request.Request(
        f'{API}/batches/{batch_id}', headers={'Authorization': f'Bearer {key}'}), timeout=120))
    print(f'{batch_id}: статус {b["status"]}, готово {b["request_counts"]["completed"]}'
          f'/{b["request_counts"]["total"]}, ошибок {b["request_counts"]["failed"]}')
    if b['status'] != 'completed':
        return
    out = urllib.request.urlopen(urllib.request.Request(
        f'{API}/files/{b["output_file_id"]}/content',
        headers={'Authorization': f'Bearer {key}'}), timeout=900).read().decode()
    items = items or {f'{it["mid"]}:{it["eid"]}': it for it in pool()}
    got = []
    for line in out.strip().split('\n'):
        r = json.loads(line)
        it = items.get(r['custom_id'])
        if not it or r.get('error'):
            continue
        msg = r['response']['body']['choices'][0]['message']
        if msg.get('refusal'):
            continue
        try:
            got.append((it, extract(it), json.loads(msg['content'])))
        except json.JSONDecodeError:
            continue
        if len(got) >= 2000:
            save(got)
            got = []
    save(got)
    print('результат записан в product_enrichment')
    stats()


def stats() -> None:
    print(sql("""select 'обогащено: '||count(*) filter (where payload is not null)
                     ||' из '||count(*)||'; среднее качество '
                     ||coalesce(round(avg(quality)::numeric,2)::text,'—')
                     ||'; ниже 0.65: '||count(*) filter (where quality<0.65)
                 from product_enrichment e
                 join lr_roles l using (shop_mid, external_id) where l.role is not null;""").strip())


def main() -> None:
    a = sys.argv
    if '--stats' in a:
        stats()
    elif '--fetch' in a:
        i = a.index('--fetch')
        ids = ([a[i + 1]] if len(a) > i + 1 and a[i + 1].startswith('batch_')
               else open(os.path.join(HERE, 'enrich-batch-id.txt')).read().split())
        cache = {f'{it["mid"]}:{it["eid"]}': it for it in pool()}   # один разбор пула на все части
        for bid in ids:
            fetch(bid, cache)
    elif '--pool' in a:
        items = todo(pool())
        print(f'к обогащению: {len(items)}')
        if not items:
            return
        run_batch(items) if '--batch' in a else run_sync(items)
    elif '--redo-desc' in a:
        # Перегон карточек, где в промпт уходил негодный текст (шаблон магазина, инструкция,
        # обрывок). Замер на 150 таких карточек: подтип меняется у 9%, роль у 2%, стиль на две
        # ступени у 5%. Подтип задаёт жёсткие правила размеров, поэтому перегон оправдан
        # (замечание владельца, 2026-08-05).
        from desc_quality import classify as _dc
        items = [it for it in pool() if _dc(it.get('desc')) in ('duplicate', 'boilerplate', 'short')]
        print(f'перегон по негодным описаниям: {len(items)}')
        if items:
            run_batch(items) if '--batch' in a else run_sync(items)
    elif '--escalate' in a:
        # Уровень 3 только тем, кому сильная модель реально поможет: текст есть, размеры полные,
        # а роль или подтип спорны. Позициям с дырами в размерах эскалация бесполезна — модель
        # не восстанавливает сантиметры (замер 2026-08-05: из 2 284 слабых таких 2 143).
        ids = sql("""select shop_mid, external_id from product_enrichment
                     where quality<0.65 and payload is not null
                       and payload->'rules'->>'has_desc'='true'
                       and payload->'rules'->>'dims_quality'='полные'""")
        keys = {tuple(l.split('\x1f')) for l in ids.strip().split('\n') if l}
        items = [it for it in pool() if (str(it['mid']), it['eid']) in keys]
        print(f'на эскалацию: {len(items)} товаров, модель {MODEL_STRONG}')
        if items:
            run_sync(items, MODEL_STRONG)
    elif '--sample' in a:
        n = int(a[a.index('--sample') + 1])
        all_items = todo(pool())
        # РОВНЫМ шагом по всему пулу, а не первые N: пул отсортирован по магазину, и «первые 60»
        # оказались светильниками одного магазина — замер по ним ничего не говорит о каталоге
        step = max(len(all_items) // max(n, 1), 1)
        items = all_items[::step][:n]
        print(f'к обогащению: {len(items)} (ровным шагом по пулу из {len(all_items)})')
        run_sync(items)
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
