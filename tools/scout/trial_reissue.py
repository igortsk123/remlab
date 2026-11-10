#!/usr/bin/env python3
"""ПЕРЕСБОРКА ГОТОВОГО ТУРА «КАК ЕСТЬ» (план agent-trial-08; T-20261110-05): данные страницы на ТЕКУЩЕМ коде сборщика из сохранённого
`result` задания и его последней опубликованной версии — без нового разбора плана и без нового подбора мебели (0 $).

Зачем: тур собирается один раз; правки сборщика и страницы (уникальные имена товаров, вкладка плана с дверями, порядок комнат)
на готовые туры не попадают, а «Обустроить» берёт только комнаты «ждут проверки». Ставит оператор (`tools/floorplan/reissue.py`).

Откуда что берётся:
  заново (текущий `trial_bundle.build` по `result`): план (`trial.panels` со стенами и проёмами), подписи и порядок комнат, этажи,
    `rooms_geo` комнат вне подбора, исходы прочих комнат (кухня, прихожая…), правила страницы, опрос, `photo_ok`, ленты замен, имена товаров;
  из прежней версии (входов подбора уже нет: сцена гостиной и куски спален живут в рабочих папках DEV сутки): ВЫБОР мебели —
    варианты комнаты с предметами (роль, место, поворот, модель, размеры, цвет, камеры), исход комнаты (готово / отказ с текстом /
    ждёт проверки), отметка «размеры примерные» и коробка комнаты (`w`, `d`, проёмы — предметы стоят в её координатах; у пустой
    перенесённой комнаты — тоже прежняя, её считала стадия подбора).
Комнату сопоставляем по (панель, id комнаты плана) через `trial.panels` обеих версий, а не по id страницы: нумерация могла смениться.
Комната-цель, которой в прежней версии нет (новый код признал её гостиной/спальней), а подбор для неё не делался, — честный отказ
`reissue_no_source` (пустая комната с текстом), а не вечное «подбирается».

  ~/venvs/scout/bin/python trial_reissue.py <job_id> <result.json> <bundle-прежний.json> --out <bundle-новый.json>
Код выхода: 0 — собрано (отчёт JSON-строкой в stdout: что пересобрано, что осталось прежним), 2 — отказ (причина JSON-строкой).
"""
from __future__ import annotations

import json
import re
import sys

import trial_bundle as TB

OUTCOME_KEYS = ('furniture_state', 'furniture_outcome', 'furniture_code', 'furniture_text', 'furniture_text_en')
GEO_KEEP = ('w', 'd', 'openings', 'radiators')        # коробка под мебелью: предметы стоят в её координатах
NO_SOURCE = 'reissue_no_source'


def room_keys(bundle: dict) -> dict:
    """id комнаты страницы → (панель, id комнаты плана) по `trial.panels`. Старая версия без `src_id` — ключ по id страницы."""
    out = {}
    for p in (bundle.get('trial') or {}).get('panels') or []:
        for r in p.get('rooms') or []:
            out[r['id']] = (p.get('id'), r['src_id']) if r.get('src_id') is not None else ('#', r['id'])
    return out


def _sleep_w(item: dict, sku: dict) -> None:
    """Ширина спального места — в имени прежней версии («Кровать 180 см…»), если в `sku` её нет (сборки до `sleep_w`)."""
    if isinstance(sku.get('sleep_w'), (int, float)):
        return
    ru, _ = TB.neutral_names(TB._base_role(item.get('role') or ''))
    m = re.match(re.escape(ru) + r' (\d{2,3}) см\b', str(sku.get('name') or ''))
    if m:
        sku['sleep_w'] = int(m.group(1))


def _carry_variant(v: dict, old_rid: str, rid: str) -> dict:
    """Вариант прежней версии → в комнату `rid`: предметы через общий разрешённый список, id — с новым id комнаты."""
    vid = str(v.get('id') or '')
    for pre in (f'trial-{old_rid}', f'{old_rid}-'):
        if vid.startswith(pre):
            vid = (f'trial-{rid}' if pre.startswith('trial-') else f'{rid}-') + vid[len(pre):]
            break
    items = []
    for it in v.get('items') or []:
        it = TB.public_item(it)
        if isinstance(it.get('sku'), dict):
            it['sku'] = dict(it['sku'])
            _sleep_w(it, it['sku'])
        items.append(it)
    return {**v, 'id': vid, 'room_id': rid, 'items': items}


