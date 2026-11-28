"""T-171 круг Б-3 4в (rab-10, 28.11): центрирование цели по «плато» профиля. Чистая функция, без cv2/numpy — годится для CI.
Профиль P(o) — доля на чернилах для стены, поставленной на цель и сдвинутой от неё поперёк на o (см). У сплошной линии и у двойной линии БТИ (две линии на расстоянии стенки, допуск чернил ±4 px
накрывает обе) P — «плато» вокруг центра линии/пары. Если цель из walls.csv села не в центр плато (на одну из двух линий, на край полосы) — центр плато и есть ось стены."""


def plateau_center(offs, P, frac=0.75, min_peak=0.30):
    """offs — смещения поперёк (см, по возрастанию, шаг постоянный), P — доли на чернилах. → {'center','lo','hi','peak'} или None.
    Плато = непрерывный участок, содержащий смещение, ближайшее к нулю, где P ≥ frac·max P. None — нет информации: пик < min_peak, цель вне плато,
    плато упирается в край окна (чернила везде — центра нет), либо данных нет."""
    if not offs or len(offs) != len(P):
        return None
    pmax = max(P)
    if pmax < min_peak:
        return None
    thr = frac * pmax
    i0 = min(range(len(offs)), key=lambda i: abs(offs[i]))
    if P[i0] < thr:
        return None
    lo = hi = i0
    while lo > 0 and P[lo - 1] >= thr:
        lo -= 1
    while hi < len(offs) - 1 and P[hi + 1] >= thr:
        hi += 1
    if lo == 0 or hi == len(offs) - 1:
        return None
    return {'center': (offs[lo] + offs[hi]) / 2.0, 'lo': offs[lo], 'hi': offs[hi], 'peak': pmax}
