#!/usr/bin/env python3
"""Раздел «Спальня» страницы шаблонов /test/canons/ (план bedroom-uk-single-01, 09.11).

Каждое назначение спальни (`services/planner-solver/rules/bedroom.json` purposes) раскладывается НАСТОЯЩИМ солвером
(`planner/bedroom.py:solve_bedroom`) в трёх спальнях из объявления владельца (`uk-bedrooms.json`); каждый шаблон
(`templates`) показан на раскладке, где солвер его применил, с паспортом (для кого, правило, проверка). Рисует тот же
`render_plan.render_artifact`, что и гостиную. Набор предметов — идеалы слотов сборщика
(`rules/bedroom-composition.json` purposes[*].slots); у назначений без слотов (кабинет, детская) — пример ниже (`EXTRA`).
Гостиную модуль не трогает: зовётся из `canon_gallery.main` и дописывает раздел в конец страницы.
"""
from __future__ import annotations

import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVER = os.path.join(HERE, '..', '..', 'services', 'planner-solver')
sys.path.insert(0, SOLVER)

from planner.bedroom import solve_bedroom  # noqa: E402
from planner.models import Item, Opening, Radiator, Room, Severity  # noqa: E402
from planner.validate import validate  # noqa: E402

BR = json.load(open(os.path.join(SOLVER, 'rules', 'bedroom.json'), encoding='utf-8'))
COMP = json.load(open(os.path.join(HERE, 'rules', 'bedroom-composition.json'), encoding='utf-8'))
UK = json.load(open(os.path.join(HERE, 'uk-bedrooms.json'), encoding='utf-8'))

PURPOSE_TITLE = {'couple': 'пара', 'single': 'один взрослый', 'guest': 'гостевая', 'office': 'кабинет',
                 'child:7-12': 'детская 7–12 лет', 'single_narrow': 'узкая односпальная (UK single 90×190)'}
TEMPLATE_TITLE = {'bed_center_wall': 'кровать по центру стены', 'bed_corner': 'односпальная в угол',
                  'storage_solid_wall': 'шкаф и комод у глухой стены', 'work_at_window': 'рабочий стол у окна',
                  'dressing_table': 'туалетный столик у стены',
                  'bed_narrow_wall': 'узкая односпальная боком к стене (UK single)'}
BED_KIND = {'double': 'только двуспальная (рама от 130 см)', 'any': 'любая',
            'single': 'только односпальная (рама уже 130 см)'}


def I(role: str, w: float, d: float, h: float) -> Item:
    return Item(role=role, w_cm=w, d_cm=d, h_cm=h)


# назначения без слотов сборщика (кабинет, детская) и предметы, которых нет в слотах, но назначение их держит (стол у
# одного взрослого, туалетный столик у пары) — пример размеров; детская — каталог 07.11 (как KIDS в test_bedroom_solver)
EXTRA = {
    'couple': [I('туалетный столик', 100, 45, 76)],
    'single': [I('стол рабочий', 110, 60, 75), I('стул рабочий', 55, 55, 90)],
    'single_narrow': [I('стол рабочий', 100, 55, 75), I('стул рабочий', 50, 50, 85)],
    'office': [I('стол рабочий', 120, 60, 75), I('стул рабочий', 60, 60, 110), I('шкаф', 100, 58, 200),
               I('комод', 80, 45, 85), I('кровать', 100, 205, 100), I('тумба прикроватная', 40, 35, 50)],
    'child:7-12': [I('кровать детская', 86, 166, 80), I('стол детский', 100, 55, 75), I('стул детский', 51, 45, 57),
                   I('шкаф', 93, 55, 195), I('комод', 80, 45, 86)],
}
# пример шаблона — где он показательнее всего; не нашёлся там — первая раскладка, где солвер его применил
EXAMPLE = {'bed_center_wall': ('couple', 'bedroom-one'), 'bed_corner': ('office', 'bedroom-two'),
           'storage_solid_wall': ('single', 'bedroom-two'), 'work_at_window': ('single', 'bedroom-two'),
           'dressing_table': ('couple', 'bedroom-one'), 'bed_narrow_wall': ('single_narrow', 'bedroom-three')}


