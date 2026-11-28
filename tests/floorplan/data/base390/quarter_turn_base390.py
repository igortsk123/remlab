# КОД 390acfbc8 (база до T-171/круг 6), НЕ ПРАВИТЬ. Копия tools/floorplan/quarter_turn.py: отличие от оригинала — только шапка и переименованные импорты
# (cleanup→cleanup_base390, apartment_cut→apartment_cut_base390, quarter_turn→quarter_turn_base390), чтобы старая и новая функции жили в одном процессе.
# Нужна тесту tests/floorplan/test_deskew_k6flag.py: «флаги выкл = прежнее» сравнивается ПРЯМО, без золота (золото зависело от версии cv2).
"""Поворот листа на четверть оборота (90/180/270°) по ориентации текста (OCR) — Fable otvet-36, круг 6 (T-171/vhod). Шаг входа за флагом FP_CLEAN_QUARTER, по умолчанию ВЫКЛ.

Угол «не по четвертям» (наклон скана 1…30°) — другой шаг (`cleanup.deskew_lines`, по толстым штрихам по модулю 90°: четверть оборота им не видна).
Здесь — только k·90°. Лист читают четырьмя поворотами; побеждает тот, на котором OCR уверенно читает заметно больше текста, чем на исходном.
  k=0 — как есть; k=1 — повернуть на 90° ПО ЧАСОВОЙ; k=2 — 180°; k=3 — 90° ПРОТИВ часовой (cv2.rotate: ROTATE_90_CLOCKWISE / ROTATE_180 / ROTATE_90_COUNTERCLOCKWISE).
Оценка поворота — «уверенно прочитанные символы»: сумма len(текст)·уверенность по строкам OCR с уверенностью ≥ CONF_MIN и длиной ≥ LEN_MIN.
OCR внутрь модуля не зашит: оценщик передаётся вызовом (`scores`: k → оценка), поэтому проверка (−контроль) идёт на подмене и не требует нейросети.
Применяется, только если лучший поворот ≥ GAIN × оценки исходного и ≥ CHARS_MIN символов; иначе — лист не трогаем (причина в info). Ничья/неясность — не трогаем."""
import numpy as np

CONF_MIN = 0.6       # строка OCR считается прочитанной при уверенности не ниже
LEN_MIN = 3          # …и длине не меньше (одиночные цифры и значки не в счёт)
GAIN = 2.0           # лучший поворот читает не меньше, чем в GAIN раз больше исходного
CHARS_MIN = 40       # …и не меньше стольких уверенно прочитанных символов (иначе текста на листе нет — решать нечем)
ROT_NAME = {1: '90° по часовой', 2: '180°', 3: '90° против часовой'}


def chars_score(items):
    """items: [(текст, уверенность[, бокс])] → число уверенно прочитанных символов (взвешено уверенностью)"""
    s = 0.0
    for it in items:
        txt, sc = str(it[0]).strip(), float(it[1])
        if sc >= CONF_MIN and len(txt) >= LEN_MIN:
            s += len(txt) * sc
    return s


def choose(scores):
    """scores: {0: s0, 1: s1, 2: s2, 3: s3} → (k, info). k=0 — не трогаем."""
    s0 = float(scores.get(0, 0.0))
    info = {'scores': {int(k): round(float(v), 1) for k, v in scores.items()}}
    best_k = max((1, 2, 3), key=lambda k: float(scores.get(k, 0.0)))
    best = float(scores.get(best_k, 0.0))
    if best < CHARS_MIN:
        info['reason'] = f'текста мало: лучший поворот читает {best:.0f} символов (< {CHARS_MIN}) — решать нечем'
        return 0, info
    if best < GAIN * max(s0, 1.0):
        info['reason'] = f'исходный лист читается не хуже: {s0:.0f} против {best:.0f} (нужно ×{GAIN:g})'
        return 0, info
    info['k'] = best_k
    info['turn'] = ROT_NAME[best_k]
    return best_k, info


def rotate_k(bgr, k):
    import cv2
    code = {1: cv2.ROTATE_90_CLOCKWISE, 2: cv2.ROTATE_180, 3: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(k)
    return bgr if code is None else cv2.rotate(bgr, code)


def matrix(k, W0, H0):
    """3×3: точка исходного листа (x, y) → точка повёрнутого (для `apartment_cut.source_point`, как у шага deskew); W0×H0 — размер ИСХОДНОГО листа"""
    if k == 1:
        return np.array([[0, -1, H0 - 1], [1, 0, 0], [0, 0, 1]], np.float64)
    if k == 2:
        return np.array([[-1, 0, W0 - 1], [0, -1, H0 - 1], [0, 0, 1]], np.float64)
    if k == 3:
        return np.array([[0, 1, 0], [-1, 0, W0 - 1], [0, 0, 1]], np.float64)
    return np.eye(3)


def quarter_turn(bgr, scorer):
    """scorer(k, img_bgr) → оценка поворота k (для k=0 — исходный лист). → (повёрнутый | None, info). Не применяется — None с причиной."""
    H0, W0 = bgr.shape[:2]
    scores = {k: float(scorer(k, rotate_k(bgr, k))) for k in (0, 1, 2, 3)}
    k, info = choose(scores)
    info['ok'] = False
    if k == 0:
        return None, info
    info['ok'] = True
    info['H'] = matrix(k, W0, H0).tolist()
    return rotate_k(bgr, k), info
