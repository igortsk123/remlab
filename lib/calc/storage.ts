// Локальное сохранение проекта расчёта в сессии (localStorage), по одному на вид материала.
// Клиент-only: на сервере — no-op. Схема версионируется через contracts (невалидное → сброс).

import { calcProject, type CalcKind, type CalcProject } from "@/contracts/calc";

const KEY_PREFIX = "remlab.calc.v1.";
const key = (kind: CalcKind) => `${KEY_PREFIX}${kind}`;

export function loadProject(kind: CalcKind): CalcProject | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key(kind));
    if (!raw) return null;
    const parsed = calcProject.safeParse(JSON.parse(raw));
    return parsed.success && parsed.data.kind === kind ? parsed.data : null;
  } catch {
    return null;
  }
}

export function saveProject(p: CalcProject): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key(p.kind), JSON.stringify(p));
  } catch {
    // приватный режим / превышена квота — молча пропускаем
  }
}

export function clearProject(kind: CalcKind): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(key(kind));
  } catch {
    // no-op
  }
}
