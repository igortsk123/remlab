#!/usr/bin/env python3
"""ПРИГОДНОСТЬ ТОВАРА ДЛЯ ЖИЛОЙ ГОСТИНОЙ — одно правило на подбор наборов (`compose2.py`) и лечение/ленты демо
(`flat215_demo.py`). Вынесено 15.10 (demo-05): лечение демо его не применяло и подставило к обеденному столу барный стул.
Лёгкий модуль без побочных эффектов — `compose2` при импорте исполняет полный прогон, его не импортировать.

  python3 unfit.py --selftest
"""
import re
import sys

# СИСТЕМНЫЙ фильтр пригодности для жилой гостиной (правило владельца: решения — на масштаб,
# не «для 1 ситуации»): недопустимые материалы/назначения по классам ролей, из params фида
UNFIT_ANY=re.compile(r'автомобильн|для ванн|банн|садов|уличн|для рассады|теплиц|туристич|детск сад',re.I)
UNFIT_BY_CLASS={
 ('ковёр','плед','подушка'): re.compile(r'каучук|эва|пвх|резин|силикон|грязезащит|противоскольз',re.I),
 ('кашпо','ваза'):           re.compile(r'для рассады|торфян|вазон|flower|чаша|горшечн|подвесн|ампельн|цеп|балконн',re.I),
 ('стул','кресло'):          re.compile(r'компьютерн|офисн|геймерск|игров|руководител|оператор|барн',re.I),
}
def unfit(role,name,mat=None,h=None,dia=None):
    txt=(name or '')+' '+(mat or '')
    if UNFIT_ANY.search(txt): return True
    for roles,rx in UNFIT_BY_CLASS.items():
        if role in roles and rx.search(txt): return True
    if role=='кашпо' and (h or dia) and (h or 0)<30 and (dia or 0)<30:
        return True  # напольное кашпо ≥30 см высоты или диаметра; мелочь = подвесное/настольное
    if role=='стул' and (h or 0)>110:
        return True  # спинка обеденного стула ≤110 см; выше — офисное/компьютерное кресло
    return False


def _selftest() -> int:
    cases = [(('стул', 'Стул барный divan.ru Эрин Рогожка Графитовый'), True), (('стул', 'Стул divan.ru Алекс Букле Серый'), False),
             (('стул', 'Стул офисный Х'), True), (('ковёр', 'Ковёр резиновый грязезащитный'), True), (('диван', 'Диван уличный'), True),
             (('стол обеденный', 'Стол барный'), False)]
    bad = [c for c, want in cases if unfit(*c) != want]
    print('unfit selftest:', 'чисто' if not bad else f'провалы {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