def purposes() -> list[str]:
    """Назначения правил солвера; детская — по возрастам, у которых есть состав (`ages`), остальные ждут."""
    out = []
    for p, cfg in BR['purposes'].items():
        if p.startswith('_'):
            continue
        if cfg.get('ages'):
            out += [f'{p}:{a}' for a in cfg['ages'] if not a.startswith('_')]
        elif not cfg.get('pending'):
            out.append(p)
    return out


def cfg_of(purpose: str) -> dict:
    p, _, age = purpose.partition(':')
    c = BR['purposes'][p]
    return c['ages'][age] if age else c


def kit(purpose: str) -> list[Item]:
    """Предметы назначения: идеалы слотов сборщика (qty — номера «тумба прикроватная 2») + EXTRA; дубли ролей — первый."""
    items = []
    for sl in (COMP['purposes'].get(purpose) or {}).get('slots') or []:
        i = sl['ideal']
        for k in range(int(sl.get('qty', 1))):
            items.append(I(sl['role'] + (f' {k + 1}' if k else ''), i['w'], i['d'], i.get('h', 80)))
    have = {x.role for x in items}
    return items + [x for x in EXTRA.get(purpose, []) if x.role not in have]


def room_of(spec: dict, purpose: str) -> Room:
    p, _, age = purpose.partition(':')
    return Room(width_cm=spec['w'], depth_cm=spec['d'], room_type='bedroom', purpose=p, child_age=age or None,
                openings=[Opening(**o) for o in spec['openings']], radiators=[Radiator(**r) for r in spec['radiators']])


def solve_all() -> dict:
    """{(назначение, комната): (Room, Layout, жёсткие повторной проверки)} — один вход → одна раскладка."""
    out = {}
    for purpose in purposes():
        for spec in UK['rooms']:
            room = room_of(spec, purpose)
            lay = solve_bedroom(room, kit(purpose))
            again = [v.code for v in validate(room, lay.placements).violations if v.severity is Severity.HARD] \
                if lay.placements else []
            out[(purpose, spec['id'])] = (room, lay, again)
    return out


def _m(cm: float) -> str:
    return f'{cm / 100:.2f}'.replace('.', ',')


def _room_name(spec: dict) -> str:
    return f"{spec['title']} {_m(spec['w'])}×{_m(spec['d'])}"


def _png(purpose: str, room_id: str) -> str:
    return f"bedroom.{purpose.replace(':', '-')}.{room_id}.png"


def _verdict(lay, again) -> str:
    """Итог раскладки простыми словами: встало / не встало и почему, мягкие замечания."""
    if not lay.placements:
        why = ', '.join(lay.meta.get('reason') or []) or 'нет раскладки'
        return f"<p class='none'>не разложено: {html.escape(why)}</p>"
    hard = [v for v in lay.violations if v.severity is Severity.HARD]
    soft = [v for v in lay.violations if v.severity is not Severity.HARD]
    parts = [("<b class='ok'>жёстких нарушений нет</b>" if not hard and not again else
              f"<b class='none'>жёсткие: {html.escape(', '.join(sorted({v.code for v in hard} | set(again))))}</b>")]
    if lay.skipped_optional:
        parts.append('не нашлось места: ' + html.escape(', '.join(lay.skipped_optional)))
    if lay.unplaced:
        parts.append("<span class='none'>обязательное не встало: " + html.escape(', '.join(lay.unplaced)) + '</span>')
    if soft:
        parts.append('мягкие: ' + html.escape('; '.join(sorted({v.message for v in soft}))))
    tpls = sorted({p.tpl_id for p in lay.placements if p.tpl_id})
    if tpls:
        parts.append('шаблоны: ' + html.escape(', '.join(tpls)))
    return "<div class='verdict'>" + '<br>'.join(parts) + '</div>'


def _new(d: dict) -> str:
    return " <span class='new'>новый</span>" if d.get('added') else ''


