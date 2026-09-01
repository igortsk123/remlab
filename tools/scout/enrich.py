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
from golden_label import SCHEMA, SYS, prompt, schema_for, _key, _image_b64  # noqa: E402
from rules0 import extract, flags, pool  # noqa: E402

MODEL = 'gpt-5.6-luna'
MODEL_STRONG = 'gpt-5.6-terra'    # уровень 3: только спорным, и только если сильной модели есть
                                  # с чем работать — размеры она восстановить не может
ENRICH_VERSION = 'furniture-v1'
PROMPT_VERSION = 'p3'
SCHEMA_VERSION = 's6'          # s6 = s5 + pack_qty (штук в одной покупке), 01.09
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
        # Картинку кладём БАЙТАМИ. Со ссылкой магазина OpenAI не успевает её скачать: в первом
        # пакетном прогоне 2 972 запроса из 19 752 (15%) упали с «Timeout while downloading»
        # (2026-08-05). Байты дороже по объёму файла, поэтому пакеты режем мельче.
        b64 = _image_b64(it['img'])
        if b64:
            content = [{'type': 'text', 'text': content},
                       {'type': 'image_url',
                        'image_url': {'url': f'data:image/jpeg;base64,{b64}', 'detail': 'low'}}]
    return {
        'model': model,
        'messages': [{'role': 'system', 'content': SYS},
                     {'role': 'user', 'content': content}],
        'response_format': {'type': 'json_schema',
                            'json_schema': {'name': 'furniture', 'strict': True,
                                            'schema': schema_for(it)}},
        'reasoning_effort': 'low',
    }


# p2 остаётся годной там, где промпт p3 ничего не поменял: разница между ними одна — p3 не шлёт
# негодное описание. Если описания не было или оно было годным, ответ p2 идентичен p3, и платить
# за перегон незачем (2026-08-05).
ACCEPT_PROMPTS = ("'p2'", "'p3'")
# ДОБАВЛЕНИЕ ПОЛЯ НЕ ДОЛЖНО ГНАТЬ ВЕСЬ КАТАЛОГ ЗАНОВО (01.09). `todo()` считает необогащённым
# всё, что не совпало по версии схемы, — поэтому s5→s6 отправил бы на перегон все 20 452
# карточки ради одного числа. Схема s5 остаётся годной: у её товаров нет `pack_qty`, и он
# добирается разовой разметкой (`pack_qty.py`), а новые карточки получают его сразу, в том же
# ответе и без отдельной оплаты. Тот же приём, что уже применён к версиям промпта выше.
ACCEPT_SCHEMAS = ("'s5'", "'s6'")


def todo(items: list[dict]) -> list[dict]:
    """Кому обогащение реально нужно: новым и тем, у кого поменялся смысл или версия."""
    rows = sql(f"""select shop_mid, external_id from product_enrichment
                 where payload is not null and enrichment_version='{ENRICH_VERSION}'
                   and prompt_version in ({','.join(ACCEPT_PROMPTS)})
                   and schema_version in ({','.join(ACCEPT_SCHEMAS)})""")
    done = {tuple(l.split('\x1f')) for l in rows.strip().split('\n') if l}
    out = [it for it in items if (str(it['mid']), it['eid']) not in done]
    if len(out) < len(items):
        print(f'пропускаю {len(items) - len(out)} — уже обогащены этой версией')
    return out


VISION_FIELDS = ('styles', 'style_strength', 'materials', 'primary_color', 'shape',
                 'visual_mass', 'warmth', 'decorativeness', 'base_type', 'image_type', 'photo',
                 'specific', 'pack_qty')       # число предметов видно на фото, а не в тексте


