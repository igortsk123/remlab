#!/usr/bin/env python3
"""ПРОФИЛЬ РЕСУРСОВ SALAD (T-186/1): показать профиль типа работы и сверить его с замером прогона.

  python3 resource_profile.py --list                    все профили: карта, vCPU/RAM/диск, тариф, откуда числа
  python3 resource_profile.py --show <тип>              одна строка профиля целиком
  python3 resource_profile.py --suggest <summary.json>  расхождения «профиль ↔ замер» по итогу пробы (summary-<группа>.json)

Профиль правит человек/директор (`rules/salad-resources.json`), скрипт ничего не пишет: он только печатает, что поменять и на чём основан вывод (замер из /health воркера:
peak_rss_gb, peak_vram_gb, disk_free_gb, disk_mb_s, weights_gb_min). Платного не запускает, сети не трогает."""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit_driver as KD  # noqa: E402

HEADROOM = 1.25            # запас над замеренным пиком (RAM/VRAM): профиль не впритык


def suggest(summary: dict, prof: dict | None = None) -> list[str]:
    """Строки-рекомендации по итогу пробы. Пик берём из `last_health` (последний /health), `weights_gb_min` — оттуда же. Пусто — расхождений нет или замера нет."""
    wt = summary.get('work_type') or ''
    prof = prof or KD.resource_profile(wt)
    h = (summary.get('last_health') or {}).get('body') or {}
    out: list[str] = []
    gb = prof['memory_mb'] / 1024
    rss = h.get('peak_rss_gb')
    if rss:
        if rss * HEADROOM > gb:
            out.append(f'RAM: пик {rss} ГБ с запасом {HEADROOM} не влезает в {gb:.0f} ГБ профиля → поднять memory_mb до ≥ {int(rss * HEADROOM * 1024)}')
        elif rss * 2 < gb:
            out.append(f'RAM: пик {rss} ГБ, профиль {gb:.0f} ГБ — можно уменьшить до ≈ {int(rss * HEADROOM * 1024)} МБ (дешевле нода; проверить на втором прогоне)')
    else:
        out.append('RAM: пик не пришёл в /health — профиль остаётся «по оценке»')
    vram = h.get('peak_vram_gb')
    if vram is not None:
        exp = (prof.get('expect') or {}).get('peak_vram_gb')
        out.append(f'VRAM: пик {vram} ГБ' + (f' (ожидали {exp})' if exp else '') + f'; карта профиля «{prof["card"]}» — если пик < 12 ГБ, кандидат 16-ГБ карта')
    free = h.get('disk_free_gb')
    if free is not None:
        used = prof['storage_gb'] - free
        out.append(f'диск: свободно {free} ГБ из {prof["storage_gb"]} ГБ профиля (занято ≈ {used:.0f}); {"можно меньше" if free > prof["storage_gb"] * 0.6 else "запас нужен"}')
    mbs = h.get('disk_mb_s')
    if mbs is not None:
        out.append(f'скорость диска ноды: запись {mbs} МБ/с, чтение {h.get("disk_read_mb_s")} МБ/с')
    wgm = h.get('weights_gb_min')
    low = (prof.get('expect') or {}).get('weights_gb_min_min') or KD.DISK_MIN_GB_MIN
    if wgm is not None:
        out.append(f'докачка весов: {wgm} ГБ/мин, нижняя норма сторожа {low}' + (' — НИЖЕ нормы, нода медленная' if wgm < low else ''))
    if summary.get('disk_culls'):
        out.append(f'сторож диска пересаживал {summary["disk_culls"]} раз(а), скорости медленных нод {summary.get("disk_slow_rates")} ГБ/мин')
    jobs = summary.get('jobs') or {}
    jobs = list(jobs.values()) if isinstance(jobs, dict) else list(jobs)                  # kit-драйверы пишут словарь, trellis_trial — список
    done = [v.get('wall_s') or v.get('seconds') for v in jobs if v.get('status') == 'done' and (v.get('wall_s') or v.get('seconds'))]
    exp_job = (prof.get('expect') or {}).get('job_s')
    if done:
        mean = sum(done) / len(done)
        out.append(f'время задания: среднее {mean:.0f} с (n={len(done)})' + (f', ожидали {exp_job} с' if exp_job else ''))
    out.append(f'основание профиля сейчас: {KD.basis_text(prof)}; после правки — basis=measured, measured.date и measured.log = итог этой пробы')
    return out


def main(argv: list[str]) -> int:
    if argv[:1] == ['--list']:
        for wt, p in KD.load_profiles().items():
            print(f'{wt:15} {p["card"]:24} {p["cpu"]} vCPU / {p["memory_mb"] // 1024} ГБ / {p["storage_gb"]} ГБ диск · {p["tier"]}→{p["tier_fallback"]} · {KD.basis_text(p)}')
        return 0
    if len(argv) == 2 and argv[0] == '--show':
        try:
            print(json.dumps(KD.resource_profile(argv[1]), ensure_ascii=False, indent=1))
            return 0
        except KD.ProfileRefused as exc:
            print('ОТКАЗ:', exc)
            return 3
    if len(argv) == 2 and argv[0] == '--suggest':
        try:
            summary = json.load(open(argv[1], encoding='utf-8'))
            for line in suggest(summary):
                print('•', line)
            return 0
        except (OSError, ValueError, KD.ProfileRefused) as exc:
            print('ОТКАЗ:', exc)
            return 3
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