# кегль подписей — доля ширины кадра (render_plan: SC 2.6 + поля 40): три плана в ряд по ~340 px, прежний кегль ужимался
# до 6–8 px; ширина/30 → ~11 px на экране у всех трёх комнат одинаково
FONT_DIV = 30.0


CSS = (".bedhead{margin:34px 0 6px;padding-top:18px;border-top:3px solid #3B76A2}"
       ".grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px;margin-top:6px}"
       ".grid3 figure{margin:0}.grid3 figcaption{font-size:14.5px;color:#3A423C;margin-top:4px}"
       ".grid3 figcaption b.cap{display:block;color:#1A1F1C;font-size:15px}"
       ".verdict{font-size:14px;line-height:1.45}.ok{color:#2D6A3E}"
       ".new{display:inline-block;background:#2D6A3E;color:#fff;font-size:13px;font-weight:600;padding:1px 8px;"
       "border-radius:10px;vertical-align:middle}"
       "section.isnew{background:#F3F8F3;border-radius:6px;padding-left:10px;padding-right:10px}"
       ".legend{font-size:14.5px;color:#3A423C}"
       ".tplrow{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:flex-start}.tplpic{flex:0 1 400px;max-width:100%}"
       ".tplrow .meta{flex:1 1 280px;margin-top:0}")


