"""Каноническая ТВ-геометрия — ОДНА функция на все слои (T6 truth-first, рефери §21).

До этого жили две логики с разным направлением причинности: валидатор выводил диагональ из
ширины тумбы, а промпт генератора считал distance-first (diag ≈ дистанция/1.6, clamp по
тумбе). Здесь — единый канон; его зовут candidates (позиции диван↔ТВ), score (терм
sofa_tv_dist), validate (SOFA_TV_DIST) и viz_final (prompt_brief). Вне канона — только
legacy-фолбэк узкой тумбы (<60 см, area-шкала) и старый DFS-путь solver_run:

  1. viewing distance (диван↔ТВ) — первичен: диагональ = дистанция / PREFERRED_DIAG
     (FOV ≈ 30°, RTINGS/SMPTE);
  2. физический clamp — экран 0.70–0.90 ширины тумбы (стенд на пару дюймов шире экрана);
  3. валидная дистанция — та, под которую СУЩЕСТВУЕТ диагональ, совместимая с тумбой:
     [DIAG_RANGE[0]·d_min, DIAG_RANGE[1]·d_max], где d_min/d_max — диагонали от clamp.

Числа читаются из occupancy.json (canonical), дефолты дублируют канон на случай отсутствия
ключей. Менять пороги — ТОЛЬКО в occupancy.json.
"""
from .clearances import rules

ASPECT_W = 0.872          # доля ширины экрана в диагонали при 16:9


def _cfg():
    r = rules()
    dyn = (r.get("dynamic") or {}).get("sofa_tv_diagonal_clamp", {})
    share = ((r.get("item_share") or {}).get("tv_vs_stand_width_pct") or {}).get("any")
    return {
        "diag_range": (float(dyn.get("min_coeff", 1.2)), float(dyn.get("max_coeff", 2.5))),
        "preferred": float(dyn.get("smpte_hd_coeff", 1.6)),
        "share": (share[0] / 100, share[1] / 100) if share else (0.70, 0.90),
        "soft_coeff": 2.0,
    }


def diag_from_stand(stand_w_cm: float) -> tuple[float, float]:
    """Диапазон диагоналей (см), физически совместимых с тумбой (clamp экран/тумба)."""
    c = _cfg()
    return (stand_w_cm * c["share"][0] / ASPECT_W,
            stand_w_cm * c["share"][1] / ASPECT_W)


def distance_range(stand_w_cm: float, bearer: str = "тв-тумба") -> tuple[float, float, float]:
    """(lo, hi, soft_hi) валидной дистанции диван↔ТВ для данного НОСИТЕЛЯ ТВ.
    Носитель «стенка» (правило владельца 08.08: ТВ всегда в стенке по центру, тумба не
    нужна): экран ограничен не всей шириной стенки, а нишей layout_rules.tv_niche_screen_cm
    (100–160 см) — иначе стенка 300 см дала бы диагональ под 3 метра.
    Существует диагональ в clamp → дистанция в [1.2·d_min, 2.5·d_max]; soft_hi — «далековато»."""
    c = _cfg()
    if bearer == "стенка":
        lr = rules().get("layout_rules", {})
        s_lo, s_hi = lr.get("tv_niche_screen_cm", [100, 160])
        d_min, d_max = s_lo / ASPECT_W, min(s_hi, stand_w_cm * 0.5) / ASPECT_W
    else:
        d_min, d_max = diag_from_stand(stand_w_cm)
    return c["diag_range"][0] * d_min, c["diag_range"][1] * d_max, c["soft_coeff"] * d_max


def distance_target(stand_w_cm: float, bearer: str = "тв-тумба") -> float:
    """П3 (MASTER-tv-sofa-pair): ЦЕЛЕВАЯ дистанция RTINGS mixed usage — 1.6 × диагональ.
    Не вилка и не hard: функция оценки для скоринга пар и позиций (свод владельца §5).
    Диагональ — середина допуска носителя (та же геометрия, что в distance_range)."""
    if bearer == "стенка":
        lr = rules().get("layout_rules", {})
        s_lo, s_hi = lr.get("tv_niche_screen_cm", [100, 160])
        d_min, d_max = s_lo / ASPECT_W, min(s_hi, stand_w_cm * 0.5) / ASPECT_W
    else:
        d_min, d_max = diag_from_stand(stand_w_cm)
    return 1.6 * (d_min + d_max) / 2


def diag_from_distance(distance_cm: float, stand_w_cm: float | None = None) -> float:
    """Distance-first выбор диагонали (генератор): дистанция/PREFERRED, clamp по тумбе."""
    c = _cfg()
    diag = distance_cm / c["preferred"]
    if stand_w_cm:
        d_min, d_max = diag_from_stand(stand_w_cm)
        diag = min(max(diag, d_min), d_max)
    return diag


def prompt_brief() -> str:
    """Фраза для промпта генератора — из тех же чисел, что валидатор (не хардкод)."""
    c = _cfg()
    lo, hi = int(c["share"][0] * 100), int(c["share"][1] * 100)
    return (f"size the TV from the viewing distance (screen diagonal is roughly the "
            f"sofa-to-TV distance divided by {c['preferred']:.1f}), and keep the screen "
            f"{lo}–{hi}% of the TV stand width — never wider than the stand")
