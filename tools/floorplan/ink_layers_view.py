"""Кадр «лист | маска старая | чуткая | строгая» для проверки слоёв глазами: python -I ink_layers_view.py лист.jpg out.png [старая_маска_из_vetka_fit]
Старая маска — vetka_fit.ink_mask (если рядом лежит vetka_fit.py и ничего не просили иначе). $0."""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ink_layers  # noqa: E402


def paint(base_gray, mask, colour):
    out = cv2.cvtColor((255 - (255 - base_gray) // 4).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    out[mask] = colour
    return out


def label(img, text):
    img = img.copy()
    cv2.rectangle(img, (0, 0), (img.shape[1], 30), (255, 255, 255), -1)
    cv2.putText(img, text, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2, cv2.LINE_AA)
    return img


def main():
    sheet, out = sys.argv[1], sys.argv[2]
    old = None
    if len(sys.argv) > 3:
        sys.path.insert(0, sys.argv[3])
        import vetka_fit as vf
        old = vf.ink_mask(vf.load_gray(sheet))
    sens, strict, pp = ink_layers.layers_of_path(sheet)
    g = cv2.imread(sheet, cv2.IMREAD_GRAYSCALE)
    frames = [label(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), 'лист')]
    if old is not None:
        frames.append(label(paint(g, old, (0, 0, 230)), f'старая {old.mean() * 100:.1f}%'))
    frames.append(label(paint(g, sens, (200, 90, 20)), f'чуткая {sens.mean() * 100:.1f}%'))
    frames.append(label(paint(g, strict, (30, 150, 30)), f'строгая {strict.mean() * 100:.1f}%'))
    sc = 900.0 / max(g.shape)
    frames = [cv2.resize(f, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA) for f in frames]
    cv2.imwrite(out, np.hstack(frames))
    print({k: v for k, v in pp.items() if k != 'steps'}, pp['steps'].get('ops'), pp['steps'].get('local'))


if __name__ == '__main__':
    main()
