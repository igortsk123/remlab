// ПАСПОРТ ОТДЕЛКИ КОМНАТЫ (план demo-04 п.1/п.4): стены, пол, потолок, плинтус — id материала и цвет. Один источник для
// живой сцены (`demo-scene.ts`, `rooms.ts`, `openings.ts`) и серверного кадра (ночная сборка кладёт готовый паспорт в
// `room.finish`, сервер красит clay-поверхности им — `services/planner-solver/planner/scene.py:clay_render`). Значения —
// из карточки квартиры застройщика (`finish`), чего нет — наш набор по умолчанию.

export type FinishSurface = "wall" | "floor" | "ceiling" | "skirting";

export interface Finish {
  id: string;
  colorHex: string;
}

export type FinishPassport = Record<FinishSurface, Finish>;

export const DEFAULT_FINISH: FinishPassport = {
  wall: { id: "paint-white", colorHex: "#f2f0ed" },
  floor: { id: "demo-floor", colorHex: "#dcc7a6" },
  ceiling: { id: "ceiling-white", colorHex: "#f6f5f2" },
  skirting: { id: "skirting-white", colorHex: "#f4f2ee" },
};

/** sRGB-компонента 0..1 → линейная и обратно (как у three: умножение карты на цвет идёт в линейном свете). */
const toLin = (c: number): number => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const toSrgb = (c: number): number => (c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055);

/**
 * Цвет, который надо поставить материалу с НЕЙТРАЛЬНОЙ картой, чтобы поверхность в среднем вышла цвета паспорта: `colorHex`,
 * делённый на среднюю яркость карты (`tintMean`, линейный свет), с отсечкой по каналу. Нет `tintMean` — карта цветная, цвет
 * белый (как раньше: «цвет уже в текстуре»). Один расчёт для браузера (`materials.ts`) и экспорта сцены для Blender.
 */
export function tintHex(m: { colorHex: string; tintMean?: number }): string {
  if (!m.tintMean) return "#ffffff";
  const ch = [1, 3, 5].map((i) => parseInt(m.colorHex.slice(i, i + 2), 16) / 255);
  const out = ch.map((c) => Math.round(Math.min(1, toSrgb(Math.min(1, toLin(c) / m.tintMean!))) * 255));
  return `#${out.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

const HEX = /^#[0-9a-fA-F]{6}$/;
const ID = /^[a-z0-9-]{1,40}$/;

/** Паспорт из карточки поверх набора по умолчанию; неверный цвет или id — значение по умолчанию (молча не красим чужим). */
export function finishPassport(p?: Partial<Record<FinishSurface, Partial<Finish>>> | null): FinishPassport {
  const out = { ...DEFAULT_FINISH };
  for (const k of Object.keys(DEFAULT_FINISH) as FinishSurface[]) {
    const v = p?.[k];
    if (v && typeof v.colorHex === "string" && HEX.test(v.colorHex)) {
      out[k] = { id: typeof v.id === "string" && ID.test(v.id) ? v.id : DEFAULT_FINISH[k].id, colorHex: v.colorHex.toLowerCase() };
    }
  }
  return out;
}
