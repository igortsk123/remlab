#!/usr/bin/env python3
"""Проход 3 (17.10, владелец: «GPT 2 теплее и больше похоже на сканди — может, промпт подкорректировать?»): тот же лист,
модель из аргументов, но STYLE GUIDE «сканди» подменён на более тёплый/конкретный — без правки styles.json. ПЛАТНО."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'scout')); sys.path.insert(0, HERE)
import improve_mode as IM  # noqa: E402
WARM = ('SCANDINAVIAN STYLE, WARM AND COSY: warm white matte walls with a faint cream undertone (never cold grey); honey-toned light oak '
        'plank flooring; white ceiling; simple flat white skirting, no mouldings; WARM late-afternoon daylight (about 3500 K) with a soft '
        'golden cast on the walls and floor; cream or oatmeal linen curtains on a thin black rod; optional one or two black-framed art '
        'prints; optional one green plant in a plain pot; flat white radiator below the window. Calm, uncluttered, looks like a real, '
        'recently renovated flat with ordinary affordable materials. No gloss, no gold, no ornament.')
_orig = IM.style_block
IM.style_block = lambda style: (_orig(style)[0], WARM, _orig(style)[2])
import importlib.util
spec = importlib.util.spec_from_file_location('b1', os.path.join(HERE, 'bench-realistic.py')); b1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(b1)
b1.main()