def save(rows: list[tuple[dict, dict, dict]], model: str = MODEL, vision: bool = False) -> None:
    """Запись обогащения одной пачкой: payload + качество + версии.

    В режиме с картинкой ответ НЕ затирает текстовый: роль и функцию оставляем от текста (они
    надёжнее и дешевле), а внешние признаки берём от фотографии. Обе версии остаются в payload,
    чтобы было видно, чем именно они разошлись.
    """
    if not rows:
        return
    old = {}
    legacy = [r for r in rows if len(r) == 3]
    if vision and legacy:
        keys = ','.join(f"({it['mid']},'{it['eid']}')" for it, _, _ in legacy)
        for line in sql(f"""select shop_mid, external_id, payload->'model'
                            from product_enrichment
                           where (shop_mid, external_id) in ({keys})""").strip().split('\n'):
            f = line.split('\x1f')
            if len(f) >= 3 and f[2]:
                old[f'{f[0]}:{f[1]}'] = json.loads(f[2])
    vals = []
    for row in rows:
        if len(row) == 4:
            # T2: явная пара (текст-ответ + vision-ответ из ОДНОГО пакета) — слияние не
            # зависит от того, был ли товар обогащён текстом когда-то раньше
            it, r0, base, mv = row
            merged = dict(base)
            for fld in VISION_FIELDS:
                if fld in mv:
                    merged[fld] = mv[fld]
            payload = json.dumps({'rules': r0, 'model': merged, 'model_text': base,
                                  'model_vision': mv, 'flags': flags(r0)}, ensure_ascii=False)
            m = merged
        elif vision:
            it, r0, m = row
            base = dict(old.get(f'{it["mid"]}:{it["eid"]}') or m)
            merged = dict(base)
            for fld in VISION_FIELDS:
                if fld in m:
                    merged[fld] = m[fld]
            payload = json.dumps({'rules': r0, 'model': merged, 'model_text': base,
                                  'model_vision': m, 'flags': flags(r0)}, ensure_ascii=False)
            m = merged
        else:
            it, r0, m = row
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


from openai_budget import log_spend as _log_spend, allow as _budget_allow, report as spend_report  # noqa: E402


def log_spend(model, usage, n_req=1, note='', batch=False):
    _log_spend(model, usage, n_req, note, batch)


