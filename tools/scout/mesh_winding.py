#!/usr/bin/env python3
"""Согласованность обхода граней и знак объёма сетки (T-20261123-42; мерка этапа 09 `winding`; только numpy).

ЗАЧЕМ. «Знаковая нормаль» (порядок обхода вершин грани) нужна этапам 06 (`tex_visible.back_face_mask`: грань спиной к камере) и 08 (свет, обратные грани). Если сетка
сшита с вывернутыми гранями или вся вывернута наизнанку, эти признаки врут: грань спиной к камере берут за лицевую (или наоборот) и красят не те стороны. Этап 06 в таком случае
молча отключает знаковый признак; здесь — та же проверка как жёсткая мерка этапа 09: «обход согласован + объём наружу».

МЕРКИ (вход — вершины V и грани F как в файле; вершины с одинаковым положением (шов развёртки режет вершины) склеиваются по `weld_eps`):
  consistency      — среди рёбер, общих ровно у двух граней, доля тех, где грани проходят ребро в ПРОТИВОПОЛОЖНЫХ направлениях (у согласованной сетки — 1,0);
  inconsistent_pct — доля несогласованных рёбер среди «парных», %; flipped_faces_pct — доля граней, у которых ≥ 2 парных ребра несогласованы (вывернутые грани);
  nonmanifold_pct / boundary_pct — рёбра у ≥ 3 граней / у одной грани (справочно: не судятся, у тонкой оболочки TRELLIS границы бывают);
  volume_rel       — знаковый объём (сумма a·(b×c)/6 по граням) / объём габаритного ящика: > 0 — нормали наружу, < 0 — сетка вывернута целиком. Не зависит от масштаба.
Пороги — `rules/paint-surface-checks.json#winding`; здесь чисел-порогов нет.
"""
from __future__ import annotations

import numpy as np


def analyze(V: np.ndarray, F: np.ndarray, weld_eps: float = 1e-6) -> dict:
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    out = {'faces': int(len(F)), 'status': 'ok'}
    if len(F) < 4 or len(V) < 4:
        return dict(out, status='na', why='в сетке меньше 4 граней')
    q = np.round(V / max(weld_eps, 1e-12)).astype(np.int64)
    _, vid = np.unique(q, axis=0, return_inverse=True)
    vid = vid.ravel()
    Fv = vid[F]
    keep = ~((Fv[:, 0] == Fv[:, 1]) | (Fv[:, 1] == Fv[:, 2]) | (Fv[:, 2] == Fv[:, 0]))          # вырожденные (после склейки) грани рёбер не дают
    fi = np.nonzero(keep)[0]
    Fv = Fv[keep]
    n = int(vid.max()) + 1
    e = np.concatenate([Fv[:, [0, 1]], Fv[:, [1, 2]], Fv[:, [2, 0]]])
    owner = np.tile(fi, 3)
    key = np.minimum(e[:, 0], e[:, 1]) * n + np.maximum(e[:, 0], e[:, 1])
    fwd = e[:, 0] < e[:, 1]
    o = np.argsort(key, kind='stable')
    ks, fw, ow = key[o], fwd[o], owner[o]
    new = np.ones(len(ks), bool)
    new[1:] = ks[1:] != ks[:-1]
    start = np.nonzero(new)[0]
    cnt = np.diff(np.append(start, len(ks)))
    n_edges = int(len(start))
    pair = start[cnt == 2]
    if not len(pair):
        return dict(out, status='na', why='нет рёбер, общих ровно у двух граней (не замкнутая сетка)', boundary_pct=round(100.0 * float((cnt == 1).mean()), 2))
    bad = fw[pair] == fw[pair + 1]                                           # оба обходят ребро в одну сторону → грани согласованы НЕ были
    cons = 1.0 - float(bad.mean())
    inc = np.zeros(len(F), np.int64)
    np.add.at(inc, ow[pair[bad]], 1)
    np.add.at(inc, ow[pair[bad] + 1], 1)
    P = V[F]
    vol = float(np.einsum('ij,ij->i', P[:, 0], np.cross(P[:, 1], P[:, 2])).sum()) / 6.0
    box = float(np.prod(np.maximum(V.max(0) - V.min(0), 1e-12)))
    out.update(consistency=round(cons, 6), inconsistent_pct=round(100.0 * (1.0 - cons), 4), flipped_faces_pct=round(100.0 * float((inc >= 2).mean()), 4),
               paired_edges=int(len(pair)), nonmanifold_pct=round(100.0 * float((cnt > 2).sum()) / n_edges, 3), boundary_pct=round(100.0 * float((cnt == 1).sum()) / n_edges, 3),
               volume_rel=round(vol / box, 6))
    return out
