// КУДА ПОКАЗЫВАЕТ КУРСОР ИЛИ ПАЛЕЦ В ПРОГУЛКЕ (T-20261112-36, владелец TG 1737, 1791). Чистая логика без three.js — гоняется тестами.
//
// Луч из точки экрана задевает по порядку: предмет, окно, стену, пол. Решает БЛИЖАЙШЕЕ попадание: то, что видно под курсором.
// Пол за стеной или за диваном не цель (иначе кольцо «просвечивало» бы сквозь стену в закуток). Равные расстояния (окно и
// штора у стекла, предмет вплотную к полу) — приоритет окно > предмет > пол: окно — отдельное действие «подойти» (T-30),
// предмет — выбор, пол — шаг туда.

export type WalkAimKind = "window" | "item" | "floor" | "none";

/** Расстояния по лучу до первого попадания каждого вида (метры сцены); нет попадания — поле не задано. `block` — стена, дверь,
 *  потолок, предмет, который не выбирается (ТВ над тумбой): закрывает то, что за ним. */
export interface WalkHits {
  window?: number;
  item?: number;
  floor?: number;
  block?: number;
}

/** Допуск «одно и то же место», м: ковёр лежит на полу, рама окна — в толще стены. */
export const AIM_TIE_M = 0.02;

const ORDER: Exclude<WalkAimKind, "none">[] = ["window", "item", "floor"];

export function chooseAim(h: WalkHits, tie = AIM_TIE_M): WalkAimKind {
  const near = Math.min(...ORDER.map((k) => h[k] ?? Infinity));
  if (!Number.isFinite(near)) return "none";
  if (h.block !== undefined && h.block < near - tie) return "none";
  return ORDER.find((k) => h[k] !== undefined && h[k]! <= near + tie) ?? "none";
}
