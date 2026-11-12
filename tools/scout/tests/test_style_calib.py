"""Поправка балла стиля по признакам фида (T-20261112-119, `style_calib.py` + `rules/style-calibration.json`): правила срабатывают
по названию и параметрам фида, «нет металла / нет натурального» не судят текстиль и декор, балл в пределах 0–10, метка версии
не даёт поправить строку дважды, ночная запись style_score без включения пишет как раньше. Без базы и сети.
    ~/venvs/scout/bin/python tools/scout/tests/test_style_calib.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import style_calib as SC  # noqa: E402

fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


cfg = SC.load()
S5 = {s: 7.0 for s in SC.STYLES} | {'universal': False}

# правила — по названию и параметрам фида
wood_table, f = SC.apply(S5, 'стол обеденный', 'Стол обеденный Лори Ясень натуральный', {'Материал ножек': 'Массив'}, cfg)
check('цельнодеревянный стол: лофт 7 → ниже порога 6,6 (нет металла)', wood_table['лофт'] < 6.6 and 'loft-no-metal' in f)
check('…и джапанди не тронут (дерево есть)', wood_table['джапанди'] == 7.0 and 'japandi-no-natural' not in f)
metal_table, f = SC.apply(S5, 'стол обеденный', 'Стол Глазго', {'Материал опор': 'Металл', 'Цвет': 'Черный'}, cfg)
check('металл в параметре опор — лофт не снижаем', metal_table['лофт'] == 7.0 and 'loft-no-metal' not in f)
curtain, f = SC.apply(S5, 'шторы', 'Шторы Togas серые', {'Материал': 'Полиэстер'}, cfg)
check('шторы: правила «нет металла/натурального» не судят текстиль', 'loft-no-metal' not in f and 'japandi-no-natural' not in f)
check('…но мягкое и текстиль — минус минимализму', curtain['минимализм'] == 5.5 and 'soft-not-minimal' in f)
boucle, f = SC.apply(S5, 'стул', 'Стул Мэник Букле Бежевый', {}, cfg)
check('букле: минимализм −1, современный +0,5', boucle['минимализм'] == 6.0 and boucle['современный'] == 7.5)
brass, f = SC.apply(S5, 'бра', 'Бра латунь абажур', {'Материал': 'металл'}, cfg)
check('латунь: неоклассика +1', brass['неоклассика'] == 8.0 and 'classic-detail' in f)
lo, _ = SC.apply({s: 0.3 for s in SC.STYLES}, 'диван', 'Диван велюр жёлтый', {}, cfg)
hi, _ = SC.apply({s: 9.8 for s in SC.STYLES}, 'диван', 'Диван ЛДСП букле', {}, cfg)
check('балл в пределах 0–10', all(0 <= v <= 10 for v in lo.values()) and all(0 <= v <= 10 for v in hi.values()))
check('прочие ключи (universal) сохраняются', 'universal' in wood_table and wood_table['universal'] is False)
check('сканди правила не трогают (разметка: ЛДСП человек 10 из 23 называет сканди)',
      all(SC.apply(S5, r, n, p, cfg)[0]['сканди'] == 7.0 for r, n, p in
          (('стол обеденный', 'Стол ЛДСП белый', {}), ('столик', 'Столик металл черный', {}), ('диван', 'Диван велюр', {}))))

# метка версии — повторно не правим
check('метка версии в src узнаётся', SC.calibrated('llm+rules+' + SC.mark(cfg), cfg) and not SC.calibrated('llm+rules', cfg))
check('другая версия — не своя метка', not SC.calibrated('llm+rules+cal:old-v0', cfg))

# правила — в одном месте (JSON), у каждого есть «почему»; включение — решением, не по умолчанию
check('у каждого правила есть id, delta и _why', all(r.get('id') and r.get('delta') and r.get('_why') for r in cfg['rules']))
check('стили в правилах — из шести', all(set(r['delta']) <= set(SC.STYLES) for r in cfg['rules']))
check('включён вариант А (директор 12.11, T-20261112-119/2): правила без сдвига шкалы', cfg['enabled'] is True and not cfg.get('offsets'))

# style_score: поправка только у гостиной и только при enabled (иначе запись как раньше)
src = open(os.path.join(HERE, '..', 'style_score.py'), encoding='utf-8').read()
i = src.index("if SOURCE=='living':\n    # ПОПРАВКА")
blk = src[i:src.index("elif '--db' in sys.argv and SOURCE=='hall' and fails", i)]
check('style_score: поправка в ветке гостиной под enabled', "_cal.get('enabled')" in blk and '_SC.apply' in blk)
check('style_score: кэш файла остаётся сырым (поправка после json.dump кэша)', src.index("json.dump(cache,open(OUT,'w'),ensure_ascii=False)\nprint") < i)

print('ИТОГ:', 'ok' if not fails else f'{fails} провалов')
sys.exit(1 if fails else 0)