def reissue(job_id: str, result: dict, old: dict, ctx: dict | None = None) -> tuple[dict, dict]:
    """→ (новые данные страницы, отчёт). Отказ сборщика (план не собрать текущим кодом) — `BundleRefused` наверх: тур остаётся прежним."""
    if (old.get('trial') or {}).get('job_id') != job_id:
        raise TB.BundleRefused('wrong_job', 'прежняя версия другого задания')
    ctx = ctx or TB.default_ctx()
    old_keys = room_keys(old)
    old_rooms = {r['id']: r for r in old.get('apartment_rooms') or []}
    by_key = {old_keys[rid]: rid for rid in old_rooms if rid in old_keys}
    # «размеры примерные» (агент снял проверку) — флагом в копии результата, как делает «Обустроить»: сборщик считает фото и отметку сам
    res = json.loads(json.dumps(result))
    consent = {old_keys[rid] for rid, r in old_rooms.items() if r.get('approx_consent') and rid in old_keys}
    for p in res['panels']:
        for r in p['rooms']:
            if (p['id'], r['id']) in consent and TB.APPROX_CONSENT not in (r.get('flags') or []):
                r['flags'] = list(r.get('flags') or []) + [TB.APPROX_CONSENT]
    new = TB.build(job_id, res, None, ctx=ctx)
    new_keys = room_keys(new)
    plan_room = {(p['id'], r['id']): r for p in res['panels'] for r in p['rooms']}
    old_vars: dict = {}
    for v in old.get('variants') or []:
        old_vars.setdefault(v.get('room_id'), []).append(v)
    carried, report = {}, {'kept_furniture': [], 'kept_outcome': [], 'no_source': [], 'renamed_rooms': {}, 'rebuilt': [
        'план и стены', 'подписи и порядок комнат', 'комнаты без мебели', 'правила страницы и опрос', 'имена товаров и ленты замен']}
    for e in new['apartment_rooms']:
        rid = e['id']
        oid = by_key.get(new_keys.get(rid))
        o = old_rooms.get(oid) if oid else None
        # цель — по виду или по «подбирается» текущего сборщика (гостиная с подписью у комнаты вида `other`); НЕ по прежнему исходу:
        # гостиную без подписи сборщик больше не угадывает (T-20261110-12), и прежний отказ угаданной «гостиной» (FYyX…: ванная без
        # подписи, «гостиная мала») иначе воскресал бы на безымянной комнате
        target = (e['kind'] in TB.TARGET_KINDS or (o or {}).get('kind') in TB.TARGET_KINDS or e['furniture_state'] == 'pending')
        if not target:
            continue
        if o is None or o.get('furniture_state') not in TB.ROOM_STATES or o['furniture_state'] == 'pending':
            if e['furniture_state'] == 'pending':        # подбора для неё не было, а новый не делаем — отказ с текстом, не крутилка
                e.update(TB._outcome('refused', NO_SOURCE))
                carried[rid] = [TB._empty_variant(rid, new['rooms_geo'][rid], 'failed', {'code': NO_SOURCE})] if rid in new['rooms_geo'] else []
                report['no_source'].append(rid)
            continue
        if oid != rid:
            report['renamed_rooms'][oid] = rid
        e.update({k: o.get(k) for k in OUTCOME_KEYS})
        e['kind'] = o.get('kind') or e['kind']
        if o.get('approx_consent'):
            e['approx_consent'] = True
        else:
            e.pop('approx_consent', None)
        vs = [_carry_variant(v, oid, rid) for v in old_vars.get(oid, [])]
        carried[rid] = vs
        og, ng = (old.get('rooms_geo') or {}).get(oid), new['rooms_geo'].get(rid)
        furnished = any(v['items'] for v in vs)
        # коробка — прежняя у ЛЮБОЙ перенесённой комнаты (обставленной и пустой «ждёт проверки»/отказ): её считала стадия подбора, текущий
        # сборщик без стадии считает проёмы иначе (прод 10.11: петля двери пустой спальни FYyX… переворачивалась); подписи — текущим кодом
        if og and vs:
            new['rooms_geo'][rid] = {**og, **{k: v for k, v in (ng or {}).items() if k not in GEO_KEEP}}
        (report['kept_furniture'] if furnished else report['kept_outcome']).append(rid)
        r = plan_room.get(new_keys.get(rid))
        if r is not None:
            consented = TB.APPROX_CONSENT in (r.get('flags') or [])
            e['photo_ok'] = TB.photo_ok(res, r, e['kind'], e['furniture_state'], consented)
    # порядок вариантов — как у сборщика (по комнатам), прежние варианты комнаты — в прежнем порядке
    order, variants = [], []
    for v in new['variants']:
        if v['room_id'] not in order:
            order.append(v['room_id'])
    order += [e['id'] for e in new['apartment_rooms'] if e['id'] in carried and e['id'] not in order]
    for rid in order:
        variants += carried[rid] if rid in carried else [v for v in new['variants'] if v['room_id'] == rid]
    ids = [v['id'] for v in variants]
    if len(ids) != len(set(ids)):
        raise TB.BundleRefused('parts_mismatch', 'id вариантов повторяются после переноса')
    lost = sorted({v['room_id'] for v in variants} - set(new['rooms_geo']))
    if lost:
        raise TB.BundleRefused('parts_mismatch', f'вариант без коробки комнаты: {lost}')
    with_variant = {v['room_id'] for v in variants}
    for e in new['apartment_rooms']:
        e['contentState'] = 'ready' if e['id'] in with_variant else 'soon'
    TB.name_items(variants)
    feeds = TB._feeds(variants)
    rules = dict(new['rules'])
    if ctx.get('slot_band') and TB.LIVING in new['rooms_geo']:
        rules['slot_band_cm'] = ctx['slot_band'](new['rooms_geo'][TB.LIVING])
    trial = dict(new['trial'])
    trial['furniture'] = (old.get('trial') or {}).get('furniture') or trial['furniture']
    trial['flags'] = sorted(set(trial.get('flags') or []) | set((old.get('trial') or {}).get('flags') or []))
    trial['complete'] = all(r['furniture_state'] != 'pending' for r in new['apartment_rooms'])
    trial['refused_rooms'] = [x for x in trial.get('refused_rooms') or [] if x.get('room_id') not in report['kept_furniture']]
    # товары прежней версии (T-20261110-25) переносятся с предметами — пометка «с товарами» и курс английской цены — по ним
    trial.pop('goods', None)
    trial.pop('money_en', None)
    trial.update(TB.goods_meta(variants, ctx['money_en'] if 'money_en' in ctx else TB.uk_money()))
    out = {**new, 'variants': variants, 'feeds': feeds, 'sofa_feed': feeds.get('диван', []), 'rules': rules, 'trial': trial,
           'rooms_enabled': sorted(with_variant), 'room': new['rooms_geo'].get(TB.LIVING) or next(iter(new['rooms_geo'].values()))}
    TB.assert_public(out, [], goods=True)
    report['kept'] = 'выбор мебели, исходы комнат и коробка комнат с мебелью — из прежней версии (подбор не повторяли)'
    return out, report


def main() -> int:
    args = sys.argv[1:]
    out = TB._arg(args, '--out')
    if len(args) != 3 or not out:
        print(__doc__)
        return 0
    job_id, result_path, old_path = args
    result = json.load(open(result_path, encoding='utf-8'))
    old = json.load(open(old_path, encoding='utf-8'))
    try:
        data, report = reissue(job_id, result, old)
    except TB.BundleRefused as e:
        print(json.dumps({'refusal': e.code, 'detail': e.detail}, ensure_ascii=False))
        return 2
    TB.write_atomic(out, data)
    # ракурсы — в данные (T-20261110-32): перевыпуск доносит их и до старых туров, страница которых закреплена (`lib/trial/tour.ts`)
    print(TB.add_cams(out, []), flush=True)                  # до итоговой строки: `floorplan/reissue.py` читает последнюю
    print(json.dumps({'ok': True, **report}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
