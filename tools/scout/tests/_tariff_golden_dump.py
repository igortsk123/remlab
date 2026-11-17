"""Печатает отпечатки входов standard для golden-теста (запускать на НЕТРОНУТОМ коде): python tests/_tariff_golden_dump.py"""
import json

import _tariff_fixture as F

out = {}
for name, kw in (('decor', dict(with_decor=True)), ('nodecor', dict(with_decor=False))):
    out[name] = F.fingerprint(F.build(F.payload(**kw)))
print(json.dumps(out, ensure_ascii=False, indent=1))