def ask(it: dict, key: str, model: str = MODEL, vision: bool = False) -> dict | None:
    # Синхронный путь — через канал по умолчанию (Vercel, ADR-0135): прямые кредиты OpenAI
    # кончились молча, и дельта новинок встала бы вместе с ними. Batch-путь остаётся на прямом
    # OpenAI: /v1/batches на шлюзе нет, а с живыми кредитами он вдвое дешевле.
    try:
        from llm_gateway import chat as _gw_chat
        body = body_for(it, model, vision)
        r = _gw_chat(body['model'], body['messages'],
                     **{k: v for k, v in body.items() if k not in ('model', 'messages')})
        log_spend(model, r.get('usage'), 1, 'ask' + ('+vision' if vision else ''))
        msg = r['choices'][0]['message']
        if msg.get('refusal'):
            return None
        return json.loads(msg['content'])
    except Exception:  # noqa: BLE001 — шлюз недоступен: старый прямой путь ниже
        pass
    req = urllib.request.Request(f'{API}/chat/completions',
                                 data=json.dumps(body_for(it, model, vision)).encode(),
                                 headers={'Authorization': f'Bearer {key}',
                                          'Content-Type': 'application/json'})
    for attempt in range(3):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=180))
            log_spend(model, r.get('usage'), 1, 'ask' + ('+vision' if vision else ''))   # учёт: openai_budget
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
    if not _budget_allow(model, len(items) * (2 if '--vision' in sys.argv else 1), batch=False, note='enrich sync'):
        return
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
CHUNK_VISION = 2000   # с картинкой в теле запроса файл растёт вчетверо — режем мельче


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
    idpath = os.path.join(HERE, 'enrich-batch-id.txt')
    # ДНЕВНОЙ ЛИМИТ $ (владелец 17.08): партия = 2 запроса на товар (текст+фото) через Batch (×0.5)
    if not _budget_allow(MODEL, 2 * len(items) if '--vision' in sys.argv else len(items), batch=True, note='enrich batch'):
        sys.exit(3)
    if os.path.exists(idpath) and open(idpath).read().strip():
        # Иначе id незабранного пакета затираются и оплаченный результат теряется:
        # так 06.08 весь свет (2 000 карточек) остался лежать у OpenAI
        print('СТОП: предыдущий пакет не забран (enrich-batch-id.txt не пуст) — сначала --fetch')
        sys.exit(1)
    key = _key()
    vision = '--vision' in sys.argv
    if vision:
        # Картинки качаем ПАРАЛЛЕЛЬНО и с отчётом. Последовательная скачка 25 тысяч фото — это
        # 3-7 часов полного молчания: прогон был запущен и семь минут не подавал признаков жизни
        # (поймано владельцем, 2026-08-06). Прогресс печатается, чтобы падение было видно сразу.
        from golden_label import _image_b64, IMG_STATS
        t0 = time.time()
        done = [0]

        def _warm(it):
            _image_b64(it.get('img') or '')
            done[0] += 1
            if done[0] % 1000 == 0:
                el = time.time() - t0
                left = el / max(done[0], 1) * (len(items) - done[0])
                print(f"  картинки: {done[0]}/{len(items)} (отказов {IMG_STATS['fail']}), "
                      f'прошло {el/60:.0f} мин, осталось ~{left/60:.0f} мин', flush=True)

        # 6 потоков, не 24: CDN магазина отдаёт 403 при высокой параллельности и прогон уходит
        # в модель вслепую (2026-08-06)
        with cf.ThreadPoolExecutor(6) as ex:
            list(ex.map(_warm, items))
        got = IMG_STATS['ok'] + IMG_STATS['from_disk']
        print(f"  картинки: получено {got}, не скачалось {IMG_STATS['fail']}, "
              f"за {(time.time() - t0)/60:.1f} мин", flush=True)
        if got < len(items) * 0.9:
            print('  СТОП: картинок меньше 90% — прогон вслепую не отправляю', flush=True)
            sys.exit(1)
    # T2 truth-first (фикс слияния): в vision-режиме шлём ПАРУ запросов на товар — текстовый
    # (#t) и с фото (#v). Раньше слияние опиралось на УЖЕ лежащий в БД текстовый payload,
    # а ежедневный конвейер шлёт новинкам только vision → base оказывался vision-ответом и
    # model_text == model_vision (дефект пойман на полном прогоне, признан в аудите рефери §6).
    # Пары держим соседними строками; чанк чётный — пара не рвётся между частями пакета.
    if vision:
        lines = []
        for it in items:
            cid = f'{it["mid"]}:{it["eid"]}'
            lines.append(json.dumps({'custom_id': cid + '#t', 'method': 'POST',
                                     'url': '/v1/chat/completions',
                                     'body': body_for(it, MODEL, False)}, ensure_ascii=False))
            lines.append(json.dumps({'custom_id': cid + '#v', 'method': 'POST',
                                     'url': '/v1/chat/completions',
                                     'body': body_for(it, MODEL, True)}, ensure_ascii=False))
        step = CHUNK_VISION if CHUNK_VISION % 2 == 0 else CHUNK_VISION - 1
    else:
        lines = [json.dumps({'custom_id': f'{it["mid"]}:{it["eid"]}', 'method': 'POST',
                             'url': '/v1/chat/completions', 'body': body_for(it, MODEL, vision)},
                            ensure_ascii=False) for it in items]
        step = CHUNK
    ids = []
    for i in range(0, len(lines), step):
        ids.append(_submit(lines[i:i + step], key, str(i // step + 1)))
    open(os.path.join(HERE, 'enrich-batch-id.txt'), 'w').write('\n'.join(ids))
    # Режим пишем рядом: забор результата запускается отдельно (из enrich_wait.sh) и командной
    # строки уже не видит. Без этого слияние не срабатывало, и ответ по фото затирал текстовый
    # целиком — поймано на первых 5 420 карточках (2026-08-05).
    open(os.path.join(HERE, 'enrich-batch-mode.txt'), 'w').write('vision' if vision else 'text')
    print(f'отправлено частей: {len(ids)}. Забрать: --fetch (id читаются из enrich-batch-id.txt)')


def fetch(batch_id: str, items: dict | None = None) -> None:
    key = _key()
    mode_path = os.path.join(HERE, 'enrich-batch-mode.txt')
    mode_vision = os.path.exists(mode_path) and open(mode_path).read().strip() == 'vision'
    b = json.load(urllib.request.urlopen(urllib.request.Request(
        f'{API}/batches/{batch_id}', headers={'Authorization': f'Bearer {key}'}), timeout=120))
    print(f'{batch_id}: статус {b["status"]}, готово {b["request_counts"]["completed"]}'
          f'/{b["request_counts"]["total"]}, ошибок {b["request_counts"]["failed"]}')
    if b['status'] != 'completed':
        return b['status']
    # Терминальность — по РЕЗУЛЬТАТУ, не по статусу (урок 203): у «completed» с 0 готовых нет
    # output_file_id, и забор падал 404 по .../files/None/content, а сторож молчал сутки.
    if not b['request_counts']['completed'] or not b.get('output_file_id'):
        print(f'СБОЙ-РЕЗУЛЬТАТА {batch_id}: статус completed, но готово '
              f'{b["request_counts"]["completed"]}/{b["request_counts"]["total"]} — '
              f'все запросы провалены (проверь биллинг/error_file), пакет забирать нечего')
        return 'failed_empty'
    out = urllib.request.urlopen(urllib.request.Request(
        f'{API}/files/{b["output_file_id"]}/content',
        headers={'Authorization': f'Bearer {key}'}), timeout=900).read().decode()
    items = items or {f'{it["mid"]}:{it["eid"]}': it for it in pool()}
    # Счётчик потерь обязателен (правило владельца, урок 189/190): каждая строка ответа либо
    # записана, либо посчитана в конкретной графе потерь — молчаливых continue нет.
    n = {'lines': 0, 'saved': 0, 'err': 0, 'refusal': 0, 'parse': 0, 'not_in_pool': 0}
    got = []
    pairs: dict[str, dict] = {}   # T2: парный режим — custom_id вида mid:eid#t / mid:eid#v
    for line in out.strip().split('\n'):
        r = json.loads(line)
        n['lines'] += 1
        cid = r['custom_id']
        base_id, _, ptype = cid.partition('#')
        it = items.get(base_id)
        if not it:
            n['not_in_pool'] += 1
            continue
        if r.get('error'):
            n['err'] += 1
            continue
        try:
            _resp = (r.get('response') or {}).get('body') or {}
            log_spend(_resp.get('model') or MODEL, _resp.get('usage'), 1, 'batch:' + batch_id[:14], batch=True)
        except Exception:
            pass
        msg = r['response']['body']['choices'][0]['message']
        if msg.get('refusal'):
            n['refusal'] += 1
            continue
        try:
            parsed = json.loads(msg['content'])
        except json.JSONDecodeError:
            n['parse'] += 1
            continue
        n['saved'] += 1
        if ptype:                      # парный режим: копим до полной пары
            pairs.setdefault(base_id, {'it': it})[ptype] = parsed
        else:
            got.append((it, extract(it), parsed))
        if len(got) >= 2000:
            save(got, MODEL, mode_vision)
            got = []
    save(got, MODEL, mode_vision)
    if pairs:
        full, half = [], []
        for d in pairs.values():
            it = d['it']
            if 't' in d and 'v' in d:
                full.append((it, extract(it), d['t'], d['v']))
            elif 'v' in d:             # текстовая половина потерялась — старый путь (base из БД)
                half.append((it, extract(it), d['v']))
            elif 't' in d:
                half.append((it, extract(it), d['t']))
        for i in range(0, len(full), 2000):
            save(full[i:i + 2000], MODEL, True)
        if half:
            print(f'  неполных пар: {len(half)} — сохранены одиночным путём')
            save(half, MODEL, mode_vision)
    lost = n['lines'] - n['saved']
    print(f"записано {n['saved']} из {n['lines']} (ошибок {n['err']}, отказов {n['refusal']}, "
          f"не разобрано {n['parse']}, вне пула {n['not_in_pool']})")
    if n['lines'] and n['saved'] < n['lines'] * 0.9:
        print(f'АЛЯРМ: потеряно {lost} из {n["lines"]} (>10%) — разобраться, прежде чем платить дальше')
    stats()
    return b['status']


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
    elif '--spend' in a:
        spend_report(int(a[a.index('--spend') + 1]) if len(a) > a.index('--spend') + 1 and a[a.index('--spend') + 1].isdigit() else 7)
    elif '--fetch' in a:
        i = a.index('--fetch')
        idpath = os.path.join(HERE, 'enrich-batch-id.txt')
        if len(a) > i + 1 and a[i + 1].startswith('batch_'):
            fetch(a[i + 1])
            return
        if not os.path.exists(idpath) or not open(idpath).read().strip():
            print('активного пакета нет (enrich-batch-id.txt пуст) — забирать нечего')
            return
        ids = open(idpath).read().split()
        cache = {f'{it["mid"]}:{it["eid"]}': it for it in pool()}   # один разбор пула на все части
        statuses = {bid: fetch(bid, cache) for bid in ids}
        bad = {b: s for b, s in statuses.items() if s != 'completed'}
        if not bad:
            # Пакет забран целиком: id — в журнал, активный файл убираем, гейт отправки открыт.
            # Пока файл существует, run_batch не отправит новый пакет и не затрёт эти id.
            mode_path = os.path.join(HERE, 'enrich-batch-mode.txt')
            mode = open(mode_path).read().strip() if os.path.exists(mode_path) else '?'
            with open(os.path.join(HERE, 'enrich-batch-log.txt'), 'a') as f:
                f.write(f'{time.strftime("%Y-%m-%d %H:%M")} {mode} {" ".join(ids)}\n')
            os.remove(idpath)
            print('пакет забран целиком — id в enrich-batch-log.txt, гейт отправки открыт')
        else:
            print(f'НЕ забрано {len(bad)} из {len(ids)}: '
                  + ', '.join(f'{b} ({s})' for b, s in bad.items()))
    elif '--download' in a:
        # Этап 1: скачать все картинки в дисковый кэш и НИЧЕГО не отправлять. Так проверка
        # «дошли ли фото» отделена от траты денег (предложение владельца, 2026-08-06).
        from golden_label import _image_b64, IMG_STATS
        items = pool()
        t0 = time.time()
        done = [0]

        def _warm(it):
            _image_b64(it.get('img') or '')
            done[0] += 1
            if done[0] % 1000 == 0:
                el = time.time() - t0
                print(f"  {done[0]}/{len(items)} (отказов {IMG_STATS['fail']}), "
                      f'прошло {el/60:.0f} мин, осталось ~{el/done[0]*(len(items)-done[0])/60:.0f} мин',
                      flush=True)

        with cf.ThreadPoolExecutor(6) as ex:
            list(ex.map(_warm, items))
        got = IMG_STATS['ok'] + IMG_STATS['from_disk']
        print(f"скачано {got} из {len(items)}, отказов {IMG_STATS['fail']} "
              f"({IMG_STATS['fail']/max(len(items),1)*100:.1f}%), за {(time.time()-t0)/60:.0f} мин")
    elif '--pool' in a:
        items = todo(pool())
        # W5 (аудит 10.08): переобогащение = свежая картинка. Кэш imgcache ключуется
        # URL'ом, и при подмене фото магазином по тому же URL модель вечно видела бы
        # старый снимок — сбрасываем кэш всем, кто идёт на переобогащение.
        import re as _re
        from golden_label import IMG_DIR as _IMGD
        _busted = 0
        for it in items:
            if it.get('img'):
                _p = os.path.join(_IMGD, _re.sub(r'[^A-Za-z0-9]', '_',
                                                 it['img'])[-90:] + '.jpg')
                if os.path.exists(_p):
                    os.remove(_p); _busted += 1
        if _busted:
            print(f'imgcache: сброшено {_busted} картинок переобогащаемых')
        if '--limit' in a:
            n = int(a[a.index('--limit') + 1])
            # Пилот берём ПОРОВНУ ИЗ ВСЕХ КАТЕГОРИЙ, а не первые N подряд: пул отсортирован по
            # магазину, и «первая тысяча» — это один поставщик и две-три категории, то есть
            # проверка ни о чём (замечание владельца, 2026-08-06).
            by: dict = {}
            for it in items:
                by.setdefault(it['role_feed'], []).append(it)
            per = max(n // max(len(by), 1), 1)
            picked = []
            for role, lst in sorted(by.items()):
                step = max(len(lst) // per, 1)
                picked += lst[::step][:per]
            items = picked[:n]
            print(f'пилот: {len(items)} товаров из {len(by)} категорий, примерно по {per}')
        if '--sets-roles' in a:
            # Роли, которые сборщик комплектов реально использует. Шкафы-купе и «другое» в
            # гостиную не идут — платить за их фотографии незачем (6 423 товара, 4.4 $).
            keep = {'диван', 'кресло', 'пуф', 'столик', 'тв-тумба', 'комод', 'стеллаж', 'витрина',
                    'стенка', 'стол обеденный', 'стул', 'камин', 'кашпо', 'торшер', 'ковёр',
                    'лампа', 'люстра', 'ваза', 'статуэтка', 'плед', 'подушка', 'растение',
                    'зеркало', 'полка', 'часы', 'шторы', 'бра'}
            rows = sql("select shop_mid, external_id, payload->'model'->>'role' "
                       "from product_enrichment where payload is not null")
            role_of = {}
            for line in rows.strip().split('\n'):
                f = line.split('\x1f')
                if len(f) >= 3:
                    role_of[(f[0], f[1])] = f[2]
            before = len(items)
            items = [it for it in items
                     if role_of.get((str(it['mid']), it['eid']), 'диван') in keep]
            print(f'по ролям комплектов: {len(items)} из {before}')
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
        # W5: дневной кап для крона — разовая добивка новичков (~3.2k), дальше капли
        if '--limit' in a:
            items = items[:int(a[a.index('--limit') + 1])]
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