def section(out_dir: str, artifact, render_artifact) -> tuple[str, list[str]]:
    """HTML раздела «Спальня» + предупреждения (шаблон без примера, жёсткое на раскладке). PNG — в out_dir."""
    res = solve_all()
    warn = []
    specs = {s['id']: s for s in UK['rooms']}
    for (purpose, rid), (room, lay, _again) in res.items():
        if lay.placements:
            render_artifact(artifact(room, lay.placements), os.path.join(out_dir, _png(purpose, rid)), band='31-40',
                            radiators=True, font_px=round((room.width_cm * 2.6 + 40) / FONT_DIV), labels_inside=True)
    rooms_html = ''.join(f"<li><b>{html.escape(_room_name(s))}</b> — "
                         f"{html.escape(s['_why'])}</li>" for s in UK['rooms'])
    head = ("<h1 id='bedroom' class='bedhead'>Спальня — шаблоны и назначения</h1>"
            "<div class='head'>Каждый план разложен ТЕМ ЖЕ солвером спальни, что и рабочие наборы "
            "(<code>planner/bedroom.py</code>), в трёх спальнях из объявления (TG 260). Размеры комнат — из объявления, "
            "окна и двери — правдоподобное допущение (плана этажа нет): " + html.escape(UK['_source'].split(': ', 1)[-1])
            + f"<ul>{rooms_html}</ul>"
            "<span class='legend'>Как читать план: синий прямоугольник с белой полосой — кровать, полоса — подушка у "
            "изголовья; оранжевая линия и четверть круга — дверь и её открывание; голубая линия — окно; розовая полоса "
            "у стены — радиатор. Подпись — роль и размер Ш×Г, см. Планы растянуты на ширину колонки, поэтому они не в одном масштабе "
            "(маленькая Bedroom Three выглядит крупнее), размер комнаты указан под планом. План открывается крупно по нажатию.</span></div>")
    # ---- шаблоны
    tcards = []
    for n, (tid, t) in enumerate((k, v) for k, v in BR['templates'].items() if not k.startswith('_')):
        hits = [k for k, (_, lay, again) in res.items()
                if any(p.tpl_id == tid for p in lay.placements) and not again
                and not any(v.severity is Severity.HARD for v in lay.violations)]
        pick = EXAMPLE.get(tid) if EXAMPLE.get(tid) in hits else (hits[0] if hits else None)
        if pick is None:
            warn.append(f'шаблон {tid}: солвер нигде его не применил — карточка без плана')
            img = "<p class='none'>ни одна раскладка этот шаблон не применила</p>"
        else:
            purpose, rid = pick
            img = (f"<a class='tplimg' href='{_png(purpose, rid)}'><img src='{_png(purpose, rid)}' alt='{html.escape(tid)}'></a>"
                   f"<div class='verdict tplex'>пример: <b>{html.escape(PURPOSE_TITLE.get(purpose, purpose))}</b> · "
                   f"{html.escape(_room_name(specs[rid]))}; "
                   + (f"ещё в {len(hits) - 1} из {len(res)} раскладок" if len(hits) > 1 else
                      f"в остальных {len(res) - 1} раскладках не применялся") + "</div>")
        fr = t.get('for')
        meta = (f"<div><b>для назначений:</b> {html.escape(', '.join(fr) if fr else 'любое, где есть эти предметы')}</div>"
                f"<div><b>правило:</b> {html.escape(t.get('_why', ''))}</div>"
                f"<div><b>проверка:</b> {html.escape(t.get('_enforce', ''))}</div>")
        tcards.append(f"<section class='{'isnew' if t.get('added') else ''}'><h2><span class='num'>С{n + 1}</span> "
                      f"{html.escape(TEMPLATE_TITLE.get(tid, tid))}{_new(t)} <small>bedroom.{html.escape(tid)}</small></h2>"
                      f"<div class='tplrow'><div class='tplpic'>{img}</div><div class='meta'>{meta}</div></div></section>")
    # ---- назначения: по плану на каждую комнату
    pcards = []
    off = len(tcards)
    for n, purpose in enumerate(purposes()):
        c = cfg_of(purpose)
        base = BR['purposes'][purpose.partition(':')[0]]
        figs = []
        for spec in UK['rooms']:
            room, lay, again = res[(purpose, spec['id'])]
            img = (f"<a href='{_png(purpose, spec['id'])}'><img src='{_png(purpose, spec['id'])}' "
                   f"alt='{html.escape(purpose)} {spec['id']}'></a>"
                   if lay.placements else '')
            figs.append(f"<figure>{img}<figcaption><b class='cap'>{html.escape(_room_name(spec))}</b>"
                        f"{_verdict(lay, again)}</figcaption></figure>")
            if again or any(v.severity is Severity.HARD for v in lay.violations):
                warn.append(f'{purpose} × {spec["id"]}: жёсткое на раскладке')
        sizes = ', '.join(f"{x.role} {x.w_cm:.0f}×{x.d_cm:.0f}" for x in kit(purpose))
        meta = (f"<div><b>обязательно:</b> {html.escape(', '.join(c.get('required', [])))}</div>"
                f"<div><b>по месту:</b> {html.escape(', '.join(c.get('optional', [])))}</div>"
                f"<div><b>кровать:</b> {html.escape(BED_KIND.get(c.get('bed', 'any'), c.get('bed', '')))}"
                + (f"; шаблон кровати — {html.escape(c['bed_template'])}" if c.get('bed_template') else '') + '</div>'
                f"<div><b>почему:</b> {html.escape(c.get('_why', ''))}</div>"
                f"<div><b>предметы на плане (Ш×Г, см):</b> {html.escape(sizes)}</div>")
        isnew = bool(base.get('added'))
        pcards.append(f"<section class='{'isnew' if isnew else ''}'><h2><span class='num'>С{off + n + 1}</span> "
                      f"Назначение: {html.escape(PURPOSE_TITLE.get(purpose, purpose))}{_new(base)} "
                      f"<small>bedroom.purpose.{html.escape(purpose)}</small></h2>"
                      f"<div class='meta'>{meta}</div><div class='grid3'>{''.join(figs)}</div></section>")
    pend = [f'{p}:{a}' for p, cfg in BR['purposes'].items() if cfg.get('ages')
            for a in ('0-3', '3-7', 'teen') if a not in cfg['ages']]
    tail = (f"<p class='legend'>Ждут состава (солвер отвечает PURPOSE_PENDING, план не рисуется): "
            f"{html.escape(', '.join(pend))}.</p>") if pend else ''
    body = (head + "<h2 style='margin-top:22px'>Шаблоны спальни</h2>" + ''.join(tcards)
            + "<h2 style='margin-top:22px'>Назначения спальни — каждая комната</h2>" + ''.join(pcards) + tail)
    return body, warn
