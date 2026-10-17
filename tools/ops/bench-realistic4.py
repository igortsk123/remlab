#!/usr/bin/env python3
"""Проход 4 (17.10, владелец: «реалистичности недостаточно»): тёплый гайд + блок PHOTOGRAPHIC LOOK в промпте; качество модели — из
GPT_IMAGE_QUALITY (medium|high). Без правки styles.json/improve_mode. ПЛАТНО."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'scout')); sys.path.insert(0, HERE)
import improve_mode as IM  # noqa: E402
WARM = ('SCANDINAVIAN STYLE, WARM AND COSY: warm white matte walls with a faint cream undertone (never cold grey); honey-toned light oak '
        'plank flooring; white ceiling; simple flat white skirting, no mouldings; WARM late-afternoon daylight (about 3500 K) with a soft '
        'golden cast on the walls and floor; cream or oatmeal linen curtains on a thin black rod; optional one or two black-framed art '
        'prints; optional one green plant in a plain pot; flat white radiator below the window. Calm, uncluttered, looks like a real, '
        'recently renovated flat with ordinary affordable materials. No gloss, no gold, no ornament.')
PHOTO = ('\n\nPHOTOGRAPHIC LOOK — MANDATORY. The result must read as a real interior photograph taken with a full-frame camera and a 24 mm '
         'lens for a property listing, not as a 3D render: physically plausible global illumination with soft bounced light, accurate '
         'contact shadows under every object, subtle ambient occlusion in corners, real fabric weave on upholstery and curtains, visible '
         'wood grain on the floor and table, faint micro-imperfections on painted walls, slight natural vignetting and gentle sensor '
         'grain, true-to-life white balance. No plastic-looking surfaces, no perfectly uniform walls, no CGI gloss, no oversaturation. '
         'Never add armrests, cushions, throws or any textile to the furniture — each product keeps exactly its catalogue shape.')
_orig_sb = IM.style_block
IM.style_block = lambda style: (_orig_sb(style)[0], WARM, _orig_sb(style)[2])
_orig_pf = IM.prompt_for
IM.prompt_for = lambda *a, **k: _orig_pf(*a, **k) + PHOTO
import importlib.util
spec = importlib.util.spec_from_file_location('b1', os.path.join(HERE, 'bench-realistic.py')); b1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(b1)
b1.main()
